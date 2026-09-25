import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V37.6
# ROBUST TABDEAL USDT MARKET SCANNER
# ============================================================

VERSION = "V37.6"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 720
MAX_MARKETS = 1000
TOP_RESULTS = 5
MIN_SCORE = 6

REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.05

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT/37.6",
    "Accept": "application/json",
})


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        if isinstance(value, bool):
            return default

        return float(value)
    except Exception:
        return default


def get_json(path, params=None):
    url = BASE_URL + path

    try:
        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    except Exception as exc:
        print(f"API ERROR {path}: {exc}")
        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are not configured.")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print("Telegram ERROR:", response.text)
        return False

    except Exception as exc:
        print("Telegram ERROR:", exc)
        return False


# ============================================================
# MARKET EXTRACTION
# ============================================================

def extract_market_list(data):
    """
    Tabdeal ممکن است پاسخ Market List را با ساختارهای مختلف برگرداند.

    این تابع همه حالت‌های رایج را بررسی می‌کند:
    - list
    - {"data": [...]}
    - {"result": [...]}
    - {"symbols": [...]}
    - {"markets": [...]}
    - {"data": {"symbols": [...]}}
    - {"data": {"markets": [...]}}
    """

    if data is None:
        return []

    # --------------------------------------------------------
    # حالت 1: پاسخ مستقیم لیست
    # --------------------------------------------------------
    if isinstance(data, list):
        return data

    # --------------------------------------------------------
    # حالت 2: پاسخ دیکشنری
    # --------------------------------------------------------
    if isinstance(data, dict):

        possible_keys = [
            "data",
            "result",
            "symbols",
            "markets",
            "items",
            "rows",
        ]

        for key in possible_keys:
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                nested = extract_market_list(value)

                if nested:
                    return nested

    return []


def normalize_symbol(item):
    """
    استخراج نام Symbol از فرمت‌های مختلف.
    """

    if isinstance(item, str):
        return item.upper()

    if not isinstance(item, dict):
        return ""

    possible_keys = [
        "symbol",
        "market",
        "pair",
        "name",
        "code",
        "instrument",
        "ticker",
    ]

    for key in possible_keys:
        value = item.get(key)

        if isinstance(value, str):
            value = value.upper().replace("-", "").replace("_", "")

            if value:
                return value

    return ""


def load_usdt_markets():
    """
    دریافت لیست بازارهای USDT با چند Endpoint احتمالی.
    """

    endpoints = endpoints = [
    "/r/api/v1/exchangeInfo",
]

    for endpoint in endpoints:

        print(f"Loading markets: {endpoint}")

        data = get_json(endpoint)

        if data is None:
            continue

        raw_markets = extract_market_list(data)

        if not raw_markets:
            continue

        symbols = []

        for item in raw_markets:

            symbol = normalize_symbol(item)

            if not symbol:
                continue

            # فقط USDT
            if not symbol.endswith("USDT"):
                continue

            # حذف موارد غیرقابل استفاده
            if len(symbol) < 7:
                continue

            symbols.append(symbol)

        symbols = sorted(set(symbols))

        if symbols:
            print(
                f"MARKETS OK: {len(symbols)} USDT markets "
                f"from {endpoint}"
            )

            return symbols[:MAX_MARKETS]

    print("Could not load USDT markets from available endpoints.")
    return []


# ============================================================
# TRADES
# ============================================================

def load_trades(symbol, limit=1000):

    data = get_json(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": limit,
        },
    )

    if data is None:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in [
            "data",
            "result",
            "trades",
            "items",
        ]:

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

    price = 0.0
    quantity = 0.0
    timestamp = None

    for key in [
        "price",
        "p",
        "rate",
    ]:
        if key in item:
            price = safe_float(item.get(key))
            if price > 0:
                break

    for key in [
        "qty",
        "quantity",
        "amount",
        "q",
        "volume",
    ]:
        if key in item:
            quantity = safe_float(item.get(key))
            if quantity > 0:
                break

    for key in [
        "timestamp",
        "time",
        "T",
        "date",
    ]:
        if key in item:
            timestamp = item.get(key)
            break

    if price <= 0:
        return None

    if quantity <= 0:
        quantity = 1.0

    return {
        "price": price,
        "quantity": quantity,
        "timestamp": timestamp,
    }


# ============================================================
# BUILD 5M CANDLES FROM TRADES
# ============================================================

