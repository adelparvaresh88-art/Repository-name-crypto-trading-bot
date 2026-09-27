import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V39
# FAST EARLY ENTRY + CONFIRMED BREAKOUT
# ============================================================

VERSION = "V39.0"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000

REQUEST_TIMEOUT = 10
MAX_WORKERS = 20

TOP_EARLY = 4
TOP_WATCH = 5
TOP_CONFIRMED = 3

# ------------------------------------------------------------
# FILTERS
# ------------------------------------------------------------

EARLY_MIN_SCORE = 10
WATCH_MIN_SCORE = 9
CONFIRMED_MIN_SCORE = 12

# Do not allow extremely weak volume into EARLY BUY
MIN_EARLY_VOLUME = 0.80

# Stronger requirement for CONFIRMED
MIN_CONFIRMED_VOLUME = 1.20

# Maximum distance from resistance for EARLY
EARLY_MAX_DISTANCE = 1.00

# Maximum distance from resistance for WATCH
WATCH_MAX_DISTANCE = 1.50

# Avoid chasing coins that already moved too much
CHASE_5M_LIMIT = 5.00

# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Real orders intentionally disabled
LIVE_TRADING = False


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Crypto-Bot/39.0",
    "Accept": "application/json",
})


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:
        r = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        return r.ok

    except Exception:
        return False


