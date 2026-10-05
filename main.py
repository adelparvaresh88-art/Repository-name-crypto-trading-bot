import os
import time
import hmac
import hashlib
import json
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlencode

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.61-FAST-TRADES
# TABDEAL SPOT
#
# FIX:
#   V40.2.60 used /klines -> HTTP 404
#
# NEW:
#   /r/api/v1/trades
#   REAL TRADES -> 5m CANDLES
#
# STRATEGY:
#   REAL BOS
#   NEAR BOS
#   PULLBACK
#   CLOSED CANDLE
#   STRONG CLOSE
#   MOMENTUM
#
# EMA: OFF
# ============================================================

VERSION = "V40.2.61-FAST-TRADES"

BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 12
RECV_WINDOW = 5000

# ------------------------------------------------------------
# SCAN SETTINGS
# ------------------------------------------------------------

SCAN_UNIVERSE = int(os.getenv("SCAN_UNIVERSE", "80"))

TRADE_LIMIT = 1000

# حداقل کندل‌های بسته‌شده مورد نیاز
MIN_CANDLES = int(os.getenv("MIN_CANDLES", "8"))

# تعداد worker برای سرعت بیشتر
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))

# ------------------------------------------------------------
# STRATEGY SETTINGS
# ------------------------------------------------------------

REAL_BOS_MIN = Decimal("0.0002")       # 0.02%
NEAR_BOS_MIN = Decimal("-0.0050")      # -0.50%

PULLBACK_TOLERANCE = Decimal("0.0120")  # 1.20%

CHASE_LIMIT = Decimal("0.0300")         # 3%

MIN_CONFIRM_CLOSE_POSITION = Decimal("0.50")

MIN_SCORE = Decimal("9")

# ------------------------------------------------------------
# ORDER
# ------------------------------------------------------------

ORDER_VALUE = Decimal(os.getenv("ORDER_QTY", "2"))

LIVE_TRADING = os.getenv(
    "LIVE_TRADING",
    "false"
).strip().lower() in (
    "1",
    "true",
    "yes",
    "on"
)

# ------------------------------------------------------------
# API KEYS
# ------------------------------------------------------------

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_API_KEY")
    or ""
).strip()

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDEAL_API_SECRET")
    or ""
).strip()

# بعضی تنظیمات قبلی ممکن است SECRET را با نام SECRET داشته باشند
if not API_SECRET:
    API_SECRET = (
        os.getenv("TABDIL_SECRET")
        or os.getenv("TABDEAL_SECRET")
        or ""
    ).strip()

# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

session = requests.Session()

SERVER_TIME_OFFSET = 0

ERRORS = []
TRADE_OK = 0
TRADE_ERROR = 0


# ============================================================
# TIME
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def now_ms():
    return int(time.time() * 1000) + SERVER_TIME_OFFSET


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TG_TOKEN or not TG_CHAT_ID:
        print(message)
        return

    try:
        url = (
            f"https://api.telegram.org/bot"
            f"{TG_TOKEN}/sendMessage"
        )

        payload = {
            "chat_id": TG_CHAT_ID,
            "text": message,
        }

        r = requests.post(
            url,
            json=payload,
            timeout=10
        )

        if r.status_code != 200:
            print(
                "TELEGRAM ERROR:",
                r.status_code,
                r.text[:300]
            )

    except Exception as e:
        print("TELEGRAM EXCEPTION:", e)


# ============================================================
# PUBLIC GET
# ============================================================

def public_get(path, params=None):
    url = f"{BASE}{path}"

    r = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT
    )

    if r.status_code != 200:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:500]}"
        )

    try:
        return r.json()
    except Exception:
        raise RuntimeError(
            f"INVALID JSON: {r.text[:500]}"
        )


# ============================================================
# SERVER TIME
# ============================================================

