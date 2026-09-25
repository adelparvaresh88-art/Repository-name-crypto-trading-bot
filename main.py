import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V37.3
# UPWARD COIN SCANNER
# ============================================================

VERSION = "V37.3"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 720
MAX_MARKETS = 1000
TOP_RESULTS = 5
WATCH_RESULTS = 3

REQUEST_TIMEOUT = 8
MAX_WORKERS = 15

# V37.3 - slightly easier than V37.2
MIN_SCORE = 5

# SAFETY
REAL_TRADING = False
ORDER_EXECUTION = False


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def telegram_send(message):
    print("\n" + message)

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM SECRETS NOT FOUND")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

        if response.ok:
            print("✅ TELEGRAM SENT")
            return True

        print("❌ TELEGRAM ERROR:", response.text[:300])
        return False

    except Exception as e:
        print("❌ TELEGRAM ERROR:", e)
        return False


# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()


def get_json(path, params=None):
    try:
        response = SESSION.get(
            BASE_URL + path,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()
        return response.json()

    except Exception:
        return None


# ============================================================
# HELPERS
# ============================================================

def as_list(data):
    if isinstance(data, list):
        return data

    if isinstance(data, tuple):
        return list(data)

    if isinstance(data, dict):
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
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                return list(value.values())

    return []


def first_value(item, keys, default=None):
    if not isinstance(item, dict):
        return default

    for key in keys:
        if key in item:
            return item[key]

    return default


def safe_float(value, default=None):
    try:
        return float(value)
    except Exception:
        return default


# ============================================================
# MARKET DISCOVERY
# ============================================================

def normalize_symbol(value):
    if value is None:
        return None

    value = str(value).upper().replace("/", "")

    return value


def get_usdt_markets():
    endpoints = [
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
        "/r/api/v1/tickers",
    ]

    markets = set()

    for endpoint in endpoints:
        data = get_json(endpoint)

        if data is None:
            continue

        items = as_list(data)

        for item in items:
            if isinstance(item, str):
                symbol = normalize_symbol(item)

            elif isinstance(item, dict):
                symbol = normalize_symbol(
                    first_value(
                        item,
                        [
                            "symbol",
                            "market",
                            "pair",
                            "name",
                            "code",
                        ],
                    )
                )

            else:
                continue

            if symbol and symbol.endswith("USDT"):
                markets.add(symbol)

        if len(markets) >= 100:
            break

    return sorted(markets)[:MAX_MARKETS]


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):
    data = get_json(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": 1000,
        },
    )

    return as_list(data)


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):
    if not isinstance(item, dict):
        return None

    price = first_value(
        item,
        [
            "price",
            "p",
            "rate",
        ],
    )

    quantity = first_value(
        item,
        [
            "quantity",
            "qty",
            "amount",
            "volume",
            "q",
        ],
        0,
    )

    timestamp = first_value(
        item,
        [
            "timestamp",
            "time",
            "T",
            "created_at",
            "createdAt",
        ],
    )

    price = safe_float(price)
    quantity = safe_float(quantity, 0)

    if price is None or price <= 0:
        return None

    if timestamp is None:
        timestamp = int(time.time() * 1000)

    try:
        timestamp = float(timestamp)
    except Exception:
        timestamp = time.time() * 1000

    # seconds -> milliseconds
    if timestamp < 10_000_000_000:
        timestamp *= 1000

    return {
        "price": price,
        "quantity": abs(quantity),
        "timestamp": timestamp,
    }


# ============================================================
# CANDLE BUILDER
# ============================================================

