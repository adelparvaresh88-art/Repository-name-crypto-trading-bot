import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.0
# REAL BREAKOUT + RETEST + CLEAN EARLY ENTRY
# ANTI-CHASE / ANTI-FAKE-BREAKOUT
# ============================================================

VERSION = "V40.0"

BASE_URL = "https://api1.tabdeal.org"

MAX_MARKETS = 1000
TOP_N = 15

REQUEST_TIMEOUT = 15

RANK_WORKERS = 20
SCAN_WORKERS = 5

PROGRESS_STEP = 50

LIVE_TRADING = False
PAPER_TRACKING = True


# ============================================================
# MOMENTUM FILTERS
# ============================================================

EARLY_5M_MIN = 0.20
EARLY_5M_MAX = 2.50

BUY_5M_MIN = 0.20
BUY_5M_MAX = 2.50

HARD_5M_REJECT = 3.50

MIN_15M = 0.30
BUY_15M_MAX = 8.00

MIN_30M = 0.50
BUY_30M_MAX = 7.00

HARD_30M_REJECT = 12.00

NEAR_HIGH_MAX = 1.50


# ============================================================
# SIGNAL THRESHOLDS
# ============================================================

BUY_SCORE = 12
EARLY_SCORE = 9
WATCH_SCORE = 7


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
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
                "text": message
            },
            timeout=15
        )

        return response.status_code == 200

    except Exception:
        return False


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def pct(old, new):
    if old <= 0:
        return 0.0

    return ((new - old) / old) * 100.0


def fmt_price(value):
    value = safe_float(value)

    if value >= 100:
        return f"{value:.4f}"

    if value >= 10:
        return f"{value:.5f}"

    if value >= 1:
        return f"{value:.6f}"

    if value >= 0.1:
        return f"{value:.7f}"

    if value >= 0.01:
        return f"{value:.8f}"

    if value >= 0.001:
        return f"{value:.9f}"

    if value >= 0.000001:
        return f"{value:.12f}"

    return f"{value:.16f}"


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()


def api_get(path, params=None):

    try:

        response = session.get(
            BASE_URL + path,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        return response.json()

    except Exception:

        return None


# ============================================================
# MARKET LIST
# ============================================================

def get_markets():

    data = api_get(
        "/r/api/v1/exchangeInfo"
    )

    if data is None:
        return []

    raw = []

    if isinstance(data, list):

        raw = data

    elif isinstance(data, dict):

        if isinstance(data.get("symbols"), list):
            raw = data["symbols"]

        elif isinstance(data.get("data"), list):
            raw = data["data"]

        elif isinstance(data.get("result"), list):
            raw = data["result"]

    markets = []

    for item in raw:

        if isinstance(item, str):

            symbol = item.upper()

            if symbol.endswith("USDT"):
                markets.append(symbol)

            continue

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("name")
            or item.get("market")
            or ""
        )

        symbol = str(symbol).upper()

        if not symbol.endswith("USDT"):
            continue

        status = str(
            item.get("status", "TRADING")
        ).upper()

        if status in (
            "TRADING",
            "ACTIVE",
            "1"
        ):
            markets.append(symbol)

    return list(dict.fromkeys(markets))[:MAX_MARKETS]


# ============================================================
# TRADE DATA
# ============================================================

def get_trades(symbol):

    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000
        }
    )

    if data is None:
        return []

    if isinstance(data, list):

        raw = data

    elif isinstance(data, dict):

        raw = (
            data.get("data")
            or data.get("trades")
            or data.get("result")
            or []
        )

    else:

        raw = []

    if not isinstance(raw, list):
        return []

    prices = []

    for item in raw:

        if isinstance(item, dict):

            price = (
                item.get("price")
                or item.get("p")
                or item.get("lastPrice")
            )

        else:

            price = item

        price = safe_float(price)

        if price > 0:
            prices.append(price)

    return prices


# ============================================================
# QUICK RANK
# ============================================================

