import os
import time
import json
import base64
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.4
# CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# + PAPER TRADE RESULT TRACKER
# ============================================================

VERSION = "V39.4"

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
# SCORE
# ============================================================

CONFIRMED_MIN_SCORE = 12
EARLY_MIN_SCORE = 10
WATCH_MIN_SCORE = 10

# ============================================================
# EARLY
# ============================================================

EARLY_MIN_VOLUME = 0.80
EARLY_MAX_VOLUME = 6.00
EARLY_MAX_5M_MOVE = 2.50
EARLY_MIN_15M = 0.50
EARLY_MIN_1H = 1.00
EARLY_MAX_DISTANCE = 1.20

# ============================================================
# CONFIRMED
# ============================================================

CONFIRMED_MIN_VOLUME = 1.20
CONFIRMED_MAX_VOLUME = 8.00
CONFIRMED_MAX_5M_MOVE = 4.00
CONFIRMED_MIN_15M = 0.50
CONFIRMED_MIN_1H = 1.00

# ============================================================
# WATCH
# ============================================================

WATCH_MIN_VOLUME = 0.80
WATCH_MAX_VOLUME = 6.00
WATCH_MAX_5M_MOVE = 2.50
WATCH_MIN_15M = 0.50
WATCH_MIN_1H = 1.00
WATCH_MAX_DISTANCE = 1.50

# ============================================================
# PAPER TRACKER
# ============================================================

PAPER_TRACKING = True
MAX_HISTORY = 500

STATE_FILE = "paper_trades.json"

# GitHub Actions token
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "").strip()

# ============================================================
# REAL ORDERS
# ============================================================

LIVE_TRADING = False

# ============================================================
# HTTP
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/39.4",
        "Accept": "application/json",
    }
)

# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
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

    try:

        response = SESSION.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
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
# LIST EXTRACTION
# ============================================================

