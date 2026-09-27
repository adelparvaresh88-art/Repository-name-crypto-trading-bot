import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.3
# CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# STRICT VOLUME / CHASE / WATCH FILTERS
# ============================================================

VERSION = "V39.3"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000

REQUEST_TIMEOUT = 10
MAX_WORKERS = 20

TOP_CONFIRMED = 3
TOP_EARLY = 4
TOP_WATCH = 5

# ============================================================
# SCORE LIMITS
# ============================================================

CONFIRMED_MIN_SCORE = 12
EARLY_MIN_SCORE = 10
WATCH_MIN_SCORE = 10

# ============================================================
# EARLY RULES
# ============================================================

EARLY_MIN_VOLUME = 0.80
EARLY_MAX_VOLUME = 6.00

EARLY_MAX_5M_MOVE = 2.50

EARLY_MIN_15M = 0.50
EARLY_MIN_1H = 1.00

EARLY_MAX_DISTANCE = 1.20

# ============================================================
# CONFIRMED RULES
# ============================================================

CONFIRMED_MIN_VOLUME = 1.20
CONFIRMED_MAX_VOLUME = 8.00

CONFIRMED_MAX_5M_MOVE = 4.00

CONFIRMED_MIN_15M = 0.50
CONFIRMED_MIN_1H = 1.00

# ============================================================
# WATCH RULES
# ============================================================

WATCH_MIN_VOLUME = 0.80
WATCH_MAX_VOLUME = 6.00

WATCH_MAX_5M_MOVE = 2.50

WATCH_MIN_15M = 0.50
WATCH_MIN_1H = 1.00

WATCH_MAX_DISTANCE = 1.50

# ============================================================
# REAL ORDERS
# ============================================================

LIVE_TRADING = False


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/39.3",
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

    if not TELEGRAM_BOT_TOKEN:
        print("⚠️ TELEGRAM_BOT_TOKEN NOT FOUND")
        return False

    if not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_CHAT_ID NOT FOUND")
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
# UTC TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# API GET
# ============================================================

def api_get(
    path,
    params=None,
):

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
        "-",
        "",
    )

    value = value.replace(
        "_",
        "",
    )

    value = value.replace(
        "/",
        "",
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

            symbol = normalize_symbol(
                value
            )

            if symbol:

                return symbol

    return ""


# ============================================================
# USDT MARKETS
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

            symbol = extract_symbol(
                item
            )

            if symbol.endswith("USDT"):

                symbols.append(symbol)

        symbols = sorted(
            set(symbols)
        )

        if len(symbols) >= 10:

            print(
                "✅ MARKET DISCOVERY OK:",
                len(symbols),
                "USDT markets",
            )

            return symbols[
                :MAX_MARKETS
            ]

    # --------------------------------------------------------
    # DICTIONARY FORMAT
    # --------------------------------------------------------

    for endpoint in [
        "/r/api/v1/ticker/24hr",
        "/r/api/v1/tickers",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
    ]:

        data = api_get(endpoint)

        if not isinstance(
            data,
            dict,
        ):
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

            if isinstance(
                value,
                dict,
            ):

                container = value

                break

        if container is None:

            container = data

        symbols = []

        for key, value in container.items():

            symbol = normalize_symbol(
                key
            )

            if symbol.endswith("USDT"):

                symbols.append(symbol)

            if isinstance(
                value,
                dict,
            ):

                symbol2 = extract_symbol(
                    value
                )

                if symbol2.endswith(
                    "USDT"
                ):

                    symbols.append(
                        symbol2
                    )

        symbols = sorted(
            set(symbols)
        )

        if len(symbols) >= 10:

            print(
                "✅ MARKET DISCOVERY OK:",
                len(symbols),
                "USDT markets",
            )

            return symbols[
                :MAX_MARKETS
            ]

    return []


# ============================================================
# GET TRADES
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

    if isinstance(
        data,
        list,
    ):

        return data

    if isinstance(
        data,
        dict,
    ):

        return extract_list(data)

    return []


# ============================================================
# PARSE TRADE
# ============================================================

def parse_trade(item):

    if not isinstance(
        item,
        dict,
    ):

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

        timestamp = float(
            timestamp
        )

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

def build_5m_candles(
    trades
):

    parsed = []

    for item in trades:

        trade = parse_trade(
            item
        )

        if trade:

            parsed.append(
                trade
            )

    if len(parsed) < 20:

        return []

    parsed.sort(
        key=lambda x: x["time"]
    )

    buckets = {}

    for trade in parsed:

        bucket = (
            int(
                trade["time"]
                // 300000
            )
            * 300000
        )

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": trade[
                    "price"
                ],
                "high": trade[
                    "price"
                ],
                "low": trade[
                    "price"
                ],
                "close": trade[
                    "price"
                ],
                "volume": 0.0,
            }

        candle = buckets[
            bucket
        ]

        price = trade[
            "price"
        ]

        quantity = trade[
            "qty"
        ]

        if price > candle[
            "high"
        ]:

            candle[
                "high"
            ] = price

        if price < candle[
            "low"
        ]:

            candle[
                "low"
            ] = price

        candle[
            "close"
        ] = price

        candle[
            "volume"
        ] += quantity

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles[
        -CANDLE_LIMIT:
    ]