def quick_rank(symbol):

    prices = get_trades(symbol)

    if len(prices) < 50:
        return None

    current = prices[-1]

    move5 = pct(
        prices[-6],
        current
    )

    move15 = pct(
        prices[-16],
        current
    )

    move30 = pct(
        prices[-31],
        current
    )

    # --------------------------------------------------------
    # HARD ANTI-CHASE
    # --------------------------------------------------------

    if move5 >= HARD_5M_REJECT:
        return None

    if move30 >= HARD_30M_REJECT:
        return None

    score = 0

    # Early momentum
    if EARLY_5M_MIN <= move5 <= EARLY_5M_MAX:
        score += 4

    elif 0 < move5 < EARLY_5M_MIN:
        score += 1

    # 15M trend
    if move15 >= MIN_15M:
        score += 3

    # Healthy acceleration
    if move15 > move5:
        score += 3

    # 30M trend
    if MIN_30M <= move30 <= BUY_30M_MAX:
        score += 2

    # All timeframes positive
    if (
        move5 > 0
        and move15 > 0
        and move30 > 0
    ):
        score += 2

    # Penalize excessive movement
    if move5 > 2.8:
        score -= 3

    if move15 > BUY_15M_MAX:
        score -= 4

    if move30 > BUY_30M_MAX:
        score -= 4

    return {
        "symbol": symbol,
        "price": current,
        "move5": move5,
        "move15": move15,
        "move30": move30,
        "score": score
    }


# ============================================================
# TOP CANDIDATES
# ============================================================

def select_top(markets):

    total = len(markets)

    telegram(
        "🔄 ATI " + VERSION +
        "\n📊 RANKING REAL SETUPS" +
        "\n📈 Markets: " + str(total) +
        "\n🚫 ANTI-CHASE: ON"
    )

    results = []

    completed = 0
    last_progress = 0

    with ThreadPoolExecutor(
        max_workers=RANK_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                quick_rank,
                symbol
            )
            for symbol in markets
        ]

        for future in as_completed(futures):

            completed += 1

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                pass

            if (
                completed - last_progress >= PROGRESS_STEP
                or completed == total
            ):

                last_progress = completed

                progress = (
                    completed / total * 100
                    if total
                    else 100
                )

                telegram(
                    "🔄 ATI " + VERSION +
                    "\n📊 RANKING" +
                    "\n⏳ Progress: "
                    + str(completed)
                    + "/"
                    + str(total)
                    + "\n📈 "
                    + f"{progress:.0f}"
                    + "% completed"
                    + "\n🎯 Valid: "
                    + str(len(results))
                )

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results[:TOP_N]


# ============================================================
# STRUCTURE ANALYSIS
# ============================================================

def structure_analysis(prices):

    current = prices[-1]

    if len(prices) < 80:

        return {
            "resistance": current,
            "recent_low": current,
            "distance_resistance": 0,
            "breakout": False,
            "confirmed_breakout": False,
            "retest": False,
            "hold": False
        }

    # --------------------------------------------------------
    # OLD RANGE / RESISTANCE
    # --------------------------------------------------------

    range_prices = prices[-60:-15]

    resistance = max(range_prices)

    recent_low = min(range_prices)

    distance_resistance = pct(
        resistance,
        current
    )

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    last12 = prices[-12:]

    above_count = sum(
        1 for p in last12
        if p > resistance
    )

    breakout = current > resistance

    confirmed_breakout = (
        breakout
        and above_count >= 3
    )

    # --------------------------------------------------------
    # BREAKOUT LEVEL
    # --------------------------------------------------------

    breakout_level = resistance

    # --------------------------------------------------------
    # RETEST
    #
    # Price must have traded above resistance
    # and then returned close to it.
    # --------------------------------------------------------

    had_above = any(
        p > resistance
        for p in prices[-18:-2]
    )

    retest_zone = (
        resistance * 0.997
        <= current
        <= resistance * 1.006
    )

    retest = (
        had_above
        and retest_zone
    )

    # --------------------------------------------------------
    # HOLD
    # --------------------------------------------------------

    recent8 = prices[-8:]

    local_low = min(recent8)

    hold = (
        current >= resistance * 0.997
        and current >= local_low
    )

    return {
        "resistance": resistance,
        "recent_low": recent_low,
        "distance_resistance": distance_resistance,
        "breakout": breakout,
        "confirmed_breakout": confirmed_breakout,
        "retest": retest,
        "hold": hold,
        "breakout_level": breakout_level
    }


# ============================================================
# DEEP SCAN
# ============================================================

