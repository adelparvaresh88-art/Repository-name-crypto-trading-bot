import os
import time
import json
import hmac
import hashlib
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.53-REAL
# TABDEAL SPOT
# TELEGRAM + RETRY + TIMEOUT SAFE
# ============================================================

VERSION = "V40.2.53-REAL"

BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 15
RECV_WINDOW = 5000

SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", "40"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "12"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "11"))

ORDER_USDT = Decimal(os.getenv("ORDER_USDT", "2"))

LIVE_TRADING = os.getenv("LIVE_TRADING", "true").lower() in (
    "1",
    "true",
    "yes",
    "on",
)

BUY_LOCK = False
MAX_REAL_BUYS_PER_RUN = 1


# ============================================================
# API KEYS
# ============================================================

TABDIL_API_KEY = os.getenv("TABDIL_API_KEY", "").strip()
TABDIL_API_SECRET = os.getenv("TABDIL_API_SECRET", "").strip()

TABDEAL_API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
TABDEAL_API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

if TABDIL_API_KEY and TABDIL_API_SECRET:
    API_KEY = TABDIL_API_KEY
    API_SECRET = TABDIL_API_SECRET
    AUTH_PAIR = "TABDIL"
elif TABDEAL_API_KEY and TABDEAL_API_SECRET:
    API_KEY = TABDEAL_API_KEY
    API_SECRET = TABDEAL_API_SECRET
    AUTH_PAIR = "TABDEAL"
else:
    API_KEY = ""
    API_SECRET = ""
    AUTH_PAIR = "NONE"


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()


def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def telegram(message, retries=3):
    """
    Reliable Telegram sender.

    Every attempt is printed.
    Successful delivery prints TELEGRAM SENT.
    """

    print(message, flush=True)

    if not TELEGRAM_BOT_TOKEN:
        print(
            "❌ TELEGRAM_BOT_TOKEN missing",
            flush=True
        )
        return False

    if not TELEGRAM_CHAT_ID:
        print(
            "❌ TELEGRAM_CHAT_ID missing",
            flush=True
        )
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": "true",
    }

    for attempt in range(1, retries + 1):

        try:
            response = requests.post(
                url,
                data=payload,
                timeout=10,
            )

            print(
                f"📨 TELEGRAM ATTEMPT {attempt}/"
                f"{retries} → HTTP {response.status_code}",
                flush=True,
            )

            if response.status_code != 200:
                print(
                    f"⚠️ Telegram HTTP ERROR: "
                    f"{response.text[:500]}",
                    flush=True,
                )

                if attempt < retries:
                    time.sleep(2)
                    continue

                return False

            try:
                data = response.json()
            except Exception:
                data = {}

            if data.get("ok") is True:
                print(
                    "✅ TELEGRAM SENT",
                    flush=True,
                )
                return True

            print(
                f"❌ Telegram rejected: {data}",
                flush=True,
            )

            if attempt < retries:
                time.sleep(2)
                continue

            return False

        except Exception as e:
            print(
                f"⚠️ Telegram ERROR attempt "
                f"{attempt}/{retries}: {e}",
                flush=True,
            )

            if attempt < retries:
                time.sleep(2)
                continue

    return False


# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()

if API_KEY:
    SESSION.headers.update({
        "X-MBX-APIKEY": API_KEY,
        "User-Agent": "ATI-Crypto-Bot/40.2.53",
    })


def public_get(path, params=None, retries=2):
    url = f"{API_ROOT}{path}"

    last_error = None

    for attempt in range(1, retries + 1):

        try:
            response = SESSION.get(
                url,
                params=params or {},
                timeout=TIMEOUT,
            )

            response.raise_for_status()
            return response.json()

        except Exception as e:
            last_error = e

            print(
                f"⚠️ PUBLIC GET ERROR "
                f"{path} "
                f"attempt={attempt}/{retries}: {e}",
                flush=True,
            )

            if attempt < retries:
                time.sleep(1)

    raise last_error


# ============================================================
# SIGNED REQUEST
# ============================================================

def server_time():
    try:
        data = public_get("/time", retries=2)
        return int(data["serverTime"])
    except Exception:
        return int(time.time() * 1000)


