import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.1
# FAST EARLY ENTRY + CONFIRMED BREAKOUT
# FIXED MARKET DISCOVERY
# ============================================================

VERSION = "V39.1"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000

REQUEST_TIMEOUT = 10
MAX_WORKERS = 20

TOP_EARLY = 4
TOP_WATCH = 5
TOP_CONFIRMED = 3

EARLY_MIN_SCORE = 10
WATCH_MIN_SCORE = 9
CONFIRMED_MIN_SCORE = 12

MIN_EARLY_VOLUME = 0.80
MIN_CONFIRMED_VOLUME = 1.20

EARLY_MAX_DISTANCE = 1.00
WATCH_MAX_DISTANCE = 1.50

CHASE_5M_LIMIT = 5.00

LIVE_TRADING = False


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/39.1",
        "Accept": "application/json",
    }
)


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM SECRETS NOT FOUND")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = SESSION.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print(
            "TELEGRAM ERROR:",
            response.status_code,
            response.text[:500],
        )

    except Exception as e:
        print("TELEGRAM EXCEPTION:", str(e))

    return False


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# GENERIC API GET
# ============================================================

def api_get(path, params=None):
    url = BASE_URL + path

    try:
        response = SESSION.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:
            return None

        return response.json()

    except Exception:
        return None


# ============================================================
# FLEXIBLE LIST EXTRACTION
# ============================================================

def extract_list(data):
    """
    Attempts to extract a list from different Tabdeal
    response formats.
    """

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    possible_keys = [
        "data",
        "result",
        "results",
        "items",
        "symbols",
        "markets",
        "tickers",
        "rows",
    ]

    for key in possible_keys:
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            nested = extract_list(value)

            if nested:
                return nested

    return []


# ============================================================
# SYMBOL EXTRACTION
# ============================================================

def normalize_symbol(value):
    if value is None:
        return ""

    value = str(value).upper().strip()

    value = value.replace("-", "")
    value = value.replace("_", "")
    value = value.replace("/", "")

    return value


def extract_symbol(item):
    if isinstance(item, str):
        return normalize_symbol(item)

    if not isinstance(item, dict):
        return ""

    keys = [
        "symbol",
        "market",
        "pair",
        "code",
        "name",
        "instrument",
    ]

    for key in keys:
        value = item.get(key)

        if isinstance(value, str):
            symbol = normalize_symbol(value)

            if symbol:
                return symbol

    return ""


# ============================================================
# USDT MARKET DISCOVERY
# ============================================================

def get_usdt_markets():
    """
    V39.1:
    Try several public market/ticker endpoints.

    IMPORTANT:
    There is NO fake BTCUSDT fallback anymore.
    """

    endpoints = [
        "/r/api/v1/ticker/24hr",
        "/r/api/v1/tickers",
        "/r/api/v1/ticker",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/exchange/info",
    ]

    found = []

    for endpoint in endpoints:

        print(f"🔎 MARKET DISCOVERY: {endpoint}")

        data = api_get(endpoint)

        if data is None:
            continue

        items = extract_list(data)

        if not items:
            continue

        symbols = []

        for item in items:

            symbol = extract_symbol(item)

            if not symbol:
                continue

            if symbol.endswith("USDT"):
                symbols.append(symbol)

        symbols = sorted(set(symbols))

        if len(symbols) >= 10:

            found = symbols[:MAX_MARKETS]

            print(
                f"✅ MARKET DISCOVERY OK: "
                f"{len(found)} USDT markets"
            )

            return found

    # --------------------------------------------------------
    # SECONDARY DISCOVERY:
    # some API responses can be dictionaries keyed by symbol
    # --------------------------------------------------------

    for endpoint in [
        "/r/api/v1/ticker/24hr",
        "/r/api/v1/tickers",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
    ]:

        data = api_get(endpoint)

        if not isinstance(data, dict):
            continue

        possible_container = None

        for key in [
            "data",
            "result",
            "markets",
            "symbols",
            "tickers",
        ]:
            value = data.get(key)

            if isinstance(value, dict):
                possible_container = value
                break

        if possible_container is None:
            possible_container = data

        symbols = []

        for key, value in possible_container.items():

            symbol = normalize_symbol(key)

            if symbol.endswith("USDT"):
                symbols.append(symbol)

            if isinstance(value, dict):
                symbol2 = extract_symbol(value)

                if symbol2.endswith("USDT"):
                    symbols.append(symbol2)

        symbols = sorted(set(symbols))

        if len(symbols) >= 10:

            found = symbols[:MAX_MARKETS]

            print(
                f"✅ MARKET DISCOVERY OK: "
                f"{len(found)} USDT markets"
            )

            return found

    print("❌ TABDEAL MARKET DISCOVERY FAILED")

    return []


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):
    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if data is None:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        items = extract_list(data)

        if items:
            return items

    return []


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = None
    quantity = None
    timestamp = None

    for key in [
        "price",
        "p",
        "lastPrice",
    ]:
        if key in item:
            price = item.get(key)
            break

    for key in [
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
    ]:
        if key in item:
            quantity = item.get(key)
            break

    for key in [
        "time",
        "timestamp",
        "T",
        "createdAt",
    ]:
        if key in item:
            timestamp = item.get(key)
            break

    try:
        price = float(price)
        quantity = float(quantity)

    except Exception:
        return None

    if timestamp is None:
        timestamp = int(time.time() * 1000)

    try:
        timestamp = float(timestamp)

    except Exception:
        timestamp = int(time.time() * 1000)

    if timestamp < 10000000000:
        timestamp *= 1000

    return {
        "price": price,
        "qty": quantity,
        "time": timestamp,
    }


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade:
            parsed.append(trade)

    if len(parsed) < 20:
        return []

    parsed.sort(key=lambda x: x["time"])

    buckets = {}

    for trade in parsed:

        bucket = int(
            trade["time"] // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
            }

        candle = buckets[bucket]

        price = trade["price"]
        qty = trade["qty"]

        if price > candle["high"]:
            candle["high"] = price

        if price < candle["low"]:
            candle["low"] = price

        candle["close"] = price
        candle["volume"] += qty

    candles = list(buckets.values())

    candles.sort(key=lambda x: x["time"])

    return candles[-CANDLE_LIMIT:]


