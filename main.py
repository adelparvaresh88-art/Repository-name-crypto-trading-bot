import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V37.1
# UPWARD COIN SCANNER
# ============================================================

VERSION = "V37.1"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 720
MAX_MARKETS = 1000
TOP_RESULTS = 5

REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.03

MIN_SCORE = 6


# ============================================================
# SAFETY
# ============================================================

REAL_TRADING = False
ORDER_EXECUTION = False


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-CRYPTO-BOT/37.1",
        "Accept": "application/json",
    }
)


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    "",
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    "",
).strip()


def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/sendMessage"
        )

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        return response.ok

    except Exception:
        return False


# ============================================================
# SAFE JSON
# ============================================================

def get_json(url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            return None

        try:
            return response.json()
        except Exception:
            return None

    except Exception:
        return None


# ============================================================
# GENERIC HELPERS
# ============================================================

def as_list(value):

    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, dict):

        for key in (
            "data",
            "result",
            "results",
            "items",
            "symbols",
            "markets",
            "ticker",
            "tickers",
        ):

            item = value.get(key)

            if isinstance(item, list):
                return item

        return []

    return []


def safe_float(value, default=None):

    try:

        if value is None:
            return default

        if isinstance(value, bool):
            return default

        return float(value)

    except Exception:
        return default


def safe_int(value, default=None):

    try:
        return int(float(value))

    except Exception:
        return default


def now_utc():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def pct_change(old, new):

    if old is None or new is None:
        return 0.0

    if old == 0:
        return 0.0

    return (
        (new - old)
        / old
    ) * 100.0


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(value):

    if value is None:
        return None

    text = str(value).upper().strip()

    text = text.replace("-", "")
    text = text.replace("_", "")
    text = text.replace("/", "")

    if text.endswith("USDT"):
        return text

    return None


