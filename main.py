import os
import time
import json
import base64
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.6.3
# CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# MARKET DISCOVERY FIX
# PAPER TRADE NOTIFICATION DEDUP FIX
# ============================================================

VERSION = "V39.6.3"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000

REQUEST_TIMEOUT = 7
MAX_WORKERS = 20

TOP_CONFIRMED = 3
TOP_EARLY = 5
TOP_WATCH = 5


# ============================================================
# CONFIRMED
# ============================================================

CONFIRMED_MIN_SCORE = 12

CONFIRMED_MIN_VOLUME = 1.20
CONFIRMED_MAX_VOLUME = 8.00

CONFIRMED_MIN_5M_MOVE = 0.20
CONFIRMED_MAX_5M_MOVE = 4.00

CONFIRMED_MIN_15M = 0.50
CONFIRMED_MIN_1H = 1.00


# ============================================================
# EARLY
# ============================================================

EARLY_MIN_SCORE = 9

EARLY_MIN_VOLUME = 0.60
EARLY_MAX_VOLUME = 8.00

EARLY_MIN_5M_MOVE = -0.10
EARLY_MAX_5M_MOVE = 3.00

EARLY_MIN_15M = 0.30
EARLY_MIN_1H = 0.60

EARLY_MIN_DISTANCE = 0.03
EARLY_MAX_DISTANCE = 1.80


# ============================================================
# WATCH
# ============================================================

WATCH_MIN_SCORE = 8

WATCH_MIN_VOLUME = 0.60
WATCH_MAX_VOLUME = 8.00

WATCH_MIN_5M_MOVE = -0.10
WATCH_MAX_5M_MOVE = 3.00

WATCH_MIN_15M = 0.20
WATCH_MIN_1H = 0.50

WATCH_MIN_DISTANCE = 0.03
WATCH_MAX_DISTANCE = 2.20


# ============================================================
# BREAKOUT
# ============================================================

BREAKOUT_BUFFER = 0.05


# ============================================================
# PAPER
# ============================================================

PAPER_TRACKING = True
MAX_HISTORY = 500

STATE_FILE = "paper_trades.json"


# ============================================================
# REAL TRADING
# ============================================================

LIVE_TRADING = False


# ============================================================
# ENV
# ============================================================

GITHUB_TOKEN = os.getenv(
    "GITHUB_TOKEN",
    ""
).strip()

GITHUB_REPOSITORY = os.getenv(
    "GITHUB_REPOSITORY",
    ""
).strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_text():
    return utc_now().strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        print(
            "⚠️ TELEGRAM CONFIG MISSING"
        )
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:

        r = requests.post(
            url,
            json=payload,
            timeout=10,
        )

        if r.status_code == 200:
            return True

        print(
            "Telegram error:",
            r.status_code,
            r.text[:300],
        )

        return False

    except Exception as e:

        print(
            "Telegram exception:",
            e,
        )

        return False


# ============================================================
# HTTP
# ============================================================

def api_get(
    path,
    params=None,
    timeout=REQUEST_TIMEOUT,
):

    url = BASE_URL + path

    try:

        r = requests.get(
            url,
            params=params or {},
            timeout=timeout,
        )

        if r.status_code != 200:
            print(
                f"API {path} -> "
                f"HTTP {r.status_code}"
            )
            return None

        return r.json()

    except Exception as e:

        print(
            f"API {path} ERROR: {e}"
        )

        return None


# ============================================================
# DATA HELPERS
# ============================================================

def extract_list(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "data",
            "result",
            "results",
            "symbols",
            "markets",
            "tickers",
            "items",
        ):

            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


def normalize_symbol(value):

    if value is None:
        return ""

    s = str(value).upper().strip()

    s = s.replace("-", "")
    s = s.replace("_", "")
    s = s.replace("/", "")
    s = s.replace(" ", "")

    return s


def extract_symbol(item):

    if isinstance(item, str):

        return normalize_symbol(
            item
        )

    if not isinstance(item, dict):
        return ""

    for key in (
        "symbol",
        "market",
        "pair",
        "code",
        "name",
    ):

        if key in item:

            s = normalize_symbol(
                item.get(key)
            )

            if s:
                return s

    return ""


# ============================================================
# MARKET SYMBOL RECURSIVE EXTRACTOR
# ============================================================
# V39.6.3
#
# Tabdeal may return:
#
# 1) [ {"symbol":"BTCUSDT"} ]
#
# 2) {"data":[{"symbol":"BTCUSDT"}]}
#
# 3) {"result":{"markets":[...]}}
#
# 4) {"BTCUSDT": {...}, "ETHUSDT": {...}}
#
# 5) {"data":{"BTCUSDT": {...}}}
#
# This function handles all of them.
# ============================================================