def signed_params(params=None):
    params = dict(params or {})

    params["timestamp"] = server_time()
    params["recvWindow"] = RECV_WINDOW

    query = "&".join(
        f"{k}={params[k]}"
        for k in sorted(params)
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    return params


def signed_get(path, params=None, retries=2):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("API credentials missing")

    url = f"{API_ROOT}{path}"

    last_error = None

    for attempt in range(1, retries + 1):

        try:
            params2 = signed_params(params)

            response = SESSION.get(
                url,
                params=params2,
                timeout=TIMEOUT,
            )

            response.raise_for_status()
            return response.json()

        except Exception as e:
            last_error = e

            print(
                f"⚠️ SIGNED GET ERROR "
                f"{path} "
                f"attempt={attempt}/{retries}: {e}",
                flush=True,
            )

            if attempt < retries:
                time.sleep(1)

    raise last_error


def signed_post(path, params=None, retries=2):
    if not API_KEY or not API_SECRET:
        raise RuntimeError("API credentials missing")

    url = f"{ORDER_ROOT}{path}"

    last_error = None

    for attempt in range(1, retries + 1):

        try:
            params2 = signed_params(params)

            response = SESSION.post(
                url,
                params=params2,
                timeout=TIMEOUT,
            )

            response.raise_for_status()
            return response.json()

        except Exception as e:
            last_error = e

            print(
                f"⚠️ SIGNED POST ERROR "
                f"{path} "
                f"attempt={attempt}/{retries}: {e}",
                flush=True,
            )

            if attempt < retries:
                time.sleep(1)

    raise last_error


# ============================================================
# AUTH TEST
# ============================================================

def auth_test():

    telegram(
        "🔐 ATI AUTH TEST\n"
        f"🔑 PAIR: {AUTH_PAIR}\n"
        f"🕐 {utc_now()}"
    )

    try:
        data = signed_get("/account")

        can_trade = data.get("canTrade", False)

        usdt_free = Decimal("0")

        for balance in data.get("balances", []):
            if balance.get("asset") == "USDT":
                try:
                    usdt_free = Decimal(
                        str(balance.get("free", "0"))
                    )
                except Exception:
                    usdt_free = Decimal("0")

        telegram(
            "✅ AUTH SUCCESS\n"
            f"🔑 PAIR: {AUTH_PAIR}\n"
            f"🔓 canTrade={can_trade}\n"
            f"💰 FREE USDT: {usdt_free}\n"
            f"🕐 {utc_now()}"
        )

        return data

    except Exception as e:

        telegram(
            "❌ AUTH FAILED\n"
            f"🔑 PAIR: {AUTH_PAIR}\n"
            f"⚠️ {str(e)[:500]}\n"
            f"🕐 {utc_now()}"
        )

        return None


# ============================================================
# MARKET INFO
# ============================================================

def get_markets():

    data = public_get(
        "/exchangeInfo",
        retries=3,
    )

    symbols = []

    if isinstance(data, dict):
        raw = data.get("symbols", [])

        if isinstance(raw, list):
            symbols = raw

    elif isinstance(data, list):
        symbols = data

    result = []

    for item in symbols:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("market")
            or ""
        ).upper()

        status = str(
            item.get("status", "TRADING")
        ).upper()

        if not symbol:
            continue

        if status not in ("TRADING", "ENABLED", "ACTIVE"):
            continue

        # Only USDT spot pairs
        if not symbol.endswith("USDT"):
            continue

        if symbol.endswith(
            (
                "USDCUSDT",
                "FDUSDUSDT",
                "TUSDUSDT",
                "DAIUSDT",
            )
        ):
            continue

        result.append(item)

    # Remove duplicates
    unique = {}

    for item in result:
        symbol = str(
            item.get("symbol", "")
        ).upper()

        if symbol:
            unique[symbol] = item

    markets = list(unique.values())

    print(
        f"📊 USDT MARKETS: {len(markets)}",
        flush=True,
    )

    return markets


# ============================================================
# MARKET FILTERS
# ============================================================

def get_filter(market, filter_type):

    for f in market.get("filters", []):

        if str(
            f.get("filterType", "")
        ).upper() == filter_type.upper():

            return f

    return {}


