import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.0.1
# CLEAN BREAKOUT + RETEST
# ANTI-CHASE
# ============================================================

VERSION = "V40.0.1"

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
# FILTERS
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

NEAR_RESISTANCE_MAX = 1.50

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
# SESSION
# ============================================================

session = requests.Session()


# ============================================================
# API
# ============================================================

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
# MARKETS
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
# TRADES
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

    # Anti-chase
    if move5 >= HARD_5M_REJECT:
        return None

    if move30 >= HARD_30M_REJECT:
        return None

    score = 0

    # 5M
    if EARLY_5M_MIN <= move5 <= EARLY_5M_MAX:
        score += 4

    elif 0 < move5 < EARLY_5M_MIN:
        score += 1

    # 15M
    if MIN_15M <= move15 <= BUY_15M_MAX:
        score += 3

    # Healthy trend
    if move15 > move5:
        score += 3

    # 30M
    if MIN_30M <= move30 <= BUY_30M_MAX:
        score += 2

    # Multi timeframe
    if move5 > 0 and move15 > 0 and move30 > 0:
        score += 2

    # Penalties
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
# RANK ALL MARKETS
# ============================================================

def select_top(markets):

    total = len(markets)

    telegram(
        "🔄 ATI " + VERSION
        + "\n📊 RANKING CLEAN CANDIDATES"
        + "\n📈 Markets: " + str(total)
        + "\n🚫 ANTI-CHASE: ON"
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

                if result is not None:
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
                    "🔄 ATI " + VERSION
                    + "\n📊 RANKING"
                    + "\n⏳ Progress: "
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
# STRUCTURE
# ============================================================

def structure_analysis(prices):

    current = prices[-1]

    if len(prices) < 80:

        return {
            "resistance": current,
            "recent_low": current,
            "distance": 0.0,
            "breakout": False,
            "confirmed_breakout": False,
            "retest": False,
            "hold": False
        }

    # Previous range.
    range_prices = prices[-60:-15]

    resistance = max(range_prices)
    recent_low = min(range_prices)

    distance = pct(
        resistance,
        current
    )

    # --------------------------------------------------------
    # BREAKOUT CONFIRMATION
    # --------------------------------------------------------

    last12 = prices[-12:]

    above_count = sum(
        1
        for price in last12
        if price > resistance
    )

    breakout = current > resistance

    confirmed_breakout = (
        breakout
        and above_count >= 3
    )

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    previous_prices = prices[-20:-2]

    had_above = any(
        price > resistance
        for price in previous_prices
    )

    retest_low = resistance * 0.997
    retest_high = resistance * 1.006

    retest_zone = (
        current >= retest_low
        and current <= retest_high
    )

    retest = (
        had_above
        and retest_zone
    )

    # --------------------------------------------------------
    # HOLD
    # --------------------------------------------------------

    last8 = prices[-8:]

    local_low = min(last8)

    hold = (
        current >= resistance * 0.997
        and current >= local_low
    )

    return {
        "resistance": resistance,
        "recent_low": recent_low,
        "distance": distance,
        "breakout": breakout,
        "confirmed_breakout": confirmed_breakout,
        "retest": retest,
        "hold": hold
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
    # HARD REJECT
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

    # 5M
    if BUY_5M_MIN <= move5 <= BUY_5M_MAX:

        score += 2
        reasons.append("5M CLEAN")

    elif 0 < move5 < BUY_5M_MIN:

        score += 1
        reasons.append("5M EARLY")

    else:

        score -= 2

    # 15M
    if MIN_15M <= move15 <= BUY_15M_MAX:

        score += 2
        reasons.append("15M UP")

    elif move15 > BUY_15M_MAX:

        score -= 3
        reasons.append("15M HOT")

    else:

        score -= 2

    # 15M stronger than 5M
    if move15 > move5:

        score += 2
        reasons.append("15M > 5M")

    # 30M
    if MIN_30M <= move30 <= BUY_30M_MAX:

        score += 2
        reasons.append("30M HEALTHY")

    elif move30 > BUY_30M_MAX:

        score -= 3
        reasons.append("30M HOT")

    # Multi timeframe
    if (
        move5 > 0
        and move15 > 0
        and move30 > 0
    ):

        score += 1
        reasons.append("MULTI TF")

    # Near resistance
    distance = structure["distance"]

    if (
        -NEAR_RESISTANCE_MAX
        <= distance
        <= NEAR_RESISTANCE_MAX
    ):

        score += 2
        reasons.append("NEAR RESISTANCE")

    # Confirmed breakout
    if structure["confirmed_breakout"]:

        score += 3
        reasons.append("BREAKOUT CONFIRMED")

    # Retest
    if structure["retest"]:

        score += 3
        reasons.append("RETEST")

    # Hold
    if structure["hold"]:

        score += 1
        reasons.append("HOLD")

    # Extra anti-chase
    if move5 > 2.50:
        score -= 3

    if move30 > 7.00:
        score -= 3

    # ========================================================
    # BUY CONDITIONS
    # ========================================================

    buy_momentum = (
        BUY_5M_MIN <= move5 <= BUY_5M_MAX
        and MIN_15M <= move15 <= BUY_15M_MAX
        and MIN_30M <= move30 <= BUY_30M_MAX
    )

    buy_structure = (
        structure["confirmed_breakout"]
        and structure["retest"]
        and structure["hold"]
    )

    signal = "NONE"

    if (
        score >= BUY_SCORE
        and buy_momentum
        and buy_structure
    ):

        signal = "CONFIRMED BUY"

    # ========================================================
    # EARLY ENTRY
    # ========================================================

    early_momentum = (
        EARLY_5M_MIN <= move5 <= EARLY_5M_MAX
        and MIN_15M <= move15 <= BUY_15M_MAX
        and MIN_30M <= move30 <= BUY_30M_MAX
    )

    early_structure = (
        abs(distance) <= NEAR_RESISTANCE_MAX
        and (
            structure["confirmed_breakout"]
            or structure["retest"]
            or structure["hold"]
        )
    )

    if (
        signal == "NONE"
        and score >= EARLY_SCORE
        and early_momentum
        and early_structure
    ):

        signal = "EARLY ENTRY"

    # ========================================================
    # WATCH
    # ========================================================

    watch_structure = (
        structure["confirmed_breakout"]
        or structure["retest"]
        or abs(distance) <= NEAR_RESISTANCE_MAX
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
    # SL
    # ========================================================

    recent_low = structure["recent_low"]

    if recent_low > 0:
        sl = recent_low * 0.997
    else:
        sl = current * 0.995

    # Maximum SL distance
    if current - sl > current * 0.012:
        sl = current * 0.995

    # Minimum SL distance
    if current - sl < current * 0.002:
        sl = current * 0.998

    risk = current - sl

    if risk <= 0:
        sl = current * 0.995
        risk = current - sl

    # ========================================================
    # TP
    # ========================================================

    tp1 = current + risk * 1.5
    tp2 = current + risk * 2.5

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
# DEEP SCAN ALL TOP CANDIDATES
# ============================================================

def scan_candidates(candidates):

    total = len(candidates)

    telegram(
        "🔎 ATI " + VERSION
        + "\n🎯 DEEP STRUCTURE SCAN"
        + "\n📊 Candidates: " + str(total)
        + "\n🛡 BREAKOUT + RETEST"
        + "\n🚫 ANTI-CHASE: ON"
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

                if result is not None:
                    results.append(result)

            except Exception:
                pass

            if (
                completed % 5 == 0
                or completed == total
            ):

                telegram(
                    "🔎 ATI " + VERSION
                    + "\n🎯 DEEP SCAN"
                    + "\n⏳ Progress: "
                    + str(completed)
                    + "/"
                    + str(total)
                    + "\n📡 TABDEAL API: OK"
                )

    return results


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(item, rank):

    return (
        "#" + str(rank)
        + "\n🪙 " + item["symbol"]
        + "\n⭐ SCORE: " + str(item["score"])
        + "\n💰 PRICE: " + fmt_price(item["price"])
        + "\n📈 5M: " + f"{item['move5']:+.2f}%"
        + "\n📊 15M: " + f"{item['move15']:+.2f}%"
        + "\n📊 30M: " + f"{item['move30']:+.2f}%"
        + "\n🛑 SL: " + fmt_price(item["sl"])
        + "\n🎯 TP1: " + fmt_price(item["tp1"])
        + "\n🎯 TP2: " + fmt_price(item["tp2"])
        + "\n📌 " + item["reason"]
    )


# ============================================================
# MAIN
# ============================================================

def main():

    start = time.time()

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    telegram(
        "⚡ ATI CRYPTO BOT " + VERSION
        + "\n🎯 CLEAN BREAKOUT + RETEST"
        + "\n🚀 EARLY ENTRY"
        + "\n🛡 ANTI-FAKE BREAKOUT"
        + "\n🚫 ANTI-CHASE"
        + "\n\n"
        + "📡 TABDEAL API: CONNECTING..."
        + "\n⏱ TIMEFRAME: 5m"
        + "\n📊 PAPER TRACKING: ON"
        + "\n🔧 REAL ORDERS: DISABLED"
        + "\n🕐 " + now_utc()
    )

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    markets = get_markets()

    if not markets:

        telegram(
            "❌ ATI " + VERSION
            + "\nTABDEAL MARKET DATA ERROR"
        )

        return

    telegram(
        "⚡ ATI " + VERSION
        + "\n📡 TABDEAL API: OK"
        + "\n📊 USDT MARKETS: "
        + str(len(markets))
        + "\n🎯 BREAKOUT FILTER: ON"
        + "\n🛡 RETEST FILTER: ON"
        + "\n🚫 BUY 5M MAX: "
        + str(BUY_5M_MAX)
        + "%"
        + "\n🚫 BUY 30M MAX: "
        + str(BUY_30M_MAX)
        + "%"
    )

    # --------------------------------------------------------
    # RANK
    # --------------------------------------------------------

    candidates = select_top(markets)

    if not candidates:

        telegram(
            "⚠️ ATI " + VERSION
            + "\n❌ NO CLEAN CANDIDATES"
        )

        return

    telegram(
        "🎯 ATI " + VERSION
        + "\n📊 TOP "
        + str(len(candidates))
        + " CANDIDATES"
        + "\n🔎 DEEP SCAN STARTING..."
    )

    # --------------------------------------------------------
    # DEEP SCAN
    # --------------------------------------------------------

    results = scan_candidates(
        candidates
    )

    valid = [
        item
        for item in results
        if item["signal"] != "REJECT"
    ]

    valid.sort(
        key=lambda item: item["score"],
        reverse=True
    )

    buys = [
        item
        for item in valid
        if item["signal"] == "CONFIRMED BUY"
    ]

    early = [
        item
        for item in valid
        if item["signal"] == "EARLY ENTRY"
    ]

    watch = [
        item
        for item in valid
        if item["signal"] == "WATCH"
    ]

    # --------------------------------------------------------
    # FINAL MESSAGE
    # --------------------------------------------------------

    message = (
        "⚡ ATI CRYPTO BOT " + VERSION
        + "\n🎯 CLEAN BREAKOUT + RETEST"
        + "\n🚀 EARLY ENTRY"
        + "\n🛡 ANTI-FAKE BREAKOUT"
        + "\n🚫 ANTI-CHASE"
        + "\n\n"
        + "📡 TABDEAL API: OK"
        + "\n📊 USDT MARKETS: "
        + str(len(markets))
        + "\n🎯 DEEP SCAN: TOP "
        + str(len(candidates))
        + "\n🕐 " + now_utc()
    )

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    message += (
        "\n\n━━━━━━━━━━━━━━━━━━"
        + "\n🟢 CONFIRMED BUY"
        + "\n━━━━━━━━━━━━━━━━━━"
    )

    if buys:

        for i, item in enumerate(
            buys[:5],
            1
        ):

            message += (
                "\n\n"
                + format_signal(
                    item,
                    i
                )
            )

    else:

        message += "\nNONE"

    # --------------------------------------------------------
    # EARLY
    # --------------------------------------------------------

    message += (
        "\n\n━━━━━━━━━━━━━━━━━━"
        + "\n⚡ EARLY ENTRY"
        + "\n━━━━━━━━━━━━━━━━━━"
    )

    if early:

        for i, item in enumerate(
            early[:5],
            1
        ):

            message += (
                "\n\n"
                + format_signal(
                    item,
                    i
                )
            )

    else:

        message += "\nNONE"

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    message += (
        "\n\n━━━━━━━━━━━━━━━━━━"
        + "\n🟡 WATCH"
        + "\n━━━━━━━━━━━━━━━━━━"
    )

    if watch:

        for i, item in enumerate(
            watch[:5],
            1
        ):

            message += (
                "\n\n"
                + format_signal(
                    item,
                    i
                )
            )

    else:

        message += "\nNONE"

    # --------------------------------------------------------
    # STATS
    # --------------------------------------------------------

    elapsed = time.time() - start

    message += (
        "\n\n━━━━━━━━━━━━━━━━━━"
        + "\n📊 PAPER STATS"
        + "\n━━━━━━━━━━━━━━━━━━"
        + "\nTrades: 0 | TP: 0 | SL: 0 | OPEN: 0"
        + "\n⏱ Scan time: "
        + f"{elapsed:.1f}"
        + " sec"
        + "\n🔧 REAL ORDERS: DISABLED"
    )

    telegram(message)


# ============================================================
# ERROR HANDLER
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        telegram(
            "🚨 ATI " + VERSION
            + "\n❌ BOT ERROR"
            + "\n"
            + str(error)
        )

        raise
