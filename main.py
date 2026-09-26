import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.1.1
# BREAKOUT + RETEST SCANNER
# TABDEAL
# ============================================================

VERSION = "V38.1.1"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 720
MAX_MARKETS = 1000
TOP_RESULTS = 5

BUY_MIN_SCORE = 11
WATCH_MIN_SCORE = 8

CHASE_LIMIT_5M = 7.0

REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.03


# ============================================================
# HTTP
# ============================================================

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-Crypto-Bot/38.1.1"
})


def get_json(path, params=None):
    try:
        r = session.get(
            BASE_URL + path,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        r.raise_for_status()
        return r.json()

    except Exception as e:
        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"

        r = session.post(
            url,
            data={
                "chat_id": chat_id,
                "text": message
            },
            timeout=15
        )

        return r.ok

    except Exception:
        return False


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_markets():
    data = get_json("/r/api/v1/markets")

    if data is None:
        return []

    markets = []

    def add_market(item):
        if not isinstance(item, dict):
            return

        symbol = (
            item.get("symbol")
            or item.get("market")
            or item.get("code")
            or ""
        )

        symbol = str(symbol).upper()

        if symbol.endswith("USDT"):
            markets.append(symbol)

    if isinstance(data, list):
        for item in data:
            add_market(item)

    elif isinstance(data, dict):

        for key in ("data", "result", "markets", "symbols"):

            value = data.get(key)

            if isinstance(value, list):
                for item in value:
                    add_market(item)

            elif isinstance(value, dict):
                for k, v in value.items():

                    if isinstance(v, dict):
                        item = dict(v)

                        if not item.get("symbol"):
                            item["symbol"] = k

                        add_market(item)

    markets = sorted(set(markets))

    return markets[:MAX_MARKETS]


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):
    data = get_json(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000
        }
    )

    if data is None:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in ("data", "result", "trades"):

            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = (
        item.get("price")
        or item.get("p")
    )

    qty = (
        item.get("qty")
        or item.get("quantity")
        or item.get("q")
        or item.get("amount")
    )

    ts = (
        item.get("time")
        or item.get("timestamp")
        or item.get("T")
    )

    try:
        price = float(price)
    except Exception:
        return None

    try:
        qty = float(qty or 0)
    except Exception:
        qty = 0.0

    try:
        ts = float(ts)
    except Exception:
        ts = 0.0

    if ts > 100000000000:
        ts /= 1000

    return price, qty, ts


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    parsed = []

    for item in trades:

        p = parse_trade(item)

        if p:
            parsed.append(p)

    if not parsed:
        return []

    parsed.sort(key=lambda x: x[2])

    buckets = {}

    for price, qty, ts in parsed:

        bucket = int(ts // 300) * 300

        if bucket not in buckets:
            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty
            }

        else:

            c = buckets[bucket]

            if price > c["high"]:
                c["high"] = price

            if price < c["low"]:
                c["low"] = price

            c["close"] = price
            c["volume"] += qty

    candles = list(buckets.values())

    candles.sort(key=lambda x: x["time"])

    return candles


# ============================================================
# HELPERS
# ============================================================

def pct_change(old, new):

    if old == 0:
        return 0.0

    return ((new - old) / old) * 100.0


def average(values):

    if not values:
        return 0.0

    return sum(values) / len(values)


def body(c):
    return abs(c["close"] - c["open"])


def candle_range(c):
    return max(c["high"] - c["low"], 0.0000000001)


def upper_wick(c):
    return c["high"] - max(c["open"], c["close"])


def lower_wick(c):
    return min(c["open"], c["close"]) - c["low"]


# ============================================================
# ANALYSIS
# ============================================================