def extract_market_symbols(
    data,
    found=None,
    depth=0,
):

    if found is None:
        found = set()

    # Safety against unexpected deeply nested JSON
    if depth > 8:
        return found

    # --------------------------------------------------------
    # LIST
    # --------------------------------------------------------

    if isinstance(data, list):

        for item in data:

            extract_market_symbols(
                item,
                found,
                depth + 1,
            )

        return found

    # --------------------------------------------------------
    # STRING
    # --------------------------------------------------------

    if isinstance(data, str):

        symbol = normalize_symbol(
            data
        )

        if symbol.endswith("USDT"):
            found.add(symbol)

        return found

    # --------------------------------------------------------
    # DICT
    # --------------------------------------------------------

    if not isinstance(data, dict):
        return found

    # --------------------------------------------------------
    # First: explicit symbol fields
    # --------------------------------------------------------

    explicit_symbol = extract_symbol(
        data
    )

    if explicit_symbol.endswith(
        "USDT"
    ):

        found.add(
            explicit_symbol
        )

    # --------------------------------------------------------
    # Second: dictionary keys
    #
    # Handles:
    #
    # {
    #   "BTCUSDT": {...},
    #   "ETHUSDT": {...}
    # }
    # --------------------------------------------------------

    for key, value in data.items():

        key_symbol = normalize_symbol(
            key
        )

        if key_symbol.endswith(
            "USDT"
        ):

            found.add(
                key_symbol
            )

        # ----------------------------------------------------
        # Recurse into values
        # ----------------------------------------------------

        if isinstance(
            value,
            (dict, list),
        ):

            extract_market_symbols(
                value,
                found,
                depth + 1,
            )

    return found


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_usdt_markets():

    endpoints = [
        "/r/api/v1/ticker/24hr",
        "/r/api/v1/markets",
        "/r/api/v1/ticker",
        "/r/api/v1/symbols",
        "/api/v1/markets",
        "/v1/markets",
    ]

    found = set()

    for path in endpoints:

        print(
            f"🔎 MARKET ENDPOINT: "
            f"{path}"
        )

        data = api_get(
            path,
            timeout=5,
        )

        if data is None:

            print(
                f"⚠️ EMPTY RESPONSE: "
                f"{path}"
            )

            continue

        before = len(found)

        # ----------------------------------------------------
        # NEW ROBUST PARSER
        # ----------------------------------------------------

        extract_market_symbols(
            data,
            found,
        )

        added = (
            len(found)
            - before
        )

        print(
            f"📊 {path} -> "
            f"+{added} USDT markets"
        )

        # ----------------------------------------------------
        # If enough markets found,
        # stop checking extra endpoints.
        # ----------------------------------------------------

        if len(found) >= 100:

            print(
                f"✅ MARKET DISCOVERY OK: "
                f"{len(found)} USDT markets"
            )

            break

    markets = sorted(
        found
    )

    if len(markets) > MAX_MARKETS:

        markets = markets[
            :MAX_MARKETS
        ]

    print(
        f"📊 FINAL USDT MARKETS: "
        f"{len(markets)}"
    )

    return markets


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

    return extract_list(data)


# ============================================================
# PARSE TRADE
# ============================================================

def parse_trade(item):

    if isinstance(
        item,
        (list, tuple),
    ):

        if len(item) < 2:
            return None

        try:

            price = float(
                item[0]
            )

            qty = float(
                item[1]
            )

            if len(item) >= 3:

                ts = float(
                    item[2]
                )

            else:

                ts = (
                    time.time()
                    * 1000
                )

            if ts < 100000000000:

                ts *= 1000

            return {
                "price": price,
                "qty": abs(qty),
                "time": int(ts),
            }

        except Exception:

            return None

    if not isinstance(
        item,
        dict,
    ):

        return None

    price = None
    qty = None
    ts = None

    for key in (
        "price",
        "p",
        "lastPrice",
        "last",
    ):

        if key in item:

            try:

                price = float(
                    item[key]
                )

                break

            except Exception:
                pass

    for key in (
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
        "baseVolume",
    ):

        if key in item:

            try:

                qty = float(
                    item[key]
                )

                break

            except Exception:
                pass

    for key in (
        "time",
        "timestamp",
        "T",
        "createdAt",
        "created_at",
    ):

        if key in item:

            try:

                ts = float(
                    item[key]
                )

                break

            except Exception:
                pass

    if price is None:
        return None

    if qty is None:
        qty = 0.0

    if ts is None:

        ts = (
            time.time()
            * 1000
        )

    if ts < 100000000000:

        ts *= 1000

    return {
        "price": price,
        "qty": abs(qty),
        "time": int(ts),
    }


# ============================================================
# 5M CANDLES
# ============================================================

