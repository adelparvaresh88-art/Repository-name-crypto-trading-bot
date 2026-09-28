import os
import time
import json
import base64
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.6.4
# CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# FIXED TABDEAL EXCHANGE INFO MARKET DISCOVERY
# PAPER TRADE NOTIFICATION DEDUP
# ============================================================

VERSION = "V39.6.4"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000

REQUEST_TIMEOUT = 10
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
# ENVIRONMENT
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
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT-V39.6.4",
    "Accept": "application/json",
})


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
        print("⚠️ TELEGRAM CONFIG MISSING")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    chunks = []

    while len(message) > 3900:

        cut = message.rfind(
            "\n",
            0,
            3900
        )

        if cut <= 0:
            cut = 3900

        chunks.append(
            message[:cut]
        )

        message = message[cut:].lstrip()

    if message:
        chunks.append(message)

    success = True

    for chunk in chunks:

        try:

            response = session.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                },
                timeout=REQUEST_TIMEOUT,
            )

            print(
                "TELEGRAM:",
                response.status_code
            )

            if not response.ok:

                print(
                    "TELEGRAM ERROR:",
                    response.text[:500]
                )

                success = False

        except Exception as e:

            print(
                "TELEGRAM CONNECTION ERROR:",
                e
            )

            success = False

    return success


# ============================================================
# STARTUP
# ============================================================

def startup_message():

    return (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 CLEAN EARLY ENTRY + "
        f"CONFIRMED BREAKOUT\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
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
# API
# ============================================================

def api_get(
    path,
    params=None,
    retries=2
):

    url = BASE_URL + path

    for attempt in range(
        retries + 1
    ):

        try:

            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            return response.json()

        except Exception as e:

            print(
                f"API ERROR {path} "
                f"attempt {attempt + 1}: {e}"
            )

            if attempt < retries:
                time.sleep(1)

    return None


# ============================================================
# SYMBOL NORMALIZER
# ============================================================

def normalize_symbol(value):

    if value is None:
        return ""

    if not isinstance(
        value,
        str
    ):
        return ""

    symbol = (
        value
        .upper()
        .strip()
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
    )

    return symbol


# ============================================================
# EXCHANGE INFO PARSER
# ============================================================

def extract_exchange_symbols(data):

    found = set()

    if not isinstance(
        data,
        dict
    ):
        return []

    # --------------------------------------------------------
    # Standard Binance-style Tabdeal response
    # {
    #   "timezone": "...",
    #   "serverTime": ...,
    #   "symbols": [...]
    # }
    # --------------------------------------------------------

    symbols_data = data.get(
        "symbols"
    )

    if isinstance(
        symbols_data,
        list
    ):

        for item in symbols_data:

            if isinstance(
                item,
                str
            ):

                symbol = normalize_symbol(
                    item
                )

                if symbol.endswith(
                    "USDT"
                ):
                    found.add(symbol)

                continue

            if not isinstance(
                item,
                dict
            ):
                continue

            symbol = ""

            for key in (
                "symbol",
                "market",
                "pair",
                "name",
            ):

                value = item.get(
                    key
                )

                if isinstance(
                    value,
                    str
                ):

                    symbol = normalize_symbol(
                        value
                    )

                    if symbol:
                        break

            if (
                symbol.endswith("USDT")
                and symbol.isalnum()
                and len(symbol) >= 7
            ):

                status = str(
                    item.get(
                        "status",
                        "TRADING"
                    )
                ).upper()

                if status in (
                    "",
                    "TRADING",
                    "ACTIVE",
                    "ENABLED",
                    "OPEN",
                ):

                    found.add(
                        symbol
                    )

    # --------------------------------------------------------
    # Recursive fallback
    # --------------------------------------------------------

    def recursive_scan(
        obj,
        depth=0
    ):

        if depth > 8:
            return

        if isinstance(
            obj,
            list
        ):

            for item in obj:

                recursive_scan(
                    item,
                    depth + 1
                )

            return

        if not isinstance(
            obj,
            dict
        ):
            return

        for key, value in obj.items():

            key_lower = str(
                key
            ).lower()

            if key_lower in (
                "symbol",
                "market",
                "pair",
                "name",
            ):

                if isinstance(
                    value,
                    str
                ):

                    symbol = normalize_symbol(
                        value
                    )

                    if (
                        symbol.endswith("USDT")
                        and symbol.isalnum()
                        and len(symbol) >= 7
                    ):

                        found.add(
                            symbol
                        )

            recursive_scan(
                value,
                depth + 1
            )

    recursive_scan(
        data
    )

    return sorted(
        found
    )


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_markets():

    print(
        "🔎 MARKET DISCOVERY: "
        "exchangeInfo"
    )

    # --------------------------------------------------------
    # PRIMARY OFFICIAL SPOT ENDPOINT
    # --------------------------------------------------------

    endpoint = (
        "/r/api/v1/exchangeInfo"
    )

    data = api_get(
        endpoint
    )

    if data is None:

        print(
            "❌ exchangeInfo returned "
            "no data"
        )

        return []

    print(
        "📦 EXCHANGE INFO TYPE:",
        type(data).__name__
    )

    markets = extract_exchange_symbols(
        data
    )

    if markets:

        print(
            f"✅ MARKET DISCOVERY OK: "
            f"{len(markets)} USDT markets"
        )

        return markets[
            :MAX_MARKETS
        ]

    # --------------------------------------------------------
    # SECOND PASS:
    # Some API responses can wrap the actual
    # exchange information.
    # --------------------------------------------------------

    candidates = []

    if isinstance(
        data,
        dict
    ):

        for key in (
            "data",
            "result",
            "markets",
            "items",
            "resultData",
        ):

            value = data.get(
                key
            )

            if value is not None:

                candidates.append(
                    value
                )

    for candidate in candidates:

        markets = extract_exchange_symbols(
            candidate
        )

        if markets:

            print(
                f"✅ WRAPPED MARKET DATA OK: "
                f"{len(markets)} USDT markets"
            )

            return markets[
                :MAX_MARKETS
            ]

    print(
        "❌ NO USDT MARKETS FOUND"
    )

    return []


# ============================================================
# TRADES
# ============================================================

def get_trades(
    symbol
):

    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        }
    )

    if data is None:
        return []

    if isinstance(
        data,
        list
    ):
        return data

    if isinstance(
        data,
        dict
    ):

        for key in (
            "data",
            "result",
            "trades",
            "items",
        ):

            value = data.get(
                key
            )

            if isinstance(
                value,
                list
            ):

                return value

    return []