def extract_list(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in [
        "data",
        "result",
        "results",
        "items",
        "symbols",
        "markets",
        "tickers",
        "rows",
    ]:

        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            nested = extract_list(value)

            if nested:
                return nested

    return []


# ============================================================
# SYMBOL
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


def extract_symbol(item):

    if isinstance(item, str):
        return normalize_symbol(item)

    if not isinstance(item, dict):
        return ""

    for key in [
        "symbol",
        "market",
        "pair",
        "code",
        "name",
        "instrument",
    ]:

        value = item.get(key)

        if isinstance(value, str):

            symbol = normalize_symbol(value)

            if symbol:
                return symbol

    return ""


# ============================================================
# MARKETS
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

        print("🔎 MARKET DISCOVERY:", endpoint)

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

        symbols = sorted(set(symbols))

        if len(symbols) >= 10:

            print(
                "✅ MARKET DISCOVERY OK:",
                len(symbols),
                "USDT markets",
            )

            return symbols[:MAX_MARKETS]

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

        symbols = sorted(set(symbols))

        if len(symbols) >= 10:

            print(
                "✅ MARKET DISCOVERY OK:",
                len(symbols),
                "USDT markets",
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
# CANDLES
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
            int(trade["time"] // 300000)
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


def aggregate_candles(
    candles,
    factor,
):

    if len(candles) < factor:
        return []

    usable = (
        len(candles)
        - len(candles) % factor
    )

    candles = candles[-usable:]

    result = []

    for i in range(
        0,
        len(candles),
        factor,
    ):

        group = candles[
            i:i + factor
        ]

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
# CALCULATIONS
# ============================================================

def pct_change(old, new):

    if old == 0:
        return 0.0

    return (
        (new - old) / old
    ) * 100.0


def volume_ratio(
    candles,
    lookback=20,
):

    if len(candles) < lookback + 1:
        return 0.0

    current = candles[-1]["volume"]

    previous = [
        x["volume"]
        for x in candles[
            -lookback - 1:-1
        ]
    ]

    if not previous:
        return 0.0

    average = sum(previous) / len(previous)

    if average <= 0:
        return 0.0

    return current / average


def recent_resistance(
    candles,
    lookback=20,
):

    if len(candles) >= lookback + 1:
        section = candles[
            -lookback - 1:-1
        ]
    else:
        section = candles[:-1]

    if not section:
        return candles[-1]["high"]

    return max(
        x["high"]
        for x in section
    )


def average_range(
    candles,
    lookback=14,
):

    if len(candles) < 2:
        return 0.0

    ranges = []

    for candle in candles[-lookback:]:

        value = (
            candle["high"]
            - candle["low"]
        )

        if value > 0:
            ranges.append(value)

    if not ranges:
        return 0.0

    return sum(ranges) / len(ranges)


def strong_bullish_candle(candle):

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
        candle["close"] > candle["open"]
        and body_ratio >= 0.50
        and close_position >= 0.70
    )


def detect_retest(
    candles,
    resistance,
):

    if len(candles) < 10:
        return False

    current = candles[-1]

    previous = candles[-6:-1]

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
                >= resistance * 0.995
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

    if current["close"] < current["open"]:

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

    if 0.20 <= change5 <= 2.50:
        score += 2

    elif 0 <= change5 < 0.20:
        score += 1

    elif 2.50 < change5 <= 4.00:
        score += 1

    if change15 >= 2.00:
        score += 3

    elif change15 >= 0.80:
        score += 2

    elif change15 > 0:
        score += 1

    if change1h >= 5.00:
        score += 3

    elif change1h >= 2.00:
        score += 2

    elif change1h > 0:
        score += 1

    if 1.20 <= volume <= 6.00:
        score += 3

    elif 0.80 <= volume < 1.20:
        score += 1

    if strong:
        score += 2

    if retest:
        score += 2

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

        candles5 = build_5m_candles(trades)

        if len(candles5) < 35:
            return None

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

        resistance = recent_resistance(
            closed5,
            20,
        )

        if resistance <= 0:
            return None

        breakout = price > resistance

        distance = (
            (
                resistance - price
            )
            / resistance
        ) * 100.0

        volume = volume_ratio(
            closed5,
            20,
        )

        if volume <= 0:
            return None

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

        if change1h <= 0:
            return None

        if change15 < -0.20:
            return None

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

        early = False

        if not confirmed and not breakout:

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
                and (
                    strong
                    or retest
                )
            ):

                early = True

        watch = False

        if (
            not confirmed
            and not early
            and not breakout
        ):

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

        if (
            not confirmed
            and not early
            and not watch
        ):
            return None

        if confirmed:
            category = "CONFIRMED"

        elif early:
            category = "EARLY"

        else:
            category = "WATCH"

        avg_range = average_range(
            closed5,
            14,
        )

        if avg_range <= 0:
            avg_range = price * 0.005

        structure_sl = (
            price
            - avg_range * 1.20
        )

        minimum_sl = price * 0.004

        stop_distance = max(
            price - structure_sl,
            minimum_sl,
        )

        stop_distance = min(
            stop_distance,
            price * 0.012,
        )

        sl = price - stop_distance

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
            f"⚠️ ANALYZE ERROR {symbol}: {e}"
        )

        return None


# ============================================================
# PRICE FORMAT
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
# GITHUB PAPER STATE
# ============================================================

def github_url():

    if not GITHUB_REPOSITORY:
        return None

    return (
        "https://api.github.com/repos/"
        + GITHUB_REPOSITORY
        + "/contents/"
        + STATE_FILE
    )


def github_headers():

    if not GITHUB_TOKEN:
        return {}

    return {
        "Authorization": "Bearer " + GITHUB_TOKEN,
        "Accept": "application/vnd.github+json",
    }