def decimal_or_zero(value):

    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def floor_decimal(value, step):

    value = Decimal(value)
    step = Decimal(step)

    if step <= 0:
        return value

    return (
        value / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


def decimal_string(value):

    text = format(
        Decimal(value),
        "f"
    )

    text = text.rstrip("0").rstrip(".")

    if text in ("", "-0"):
        return "0"

    return text


# ============================================================
# TRADE → 5M CANDLES
# ============================================================

def fetch_trades(symbol):

    try:

        data = public_get(
            "/trades",
            {
                "symbol": symbol,
                "limit": 1000,
            },
            retries=2,
        )

        if not isinstance(data, list):
            return []

        return data

    except Exception as e:

        print(
            f"⚠️ Trade fetch error "
            f"{symbol}: {e}",
            flush=True,
        )

        return []


def build_5m_candles(trades):

    buckets = {}

    for trade in trades:

        try:
            price = Decimal(
                str(trade["price"])
            )

            qty = Decimal(
                str(
                    trade.get(
                        "qty",
                        "0"
                    )
                )
            )

            ts = int(
                trade.get("time", 0)
            )

            if price <= 0 or ts <= 0:
                continue

            bucket = (
                ts // 300000
            ) * 300000

            if bucket not in buckets:

                buckets[bucket] = {
                    "time": bucket,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price,
                    "volume": qty,
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

        except Exception:
            continue

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    # Last bucket can still be open.
    # Remove it so only CLOSED 5m candles remain.
    if candles:

        current_bucket = (
            int(time.time() * 1000)
            // 300000
        ) * 300000

        candles = [
            c for c in candles
            if c["time"] < current_bucket
        ]

    return candles


# ============================================================
# PRICE ACTION HELPERS
# ============================================================

def body(c):
    return abs(
        c["close"] - c["open"]
    )


def candle_range(c):
    return max(
        c["high"] - c["low"],
        Decimal("0")
    )


def bullish(c):
    return c["close"] > c["open"]


def strong_bull(c):

    r = candle_range(c)

    if r <= 0:
        return False

    return (
        bullish(c)
        and body(c) / r >= Decimal("0.45")
    )


def find_recent_swing_high(candles, start, end):

    start = max(2, start)
    end = min(
        len(candles) - 2,
        end
    )

    best = None

    for i in range(start, end + 1):

        if (
            candles[i]["high"]
            > candles[i - 1]["high"]
            and
            candles[i]["high"]
            >= candles[i + 1]["high"]
        ):
            best = i

    return best


def find_recent_swing_low(candles, start, end):

    start = max(2, start)
    end = min(
        len(candles) - 2,
        end
    )

    best = None

    for i in range(start, end + 1):

        if (
            candles[i]["low"]
            < candles[i - 1]["low"]
            and
            candles[i]["low"]
            <= candles[i + 1]["low"]
        ):
            best = i

    return best


# ============================================================
# SIGNAL ENGINE
# ============================================================

def analyze_market(market):

    symbol = str(
        market.get("symbol", "")
    ).upper()

    if not symbol:
        return None

    trades = fetch_trades(symbol)

    if len(trades) < 30:
        return None

    candles = build_5m_candles(trades)

    if len(candles) < 30:
        return None

    # Use last closed candle
    last = candles[-1]

    # Previous section
    prev = candles[:-1]

    # Recent swing high / low
    hi_idx = find_recent_swing_high(
        prev,
        max(2, len(prev) - 18),
        len(prev) - 3,
    )

    lo_idx = find_recent_swing_low(
        prev,
        max(2, len(prev) - 18),
        len(prev) - 3,
    )

    if hi_idx is None or lo_idx is None:
        return None

    swing_high = prev[hi_idx]["high"]
    swing_low = prev[lo_idx]["low"]

    close = last["close"]
    low = last["low"]

    # ========================================================
    # TREND
    # ========================================================

    recent_closes = [
        c["close"]
        for c in candles[-8:]
    ]

    rising_count = sum(
        1
        for i in range(1, len(recent_closes))
        if recent_closes[i]
        > recent_closes[i - 1]
    )

    trend_up = (
        close > swing_low
        and rising_count >= 4
    )

    if not trend_up:
        return None

    # ========================================================
    # BOS / NEAR BOS
    # ========================================================

    distance_from_bos = (
        close - swing_high
    ) / swing_high * Decimal("100")

    real_bos = (
        close > swing_high
        and distance_from_bos >= Decimal("0.05")
    )

    near_bos = (
        distance_from_bos >= Decimal("-0.25")
        and distance_from_bos <= Decimal("0.05")
    )

    if not real_bos and not near_bos:
        return None

    # ========================================================
    # PULLBACK
    # ========================================================

    reference = swing_high

    pullback_touched = (
        low <= reference * (
            Decimal("1")
            + Decimal("0.008")
        )
    )

    if not pullback_touched:
        return None

    # ========================================================
    # CONTINUATION
    # ========================================================

    continuation = (
        close >= reference
        or
        (
            real_bos
            and close > last["open"]
        )
    )

    if not continuation:
        return None

    # ========================================================
    # CLOSED CONFIRMATION
    # ========================================================

    r = candle_range(last)

    if r <= 0:
        return None

    close_position = (
        last["close"] - last["low"]
    ) / r

    closed_confirm = (
        bullish(last)
        and
        close_position >= Decimal("0.55")
    )

    if not closed_confirm:
        return None

    # ========================================================
    # PRESSURE
    # ========================================================

    bullish_candles = sum(
        1
        for c in candles[-10:]
        if bullish(c)
    )

    pressure = (
        Decimal(bullish_candles)
        / Decimal("10")
        * Decimal("100")
    )

    # ========================================================
    # SCORE
    # ========================================================

    score = 0

    if real_bos:
        score += 4
    elif near_bos:
        score += 3

    if pullback_touched:
        score += 2

    if continuation:
        score += 2

    if closed_confirm:
        score += 2

    if pressure >= Decimal("60"):
        score += 1

    if score < MIN_SCORE:
        return None

    # ========================================================
    # ENTRY / SL / TP
    # ========================================================

    entry = close

    risk = max(
        entry - swing_low,
        entry * Decimal("0.006")
    )

    sl = entry - risk

    tp1 = entry + (
        risk * Decimal("1.67")
    )

    tp2 = entry + (
        risk * Decimal("2.67")
    )

    move = (
        entry - swing_low
    ) / swing_low * Decimal("100")

    return {
        "symbol": symbol,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "score": score,
        "pressure": pressure,
        "move": move,
        "bos": (
            "REAL BOS"
            if real_bos
            else "NEAR BOS"
        ),
        "candle_time": last["time"],
    }


# ============================================================
# REAL BUY
# ============================================================

def place_real_buy(signal, market):

    if not LIVE_TRADING:
        return {
            "ok": False,
            "reason": "LIVE_TRADING disabled",
        }

    if BUY_LOCK:
        return {
            "ok": False,
            "reason": "BUY_LOCK enabled",
        }

    symbol = signal["symbol"]
    price = Decimal(signal["entry"])

    if price <= 0:
        return {
            "ok": False,
            "reason": "invalid price",
        }

    lot_filter = get_filter(
        market,
        "LOT_SIZE"
    )

    min_notional_filter = get_filter(
        market,
        "MIN_NOTIONAL"
    )

    step = decimal_or_zero(
        lot_filter.get("stepSize", "0")
    )

    min_qty = decimal_or_zero(
        lot_filter.get("minQty", "0")
    )

    min_notional = decimal_or_zero(
        min_notional_filter.get(
            "minNotional",
            "0"
        )
    )

    qty = ORDER_USDT / price

    if step > 0:
        qty = floor_decimal(
            qty,
            step
        )

    if qty < min_qty:
        qty = min_qty

    if qty <= 0:
        return {
            "ok": False,
            "reason": "quantity <= 0",
        }

    notional = qty * price

    if (
        min_notional > 0
        and notional < min_notional
    ):
        needed_qty = (
            min_notional / price
        )

        if step > 0:
            needed_qty = floor_decimal(
                needed_qty,
                step
            )

            if (
                needed_qty * price
                < min_notional
            ):
                needed_qty += step

        qty = needed_qty
        notional = qty * price

    qty_text = decimal_string(qty)

    telegram(
        "🟢 REAL BUY READY\n"
        f"🪙 {symbol}\n"
        f"💵 ENTRY: {price}\n"
        f"📦 QTY: {qty_text}\n"
        f"💰 VALUE: {notional:.8f} USDT\n"
        f"🎯 TP1: {signal['tp1']}\n"
        f"🎯 TP2: {signal['tp2']}\n"
        f"🛑 SL: {signal['sl']}\n"
        f"📊 SCORE: {signal['score']}\n"
        f"🧠 {signal['bos']}"
    )

    try:

        order = signed_post(
            "/order",
            {
                "symbol": symbol,
                "side": "BUY",
                "type": "MARKET",
                "quantity": qty_text,
            },
            retries=2,
        )

        telegram(
            "✅ REAL BUY SENT\n"
            f"🪙 {symbol}\n"
            f"📦 QTY: {qty_text}\n"
            f"💰 TARGET: {ORDER_USDT} USDT\n"
            f"🧾 ORDER ID: "
            f"{order.get('orderId', 'N/A')}\n"
            f"📌 STATUS: "
            f"{order.get('status', 'N/A')}\n"
            f"🕐 {utc_now()}"
        )

        return {
            "ok": True,
            "order": order,
        }

    except Exception as e:

        telegram(
            "❌ REAL BUY FAILED\n"
            f"🪙 {symbol}\n"
            f"⚠️ {str(e)[:700]}\n"
            f"🕐 {utc_now()}"
        )

        return {
            "ok": False,
            "reason": str(e),
        }


# ============================================================
# SCAN
# ============================================================

def scan():

    telegram(
        "🔎 SCAN STARTING\n"
        f"⚡ {VERSION}\n"
        "🧠 BOS / NEAR BOS → PULLBACK → "
        "CONTINUATION → CLOSED CONFIRM\n"
        "⏱ 5m CLOSED CANDLES\n"
        "🚫 EMA: OFF\n"
        f"🔓 REAL TRADING: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"💵 ORDER TARGET: {ORDER_USDT} USDT\n"
        f"🕐 {utc_now()}"
    )

    try:

        markets = get_markets()

    except Exception as e:

        telegram(
            "❌ MARKET LIST FAILED\n"
            f"⚠️ {str(e)[:700]}\n"
            f"🕐 {utc_now()}"
        )

        return

    markets = markets[:SCAN_LIMIT]

    telegram(
        "📡 MARKET SCAN\n"
        f"👀 {len(markets)} USDT MARKETS\n"
        f"🕐 {utc_now()}"
    )

    signals = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_market,
                market
            ): market
            for market in markets
        }

        for future in as_completed(futures):

            market = futures[future]

            try:

                signal = future.result()

                if signal:
                    signals.append(signal)

            except Exception as e:

                symbol = market.get(
                    "symbol",
                    "UNKNOWN"
                )

                print(
                    f"⚠️ Scanner error "
                    f"{symbol}: {e}",
                    flush=True,
                )

    signals.sort(
        key=lambda x: (
            x["score"],
            x["pressure"]
        ),
        reverse=True,
    )

    if not signals:

        telegram(
            "💓 ATI RUN ALIVE\n"
            f"🕐 {utc_now()}\n"
            "📡 SCAN FINISHED\n"
            "👀 NO BUY"
        )

        return

    telegram(
        "🔥 BUY SIGNALS FOUND\n"
        f"📊 COUNT: {len(signals)}\n"
        f"🕐 {utc_now()}"
    )

    for signal in signals[:5]:

        telegram(
            "🟢 BUY SIGNAL\n"
            f"🪙 {signal['symbol']}\n"
            f"📍 ENTRY: {signal['entry']}\n"
            f"🛑 SL: {signal['sl']}\n"
            f"🎯 TP1: {signal['tp1']}\n"
            f"🎯 TP2: {signal['tp2']}\n"
            f"📊 SCORE: {signal['score']}\n"
            f"💪 PRESSURE: "
            f"{signal['pressure']:.1f}%\n"
            f"📈 MOVE: "
            f"{signal['move']:.2f}%\n"
            f"🧠 {signal['bos']}"
        )

    # ========================================================
    # ONE REAL BUY MAX PER RUN
    # ========================================================

    if LIVE_TRADING and not BUY_LOCK:

        selected = signals[0]

        selected_market = next(
            (
                m for m in markets
                if str(
                    m.get("symbol", "")
                ).upper()
                == selected["symbol"]
            ),
            None,
        )

        if selected_market:

            result = place_real_buy(
                selected,
                selected_market
            )

            if result.get("ok"):
                print(
                    "✅ ONE REAL BUY COMPLETED",
                    flush=True,
                )

    else:

        print(
            "ℹ️ REAL BUY NOT EXECUTED",
            flush=True,
        )


