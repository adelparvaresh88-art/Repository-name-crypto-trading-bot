import os
import time
import json
import base64
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.6
# CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# FIXED RESISTANCE / BREAKOUT LOGIC
# ALIGNED 15M + 1H
# PAPER TRADE TRACKER
# ============================================================

VERSION = "V39.6"

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
# SIGNAL SETTINGS
# ============================================================

CONFIRMED_MIN_SCORE = 12

EARLY_MIN_SCORE = 10

WATCH_MIN_SCORE = 10


# ============================================================
# BREAKOUT
# ============================================================

BREAKOUT_BUFFER = 0.05


# ============================================================
# EARLY BUY
# ============================================================

EARLY_MIN_VOLUME = 0.80
EARLY_MAX_VOLUME = 6.00

EARLY_MAX_5M_MOVE = 2.50

EARLY_MIN_15M = 0.50
EARLY_MIN_1H = 1.00

EARLY_MIN_DISTANCE = 0.05
EARLY_MAX_DISTANCE = 1.20


# ============================================================
# CONFIRMED BUY
# ============================================================

CONFIRMED_MIN_VOLUME = 1.20
CONFIRMED_MAX_VOLUME = 8.00

CONFIRMED_MIN_5M_MOVE = 0.20
CONFIRMED_MAX_5M_MOVE = 4.00

CONFIRMED_MIN_15M = 0.50
CONFIRMED_MIN_1H = 1.00


# ============================================================
# WATCH
# ============================================================

WATCH_MIN_VOLUME = 0.80
WATCH_MAX_VOLUME = 6.00

WATCH_MIN_5M_MOVE = 0.00
WATCH_MAX_5M_MOVE = 2.50

WATCH_MIN_15M = 0.50
WATCH_MIN_1H = 1.00

WATCH_MIN_DISTANCE = 0.05
WATCH_MAX_DISTANCE = 1.50


# ============================================================
# PAPER
# ============================================================

PAPER_TRACKING = True

MAX_HISTORY = 500

STATE_FILE = "paper_trades.json"


# ============================================================
# GITHUB
# ============================================================

GITHUB_TOKEN = os.getenv(
    "GITHUB_TOKEN",
    ""
).strip()

GITHUB_REPOSITORY = os.getenv(
    "GITHUB_REPOSITORY",
    ""
).strip()


# ============================================================
# REAL ORDERS
# ============================================================

LIVE_TRADING = False


# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "ATI-Crypto-Bot/39.6",
    "Accept": "application/json",
})


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


# ============================================================
# TELEGRAM SEND
# ============================================================

def telegram_send(message):

    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN NOT FOUND")
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID NOT FOUND")
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

    except Exception as exc:

        print(
            "TELEGRAM EXCEPTION:",
            str(exc),
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

    return (
        str(value)
        .upper()
        .strip()
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
    )


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
# GET USDT MARKETS
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
            "MARKET DISCOVERY:",
            endpoint,
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
                "MARKET DISCOVERY OK:",
                len(symbols),
                "USDT markets",
            )

            return symbols[:MAX_MARKETS]

    # --------------------------------------------------------
    # DICTIONARY FALLBACK
    # --------------------------------------------------------

    fallback_endpoints = [
        "/r/api/v1/ticker/24hr",
        "/r/api/v1/tickers",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
    ]

    for endpoint in fallback_endpoints:

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
                "MARKET DISCOVERY OK:",
                len(symbols),
                "USDT markets",
            )

            return symbols[:MAX_MARKETS]

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

        if trade is not None:

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

        candle["high"] = max(
            candle["high"],
            price,
        )

        candle["low"] = min(
            candle["low"],
            price,
        )

        candle["close"] = price

        candle["volume"] += trade["qty"]

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles[-CANDLE_LIMIT:]


# ============================================================
# ALIGNED CANDLE AGGREGATION
# ============================================================