# ============================================================
# PARSE TRADE
# ============================================================

def parse_trade(
    item
):

    if isinstance(
        item,
        (list, tuple)
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
        dict
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

        if (
            trade
            and trade["price"] > 0
        ):

            parsed.append(
                trade
            )

    if not parsed:
        return []

    parsed.sort(
        key=lambda x:
        x["time"]
    )

    buckets = {}

    for trade in parsed:

        bucket = (
            trade["time"]
            // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = []

        buckets[bucket].append(
            trade
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

        candles.append({
            "time": bucket,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": volume,
        })

    return candles[
        -CANDLE_LIMIT:
    ]


# ============================================================
# AGGREGATE CANDLES
# ============================================================

def aggregate_candles(
    candles,
    factor
):

    if not candles:
        return []

    interval = (
        300000
        * factor
    )

    groups = {}

    for candle in candles:

        group_time = (
            candle["time"]
            // interval
        ) * interval

        if group_time not in groups:

            groups[group_time] = []

        groups[
            group_time
        ].append(
            candle
        )

    result = []

    for group_time in sorted(
        groups.keys()
    ):

        rows = groups[
            group_time
        ]

        if len(rows) != factor:
            continue

        rows.sort(
            key=lambda x:
            x["time"]
        )

        result.append({
            "time": group_time,

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
        })

    return result


# ============================================================
# CALCULATIONS
# ============================================================

def pct_change(
    old,
    new
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
    lookback=20
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

    average = (
        sum(previous)
        / len(previous)
    )

    if average <= 0:
        return 1.0

    return (
        current
        / average
    )


def recent_resistance(
    candles,
    lookback=20
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
    lookback=14
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
            - x["low"]
        )
        for x in rows
    ]

    return (
        sum(ranges)
        / len(ranges)
    )


# ============================================================
# CANDLE QUALITY
# ============================================================

def strong_bullish_candle(
    candle
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


# ============================================================
# RETEST
# ============================================================

def detect_retest(
    candles,
    resistance
):

    if len(candles) < 4:
        return False

    recent = candles[
        -4:
    ]

    for candle in recent:

        distance = (
            abs(
                candle["low"]
                - resistance
            )
            / resistance
            * 100
        )

        if (
            distance <= 0.40
            and candle["close"]
            >= resistance * 0.995
        ):

            return True

    return False


# ============================================================
# SCORE
# ============================================================

def calculate_score(
    change5,
    change15,
    change1h,
    vol_ratio,
    breakout,
    retest,
    strong,
    distance
):

    score = 0

    # 5M

    if change5 >= 0.15:
        score += 2

    elif change5 >= 0:
        score += 1

    # 15M

    if change15 >= 1.0:
        score += 3

    elif change15 >= 0.50:
        score += 2

    elif change15 >= 0.20:
        score += 1

    # 1H

    if change1h >= 2.0:
        score += 3

    elif change1h >= 1.0:
        score += 2

    elif change1h >= 0.50:
        score += 1

    # VOLUME

    if vol_ratio >= 2.0:
        score += 3

    elif vol_ratio >= 1.25:
        score += 2

    elif vol_ratio >= 0.80:
        score += 1

    # BREAKOUT

    if breakout:
        score += 3

    # RETEST

    if retest:
        score += 2

    # STRONG CANDLE

    if strong:
        score += 2

    # RESISTANCE

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
# FORMAT PRICE
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

        # Remove incomplete candle

        closed5 = candles5[
            :-1
        ]

        if len(closed5) < 30:
            return None

        candles15 = (
            aggregate_candles(
                closed5,
                3
            )
        )

        candles1h = (
            aggregate_candles(
                closed5,
                12
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
            current["close"]
        )

        change15 = pct_change(
            candles15[-2]["close"],
            candles15[-1]["close"]
        )

        change1h = pct_change(
            candles1h[-2]["close"],
            candles1h[-1]["close"]
        )

        vol = volume_ratio(
            closed5
        )

        resistance = (
            recent_resistance(
                closed5,
                20
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
            resistance
        )

        score = calculate_score(
            change5,
            change15,
            change1h,
            vol,
            breakout,
            retest,
            strong,
            distance
        )

        # ====================================================
        # TREND FILTER
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

        if not (
            confirmed
            or early
            or watch
        ):

            return None

        # ====================================================
        # SL / TP
        # ====================================================

        avg_range = (
            average_range(
                closed5,
                14
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
            minimum_risk
        )

        risk = min(
            risk,
            maximum_risk
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

            signal_type = "CONFIRMED"

        elif early:

            signal_type = "EARLY"

        else:

            signal_type = "WATCH"

        return {
            "symbol": symbol,
            "type": signal_type,
            "score": score,
            "price": price,
            "change5": change5,
            "change15": change15,
            "change1h": change1h,
            "volume": vol,
            "resistance": resistance,
            "distance": distance,
            "breakout": breakout,
            "retest": retest,
            "strong": strong,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "time": utc_text(),
        }

    except Exception as e:

        print(
            f"ANALYZE ERROR {symbol}: {e}"
        )

        return None


# ============================================================
# PAPER STATE
# ============================================================

def empty_state():

    return {
        "trades": []
    }


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
        raw.encode(
            "utf-8"
        )
    ).hexdigest()[:24]


# ============================================================
# NORMALIZE STATE
# ============================================================

def normalize_state(
    state
):

    if not isinstance(
        state,
        dict
    ):

        state = empty_state()

    if not isinstance(
        state.get("trades"),
        list
    ):

        state["trades"] = []

    for trade in state[
        "trades"
    ]:

        if not isinstance(
            trade,
            dict
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
# LOCAL STATE
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
            encoding="utf-8"
        ) as file:

            return normalize_state(
                json.load(file)
            )

    except Exception as e:

        print(
            "LOCAL LOAD ERROR:",
            e
        )

        return empty_state()


def save_local_state(
    state
):

    try:

        with open(
            STATE_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                normalize_state(
                    state
                ),
                file,
                ensure_ascii=False,
                indent=2
            )

        return True

    except Exception as e:

        print(
            "LOCAL SAVE ERROR:",
            e
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
        f"{GITHUB_REPOSITORY}/contents/"
        f"{STATE_FILE}"
    )


def github_headers():

    return {
        "Authorization":
            f"Bearer {GITHUB_TOKEN}",

        "Accept":
            "application/vnd.github+json",

        "X-GitHub-Api-Version":
            "2022-11-28"
    }


def load_github_state():

    url = github_url()

    if (
        not url
        or not GITHUB_TOKEN
    ):

        return None

    try:

        response = requests.get(
            url,
            headers=github_headers(),
            timeout=10
        )

        if response.status_code != 200:
            return None

        content = response.json().get(
            "content"
        )

        if not content:
            return None

        raw = base64.b64decode(
            content.replace(
                "\n",
                ""
            )
        )

        state = json.loads(
            raw.decode(
                "utf-8"
            )
        )

        return normalize_state(
            state
        )

    except Exception as e:

        print(
            "GITHUB LOAD ERROR:",
            e
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
            indent=2
        )

        encoded = base64.b64encode(
            content.encode(
                "utf-8"
            )
        ).decode(
            "utf-8"
        )

        current_sha = None

        response = requests.get(
            url,
            headers=github_headers(),
            timeout=10
        )

        if response.status_code == 200:

            current_sha = (
                response.json().get(
                    "sha"
                )
            )

        payload = {
            "message":
                f"ATI Bot {VERSION} "
                f"paper state update",

            "content":
                encoded
        }

        if current_sha:

            payload[
                "sha"
            ] = current_sha

        response = requests.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=15
        )

        if response.status_code in (
            200,
            201
        ):

            return True

        print(
            "GITHUB SAVE FAILED:",
            response.status_code,
            response.text[:300]
        )

        return False

    except Exception as e:

        print(
            "GITHUB SAVE ERROR:",
            e
        )

        return False


def load_state():

    github_state = (
        load_github_state()
    )

    if github_state is not None:

        return github_state

    return load_local_state()


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
# LATEST PRICE
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

        trade = parse_trade(
            item
        )

        if (
            trade
            and trade["price"] > 0
        ):

            parsed.append(
                trade
            )

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

    for trade in state.get(
        "trades",
        []
    ):

        if trade.get(
            "status"
        ) != "OPEN":

            continue

        symbol = trade.get(
            "symbol"
        )

        if not symbol:
            continue

        price = get_latest_price(
            symbol
        )

        if price is None:
            continue

        try:

            tp1 = float(
                trade.get(
                    "tp1",
                    0
                )
            )

            tp2 = float(
                trade.get(
                    "tp2",
                    0
                )
            )

            sl = float(
                trade.get(
                    "sl",
                    0
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
                "closed_at"
            ] = utc_text()

            trade[
                "close_price"
            ] = price

            trade[
                "notification_sent"
            ] = False

            updates.append(
                trade
            )

    return updates


# ============================================================
# PAPER UPDATE TELEGRAM
# ============================================================

def send_paper_updates(
    state,
    updates
):

    if not updates:
        return False

    pending = [
        trade
        for trade in updates
        if not trade.get(
            "notification_sent",
            False
        )
    ]

    if not pending:
        return False

    lines = [
        f"📊 ATI PAPER UPDATE {VERSION}",
        ""
    ]

    for trade in pending:

        result = trade.get(
            "result",
            "?"
        )

        if result == "TP1":
            emoji = "🎯"

        elif result == "TP2":
            emoji = "🚀"

        else:
            emoji = "🛑"

        lines.extend([
            f"{emoji} {result}",
            f"🪙 {trade.get('symbol')}",
            f"💰 ENTRY: "
            f"{fmt_price(float(trade.get('entry', 0)))}",
            f"📍 CLOSE: "
            f"{fmt_price(float(trade.get('close_price', 0)))}",
            ""
        ])

    lines.append(
        f"🕐 {utc_text()}"
    )

    success = telegram_send(
        "\n".join(lines)
    )

    if success:

        for trade in pending:

            trade[
                "notification_sent"
            ] = True

        save_state(
            state
        )

        return True

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
        trade.get("symbol")
        for trade in trades
        if trade.get("status")
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

    tp1 = 0
    tp2 = 0
    sl = 0
    opened = 0

    for trade in state.get(
        "trades",
        []
    ):

        status = trade.get(
            "status"
        )

        result = trade.get(
            "result"
        )

        if status == "OPEN":

            opened += 1

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

    if closed:

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
        "open": opened,
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
        f"{'YES' if item['breakout'] else 'NO'}\n"
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
# SCAN ALL MARKETS
# ============================================================

def scan_markets(
    markets
):

    results = []

    if not markets:
        return results

    print(
        f"🔍 SCANNING "
        f"{len(markets)} USDT MARKETS"
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol
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

                if result:

                    results.append(
                        result
                    )

            except Exception as e:

                print(
                    f"SCAN ERROR "
                    f"{symbol}: {e}"
                )

    results.sort(
        key=lambda x: (
            x["score"],
            x["change1h"],
            x["change15"],
            x["volume"]
        ),
        reverse=True
    )

    return results


# ============================================================
# BUILD TELEGRAM SCAN MESSAGE
# ============================================================

def build_scan_message(
    results,
    market_count
):

    confirmed = [
        x
        for x in results
        if x["type"]
        == "CONFIRMED"
    ][:TOP_CONFIRMED]

    early = [
        x
        for x in results
        if x["type"]
        == "EARLY"
    ][:TOP_EARLY]

    watch = [
        x
        for x in results
        if x["type"]
        == "WATCH"
    ][:TOP_WATCH]

    lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "",
        "🚀 CLEAN EARLY ENTRY + "
        "CONFIRMED BREAKOUT",
        "",
        f"📊 USDT MARKETS: "
        f"{market_count}",
        f"⏱ TIMEFRAME: 5m",
        "🕯 CLOSED CANDLE: YES",
        "📊 PAPER TRACKING: ON",
        "🔧 REAL ORDERS: DISABLED",
        "",
    ]

    if confirmed:

        lines.extend([
            "━━━━━━━━━━━━━━━━━━",
            "🟢 CONFIRMED BUY",
            "━━━━━━━━━━━━━━━━━━",
            ""
        ])

        for index, item in enumerate(
            confirmed,
            1
        ):

            lines.append(
                format_candidate(
                    item,
                    index
                )
            )

            lines.append("")

    if early:

        lines.extend([
            "━━━━━━━━━━━━━━━━━━",
            "⚡ EARLY ENTRY",
            "━━━━━━━━━━━━━━━━━━",
            ""
        ])

        for index, item in enumerate(
            early,
            1
        ):

            lines.append(
                format_candidate(
                    item,
                    index
                )
            )

            lines.append("")

    if watch:

        lines.extend([
            "━━━━━━━━━━━━━━━━━━",
            "🟡 WATCH",
            "━━━━━━━━━━━━━━━━━━",
            ""
        ])

        for index, item in enumerate(
            watch,
            1
        ):

            lines.append(
                format_candidate(
                    item,
                    index
                )
            )

            lines.append("")

    if not (
        confirmed
        or early
        or watch
    ):

        lines.extend([
            "⚪ NO SIGNAL",
            "",
            "No qualifying setup "
            "on this scan.",
            ""
        ])

    stats = paper_statistics(
        load_state()
    )

    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        "📊 PAPER STATISTICS",
        "━━━━━━━━━━━━━━━━━━",
        f"🎯 TP1: {stats['tp1']}",
        f"🚀 TP2: {stats['tp2']}",
        f"🛑 SL: {stats['sl']}",
        f"📂 OPEN: {stats['open']}",
        f"📈 WIN RATE: "
        f"{stats['win_rate']:.1f}%",
        "",
        f"🕐 {utc_text()}",
    ])

    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"ATI BOT {VERSION}"
    )

    # --------------------------------------------------------
    # Startup Telegram
    # --------------------------------------------------------

    telegram_send(
        startup_message()
    )

    # --------------------------------------------------------
    # Load paper state
    # --------------------------------------------------------

    state = load_state()

    # --------------------------------------------------------
    # Check previous paper trades
    # --------------------------------------------------------

    updates = (
        check_open_paper_trades(
            state
        )
    )

    if updates:

        send_paper_updates(
            state,
            updates
        )

    save_state(
        state
    )

    # --------------------------------------------------------
    # Market discovery
    # --------------------------------------------------------

    markets = get_markets()

    if not markets:

        message = (
            f"⚠️ ATI BOT {VERSION}\n\n"
            "❌ TABDEAL MARKET DATA ERROR\n"
            "📡 No USDT markets found.\n\n"
            "🔎 MARKET DISCOVERY FAILED\n"
            f"🕐 {utc_text()}"
        )

        telegram_send(
            message
        )

        print(
            "❌ STOP: NO MARKETS"
        )

        return

    print(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    # --------------------------------------------------------
    # Scan
    # --------------------------------------------------------

    results = scan_markets(
        markets
    )

    print(
        f"📊 SIGNAL RESULTS: "
        f"{len(results)}"
    )

    # --------------------------------------------------------
    # Paper entries
    # --------------------------------------------------------

    before_count = len(
        state.get(
            "trades",
            []
        )
    )

    add_paper_trades(
        state,
        results
    )

    after_count = len(
        state.get(
            "trades",
            []
        )
    )

    if after_count != before_count:

        print(
            "📊 NEW PAPER TRADE(S):",
            after_count
            - before_count
        )

    save_state(
        state
    )

    # --------------------------------------------------------
    # Telegram scan
    # --------------------------------------------------------

    message = build_scan_message(
        results,
        len(markets)
    )

    telegram_send(
        message
    )

    # --------------------------------------------------------
    # Final
    # --------------------------------------------------------

    print(
        "✅ SCAN COMPLETE"
    )

    print(
        f"🕐 {utc_text()}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