def sync_server_time():

    global SERVER_TIME_OFFSET

    try:

        data = public_get(
            f"{API_ROOT}/time"
        )

        server_time = (
            data.get("serverTime")
            or data.get("time")
        )

        if server_time is None:
            raise RuntimeError(
                f"Unexpected time response: {data}"
            )

        local = int(time.time() * 1000)

        SERVER_TIME_OFFSET = (
            int(server_time) - local
        )

        print(
            f"🕐 SERVER OFFSET: "
            f"{SERVER_TIME_OFFSET} ms"
        )

        return True

    except Exception as e:

        print(
            "⚠️ SERVER TIME ERROR:",
            e
        )

        return False


# ============================================================
# SIGNATURE
# ============================================================

def sign_params(params):

    query = urlencode(params)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    return signature


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None
):

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "API KEY / SECRET MISSING"
        )

    params = dict(params or {})

    params["timestamp"] = now_ms()
    params["recvWindow"] = RECV_WINDOW

    params["signature"] = sign_params(
        params
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = f"{BASE}{path}"

    method = method.upper()

    if method == "GET":

        r = session.get(
            url,
            params=params,
            headers=headers,
            timeout=TIMEOUT
        )

    elif method == "POST":

        r = session.post(
            url,
            params=params,
            headers=headers,
            timeout=TIMEOUT
        )

    elif method == "DELETE":

        r = session.delete(
            url,
            params=params,
            headers=headers,
            timeout=TIMEOUT
        )

    else:

        raise RuntimeError(
            f"Unsupported method: {method}"
        )

    if r.status_code != 200:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:700]}"
        )

    try:
        return r.json()

    except Exception:

        raise RuntimeError(
            f"INVALID JSON: {r.text[:500]}"
        )


# ============================================================
# AUTH CHECK
# ============================================================

def auth_check():

    print("🔐 AUTH CHECK")

    try:

        data = signed_request(
            "GET",
            f"{API_ROOT}/account"
        )

        can_trade = data.get(
            "canTrade",
            False
        )

        print(
            f"✅ AUTH SUCCESS | "
            f"canTrade={can_trade}"
        )

        return True

    except Exception as e:

        print(
            "🚨 AUTH FAILED:",
            e
        )

        telegram(
            "🚨 ATI AUTH FAILED\n\n"
            f"{e}"
        )

        return False


# ============================================================
# MARKETS
# ============================================================

def get_markets():

    data = public_get(
        f"{API_ROOT}/exchangeInfo"
    )

    if isinstance(data, dict):

        markets = (
            data.get("symbols")
            or data.get("markets")
            or data.get("data")
            or []
        )

    else:

        markets = data

    result = []

    for m in markets:

        if not isinstance(m, dict):
            continue

        symbol = str(
            m.get("symbol")
            or ""
        ).upper()

        status = str(
            m.get("status")
            or ""
        ).upper()

        quote = str(
            m.get("quoteAsset")
            or ""
        ).upper()

        if not symbol:
            continue

        # فقط USDT
        if not (
            symbol.endswith("USDT")
            or quote == "USDT"
        ):
            continue

        if status and status != "TRADING":
            continue

        result.append(m)

    # حذف تکراری
    unique = {}

    for m in result:

        symbol = str(
            m.get("symbol")
            or ""
        ).upper()

        unique[symbol] = m

    markets = list(unique.values())

    # اول بازارهایی که USDT هستند
    markets.sort(
        key=lambda x: str(
            x.get("symbol", "")
        )
    )

    return markets[:SCAN_UNIVERSE]


# ============================================================
# SYMBOL FORMAT
# ============================================================

def get_trade_symbol(market):

    symbol = str(
        market.get("symbol")
        or ""
    ).strip()

    tabdeal_symbol = str(
        market.get("tabdealSymbol")
        or ""
    ).strip()

    # برای trades هر دو قابل قبول‌اند.
    # اول symbol استاندارد را امتحان می‌کنیم.
    if symbol:
        return symbol

    return tabdeal_symbol


# ============================================================
# FETCH RECENT TRADES
# ============================================================