# ============================================================
# AGGREGATE CANDLES
# ============================================================

def aggregate_candles(candles, factor):

    if len(candles) < factor:
        return []

    result = []

    usable = len(candles) - (
        len(candles) % factor
    )

    candles = candles[-usable:]

    for i in range(0, len(candles), factor):

        group = candles[i:i + factor]

        if len(group) < factor:
            continue

        result.append(
            {
                "time": group[0]["time"],
                "open": group[0]["open"],
                "high": max(
                    x["high"] for x in group
                ),
                "low": min(
                    x["low"] for x in group
                ),
                "close": group[-1]["close"],
                "volume": sum(
                    x["volume"] for x in group
                ),
            }
        )

    return result


# ============================================================
# PERCENT CHANGE
# ============================================================

def pct_change(old, new):

    if old == 0:
        return 0.0

    return (
        (new - old) / old
    ) * 100.0


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(candles, lookback=20):

    if len(candles) < lookback + 1:
        return 0.0

    current = candles[-1]["volume"]

    previous = [
        x["volume"]
        for x in candles[-lookback - 1:-1]
    ]

    if not previous:
        return 0.0

    avg = sum(previous) / len(previous)

    if avg <= 0:
        return 0.0

    return current / avg


# ============================================================
# RESISTANCE
# ============================================================

def recent_resistance(candles, lookback=20):

    if len(candles) < lookback + 1:
        return candles[-1]["high"]

    section = candles[-lookback - 1:-1]

    return max(
        x["high"] for x in section
    )


# ============================================================
# CANDLE STRENGTH
# ============================================================

def strong_bullish_candle(candle):

    candle_range = (
        candle["high"] - candle["low"]
    )

    if candle_range <= 0:
        return False

    body = abs(
        candle["close"] - candle["open"]
    )

    body_ratio = body / candle_range

    close_position = (
        candle["close"] - candle["low"]
    ) / candle_range

    return (
        candle["close"] > candle["open"]
        and body_ratio >= 0.45
        and close_position >= 0.65
    )


# ============================================================
# RETEST DETECTION
# ============================================================