# ============================================================
# AGGREGATE CANDLES
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
            len(candles)
            % factor
        )
    )

    candles = candles[
        -usable:
    ]

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
                "time": group[
                    0
                ]["time"],
                "open": group[
                    0
                ]["open"],
                "high": max(
                    x["high"]
                    for x in group
                ),
                "low": min(
                    x["low"]
                    for x in group
                ),
                "close": group[
                    -1
                ]["close"],
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

def pct_change(
    old,
    new,
):

    if old == 0:

        return 0.0

    return (
        (
            new - old
        )
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

    current = candles[
        -1
    ]["volume"]

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
        current
        / average
    )


# ============================================================
# RESISTANCE
# ============================================================

def recent_resistance(
    candles,
    lookback=20,
):

    if len(candles) >= (
        lookback + 1
    ):

        section = candles[
            -lookback - 1:-1
        ]

    else:

        section = candles[
            :-1
        ]

    if not section:

        return candles[
            -1
        ]["high"]

    return max(
        x["high"]
        for x in section
    )


# ============================================================
# AVERAGE RANGE
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

        value = (
            candle["high"]
            - candle["low"]
        )

        if value > 0:

            ranges.append(
                value
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
        body
        / candle_range
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

    current = candles[
        -1
    ]

    previous = candles[
        -6:-1
    ]

    touched = False

    for candle in previous:

        distance = (
            abs(
                candle["low"]
                - resistance
            )
            / resistance
        ) * 100.0

        if distance <= 0.80:

            if (
                candle["close"]
                >= resistance
                * 0.995
            ):

                touched = True

                break

    if not touched:

        return False

    current_distance = (
        (
            current["close"]
            - resistance
        )
        / resistance
    ) * 100.0

    if current_distance < -0.30:

        return False

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
                body
                / candle_range
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
    # 5M
    # --------------------------------------------------------

    if (
        0.20
        <= change5
        <= 2.50
    ):

        score += 2

    elif (
        0
        <= change5
        < 0.20
    ):

        score += 1

    elif (
        2.50
        < change5
        <= 4.00
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

    if (
        1.20
        <= volume
        <= 6.00
    ):

        score += 3

    elif (
        0.80
        <= volume
        < 1.20
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
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(
    symbol
):

    try:

        trades = get_trades(
            symbol
        )

        if len(trades) < 20:

            return None

        candles5 = (
            build_5m_candles(
                trades
            )
        )

        if len(candles5) < 35:

            return None

        # ----------------------------------------------------
        # CLOSED CANDLE ONLY
        # ----------------------------------------------------

        closed5 = candles5[
            :-1
        ]

        if len(closed5) < 30:

            return None

        candles15 = (
            aggregate_candles(
                closed5,
                3,
            )
        )

        candles1h = (
            aggregate_candles(
                closed5,
                12,
            )
        )

        if len(candles15) < 6:

            return None

        if len(candles1h) < 3:

            return None

        current = closed5[
            -1
        ]

        previous = closed5[
            -2
        ]

        price = current[
            "close"
        ]

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

        resistance = (
            recent_resistance(
                closed5,
                20,
            )
        )

        if resistance <= 0:

            return None

        breakout = (
            price > resistance
        )

        distance = (
            (
                resistance
                - price
            )
            / resistance
        ) * 100.0

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        volume = (
            volume_ratio(
                closed5,
                20,
            )
        )

        if volume <= 0:

            return None

        # ----------------------------------------------------
        # CANDLE
        # ----------------------------------------------------

        strong = (
            strong_bullish_candle(
                current
            )
        )

        # ----------------------------------------------------
        # RETEST
        # ----------------------------------------------------

        retest = (
            detect_retest(
                closed5,
                resistance,
            )
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
        # GLOBAL FILTERS
        # ====================================================

        if change1h <= 0:

            return None

        if change15 < -0.20:

            return None

        # ====================================================
        # CONFIRMED
        # ====================================================

        confirmed = False

        if breakout:

            if (
                CONFIRMED_MIN_VOLUME
                <= volume
                <= CONFIRMED_MAX_VOLUME
                and change5
                <= CONFIRMED_MAX_5M_MOVE
                and change15
                >= CONFIRMED_MIN_15M
                and change1h
                >= CONFIRMED_MIN_1H
                and strong
                and score
                >= CONFIRMED_MIN_SCORE
            ):

                confirmed = True

        # ====================================================
        # EARLY
        # ====================================================

        early = False

        if not confirmed:

            # EARLY MUST BE BEFORE BREAKOUT
            if not breakout:

                if (
                    EARLY_MIN_VOLUME
                    <= volume
                    <= EARLY_MAX_VOLUME
                    and change5
                    <= EARLY_MAX_5M_MOVE
                    and change15
                    >= EARLY_MIN_15M
                    and change1h
                    >= EARLY_MIN_1H
                    and distance >= 0
                    and distance
                    <= EARLY_MAX_DISTANCE
                    and score
                    >= EARLY_MIN_SCORE
                ):

                    # Strong candle or retest required
                    if (
                        strong
                        or retest
                    ):

                        early = True

        # ====================================================
        # WATCH
        # ====================================================

        watch = False

        if (
            not confirmed
            and not early
        ):

            # WATCH is ONLY PRE-BREAKOUT.
            # Already broken coins are not WATCH.
            if not breakout:

                if (
                    WATCH_MIN_VOLUME
                    <= volume
                    <= WATCH_MAX_VOLUME
                    and change5
                    <= WATCH_MAX_5M_MOVE
                    and change15
                    >= WATCH_MIN_15M
                    and change1h
                    >= WATCH_MIN_1H
                    and distance >= 0
                    and distance
                    <= WATCH_MAX_DISTANCE
                    and score
                    >= WATCH_MIN_SCORE
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
        # STRUCTURE SL / TP
        # ====================================================

        avg_range = (
            average_range(
                closed5,
                14,
            )
        )

        if avg_range <= 0:

            avg_range = (
                price * 0.005
            )

        structure_sl = (
            price
            - (
                avg_range
                * 1.20
            )
        )

        minimum_sl = (
            price
            * 0.004
        )

        stop_distance = max(
            price
            - structure_sl,
            minimum_sl,
        )

        maximum_sl = (
            price
            * 0.012
        )

        stop_distance = min(
            stop_distance,
            maximum_sl,
        )

        sl = (
            price
            - stop_distance
        )

        tp1 = (
            price
            + (
                stop_distance
                * 1.50
            )
        )

        tp2 = (
            price
            + (
                stop_distance
                * 2.50
            )
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
# PRICE FORMAT
# ============================================================

def fmt_price(
    value
):

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
# SIGNAL FORMAT
# ============================================================

def format_signal(
    item,
    number,
):

    if (
        item["category"]
        == "CONFIRMED"
    ):

        title = (
            "🟢 CONFIRMED BUY"
        )

    elif (
        item["category"]
        == "EARLY"
    ):

        title = (
            "⚡ EARLY BUY"
        )

    else:

        title = (
            "🟡 WATCH"
        )

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
        f"💰 PRICE: "
        f"{fmt_price(item['price'])}\n"
        f"📈 5M: "
        f"{item['change5']:+.2f}%\n"
        f"📊 15M: "
        f"{item['change15']:+.2f}%\n"
        f"⏱ 1H: "
        f"{item['change1h']:+.2f}%\n"
        f"🔊 VOLUME: "
        f"{item['volume']:.2f}x\n"
        f"📏 RESISTANCE: "
        f"{resistance_text}\n"
        f"🔁 RETEST: "
        f"{'YES' if item['retest'] else 'NO'}\n"
        f"💥 BREAKOUT: "
        f"{'YES' if item['breakout'] else 'NO'}\n"
        f"🕯 STRONG CANDLE: "
        f"{'YES' if item['strong'] else 'NO'}\n"
        f"🛑 SL: "
        f"{fmt_price(item['sl'])}\n"
        f"🎯 TP1: "
        f"{fmt_price(item['tp1'])}\n"
        f"🎯 TP2: "
        f"{fmt_price(item['tp2'])}"
    )


# ============================================================
# SCAN MARKETS
# ============================================================

def scan_markets(
    markets
):

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

                    results.append(
                        result
                    )

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

    return (
        results,
        elapsed,
    )


# ============================================================
# BUILD MESSAGE
# ============================================================

def build_message(
    markets,
    results,
    scan_time,
):

    confirmed = [
        x
        for x in results
        if x["category"]
        == "CONFIRMED"
    ]

    early = [
        x
        for x in results
        if x["category"]
        == "EARLY"
    ]

    watch = [
        x
        for x in results
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
            x["change15"],
            x["distance"],
        ),
        reverse=True,
    )

    message = (
        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}\n\n"
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

    # ========================================================
    # CONFIRMED
    # ========================================================

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
            "\n"
            "❌ No confirmed BUY signal.\
