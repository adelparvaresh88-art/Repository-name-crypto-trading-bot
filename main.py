import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.9.0
# PRECISION FILTER
# EARLY ENTRY + CLEAN BREAKOUT + PULLBACK
# ============================================================

VERSION = "V39.9.0"

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
# PRECISION FILTERS
# ============================================================

EARLY_5M_MIN = 0.20
EARLY_5M_MAX = 3.00

# بالاتر از این مقدار تعقیب قیمت محسوب می‌شود
HARD_5M_REJECT = 5.00

# برای BUY سخت‌گیرانه‌تر
BUY_5M_MAX = 2.50

MIN_15M = 0.30
BUY_15M_MAX = 12.00

MIN_30M = 0.50

# اگر 30M بیش از این رشد کرده باشد، BUY ممنوع
BUY_30M_MAX = 7.00

# فاصله از سقف اخیر
NEAR_HIGH_MAX = 2.00

# حداقل Score فقط برای کمک به فیلتر
WATCH_SCORE = 7
EARLY_SCORE = 9
BUY_SCORE = 11


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
                "text": message,
            },
            timeout=15,
        )

        return response.status_code == 200

    except Exception:

        return False


# ============================================================
# HELPERS
# ============================================================

def now_utc():

    return datetime.now(
        timezone.utc
    ).strftime(
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

    return (
        (new - old)
        / old
        * 100.0
    )


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
# API
# ============================================================

session = requests.Session()


def api_get(path, params=None):

    try:

        response = session.get(
            BASE_URL + path,
            params=params,
            timeout=REQUEST_TIMEOUT,
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

        if isinstance(
            data.get("symbols"),
            list
        ):
            raw = data["symbols"]

        elif isinstance(
            data.get("data"),
            list
        ):
            raw = data["data"]

        elif isinstance(
            data.get("result"),
            list
        ):
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

        symbol = str(
            symbol
        ).upper()

        if not symbol.endswith("USDT"):
            continue

        status = str(
            item.get(
                "status",
                "TRADING"
            )
        ).upper()

        if status in (
            "TRADING",
            "ACTIVE",
            "1",
        ):
            markets.append(symbol)

    return list(
        dict.fromkeys(markets)
    )[:MAX_MARKETS]


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

    if len(prices) < 40:
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

    # حذف پامپ شدید از Ranking
    if move5 > HARD_5M_REJECT:
        return None

    if move30 > 20:
        return None

    score = 0

    if move5 > 0:
        score += 2

    if (
        EARLY_5M_MIN
        <= move5
        <= EARLY_5M_MAX
    ):
        score += 4

    if move15 > MIN_15M:
        score += 3

    if move15 > move5:
        score += 2

    if move30 > MIN_30M:
        score += 2

    if (
        move5 > 0
        and move15 > 0
        and move30 > 0
    ):
        score += 2

    if move5 > 3:
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
        "score": score,
    }


# ============================================================
# RANK ALL MARKETS
# ============================================================

def select_top(markets):

    total = len(markets)

    telegram(
        "🔄 ATI "
        + VERSION
        + "\n"
        "📊 RANKING PRECISION CANDIDATES\n"
        "📈 Markets: "
        + str(total)
        + "\n"
        "🚫 ANTI-CHASE: ON"
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

        for future in as_completed(
            futures
        ):

            completed += 1

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:

                pass

            if (
                completed
                - last_progress
                >= PROGRESS_STEP
                or completed == total
            ):

                last_progress = completed

                progress = (
                    completed
                    / total
                    * 100
                    if total
                    else 100
                )

                telegram(
                    "🔄 ATI "
                    + VERSION
                    + "\n"
                    "📊 RANKING PRECISION\n"
                    "⏳ Progress: "
                    + str(completed)
                    + "/"
                    + str(total)
                    + "\n"
                    "📈 "
                    + f"{progress:.0f}%"
                    + " completed\n"
                    "🎯 Valid: "
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

    if len(prices) < 60:

        return {
            "recent_high": current,
            "recent_low": current,
            "distance_high": 0,
            "breakout": False,
            "pullback": False,
            "hold": False,
        }

    # محدوده قبل از حرکت فعلی
    base = prices[-36:-6]

    recent_high = max(base)
    recent_low = min(base)

    distance_high = pct(
        recent_high,
        current
    )

    # شکست سقف
    breakout = (
        current
        > recent_high
    )

    # --------------------------------------------------------
    # بررسی پولبک
    # --------------------------------------------------------

    last10 = prices[-10:]

    local_high = max(
        last10[:-2]
    )

    latest = last10[-1]

    pullback_pct = pct(
        local_high,
        latest
    )

    pullback = (
        -2.0
        <= pullback_pct
        <= 0.60
        and local_high >= recent_high
    )

    # --------------------------------------------------------
    # HOLD
    # --------------------------------------------------------

    last_low = min(
        prices[-8:]
    )

    hold = (
        current >= last_low
    )

    return {
        "recent_high": recent_high,
        "recent_low": recent_low,
        "distance_high": distance_high,
        "breakout": breakout,
        "pullback": pullback,
        "hold": hold,
    }


# ============================================================
# DEEP SCAN
# ============================================================

def deep_scan(candidate):

    symbol = candidate["symbol"]

    prices = get_trades(symbol)

    if len(prices) < 60:
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

    score = 0
    reasons = []

    # ========================================================
    # HARD FILTERS
    # ========================================================

    if move5 > HARD_5M_REJECT:

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
            "tp2": 0,
        }

    if move30 > 15:

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
            "tp2": 0,
        }

    # ========================================================
    # MOMENTUM
    # ========================================================

    if (
        EARLY_5M_MIN
        <= move5
        <= EARLY_5M_MAX
    ):

        score += 3
        reasons.append(
            "5M EARLY"
        )

    elif move5 > 0:

        score += 1

    else:

        score -= 3

    # ========================================================
    # 15M
    # ========================================================

    if move15 > MIN_15M:

        score += 2
        reasons.append(
            "15M UP"
        )

    else:

        score -= 2

    if move15 > move5:

        score += 2
        reasons.append(
            "15M > 5M"
        )

    # ========================================================
    # 30M
    # ========================================================

    if (
        move30 > MIN_30M
        and move30 <= BUY_30M_MAX
    ):

        score += 2
        reasons.append(
            "30M HEALTHY"
        )

    elif move30 > BUY_30M_MAX:

        score -= 3

    # ========================================================
    # MULTI TF
    # ========================================================

    if (
        move5 > 0
        and move15 > 0
        and move30 > 0
    ):

        score += 2
        reasons.append(
            "MULTI TF"
        )

    # ========================================================
    # NEAR HIGH
    # ========================================================

    distance_high = (
        structure["distance_high"]
    )

    if (
        -NEAR_HIGH_MAX
        <= distance_high
        <= NEAR_HIGH_MAX
    ):

        score += 2
        reasons.append(
            "NEAR HIGH"
        )

    # ========================================================
    # BREAKOUT
    # ========================================================

    if structure["breakout"]:

        score += 3
        reasons.append(
            "BREAKOUT"
        )

    # ========================================================
    # PULLBACK
    # ========================================================

    if structure["pullback"]:

        score += 3
        reasons.append(
            "PULLBACK"
        )

    # ========================================================
    # HOLD
    # ========================================================

    if structure["hold"]:

        score += 1
        reasons.append(
            "HOLD"
        )

    # ========================================================
    # ADDITIONAL ANTI-CHASE
    # ========================================================

    if move5 > 2.5:

        score -= 3

    if move15 > BUY_15M_MAX:

        score -= 4

    if move30 > BUY_30M_MAX:

        score -= 4

    # ========================================================
    # BUY STRUCTURE REQUIREMENTS
    # ========================================================

    valid_momentum = (
        EARLY_5M_MIN
        <= move5
        <= BUY_5M_MAX
        and move15 > MIN_15M
        and move30 > MIN_30M
        and move30 <= BUY_30M_MAX
    )

    has_structure = (
        structure["breakout"]
        or structure["pullback"]
    )

    clean_structure = (
        structure["hold"]
        and distance_high
        <= NEAR_HIGH_MAX
    )

    # ========================================================
    # SIGNAL
    # ========================================================

    signal = "NONE"

    # BUY بسیار سخت‌گیر
    if (
        score >= BUY_SCORE
        and valid_momentum
        and has_structure
        and clean_structure
    ):

        signal = "CONFIRMED BUY"

    # EARLY ENTRY
    elif (
        score >= EARLY_SCORE
        and EARLY_5M_MIN
        <= move5
        <= EARLY_5M_MAX
        and move15 > MIN_15M
        and move30 > MIN_30M
        and move30 <= BUY_30M_MAX
    ):

        signal = "EARLY ENTRY"

    # WATCH
    elif (
        score >= WATCH_SCORE
        and move5 >= 0
        and move5 <= BUY_5M_MAX
        and move15 > 0
        and (
            structure["breakout"]
            or structure["pullback"]
            or distance_high
            <= NEAR_HIGH_MAX
        )
    ):

        signal = "WATCH"

    # ========================================================
    # SL
    # ========================================================

    recent_low = (
        structure["recent_low"]
    )

    if recent_low > 0:

        sl = recent_low * 0.997

    else:

        sl = current * 0.995

    # SL خیلی دور نباشد
    if (
        current - sl
        > current * 0.012
    ):

        sl = current * 0.995

    # حداقل فاصله
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
        "tp2": tp2,
    }