def aggregate_candles(
    candles,
    factor,
):

    if not candles:
        return []

    interval = 300000 * factor

    groups = {}

    for candle in candles:

        bucket = (
            int(
                candle["time"]
                // interval
            )
            * interval
        )

        if bucket not in groups:

            groups[bucket] = []

        groups[bucket].append(
            candle
        )

    result = []

    for bucket in sorted(groups):

        group = groups[bucket]

        if len(group) != factor:
            continue

        group.sort(
            key=lambda x: x["time"]
        )

        result.append({
            "time": bucket,
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
        })

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

    if len(candles) < lookback + 1:
        return 0.0

    current_volume = candles[-1][
        "volume"
    ]

    previous = candles[
        -lookback - 1:-1
    ]

    if not previous:
        return 0.0

    average_volume = (
        sum(
            candle["volume"]
            for candle in previous
        )
        / len(previous)
    )

    if average_volume <= 0:
        return 0.0

    return (
        current_volume
        / average_volume
    )


# ============================================================
# RECENT RESISTANCE
# ============================================================

def recent_resistance(
    candles,
    lookback=20,
):

    if len(candles) < 3:

        return candles[-1]["high"]

    previous = candles[
        -lookback - 1:-1
    ]

    if not previous:

        previous = candles[:-1]

    if not previous:

        return candles[-1]["high"]

    return max(
        candle["high"]
        for candle in previous
    )


# ============================================================
# AVERAGE RANGE
# ============================================================

def average_range(
    candles,
    lookback=14,
):

    if not candles:
        return 0.0

    selected = candles[
        -lookback:
    ]

    ranges = []

    for candle in selected:

        candle_range = (
            candle["high"]
            - candle["low"]
        )

        if candle_range >= 0:

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
    candle,
):

    candle_open = candle["open"]
    candle_close = candle["close"]
    candle_high = candle["high"]
    candle_low = candle["low"]

    candle_range = (
        candle_high
        - candle_low
    )

    if candle_range <= 0:
        return False

    if candle_close <= candle_open:
        return False

    body = (
        candle_close
        - candle_open
    )

    body_ratio = (
        body
        / candle_range
    )

    close_position = (
        candle_close
        - candle_low
    ) / candle_range

    return (
        body_ratio >= 0.50
        and close_position >= 0.70
    )


# ============================================================
# RETEST
# ============================================================

def detect_retest(
    candles,
    resistance,
):

    if len(candles) < 6:
        return False

    recent = candles[-6:-1]

    tolerance = 0.0080

    lower = (
        resistance
        * (1.0 - tolerance)
    )

    upper = (
        resistance
        * (1.0 + tolerance)
    )

    for candle in recent:

        low = candle["low"]
        close = candle["close"]

        touched = (
            lower <= low <= upper
        )

        close_near = (
            close
            >= resistance * 0.995
        )

        bearish = (
            candle["close"]
            < candle["open"]
        )

        if touched and close_near:

            if bearish:

                candle_range = (
                    candle["high"]
                    - candle["low"]
                )

                if candle_range > 0:

                    body = abs(
                        candle["close"]
                        - candle["open"]
                    )

                    if (
                        body
                        / candle_range
                        > 0.60
                    ):

                        continue

            return True

    return False


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

    # 5M
    if 0.20 <= change5 <= 2.50:

        score += 2

    elif 0.00 <= change5 < 0.20:

        score += 1

    elif 2.50 < change5 <= 4.00:

        score += 1

    # 15M
    if change15 >= 2.00:

        score += 3

    elif change15 >= 0.80:

        score += 2

    elif change15 > 0:

        score += 1

    # 1H
    if change1h >= 5.00:

        score += 3

    elif change1h >= 2.00:

        score += 2

    elif change1h > 0:

        score += 1

    # Volume
    if 1.20 <= volume <= 6.00:

        score += 3

    elif 0.80 <= volume < 1.20:

        score += 1

    # Strong candle
    if strong:

        score += 2

    # Retest
    if retest:

        score += 2

    # Breakout
    if breakout:

        score += 2

    return score