def load_paper_state():

    empty = {
        "trades": [],
    }

    # --------------------------------------------------------
    # GitHub state
    # --------------------------------------------------------

    url = github_url()

    if GITHUB_TOKEN and url:

        try:

            response = SESSION.get(
                url,
                headers=github_headers(),
                timeout=REQUEST_TIMEOUT,
            )

            if response.ok:

                data = response.json()

                content = data.get(
                    "content",
                    "",
                )

                if content:

                    decoded = base64.b64decode(
                        content
                    ).decode("utf-8")

                    state = json.loads(
                        decoded
                    )

                    if isinstance(state, dict):

                        if "trades" not in state:
                            state["trades"] = []

                        return state

        except Exception as e:

            print(
                "⚠️ GITHUB STATE LOAD ERROR:",
                e,
            )

    # --------------------------------------------------------
    # Local fallback
    # --------------------------------------------------------

    try:

        if os.path.exists(STATE_FILE):

            with open(
                STATE_FILE,
                "r",
                encoding="utf-8",
            ) as f:

                state = json.load(f)

                if isinstance(state, dict):
                    return state

    except Exception as e:

        print(
            "⚠️ LOCAL STATE LOAD ERROR:",
            e,
        )

    return empty


def save_paper_state(state):

    # Keep history limited
    trades = state.get(
        "trades",
        [],
    )

    state["trades"] = trades[
        -MAX_HISTORY:
    ]

    # --------------------------------------------------------
    # Local
    # --------------------------------------------------------

    try:

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

    except Exception as e:

        print(
            "⚠️ LOCAL STATE SAVE ERROR:",
            e,
        )

    # --------------------------------------------------------
    # GitHub
    # --------------------------------------------------------

    url = github_url()

    if not GITHUB_TOKEN or not url:
        return False

    try:

        old = SESSION.get(
            url,
            headers=github_headers(),
            timeout=REQUEST_TIMEOUT,
        )

        sha = None

        if old.ok:

            sha = old.json().get(
                "sha"
            )

        raw = json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        )

        encoded = base64.b64encode(
            raw.encode("utf-8")
        ).decode("utf-8")

        payload = {
            "message": (
                "ATI Bot paper trade state"
            ),
            "content": encoded,
        }

        if sha:
            payload["sha"] = sha

        response = SESSION.put(
            url,
            headers=github_headers(),
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:

            print(
                "💾 PAPER STATE SAVED TO GITHUB"
            )

            return True

        print(
            "⚠️ GITHUB STATE SAVE ERROR:",
            response.status_code,
            response.text[:500],
        )

    except Exception as e:

        print(
            "⚠️ GITHUB STATE SAVE EXCEPTION:",
            e,
        )

    return False


# ============================================================
# PAPER TRACKER
# ============================================================

def get_latest_price(symbol):

    trades = get_trades(symbol)

    if not trades:
        return None

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade:
            parsed.append(trade)

    if not parsed:
        return None

    parsed.sort(
        key=lambda x: x["time"]
    )

    return parsed[-1]["price"]


def track_open_trades(state):

    trades = state.get(
        "trades",
        [],
    )

    open_trades = [
        x
        for x in trades
        if x.get("status") == "OPEN"
    ]

    if not open_trades:
        return [], False

    print(
        f"📊 PAPER TRACKER: "
        f"{len(open_trades)} OPEN"
    )

    updates = []

    with ThreadPoolExecutor(
        max_workers=min(
            10,
            len(open_trades),
        )
    ) as executor:

        futures = {
            executor.submit(
                get_latest_price,
                item["symbol"],
            ): item
            for item in open_trades
        }

        for future in as_completed(
            futures
        ):

            item = futures[future]

            try:

                price = future.result()

                if price is None:
                    continue

                item["last_price"] = price
                item["last_check"] = utc_now()

                sl = float(item["sl"])
                tp1 = float(item["tp1"])
                tp2 = float(item["tp2"])

                # ------------------------------------------------
                # TP2 first
                # ------------------------------------------------

                if price >= tp2:

                    item["status"] = "TP2_HIT"
                    item["result"] = "WIN_TP2"
                    item["closed_at"] = utc_now()
                    item["exit_price"] = price

                    updates.append(
                        (
                            "TP2",
                            item.copy(),
                        )
                    )

                elif price >= tp1:

                    item["status"] = "TP1_HIT"
                    item["result"] = "WIN_TP1"
                    item["closed_at"] = utc_now()
                    item["exit_price"] = price

                    updates.append(
                        (
                            "TP1",
                            item.copy(),
                        )
                    )

                elif price <= sl:

                    item["status"] = "SL_HIT"
                    item["result"] = "LOSS"
                    item["closed_at"] = utc_now()
                    item["exit_price"] = price

                    updates.append(
                        (
                            "SL",
                            item.copy(),
                        )
                    )

            except Exception as e:

                print(
                    "⚠️ PAPER TRACK ERROR:",
                    item.get("symbol"),
                    e,
                )

    return updates, bool(updates)


# ============================================================
# ADD NEW PAPER TRADES
# ============================================================

def add_new_paper_trades(
    state,
    results,
):

    if not PAPER_TRACKING:
        return []

    trades = state.get(
        "trades",
        [],
    )

    existing_open = {
        x.get("symbol")
        for x in trades
        if x.get("status") == "OPEN"
    }

    added = []

    for item in results:

        # WATCH does not become a paper trade
        if item["category"] == "WATCH":
            continue

        symbol = item["symbol"]

        # Do not duplicate an open signal
        if symbol in existing_open:
            continue

        record = {
            "id": (
                symbol
                + "_"
                + str(
                    int(
                        time.time()
                    )
                )
            ),
            "symbol": symbol,
            "category": item["category"],
            "score": item["score"],
            "entry": item["price"],
            "sl": item["sl"],
            "tp1": item["tp1"],
            "tp2": item["tp2"],
            "status": "OPEN",
            "result": "",
            "created_at": utc_now(),
            "closed_at": "",
            "exit_price": None,
            "last_price": item["price"],
            "last_check": utc_now(),
        }

        trades.append(record)
        existing_open.add(symbol)
        added.append(record)

    state["trades"] = trades[
        -MAX_HISTORY:
    ]

    return added


# ============================================================
# PAPER RESULT MESSAGE
# ============================================================

def build_paper_result_message(
    updates,
):

    if not updates:
        return None

    lines = [
        f"📊 ATI PAPER RESULT {VERSION}",
        "",
    ]

    for result_type, item in updates:

        if result_type == "TP2":

            lines.append(
                "🎯 TP2 HIT"
            )

        elif result_type == "TP1":

            lines.append(
                "🎯 TP1 HIT"
            )

        else:

            lines.append(
                "🛑 SL HIT"
            )

        lines.extend(
            [
                f"🪙 {item['symbol']}",
                f"📂 {item['category']}",
                f"💰 ENTRY: {fmt_price(item['entry'])}",
                f"📍 EXIT: {fmt_price(item['exit_price'])}",
                f"🛑 SL: {fmt_price(item['sl'])}",
                f"🎯 TP1: {fmt_price(item['tp1'])}",
                f"🎯 TP2: {fmt_price(item['tp2'])}",
                "",
            ]
        )

    return "\n".join(lines)


# ============================================================
# PAPER STATISTICS
# ============================================================

def paper_statistics(state):

    trades = state.get(
        "trades",
        [],
    )

    closed = [
        x
        for x in trades
        if x.get("status")
        in [
            "TP1_HIT",
            "TP2_HIT",
            "SL_HIT",
        ]
    ]

    open_count = len(
        [
            x
            for x in trades
            if x.get("status") == "OPEN"
        ]
    )

    tp1 = len(
        [
            x
            for x in closed
            if x.get("status") == "TP1_HIT"
        ]
    )

    tp2 = len(
        [
            x
            for x in closed
            if x.get("status") == "TP2_HIT"
        ]
    )

    sl = len(
        [
            x
            for x in closed
            if x.get("status") == "SL_HIT"
        ]
    )

    wins = tp1 + tp2

    total = len(closed)

    win_rate = (
        (wins / total) * 100
        if total
        else 0.0
    )

    confirmed = [
        x
        for x in closed
        if x.get("category") == "CONFIRMED"
    ]

    early = [
        x
        for x in closed
        if x.get("category") == "EARLY"
    ]

    confirmed_wins = len(
        [
            x
            for x in confirmed
            if x.get("status")
            in [
                "TP1_HIT",
                "TP2_HIT",
            ]
        ]
    )

    early_wins = len(
        [
            x
            for x in early
            if x.get("status")
            in [
                "TP1_HIT",
                "TP2_HIT",
            ]
        ]
    )

    confirmed_rate = (
        confirmed_wins
        / len(confirmed)
        * 100
        if confirmed
        else 0.0
    )

    early_rate = (
        early_wins
        / len(early)
        * 100
        if early
        else 0.0
    )

    return {
        "total": total,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "open": open_count,
        "win_rate": win_rate,
        "confirmed": len(confirmed),
        "confirmed_rate": confirmed_rate,
        "early": len(early),
        "early_rate": early_rate,
    }


def build_statistics_message(state):

    s = paper_statistics(state)

    lines = [
        f"📊 ATI PAPER STATISTICS {VERSION}",
        "",
        f"📌 CLOSED TRADES: {s['total']}",
        f"⏳ OPEN: {s['open']}",
        "",
        f"🎯 TP1: {s['tp1']}",
        f"🎯 TP2: {s['tp2']}",
        f"🛑 SL: {s['sl']}",
        "",
        f"📈 WIN RATE: {s['win_rate']:.1f}%",
        "",
        "🟢 CONFIRMED:",
        f"Trades: {s['confirmed']}",
        f"Win Rate: {s['confirmed_rate']:.1f}%",
        "",
        "⚡ EARLY:",
        f"Trades: {s['early']}",
        f"Win Rate: {s['early_rate']:.1f}%",
    ]

    return "\n".join(lines)


# ============================================================
# SIGNAL FORMAT
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
            f"{abs(item['distance']):.2f}% ABOVE"
        )

    else:

        resistance_text = (
            f"{item['distance']:.2f}% BELOW"
        )

    lines = [
        title,
        f"#{number}",
        f"🪙 {item['symbol']}",
        f"⭐ SCORE: {item['score']}",
        f"💰 PRICE: {fmt_price(item['price'])}",
        f"📈 5M: {item['change5']:+.2f}%",
        f"📊 15M: {item['change15']:+.2f}%",
        f"⏱ 1H: {item['change1h']:+.2f}%",
        f"🔊 VOLUME: {item['volume']:.2f}x",
        f"📏 RESISTANCE: {resistance_text}",
        (
            "🔁 RETEST: "
            + (
                "YES"
                if item["retest"]
                else "NO"
            )
        ),
        (
            "💥 BREAKOUT: "
            + (
                "YES"
                if item["breakout"]
                else "NO"
            )
        ),
        (
            "🕯 STRONG CANDLE: "
            + (
                "YES"
                if item["strong"]
                else "NO"
            )
        ),
        f"🛑 SL: {fmt_price(item['sl'])}",
        f"🎯 TP1: {fmt_price(item['tp1'])}",
        f"🎯 TP2: {fmt_price(item['tp2'])}",
    ]

    return "\n".join(lines)


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

                symbol = futures[future]

                print(
                    f"⚠️ WORKER ERROR {symbol}: {e}"
                )

    elapsed = (
        time.time() - start
    )

    return results, elapsed