def analyze(symbol, candles):

    if len(candles) < 100:
        return None

    # --------------------------------------------------------
    # CLOSED CANDLE
    # --------------------------------------------------------

    closed = candles[:-1]

    if len(closed) < 80:
        return None

    last = closed[-1]

    price = last["close"]

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    price_5m = closed[-2]["close"]
    price_15m = closed[-4]["close"]
    price_1h = closed[-13]["close"]

    move_5m = pct_change(price_5m, price)
    move_15m = pct_change(price_15m, price)
    move_1h = pct_change(price_1h, price)

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    recent_volumes = [
        c["volume"]
        for c in closed[-21:-1]
    ]

    avg_volume = average(recent_volumes)

    if avg_volume > 0:
        volume_ratio = last["volume"] / avg_volume
    else:
        volume_ratio = 0.0

    # --------------------------------------------------------
    # SWING HIGH / LOW
    # --------------------------------------------------------

    lookback = closed[-25:-1]

    if not lookback:
        return None

    resistance = max(c["high"] for c in lookback)
    support = min(c["low"] for c in lookback)

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    breakout = last["close"] > resistance

    # Previous candle touching / breaking resistance
    previous = closed[-2]

    previous_near_resistance = (
        previous["high"] >= resistance * 0.997
    )

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    retest = False

    if breakout:

        distance_from_breakout = abs(
            last["low"] - resistance
        ) / resistance * 100

        close_above = last["close"] > resistance

        if (
            distance_from_breakout <= 1.2
            and close_above
        ):
            retest = True

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    closes = [c["close"] for c in closed]

    fast_avg = average(closes[-6:])
    slow_avg = average(closes[-20:])

    trend_up = fast_avg > slow_avg

    # --------------------------------------------------------
    # HIGHER HIGHS / HIGHER LOWS
    # --------------------------------------------------------

    recent = closed[-10:]

    hh_count = 0
    hl_count = 0

    for i in range(2, len(recent)):

        if recent[i]["high"] > recent[i - 1]["high"]:
            hh_count += 1

        if recent[i]["low"] > recent[i - 1]["low"]:
            hl_count += 1

    structure_up = (
        hh_count >= 4 and
        hl_count >= 3
    )

    # --------------------------------------------------------
    # CANDLE STRENGTH
    # --------------------------------------------------------

    rng = candle_range(last)

    body_ratio = body(last) / rng

    bullish_candle = (
        last["close"] > last["open"]
        and body_ratio >= 0.45
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    reasons = []

    # Breakout
    if breakout:
        score += 4
        reasons.append("BREAKOUT")

    # Retest
    if retest:
        score += 3
        reasons.append("RETEST")

    # Momentum 5m
    if move_5m >= 1.0:
        score += 1
        reasons.append("5M MOMENTUM")

    # Momentum 15m
    if move_15m >= 2.0:
        score += 1
        reasons.append("15M MOMENTUM")

    # Momentum 1h
    if move_1h >= 3.0:
        score += 1
        reasons.append("1H MOMENTUM")

    # Volume
    if volume_ratio >= 1.20:
        score += 2
        reasons.append("VOLUME")

    elif volume_ratio >= 0.80:
        score += 1

    # Trend
    if trend_up:
        score += 1
        reasons.append("TREND UP")

    # Structure
    if structure_up:
        score += 2
        reasons.append("BULLISH STRUCTURE")

    # Candle
    if bullish_candle:
        score += 1
        reasons.append("BULLISH CANDLE")

    # --------------------------------------------------------
    # CHASE PROTECTION
    # --------------------------------------------------------

    chase_block = move_5m > CHASE_LIMIT_5M

    # --------------------------------------------------------
    # SIGNAL TYPE
    # --------------------------------------------------------

    signal = "NONE"

    if score >= BUY_MIN_SCORE and not chase_block:
        signal = "BUY"

    elif score >= WATCH_MIN_SCORE and not chase_block:
        signal = "WATCH"

    # --------------------------------------------------------
    # STOP / TARGETS
    # --------------------------------------------------------

    risk_base = max(
        price - support,
        price * 0.004
    )

    sl = price - risk_base

    tp1 = price + risk_base * 1.5
    tp2 = price + risk_base * 2.5

    return {
        "symbol": symbol,
        "price": price,

        "score": score,
        "signal": signal,

        "move_5m": move_5m,
        "move_15m": move_15m,
        "move_1h": move_1h,

        "volume_ratio": volume_ratio,

        "resistance": resistance,
        "support": support,

        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,

        "breakout": breakout,
        "retest": retest,

        "reasons": reasons,

        "candles": len(closed)
    }


# ============================================================
# FORMAT PRICE
# ============================================================

def fmt_price(value):

    if value >= 1000:
        return f"{value:.2f}"

    if value >= 1:
        return f"{value:.4f}"

    if value >= 0.01:
        return f"{value:.6f}"

    return f"{value:.8f}"


# ============================================================
# MAIN
# ============================================================

def main():

    print(f"⚡ ATI CRYPTO BOT {VERSION}")
    print()
    print("🚀 BREAKOUT + RETEST SCANNER")
    print()
    print("📡 TABDEAL API: CONNECTING...")

    markets = get_markets()

    if not markets:

        print("❌ TABDEAL API: MARKET DATA ERROR")

        send_telegram(
            f"⚠️ ATI BOT {VERSION}\n\n"
            "❌ TABDEAL MARKET DATA ERROR"
        )

        return

    print("📡 TABDEAL API: OK")
    print(f"📊 USDT MARKETS: {len(markets)}")
    print(f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}")
    print(f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}")
    print(f"🚫 5M CHASE LIMIT: {CHASE_LIMIT_5M}%")
    print()

    now = datetime.now(timezone.utc)

    print(
        "🕐 Scan:",
        now.strftime("%Y-%m-%d %H:%M UTC")
    )

    print()

    buys = []
    watches = []

    unavailable = 0

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    for symbol in markets:

        trades = get_trades(symbol)

        if not trades:
            unavailable += 1
            continue

        candles = build_candles(trades)

        if len(candles) < 100:
            unavailable += 1
            continue

        result = analyze(symbol, candles)

        if result is None:
            continue

        if result["signal"] == "BUY":
            buys.append(result)

        elif result["signal"] == "WATCH":
            watches.append(result)

        time.sleep(SLEEP_BETWEEN_MARKETS)

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    buys.sort(
        key=lambda x: (
            x["score"],
            x["move_1h"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    watches.sort(
        key=lambda x: (
            x["score"],
            x["move_1h"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    buys = buys[:TOP_RESULTS]
    watches = watches[:TOP_RESULTS]

    # --------------------------------------------------------
    # TERMINAL OUTPUT
    # --------------------------------------------------------

    print()
    print(f"⚠️ Candle data unavailable: {unavailable} markets")
    print()

    print("🔥 STRONG BREAKOUT + RETEST SETUPS")
    print()

    if not buys:
        print("❌ No confirmed BUY setups")
    else:

        for i, r in enumerate(buys, 1):

            print(
                f"{i}. {r['symbol']} | "
                f"{r['signal']}"
            )

            print(
                f"   💰 {fmt_price(r['price'])} | "
                f"Score {r['score']}"
            )

            print(
                f"   📈 5M {r['move_5m']:+.2f}% | "
                f"15M {r['move_15m']:+.2f}% | "
                f"1H {r['move_1h']:+.2f}%"
            )

            print(
                f"   📊 Vol {r['volume_ratio']:.2f}x | "
                f"Candles {r['candles']}"
            )

            print(
                f"   🛑 SL {fmt_price(r['sl'])} | "
                f"🎯 TP1 {fmt_price(r['tp1'])} | "
                f"🎯 TP2 {fmt_price(r['tp2'])}"
            )

            print(
                "   🔎 " +
                ", ".join(r["reasons"])
            )

            print()

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    if watches:

        print("🟡 WATCH")
        print()

        for i, r in enumerate(watches, 1):

            print(
                f"{i}. {r['symbol']} | "
                f"Score {r['score']} | "
                f"5M {r['move_5m']:+.2f}%"
            )

        print()

    # --------------------------------------------------------
    # TELEGRAM MESSAGE
    # --------------------------------------------------------

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 BREAKOUT + RETEST SCANNER\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n\n"
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}\n"
        f"🚫 5M CHASE LIMIT: {CHASE_LIMIT_5M}%\n\n"
    )

    if buys:

        message += "🟢 CONFIRMED BUYS\n\n"

        for i, r in enumerate(buys, 1):

            message += (
                f"#{i}\n"
                f"🟢 BUY\n"
                f"🪙 {r['symbol']}\n"
                f"⭐ SCORE: {r['score']}\n"
                f"💰 PRICE: {fmt_price(r['price'])}\n"
                f"📈 5M: {r['move_5m']:+.2f}%\n"
                f"📊 15M: {r['move_15m']:+.2f}%\n"
                f"📊 1H: {r['move_1h']:+.2f}%\n"
                f"📊 VOL: {r['volume_ratio']:.2f}x\n"
                f"🔓 BREAKOUT: "
                f"{'YES' if r['breakout'] else 'NO'}\n"
                f"🔄 RETEST: "
                f"{'YES' if r['retest'] else 'NO'}\n"
                f"🛑 SL: {fmt_price(r['sl'])}\n"
                f"🎯 TP1: {fmt_price(r['tp1'])}\n"
                f"🎯 TP2: {fmt_price(r['tp2'])}\n\n"
            )

    else:

        message += (
            "❌ NO CONFIRMED BUY\n\n"
        )

    if watches:

        message += "🟡 WATCH LIST\n\n"

        for i, r in enumerate(watches, 1):

            message += (
                f"{i}. {r['symbol']} | "
                f"Score {r['score']} | "
                f"5M {r['move_5m']:+.2f}%\n"
            )

        message += "\n"

    message += (
        "━━━━━━━━━━━━━━━━━━\n"
        "🧪 SCANNER MODE\n"
        "🚫 REAL TRADING: DISABLED\n"
        "🚫 ORDER EXECUTION: DISABLED\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    send_telegram(message)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