def deep_scan(candidate):

    symbol = candidate["symbol"]

    prices = get_trades(symbol)

    if len(prices) < 80:
        return None

    current = prices[-1]

    move5 = pct(
        prices[-6],
        current
    )

    move15 = pct(
        prices[-16],
        current
    )

    move30 = pct(
        prices[-31],
        current
    )

    structure = structure_analysis(
        prices
    )

    # ========================================================
    # HARD REJECTS
    # ========================================================

    if move5 >= HARD_5M_REJECT:

        return {
            "symbol": symbol,
            "price": current,
            "move5": move5,
            "move15": move15,
            "move30": move30,
            "score": -100,
            "signal": "REJECT",
            "reason": "5M CHASE",
            "sl": 0,
            "tp1": 0,
            "tp2": 0
        }

    if move30 >= HARD_30M_REJECT:

        return {
            "symbol": symbol,
            "price": current,
            "move5": move5,
            "move15": move15,
            "move30": move30,
            "score": -100,
            "signal": "REJECT",
            "reason": "30M TOO HOT",
            "sl": 0,
            "tp1": 0,
            "tp2": 0
        }

    # ========================================================
    # SCORE
    # ========================================================

    score = 0

    reasons = []

    # --------------------------------------------------------
    # 5M
    # --------------------------------------------------------

    if (
        BUY_5M_MIN
        <= move5
        <= BUY_5M_MAX
    ):

        score += 2
        reasons.append("5M CLEAN")

    elif (
        0 < move5 < BUY_5M_MIN
    ):

        score += 1
        reasons.append("5M EARLY")

    else:

        score -= 2

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    if (
        move15 >= MIN_15M
        and move15 <= BUY_15M_MAX
    ):

        score += 2
        reasons.append("15M UP")

    elif move15 > BUY_15M_MAX:

        score -= 3
        reasons.append("15M HOT")

    else:

        score -= 2

    # --------------------------------------------------------
    # 15M > 5M
    # --------------------------------------------------------

    if move15 > move5:

        score += 2
        reasons.append("15M > 5M")

    # --------------------------------------------------------
    # 30M
    # --------------------------------------------------------

    if (
        MIN_30M
        <= move30
        <= BUY_30M_MAX
    ):

        score += 2
        reasons.append("30M HEALTHY")

    elif move30 > BUY_30M_MAX:

        score -= 3
        reasons.append("30M HOT")

    # --------------------------------------------------------
    # MULTI TIMEFRAME
    # --------------------------------------------------------

    if (
        move5 > 0
        and move15 > 0
        and move30 > 0
    ):

        score += 1
        reasons.append("MULTI TF")

    # ========================================================
    # STRUCTURE
    # ========================================================

    distance = structure[
        "distance_resistance"
    ]

    if (
        -NEAR_HIGH_MAX
        <= distance
        <= NEAR_HIGH_MAX
    ):

        score += 2
        reasons.append("NEAR RESISTANCE")

    # --------------------------------------------------------
    # CONFIRMED BREAKOUT
    # --------------------------------------------------------

    if structure[
        "confirmed_breakout"
    ]:

        score += 3
        reasons.append(
            "CONFIRMED BREAKOUT"
        )

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    if structure["retest"]:

        score += 3
        reasons.append("RETEST")

    # --------------------------------------------------------
    # HOLD
    # --------------------------------------------------------

    if structure["hold"]:

        score += 1
        reasons.append("HOLD")

    # ========================================================
    # EXTRA ANTI-CHASE
    # ========================================================

    if move5 > 2.50:

        score -= 3

    if move30 > 7.00:

        score -= 3

    # ========================================================
    # SIGNAL LOGIC
    # ========================================================

    signal = "NONE"

    # --------------------------------------------------------
    # BUY REQUIREMENTS
    #
    # Must have:
    # 1. Clean 5M
    # 2. Healthy 15M
    # 3. Healthy 30M
    # 4. Confirmed breakout
    # 5. Retest
    # 6. Hold
    # --------------------------------------------------------

    buy_momentum = (
        BUY_5M_MIN
        <= move5
        <= BUY_5M_MAX
        and
        MIN_15M
        <= move15
        <= BUY_15M_MAX
        and
        MIN_30M
        <= move30
        <= BUY_30M_MAX
    )

    buy_structure = (
        structure["confirmed_breakout"]
        and structure["retest"]
        and structure["hold"]
    )

    if (
        score >= BUY_SCORE
        and buy_momentum
        and buy_structure
    ):

        signal = "CONFIRMED BUY"

    # --------------------------------------------------------
    # EARLY ENTRY
    #
    # No chase.
    # Must be near resistance and healthy.
    # Does NOT buy an already extended pump.
    # --------------------------------------------------------

    early_structure = (
        abs(distance)
        <= 1.50
        and
        (
            structure["confirmed_breakout"]
            or structure["retest"]
            or structure["hold"]
        )
    )

    early_momentum = (
        EARLY_5M_MIN
        <= move5
        <= EARLY_5M_MAX
        and
        MIN_15M
        <= move15
        <= BUY_15M_MAX
        and
        MIN_30M
        <= move30
        <= BUY_30M_MAX
    )

    if (
        signal == "NONE"
        and score >= EARLY_SCORE
        and early_momentum
        and early_structure
    ):

        signal = "EARLY ENTRY"

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    watch_structure = (
        structure["confirmed_breakout"]
        or structure["retest"]
        or
        abs(distance) <= 1.50
    )

    if (
        signal == "NONE"
        and score >= WATCH_SCORE
        and 0 <= move5 <= BUY_5M_MAX
        and move15 > 0
        and watch_structure
    ):

        signal = "WATCH"

    # ========================================================
    # SL / TP
    # ========================================================

    resistance = structure[
        "resistance"
    ]

    recent_low = structure[
        "recent_low"
    ]

    if recent_low > 0:

        sl = recent_low * 0.997

    else:

        sl = current * 0.995

    # Don't allow extremely wide SL
    if (
        current - sl
        > current * 0.012
    ):

        sl = current * 0.995

    # Don't allow microscopic SL
    if (
        current - sl
        < current * 0.002
    ):

        sl = current * 0.998

    risk = current - sl

    if risk <= 0:

        sl = current * 0.995

        risk = current - sl

    tp1 = current + (
        risk * 1.5
    )

    tp2 = current + (
        risk * 2.5
    )

    # ========================================================
    # RETURN
    # ========================================================

    return {
        "symbol": symbol,
        "price": current,
        "move5": move5,
        "move15": move15,
        "move30": move30,
        "score": score,
        "signal": signal,
        "reason": (
            " + ".join(reasons)
            if reasons
            else "FILTER"
        ),
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2
    }


