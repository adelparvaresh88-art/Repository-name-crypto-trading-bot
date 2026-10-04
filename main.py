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
# ATI CRYPTO BOT V40.2.50-REAL
# TABDEAL SPOT
#
# STRATEGY:
# Trend → REAL BOS → Pullback → Continuation → CLOSED CONFIRM
#
# EMA: OFF
# TIMEFRAME: 5m CLOSED CANDLES
# REAL TRADING: ENABLED BY SECRET
# ORDER SIZE: 2 USDT
# MAX REAL BUYS PER RUN: 1
# ============================================================

VERSION = "V40.2.50-REAL"

BASE = "https://api1.tabdeal.org"
API_ROOT = f"{BASE}/r/api/v1"
ORDER_ROOT = f"{BASE}/api/v1"

TIMEOUT = 15
RECV_WINDOW = int(os.getenv("RECV_WINDOW", "10000"))

SCAN_LIMIT = int(os.getenv("SCAN_LIMIT", "40"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "12"))

MIN_SCORE = float(os.getenv("MIN_SCORE", "11"))

# ============================================================
# REAL ORDER VALUE
# ============================================================

ORDER_USDT = Decimal(os.getenv("ORDER_USDT", "2"))

MAX_REAL_BUYS_PER_RUN = 1

LIVE_TRADING = os.getenv(
    "LIVE_TRADING", "false"
).strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

BUY_LOCK = False


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return

    try:
        url = (
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage"
        )

        requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

    except Exception as e:
        print("Telegram error:", e)


# ============================================================
# API KEYS
# ============================================================

API_KEY = (
    os.getenv("TABDEAL_API_KEY", "").strip()
    or os.getenv("TABDIL_API_KEY", "").strip()
)

API_SECRET = (
    os.getenv("TABDEAL_API_SECRET", "").strip()
    or os.getenv("TABDIL_API_SECRET", "").strip()
)


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def D(value, default="0"):
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def fmt_decimal(value):
    value = D(value)
    text = format(value, "f")

    if "." in text:
        text = text.rstrip("0").rstrip(".")

    return text or "0"


def floor_step(value, step):
    value = D(value)
    step = D(step)

    if step <= 0:
        return value

    return (value / step).to_integral_value(
        rounding=ROUND_DOWN
    ) * step


# ============================================================
# PUBLIC GET
# ============================================================

def public_get(path, params=None):
    url = BASE + path

    response = requests.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():
    data = public_get("/api/v1/time")

    if isinstance(data, dict):
        for key in (
            "serverTime",
            "server_time",
            "timestamp",
            "time",
        ):
            if key in data:
                return int(data[key])

    if isinstance(data, (int, float)):
        return int(data)

    raise RuntimeError(
        f"Cannot read server time: {data}"
    )


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None,
):
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "API KEY / SECRET missing"
        )

    params = dict(params or {})

    server_time = get_server_time()

    params["timestamp"] = server_time
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

    headers = {
        "X-MBX-APIKEY": API_KEY,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    url = BASE + path

    response = requests.request(
        method,
        url,
        params=params if method.upper() == "GET" else None,
        data=params if method.upper() != "GET" else None,
        headers=headers,
        timeout=TIMEOUT,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"HTTP {response.status_code}: {response.text}"
        )

    try:
        return response.json()
    except Exception:
        return response.text


# ============================================================
# ACCOUNT
# ============================================================

def get_account():
    return signed_request(
        "GET",
        "/r/api/v1/account",
    )


def get_free_usdt():
    account = get_account()

    balances = account.get(
        "balances",
        account.get("assets", []),
    )

    for item in balances:
        asset = str(
            item.get("asset", item.get("currency", ""))
        ).upper()

        if asset == "USDT":
            return D(
                item.get(
                    "free",
                    item.get("available", "0"),
                )
            )

    return Decimal("0")


# ============================================================
# AUTH TEST
# ============================================================

def auth_test():
    telegram(
        "🔐 AUTH CHECK\n"
        f"🕐 {now_utc()}"
    )

    account = get_account()

    can_trade = account.get(
        "canTrade",
        account.get("can_trade", True),
    )

    balance = get_free_usdt()

    telegram(
        "✅ AUTH OK\n"
        f"🔓 canTrade={can_trade}\n"
        f"💰 FREE USDT: {balance}"
    )

    if can_trade is False:
        raise RuntimeError(
            "API account cannot trade"
        )

    return account


# ============================================================
# MARKET LIST
# ============================================================

def get_usdt_markets():

    data = public_get(
        "/api/v1/exchangeInfo"
    )

    if isinstance(data, dict):
        symbols = data.get(
            "symbols",
            data.get("data", []),
        )
    else:
        symbols = data

    markets = []

    for s in symbols:

        if not isinstance(s, dict):
            continue

        symbol = str(
            s.get("symbol", "")
        ).upper()

        status = str(
            s.get("status", "TRADING")
        ).upper()

        if not symbol.endswith("USDT"):
            continue

        if status not in (
            "TRADING",
            "ENABLED",
            "1",
            "",
        ):
            continue

        markets.append(s)

    return markets


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):

    try:
        data = public_get(
            "/api/v1/trades",
            {
                "symbol": symbol,
                "limit": 500,
            },
        )

        if isinstance(data, dict):
            data = data.get(
                "data",
                data.get("trades", []),
            )

        return data or []

    except Exception:
        return []


