import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.7
# OPPORTUNITY ENGINE
# EARLY ENTRY ROOT FIX
# ============================================================

VERSION = "V40.2.7"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

MAX_MARKETS = 529
MAX_WORKERS = 6

TRADE_LIMIT = 1000
REQUEST_TIMEOUT = 15
MAX_RETRIES = 4
REQUEST_DELAY = 0.08

SCAN_INTERVAL_SECONDS = 300

MIN_CANDLES_FOR_SIGNAL = 12
BREAKOUT_LOOKBACK = 12

# ============================================================
# MOVEMENT
# ============================================================

MIN_5M_CHANGE = 0.10
MAX_5M_CHANGE = 7.0

# ============================================================
# PRESSURE
# ============================================================

MIN_BUY_PRESSURE = 58.0
STRONG_BUY_PRESSURE = 65.0

EARLY_BUY_PRESSURE = 62.0
WATCH_BUY_PRESSURE = 55.0

PRESSURE_TRADES = 80

# ============================================================
# RESISTANCE
# ============================================================

EARLY_RESISTANCE_DISTANCE = 0.30
WATCH_RESISTANCE_DISTANCE = 0.90

# ============================================================
# CANDLE
# ============================================================

MIN_BODY_RATIO = 0.25
MIN_CANDLE_POSITION = 0.60

# ============================================================
# SCORE
# ============================================================

CONFIRMED_SCORE = 8
EARLY_SCORE = 7
WATCH_SCORE = 5

# ============================================================
# RISK
# ============================================================

SL_PERCENT = 0.60
TP1_PERCENT = 1.00
TP2_PERCENT = 1.60

MAX_CANDLE_EXTENSION = 2.50

# ============================================================
# SAFETY
# ============================================================

REAL_ORDERS = False


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        return response.ok

    except Exception:

        return False


# ============================================================
# STATS
# ============================================================

LAST_STATS = {
    "requested": 0,
    "responses": 0,
    "valid_trades": 0,
    "markets_with_data": 0,
    "insufficient": 0,
    "unknown_pressure": 0,
    "total_candles": 0,
}


# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/40.2.7",
        "Accept": "application/json",
    }
)


def get_json(path, params=None):

    url = BASE_URL + path

    for attempt in range(MAX_RETRIES):

        try:

            response = SESSION.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 429:

                time.sleep(
                    1.5 * (attempt + 1)
                )

                continue

            if response.status_code >= 500:

                time.sleep(
                    1.0 * (attempt + 1)
                )

                continue

            if response.status_code != 200:

                return None

            return response.json()

        except Exception:

            if attempt < MAX_RETRIES - 1:

                time.sleep(
                    0.8 * (attempt + 1)
                )

    return None


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(value):

    if value is None:
        return ""

    symbol = str(value).upper().strip()

    for char in [
        "-",
        "_",
        "/",
        " ",
    ]:

        symbol = symbol.replace(
            char,
            "",
        )

    return symbol


# ============================================================
# EXCHANGE INFO
# ============================================================

def extract_exchange_symbols(data):

    result = []

    def walk(obj):

        if isinstance(obj, list):

            for item in obj:
                walk(item)

            return

        if not isinstance(obj, dict):
            return

        symbol = None

        for key in [
            "symbol",
            "pair",
            "market",
            "instrument",
            "code",
            "name",
        ]:

            if key in obj:

                value = obj.get(key)

                if value:
                    symbol = value
                    break

        if symbol:

            normalized = normalize_symbol(
                symbol
            )

            if normalized.endswith("USDT"):

                result.append(
                    normalized
                )

        for key in [
            "data",
            "result",
            "markets",
            "symbols",
            "instruments",
            "items",
            "rows",
        ]:

            if key in obj:
                walk(obj[key])

    walk(data)

    return list(
        dict.fromkeys(result)
    )


def get_usdt_markets():

    data = get_json(
        "/r/api/v1/exchangeInfo"
    )

    if data is None:
        return []

    symbols = extract_exchange_symbols(
        data
    )

    return symbols[:MAX_MARKETS]