# ============================================================
# MAIN
# ============================================================

def main():

    start = time.time()

    telegram(
        "💓 ATI ALIVE\n"
        f"⚡ {VERSION}\n"
        "🟢 NEW RUN STARTED\n"
        f"🕐 {utc_now()}"
    )

    telegram(
        f"⚡ ATI BOT {VERSION}\n"
        "🧠 REAL BOS / NEAR BOS → "
        "PULLBACK → CONTINUATION → CLOSED\n"
        "🚫 EMA: OFF\n"
        f"🔓 REAL TRADING: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"💵 ORDER TARGET: {ORDER_USDT} USDT\n"
        f"🔑 AUTH PAIR: {AUTH_PAIR}\n"
        f"🕐 {utc_now()}"
    )

    account = auth_test()

    if account is None:

        telegram(
            "🛑 BOT STOPPED\n"
            "❌ AUTH FAILED\n"
            f"🕐 {utc_now()}"
        )

        return

    if not account.get("canTrade", False):

        telegram(
            "🛑 BOT STOPPED\n"
            "❌ canTrade=False\n"
            f"🕐 {utc_now()}"
        )

        return

    try:

        scan()

    except Exception as e:

        telegram(
            "❌ SCAN CRASH\n"
            f"⚠️ {str(e)[:700]}\n"
            f"🕐 {utc_now()}"
        )

    elapsed = time.time() - start

    telegram(
        "💓 ATI RUN END\n"
        f"⚡ {VERSION}\n"
        f"⏱ {elapsed:.1f}s\n"
        f"🕐 {utc_now()}"
    )


if __name__ == "__main__":
    main()