def get_trades(market):

    symbol = get_trade_symbol(market)

    if not symbol:
        raise RuntimeError(
            "EMPTY SYMBOL"
        )

    data = public_get(
        f"{API_ROOT}/trades",
        {
            "symbol": symbol,
            "limit": TRADE_LIMIT
        }
    )

    if isinstance(data, dict):

        data = (
            data.get("data")
            or data.get("trades")
            or data.get("results")
            or []
        )

    if not isinstance(data, list):
        raise RuntimeError(
            f"Unexpected trades response: "
            f"{str(data)[:300]}"
        )

    return data


# ============================================================
# DECIMAL SAFE
# ============================================================

def D(value):

    try:
        return Decimal(str(value))

    except (
        InvalidOperation,
        ValueError,
        TypeError
    ):
        return Decimal("0")


# ============================================================
# TRADES -> 5M CANDLES
# ============================================================

def trades_to_5m(trades):

    buckets = {}

    for t in trades:

        if not isinstance(t, dict):
            continue

        price = D(
            t.get("price")
        )

        qty = D(
            t.get("qty")
        )

        timestamp = t.get("time")

        if price <= 0:
            continue

        if qty < 0:
            qty = Decimal("0")

        if timestamp is None:
            continue

        try:
            timestamp = int(timestamp)
        except Exception:
            continue

        # 5 دقیقه = 300000 ms
        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
                "trades": 1,
            }

        else:

            c = buckets[bucket]

            c["high"] = max(
                c["high"],
                price
            )

            c["low"] = min(
                c["low"],
                price
            )

            c["close"] = price

            c["volume"] += qty

            c["trades"] += 1

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    # آخرین bucket ممکن است هنوز بسته نشده باشد.
    if len(candles) >= 2:

        current_bucket = (
            (int(time.time() * 1000))
            // 300000
        ) * 300000

        if candles[-1]["time"] == current_bucket:

            candles = candles[:-1]

    return candles


# ============================================================
# MARKET DATA WORKER
# ============================================================

def scan_market(market):

    global TRADE_OK
    global TRADE_ERROR

    symbol = get_trade_symbol(
        market
    )

    try:

        trades = get_trades(
            market
        )

        candles = trades_to_5m(
            trades
        )

        if len(candles) < MIN_CANDLES:

            return {
                "ok": False,
                "symbol": symbol,
                "reason": (
                    f"ONLY {len(candles)} "
                    f"CLOSED 5M CANDLES"
                ),
                "candles": candles,
            }

        TRADE_OK += 1

        return {
            "ok": True,
            "symbol": symbol,
            "candles": candles,
        }

    except Exception as e:

        TRADE_ERROR += 1

        return {
            "ok": False,
            "symbol": symbol,
            "reason": str(e),
            "candles": [],
        }


# ============================================================
# PRICE ACTION ENGINE
# ============================================================