def build_5m_candles(
    trades
):

    parsed = []

    for item in trades:

        t = parse_trade(
            item
        )

        if (
            t is not None
            and t["price"] > 0
        ):

            parsed.append(t)

    if not parsed:
        return []

    parsed.sort(
        key=lambda x: x["time"]
    )

    buckets = {}

    for t in parsed:

        bucket = (
            t["time"]
            // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = []

        buckets[bucket].append(
            t
        )

    candles = []

    for bucket in sorted(
        buckets.keys()
    ):

        rows = buckets[
            bucket
        ]

        prices = [
            x["price"]
            for x in rows
        ]

        volume = sum(
            x["qty"]
            for x in rows
        )

        candles.append(
            {
                "time": bucket,
                "open": prices[0],
                "high": max(prices),
                "low": min(prices),
                "close": prices[-1],
                "volume": volume,
            }
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

    if not candles:
        return []

    result = []

    interval = (
        300000 * factor
    )

    groups = {}

    for candle in candles:

        group_time = (
            candle["time"]
            // interval
        ) * interval

        if group_time not in groups:

            groups[group_time] = []

        groups[group_time].append(
            candle
        )

    for group_time in sorted(
        groups.keys()
    ):

        rows = groups[
            group_time
        ]

        if len(rows) != factor:
            continue

        rows = sorted(
            rows,
            key=lambda x:
                x["time"],
        )

        result.append(
            {
                "time":
                    group_time,

                "open":
                    rows[0]["open"],

                "high":
                    max(
                        x["high"]
                        for x in rows
                    ),

                "low":
                    min(
                        x["low"]
                        for x in rows
                    ),

                "close":
                    rows[-1]["close"],

                "volume":
                    sum(
                        x["volume"]
                        for x in rows
                    ),
            }
        )

    return result


# ============================================================
# CALCULATIONS
# ============================================================

def pct_change(
    old,
    new,
):

    if (
        old is None
        or old == 0
    ):

        return 0.0

    return (
        (new - old)
        / old
        * 100.0
    )


def volume_ratio(
    candles,
    lookback=20,
):

    if len(candles) < (
        lookback + 1
    ):

        return 1.0

    current = candles[
        -1
    ]["volume"]

    previous = [
        x["volume"]
        for x in candles[
            -lookback - 1:-1
        ]
        if x["volume"] >= 0
    ]

    if not previous:
        return 1.0

    avg = (
        sum(previous)
        / len(previous)
    )

    if avg <= 0:
        return 1.0

    return (
        current
        / avg
    )


def recent_resistance(
    candles,
    lookback=20,
):

    if len(candles) < 3:

        return candles[
            -2
        ]["high"]

    rows = candles[
        -lookback - 1:-1
    ]

    if not rows:

        rows = candles[
            :-1
        ]

    return max(
        x["high"]
        for x in rows
    )


def average_range(
    candles,
    lookback=14,
):

    rows = candles[
        -lookback:
    ]

    if not rows:
        return 0.0

    ranges = [
        max(
            0.0,
            x["high"]
            - x["low"],
        )
        for x in rows
    ]

    return (
        sum(ranges)
        / len(ranges)
    )


def strong_bullish_candle(
    candle,
):

    o = candle["open"]
    h = candle["high"]
    l = candle["low"]
    c = candle["close"]

    if h <= l:
        return False

    body = abs(
        c - o
    )

    full = (
        h - l
    )

    if full <= 0:
        return False

    close_position = (
        (c - l)
        / full
    )

    return (
        c > o
        and body / full >= 0.35
        and close_position >= 0.65
    )


def detect_retest(
    candles,
    resistance,
):

    if len(candles) < 4:
        return False

    recent = candles[
        -4:
    ]

    for c in recent:

        distance = (
            abs(
                c["low"]
                - resistance
            )
            / resistance
            * 100
        )

        if (
            distance <= 0.40
            and c["close"]
            >= resistance * 0.995
        ):

            return True

    return False


def calculate_score(
    change5,
    change15,
    change1h,
    vol_ratio,
    breakout,
    retest,
    strong,
    distance,
):

    score = 0

    # 5m momentum

    if change5 >= 0.15:

        score += 2

    elif change5 >= 0:

        score += 1

    # 15m momentum

    if change15 >= 1.0:

        score += 3

    elif change15 >= 0.50:

        score += 2

    elif change15 >= 0.20:

        score += 1

    # 1h momentum

    if change1h >= 2.0:

        score += 3

    elif change1h >= 1.0:

        score += 2

    elif change1h >= 0.50:

        score += 1

    # volume

    if vol_ratio >= 2.0:

        score += 3

    elif vol_ratio >= 1.25:

        score += 2

    elif vol_ratio >= 0.80:

        score += 1

    if breakout:

        score += 3

    if retest:

        score += 2

    if strong:

        score += 2

    if (
        0
        <= distance
        <= 0.50
    ):

        score += 2

    elif (
        0
        < distance
        <= 1.50
    ):

        score += 1

    return score


# ============================================================
# FORMAT
# ============================================================

def fmt_price(
    price
):

    if price >= 1000:

        return f"{price:.2f}"

    if price >= 1:

        return f"{price:.5f}"

    if price >= 0.01:

        return f"{price:.7f}"

    return f"{price:.10f}"


def resistance_text(
    distance
):

    if distance >= 0:

        return (
            f"{distance:.2f}% ABOVE"
        )

    return (
        f"{abs(distance):.2f}% "
        f"BELOW PRICE"
    )


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

        if len(trades) < 50:

            return None

        candles5 = (
            build_5m_candles(
                trades
            )
        )

        if len(candles5) < 40:

            return None

        # Remove current incomplete candle

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

        if (
            len(candles15) < 5
            or len(candles1h) < 3
        ):

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

        change5 = pct_change(
            previous["close"],
            current["close"],
        )

        change15 = pct_change(
            candles15[
                -2
            ]["close"],
            candles15[
                -1
            ]["close"],
        )

        change1h = pct_change(
            candles1h[
                -2
            ]["close"],
            candles1h[
                -1
            ]["close"],
        )

        vol = volume_ratio(
            closed5
        )

        resistance = (
            recent_resistance(
                closed5,
                lookback=20,
            )
        )

        if resistance <= 0:

            return None

        distance = (
            (
                resistance
                - price
            )
            / resistance
            * 100.0
        )

        breakout = (
            price
            >= resistance
            * (
                1.0
                + BREAKOUT_BUFFER
                / 100.0
            )
        )

        strong = (
            strong_bullish_candle(
                current
            )
        )

        retest = detect_retest(
            closed5,
            resistance,
        )

        score = calculate_score(
            change5,
            change15,
            change1h,
            vol,
            breakout,
            retest,
            strong,
            distance,
        )

        # ====================================================
        # BASIC TREND FILTER
        # ====================================================

        if change1h <= -0.10:

            return None

        if change15 <= -0.50:

            return None

        # ====================================================
        # CONFIRMED
        # ====================================================

        confirmed = (
            breakout
            and vol
            >= CONFIRMED_MIN_VOLUME
            and vol
            <= CONFIRMED_MAX_VOLUME
            and change5
            >= CONFIRMED_MIN_5M_MOVE
            and change5
            <= CONFIRMED_MAX_5M_MOVE
            and change15
            >= CONFIRMED_MIN_15M
            and change1h
            >= CONFIRMED_MIN_1H
            and strong
            and score
            >= CONFIRMED_MIN_SCORE
        )

        # ====================================================
        # EARLY
        # ====================================================

        early = (
            not breakout
            and distance
            >= EARLY_MIN_DISTANCE
            and distance
            <= EARLY_MAX_DISTANCE
            and vol
            >= EARLY_MIN_VOLUME
            and vol
            <= EARLY_MAX_VOLUME
            and change5
            >= EARLY_MIN_5M_MOVE
            and change5
            <= EARLY_MAX_5M_MOVE
            and change15
            >= EARLY_MIN_15M
            and change1h
            >= EARLY_MIN_1H
            and score
            >= EARLY_MIN_SCORE
            and (
                strong
                or retest
            )
        )

        # ====================================================
        # WATCH
        # ====================================================

        watch = (
            not breakout
            and not early
            and distance
            >= WATCH_MIN_DISTANCE
            and distance
            <= WATCH_MAX_DISTANCE
            and vol
            >= WATCH_MIN_VOLUME
            and vol
            <= WATCH_MAX_VOLUME
            and change5
            >= WATCH_MIN_5M_MOVE
            and change5
            <= WATCH_MAX_5M_MOVE
            and change15
            >= WATCH_MIN_15M
            and change1h
            >= WATCH_MIN_1H
            and score
            >= WATCH_MIN_SCORE
            and (
                strong
                or retest
            )
        )

        if (
            not confirmed
            and not early
            and not watch
        ):

            return None

        # ====================================================
        # SL / TP
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

        risk = (
            avg_range * 1.2
        )

        minimum_risk = (
            price * 0.004
        )

        maximum_risk = (
            price * 0.012
        )

        risk = max(
            risk,
            minimum_risk,
        )

        risk = min(
            risk,
            maximum_risk,
        )

        sl = (
            price - risk
        )

        tp1 = (
            price
            + risk * 1.5
        )

        tp2 = (
            price
            + risk * 2.5
        )

        if confirmed:

            signal_type = (
                "CONFIRMED"
            )

        elif early:

            signal_type = "EARLY"

        else:

            signal_type = "WATCH"

        return {
            "symbol":
                symbol,

            "type":
                signal_type,

            "score":
                score,

            "price":
                price,

            "change5":
                change5,

            "change15":
                change15,

            "change1h":
                change1h,

            "volume":
                vol,

            "resistance":
                resistance,

            "distance":
                distance,

            "breakout":
                breakout,

            "retest":
                retest,

            "strong":
                strong,

            "sl":
                sl,

            "tp1":
                tp1,

            "tp2":
                tp2,

            "time":
                utc_text(),
        }

    except Exception as e:

        print(
            f"Analyze error "
            f"{symbol}: {e}"
        )

        return None


# ============================================================
# PAPER STATE
# ============================================================

def empty_state():

    return {
        "trades": []
    }


# ============================================================
# TRADE ID
# ============================================================

def make_trade_id(
    trade
):

    raw = (
        f"{trade.get('symbol', '')}|"
        f"{trade.get('opened_at', '')}|"
        f"{trade.get('entry', '')}|"
        f"{trade.get('sl', '')}|"
        f"{trade.get('tp1', '')}|"
        f"{trade.get('tp2', '')}"
    )

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()[:24]


# ============================================================
# STATE MIGRATION
# ============================================================

def normalize_state(
    state
):

    if not isinstance(
        state,
        dict,
    ):

        state = empty_state()

    if not isinstance(
        state.get("trades"),
        list,
    ):

        state["trades"] = []

    for trade in state[
        "trades"
    ]:

        if not isinstance(
            trade,
            dict,
        ):

            continue

        if not trade.get(
            "trade_id"
        ):

            trade[
                "trade_id"
            ] = make_trade_id(
                trade
            )

        if trade.get(
            "status"
        ) == "CLOSED":

            if (
                "notification_sent"
                not in trade
            ):

                trade[
                    "notification_sent"
                ] = True

        else:

            if (
                "notification_sent"
                not in trade
            ):

                trade[
                    "notification_sent"
                ] = False

    return state


# ============================================================
# LOCAL STATE LOAD
# ============================================================

def load_local_state():

    try:

        if not os.path.exists(
            STATE_FILE
        ):

            return empty_state()

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        return normalize_state(
            data
        )

    except Exception:

        return empty_state()


# ============================================================
# LOCAL STATE SAVE
# ============================================================

def save_local_state(
    state
):

    try:

        state = normalize_state(
            state
        )

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                state,
                f,
                ensure_ascii=False,
                indent=2,
            )

        return True

    except Exception as e:

        print(
            "Local state save error:",
            e,
        )

        return False


# ============================================================
# GITHUB STATE
# ============================================================

def github_url():

    if not GITHUB_REPOSITORY:

        return None

    return (
        "https://api.github.com/repos/"
        f"{GITHUB_REPOSITORY}"
        f"/contents/{STATE_FILE}"
    )


def github_headers():

    if not GITHUB_TOKEN:

        return {}

    return {
        "Authorization":
            f"Bearer {GITHUB_TOKEN}",

        "Accept":
            "application/vnd.github+json",
    }


def load_github_state():

    url = github_url()

    if (
        not url
        or not GITHUB_TOKEN
    ):

        return None

    try:

        r = requests.get(
            url,
            headers=github_headers(),
            timeout=10,
        )

        if r.status_code != 200:

            return None

        data = r.json()

        content = data.get(
            "content"
        )

        if not content:

            return None

        raw = base64.b64decode(
            content.replace(
                "\n",
                "",
            )
        )

        state = json.loads(
            raw.decode("utf-8")
        )

        return normalize_state(
            state
        )

    except Exception as e:

        print(
            "GitHub load error:",
            e,
        )

        return None


def save_github_state(
    state
):

    url = github_url()

    if (
        not url
        or not GITHUB_TOKEN
    ):

        return False

    try:

        state = normalize_state(
            state
        )

        content = json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        )

        encoded = (
            base64.b64encode(
                content.encode(
                    "utf-8"
                )
            )
            .decode("utf-8")
        )

        current_sha = None

        r = requests.get(
            url,
            headers=github_headers(),
            timeout=10,
        )

        if r.status_code == 200:

            current_sha = (
                r.json().get(
                    "sha"
                )
            )

        payload = {
            "message": (
                f"ATI Bot {VERSION} "
                f"paper state update"
            ),
            "content": encoded,
        }

        if current_sha:

            payload["sha"] = (
                current_sha
            )

        r = requests.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=15,
        )

        if r.status_code in (
            200,
            201,
        ):

            return True

        print(
            "GitHub save failed:",
            r.status_code,
            r.text[:300],
        )

        return False

    except Exception as e:

        print(
            "GitHub save error:",
            e,
        )

        return False