# ============================================================
# DEEP SCAN WITH HEARTBEAT
# ============================================================

def scan_candidates(candidates):

    total = len(candidates)

    telegram(
        "🔎 ATI "
        + VERSION
        + "\n"
        "🎯 DEEP PRECISION SCAN\n"
        "📊 Candidates: "
        + str(total)
        + "\n"
        "🚫 ANTI-CHASE: ON"
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

            # heartbeat every 5 candidates
            if (
                completed % 5 == 0
                or completed == total
            ):

                telegram(
                    "🔎 ATI "
                    + VERSION
                    + "\n"
                    "🎯 DEEP SCAN\n"
                    "⏳ Progress: "
                    + str(completed)
                    + "/"
                    + str(total)
                    + "\n"
                    "📡 API: OK"
                )

    return results


# ============================================================
# FORMAT
# ============================================================

def format_signal(item, rank):

    return (
        f"#{rank}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: {fmt_price(item['price'])}\n"
        f"📈 5M: {item['move5']:+.2f}%\n"
        f"📊 15M: {item['move15']:+.2f}%\n"
        f"📊 30M: {item['move30']:+.2f}%\n"
        f"🛑 SL: {fmt_price(item['sl'])}\n"
        f"🎯 TP1: {fmt_price(item['tp1'])}\n"
        f"🎯 TP2: {fmt_price(item['tp2'])}\n"
        f"📌 {item['reason']}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    start = time.time()

    telegram(
        "⚡ ATI CRYPTO BOT "
        + VERSION
        + "\n"
        "🎯 PRECISION FILTER\n"
        "🚀 CLEAN EARLY ENTRY\n"
        "🔎 BREAKOUT + PULLBACK\n"
        "🚫 ANTI-CHASE\n"
        "📡 TABDEAL API: CONNECTING...\n"
        "⏱ TIMEFRAME: 5m\n"
        "📊 PAPER TRACKING: ON\n"
        "🔧 REAL ORDERS: DISABLED\n"
        "🕐 "
        + now_utc()
    )

    markets = get_markets()

    if not markets:

        telegram(
            "❌ ATI "
            + VERSION
            + "\n"
            "TABDEAL MARKET DATA ERROR"
        )

        return

    telegram(
        "⚡ ATI "
        + VERSION
        + "\n"
        "📡 TABDEAL API: OK\n"
        "📊 USDT MARKETS: "
        + str(len(markets))
        + "\n"
        "🎯 PRECISION FILTER: ON\n"
        "🚫 BUY 5M MAX: "
        + str(BUY_5M_MAX)
        + "%\n"
        "🚫 BUY 30M MAX: "
        + str(BUY_30M_MAX)
        + "%"
    )

    candidates = select_top(
        markets
    )

    if not candidates:

        telegram(
            "⚠️ ATI "
            + VERSION
            + "\n"
            "❌ NO PRECISION CANDIDATES"
        )

        return

    telegram(
        "🎯 ATI "
        + VERSION
        + "\n"
        "📊 TOP "
        + str(len(candidates))
        + " PRECISION CANDIDATES\n"
        "🔎 DEEP SCAN STARTING..."
    )

    results = scan_candidates(
        candidates
    )

    valid = [
        x for x in results
        if x["signal"] != "REJECT"
    ]

    valid.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    buys = [
        x for x in valid
        if x["signal"]
        == "CONFIRMED BUY"
    ]

    early = [
        x for x in valid
        if x["signal"]
        == "EARLY ENTRY"
    ]

    watch = [
        x for x in valid
        if x["signal"]
        == "WATCH"
    ]

    # ========================================================
    # FINAL
    # ========================================================

    message = (
        "⚡ ATI CRYPTO BOT "
        + VERSION
        + "\n"
        "🎯 PRECISION FILTER\n"
        "🚀 CLEAN EARLY ENTRY\n"
        "🔎 BREAKOUT + PULLBACK\n"
        "🚫 ANTI-CHASE\n\n"
        "📡 TABDEAL API: OK\n"
        "📊 USDT MARKETS: "
        + str(len(markets))
        + "\n"
        "🎯 DEEP SCAN: TOP "
        + str(len(candidates))
        + "\n"
        "🕐 "
        + now_utc()
        + "\n\n"
    )

    # BUY
    message += (
        "━━━━━━━━━━━━━━━━━━\n"
        "🟢 CONFIRMED BUY\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if buys:

        for i, item in enumerate(
            buys[:5],
            1
        ):

            message += (
                "\n"
                + format_signal(
                    item,
                    i
                )
                + "\n"
            )

    else:

        message += "NONE\n"

    # EARLY
    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "⚡ EARLY ENTRY\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if early:

        for i, item in enumerate(
            early[:5],
            1
        ):

            message += (
                "\n"
                + format_signal(
                    item,
                    i
                )
                + "\n"
            )

    else:

        message += "NONE\n"

    # WATCH
    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "🟡 WATCH\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if watch:

        for i, item in enumerate(
            watch[:5],
            1
        ):

            message += (
                "\n"
                + format_signal(
                    item,
                    i
                )
                + "\n"
            )

    else:

        message += "NONE\n"

    elapsed = (
        time.time() - start
    )

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "📊 PAPER STATS\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "Trades: 0 | TP: 0 | SL: 0 | OPEN: 0\n"
        "⏱ Scan time: "
        + f"{elapsed:.1f}"
        + " sec\n"
        "🔧 REAL ORDERS: DISABLED"
    )

    telegram(message)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        telegram(
            "🚨 ATI "
            + VERSION
            + "\n"
            "❌ BOT ERROR\n"
            + str(e)
        )

        raise