def analyze(symbol, candles):

    if len(candles) < MIN_CANDLES:
        return None

    # آخرین کندل بسته
    c = candles[-1]

    # قبل از آن
    p = candles[-2]

    # چند کندل قبلی برای ساختار
    lookback = candles[
        max(0, len(candles) - 8):-2
    ]

    if len(lookback) < 3:
        return None

    recent_high = max(
        x["high"]
        for x in lookback
    )

    recent_low = min(
        x["low"]
        for x in lookback
    )

    close = c["close"]
    open_ = c["open"]
    high = c["high"]
    low = c["low"]

    prev_close = p["close"]

    if close <= 0:
        return None

    candle_range = high - low

    if candle_range <= 0:
        return None

    body = abs(
        close - open_
    )

    close_position = (
        close - low
    ) / candle_range

    move_from_high = (
        close - recent_high
    ) / recent_high

    # --------------------------------------------------------
    # BOS
    # --------------------------------------------------------

    real_bos = (
        close > recent_high
        and move_from_high >= REAL_BOS_MIN
    )

    near_bos = (
        move_from_high >= NEAR_BOS_MIN
        and close >= recent_high * Decimal("0.995")
    )

    # --------------------------------------------------------
    # BULLISH CANDLE
    # --------------------------------------------------------

    bullish = close > open_

    strong_close = (
        close_position
        >= MIN_CONFIRM_CLOSE_POSITION
    )

    body_ratio = (
        body / candle_range
    )

    strong_body = (
        body_ratio >= Decimal("0.35")
    )

    # --------------------------------------------------------
    # PULLBACK / RECLAIM
    # --------------------------------------------------------

    pullback_distance = (
        abs(close - recent_high)
        / recent_high
    )

    pullback_ok = (
        pullback_distance
        <= PULLBACK_TOLERANCE
    )

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    momentum = (
        close > prev_close
    )

    # --------------------------------------------------------
    # CHASE PROTECTION
    # --------------------------------------------------------

    chase = (
        (close - recent_low)
        / recent_low
    )

    if chase > CHASE_LIMIT:
        return None

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = Decimal("0")

    setup = []

    if real_bos:

        score += Decimal("5")
        setup.append(
            "REAL-BOS"
        )

    elif near_bos:

        score += Decimal("3")
        setup.append(
            "NEAR-BOS"
        )

    else:

        # بدون BOS نزدیک، سیگنال نمی‌سازیم
        return None

    if bullish:

        score += Decimal("2")

    if strong_close:

        score += Decimal("2")

    if strong_body:

        score += Decimal("1")

    if momentum:

        score += Decimal("1")

    if pullback_ok:

        score += Decimal("2")
        setup.append(
            "PULLBACK"
        )

    if score < MIN_SCORE:
        return None

    return {
        "symbol": symbol,
        "score": score,
        "price": close,
        "high": high,
        "low": low,
        "setup": " → ".join(setup),
        "close_position": close_position,
        "body_ratio": body_ratio,
        "candles": len(candles),
    }


# ============================================================
# RANK CANDIDATES
# ============================================================

def rank_candidates(results):

    candidates = []

    for result in results:

        if not result.get("ok"):
            continue

        symbol = result["symbol"]
        candles = result["candles"]

        try:

            signal = analyze(
                symbol,
                candles
            )

            if signal:
                candidates.append(
                    signal
                )

        except Exception as e:

            print(
                f"ANALYZE ERROR "
                f"{symbol}: {e}"
            )

    candidates.sort(
        key=lambda x: (
            x["score"],
            x["close_position"],
            x["body_ratio"],
        ),
        reverse=True
    )

    return candidates


# ============================================================
# ORDER QUANTITY
# ============================================================

def get_symbol_filters(market):

    filters = (
        market.get("filters")
        or []
    )

    min_qty = Decimal("0")
    step_size = Decimal("0")
    min_notional = Decimal("0")

    for f in filters:

        if not isinstance(f, dict):
            continue

        ftype = str(
            f.get("filterType")
            or ""
        ).upper()

        if ftype in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE"
        ):

            min_qty = max(
                min_qty,
                D(f.get("minQty"))
            )

            if D(
                f.get("stepSize")
            ) > 0:

                step_size = D(
                    f.get("stepSize")
                )

        if ftype in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            min_notional = max(
                min_notional,
                D(
                    f.get("minNotional")
                    or f.get("notional")
                )
            )

    return (
        min_qty,
        step_size,
        min_notional
    )


def calculate_quantity(
    market,
    price
):

    if price <= 0:
        return Decimal("0")

    min_qty, step, min_notional = (
        get_symbol_filters(market)
    )

    qty = (
        ORDER_VALUE / price
    )

    if step > 0:

        qty = (
            qty / step
        ).to_integral_value(
            rounding=ROUND_DOWN
        ) * step

    if min_qty > 0 and qty < min_qty:

        qty = min_qty

    if (
        min_notional > 0
        and qty * price < min_notional
    ):

        required = (
            min_notional / price
        )

        if step > 0:

            qty = (
                required / step
            ).to_integral_value(
                rounding=ROUND_DOWN
            ) * step

            if qty * price < min_notional:
                qty += step

        else:
            qty = required

    return qty