# ============================================================
# PRICE FORMAT
# ============================================================

def fmt_price(value):

    try:

        value = float(value)

    except Exception:

        return "0"

    if value >= 1000:

        return f"{value:.2f}"

    if value >= 100:

        return f"{value:.4f}"

    if value >= 1:

        return f"{value:.5f}"

    if value >= 0.1:

        return f"{value:.6f}"

    if value >= 0.01:

        return f"{value:.8f}"

    return (
        f"{value:.10f}"
        .rstrip("0")
        .rstrip(".")
    )


# ============================================================
# RESISTANCE TEXT
# ============================================================

def resistance_text(
    distance,
):

    if distance < 0:

        return (
            f"{abs(distance):.2f}% "
            "BELOW PRICE"
        )

    return (
        f"{abs(distance):.2f}% "
        "ABOVE PRICE"
    )


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(
    symbol,
):

    try:

        trades = get_trades(
            symbol
        )

        candles5 = build_5m_candles(
            trades
        )

        if len(candles5) < 40:

            return None

        # Remove current incomplete candle
        closed5 = candles5[:-1]

        if len(closed5) < 30:

            return None

        # 15M
        candles15 = aggregate_candles(
            closed5,
            3,
        )

        # 1H
        candles1h = aggregate_candles(
            closed5,
            12,
        )

        if len(candles15) < 3:

            return None

        if len(candles1h) < 3:

            return None

        current = closed5[-1]
        previous = closed5[-2]

        price = current["close"]

        if price <= 0:

            return None

        # Changes
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

        # Resistance from previous closed candles
        resistance = recent_resistance(
            closed5,
            20,
        )

        if resistance <= 0:

            return None

        # Positive = resistance above price
        # Negative = price above resistance
        distance = (
            (
                resistance
                - price
            )
            / resistance
        ) * 100.0

        # Real breakout requires price
        # to be above resistance + buffer.
        breakout_level = (
            resistance
            * (
                1.0
                + BREAKOUT_BUFFER / 100.0
            )
        )

        breakout = (
            price >= breakout_level
        )

        volume = volume_ratio(
            closed5,
            20,
        )

        strong = strong_bullish_candle(
            current
        )

        retest = detect_retest(
            closed5,
            resistance,
        )

        score = calculate_score(
            change5,
            change15,
            change1h,
            volume,
            strong,
            retest,
            breakout,
        )

        # Global trend protection
        if change1h <= 0:

            return None

        if change15 < -0.20:

            return None

        # ----------------------------------------------------
        # CONFIRMED
        # ----------------------------------------------------

        confirmed = (
            breakout
            and volume >= CONFIRMED_MIN_VOLUME
            and volume <= CONFIRMED_MAX_VOLUME
            and change5 >= CONFIRMED_MIN_5M_MOVE
            and change5 <= CONFIRMED_MAX_5M_MOVE
            and change15 >= CONFIRMED_MIN_15M
            and change1h >= CONFIRMED_MIN_1H
            and strong
            and score >= CONFIRMED_MIN_SCORE
        )

        # ----------------------------------------------------
        # EARLY
        # ----------------------------------------------------

        early = (
            not confirmed
            and not breakout
            and distance >= EARLY_MIN_DISTANCE
            and distance <= EARLY_MAX_DISTANCE
            and change5 >= 0.00
            and change5 <= EARLY_MAX_5M_MOVE
            and change15 >= EARLY_MIN_15M
            and change1h >= EARLY_MIN_1H
            and volume >= EARLY_MIN_VOLUME
            and volume <= EARLY_MAX_VOLUME
            and score >= EARLY_MIN_SCORE
            and (strong or retest)
        )

        # ----------------------------------------------------
        # WATCH
        # ----------------------------------------------------

        watch = (
            not confirmed
            and not early
            and not breakout
            and distance >= WATCH_MIN_DISTANCE
            and distance <= WATCH_MAX_DISTANCE
            and change5 >= WATCH_MIN_5M_MOVE
            and change5 <= WATCH_MAX_5M_MOVE
            and change15 >= WATCH_MIN_15M
            and change1h >= WATCH_MIN_1H
            and volume >= WATCH_MIN_VOLUME
            and volume <= WATCH_MAX_VOLUME
            and score >= WATCH_MIN_SCORE
            and (strong or retest)
        )

        if not (
            confirmed
            or early
            or watch
        ):

            return None

        if confirmed:

            signal_type = "CONFIRMED"

        elif early:

            signal_type = "EARLY"

        else:

            signal_type = "WATCH"

        # ----------------------------------------------------
        # SL / TP
        # ----------------------------------------------------

        avg_range = average_range(
            closed5,
            14,
        )

        structure_sl = (
            price
            - avg_range * 1.20
        )

        minimum_sl = (
            price * 0.004
        )

        stop_distance = max(
            price - structure_sl,
            minimum_sl,
        )

        maximum_sl = (
            price * 0.012
        )

        stop_distance = min(
            stop_distance,
            maximum_sl,
        )

        if stop_distance <= 0:

            return None

        sl = (
            price
            - stop_distance
        )

        tp1 = (
            price
            + stop_distance * 1.50
        )

        tp2 = (
            price
            + stop_distance * 2.50
        )

        return {
            "symbol": symbol,
            "type": signal_type,
            "score": score,
            "price": price,
            "change5": change5,
            "change15": change15,
            "change1h": change1h,
            "volume": volume,
            "resistance": resistance,
            "distance": distance,
            "retest": retest,
            "breakout": breakout,
            "strong": strong,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "time": int(
                current["time"]
            ),
        }

    except Exception as exc:

        print(
            "ANALYZE ERROR:",
            symbol,
            str(exc),
        )

        return None