# ============================================================
# MESSAGE
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

    lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "",
        "🚀 CLEAN EARLY ENTRY + CONFIRMED BREAKOUT",
        "",
        "📡 TABDEAL API: OK",
        f"📊 USDT MARKETS: {len(markets)}",
        "⏱ TIMEFRAME: 5m",
        "🕯 CLOSED CANDLE: YES",
        "📊 PAPER TRACKING: ON",
        "🔧 REAL ORDERS: DISABLED",
        f"🕐 {utc_now()}",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🟢 CONFIRMED BUYS",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if confirmed:

        for i, item in enumerate(
            confirmed[:TOP_CONFIRMED],
            1,
        ):

            lines.append(
                format_signal(
                    item,
                    i,
                )
            )

            lines.append("")

    else:

        lines.append(
            "❌ No confirmed BUY signal."
        )

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "⚡ EARLY BUY",
            "━━━━━━━━━━━━━━━━━━",
        ]
    )

    if early:

        for i, item in enumerate(
            early[:TOP_EARLY],
            1,
        ):

            lines.append(
                format_signal(
                    item,
                    i,
                )
            )

            lines.append("")

    else:

        lines.append(
            "❌ No early BUY signal."
        )

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "🟡 WATCH",
            "━━━━━━━━━━━━━━━━━━",
        ]
    )

    if watch:

        for i, item in enumerate(
            watch[:TOP_WATCH],
            1,
        ):

            lines.append(
                format_signal(
                    item,
                    i,
                )
            )

            lines.append("")

    else:

        lines.append(
            "❌ No WATCH candidates."
        )

    s = paper_statistics(
        load_paper_state()
    )

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "📊 PAPER RESULTS",
            "━━━━━━━━━━━━━━━━━━",
            f"🎯 TP1: {s['tp1']}",
            f"🎯 TP2: {s['tp2']}",
            f"🛑 SL: {s['sl']}",
            f"⏳ OPEN: {s['open']}",
            f"📈 WIN RATE: {s['win_rate']:.1f}%",
            "",
            f"📌 TOTAL CANDIDATES: {len(results)}",
            f"🟢 CONFIRMED: {len(confirmed)}",
            f"⚡ EARLY: {len(early)}",
            f"🟡 WATCH: {len(watch)}",
            f"⏱ SCAN TIME: {scan_time:.1f}s",
            "🔄 NEXT SCAN: ABOUT 5 MINUTES",
        ]
    )

    return "\n".join(lines)