# ============================================================
# TRADE EXTRACTION
# ============================================================

def extract_trade_list(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in [
        "data",
        "result",
        "trades",
        "items",
        "rows",
    ]:

        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            for subkey in [
                "data",
                "trades",
                "items",
                "rows",
            ]:

                subvalue = value.get(
                    subkey
                )

                if isinstance(
                    subvalue,
                    list,
                ):

                    return subvalue

    return []


# ============================================================
# TIMESTAMP
# ============================================================

def normalize_timestamp(value):

    if value is None:
        return None

    try:

        timestamp = float(value)

        if timestamp > 1e18:
            timestamp /= 1e9

        elif timestamp > 1e15:
            timestamp /= 1e6

        elif timestamp > 1e12:
            timestamp /= 1e3

        return timestamp

    except Exception:

        return None


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = None
    quantity = None
    timestamp = None
    buyer_maker = None

    for key in [
        "price",
        "p",
        "Price",
    ]:

        if key in item:

            price = item.get(key)
            break

    for key in [
        "qty",
        "quantity",
        "q",
        "Qty",
    ]:

        if key in item:

            quantity = item.get(key)
            break

    for key in [
        "time",
        "timestamp",
        "transactTime",
        "T",
        "Time",
    ]:

        if key in item:

            timestamp = item.get(key)
            break

    for key in [
        "isBuyerMaker",
        "buyerMaker",
        "m",
        "is_buyer_maker",
    ]:

        if key in item:

            buyer_maker = item.get(key)
            break

    try:

        price = float(price)
        quantity = float(quantity)

    except Exception:

        return None

    timestamp = normalize_timestamp(
        timestamp
    )

    if timestamp is None:
        timestamp = time.time()

    if isinstance(
        buyer_maker,
        str,
    ):

        value = buyer_maker.strip().lower()

        if value in [
            "true",
            "1",
            "yes",
        ]:

            buyer_maker = True

        elif value in [
            "false",
            "0",
            "no",
        ]:

            buyer_maker = False

        else:

            buyer_maker = None

    elif isinstance(
        buyer_maker,
        (int, float, bool),
    ):

        buyer_maker = bool(
            buyer_maker
        )

    else:

        buyer_maker = None

    return {
        "price": price,
        "qty": quantity,
        "time": timestamp,
        "buyer_maker": buyer_maker,
    }


# ============================================================
# GET TRADES
# ============================================================

def get_symbol_trades(symbol):

    data = get_json(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    )

    trades = extract_trade_list(
        data
    )

    if not trades:

        fallback_symbol = (
            symbol.replace(
                "USDT",
                "_USDT",
            )
        )

        data = get_json(
            "/r/api/v1/trades",
            {
                "tabdealSymbol":
                    fallback_symbol,
                "limit":
                    TRADE_LIMIT,
            },
        )

        trades = extract_trade_list(
            data
        )

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade:
            parsed.append(trade)

    return parsed


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    buckets = {}

    for trade in trades:

        timestamp = trade["time"]

        bucket = (
            int(timestamp // 300)
            * 300
        )

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open":
                    trade["price"],
                "high":
                    trade["price"],
                "low":
                    trade["price"],
                "close":
                    trade["price"],
                "volume": 0.0,
            }

        candle = buckets[bucket]

        price = trade["price"]
        quantity = trade["qty"]

        candle["high"] = max(
            candle["high"],
            price,
        )

        candle["low"] = min(
            candle["low"],
            price,
        )

        candle["close"] = price

        candle["volume"] += quantity

    candles = sorted(
        buckets.values(),
        key=lambda x: x["time"],
    )

    current_bucket = (
        int(time.time() // 300)
        * 300
    )

    candles = [
        candle
        for candle in candles
        if candle["time"]
        < current_bucket
    ]

    return candles


# ============================================================
# BUY PRESSURE
# ============================================================

def calculate_buy_pressure(trades):

    valid = [
        trade
        for trade in trades
        if trade["buyer_maker"] is not None
    ]

    if len(valid) < 10:
        return None

    valid = valid[
        -PRESSURE_TRADES:
    ]

    buy_volume = 0.0
    sell_volume = 0.0

    for trade in valid:

        volume = (
            trade["price"]
            * trade["qty"]
        )

        if trade["buyer_maker"] is False:

            buy_volume += volume

        else:

            sell_volume += volume

    total = (
        buy_volume
        + sell_volume
    )

    if total <= 0:
        return None

    return (
        buy_volume
        / total
        * 100.0
    )


# ============================================================
# STRUCTURE
# ============================================================

def structure_info(candles):

    if len(candles) < (
        BREAKOUT_LOOKBACK + 1
    ):

        return None

    current = candles[-1]

    previous = candles[
        -(BREAKOUT_LOOKBACK + 1):-1
    ]

    resistance = max(
        candle["high"]
        for candle in previous
    )

    close = current["close"]

    breakout = (
        close > resistance
    )

    if resistance > 0:

        distance = (
            (
                resistance
                - close
            )
            / resistance
            * 100
        )

    else:

        distance = 999.0

    recent = candles[-6:]

    rising_count = 0

    for index in range(
        1,
        len(recent),
    ):

        if (
            recent[index]["close"]
            >
            recent[index - 1]["close"]
        ):

            rising_count += 1

    rising = (
        rising_count >= 3
    )

    return {
        "resistance": resistance,
        "breakout": breakout,
        "distance": distance,
        "rising": rising,
    }


# ============================================================
# CANDLE QUALITY
# ============================================================

def candle_quality(candle):

    high = candle["high"]
    low = candle["low"]

    open_price = candle["open"]
    close = candle["close"]

    candle_range = (
        high - low
    )

    if candle_range <= 0:

        return 0.0, 0.0

    body = abs(
        close - open_price
    )

    body_ratio = (
        body
        / candle_range
    )

    candle_position = (
        close - low
    ) / candle_range

    return (
        body_ratio,
        candle_position,
    )


# ============================================================
# SCORE
# MAX = 11
# ============================================================

def calculate_score(
    change_5m,
    pressure,
    breakout,
    body_ratio,
    candle_position,
    rising,
):

    score = 0

    # Movement = 3
    if change_5m >= MIN_5M_CHANGE:
        score += 2

    if change_5m <= MAX_5M_CHANGE:
        score += 1

    # Pressure = 3
    if pressure is not None:

        if pressure >= MIN_BUY_PRESSURE:
            score += 2

        if pressure >= STRONG_BUY_PRESSURE:
            score += 1

    # Breakout = 2
    if breakout:
        score += 2

    # Candle body = 1
    if body_ratio >= MIN_BODY_RATIO:
        score += 1

    # Candle position = 1
    if candle_position >= MIN_CANDLE_POSITION:
        score += 1

    # Rising = 1
    if rising:
        score += 1

    return score


# ============================================================
# ANALYZE
# ============================================================

def analyze_market(symbol):

    trades = get_symbol_trades(
        symbol
    )

    if not trades:
        return None

    candles = build_candles(
        trades
    )

    if len(candles) < (
        MIN_CANDLES_FOR_SIGNAL
    ):

        return {
            "symbol": symbol,
            "status":
                "INSUFFICIENT DATA",
            "candles":
                len(candles),
        }

    pressure = calculate_buy_pressure(
        trades
    )

    if pressure is None:

        return {
            "symbol": symbol,
            "status":
                "UNKNOWN PRESSURE",
            "candles":
                len(candles),
        }

    current = candles[-1]
    previous = candles[-2]

    price = current["close"]

    previous_close = (
        previous["close"]
    )

    if previous_close <= 0:
        return None

    change_5m = (
        (
            price
            - previous_close
        )
        / previous_close
        * 100
    )

    structure = structure_info(
        candles
    )

    if structure is None:
        return None

    body_ratio, candle_position = (
        candle_quality(current)
    )

    breakout = structure[
        "breakout"
    ]

    distance = structure[
        "distance"
    ]

    rising = structure[
        "rising"
    ]

    score = calculate_score(
        change_5m,
        pressure,
        breakout,
        body_ratio,
        candle_position,
        rising,
    )

    too_extended = (
        change_5m
        > MAX_CANDLE_EXTENSION
    )

    signal = "NONE"

    # ========================================================
    # CONFIRMED BUY
    # ========================================================

    confirmed = (
        breakout
        and pressure >= MIN_BUY_PRESSURE
        and MIN_5M_CHANGE
        <= change_5m
        <= MAX_5M_CHANGE
        and body_ratio
        >= MIN_BODY_RATIO
        and candle_position
        >= MIN_CANDLE_POSITION
        and rising
        and score >= CONFIRMED_SCORE
        and not too_extended
    )

    if confirmed:

        signal = "CONFIRMED BUY"

    else:

        # ====================================================
        # EARLY BUY V40.2.7
        #
        # Root change:
        #
        # Near resistance
        # + strong pressure
        # + positive movement
        # + rising structure
        # + score >= 7
        #
        # Candle quality no longer requires
        # BOTH body + position.
        #
        # At least ONE must be good.
        # ====================================================

        candle_quality_ok = (
            body_ratio
            >= MIN_BODY_RATIO
            or
            candle_position
            >= MIN_CANDLE_POSITION
        )

        early = (
            not breakout
            and 0.0
            <= distance
            <= EARLY_RESISTANCE_DISTANCE
            and pressure
            >= EARLY_BUY_PRESSURE
            and MIN_5M_CHANGE
            <= change_5m
            <= MAX_5M_CHANGE
            and rising
            and candle_quality_ok
            and score >= EARLY_SCORE
            and not too_extended
        )

        if early:

            signal = "EARLY BUY"

        else:

            # =================================================
            # WATCH
            # =================================================

            watch = (
                not breakout
                and 0.0
                <= distance
                <= WATCH_RESISTANCE_DISTANCE
                and pressure
                >= WATCH_BUY_PRESSURE
                and MIN_5M_CHANGE
                <= change_5m
                <= MAX_5M_CHANGE
                and rising
                and score >= WATCH_SCORE
                and not too_extended
            )

            if watch:
                signal = "WATCH"

    sl = (
        price
        * (
            1
            - SL_PERCENT / 100
        )
    )

    tp1 = (
        price
        * (
            1
            + TP1_PERCENT / 100
        )
    )

    tp2 = (
        price
        * (
            1
            + TP2_PERCENT / 100
        )
    )

    return {
        "symbol": symbol,
        "status": "OK",
        "signal": signal,
        "price": price,
        "change_5m": change_5m,
        "pressure": pressure,
        "distance": distance,
        "score": score,
        "breakout": breakout,
        "body_ratio": body_ratio,
        "candle_position":
            candle_position,
        "rising": rising,
        "candles":
            len(candles),
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


# ============================================================
# SCAN
# ============================================================

def run_scan():

    for key in LAST_STATS:
        LAST_STATS[key] = 0

    markets = get_usdt_markets()

    if not markets:

        return {
            "confirmed": [],
            "early": [],
            "watch": [],
        }

    LAST_STATS[
        "requested"
    ] = len(markets)

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_market,
                symbol,
            ): symbol
            for symbol in markets
        }

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                LAST_STATS[
                    "responses"
                ] += 1

                if not result:
                    continue

                status = result.get(
                    "status"
                )

                if (
                    status
                    == "INSUFFICIENT DATA"
                ):

                    LAST_STATS[
                        "insufficient"
                    ] += 1

                    continue

                if (
                    status
                    == "UNKNOWN PRESSURE"
                ):

                    LAST_STATS[
                        "unknown_pressure"
                    ] += 1

                    continue

                if status != "OK":
                    continue

                LAST_STATS[
                    "valid_trades"
                ] += 1

                LAST_STATS[
                    "markets_with_data"
                ] += 1

                LAST_STATS[
                    "total_candles"
                ] += result.get(
                    "candles",
                    0,
                )

                if (
                    result.get(
                        "signal"
                    )
                    != "NONE"
                ):

                    results.append(
                        result
                    )

            except Exception:

                continue

    confirmed = [
        item
        for item in results
        if item["signal"]
        == "CONFIRMED BUY"
    ]

    early = [
        item
        for item in results
        if item["signal"]
        == "EARLY BUY"
    ]

    watch = [
        item
        for item in results
        if item["signal"]
        == "WATCH"
    ]

    confirmed.sort(
        key=lambda item: (
            item["score"],
            item["pressure"],
            item["change_5m"],
        ),
        reverse=True,
    )

    early.sort(
        key=lambda item: (
            item["score"],
            item["pressure"],
            -item["distance"],
        ),
        reverse=True,
    )

    watch.sort(
        key=lambda item: (
            item["score"],
            item["pressure"],
            -item["distance"],
        ),
        reverse=True,
    )

    return {
        "confirmed":
            confirmed[:10],
        "early":
            early[:10],
        "watch":
            watch[:10],
    }


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(
    item,
    icon,
):

    message = (
        f"{icon} {item['symbol']}\n"
        f"💰 PRICE: "
        f"{item['price']:.8g}\n"
        f"📈 5m: "
        f"{item['change_5m']:+.2f}%\n"
        f"💚 BUY PRESSURE: "
        f"{item['pressure']:.1f}%\n"
    )

    if not item["breakout"]:

        message += (
            f"📏 RESISTANCE DIST: "
            f"{item['distance']:.2f}%\n"
        )

    message += (
        f"🎯 SCORE: "
        f"{item['score']}/11\n"
        f"🚀 BREAKOUT: "
        f"{'YES' if item['breakout'] else 'NO'}\n"
    )

    if item["signal"] == "CONFIRMED BUY":

        message += (
            f"🕯 CANDLES: "
            f"{item['candles']}\n"
            f"🛡 SL: "
            f"{item['sl']:.8g}\n"
            f"🎯 TP1: "
            f"{item['tp1']:.8g}\n"
            f"🎯 TP2: "
            f"{item['tp2']:.8g}\n"
        )

    return message


# ============================================================
# MESSAGE
# ============================================================

def build_scan_message(scan):

    confirmed = scan[
        "confirmed"
    ]

    early = scan[
        "early"
    ]

    watch = scan[
        "watch"
    ]

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    lines.append(
        "🧠 OPPORTUNITY ENGINE"
    )

    lines.append("")

    lines.append(
        "📡 TABDEAL API: OK"
    )

    lines.append(
        f"📊 USDT MARKETS: "
        f"{LAST_STATS['requested']}"
    )

    lines.append(
        f"📡 REQUESTED: "
        f"{LAST_STATS['requested']}"
    )

    lines.append(
        f"📥 RESPONSES: "
        f"{LAST_STATS['responses']}"
    )

    lines.append(
        f"📊 VALID TRADES: "
        f"{LAST_STATS['valid_trades']}"
    )

    lines.append(
        f"📊 MARKETS WITH DATA: "
        f"{LAST_STATS['markets_with_data']}"
    )

    lines.append(
        f"⚠️ INSUFFICIENT DATA: "
        f"{LAST_STATS['insufficient']}"
    )

    lines.append(
        f"⚠️ UNKNOWN PRESSURE: "
        f"{LAST_STATS['unknown_pressure']}"
    )

    lines.append(
        f"🕯 TOTAL CANDLES: "
        f"{LAST_STATS['total_candles']}"
    )

    lines.append(
        f"🛡 MIN CANDLES: "
        f"{MIN_CANDLES_FOR_SIGNAL}"
    )

    lines.append("")

    # ========================================================
    # CONFIRMED
    # ========================================================

    lines.append(
        "🟢 CONFIRMED BUY"
    )

    if confirmed:

        lines.append("")

        for item in confirmed:

            lines.append(
                format_signal(
                    item,
                    "🟢",
                )
            )

            lines.append("")

    else:

        lines.append("NONE")

    lines.append("")

    # ========================================================
    # EARLY
    # ========================================================

    lines.append(
        "⚡ EARLY BUY"
    )

    if early:

        lines.append("")

        for item in early:

            lines.append(
                format_signal(
                    item,
                    "⚡",
                )
            )

            lines.append("")

    else:

        lines.append("NONE")

    lines.append("")

    # ========================================================
    # WATCH
    # ========================================================

    lines.append(
        "🟡 WATCH"
    )

    if watch:

        lines.append("")

        for item in watch:

            lines.append(
                format_signal(
                    item,
                    "🟡",
                )
            )

            lines.append("")

    else:

        lines.append("NONE")

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "📊 PAPER SIGNALS: ON"
    )

    lines.append(
        "🔧 REAL ORDERS: DISABLED"
    )

    lines.append(
        "💓 HEARTBEAT: ON"
    )

    lines.append(
        "🔄 CONTINUOUS MODE: ON"
    )

    lines.append(
        "🕐 "
        + datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    return "\n".join(lines)


# ============================================================
# HEARTBEAT
# ============================================================

def send_heartbeat():

    message = (
        f"💓 ATI BOT HEARTBEAT\n\n"
        f"⚡ VERSION: {VERSION}\n"
        f"📡 STATUS: ALIVE\n"
        f"⏱ TIMEFRAME: {TIMEFRAME}\n"
        f"📊 MARKETS: "
        f"{LAST_STATS['requested']}\n"
        f"📊 DATA: "
        f"{LAST_STATS['markets_with_data']}\n"
        f"⚠️ UNKNOWN PRESSURE: "
        f"{LAST_STATS['unknown_pressure']}\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔄 NEXT SCAN: ABOUT 5 MINUTES\n"
        f"🕐 "
        + datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    send_telegram(
        message
    )


# ============================================================
# STARTUP
# ============================================================

def send_startup():

    message = (
        f"🟢 ATI CRYPTO BOT "
        f"{VERSION}\n\n"
        f"🧠 OPPORTUNITY ENGINE\n"
        f"🎯 EARLY ENTRY ROOT FIX\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED 5M DATA: YES\n"
        f"🛡 MINIMUM CANDLES: "
        f"{MIN_CANDLES_FOR_SIGNAL}\n"
        f"💚 CONFIRMED PRESSURE: "
        f"{MIN_BUY_PRESSURE:.0f}%+\n"
        f"⚡ EARLY PRESSURE: "
        f"{EARLY_BUY_PRESSURE:.0f}%+\n"
        f"📏 EARLY DISTANCE: "
        f"≤ {EARLY_RESISTANCE_DISTANCE:.2f}%\n"
        f"🚀 BREAKOUT ENGINE: ON\n"
        f"💓 HEARTBEAT: ON\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔄 CONTINUOUS MODE: ON\n"
        f"🕐 "
        + datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )
    )

    send_telegram(
        message
    )


# ============================================================
# MAIN LOOP
# ============================================================

def run_forever():

    send_startup()

    time.sleep(2)

    while True:

        try:

            scan = run_scan()

            message = build_scan_message(
                scan
            )

            send_telegram(
                message
            )

            send_heartbeat()

        except Exception as error:

            message = (
                f"⚠️ ATI BOT "
                f"{VERSION}\n\n"
                f"❌ SCAN ERROR\n"
                f"{str(error)[:500]}\n\n"
                f"🔄 BOT WILL RETRY"
            )

            send_telegram(
                message
            )

        time.sleep(
            SCAN_INTERVAL_SECONDS
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    run_forever()