# ============================================================
# LATEST PRICE
# ============================================================

def get_latest_price(
    symbol,
):

    trades = get_trades(
        symbol
    )

    if not trades:

        return None

    prices = []

    for item in trades:

        parsed = parse_trade(
            item
        )

        if parsed:

            prices.append(
                parsed["price"]
            )

    if not prices:

        return None

    return prices[-1]


# ============================================================
# LOCAL STATE
# ============================================================

def load_local_state():

    if not os.path.exists(
        STATE_FILE
    ):

        return {
            "open": [],
            "history": [],
        }

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as file:

            data = json.load(file)

        if not isinstance(
            data,
            dict,
        ):

            return {
                "open": [],
                "history": [],
            }

        data.setdefault(
            "open",
            [],
        )

        data.setdefault(
            "history",
            [],
        )

        return data

    except Exception:

        return {
            "open": [],
            "history": [],
        }


# ============================================================
# GITHUB LOAD STATE
# ============================================================

def github_load_state():

    if not GITHUB_TOKEN:

        return None

    if not GITHUB_REPOSITORY:

        return None

    url = (
        "https://api.github.com/repos/"
        + GITHUB_REPOSITORY
        + "/contents/"
        + STATE_FILE
    )

    headers = {
        "Authorization":
            f"Bearer {GITHUB_TOKEN}",
        "Accept":
            "application/vnd.github+json",
    }

    try:

        response = SESSION.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:

            return None

        data = response.json()

        encoded = data.get(
            "content",
            "",
        )

        if not encoded:

            return None

        raw = base64.b64decode(
            encoded.replace(
                "\n",
                "",
            )
        )

        state = json.loads(
            raw.decode("utf-8")
        )

        if not isinstance(
            state,
            dict,
        ):

            return None

        state.setdefault(
            "open",
            [],
        )

        state.setdefault(
            "history",
            [],
        )

        return state

    except Exception as exc:

        print(
            "GITHUB LOAD ERROR:",
            str(exc),
        )

        return None


# ============================================================
# LOAD STATE
# ============================================================

def load_state():

    github_state = (
        github_load_state()
    )

    if github_state is not None:

        return github_state

    return load_local_state()


# ============================================================
# GITHUB SAVE STATE
# ============================================================

