import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V37.4
# SMART UPWARD COIN SCANNER
# ============================================================

VERSION = "V37.4"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

MAX_MARKETS = 1000
TOP_RESULTS = 5
WATCH_RESULTS = 3

REQUEST_TIMEOUT = 8
MAX_WORKERS = 15

# Strong signal threshold
MIN_SCORE = 6

# Safety
REAL_TRADING = False
ORDER_EXECUTION = False

# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

SESSION = requests.Session()


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
# MARKET DISCOVERY
# ============================================================

def normalize_symbol(value):
    if value is None:
        return None

    return str(value).upper().replace("/", "")


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

        ts = int(
            trade["timestamp"] // 300000
        ) * 300000

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

    # Remove current unfinished candle
    if result:

        current_bucket = (
            int(time.time() // 300)
            * 300000
        )

        if result[-1]["timestamp"] >= current_bucket:
            result.pop()

    return result


# ============================================================
# MOMENTUM
# ============================================================

def timeframe_momentum(candles):

    if len(candles) < 15:
        return 0.0, 0.0, 0.0

    close = candles[-1]["close"]

    m5 = pct_change(
        candles[-2]["close"],
        close,
    )

    m15 = pct_change(
        candles[-4]["close"],
        close,
    )

    if len(candles) >= 13:

        h1 = pct_change(
            candles[-13]["close"],
            close,
        )

    else:

        h1 = pct_change(
            candles[0]["close"],
            close,
        )

    return m5, m15, h1


# ============================================================
# MARKET STRUCTURE
# ============================================================

def structure_score(candles):

    score = 0
    reasons = []

    if len(candles) < 12:
        return score, reasons

    recent = candles[-6:]

    # Higher closes
    if (
        recent[-1]["close"]
        > recent[-2]["close"]
        > recent[-3]["close"]
    ):
        score += 1
        reasons.append("HIGHER CLOSES")

    # Higher lows
    if (
        recent[-1]["low"]
        > recent[-3]["low"]
    ):
        score += 1
        reasons.append("HIGHER LOW")

    # Higher high
    previous_high = max(
        x["high"]
        for x in candles[-11:-1]
    )

    current_high = candles[-1]["high"]

    if current_high > previous_high:
        score += 1
        reasons.append("NEW HIGH")

    return score, reasons


# ============================================================
# BREAKOUT
# ============================================================

def breakout_analysis(candles):

    if len(candles) < 22:
        return 0, 0.0, []

    previous_high = max(
        x["high"]
        for x in candles[-21:-1]
    )

    close = candles[-1]["close"]

    breakout_pct = pct_change(
        previous_high,
        close,
    )

    score = 0
    reasons = []

    if breakout_pct > 0.03:

        score += 1
        reasons.append("BREAKOUT")

    if breakout_pct > 0.15:

        score += 1
        reasons.append("STRONG BREAKOUT")

    return score, breakout_pct, reasons


# ============================================================
# VOLUME
# ============================================================

def volume_analysis(candles):

    if len(candles) < 22:
        return 0, 0.0, []

    current_volume = candles[-1]["volume"]

    previous = [
        x["volume"]
        for x in candles[-21:-1]
        if x["volume"] > 0
    ]

    avg_volume = average(previous)

    if avg_volume <= 0:
        return 0, 0.0, []

    ratio = current_volume / avg_volume

    score = 0
    reasons = []

    if ratio >= 1.10:

        score += 1
        reasons.append("VOLUME UP")

    if ratio >= 1.60:

        score += 1
        reasons.append("VOLUME STRONG")

    return score, ratio, reasons


# ============================================================
# ENTRY QUALITY
# ============================================================

def entry_quality(candles, m5, m15):

    score = 0
    reasons = []

    if len(candles) < 15:
        return score, reasons

    current = candles[-1]

    open_price = current["open"]
    close = current["close"]

    body_pct = pct_change(
        open_price,
        close,
    )

    # Healthy bullish candle
    if body_pct > 0.05:

        score += 1
        reasons.append("HEALTHY ENTRY")

    # Avoid extreme late entries
    if m5 > 0 and m5 < 3.0:

        score += 1
        reasons.append("ENTRY NOT EXTREME")

    # Positive short and medium momentum
    if m5 > 0 and m15 > 0:

        score += 1
        reasons.append("MOMENTUM ALIGNED")

    # Avoid chasing a very large single candle
    if body_pct <= 2.5:

        score += 1
        reasons.append("NO CHASE")

    return score, reasons


# ============================================================
# SCORE ENGINE
# ============================================================

def calculate_score(candles):

    if len(candles) < 25:
        return None

    m5, m15, h1 = timeframe_momentum(
        candles
    )

    score = 0
    reasons = []

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if m5 > 0.08:

        score += 1
        reasons.append("5M UP")

    if m5 > 0.20:

        score += 1
        reasons.append("5M STRONG")

    if m15 > 0.10:

        score += 1
        reasons.append("15M UP")

    if m15 > 0.30:

        score += 1
        reasons.append("15M STRONG")

    if h1 > 0.15:

        score += 1
        reasons.append("1H UP")

    if h1 > 0.50:

        score += 1
        reasons.append("1H STRONG")

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    s_score, s_reasons = structure_score(
        candles
    )

    score += s_score
    reasons.extend(s_reasons)

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    b_score, breakout_pct, b_reasons = (
        breakout_analysis(candles)
    )

    score += b_score
    reasons.extend(b_reasons)

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    v_score, volume_ratio, v_reasons = (
        volume_analysis(candles)
    )

    score += v_score
    reasons.extend(v_reasons)

    # --------------------------------------------------------
    # ENTRY QUALITY
    # --------------------------------------------------------

    e_score, e_reasons = entry_quality(
        candles,
        m5,
        m15,
    )

    score += e_score
    reasons.extend(e_reasons)

    # --------------------------------------------------------
    # LATE-MOVE PENALTY
    # --------------------------------------------------------

    late_penalty = 0

    if m5 > 5.0:
        late_penalty += 2

    elif m5 > 3.0:
        late_penalty += 1

    if breakout_pct > 2.0:
        late_penalty += 1

    if late_penalty > 0:

        score -= late_penalty
        reasons.append(
            f"LATE PENALTY -{late_penalty}"
        )

    return {
        "score": score,
        "m5": m5,
        "m15": m15,
        "h1": h1,
        "volume_ratio": volume_ratio,
        "breakout_pct": breakout_pct,
        "reasons": reasons,
    }


# ============================================================
# LEVELS
# ============================================================

def calculate_levels(candles):

    price = candles[-1]["close"]

    recent = candles[-20:]

    swing_low = min(
        x["low"]
        for x in recent
    )

    if swing_low >= price:

        swing_low = price * 0.995

    sl = swing_low

    risk = price - sl

    if risk <= 0:

        risk = price * 0.005
        sl = price - risk

    tp1 = price + (
        risk * 1.5
    )

    tp2 = price + (
        risk * 2.5
    )

    return (
        price,
        sl,
        tp1,
        tp2,
    )


# ============================================================
# SYMBOL ANALYSIS
# ============================================================

def analyze_symbol(symbol):

    try:

        trades = get_trades(symbol)

        if not trades:
            return None

        candles = build_5m_candles(
            trades
        )

        if len(candles) < 25:
            return None

        analysis = calculate_score(
            candles
        )

        if not analysis:
            return None

        price, sl, tp1, tp2 = (
            calculate_levels(
                candles
            )
        )

        score = analysis["score"]

        # Keep watch candidates too
        if score < 3:
            return None

        return {
            "symbol": symbol,
            "score": score,
            "price": price,
            "m5": analysis["m5"],
            "m15": analysis["m15"],
            "h1": analysis["h1"],
            "volume_ratio": analysis[
                "volume_ratio"
            ],
            "breakout_pct": analysis[
                "breakout_pct"
            ],
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "reasons": analysis[
                "reasons"
            ],
        }

    except Exception as e:

        print(
            f"⚠️ {symbol}: "
            f"{str(e)[:80]}"
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
        f"💰 PRICE: "
        f"{format_price(item['price'])}\n"
        f"📈 5M: "
        f"{item['m5']:+.2f}%\n"
        f"📊 15M: "
        f"{item['m15']:+.2f}%\n"
        f"🚀 1H: "
        f"{item['h1']:+.2f}%\n"
        f"📦 VOL: "
        f"{item['volume_ratio']:.2f}x\n"
        f"💥 BREAKOUT: "
        f"{item['breakout_pct']:+.2f}%\n"
        f"🛑 SL: "
        f"{format_price(item['sl'])}\n"
        f"🎯 TP1: "
        f"{format_price(item['tp1'])}\n"
        f"🎯 TP2: "
        f"{format_price(item['tp2'])}\n"
        f"🔎 "
        f"{', '.join(item['reasons'][:10])}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    print("=" * 60)

    print(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    print()
    print(
        "🚀 SMART UPWARD COIN SCANNER"
    )

    print(
        "⏱ TIMEFRAME: 5m"
    )

    print(
        "✅ CLOSED CANDLE"
    )

    print(
        "📊 5M + 15M + 1H MOMENTUM"
    )

    print(
        "💥 BREAKOUT + STRUCTURE + VOLUME"
    )

    print(
        "🎯 ENTRY QUALITY ENGINE"
    )

    print(
        "🚫 LATE ENTRY FILTER"
    )

    print(
        "🔒 REAL TRADING: OFF"
    )

    print(
        "🔒 ORDER EXECUTION: OFF"
    )

    print("=" * 60)

    telegram_send(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 SMART UPWARD COIN SCANNER\n\n"
        f"📡 Starting scan...\n"
        f"🎯 ENTRY QUALITY ENGINE: ON\n"
        f"🚫 LATE ENTRY FILTER: ON\n"
        f"🔒 REAL TRADING: OFF"
    )

    markets = get_usdt_markets()

    if not markets:

        telegram_send(
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET DISCOVERY FAILED"
        )

        return

    print()
    print(
        "📡 TABDEAL API: OK"
    )

    print(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    print(
        f"⚡ PARALLEL WORKERS: "
        f"{MAX_WORKERS}"
    )

    print(
        "🔎 Scanning markets..."
    )

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

        for future in as_completed(
            futures
        ):

            completed += 1

            try:

                result = future.result()

                if result:
                    results.append(
                        result
                    )

            except Exception:
                pass

            if completed % 50 == 0:

                print(
                    f"🔎 Progress: "
                    f"{completed}/"
                    f"{len(markets)}"
                )

    scan_time = (
        time.time()
        - start_time
    )

    # ========================================================
    # SORT
    # ========================================================

    results.sort(
        key=lambda x: (
            x["score"],
            x["m15"],
            x["h1"],
            x["volume_ratio"],
        ),
        reverse=True,
    )

    strong_results = [
        x
        for x in results
        if x["score"] >= MIN_SCORE
    ]

    watch_results = results[
        :WATCH_RESULTS
    ]

    timestamp = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    # ========================================================
    # STRONG SIGNAL
    # ========================================================

    if strong_results:

        selected = (
            strong_results[
                :TOP_RESULTS
            ]
        )

        message = (
            f"⚡ ATI CRYPTO BOT "
            f"{VERSION}\n\n"
            f"🚀 STRONG UPWARD "
            f"SIGNALS\n\n"
            f"📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: "
            f"{len(markets)}\n"
            f"⭐ MIN SCORE: "
            f"{MIN_SCORE}\n\n"
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
            f"⏱ SCAN TIME: "
            f"{scan_time:.1f}s\n"
            f"🕐 {timestamp}\n"
            f"🔒 REAL TRADING: OFF"
        )

        telegram_send(
            message
        )

    # ========================================================
    # NO STRONG SIGNAL
    # ========================================================

    else:

        message = (
            f"⚡ ATI CRYPTO BOT "
            f"{VERSION}\n\n"
            f"📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: "
            f"{len(markets)}\n"
            f"❌ NO STRONG "
            f"UPWARD SIGNAL\n\n"
            f"⭐ MIN SCORE: "
            f"{MIN_SCORE}\n"
            f"⏱ SCAN TIME: "
            f"{scan_time:.1f}s\n"
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
                    f"📈 5M "
                    f"{item['m5']:+.2f}% | "
                    f"15M "
                    f"{item['m15']:+.2f}% | "
                    f"1H "
                    f"{item['h1']:+.2f}%\n"
                    f"📦 VOL "
                    f"{item['volume_ratio']:.2f}x\n"
                    f"💥 BO "
                    f"{item['breakout_pct']:+.2f}%\n\n"
                )

        else:

            message += (
                "هیچ حرکت صعودی "
                "قابل‌قبولی پیدا نشد.\n\n"
            )

        message += (
            "🔒 REAL TRADING: OFF\n"
            "🔒 ORDER EXECUTION: OFF"
        )

        telegram_send(
            message
        )

    print()
    print("=" * 60)

    print(
        f"✅ SCAN FINISHED: "
        f"{scan_time:.1f}s"
    )

    print(
        f"📊 CANDIDATES: "
        f"{len(results)}"
    )

    print(
        f"🚀 STRONG: "
        f"{len(strong_results)}"
    )

    print("=" * 60)


if __name__ == "__main__":
    main()