# ============================================================
# LOAD STATE
# ============================================================

def load_state():

    github_state = (
        load_github_state()
    )

    if github_state is not None:

        return github_state

    return load_local_state()


# ============================================================
# SAVE STATE
# ============================================================

def save_state(
    state
):

    state = normalize_state(
        state
    )

    local_ok = (
        save_local_state(
            state
        )
    )

    github_ok = False

    if (
        GITHUB_TOKEN
        and GITHUB_REPOSITORY
    ):

        github_ok = (
            save_github_state(
                state
            )
        )

    return (
        local_ok
        or github_ok
    )


# ============================================================
# PAPER PRICE
# ============================================================

def get_latest_price(
    symbol
):

    trades = get_trades(
        symbol
    )

    if not trades:

        return None

    parsed = []

    for item in trades:

        t = parse_trade(
            item
        )

        if (
            t
            and t["price"] > 0
        ):

            parsed.append(t)

    if not parsed:

        return None

    parsed.sort(
        key=lambda x:
            x["time"]
    )

    return parsed[
        -1
    ]["price"]


# ============================================================
# CHECK OPEN PAPER TRADES
# ============================================================

def check_open_paper_trades(
    state
):

    updates = []

    trades = state.get(
        "trades",
        []
    )

    for trade in trades:

        if trade.get(
            "status"
        ) != "OPEN":

            continue

        symbol = trade.get(
            "symbol"
        )

        if not symbol:

            continue

        price = (
            get_latest_price(
                symbol
            )
        )

        if price is None:

            continue

        try:

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

            sl = float(
                trade.get(
                    "sl",
                    0,
                )
            )

        except Exception:

            continue

        result = None

        # TP2 FIRST

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

        if result:

            trade[
                "status"
            ] = "CLOSED"

            trade[
                "result"
            ] = result

            trade[
                "exit_price"
            ] = price

            trade[
                "closed_at"
            ] = utc_text()

            trade[
                "notification_sent"
            ] = False

            if not trade.get(
                "trade_id"
            ):

                trade[
                    "trade_id"
                ] = make_trade_id(
                    trade
                )

            updates.append(
                {
                    "trade_id":
                        trade[
                            "trade_id"
                        ],

                    "symbol":
                        symbol,

                    "result":
                        result,

                    "entry":
                        trade.get(
                            "entry"
                        ),

                    "exit":
                        price,
                }
            )

    return updates