def detect_retest(candles):

    if len(candles) < 8:
        return False

    resistance = recent_resistance(
        candles,
        lookback=12,
    )

    recent = candles[-5:]

    for candle in recent:

        low_distance = abs(
            candle["low"] - resistance
        ) / resistance * 100

        if low_distance <= 1.0:
            if candle["close"] >= resistance * 0.995:
                return True

    return False


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(symbol):

    try:

        trades = get_trades(symbol)

        if len(trades) < 20:
            return None

        candles5 = build_5m_candles(trades)

        if len(candles5) < 30:
            return None

        # Remove current unfinished candle
        closed5 = candles5[:-1]

        if len(closed5) < 25:
            return None

        candles15 = aggregate_candles(
            closed5,
            3,
        )

        candles1h = aggregate_candles(
            closed5,
            12,
        )

        if len(candles15) < 6:
            return None

        if len(candles1h) < 3:
            return None

        current = closed5[-1]

        price = current["close"]

        change5 = pct_change(
            closed5[-2]["close"],
            closed5[-1]["close"],
        )

        change15 = pct_change(
            candles15[-2]["close"],
            candles15[-1]["close"],
        )

        change1h = pct_change(
            candles1h[-2]["close"],
            candles1h[-1]["close"],
        )

        resistance = recent_resistance(
            closed5,
            lookback=20,
        )

        if resistance <= 0:
            return None

        distance_to_resistance = (
            (resistance - price)
            / resistance
        ) * 100

        vol_ratio = volume_ratio(
            closed5,
            lookback=20,
        )

        strong = strong_bullish_candle(
            current
        )

        retest = detect_retest(
            closed5
        )

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        score = 0

        # 5m momentum
        if change5 >= 0.15:
            score += 2
        elif change5 >= 0:
            score += 1

        # 15m momentum
        if change15 >= 1.00:
            score += 3
        elif change15 >= 0.50:
            score += 2
        elif change15 > 0:
            score += 1

        # 1h momentum
        if change1h >= 2.00:
            score += 3
        elif change1h >= 1.00:
            score += 2
        elif change1h > 0:
            score += 1

        # Volume
        if vol_ratio >= 2.00:
            score += 3
        elif vol_ratio >= 1.20:
            score += 2
        elif vol_ratio >= 0.80:
            score += 1

        # Strong candle
        if strong:
            score += 2

        # Retest
        if retest:
            score += 2

        # Breakout
        breakout = (
            price > resistance
        )

        if breakout:
            score += 3

        # ----------------------------------------------------
        # CHASE FILTER
        # ----------------------------------------------------

        if change5 > CHASE_5M_LIMIT:
            return None

        # ----------------------------------------------------
        # DIRECTION FILTER
        # ----------------------------------------------------

        if change15 <= 0 and change1h <= 0:
            return None

        # ----------------------------------------------------
        # CLASSIFICATION
        # ----------------------------------------------------

        category = None

        # Confirmed BUY
        if (
            breakout
            and strong
            and vol_ratio >= MIN_CONFIRMED_VOLUME
            and score >= CONFIRMED_MIN_SCORE
        ):
            category = "CONFIRMED"

        # Early BUY
        elif (
            score >= EARLY_MIN_SCORE
            and vol_ratio >= MIN_EARLY_VOLUME
            and change15 > 0
            and change1h > 0
            and distance_to_resistance <= EARLY_MAX_DISTANCE
        ):
            category = "EARLY"

        # WATCH
        elif (
            score >= WATCH_MIN_SCORE
            and vol_ratio >= MIN_EARLY_VOLUME
            and change1h > 0
            and distance_to_resistance <= WATCH_MAX_DISTANCE
        ):
            category = "WATCH"

        else:
            return None

        # ----------------------------------------------------
        # SL / TP
        # ----------------------------------------------------

        sl = price * 0.995
        tp1 = price * 1.010
        tp2 = price * 1.020

        return {
            "symbol": symbol,
            "category": category,
            "score": score,
            "price": price,
            "change5": change5,
            "change15": change15,
            "change1h": change1h,
            "volume": vol_ratio,
            "distance": distance_to_resistance,
            "strong": strong,
            "retest": retest,
            "breakout": breakout,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
        }

    except Exception as e:

        print(
            f"⚠️ ANALYZE ERROR {symbol}: {e}"
        )

        return None


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

    return f"{value:.10f}"


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(item, number):

    category = item["category"]

    if category == "CONFIRMED":
        title = "🟢 CONFIRMED BUY"

    elif category == "EARLY":
        title = "⚡ EARLY BUY"

    else:
        title = "🟡 WATCH"

    return (
        f"{title}\n"
        f"#{number}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: {fmt_price(item['price'])}\n"
        f"📈 5M: {item['change5']:+.2f}%\n"
        f"📊 15M: {item['change15']:+.2f}%\n"
        f"⏱ 1H: {item['change1h']:+.2f}%\n"
        f"🔊 VOLUME: {item['volume']:.2f}x\n"
        f"📏 RESISTANCE DIST: "
        f"{item['distance']:.2f}%\n"
        f"🔁 RETEST: "
        f"{'YES' if item['retest'] else 'NO'}\n"
        f"💥 BREAKOUT: "
        f"{'YES' if item['breakout'] else 'NO'}\n"
        f"🕯 STRONG CANDLE: "
        f"{'YES' if item['strong'] else 'NO'}\n"
        f"🛑 SL: {fmt_price(item['sl'])}\n"
        f"🎯 TP1: {fmt_price(item['tp1'])}\n"
        f"🎯 TP2: {fmt_price(item['tp2'])}"
    )


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
                analyze_symbol,
                symbol,
            ): symbol
            for symbol in markets
        }

        completed = 0

        for future in as_completed(futures):

            completed += 1

            try:
                result = future.result()

                if result:
                    results.append(result)

            except Exception as e:

                symbol = futures[future]

                print(
                    f"⚠️ WORKER ERROR "
                    f"{symbol}: {e}"
                )

    elapsed = time.time() - start

    return results, elapsed


