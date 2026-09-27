import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.2
# EARLY ENTRY + CLEAN BREAKOUT + REAL RETEST FILTER
# ============================================================

VERSION = "V39.2"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000

REQUEST_TIMEOUT = 10
MAX_WORKERS = 20

TOP_CONFIRMED = 3
TOP_EARLY = 4
TOP_WATCH = 5

CONFIRMED_MIN_SCORE = 12
EARLY_MIN_SCORE = 10
WATCH_MIN_SCORE = 9

# ------------------------------------------------------------
# EARLY FILTERS
# ------------------------------------------------------------

EARLY_MAX_5M_MOVE = 3.00
EARLY_MAX_VOLUME = 8.00
EARLY_MAX_DISTANCE = 1.20

# ------------------------------------------------------------
# CONFIRMED FILTERS
# ------------------------------------------------------------

CONFIRMED_MIN_VOLUME = 1.20
CONFIRMED_MAX_5M_MOVE = 5.00

# ------------------------------------------------------------
# WATCH FILTERS
# ------------------------------------------------------------

WATCH_MAX_5M_DROP = -1.50
WATCH_MAX_DISTANCE = 1.80

# ------------------------------------------------------------
# REAL ORDERS
# ------------------------------------------------------------

LIVE_TRADING = False


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/39.2",
        "Accept": "application/json",
    }
)


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