def api_get(path, params=None):
    try:
        r = session.get(
            BASE_URL + path,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        r.raise_for_status()

        return r.json()

    except Exception:
        return None


# ============================================================
# SYMBOL EXTRACTION
# ============================================================

def extract_symbol(item):
    if isinstance(item, str):
        return item.upper()

    if not isinstance(item, dict):
        return ""

    for key in (
        "symbol",
        "market",
        "pair",
        "ticker",
        "instrument",
    ):
        value = item.get(key)

        if isinstance(value, str):
            return value.upper()

    return ""


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_usdt_markets():
    candidates = []

    paths = [
        "/r/api/v1/tickers",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
    ]

    for path in paths:

        data = api_get(path)

        if data is None:
            continue

        if isinstance(data, dict):

            for key in (
                "data",
                "result",
                "symbols",
                "markets",
                "tickers",
            ):
                if key in data:
                    data = data[key]
                    break

        if isinstance(data, list):

            for item in data:

                symbol = extract_symbol(item)

                if (
                    symbol.endswith("USDT")
                    and "_" not in symbol
                    and "-" not in symbol
                ):
                    candidates.append(symbol)

            if candidates:
                break

    # Fallback: use known public market endpoint
    if not candidates:

        data = api_get(
            "/r/api/v1/trades",
            params={
                "symbol": "BTCUSDT",
                "limit": 1,
            },
        )

        if data is not None:
            # BTCUSDT only as emergency connectivity check
            candidates = ["BTCUSDT"]

    markets = sorted(set(candidates))

    return markets[:MAX_MARKETS]


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):
    data = api_get(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if not isinstance(data, list):
        return []

    return data


# ============================================================
# TRADE NORMALIZATION
# ============================================================

def normalize_trade(item):

    if not isinstance(item, dict):
        return None

    price = 0.0
    qty = 0.0
    timestamp = 0

    for key in (
        "price",
        "p",
    ):
        if key in item:
            price = safe_float(item.get(key))
            break

    for key in (
        "quantity",
        "qty",
        "q",
        "amount",
    ):
        if key in item:
            qty = safe_float(item.get(key))
            break

    for key in (
        "time",
        "timestamp",
        "T",
        "created_at",
    ):
        if key in item:
            timestamp = safe_float(item.get(key))
            break

    if price <= 0:
        return None

    if qty <= 0:
        qty = 1.0

    return {
        "price": price,
        "qty": qty,
        "time": timestamp,
    }


# ============================================================
# BUILD 5M CANDLES FROM TRADES
# ============================================================

def build_candles(trades):

    normalized = []

    for item in trades:

        t = normalize_trade(item)

        if t:
            normalized.append(t)

    if len(normalized) < 20:
        return []

    normalized.sort(key=lambda x: x["time"])

    candles = {}

    for trade in normalized:

        timestamp = trade["time"]

        # Handle milliseconds
        if timestamp > 100000000000:
            timestamp = timestamp / 1000

        bucket = int(timestamp // 300) * 300

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
            }

        c = candles[bucket]

        c["high"] = max(
            c["high"],
            trade["price"],
        )

        c["low"] = min(
            c["low"],
            trade["price"],
        )

        c["close"] = trade["price"]

        c["volume"] += trade["qty"]

    result = sorted(
        candles.values(),
        key=lambda x: x["time"],
    )

    return result[-CANDLE_LIMIT:]


# ============================================================
# MULTI-TIMEFRAME
# ============================================================

def aggregate_candles(candles, minutes):

    if not candles:
        return []

    seconds = minutes * 60

    result = {}

    for c in candles:

        bucket = int(c["time"] // seconds) * seconds

        if bucket not in result:

            result[bucket] = {
                "time": bucket,
                "open": c["open"],
                "high": c["high"],
                "low": c["low"],
                "close": c["close"],
                "volume": 0.0,
            }

        r = result[bucket]

        r["high"] = max(
            r["high"],
            c["high"],
        )

        r["low"] = min(
            r["low"],
            c["low"],
        )

        r["close"] = c["close"]

        r["volume"] += c["volume"]

    return sorted(
        result.values(),
        key=lambda x: x["time"],
    )


# ============================================================
# PERCENT CHANGE
# ============================================================

def pct_change(candles, count):

    if len(candles) < count + 1:
        return 0.0

    old = candles[-count - 1]["close"]
    new = candles[-1]["close"]

    if old <= 0:
        return 0.0

    return ((new - old) / old) * 100.0


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(candles):

    if len(candles) < 21:
        return 1.0

    current = candles[-1]["volume"]

    previous = [
        c["volume"]
        for c in candles[-21:-1]
        if c["volume"] > 0
    ]

    if not previous:
        return 1.0

    avg = sum(previous) / len(previous)

    if avg <= 0:
        return 1.0

    return current / avg


# ============================================================
# RESISTANCE
# ============================================================

def find_resistance(candles):

    if len(candles) < 12:
        return 0.0

    # Exclude current candle
    previous = candles[-13:-1]

    highs = [
        c["high"]
        for c in previous
        if c["high"] > 0
    ]

    if not highs:
        return 0.0

    return max(highs)


# ============================================================
# CANDLE STRENGTH
# ============================================================

def strong_candle(candle):

    if not candle:
        return False

    high = candle["high"]
    low = candle["low"]
    open_price = candle["open"]
    close = candle["close"]

    if high <= low:
        return False

    body = abs(close - open_price)
    range_size = high - low

    body_ratio = body / range_size

    close_position = (
        (close - low) / range_size
    )

    bullish = close > open_price

    return (
        bullish
        and body_ratio >= 0.45
        and close_position >= 0.65
    )


# ============================================================
# RETEST DETECTION
# ============================================================

def detect_retest(candles, resistance):

    if len(candles) < 4:
        return False

    if resistance <= 0:
        return False

    current = candles[-1]
    previous = candles[-2]

    tolerance = resistance * 0.003

    previous_touched = (
        previous["low"]
        <= resistance + tolerance
        and previous["high"]
        >= resistance - tolerance
    )

    current_above = (
        current["close"] >= resistance * 0.998
    )

    return previous_touched and current_above


# ============================================================
# ANALYZE MARKET
# ============================================================

def analyze_market(symbol):

    trades = get_trades(symbol)

    if not trades:
        return None

    candles5 = build_candles(trades)

    if len(candles5) < 30:
        return None

    # IMPORTANT:
    # Use CLOSED candle only.
    closed5 = candles5[:-1]

    if len(closed5) < 25:
        return None

    candles15 = aggregate_candles(
        closed5,
        15,
    )

    candles60 = aggregate_candles(
        closed5,
        60,
    )

    if len(candles15) < 5 or len(candles60) < 3:
        return None

    current = closed5[-1]

    price = current["close"]

    resistance = find_resistance(
        closed5
    )

    if resistance <= 0:
        return None

    change5 = pct_change(
        closed5,
        1,
    )

    change15 = pct_change(
        candles15,
        1,
    )

    change60 = pct_change(
        candles60,
        1,
    )

    volume = volume_ratio(
        closed5
    )

    distance = (
        (resistance - price)
        / price
    ) * 100.0

    # Positive = below resistance
    # Negative = already above resistance

    candle_strong = strong_candle(
        current
    )

    retest = detect_retest(
        closed5,
        resistance,
    )

    # --------------------------------------------------------
    # BASIC DIRECTION FILTER
    # --------------------------------------------------------

    if change15 <= -1.0:
        return None

    if change60 <= -2.0:
        return None

    # Avoid extreme chase
    if change5 > CHASE_5M_LIMIT:
        return None

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    # 5m momentum
    if change5 >= 0.20:
        score += 2
    elif change5 > 0:
        score += 1

    # 15m momentum
    if change15 >= 1.00:
        score += 2
    elif change15 >= 0.30:
        score += 1

    # 1h momentum
    if change60 >= 4.00:
        score += 3
    elif change60 >= 2.00:
        score += 2
    elif change60 >= 0.50:
        score += 1

    # Volume
    if volume >= 3.00:
        score += 3
    elif volume >= 2.00:
        score += 2
    elif volume >= 1.20:
        score += 1

    # Strong candle
    if candle_strong:
        score += 2

    # Retest
    if retest:
        score += 2

    # Close near resistance
    if distance <= 0.50:
        score += 2
    elif distance <= 1.00:
        score += 1

    # --------------------------------------------------------
    # BREAKOUT CONFIRMATION
    # --------------------------------------------------------

    breakout_confirmed = (
        price > resistance
        and candle_strong
        and volume >= MIN_CONFIRMED_VOLUME
        and change5 >= 0
    )

    # --------------------------------------------------------
    # EARLY CONDITIONS
    # --------------------------------------------------------

    early_valid = (
        score >= EARLY_MIN_SCORE
        and volume >= MIN_EARLY_VOLUME
        and distance <= EARLY_MAX_DISTANCE
        and change15 > 0
        and change60 > 0
    )

    # --------------------------------------------------------
    # WATCH CONDITIONS
    # --------------------------------------------------------

    watch_valid = (
        score >= WATCH_MIN_SCORE
        and volume >= MIN_EARLY_VOLUME
        and distance <= WATCH_MAX_DISTANCE
        and change60 > 0
    )

    category = None

    if breakout_confirmed and score >= CONFIRMED_MIN_SCORE:
        category = "CONFIRMED"

    elif early_valid:
        category = "EARLY"

    elif watch_valid:
        category = "WATCH"

    else:
        return None

    # --------------------------------------------------------
    # RISK
    # --------------------------------------------------------

    # Fixed risk model based on current price.
    sl = price * 0.955

    tp1 = price * 1.085
    tp2 = price * 1.120

    return {
        "symbol": symbol,
        "price": price,
        "change5": change5,
        "change15": change15,
        "change60": change60,
        "resistance": resistance,
        "distance": distance,
        "volume": volume,
        "retest": retest,
        "strong": candle_strong,
        "score": score,
        "category": category,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


# ============================================================
# SCAN ALL MARKETS
# ============================================================

def scan_markets(markets):

    results = []

    start = time.time()

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_market,
                symbol
            ): symbol
            for symbol in markets
        }

        for future in as_completed(futures):

            try:
                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                continue

    elapsed = time.time() - start

    return results, elapsed


# ============================================================
# SORT
# ============================================================

def sort_results(results):

    return sorted(
        results,
        key=lambda x: (
            x["score"],
            x["volume"],
            x["change60"],
        ),
        reverse=True,
    )


# ============================================================
# FORMAT NUMBER
# ============================================================

def fmt(value):

    if value >= 1000:
        return f"{value:.2f}"

    if value >= 1:
        return f"{value:.5f}"

    if value >= 0.01:
        return f"{value:.7f}"

    return f"{value:.10f}"


# ============================================================
# FORMAT RESULT
# ============================================================

def format_candidate(item, index, title):

    return (
        f"{title} #{index}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: {fmt(item['price'])}\n"
        f"📈 5M: {item['change5']:+.2f}%\n"
        f"📊 15M: {item['change15']:+.2f}%\n"
        f"🕐 1H: {item['change60']:+.2f}%\n"
        f"🎯 RESISTANCE: {fmt(item['resistance'])}\n"
        f"📏 DISTANCE: {item['distance']:+.2f}%\n"
        f"📦 VOLUME: {item['volume']:.2f}x\n"
        f"🔁 RETEST: {'YES' if item['retest'] else 'NO'}\n"
        f"🕯 STRONG CANDLE: {'YES' if item['strong'] else 'NO'}\n"
        f"🛑 SL: {fmt(item['sl'])}\n"
        f"🎯 TP1: {fmt(item['tp1'])}\n"
        f"🎯 TP2: {fmt(item['tp2'])}\n"
    )


# ============================================================
# BUILD TELEGRAM MESSAGE
# ============================================================

def build_message(markets_count, results, elapsed):

    confirmed = [
        x for x in results
        if x["category"] == "CONFIRMED"
    ]

    early = [
        x for x in results
        if x["category"] == "EARLY"
    ]

    watch = [
        x for x in results
        if x["category"] == "WATCH"
    ]

    confirmed = sort_results(
        confirmed
    )[:TOP_CONFIRMED]

    early = sort_results(
        early
    )[:TOP_EARLY]

    watch = sort_results(
        watch
    )[:TOP_WATCH]

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    lines.append("")
    lines.append(
        "🚀 FAST EARLY ENTRY + CONFIRMED BREAKOUT"
    )

    lines.append("")
    lines.append(
        "📡 TABDEAL API: OK"
    )

    lines.append(
        f"📊 USDT MARKETS: {markets_count}"
    )

    lines.append(
        f"⏱ TIMEFRAME: {TIMEFRAME}"
    )

    lines.append(
        "🕯 CLOSED CANDLE: YES"
    )

    lines.append(
        "🔧 REAL ORDERS: DISABLED"
    )

    lines.append(
        f"🕐 {now_utc()}"
    )

    # --------------------------------------------------------
    # CONFIRMED
    # --------------------------------------------------------

    lines.append("")
    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )
    lines.append(
        "🟢 CONFIRMED BUY"
    )
    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    if confirmed:

        for i, item in enumerate(
            confirmed,
            1
        ):
            lines.append(
                format_candidate(
                    item,
                    i,
                    "🟢 CONFIRMED BUY"
                )
            )

    else:
        lines.append(
            "No confirmed BUY signal."
        )

    # --------------------------------------------------------
    # EARLY
    # --------------------------------------------------------

    lines.append("")
    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )
    lines.append(
        "🟡 EARLY BUY"
    )
    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    if early:

        for i, item in enumerate(
            early,
            1
        ):
            lines.append(
                format_candidate(
                    item,
                    i,
                    "🟡 EARLY BUY"
                )
            )

    else:
        lines.append(
            "No early BUY signal."
        )

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    lines.append("")
    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )
    lines.append(
        "👀 WATCH"
    )
    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    if watch:

        for i, item in enumerate(
            watch,
            1
        ):
            lines.append(
                format_candidate(
                    item,
                    i,
                    "👀 WATCH"
                )
            )

    else:
        lines.append(
            "No WATCH candidates."
        )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    lines.append("")
    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        f"📌 TOTAL CANDIDATES: {len(results)}"
    )

    lines.append(
        f"⏱ SCAN TIME: {elapsed:.1f}s"
    )

    lines.append(
        "🔄 NEXT SCAN: ABOUT 5 MINUTES"
    )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    print(
        "📡 TABDEAL API: CONNECTING..."
    )

    print(
        "📊 SCAN: STARTING"
    )

    print(
        f"⏱ TIMEFRAME: {TIMEFRAME}"
    )

    print(
        "🔧 REAL ORDERS: DISABLED"
    )

    markets = get_usdt_markets()

    if not markets:

        message = (
            f"⚠️ ATI BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET DATA ERROR\n"
            f"🕐 {now_utc()}"
        )

        print(message)

        send_telegram(message)

        return

    print(
        f"📊 MARKETS FOUND: {len(markets)}"
    )

    results, elapsed = scan_markets(
        markets
    )

    message = build_message(
        len(markets),
        results,
        elapsed,
    )

    print("")
    print(message)

    sent = send_telegram(
        message
    )

    if sent:
        print(
            "\n📨 TELEGRAM: SENT"
        )
    else:
        print(
            "\n⚠️ TELEGRAM: NOT SENT"
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