# ============================================================
# MARKET ERROR
# ============================================================

def build_market_error_message():

    lines = [
        f"⚠️ ATI CRYPTO BOT {VERSION}",
        "",
        "❌ TABDEAL MARKET DATA ERROR",
        "",
        "📡 TABDEAL API: CONNECTED",
        "❌ USDT MARKET LIST: FAILED",
        "",
        "🚫 SCAN STOPPED SAFELY",
        "🚫 BTCUSDT FALLBACK DISABLED",
        "",
        f"🕐 {utc_now()}",
        "",
        "🔧 REAL ORDERS: DISABLED",
    ]

    return "\n".join(lines)


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

    # ========================================================
    # LOAD PAPER STATE
    # ========================================================

    paper_state = load_paper_state()

    # ========================================================
    # CHECK OLD TRADES FIRST
    # ========================================================

    updates, changed = track_open_trades(
        paper_state
    )

    if updates:

        result_message = (
            build_paper_result_message(
                updates
            )
        )

        if result_message:
            telegram_send(
                result_message
            )

        stats_message = (
            build_statistics_message(
                paper_state
            )
        )

        telegram_send(
            stats_message
        )

        changed = True

    # ========================================================
    # STARTUP
    # ========================================================

    startup_lines = [
        f"🟢 ATI CRYPTO BOT {VERSION}",
        "",
        "🚀 CLEAN EARLY ENTRY + CONFIRMED BREAKOUT",
        "",
        "📡 TABDEAL API: CONNECTING...",
        "📊 SCAN: STARTING",
        "⏱ TIMEFRAME: 5m",
        "📊 PAPER TRACKING: ON",
        "🔄 NEXT SCAN: ABOUT 5 MINUTES",
        "🔧 REAL ORDERS: DISABLED",
        "",
        f"🕐 {utc_now()}",
    ]

    telegram_send(
        "\n".join(startup_lines)
    )

    # ========================================================
    # MARKET DISCOVERY
    # ========================================================

    markets = get_usdt_markets()

    if not markets:

        telegram_send(
            build_market_error_message()
        )

        return

    print(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    # ========================================================
    # SCAN
    # ========================================================

    results, scan_time = scan_markets(
        markets
    )

    # ========================================================
    # ADD PAPER TRADES
    # ========================================================

    new_paper = add_new_paper_trades(
        paper_state,
        results,
    )

    if new_paper:

        changed = True

        print(
            "📝 NEW PAPER TRADES:",
            len(new_paper),
        )

    # ========================================================
    # SAVE STATE
    # ========================================================

    if changed or new_paper:

        save_paper_state(
            paper_state
        )

    # ========================================================
    # RESULT MESSAGE
    # ========================================================

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


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