def github_save_state(
    state,
):

    if not GITHUB_TOKEN:

        return False

    if not GITHUB_REPOSITORY:

        return False

    url = (
        "https://api.github.com/repos/"
        + GITHUB_REPOSITORY
        + "/contents/"
        + STATE_FILE
    )

    headers = {
        "Authorization":
            f"Bearer {GITHUB_TOKEN}",
        "Accept":
            "application/vnd.github+json",
    }

    try:

        get_response = SESSION.get(
            url,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        sha = None

        if get_response.status_code == 200:

            sha = (
                get_response
                .json()
                .get("sha")
            )

        content = json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")

        encoded = (
            base64.b64encode(
                content
            )
            .decode("utf-8")
        )

        payload = {
            "message":
                f"ATI bot {VERSION} paper state",
            "content":
                encoded,
        }

        if sha:

            payload["sha"] = sha

        response = SESSION.put(
            url,
            headers=headers,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:

            print(
                "PAPER STATE SAVED TO GITHUB"
            )

            return True

        print(
            "GITHUB SAVE ERROR:",
            response.status_code,
            response.text[:500],
        )

    except Exception as exc:

        print(
            "GITHUB SAVE EXCEPTION:",
            str(exc),
        )

    return False


# ============================================================
# SAVE STATE
# ============================================================

def save_state(
    state,
):

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8",
        ) as file:

            json.dump(
                state,
                file,
                ensure_ascii=False,
                indent=2,
            )

    except Exception as exc:

        print(
            "LOCAL STATE SAVE ERROR:",
            str(exc),
        )

    github_save_state(
        state
    )


# ============================================================
# CHECK OPEN PAPER TRADES
# ============================================================

def check_open_paper_trades(
    state,
):

    if not PAPER_TRACKING:

        return []

    open_trades = state.get(
        "open",
        [],
    )

    if not open_trades:

        return []

    updates = []

    remaining = []

    for trade in open_trades:

        symbol = trade.get(
            "symbol",
            "",
        )

        if not symbol:

            continue

        price = get_latest_price(
            symbol
        )

        if price is None:

            remaining.append(
                trade
            )

            continue

        try:

            sl = float(
                trade.get(
                    "sl",
                    0,
                )
            )

            tp1 = float(
                trade.get(
                    "tp1",
                    0,
                )
            )

            tp2 = float(
                trade.get(
                    "tp2",
                    0,
                )
            )

        except Exception:

            remaining.append(
                trade
            )

            continue

        result = None

        if (
            tp2 > 0
            and price >= tp2
        ):

            result = "TP2"

        elif (
            tp1 > 0
            and price >= tp1
        ):

            result = "TP1"

        elif (
            sl > 0
            and price <= sl
        ):

            result = "SL"

        if result is None:

            remaining.append(
                trade
            )

            continue

        trade["status"] = result

        trade["exit_price"] = price

        trade["exit_time"] = utc_now()

        state.setdefault(
            "history",
            [],
        ).append(
            trade
        )

        updates.append(
            trade
        )

    state["open"] = remaining

    history = state.get(
        "history",
        [],
    )

    if len(history) > MAX_HISTORY:

        state["history"] = history[
            -MAX_HISTORY:
        ]

    return updates


# ============================================================
# ADD PAPER TRADES
# ============================================================

def add_paper_trades(
    state,
    signals,
):

    if not PAPER_TRACKING:

        return 0

    open_trades = state.setdefault(
        "open",
        [],
    )

    existing_symbols = set()

    for trade in open_trades:

        symbol = trade.get(
            "symbol",
            "",
        )

        if symbol:

            existing_symbols.add(
                symbol
            )

    added = 0

    for signal in signals:

        if signal["type"] not in [
            "CONFIRMED",
            "EARLY",
        ]:

            continue

        symbol = signal["symbol"]

        if symbol in existing_symbols:

            continue

        trade = {
            "id": (
                f"{symbol}-"
                f"{int(time.time() * 1000)}"
            ),
            "symbol": symbol,
            "type": signal["type"],
            "entry": signal["price"],
            "sl": signal["sl"],
            "tp1": signal["tp1"],
            "tp2": signal["tp2"],
            "score": signal["score"],
            "entry_time": utc_now(),
            "status": "OPEN",
        }

        open_trades.append(
            trade
        )

        existing_symbols.add(
            symbol
        )

        added += 1

    return added


# ============================================================
# PAPER STATISTICS
# ============================================================

def paper_statistics(
    state,
):

    history = state.get(
        "history",
        [],
    )

    tp1 = 0
    tp2 = 0
    sl = 0

    for trade in history:

        status = trade.get(
            "status",
            "",
        )

        if status == "TP1":

            tp1 += 1

        elif status == "TP2":

            tp2 += 1

        elif status == "SL":

            sl += 1

    closed = (
        tp1
        + tp2
        + sl
    )

    open_trades = state.get(
        "open",
        [],
    )

    open_count = len(
        open_trades
    )

    wins = (
        tp1
        + tp2
    )

    if closed > 0:

        win_rate = (
            wins
            / closed
        ) * 100.0

    else:

        win_rate = 0.0

    return {
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "closed": closed,
        "open": open_count,
        "win_rate": win_rate,
    }


# ============================================================
# STARTUP
# ============================================================

def startup_message():

    return (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        "🚀 CLEAN EARLY ENTRY + CONFIRMED BREAKOUT\n\n"
        "📡 TABDEAL API: CONNECTING...\n"
        "📊 SCAN: STARTING\n"
        "⏱ TIMEFRAME: 5m\n"
        "🕯 CLOSED CANDLE: YES\n"
        "📊 PAPER TRACKING: ON\n"
        "🔧 REAL ORDERS: DISABLED\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# MARKET ERROR
# ============================================================

def market_error_message():

    return (
        f"⚠️ ATI CRYPTO BOT {VERSION}\n\n"
        "❌ TABDEAL MARKET DATA ERROR\n\n"
        "🚫 SCAN STOPPED SAFELY\n"
        "🚫 NO USDT MARKETS FOUND\n\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(
    signal,
    number,
):

    signal_type = signal["type"]

    if signal_type == "CONFIRMED":

        title = "🟢 CONFIRMED BUY"

    elif signal_type == "EARLY":

        title = "⚡ EARLY BUY"

    else:

        title = "🟡 WATCH"

    return (
        f"{title}\n"
        f"#{number}\n"
        f"🪙 {signal['symbol']}\n"
        f"⭐ SCORE: {signal['score']}\n"
        f"💰 PRICE: {fmt_price(signal['price'])}\n"
        f"📈 5M: {signal['change5']:+.2f}%\n"
        f"📊 15M: {signal['change15']:+.2f}%\n"
        f"⏱ 1H: {signal['change1h']:+.2f}%\n"
        f"🔊 VOLUME: {signal['volume']:.2f}x\n"
        f"🎯 RESISTANCE: "
        f"{fmt_price(signal['resistance'])}\n"
        f"📏 DISTANCE: "
        f"{resistance_text(signal['distance'])}\n"
        f"🔁 RETEST: "
        f"{'YES' if signal['retest'] else 'NO'}\n"
        f"💥 BREAKOUT: "
        f"{'YES' if signal['breakout'] else 'NO'}\n"
        f"🕯 STRONG CANDLE: "
        f"{'YES' if signal['strong'] else 'NO'}\n"
        f"🛑 SL: "
        f"{fmt_price(signal['sl'])}\n"
        f"🎯 TP1: "
        f"{fmt_price(signal['tp1'])}\n"
        f"🎯 TP2: "
        f"{fmt_price(signal['tp2'])}"
    )


# ============================================================
# BUILD MESSAGE
# ============================================================

def build_message(
    confirmed,
    early,
    watch,
    state,
    market_count,
    scan_time,
):

    parts = []

    parts.append(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        "🚀 CLEAN EARLY ENTRY + CONFIRMED BREAKOUT\n\n"
        "📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {market_count}\n"
        "⏱ TIMEFRAME: 5m\n"
        "🕯 CLOSED CANDLE: YES\n"
        "📊 PAPER TRACKING: ON\n"
        "🔧 REAL ORDERS: DISABLED\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # CONFIRMED
    # --------------------------------------------------------

    parts.append(
        "\n━━━━━━━━━━━━━━━━━━\n"
        "🟢 CONFIRMED BUYS\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    if confirmed:

        for index, signal in enumerate(
            confirmed,
            1,
        ):

            parts.append(
                format_signal(
                    signal,
                    index,
                )
            )

    else:

        parts.append(
            "❌ No CONFIRMED BUY candidates."
        )

    # --------------------------------------------------------
    # EARLY
    # --------------------------------------------------------

    parts.append(
        "\n━━━━━━━━━━━━━━━━━━\n"
        "⚡ EARLY BUY\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    if early:

        for index, signal in enumerate(
            early,
            1,
        ):

            parts.append(
                format_signal(
                    signal,
                    index,
                )
            )

    else:

        parts.append(
            "❌ No EARLY BUY candidates."
        )

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    parts.append(
        "\n━━━━━━━━━━━━━━━━━━\n"
        "🟡 WATCH\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    if watch:

        for index, signal in enumerate(
            watch,
            1,
        ):

            parts.append(
                format_signal(
                    signal,
                    index,
                )
            )

    else:

        parts.append(
            "❌ No WATCH candidates."
        )

    # --------------------------------------------------------
    # PAPER RESULTS
    # --------------------------------------------------------

    stats = paper_statistics(
        state
    )

    parts.append(
        "\n━━━━━━━━━━━━━━━━━━\n"
        "📊 PAPER RESULTS\n"
        "━━━━━━━━━━━━━━━━━━"
    )

    parts.append(
        f"🎯 TP1: {stats['tp1']}\n"
        f"🎯 TP2: {stats['tp2']}\n"
        f"🛑 SL: {stats['sl']}\n"
        f"⏳ OPEN: {stats['open']}\n"
        f"📈 WIN RATE: "
        f"{stats['win_rate']:.1f}%"
    )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    total = (
        len(confirmed)
        + len(early)
        + len(watch)
    )

    parts.append(
        "\n"
        f"📌 TOTAL CANDIDATES: {total}\n"
        f"🟢 CONFIRMED: {len(confirmed)}\n"
        f"⚡ EARLY: {len(early)}\n"
        f"🟡 WATCH: {len(watch)}\n"
        f"⏱ SCAN TIME: {scan_time:.1f}s\n"
        "🔄 NEXT SCAN: ABOUT 5 MINUTES"
    )

    return "\n".join(parts)


# ============================================================
# PAPER UPDATE MESSAGE
# ============================================================

def format_paper_updates(
    updates,
):

    if not updates:

        return ""

    lines = [
        f"📊 ATI PAPER UPDATE {VERSION}",
        "",
    ]

    for trade in updates:

        status = trade.get(
            "status",
            "",
        )

        symbol = trade.get(
            "symbol",
            "",
        )

        try:

            entry = float(
                trade.get(
                    "entry",
                    0,
                )
            )

            exit_price = float(
                trade.get(
                    "exit_price",
                    0,
                )
            )

        except Exception:

            entry = 0.0
            exit_price = 0.0

        if entry > 0:

            pnl = (
                (
                    exit_price
                    - entry
                )
                / entry
            ) * 100.0

        else:

            pnl = 0.0

        if status == "TP1":

            icon = "🎯"

        elif status == "TP2":

            icon = "🏆"

        else:

            icon = "🛑"

        lines.append(
            f"{icon} {symbol} {status}\n"
            f"💰 ENTRY: {fmt_price(entry)}\n"
            f"💵 EXIT: {fmt_price(exit_price)}\n"
            f"📈 P/L: {pnl:+.2f}%"
        )

    return "\n\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    scan_start = time.time()

    # --------------------------------------------------------
    # STARTUP
    # --------------------------------------------------------

    telegram_send(
        startup_message()
    )

    print(
        f"ATI CRYPTO BOT {VERSION}"
    )

    print(
        "TABDEAL API: CONNECTING..."
    )

    # --------------------------------------------------------
    # STATE
    # --------------------------------------------------------

    state = load_state()

    state.setdefault(
        "open",
        [],
    )

    state.setdefault(
        "history",
        [],
    )

    # --------------------------------------------------------
    # CHECK PAPER TRADES
    # --------------------------------------------------------

    paper_updates = []

    if PAPER_TRACKING:

        paper_updates = (
            check_open_paper_trades(
                state
            )
        )

        if paper_updates:

            update_message = (
                format_paper_updates(
                    paper_updates
                )
            )

            telegram_send(
                update_message
            )

    # --------------------------------------------------------
    # MARKET DISCOVERY
    # --------------------------------------------------------

    markets = get_usdt_markets()

    if not markets:

        telegram_send(
            market_error_message()
        )

        return

    market_count = len(
        markets
    )

    print(
        "TABDEAL API: OK"
    )

    print(
        "USDT MARKETS:",
        market_count,
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results = []

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

            symbol = futures[
                future
            ]

            try:

                result = future.result()

                if result is not None:

                    results.append(
                        result
                    )

            except Exception as exc:

                print(
                    "SCAN ERROR:",
                    symbol,
                    str(exc),
                )

    # --------------------------------------------------------
    # CONFIRMED
    # --------------------------------------------------------

    confirmed = sorted(
        [
            item
            for item in results
            if item["type"]
            == "CONFIRMED"
        ],
        key=lambda item: (
            item["score"],
            item["change1h"],
            item["change15"],
            item["volume"],
        ),
        reverse=True,
    )

    confirmed = confirmed[
        :TOP_CONFIRMED
    ]

    # --------------------------------------------------------
    # EARLY
    # --------------------------------------------------------

    early = sorted(
        [
            item
            for item in results
            if item["type"]
            == "EARLY"
        ],
        key=lambda item: (
            item["score"],
            item["change1h"],
            item["change15"],
            item["volume"],
        ),
        reverse=True,
    )

    early = early[
        :TOP_EARLY
    ]

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    watch = sorted(
        [
            item
            for item in results
            if item["type"]
            == "WATCH"
        ],
        key=lambda item: (
            item["score"],
            item["change1h"],
            item["change15"],
            item["volume"],
        ),
        reverse=True,
    )

    watch = watch[
        :TOP_WATCH
    ]

    # --------------------------------------------------------
    # SELECTED
    # --------------------------------------------------------

    selected = (
        confirmed
        + early
        + watch
    )

    # --------------------------------------------------------
    # PAPER TRADES
    # --------------------------------------------------------

    added = add_paper_trades(
        state,
        selected,
    )

    if added > 0:

        print(
            "NEW PAPER TRADES:",
            added,
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_state(
        state
    )

    # --------------------------------------------------------
    # SCAN TIME
    # --------------------------------------------------------

    scan_time = (
        time.time()
        - scan_start
    )

    # --------------------------------------------------------
    # FINAL MESSAGE
    # --------------------------------------------------------

    message = build_message(
        confirmed,
        early,
        watch,
        state,
        market_count,
        scan_time,
    )

    telegram_send(
        message
    )

    # --------------------------------------------------------
    # CONSOLE
    # --------------------------------------------------------

    print("")
    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    print(
        "TOTAL CANDIDATES:",
        len(selected),
    )

    print(
        "CONFIRMED:",
        len(confirmed),
    )

    print(
        "EARLY:",
        len(early),
    )

    print(
        "WATCH:",
        len(watch),
    )

    print(
        "SCAN TIME:",
        f"{scan_time:.1f}s",
    )

    print(
        "━━━━━━━━━━━━━━━━━━━━━━━━"
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