# ============================================================
# BUILD TELEGRAM MESSAGE
# ============================================================

def build_message(
    markets,
    results,
    scan_time,
):

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

    confirmed.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    early.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    watch.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 FAST EARLY ENTRY + "
        f"CONFIRMED BREAKOUT\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED CANDLE: YES\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🕐 {utc_now()}\n"
    )

    # --------------------------------------------------------
    # CONFIRMED
    # --------------------------------------------------------

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "🟢 CONFIRMED BUYS\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if confirmed:

        for i, item in enumerate(
            confirmed[:TOP_CONFIRMED],
            1,
        ):

            message += (
                "\n"
                + format_signal(item, i)
                + "\n"
            )

    else:

        message += (
            "\n❌ No confirmed BUY signal.\n"
        )

    # --------------------------------------------------------
    # EARLY
    # --------------------------------------------------------

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "⚡ EARLY BUY\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if early:

        for i, item in enumerate(
            early[:TOP_EARLY],
            1,
        ):

            message += (
                "\n"
                + format_signal(item, i)
                + "\n"
            )

    else:

        message += (
            "\n❌ No early BUY signal.\n"
        )

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "🟡 WATCH\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if watch:

        for i, item in enumerate(
            watch[:TOP_WATCH],
            1,
        ):

            message += (
                "\n"
                + format_signal(item, i)
                + "\n"
            )

    else:

        message += (
            "\n❌ No WATCH candidates.\n"
        )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        f"📌 TOTAL CANDIDATES: "
        f"{len(results)}\n"
        f"🟢 CONFIRMED: {len(confirmed)}\n"
        f"⚡ EARLY: {len(early)}\n"
        f"🟡 WATCH: {len(watch)}\n"
        f"⏱ SCAN TIME: {scan_time:.1f}s\n"
        "🔄 NEXT SCAN: ABOUT 5 MINUTES\n"
    )

    return message


# ============================================================
# MARKET ERROR MESSAGE
# ============================================================

def build_market_error_message():

    return (
        f"⚠️ ATI CRYPTO BOT {VERSION}\n\n"
        f"❌ TABDEAL MARKET DATA ERROR\n\n"
        f"📡 TABDEAL API: CONNECTED\n"
        f"❌ USDT MARKET LIST: FAILED\n\n"
        f"🚫 SCAN STOPPED SAFELY\n"
        f"🚫 BTCUSDT FALLBACK DISABLED\n\n"
        f"🕐 {utc_now()}\n\n"
        f"🔧 REAL ORDERS: DISABLED"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    start_all = time.time()

    print()
    print("=" * 60)
    print(f"⚡ ATI CRYPTO BOT {VERSION}")
    print("🚀 FAST EARLY ENTRY + CONFIRMED BREAKOUT")
    print("=" * 60)

    # --------------------------------------------------------
    # TELEGRAM START MESSAGE
    # --------------------------------------------------------

    startup_message = (
        f"🟢 ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 FAST EARLY ENTRY + "
        f"CONFIRMED BREAKOUT\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🔄 NEXT SCAN: ABOUT 5 MINUTES\n"
        f"🔧 REAL ORDERS: DISABLED\n\n"
        f"🕐 {utc_now()}"
    )

    telegram_send(startup_message)

    # --------------------------------------------------------
    # MARKET DISCOVERY
    # --------------------------------------------------------

    markets = get_usdt_markets()

    if not markets:

        print()
        print("❌ NO USDT MARKETS FOUND")
        print("❌ SCAN ABORTED")
        print()

        telegram_send(
            build_market_error_message()
        )

        return

    print()
    print(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results, scan_time = scan_markets(
        markets
    )

    # --------------------------------------------------------
    # TELEGRAM RESULT
    # --------------------------------------------------------

    message = build_message(
        markets,
        results,
        scan_time,
    )

    telegram_send(message)

    # --------------------------------------------------------
    # CONSOLE
    # --------------------------------------------------------

    print()
    print(message)

    total_time = time.time() - start_all

    print()
    print(
        f"⏱ TOTAL RUNTIME: "
        f"{total_time:.1f}s"
    )
    print(
        f"🔄 NEXT SCAN: ABOUT 5 MINUTES"
    )
    print()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