# ============================================================
# SEND PAPER UPDATES
# ============================================================

def send_paper_updates(
    state,
    updates
):

    if not updates:

        return False

    unique_updates = []

    seen = set()

    trades = state.get(
        "trades",
        []
    )

    trade_map = {
        t.get("trade_id"): t
        for t in trades
        if t.get("trade_id")
    }

    for update in updates:

        trade_id = update.get(
            "trade_id"
        )

        if not trade_id:

            continue

        if trade_id in seen:

            continue

        seen.add(
            trade_id
        )

        trade = trade_map.get(
            trade_id
        )

        if not trade:

            continue

        if trade.get(
            "notification_sent"
        ):

            continue

        unique_updates.append(
            update
        )

    if not unique_updates:

        print(
            "📊 No NEW paper "
            "notifications."
        )

        return False

    update_lines = [
        f"📊 ATI PAPER UPDATE "
        f"{VERSION}",
        "",
    ]

    for update in unique_updates:

        result = update[
            "result"
        ]

        if result == "SL":

            emoji = "🛑"

        elif result == "TP2":

            emoji = "🎯"

        else:

            emoji = "✅"

        update_lines.append(
            f"{emoji} "
            f"{update['symbol']} "
            f"→ {result}"
        )

    message = "\n".join(
        update_lines
    )

    sent = telegram_send(
        message
    )

    if sent:

        for update in unique_updates:

            trade_id = update[
                "trade_id"
            ]

            trade = trade_map.get(
                trade_id
            )

            if trade:

                trade[
                    "notification_sent"
                ] = True

        save_state(
            state
        )

        print(
            "✅ Paper update sent "
            "and marked as notified."
        )

        return True

    print(
        "⚠️ Paper update Telegram "
        "send failed. "
        "Will retry later."
    )

    return False