def build_5m_candles(trades):
    parsed = []

    for item in trades:
        trade = parse_trade(item)

        if trade:
            parsed.append(trade)

    if len(parsed) < 30:
        return []

    candles = {}

    for trade in parsed:
        ts = int(trade["timestamp"] // 300000) * 300000

        price = trade["price"]
        qty = trade["quantity"]

        if ts not in candles:
            candles[ts] = {
                "timestamp": ts,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }
        else:
            candle = candles[ts]

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

    result = sorted(
        candles.values(),
        key=lambda x: x["timestamp"],
    )

    # remove current unfinished candle
    if result:
        now_bucket = int(time.time() // 300) * 300000

        if result[-1]["timestamp"] >= now_bucket:
            result.pop()

    return result[-CANDLE_LIMIT:]


# ============================================================
# BASIC MATH
# ============================================================

def pct_change(old, new):
    if old is None or new is None:
        return 0.0

    if old == 0:
        return 0.0

    return ((new - old) / old) * 100.0


def average(values):
    if not values:
        return 0.0

    return sum(values) / len(values)


# ============================================================
# MOMENTUM
# ============================================================

def timeframe_momentum(candles):
    if len(candles) < 15:
        return 0.0, 0.0, 0.0

    close = candles[-1]["close"]

    # 5m
    old_5m = candles[-2]["close"]

    # 15m
    old_15m = candles[-4]["close"]

    # 1h
    if len(candles) >= 13:
        old_1h = candles[-13]["close"]
    else:
        old_1h = candles[0]["close"]

    m5 = pct_change(old_5m, close)
    m15 = pct_change(old_15m, close)
    h1 = pct_change(old_1h, close)

    return m5, m15, h1


# ============================================================
# SCORE ENGINE
# ============================================================

def calculate_score(candles):
    if len(candles) < 25:
        return 0, []

    current = candles[-1]

    close = current["close"]
    open_price = current["open"]

    m5, m15, h1 = timeframe_momentum(candles)

    score = 0
    reasons = []

    # --------------------------------------------------------
    # 5M MOMENTUM
    # --------------------------------------------------------

    if m5 > 0.08:
        score += 1
        reasons.append("5M UP")

    if m5 > 0.20:
        score += 1
        reasons.append("5M STRONG")

    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    if m15 > 0.10:
        score += 1
        reasons.append("15M UP")

    if m15 > 0.30:
        score += 1
        reasons.append("15M STRONG")

    # --------------------------------------------------------
    # 1H MOMENTUM
    # --------------------------------------------------------

    if h1 > 0.15:
        score += 1
        reasons.append("1H UP")

    if h1 > 0.50:
        score += 1
        reasons.append("1H STRONG")

    # --------------------------------------------------------
    # BULLISH BODY
    # --------------------------------------------------------

    body_pct = pct_change(
        open_price,
        close,
    )

    if body_pct > 0.05:
        score += 1
        reasons.append("BULLISH BODY")

    if body_pct > 0.20:
        score += 1
        reasons.append("STRONG BODY")

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    recent_volumes = [
        x["volume"]
        for x in candles[-21:-1]
        if x["volume"] > 0
    ]

    avg_volume = average(recent_volumes)

    volume_ratio = 0.0

    if avg_volume > 0:
        volume_ratio = current["volume"] / avg_volume

    if volume_ratio >= 1.10:
        score += 1
        reasons.append("VOLUME UP")

    if volume_ratio >= 1.60:
        score += 1
        reasons.append("VOLUME STRONG")

    # --------------------------------------------------------
    # HIGHER CLOSES
    # --------------------------------------------------------

    closes = [
        x["close"]
        for x in candles[-4:]
    ]

    if len(closes) == 4:
        if closes[-1] > closes[-2] > closes[-3]:
            score += 1
            reasons.append("HIGHER CLOSES")

    # --------------------------------------------------------
    # HIGHER LOW
    # --------------------------------------------------------

    lows = [
        x["low"]
        for x in candles[-6:]
    ]

    if len(lows) >= 5:
        if lows[-1] >= min(lows[:-1]):
            score += 1
            reasons.append("HIGHER LOW")

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    previous_highs = [
        x["high"]
        for x in candles[-21:-1]
    ]

    if previous_highs:
        previous_high = max(previous_highs)

        breakout_pct = pct_change(
            previous_high,
            close,
        )

        if breakout_pct > 0.03:
            score += 1
            reasons.append("BREAKOUT")

        if breakout_pct > 0.15:
            score += 1
            reasons.append("STRONG BREAKOUT")

    return score, reasons


# ============================================================
# LEVELS
# ============================================================

def calculate_levels(candles):
    price = candles[-1]["close"]

    recent = candles[-20:]

    swing_low = min(
        candle["low"]
        for candle in recent
    )

    # safety fallback
    if swing_low >= price:
        swing_low = price * 0.995

    sl = swing_low

    risk = price - sl

    if risk <= 0:
        risk = price * 0.005
        sl = price - risk

    tp1 = price + (risk * 1.5)
    tp2 = price + (risk * 2.5)

    return price, sl, tp1, tp2


# ============================================================
# SYMBOL ANALYSIS
# ============================================================

def analyze_symbol(symbol):
    try:
        trades = get_trades(symbol)

        if not trades:
            return None

        candles = build_5m_candles(trades)

        if len(candles) < 25:
            return None

        score, reasons = calculate_score(candles)

        m5, m15, h1 = timeframe_momentum(candles)

        price, sl, tp1, tp2 = calculate_levels(
            candles
        )

        # Watch candidates can be weaker
        if score < 3:
            return None

        volume_now = candles[-1]["volume"]

        avg_volumes = [
            x["volume"]
            for x in candles[-21:-1]
            if x["volume"] > 0
        ]

        avg_vol = average(avg_volumes)

        volume_ratio = 0.0

        if avg_vol > 0:
            volume_ratio = volume_now / avg_vol

        return {
            "symbol": symbol,
            "score": score,
            "price": price,
            "m5": m5,
            "m15": m15,
            "h1": h1,
            "volume_ratio": volume_ratio,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "reasons": reasons,
        }

    except Exception as e:
        print(
            f"⚠️ {symbol}: {str(e)[:80]}"
        )

        return None


# ============================================================
# FORMAT
# ============================================================

def format_price(value):
    if value >= 100:
        return f"{value:.2f}"

    if value >= 1:
        return f"{value:.4f}"

    if value >= 0.01:
        return f"{value:.6f}"

    return f"{value:.8f}"


def format_result(item, title):
    return (
        f"{title}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: {format_price(item['price'])}\n"
        f"📈 5M: {item['m5']:+.2f}%\n"
        f"📊 15M: {item['m15']:+.2f}%\n"
        f"🚀 1H: {item['h1']:+.2f}%\n"
        f"📦 VOL: {item['volume_ratio']:.2f}x\n"
        f"🛑 SL: {format_price(item['sl'])}\n"
        f"🎯 TP1: {format_price(item['tp1'])}\n"
        f"🎯 TP2: {format_price(item['tp2'])}\n"
        f"🔎 {', '.join(item['reasons'][:8])}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    print("=" * 55)
    print(f"⚡ ATI CRYPTO BOT {VERSION}")
    print()
    print("🚀 UPWARD COIN SCANNER")
    print("⏱ TIMEFRAME: 5m")
    print("✅ CLOSED CANDLE")
    print("📊 5M + 15M + 1H MOMENTUM")
    print("💥 BREAKOUT + STRUCTURE + VOLUME")
    print("🔒 REAL TRADING: OFF")
    print("🔒 ORDER EXECUTION: OFF")
    print("=" * 55)

    telegram_send(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 UPWARD COIN SCANNER\n\n"
        f"📡 Starting scan...\n"
        f"🔒 REAL TRADING: OFF"
    )

    markets = get_usdt_markets()

    if not markets:
        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET DISCOVERY FAILED"
        )

        telegram_send(message)
        return

    print()
    print("📡 TABDEAL API: OK")
    print(f"📊 USDT MARKETS: {len(markets)}")
    print(f"⚡ PARALLEL WORKERS: {MAX_WORKERS}")
    print("🔎 Scanning markets...")

    results = []

    completed = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol,
            ): symbol
            for symbol in markets
        }

        for future in as_completed(futures):

            completed += 1

            try:
                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                pass

            if completed % 50 == 0:
                print(
                    f"🔎 Progress: "
                    f"{completed}/{len(markets)}"
                )

    scan_time = time.time() - start_time

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["score"],
            x["m5"],
            x["m15"],
            x["volume_ratio"],
        ),
        reverse=True,
    )

    strong_results = [
        x
        for x in results
        if x["score"] >= MIN_SCORE
    ]

    watch_results = results[:WATCH_RESULTS]

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    # --------------------------------------------------------
    # STRONG SIGNALS
    # --------------------------------------------------------

    if strong_results:

        selected = strong_results[:TOP_RESULTS]

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"🚀 STRONG UPWARD SIGNALS\n\n"
            f"📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: {len(markets)}\n"
            f"⭐ MIN SCORE: {MIN_SCORE}\n\n"
        )

        for index, item in enumerate(
            selected,
            start=1,
        ):
            message += (
                format_result(
                    item,
                    f"#{index} SIGNAL",
                )
                + "\n\n"
            )

        message += (
            f"⏱ SCAN TIME: {scan_time:.1f}s\n"
            f"🕐 {timestamp}\n"
            f"🔒 REAL TRADING: OFF"
        )

        telegram_send(message)

    # --------------------------------------------------------
    # NO STRONG SIGNAL
    # --------------------------------------------------------

    else:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: {len(markets)}\n"
            f"❌ NO STRONG UPWARD SIGNAL\n\n"
            f"⭐ MIN SCORE: {MIN_SCORE}\n"
            f"⏱ SCAN TIME: {scan_time:.1f}s\n"
            f"🕐 {timestamp}\n\n"
            f"👀 TOP WATCHLIST:\n\n"
        )

        if watch_results:

            for index, item in enumerate(
                watch_results,
                start=1,
            ):

                message += (
                    f"#{index} "
                    f"{item['symbol']} "
                    f"⭐{item['score']}\n"
                    f"📈 5M {item['m5']:+.2f}% | "
                    f"15M {item['m15']:+.2f}% | "
                    f"1H {item['h1']:+.2f}%\n"
                    f"📦 VOL {item['volume_ratio']:.2f}x\n\n"
                )

        else:

            message += (
                "هیچ حرکت صعودی قابل‌قبولی "
                "پیدا نشد.\n\n"
            )

        message += (
            "🔒 REAL TRADING: OFF\n"
            "🔒 ORDER EXECUTION: OFF"
        )

        telegram_send(message)

    print()
    print("=" * 55)
    print(
        f"✅ SCAN FINISHED IN "
        f"{scan_time:.1f}s"
    )
    print(
        f"📊 RESULTS: {len(results)}"
    )
    print(
        f"🚀 STRONG: {len(strong_results)}"
    )
    print("=" * 55)


if __name__ == "__main__":
    main()