# ============================================================
# REAL BUY
# ============================================================

def real_buy(
    market,
    signal
):

    symbol = get_trade_symbol(
        market
    )

    price = D(
        signal["price"]
    )

    quantity = calculate_quantity(
        market,
        price
    )

    if quantity <= 0:

        raise RuntimeError(
            "CALCULATED QUANTITY <= 0"
        )

    print(
        f"💰 REAL BUY PREP\n"
        f"SYMBOL: {symbol}\n"
        f"PRICE: {price}\n"
        f"QTY: {quantity}\n"
        f"VALUE: {quantity * price}"
    )

    if not LIVE_TRADING:

        print(
            "🛑 LIVE_TRADING=false "
            "→ NO REAL ORDER"
        )

        return {
            "paper": True,
            "symbol": symbol,
            "quantity": str(quantity),
            "price": str(price),
        }

    params = {
        "symbol": symbol,
        "side": "BUY",
        "type": "MARKET",
        "quantity": format(
            quantity,
            "f"
        ),
    }

    result = signed_request(
        "POST",
        f"{ORDER_ROOT}/order",
        params
    )

    return result


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(signal):

    return (
        "🎯 ATI BUY SIGNAL\n\n"
        f"🪙 {signal['symbol']}\n"
        f"💵 PRICE: {signal['price']}\n"
        f"⭐ SCORE: {signal['score']}\n"
        f"🧠 {signal['setup']}\n"
        f"🕯 CLOSED 5M: {signal['candles']}\n"
        f"📊 CLOSE POSITION: "
        f"{signal['close_position'] * 100:.1f}%\n"
        f"💪 BODY: "
        f"{signal['body_ratio'] * 100:.1f}%\n"
        f"🕐 {now_utc()}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    global TRADE_OK
    global TRADE_ERROR

    TRADE_OK = 0
    TRADE_ERROR = 0

    print("=" * 60)
    print(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )
    print(
        "🧠 REAL TRADES → 5M CANDLES"
    )
    print(
        "📐 BOS → PULLBACK → "
        "CLOSED CONFIRM"
    )
    print(
        "🚫 EMA: OFF"
    )
    print(
        f"🔓 LIVE TRADING: "
        f"{LIVE_TRADING}"
    )
    print(
        f"💵 ORDER VALUE: "
        f"{ORDER_VALUE} USDT"
    )
    print(
        f"📊 SCAN UNIVERSE: "
        f"{SCAN_UNIVERSE}"
    )
    print(
        f"🕐 {now_utc()}"
    )
    print("=" * 60)

    telegram(
        "💓 ATI ALIVE\n"
        f"⚡ {VERSION}\n"
        "📡 REAL TRADES DATA\n"
        f"🔓 LIVE TRADING: "
        f"{LIVE_TRADING}\n"
        f"🕐 {now_utc()}"
    )

    # --------------------------------------------------------
    # TIME
    # --------------------------------------------------------

    sync_server_time()

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    if LIVE_TRADING:

        if not auth_check():

            print(
                "🛑 AUTH FAILED "
                "→ STOP"
            )

            return

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    try:

        markets = get_markets()

    except Exception as e:

        print(
            "🚨 MARKET ERROR:",
            e
        )

        telegram(
            "🚨 ATI MARKET ERROR\n\n"
            f"{e}"
        )

        return

    print(
        f"📊 MARKETS: {len(markets)}"
    )

    if not markets:

        telegram(
            "🚨 ATI\n"
            "NO USDT MARKETS"
        )

        return

    # --------------------------------------------------------
    # FAST TRADE SCAN
    # --------------------------------------------------------

    print(
        "🔎 FAST TRADES SCAN STARTING"
    )

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                scan_market,
                market
            ): market
            for market in markets
        }

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                results.append(
                    result
                )

                if result["ok"]:

                    print(
                        f"✅ "
                        f"{result['symbol']} "
                        f"| "
                        f"{len(result['candles'])} "
                        f"closed 5m"
                    )

                else:

                    print(
                        f"⏭ "
                        f"{result['symbol']} "
                        f"| "
                        f"{result['reason']}"
                    )

            except Exception as e:

                print(
                    "WORKER ERROR:",
                    e
                )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    print("=" * 60)

    print(
        f"📡 DATA SCAN FINISHED"
    )

    print(
        f"✅ TRADE DATA OK: "
        f"{TRADE_OK}"
    )

    print(
        f"❌ TRADE DATA ERROR: "
        f"{TRADE_ERROR}"
    )

    # --------------------------------------------------------
    # SIGNALS
    # --------------------------------------------------------

    candidates = rank_candidates(
        results
    )

    print(
        f"🎯 CANDIDATES: "
        f"{len(candidates)}"
    )

    if not candidates:

        message = (
            "📡 ATI SCAN FINISHED\n\n"
            f"⚡ {VERSION}\n"
            f"📊 MARKETS: {len(markets)}\n"
            f"✅ DATA OK: {TRADE_OK}\n"
            f"❌ DATA ERROR: {TRADE_ERROR}\n"
            "🎯 BUY CANDIDATES: 0\n\n"
            "🔒 NO BUY\n"
            f"🕐 {now_utc()}"
        )

        print(message)
        telegram(message)

        return

    # --------------------------------------------------------
    # BEST SIGNAL ONLY
    # --------------------------------------------------------

    best = candidates[0]

    print(
        "\n" + format_signal(best)
    )

    telegram(
        format_signal(best)
    )

    # --------------------------------------------------------
    # FIND MARKET
    # --------------------------------------------------------

    market = None

    for m in markets:

        if (
            get_trade_symbol(m)
            == best["symbol"]
        ):

            market = m
            break

    if market is None:

        telegram(
            "🚨 ATI ERROR\n"
            "MARKET OBJECT NOT FOUND"
        )

        return

    # --------------------------------------------------------
    # REAL BUY
    # --------------------------------------------------------

    if LIVE_TRADING:

        try:

            telegram(
                "🔓 REAL BUY STARTING\n\n"
                f"🪙 {best['symbol']}\n"
                f"💵 {best['price']}\n"
                f"⭐ SCORE {best['score']}\n"
                f"🕐 {now_utc()}"
            )

            order = real_buy(
                market,
                best
            )

            print(
                "✅ ORDER RESPONSE:"
            )

            print(
                json.dumps(
                    order,
                    indent=2,
                    ensure_ascii=False
                )
            )

            telegram(
                "✅ REAL BUY SENT\n\n"
                f"🪙 {best['symbol']}\n"
                f"💵 PRICE: {best['price']}\n"
                f"⭐ SCORE: {best['score']}\n"
                f"📦 ORDER:\n"
                f"{str(order)[:2500]}\n"
                f"🕐 {now_utc()}"
            )

        except Exception as e:

            print(
                "🚨 REAL BUY ERROR:",
                e
            )

            telegram(
                "🚨 REAL BUY ERROR\n\n"
                f"🪙 {best['symbol']}\n"
                f"❌ {e}\n"
                f"🕐 {now_utc()}"
            )

    else:

        print(
            "🛑 REAL ORDER NOT SENT"
        )

        telegram(
            "🛑 SIGNAL ONLY\n\n"
            f"🪙 {best['symbol']}\n"
            f"💵 {best['price']}\n"
            f"⭐ SCORE {best['score']}\n"
            "LIVE_TRADING=false"
        )

    print(
        "\n✅ ATI RUN COMPLETED"
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "🛑 STOPPED"
        )

    except Exception as e:

        print(
            "🚨 FATAL ERROR:",
            e
        )

        telegram(
            "🚨 ATI FATAL ERROR\n\n"
            f"{e}"
        )