# ============================================================
# ADD PAPER TRADES
# ============================================================

def add_paper_trades(
    state,
    candidates
):

    if not PAPER_TRACKING:

        return

    trades = state.setdefault(
        "trades",
        []
    )

    open_symbols = {
        t.get("symbol")
        for t in trades
        if t.get("status")
        == "OPEN"
    }

    for item in candidates:

        if item["type"] == "WATCH":

            continue

        symbol = item[
            "symbol"
        ]

        if symbol in open_symbols:

            continue

        trade = {
            "symbol":
                symbol,

            "type":
                item["type"],

            "score":
                item["score"],

            "entry":
                item["price"],

            "sl":
                item["sl"],

            "tp1":
                item["tp1"],

            "tp2":
                item["tp2"],

            "opened_at":
                utc_text(),

            "status":
                "OPEN",

            "result":
                None,

            "notification_sent":
                False,
        }

        trade[
            "trade_id"
        ] = make_trade_id(
            trade
        )

        trades.append(
            trade
        )

        open_symbols.add(
            symbol
        )

    if len(trades) > MAX_HISTORY:

        state[
            "trades"
        ] = trades[
            -MAX_HISTORY:
        ]


# ============================================================
# PAPER STATISTICS
# ============================================================

def paper_statistics(
    state
):

    trades = state.get(
        "trades",
        []
    )

    tp1 = 0
    tp2 = 0
    sl = 0
    open_count = 0

    for trade in trades:

        result = trade.get(
            "result"
        )

        status = trade.get(
            "status"
        )

        if status == "OPEN":

            open_count += 1

        elif result == "TP1":

            tp1 += 1

        elif result == "TP2":

            tp2 += 1

        elif result == "SL":

            sl += 1

    closed = (
        tp1
        + tp2
        + sl
    )

    if closed > 0:

        win_rate = (
            (
                tp1
                + tp2
            )
            / closed
            * 100
        )

    else:

        win_rate = 0.0

    return {
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "open": open_count,
        "win_rate": win_rate,
    }