def telegram_send(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM SECRETS NOT FOUND")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
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

        print(
            "TELEGRAM EXCEPTION:",
            str(e),
        )

    return False


# ============================================================
# TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# API
# ============================================================

def api_get(path, params=None):

    try:

        response = SESSION.get(
            BASE_URL + path,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:
            return None

        return response.json()

    except Exception:

        return None


# ============================================================
# EXTRACT LIST
# ============================================================

def extract_list(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    keys = [
        "data",
        "result",
        "results",
        "items",
        "symbols",
        "markets",
        "tickers",
        "rows",
    ]

    for key in keys:

        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            nested = extract_list(value)

            if nested:
                return nested

    return []


# ============================================================
# NORMALIZE SYMBOL
# ============================================================

def normalize_symbol(value):

    if value is None:
        return ""

    value = str(value).upper().strip()

    value = value.replace(
        "-", ""
    )

    value = value.replace(
        "_", ""
    )

    value = value.replace(
        "/", ""
    )

    return value


# ============================================================
# EXTRACT SYMBOL
# ============================================================

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
# MARKET DISCOVERY
# ============================================================

def get_usdt_markets():

    endpoints = [
        "/r/api/v1/ticker/24hr",
        "/r/api/v1/tickers",
        "/r/api/v1/ticker",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/exchange/info",
    ]

    for endpoint in endpoints:

        print(
            f"🔎 MARKET DISCOVERY: {endpoint}"
        )

        data = api_get(endpoint)

        if data is None:
            continue

        items = extract_list(data)

        if not items:
            continue

        symbols = []

        for item in items:

            symbol = extract_symbol(item)

            if symbol.endswith("USDT"):
                symbols.append(symbol)

        symbols = sorted(
            set(symbols)
        )

        if len(symbols) >= 10:

            print(
                f"✅ MARKET DISCOVERY OK: "
                f"{len(symbols)} USDT markets"
            )

            return symbols[:MAX_MARKETS]

    # --------------------------------------------------------
    # DICT FORMAT
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

        container = None

        for key in [
            "data",
            "result",
            "markets",
            "symbols",
            "tickers",
        ]:

            value = data.get(key)

            if isinstance(value, dict):
                container = value
                break

        if container is None:
            container = data

        symbols = []

        for key, value in container.items():

            symbol = normalize_symbol(key)

            if symbol.endswith("USDT"):
                symbols.append(symbol)

            if isinstance(value, dict):

                symbol2 = extract_symbol(value)

                if symbol2.endswith("USDT"):
                    symbols.append(symbol2)

        symbols = sorted(
            set(symbols)
        )

        if len(symbols) >= 10:

            print(
                f"✅ MARKET DISCOVERY OK: "
                f"{len(symbols)} USDT markets"
            )

            return symbols[:MAX_MARKETS]

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
        return extract_list(data)

    return []


# ============================================================
# PARSE TRADE
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
        timestamp = int(
            time.time() * 1000
        )

    try:

        timestamp = float(timestamp)

    except Exception:

        timestamp = int(
            time.time() * 1000
        )

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

    parsed.sort(
        key=lambda x: x["time"]
    )

    buckets = {}

    for trade in parsed:

        bucket = (
            int(
                trade["time"] // 300000
            )
            * 300000
        )

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

        quantity = trade["qty"]

        if price > candle["high"]:
            candle["high"] = price

        if price < candle["low"]:
            candle["low"] = price

        candle["close"] = price

        candle["volume"] += quantity

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles[-CANDLE_LIMIT:]


# ============================================================
# AGGREGATE
# ============================================================

def aggregate_candles(
    candles,
    factor,
):

    if len(candles) < factor:
        return []

    result = []

    usable = (
        len(candles)
        - (
            len(candles) % factor
        )
    )

    candles = candles[-usable:]

    for i in range(
        0,
        len(candles),
        factor,
    ):

        group = candles[
            i:i + factor
        ]

        if len(group) < factor:
            continue

        result.append(
            {
                "time": group[0]["time"],
                "open": group[0]["open"],
                "high": max(
                    x["high"]
                    for x in group
                ),
                "low": min(
                    x["low"]
                    for x in group
                ),
                "close": group[-1]["close"],
                "volume": sum(
                    x["volume"]
                    for x in group
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
        (new - old)
        / old
    ) * 100.0


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(
    candles,
    lookback=20,
):

    if len(candles) < (
        lookback + 1
    ):
        return 0.0

    current = candles[-1][
        "volume"
    ]

    previous = [
        x["volume"]
        for x in candles[
            -lookback - 1:-1
        ]
    ]

    if not previous:
        return 0.0

    average = (
        sum(previous)
        / len(previous)
    )

    if average <= 0:
        return 0.0

    return (
        current / average
    )


# ============================================================
# RESISTANCE
# ============================================================

def recent_resistance(
    candles,
    lookback=20,
):

    if len(candles) < (
        lookback + 1
    ):
        section = candles[:-1]

    else:
        section = candles[
            -lookback - 1:-1
        ]

    if not section:
        return candles[-1]["high"]

    return max(
        x["high"]
        for x in section
    )


# ============================================================
# ATR-LIKE VOLATILITY
# ============================================================

def average_range(
    candles,
    lookback=14,
):

    if len(candles) < 2:
        return 0.0

    section = candles[
        -lookback:
    ]

    ranges = []

    for candle in section:

        candle_range = (
            candle["high"]
            - candle["low"]
        )

        if candle_range > 0:
            ranges.append(
                candle_range
            )

    if not ranges:
        return 0.0

    return (
        sum(ranges)
        / len(ranges)
    )


# ============================================================
# STRONG BULLISH CANDLE
# ============================================================

def strong_bullish_candle(
    candle
):

    candle_range = (
        candle["high"]
        - candle["low"]
    )

    if candle_range <= 0:
        return False

    body = abs(
        candle["close"]
        - candle["open"]
    )

    body_ratio = (
        body / candle_range
    )

    close_position = (
        candle["close"]
        - candle["low"]
    ) / candle_range

    return (
        candle["close"]
        > candle["open"]
        and body_ratio >= 0.50
        and close_position >= 0.70
    )


# ============================================================
# REAL RETEST
# ============================================================

def detect_retest(
    candles,
    resistance,
):

    if len(candles) < 10:
        return False

    # Last candle must be bullish/holding
    current = candles[-1]

    # Search previous 5 candles for a touch
    previous = candles[-6:-1]

    touched = False

    for candle in previous:

        distance = abs(
            candle["low"]
            - resistance
        ) / resistance * 100

        if distance <= 0.80:

            if (
                candle["close"]
                >= resistance * 0.995
            ):
                touched = True
                break

    if not touched:
        return False

    # Current candle must hold above/near level
    current_distance = (
        current["close"]
        - resistance
    ) / resistance * 100

    if current_distance < -0.30:
        return False

    # Current candle should not be a heavy bearish candle
    if (
        current["close"]
        < current["open"]
    ):
        candle_range = (
            current["high"]
            - current["low"]
        )

        if candle_range > 0:

            body = (
                current["open"]
                - current["close"]
            )

            if (
                body / candle_range
                > 0.55
            ):
                return False

    return True


# ============================================================
# SCORE
# ============================================================

def calculate_score(
    change5,
    change15,
    change1h,
    volume,
    strong,
    retest,
    breakout,
):

    score = 0

    # --------------------------------------------------------
    # 5M MOMENTUM
    # --------------------------------------------------------

    if 0.20 <= change5 <= 2.50:
        score += 2

    elif 0 <= change5 < 0.20:
        score += 1

    elif (
        2.50 < change5 <= 4.00
    ):
        score += 1

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    if change15 >= 2.00:
        score += 3

    elif change15 >= 0.80:
        score += 2

    elif change15 > 0:
        score += 1

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    if change1h >= 5.00:
        score += 3

    elif change1h >= 2.00:
        score += 2

    elif change1h > 0:
        score += 1

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    if 1.20 <= volume <= 6.00:
        score += 3

    elif 0.90 <= volume < 1.20:
        score += 1

    elif (
        6.00 < volume <= 8.00
    ):
        score += 1

    # --------------------------------------------------------
    # CANDLE
    # --------------------------------------------------------

    if strong:
        score += 2

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    if retest:
        score += 2

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    if breakout:
        score += 2

    return score


# ============================================================
# ANALYZE
# ============================================================

def analyze_symbol(symbol):

    try:

        trades = get_trades(symbol)

        if len(trades) < 20:
            return None

        candles5 = build_5m_candles(
            trades
        )

        if len(candles5) < 35:
            return None

        # ----------------------------------------------------
        # CLOSED CANDLES ONLY
        # ----------------------------------------------------

        closed5 = candles5[:-1]

        if len(closed5) < 30:
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

        previous = closed5[-2]

        price = current["close"]

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        change5 = pct_change(
            previous["close"],
            current["close"],
        )

        change15 = pct_change(
            candles15[-2]["close"],
            candles15[-1]["close"],
        )

        change1h = pct_change(
            candles1h[-2]["close"],
            candles1h[-1]["close"],
        )

        # ----------------------------------------------------
        # RESISTANCE
        # ----------------------------------------------------

        resistance = recent_resistance(
            closed5,
            20,
        )

        if resistance <= 0:
            return None

        breakout = (
            price > resistance
        )

        # Distance:
        # positive = below resistance
        # negative = above resistance
        distance = (
            (resistance - price)
            / resistance
        ) * 100.0

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        volume = volume_ratio(
            closed5,
            20,
        )

        if volume <= 0:
            return None

        # ----------------------------------------------------
        # CANDLE
        # ----------------------------------------------------

        strong = strong_bullish_candle(
            current
        )

        # ----------------------------------------------------
        # RETEST
        # ----------------------------------------------------

        retest = detect_retest(
            closed5,
            resistance,
        )

        # ----------------------------------------------------
        # SCORE
        # ----------------------------------------------------

        score = calculate_score(
            change5,
            change15,
            change1h,
            volume,
            strong,
            retest,
            breakout,
        )

        # ====================================================
        # HARD SAFETY FILTERS
        # ====================================================

        # Avoid strong negative momentum
        if change15 < -0.20:
            return None

        if change1h <= 0:
            return None

        # ====================================================
        # CONFIRMED
        # ====================================================

        confirmed = False

        if (
            breakout
            and change5 <= CONFIRMED_MAX_5M_MOVE
            and change15 > 0
            and change1h > 0
            and volume >= CONFIRMED_MIN_VOLUME
            and strong
            and score >= CONFIRMED_MIN_SCORE
        ):

            confirmed = True

        # ====================================================
        # EARLY
        # ====================================================

        early = False

        if not confirmed:

            # Early must NOT be an already explosive move
            if (
                change5 <= EARLY_MAX_5M_MOVE
                and volume <= EARLY_MAX_VOLUME
                and change15 > 0
                and change1h > 0
                and score >= EARLY_MIN_SCORE
            ):

                # If already above resistance,
                # demand real retest/confirmation.
                if breakout:

                    if (
                        retest
                        and strong
                    ):
                        early = True

                else:

                    if (
                        distance >= 0
                        and distance
                        <= EARLY_MAX_DISTANCE
                    ):
                        early = True

        # ====================================================
        # WATCH
        # ====================================================

        watch = False

        if not confirmed and not early:

            if (
                score >= WATCH_MIN_SCORE
                and change1h > 0
                and change15 > 0
                and change5
                >= WATCH_MAX_5M_DROP
                and distance
                <= WATCH_MAX_DISTANCE
            ):

                watch = True

        # ====================================================
        # NO SIGNAL
        # ====================================================

        if (
            not confirmed
            and not early
            and not watch
        ):
            return None

        # ====================================================
        # CATEGORY
        # ====================================================

        if confirmed:
            category = "CONFIRMED"

        elif early:
            category = "EARLY"

        else:
            category = "WATCH"

        # ====================================================
        # STRUCTURE-BASED SL / TP
        # ====================================================

        avg_range = average_range(
            closed5,
            14,
        )

        if avg_range <= 0:
            avg_range = (
                price * 0.005
            )

        # Base stop around 1.2 average 5m ranges
        structure_sl = (
            price
            - (
                avg_range * 1.20
            )
        )

        fixed_min_sl = (
            price * 0.004
        )

        stop_distance = max(
            price - structure_sl,
            fixed_min_sl,
        )

        # Limit excessive stop
        max_sl = (
            price * 0.012
        )

        stop_distance = min(
            stop_distance,
            max_sl,
        )

        sl = (
            price
            - stop_distance
        )

        # TP based on risk
        tp1 = (
            price
            + stop_distance * 1.5
        )

        tp2 = (
            price
            + stop_distance * 2.5
        )

        return {
            "symbol": symbol,
            "category": category,
            "score": score,
            "price": price,
            "change5": change5,
            "change15": change15,
            "change1h": change1h,
            "volume": volume,
            "distance": distance,
            "strong": strong,
            "retest": retest,
            "breakout": breakout,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
        }

    except Exception as e:

        print(
            f"⚠️ ANALYZE ERROR "
            f"{symbol}: {e}"
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

    if value >= 0.0001:
        return f"{value:.8f}"

    return f"{value:.10f}"


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(
    item,
    number,
):

    if item["category"] == "CONFIRMED":

        title = "🟢 CONFIRMED BUY"

    elif item["category"] == "EARLY":

        title = "⚡ EARLY BUY"

    else:

        title = "🟡 WATCH"

    if item["distance"] < 0:

        resistance_text = (
            f"{abs(item['distance']):.2f}% "
            "ABOVE"
        )

    else:

        resistance_text = (
            f"{item['distance']:.2f}% "
            "BELOW"
        )

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
        f"📏 RESISTANCE: "
        f"{resistance_text}\n"
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
# SCAN
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

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception as e:

                symbol = futures[
                    future
                ]

                print(
                    f"⚠️ WORKER ERROR "
                    f"{symbol}: {e}"
                )

    elapsed = (
        time.time()
        - start
    )

    return results, elapsed


# ============================================================
# BUILD RESULT MESSAGE
# ============================================================

def build_message(
    markets,
    results,
    scan_time,
):

    confirmed = [
        x for x in results
        if x["category"]
        == "CONFIRMED"
    ]

    early = [
        x for x in results
        if x["category"]
        == "EARLY"
    ]

    watch = [
        x for x in results
        if x["category"]
        == "WATCH"
    ]

    confirmed.sort(
        key=lambda x: (
            x["score"],
            x["change15"],
            x["change1h"],
        ),
        reverse=True,
    )

    early.sort(
        key=lambda x: (
            x["score"],
            x["change15"],
            x["volume"],
        ),
        reverse=True,
    )

    watch.sort(
        key=lambda x: (
            x["score"],
            x["change1h"],
        ),
        reverse=True,
    )

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 CLEAN EARLY ENTRY + "
        f"CONFIRMED BREAKOUT\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: "
        f"{len(markets)}\n"
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
            confirmed[
                :TOP_CONFIRMED
            ],
            1,
        ):

            message += (
                "\n"
                + format_signal(
                    item,
                    i,
                )
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
                + format_signal(
                    item,
                    i,
                )
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
                + format_signal(
                    item,
                    i,
                )
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
        f"🟢 CONFIRMED: "
        f"{len(confirmed)}\n"
        f"⚡ EARLY: "
        f"{len(early)}\n"
        f"🟡 WATCH: "
        f"{len(watch)}\n"
        f"⏱ SCAN TIME: "
        f"{scan_time:.1f}s\n"
        f"🔄 NEXT SCAN: "
        f"ABOUT 5 MINUTES\n"
    )

    return message


# ============================================================
# MARKET ERROR
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

    total_start = time.time()

    print()
    print("=" * 60)
    print(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )
    print(
        "🚀 CLEAN EARLY ENTRY + "
        "CONFIRMED BREAKOUT"
    )
    print("=" * 60)

    # --------------------------------------------------------
    # START TELEGRAM
    # --------------------------------------------------------

    startup_message = (
        f"🟢 ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 CLEAN EARLY ENTRY + "
        f"CONFIRMED BREAKOUT\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🔄 NEXT SCAN: ABOUT 5 MINUTES\n"
        f"🔧 REAL ORDERS: DISABLED\n\n"
        f"🕐 {utc_now()}"
    )

    telegram_send(
        startup_message
    )

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    markets = get_usdt_markets()

    if not markets:

        print(
            "❌ NO USDT MARKETS FOUND"
        )

        telegram_send(
            build_market_error_message()
        )

        return

    print(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results, scan_time = scan_markets(
        markets
    )

    # --------------------------------------------------------
    # RESULT
    # --------------------------------------------------------

    message = build_message(
        markets,
        results,
        scan_time,
    )

    telegram_send(message)

    print()
    print(message)

    total_time = (
        time.time()
        - total_start
    )

    print()
    print(
        f"⏱ TOTAL RUNTIME: "
        f"{total_time:.1f}s"
    )
    print(
        "🔄 NEXT SCAN: ABOUT 5 MINUTES"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