# ============================================================
# DEEP SCAN
# ============================================================

def scan_candidates(candidates):

    total = len(candidates)

    telegram(
        "🔎 ATI " + VERSION +
        "\n🎯 DEEP REAL SETUP SCAN" +
        "\n📊 Candidates: "
        + str(total) +
        "\n🚫 ANTI-CHASE: ON"
    )

    results = []

    completed = 0

    with ThreadPoolExecutor(
        max_workers=SCAN_WORKERS
    ) as executor:

        future_map = {
            executor.submit(
                deep_scan,
                candidate
            ): candidate
            for candidate in candidates
        }

        for future in as_completed(
            future_map
        ):

            completed += 1

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                pass

            if (
                completed % 5 == 0
                or completed == total
            ):

                telegram(
                    "🔎 ATI " + VERSION +
                    "\n🎯 DEEP SCAN" +
                    "\n⏳ Progress: "
                    + str(completed)
                    + "/"
                    + str(total)
                    + "\n📡 API: OK"
                )

    return results


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(item, rank):

    return (
        f"#{rank}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: "
        f"{fmt_price(item['price'])}\n"
        f"📈 5M: "
        f"{item['move5']:+.2f}%\n"
        f"📊 15M: "
        f"{item['move15']:+.2f}%\n"
        f"📊 30M: "
        f"{item['move30']:+.2f}%\n"
        f"🛑 SL: "
        f"{fmt_price(item['sl'])}\n"
        f"🎯 TP1: "
        f"{fmt_price(item['tp1'])}\n"
        f"🎯 TP2: "
        f"{fmt_price(item['tp2'])}\n"
        f"📌 {item['reason']}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    start = time.time()

    # --------------------------------------------------------
    # BOOT MESSAGE
    # --------------------------------------------------------

    telegram(
        "⚡ ATI CRYPTO BOT " + VERSION +
        "\n