# ============================================================
# BUILD 5M CLOSED CANDLES
# ============================================================

def build_candles(trades):

    buckets = {}

    for trade in trades:

        try:
            if "time" in trade:
                ts = int(trade["time"])
            elif "timestamp" in trade:
                ts = int(trade["timestamp"])
            else:
                continue

            price = D(
                trade.get(
                    "price",
                    trade.get("p", "0"),
                )
            )

            qty = D(
                trade.get(
                    "qty",
                    trade.get(
                        "quantity",
                        trade.get("q", "0"),
                    ),
                )
            )

            if price <= 0:
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

            c = buckets[bucket]

            c["high"] = max(
                c["high"],
                price,
            )

            c["low"] = min(
                c["low"],
                price,
            )

            c["close"] = price
            c["volume"] += qty

        except Exception:
            continue

    candles = [
        buckets[k]
        for k in sorted(buckets)
    ]

    # Remove current forming 5m candle
    current_bucket = (
        int(time.time() * 1000)
        // 300000
    ) * 300000

    candles = [
        c
        for c in candles
        if c["time"] < current_bucket
    ]

    return candles


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return Decimal("0")

    trs = []

    for i in range(1, len(candles)):

        cur = candles[i]
        prev = candles[i - 1]

        high = cur["high"]
        low = cur["low"]
        prev_close = prev["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )

        trs.append(tr)

    if len(trs) < period:
        return Decimal("0")

    return sum(
        trs[-period:]
    ) / Decimal(period)


# ============================================================
# ANALYSIS
# ============================================================

def analyze(symbol):

    trades = get_trades(symbol)

    candles = build_candles(trades)

    if len(candles) < 30:
        return None

    c = candles[-1]
    prev = candles[-2]

    price = c["close"]

    atr = calculate_atr(candles, 14)

    if atr <= 0:
        return None

    lookback = candles[-21:-1]

    swing_high = max(
        x["high"]
        for x in lookback
    )

    swing_low = min(
        x["low"]
        for x in lookback
    )

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    recent = candles[-6:]

    rising = (
        recent[-1]["close"]
        > recent[0]["close"]
    )

    higher_lows = (
        recent[-1]["low"]
        >= recent[0]["low"]
    )

    trend = rising or higher_lows

    if not trend:
        return None

    # --------------------------------------------------------
    # REAL BOS
    # --------------------------------------------------------

    bos_level = swing_high

    bos_strength = (
        price - bos_level
    ) / atr

    real_bos = (
        price > bos_level
        and bos_strength >= Decimal("0.05")
    )

    near_bos = (
        bos_strength >= Decimal("-0.25")
    )

    if not real_bos and not near_bos:
        return None

    # --------------------------------------------------------
    # PULLBACK
    # --------------------------------------------------------

    pullback_distance = abs(
        price - bos_level
    ) / atr

    pullback = (
        pullback_distance
        <= Decimal("0.80")
    )

    if not pullback:
        return None

    # --------------------------------------------------------
    # SIGNAL BAR
    # --------------------------------------------------------

    candle_range = (
        c["high"] - c["low"]
    )

    if candle_range <= 0:
        return None

    close_position = (
        c["close"] - c["low"]
    ) / candle_range

    bullish = (
        c["close"] > c["open"]
    )

    signal_bar = (
        bullish
        and close_position >= Decimal("0.55")
    )

    # --------------------------------------------------------
    # CONTINUATION
    # --------------------------------------------------------

    continuation = (
        c["close"] >= prev["close"]
    )

    # --------------------------------------------------------
    # CHASE FILTER
    # --------------------------------------------------------

    move_from_low = (
        price - swing_low
    ) / atr

    chase = (
        move_from_low
        > Decimal("2.20")
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0.0

    if trend:
        score += 3

    if real_bos:
        score += 4
    elif near_bos:
        score += 2

    if pullback:
        score += 2

    if signal_bar:
        score += 3

    if continuation:
        score += 2

    if chase:
        score -= 3

    if not real_bos:
        score -= 1

    if score < MIN_SCORE:
        return None

    # --------------------------------------------------------
    # ENTRY / SL / TP
    # --------------------------------------------------------

    entry = price

    sl = min(
        c["low"],
        prev["low"],
    ) - (
        atr * Decimal("0.15")
    )

    risk = entry - sl

    if risk <= 0:
        return None

    tp1 = entry + (
        risk * Decimal("1.5")
    )

    tp2 = entry + (
        risk * Decimal("2.2")
    )

    return {
        "symbol": symbol,
        "score": score,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "atr": atr,
        "real_bos": real_bos,
    }


# ============================================================
# SCAN
# ============================================================

def scan():

    telegram(
        "🔎 SCAN STARTING\n"
        f"⚡ {VERSION}\n"
        "🧠 REAL BOS → PULLBACK → "
        "CONTINUATION → CLOSED CONFIRM\n"
        "⏱ 5m CLOSED CANDLES\n"
        "🚫 EMA: OFF\n"
        f"💵 ORDER TARGET: {ORDER_USDT} USDT\n"
        f"🕐 {now_utc()}"
    )

    markets = get_usdt_markets()

    telegram(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    results = []

    selected = markets[:SCAN_LIMIT]

    def worker(market):

        symbol = str(
            market.get("symbol", "")
        ).upper()

        return analyze(symbol)

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                worker,
                market,
            )
            for market in selected
        ]

        for future in as_completed(futures):

            try:
                result = future.result()

                if result:
                    results.append(result)

            except Exception as e:
                print(
                    "Scan error:",
                    e,
                )

    results.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    if not results:

        telegram(
            "👀 NO BUY READY\n"
            "هیچ سیگنال واجد شرایطی پیدا نشد."
        )

        return []

    ready_text = [
        "📡 ATI SCAN RESULT"
    ]

    for r in results[:10]:

        ready_text.append(
            f"🔥 BUY READY "
            f"{r['symbol']} | "
            f"score {r['score']:.1f} | "
            f"entry~ {fmt_decimal(r['entry'])}"
        )

    telegram(
        "\n".join(ready_text)
    )

    return results


# ============================================================
# MARKET LIMITS
# ============================================================

def get_market_limits(symbol):

    info = public_get(
        "/api/v1/exchangeInfo"
    )

    symbols = (
        info.get("symbols", [])
        if isinstance(info, dict)
        else info
    )

    for s in symbols:

        if str(
            s.get("symbol", "")
        ).upper() != symbol.upper():
            continue

        filters = s.get(
            "filters",
            [],
        )

        min_qty = Decimal("0")
        max_qty = Decimal("999999999")
        step_size = Decimal("0")

        min_notional = Decimal("0")

        for f in filters:

            ftype = str(
                f.get("filterType", "")
            ).upper()

            if ftype in (
                "MARKET_LOT_SIZE",
                "LOT_SIZE",
            ):

                fq = D(
                    f.get(
                        "minQty",
                        "0",
                    )
                )

                fs = D(
                    f.get(
                        "stepSize",
                        "0",
                    )
                )

                fm = D(
                    f.get(
                        "maxQty",
                        "0",
                    )
                )

                if ftype == "MARKET_LOT_SIZE":

                    if fq > 0:
                        min_qty = fq

                    if fs > 0:
                        step_size = fs

                    if fm > 0:
                        max_qty = fm

            if ftype in (
                "MIN_NOTIONAL",
                "NOTIONAL",
            ):

                mn = D(
                    f.get(
                        "minNotional",
                        f.get(
                            "notional",
                            "0",
                        ),
                    )
                )

                if mn > 0:
                    min_notional = mn

        return {
            "min_qty": min_qty,
            "max_qty": max_qty,
            "step_size": step_size,
            "min_notional": min_notional,
        }

    raise RuntimeError(
        f"Market limits not found: {symbol}"
    )


# ============================================================
# PREPARE REAL MARKET BUY
# ============================================================

def prepare_market_buy(
    symbol,
    price,
):

    limits = get_market_limits(symbol)

    min_qty = limits["min_qty"]
    max_qty = limits["max_qty"]
    step = limits["step_size"]
    min_notional = limits["min_notional"]

    if price <= 0:
        raise RuntimeError(
            "Invalid market price"
        )

    raw_qty = (
        ORDER_USDT / price
    )

    qty = raw_qty

    if step > 0:
        qty = floor_step(
            qty,
            step,
        )

    if max_qty > 0 and qty > max_qty:
        qty = max_qty

    if min_qty > 0 and qty < min_qty:

        raise RuntimeError(
            f"ORDER SKIPPED: "
            f"qty {qty} < minQty {min_qty}"
        )

    estimated_value = (
        qty * price
    )

    if (
        min_notional > 0
        and estimated_value < min_notional
    ):

        raise RuntimeError(
            f"ORDER SKIPPED: "
            f"value {estimated_value} "
            f"< minNotional {min_notional}"
        )

    return {
        "qty": qty,
        "estimated_value": estimated_value,
        "min_qty": min_qty,
        "step_size": step,
        "min_notional": min_notional,
    }


# ============================================================
# REAL BUY
# ============================================================

def place_real_buy(signal):

    symbol = signal["symbol"]
    price = signal["entry"]

    prepared = prepare_market_buy(
        symbol,
        price,
    )

    qty = prepared["qty"]
    estimated_value = prepared[
        "estimated_value"
    ]

    telegram(
        "✅ ORDER SIZE VALID\n\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: {fmt_decimal(qty)}\n"
        f"💵 EST. VALUE: "
        f"{estimated_value:.8f} USDT\n"
        f"📏 minQty: "
        f"{fmt_decimal(prepared['min_qty'])}\n"
        f"📐 stepSize: "
        f"{fmt_decimal(prepared['step_size'])}"
    )

    # --------------------------------------------------------
    # FINAL BALANCE CHECK
    # --------------------------------------------------------

    free_usdt = get_free_usdt()

    if free_usdt < estimated_value:

        raise RuntimeError(
            f"Insufficient USDT: "
            f"need~{estimated_value}, "
            f"free={free_usdt}"
        )

    telegram(
        "🚀 SENDING ONE REAL BUY...\n\n"
        f"🪙 {symbol}\n"
        f"💵 TARGET: {ORDER_USDT} USDT\n"
        f"📦 QTY: {fmt_decimal(qty)}\n"
        f"💰 FREE USDT: {free_usdt}"
    )

    if not LIVE_TRADING:

        telegram(
            "🧪 PAPER MODE\n"
            "LIVE_TRADING=false\n"
            "❌ REAL ORDER NOT SENT"
        )

        return None

    if BUY_LOCK:

        telegram(
            "🔒 BUY LOCK ACTIVE\n"
            "❌ REAL ORDER NOT SENT"
        )

        return None

    # --------------------------------------------------------
    # REAL MARKET ORDER
    # --------------------------------------------------------

    order = signed_request(
        "POST",
        "/api/v1/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": fmt_decimal(qty),
        },
    )

    order_id = (
        order.get("orderId")
        if isinstance(order, dict)
        else None
    )

    telegram(
        "🟢 ATI REAL BUY ACCEPTED\n\n"
        f"🪙 {symbol}\n"
        f"📦 QTY: {fmt_decimal(qty)}\n"
        f"💵 TARGET: {ORDER_USDT} USDT\n"
        f"🆔 ORDER ID: {order_id}\n"
        f"🕐 {now_utc()}"
    )

    return order