# ============================================================
# FORMAT CANDIDATE
# ============================================================

def format_candidate(
    item,
    rank
):

    signal = item[
        "type"
    ]

    if signal == "CONFIRMED":

        emoji = "🟢"

    elif signal == "EARLY":

        emoji = "⚡"

    else:

        emoji = "🟡"

    breakout_text = (
        "YES"
        if item["breakout"]
        else "NO"
    )

    return (
        f"{emoji} {signal} #{rank}\n"
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
        f"🔥 VOLUME: "
        f"{item['volume']:.2f}x\n"
        f"🚧 RESISTANCE: "
        f"{resistance_text(item['distance'])}\n"
        f"🚀 BREAKOUT: "
        f"{breakout_text}\n"
        f"🔁 RETEST: "
        f"{'YES' if item['retest'] else 'NO'}\n"
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
# STARTUP MESSAGE
# ============================================================

def startup_message():

    return (
        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}\n\n"

        f"🚀 CLEAN EARLY ENTRY + "
        f"CONFIRMED BREAKOUT\n\n"

        f"📡 TABDEAL API: "
        f"CONNECTING...\n"

        f"📊 SCAN: STARTING\n"

        f"⏱ TIMEFRAME: 5m\n"

        f"🕯 CLOSED CANDLE: YES\n"

        f"📊 PAPER TRACKING: "
        f"{'ON' if PAPER_TRACKING else 'OFF'}\n"

        f"🔧 REAL ORDERS: "
        f"{'ENABLED' if LIVE_TRADING else 'DISABLED'}\n"

        f"🕐 {utc_text()}"
    )


# ============================================================
# FINAL MESSAGE
# ============================================================

def build_final_message(
    confirmed,
    early,
    watch,
    state,
    scan_time,
):

    stats = paper_statistics(
        state
    )

    lines = [
        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}",

        "",

        "🚀 CLEAN EARLY ENTRY + "
        "CONFIRMED BREAKOUT",

        "",

        "📡 TABDEAL API: OK",

        f"📊 USDT MARKETS: "
        f"{market_count_for_message}",

        "⏱ TIMEFRAME: 5m",

        "🕯 CLOSED CANDLE: YES",

        "📊 PAPER TRACKING: ON",

        "🔧 REAL ORDERS: DISABLED",

        f"🕐 {utc_text()}",

        "",

        "━━━━━━━━━━━━━━━━━━",

        "🟢 CONFIRMED BUYS",

        "━━━━━━━━━━━━━━━━━━",
    ]

    if confirmed:

        for i, item in enumerate(
            confirmed[
                :TOP_CONFIRMED
            ],
            1,
        ):

            lines.append(
                format_candidate(
                    item,
                    i,
                )
            )

            lines.append("")

    else:

        lines.append(
            "❌ No CONFIRMED "
            "BUY candidates."
        )

    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━━━━━",
            "⚡ EARLY BUY",
            "━━━━━━━━━━━━━━━━━━",
        ]
    )

    if early:

        for i, item in enumerate(
            early[
                :TOP_EARLY
            ],
            1,
        ):

            lines.append(
                format_candidate(
                    item,
                    i,
                )
            )

            lines.append("")

    else:

        lines.append(
            "❌ No EARLY BUY "
            "candidates."
        )

    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━━━━━",
            "🟡 WATCH",
            "━━━━━━━━━━━━━━━━━━",
        ]
    )

    if watch:

        for i, item in enumerate(
            watch[
                :TOP_WATCH
            ],
            1,
        ):

            lines.append(
                format_candidate(
                    item,
                    i,
                )
            )

            lines.append("")

    else:

        lines.append(
            "❌ No WATCH candidates."
        )

    total_candidates = (
        len(confirmed)
        + len(early)
        + len(watch)
    )

    lines.extend(
        [
            "",
            "━━━━━━━━━━━━━━━━━━",
            "📊 PAPER RESULTS",
            "━━━━━━━━━━━━━━━━━━",

            f"🎯 TP1: "
            f"{stats['tp1']}",

            f"🎯 TP2: "
            f"{stats['tp2']}",

            f"🛑 SL: "
            f"{stats['sl']}",

            f"⏳ OPEN: "
            f"{stats['open']}",

            f"📈 WIN RATE: "
            f"{stats['win_rate']:.1f}%",

            "",

            f"📌 TOTAL CANDIDATES: "
            f"{total_candidates}",

            f"🟢 CONFIRMED: "
            f"{len(confirmed)}",

            f"⚡ EARLY: "
            f"{len(early)}",

            f"🟡 WATCH: "
            f"{len(watch)}",

            f"⏱ SCAN TIME: "
            f"{scan_time:.1f}s",

            "🔄 NEXT SCAN: "
            "ABOUT 5 MINUTES",
        ]
    )

    return "\n".join(
        lines
    )