def build_candles(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade is None:
            continue

        ts = trade["timestamp"]

        try:
            ts = float(ts)

            # milliseconds
            if ts > 100000000000:
                ts = ts / 1000

        except Exception:
            continue

        trade["timestamp"] = ts

        parsed.append(trade)

    if not parsed:
        return []

    parsed.sort(key=lambda x: x["timestamp"])

    candles = {}

    bucket_seconds = 5 * 60

    for trade in parsed:

        bucket = int(
            trade["timestamp"] // bucket_seconds
        ) * bucket_seconds

        price = trade["price"]
        qty = trade["quantity"]

        if bucket not in candles:

            candles[bucket] = {
                "timestamp": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }

        else:

            candle = candles[bucket]

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

    return list(
        sorted(
            candles.values(),
            key=lambda x: x["timestamp"],
        )
    )


# ============================================================
# MOMENTUM
# ============================================================

def percentage_change(old, new):

    if old <= 0:
        return 0.0

    return ((new - old) / old) * 100.0


def momentum(candles, candle_count):

    if len(candles) < candle_count + 1:
        return 0.0

    old_price = candles[-(candle_count + 1)]["close"]
    new_price = candles[-1]["close"]

    return percentage_change(
        old_price,
        new_price,
    )


# ============================================================
# SCORE
# ============================================================

def calculate_score(candles):

    if len(candles) < 10:
        return None

    # آخرین کندل بسته‌شده
    closed = candles[:-1]

    if len(closed) < 10:
        return None

    last = closed[-1]
    price = last["close"]

    if price <= 0:
        return None

    score = 0

    # --------------------------------------------------------
    # 5M MOMENTUM
    # --------------------------------------------------------

    m5 = momentum(closed, 1)

    if m5 > 0.10:
        score += 2

    elif m5 > 0.03:
        score += 1

    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    m15 = momentum(closed, 3)

    if m15 > 0.20:
        score += 3

    elif m15 > 0.08:
        score += 2

    elif m15 > 0:
        score += 1

    # --------------------------------------------------------
    # 1H MOMENTUM
    # --------------------------------------------------------

    m1h = momentum(closed, 12)

    if m1h > 0.50:
        score += 3

    elif m1h > 0.20:
        score += 2

    elif m1h > 0:
        score += 1

    # --------------------------------------------------------
    # CANDLE STRUCTURE
    # --------------------------------------------------------

    previous = closed[-2]

    if last["close"] > last["open"]:
        score += 1

    if last["close"] > previous["high"]:
        score += 2

    # --------------------------------------------------------
    # HIGHER HIGH
    # --------------------------------------------------------

    recent = closed[-6:]

    if len(recent) >= 6:

        previous_high = max(
            c["high"]
            for c in recent[:-1]
        )

        if last["high"] > previous_high:
            score += 2

    return {
        "score": score,
        "price": price,
        "m5": m5,
        "m15": m15,
        "m1h": m1h,
        "candle": last,
    }


# ============================================================
# SIGNAL
# ============================================================

def analyze_symbol(symbol):

    trades = load_trades(
        symbol,
        limit=1000,
    )

    if not trades:
        return None

    candles = build_candles(trades)

    if len(candles) < 15:
        return None

    result = calculate_score(candles)

    if result is None:
        return None

    if result["score"] < MIN_SCORE:
        return None

    price = result["price"]

    # محافظه‌کارانه برای Scanner
    sl = price * 0.995
    tp1 = price * 1.008
    tp2 = price * 1.015

    return {
        "symbol": symbol,
        "score": result["score"],
        "price": price,
        "m5": result["m5"],
        "m15": result["m15"],
        "m1h": result["m1h"],
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


# ============================================================
# SCANNER
# ============================================================

def scan_markets(markets):

    signals = []

    total = len(markets)

    print(
        f"Scanning {total} USDT markets..."
    )

    for index, symbol in enumerate(markets, 1):

        try:

            result = analyze_symbol(symbol)

            if result is not None:
                signals.append(result)

        except Exception as exc:

            print(
                f"{symbol} ERROR: {exc}"
            )

        if index % 50 == 0:

            print(
                f"Progress: {index}/{total}"
            )

        time.sleep(
            SLEEP_BETWEEN_MARKETS
        )

    signals.sort(
        key=lambda x: (
            x["score"],
            x["m15"],
            x["m5"],
        ),
        reverse=True,
    )

    return signals[:TOP_RESULTS]


# ============================================================
# FORMAT TELEGRAM
# ============================================================

def format_signal_message(signals, market_count):

    lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "",
        "🚀 STRONG UPWARD SIGNALS",
        "",
        "📡 TABDEAL API: OK",
        f"📊 USDT MARKETS: {market_count}",
        f"⭐ MIN SCORE: {MIN_SCORE}",
        "",
    ]

    if not signals:

        lines.extend([
            "❌ NO STRONG SIGNAL",
            "",
            "Scanner completed successfully.",
            "",
            f"🕐 {now_utc()}",
        ])

        return "\n".join(lines)

    for index, signal in enumerate(signals, 1):

        lines.extend([
            f"#{index} SIGNAL",
            f"🪙 {signal['symbol']}",
            f"⭐ SCORE: {signal['score']}",
            f"💰 PRICE: {signal['price']:.8f}",
            f"📈 5M: {signal['m5']:+.2f}%",
            f"📊 15M: {signal['m15']:+.2f}%",
            f"⏱ 1H: {signal['m1h']:+.2f}%",
            "",
            f"🛑 SL: {signal['sl']:.8f}",
            f"🎯 TP1: {signal['tp1']:.8f}",
            f"🎯 TP2: {signal['tp2']:.8f}",
            "",
        ])

    lines.append(
        f"🕐 {now_utc()}"
    )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print(f"ATI CRYPTO BOT {VERSION}")
    print("ROBUST TABDEAL USDT MARKET SCANNER")
    print("=" * 60)

    print()
    print("Loading Tabdeal USDT markets...")

    markets = load_usdt_markets()

    if not markets:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "❌ TABDEAL MARKET ERROR\n"
            "Could not load USDT markets.\n\n"
            f"🕐 {now_utc()}"
        )

        print(message)

        send_telegram(message)

        return

    print()
    print(
        f"✅ USDT MARKETS: {len(markets)}"
    )

    signals = scan_markets(markets)

    message = format_signal_message(
        signals,
        len(markets),
    )

    print()
    print(message)

    send_telegram(message)


if __name__ == "__main__":
    main()