# ============================================================
# MAIN
# ============================================================

def main():

    telegram(
        "⚡ ATI BOT "
        f"{VERSION}\n"
        "🧠 REAL BOS / NEAR BOS → "
        "PULLBACK → CLOSED CONFIRM\n"
        "🚫 EMA: OFF\n"
        f"🔓 REAL TRADING: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"
        f"💵 ORDER TARGET: "
        f"{ORDER_USDT} USDT\n"
        f"🕐 {now_utc()}"
    )

    try:

        # ----------------------------------------------------
        # AUTH
        # ----------------------------------------------------

        auth_test()

        # ----------------------------------------------------
        # SCAN
        # ----------------------------------------------------

        signals = scan()

        if not signals:
            return

        # ----------------------------------------------------
        # TOP SIGNAL
        # ----------------------------------------------------

        signal = signals[0]

        telegram(
            "🔥 BUY READY\n\n"
            f"🪙 {signal['symbol']}\n"
            f"📊 SCORE: "
            f"{signal['score']:.0f}\n"
            "📐 Trend → BOS → Pullback "
            "→ Continuation → CLOSED\n"
            f"💵 ENTRY~ "
            f"{fmt_decimal(signal['entry'])}\n"
            f"🛡 SL(calc) "
            f"{fmt_decimal(signal['sl'])}\n"
            f"🎯 TP1(calc) "
            f"{fmt_decimal(signal['tp1'])}\n"
            f"🎯 TP2(calc) "
            f"{fmt_decimal(signal['tp2'])}\n"
            f"💵 ORDER TARGET: "
            f"{ORDER_USDT} USDT"
        )

        if not LIVE_TRADING:

            telegram(
                "🧪 PAPER MODE\n"
                "LIVE_TRADING=false\n"
                "❌ REAL ORDER NOT SENT"
            )

            return

        # ----------------------------------------------------
        # FINAL AUTH
        # ----------------------------------------------------

        telegram(
            "🔐 AUTH CHECK BEFORE REAL BUY..."
        )

        auth_test()

        # ----------------------------------------------------
        # ONE REAL BUY ONLY
        # ----------------------------------------------------

        place_real_buy(signal)

    except Exception as e:

        message = (
            f"🚨 ATI ERROR {VERSION}\n\n"
            f"❌ {str(e)}\n\n"
            "🛑 REAL BUY NOT COMPLETED"
        )

        telegram(message)

        print(message)


if __name__ == "__main__":
    main()