# ============================================================
# GLOBAL MESSAGE VALUE
# ============================================================

market_count_for_message = 0


# ============================================================
# MAIN
# ============================================================

def main():

    global market_count_for_message

    started = time.time()

    # --------------------------------------------------------
    # TELEGRAM START
    # --------------------------------------------------------

    telegram_send(
        startup_message()
    )

    print(
        f"ATI BOT "
        f"{VERSION} "
        f"STARTED"
    )

    # --------------------------------------------------------
    # LOAD STATE
    # --------------------------------------------------------

    state = load_state()

    # --------------------------------------------------------
    # CHECK OLD PAPER TRADES
    # --------------------------------------------------------

    updates = []

    if PAPER_TRACKING:

        updates = (
            check_open_paper_trades(
                state
            )
        )

        if updates:

            save_state(
                state
            )

            send_paper_updates(
                state,
                updates,
            )

    # --------------------------------------------------------
    # MARKET DISCOVERY
    # --------------------------------------------------------

    print(
        "📡 DISCOVERING MARKETS..."
    )

    markets = (
        get_usdt_markets()
    )

    market_count_for_message = (
        len(markets)
    )

    if not markets:

        error_message = (
            f"⚠️ ATI BOT "
            f"{VERSION}\n\n"

            f"❌ TABDEAL MARKET "
            f"DATA ERROR\n"

            f"📡 No USDT markets "
            f"found.\n\n"

            f"🔎 MARKET DISCOVERY "
            f"FAILED\n"

            f"🕐 {utc_text()}"
        )

        telegram_send(
            error_message
        )

        print(
            "❌ No markets found."
        )

        return

    print(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    confirmed = []
    early = []
    watch = []

    print(
        f"🔎 SCANNING "
        f"{len(markets)} MARKETS..."
    )

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

        for future in as_completed(
            futures
        ):

            completed += 1

            try:

                result = (
                    future.result()
                )

                if result is None:

                    continue

                if (
                    result["type"]
                    == "CONFIRMED"
                ):

                    confirmed.append(
                        result
                    )

                elif (
                    result["type"]
                    == "EARLY"
                ):

                    early.append(
                        result
                    )

                elif (
                    result["type"]
                    == "WATCH"
                ):

                    watch.append(
                        result
                    )

            except Exception as e:

                symbol = futures[
                    future
                ]

                print(
                    f"Scan error "
                    f"{symbol}: {e}"
                )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

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
            x["change1h"],
        ),
        reverse=True,
    )

    watch.sort(
        key=lambda x: (
            x["score"],
            x["change15"],
            x["change1h"],
        ),
        reverse=True,
    )

    # --------------------------------------------------------
    # PAPER ADD
    # --------------------------------------------------------

    candidates_for_paper = (
        confirmed
        + early
    )

    if PAPER_TRACKING:

        add_paper_trades(
            state,
            candidates_for_paper,
        )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_state(
        state
    )

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    scan_time = (
        time.time()
        - started
    )

    message = (
        build_final_message(
            confirmed,
            early,
            watch,
            state,
            scan_time,
        )
    )

    telegram_send(
        message
    )

    # --------------------------------------------------------
    # CONSOLE
    # --------------------------------------------------------

    print("")

    print(
        "━━━━━━━━━━━━━━━━━━"
    )

    print(
        f"🟢 CONFIRMED: "
        f"{len(confirmed)}"
    )

    print(
        f"⚡ EARLY: "
        f"{len(early)}"
    )

    print(
        f"🟡 WATCH: "
        f"{len(watch)}"
    )

    print(
        f"⏱ SCAN TIME: "
        f"{scan_time:.1f}s"
    )

    print(
        "━━━━━━━━━━━━━━━━━━"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    main()