def extract_symbol(item):

    if isinstance(item, str):
        return normalize_symbol(item)

    if not isinstance(item, dict):
        return None

    for key in (
        "symbol",
        "pair",
        "market",
        "instrument",
        "code",
        "name",
    ):

        value = item.get(key)

        symbol = normalize_symbol(value)

        if symbol:
            return symbol

    return None


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_markets():

    endpoints = [
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
        "/r/api/v1/tickers",
    ]

    symbols = set()

    for endpoint in endpoints:

        data = get_json(
            BASE_URL + endpoint
        )

        if data is None:
            continue

        items = as_list(data)

        for item in items:

            symbol = extract_symbol(item)

            if symbol and symbol.endswith("USDT"):
                symbols.add(symbol)

        if symbols:
            break

    symbols = {
        s
        for s in symbols
        if (
            s
            and s.endswith("USDT")
            and len(s) > 4
            and len(s) < 30
        )
    }

    symbols = sorted(symbols)

    if MAX_MARKETS:
        symbols = symbols[:MAX_MARKETS]

    return symbols


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):

    data = get_json(
        BASE_URL + "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if data is None:
        return []

    return as_list(data)


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if isinstance(item, list):

        if len(item) < 2:
            return None

        price = safe_float(item[0])
        qty = safe_float(item[1])

        timestamp = None

        if len(item) >= 3:
            timestamp = safe_int(item[2])

        if price is None or qty is None:
            return None

        return {
            "price": price,
            "qty": abs(qty),
            "timestamp": timestamp,
        }

    if not isinstance(item, dict):
        return None

    price = None
    qty = None
    timestamp = None

    for key in (
        "price",
        "p",
        "trade_price",
        "rate",
    ):

        if key in item:

            price = safe_float(
                item.get(key)
            )

            if price is not None:
                break

    for key in (
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
    ):

        if key in item:

            qty = safe_float(
                item.get(key)
            )

            if qty is not None:
                break

    for key in (
        "timestamp",
        "time",
        "T",
        "created_at",
        "createdAt",
    ):

        if key in item:

            timestamp = safe_int(
                item.get(key)
            )

            if timestamp is not None:
                break

    if price is None or qty is None:
        return None

    return {
        "price": price,
        "qty": abs(qty),
        "timestamp": timestamp,
    }


# ============================================================
# TIMESTAMP
# ============================================================

def normalize_timestamp(ts):

    if ts is None:
        return None

    if ts > 10_000_000_000:
        return ts / 1000.0

    return float(ts)


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade is None:
            continue

        ts = normalize_timestamp(
            trade["timestamp"]
        )

        if ts is None:
            continue

        trade["timestamp"] = ts

        parsed.append(trade)

    if not parsed:
        return []

    parsed.sort(
        key=lambda x: x["timestamp"]
    )

    buckets = {}

    for trade in parsed:

        bucket = (
            int(
                trade["timestamp"] // 300
            )
            * 300
        )

        if bucket not in buckets:

            buckets[bucket] = {
                "timestamp": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
                "trades": 0,
            }

        candle = buckets[bucket]

        price = trade["price"]
        qty = trade["qty"]

        candle["high"] = max(
            candle["high"],
            price,
        )

        candle["low"] = min(
            candle["low"],
            price,
        )

        candle["close"] = price

        candle["volume"] += qty
        candle["trades"] += 1

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["timestamp"]
    )

    current_bucket = (
        int(time.time() // 300)
        * 300
    )

    candles = [
        c
        for c in candles
        if c["timestamp"] < current_bucket
    ]

    return candles[-CANDLE_LIMIT:]


# ============================================================
# CANDLE CONTINUITY
# ============================================================

def has_continuous_candles(
    candles,
    required_bars,
):

    if len(candles) < required_bars:
        return False

    recent = candles[
        -required_bars:
    ]

    for i in range(1, len(recent)):

        previous_ts = recent[
            i - 1
        ]["timestamp"]

        current_ts = recent[
            i
        ]["timestamp"]

        if (
            current_ts
            - previous_ts
            != 300
        ):
            return False

    return True


# ============================================================
# TIMEFRAME MOMENTUM
# ============================================================

def timeframe_momentum(
    candles,
    minutes,
):

    bars = minutes // 5
    required = bars + 1

    if not has_continuous_candles(
        candles,
        required,
    ):
        return None

    old = candles[
        -bars - 1
    ]["close"]

    new = candles[
        -1
    ]["close"]

    return pct_change(
        old,
        new,
    )


# ============================================================
# CANDLE BODY
# ============================================================

def candle_body_percent(candle):

    if candle is None:
        return 0.0

    open_price = candle.get("open")
    close_price = candle.get("close")

    if open_price in (None, 0):
        return 0.0

    return (
        (close_price - open_price)
        / open_price
    ) * 100.0


# ============================================================
# RECENT HIGH / LOW
# ============================================================

def recent_high(candles, count=20):

    if len(candles) < count:
        return None

    values = [
        c["high"]
        for c in candles[-count:]
    ]

    return max(values)


def recent_low(candles, count=20):

    if len(candles) < count:
        return None

    values = [
        c["low"]
        for c in candles[-count:]
    ]

    return min(values)


# ============================================================
# BREAKOUT
# ============================================================

def breakout_strength(candles):

    if len(candles) < 21:
        return 0.0

    previous_high = recent_high(
        candles[:-1],
        20,
    )

    last_close = candles[-1]["close"]

    if previous_high in (None, 0):
        return 0.0

    return pct_change(
        previous_high,
        last_close,
    )


# ============================================================
# VOLUME MOMENTUM
# ============================================================

def volume_ratio(candles):

    if len(candles) < 21:
        return 0.0

    previous = candles[-21:-1]

    volumes = [
        c["volume"]
        for c in previous
        if c["volume"] is not None
    ]

    if not volumes:
        return 0.0

    average_volume = (
        sum(volumes)
        / len(volumes)
    )

    if average_volume <= 0:
        return 0.0

    current_volume = candles[-1]["volume"]

    return (
        current_volume
        / average_volume
    )


# ============================================================
# PRICE STRUCTURE
# ============================================================

def higher_closes(candles, count=3):

    if len(candles) < count + 1:
        return False

    recent = candles[-count:]

    for i in range(1, len(recent)):

        if (
            recent[i]["close"]
            <= recent[i - 1]["close"]
        ):
            return False

    return True


def higher_lows(candles, count=3):

    if len(candles) < count + 1:
        return False

    recent = candles[-count:]

    for i in range(1, len(recent)):

        if (
            recent[i]["low"]
            <= recent[i - 1]["low"]
        ):
            return False

    return True


# ============================================================
# SCORE ENGINE
# ============================================================

def calculate_score(candles):

    if len(candles) < 25:
        return None

    m5 = timeframe_momentum(
        candles,
        5,
    )

    m15 = timeframe_momentum(
        candles,
        15,
    )

    h1 = timeframe_momentum(
        candles,
        60,
    )

    if (
        m5 is None
        or m15 is None
        or h1 is None
    ):
        return None

    last = candles[-1]

    score = 0
    reasons = []

    # --------------------------------------------------------
    # 5M MOMENTUM
    # --------------------------------------------------------

    if m5 > 0.10:
        score += 1
        reasons.append("5M UP")

    if m5 > 0.25:
        score += 1
        reasons.append("5M STRONG")

    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    if m15 > 0.15:
        score += 1
        reasons.append("15M UP")

    if m15 > 0.40:
        score += 1
        reasons.append("15M STRONG")

    # --------------------------------------------------------
    # 1H MOMENTUM
    # --------------------------------------------------------

    if h1 > 0.20:
        score += 1
        reasons.append("1H UP")

    if h1 > 0.60:
        score += 1
        reasons.append("1H STRONG")

    # --------------------------------------------------------
    # CANDLE BODY
    # --------------------------------------------------------

    body = candle_body_percent(last)

    if body > 0.10:
        score += 1
        reasons.append("BULL CANDLE")

    if body > 0.30:
        score += 1
        reasons.append("STRONG BODY")

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    vr = volume_ratio(candles)

    if vr >= 1.20:
        score += 1
        reasons.append("VOLUME UP")

    if vr >= 1.80:
        score += 1
        reasons.append("VOLUME STRONG")

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    if higher_closes(candles, 3):
        score += 1
        reasons.append("HIGHER CLOSES")

    if higher_lows(candles, 3):
        score += 1
        reasons.append("HIGHER LOWS")

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    breakout = breakout_strength(candles)

    if breakout > 0.05:
        score += 1
        reasons.append("BREAKOUT")

    if breakout > 0.20:
        score += 1
        reasons.append("STRONG BREAKOUT")

    return {
        "score": score,
        "m5": m5,
        "m15": m15,
        "h1": h1,
        "body": body,
        "volume_ratio": vr,
        "breakout": breakout,
        "reasons": reasons,
    }


# ============================================================
# TRADE LEVELS
# ============================================================

def calculate_levels(candles):

    if not candles:
        return None

    price = candles[-1]["close"]

    low = recent_low(
        candles,
        20,
    )

    if low is None or low <= 0:
        sl = price * 0.995
    else:
        sl = low

        if sl >= price:
            sl = price * 0.995

    risk = price - sl

    if risk <= 0:
        risk = price * 0.005

    tp1 = price + (
        risk * 1.5
    )

    tp2 = price + (
        risk * 2.5
    )

    return {
        "entry": price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(symbol):

    trades = get_trades(symbol)

    if not trades:
        return None

    candles = build_candles(
        trades
    )

    if len(candles) < 25:
        return None

    result = calculate_score(
        candles
    )

    if result is None:
        return None

    if result["score"] < MIN_SCORE:
        return None

    levels = calculate_levels(
        candles
    )

    if levels is None:
        return None

    result.update(
        {
            "symbol": symbol,
            "candles": len(candles),
            "price": candles[-1]["close"],
            "levels": levels,
        }
    )

    return result


# ============================================================
# SORT RESULTS
# ============================================================

def sort_results(results):

    return sorted(
        results,
        key=lambda x: (
            x.get("score", 0),
            x.get("m15", 0),
            x.get("m5", 0),
        ),
        reverse=True,
    )


# ============================================================
# TELEGRAM FORMAT
# ============================================================

def format_signal(item, rank):

    symbol = item["symbol"]
    score = item["score"]

    price = item["price"]

    levels = item["levels"]

    m5 = item["m5"]
    m15 = item["m15"]
    h1 = item["h1"]

    vr = item["volume_ratio"]

    reasons = item["reasons"]

    return (
        f"#{rank} 🚀 {symbol}\n"
        f"🟢 BUY WATCH\n"
        f"⭐ SCORE: {score}\n"
        f"💰 PRICE: {price:.8g}\n"
        f"📈 5M: {m5:+.2f}%\n"
        f"📈 15M: {m15:+.2f}%\n"
        f"📈 1H: {h1:+.2f}%\n"
        f"📊 VOL: {vr:.2f}x\n"
        f"🛑 SL: {levels['sl']:.8g}\n"
        f"🎯 TP1: {levels['tp1']:.8g}\n"
        f"🎯 TP2: {levels['tp2']:.8g}\n"
        f"🔎 {', '.join(reasons)}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    header = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 UPWARD COIN SCANNER\n\n"
        f"⏱ Timeframe: {TIMEFRAME}\n"
        f"✅ CLOSED CANDLE\n"
        f"📊 5M + 15M + 1H MOMENTUM\n"
        f"💥 BREAKOUT + STRUCTURE + VOLUME\n"
        f"🔒 REAL TRADING: {'ON' if REAL_TRADING else 'OFF'}\n"
        f"🔒 ORDER EXECUTION: {'ON' if ORDER_EXECUTION else 'OFF'}\n"
        f"\n📡 Scanning..."
    )

    print(header)

    telegram_send(header)

    markets = get_markets()

    if not markets:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET DISCOVERY FAILED\n"
            f"🕐 {now_utc()}"
        )

        print(message)
        telegram_send(message)
        return

    api_message = (
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"🕐 {now_utc()}"
    )

    print(api_message)

    results = []

    for index, symbol in enumerate(
        markets,
        start=1,
    ):

        try:

            result = analyze_symbol(
                symbol
            )

            if result is not None:
                results.append(result)

        except Exception as exc:

            print(
                f"⚠️ {symbol}: {exc}"
            )

        if (
            SLEEP_BETWEEN_MARKETS
            > 0
        ):
            time.sleep(
                SLEEP_BETWEEN_MARKETS
            )

    results = sort_results(
        results
    )

    results = results[
        :TOP_RESULTS
    ]

    elapsed = (
        time.time()
        - start_time
    )

    print(
        f"⏱ Scan time: {elapsed:.1f}s"
    )

    # --------------------------------------------------------
    # SIGNAL FOUND
    # --------------------------------------------------------

    if results:

        message_parts = [
            f"⚡ ATI CRYPTO BOT {VERSION}",
            "",
            "🚀 TOP UPWARD COINS",
            "",
            f"📊 MARKETS: {len(markets)}",
            f"🎯 RESULTS: {len(results)}",
            f"⏱ SCAN: {elapsed:.1f}s",
            "",
        ]

        for rank, item in enumerate(
            results,
            start=1,
        ):

            block = format_signal(
                item,
                rank,
            )

            print()
            print(block)

            message_parts.append(
                block
            )

            message_parts.append(
                ""
            )

        message = "\n".join(
            message_parts
        )

        telegram_send(message)

        return

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    no_signal = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 UPWARD COIN SCANNER\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"❌ NO STRONG UPWARD SIGNAL\n\n"
        f"🔎 Minimum Score: {MIN_SCORE}\n"
        f"⏱ Scan: {elapsed:.1f}s\n"
        f"🕐 {now_utc()}"
    )

    print(no_signal)

    # Telegram test is sent even with NO SIGNAL
    telegram_send(no_signal)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
