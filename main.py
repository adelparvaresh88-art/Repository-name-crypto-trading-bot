import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.8.0
# PRECISION EARLY ENTRY
# BREAKOUT + PULLBACK + ANTI-CHASE
# ============================================================

VERSION = "V39.8.0"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

MAX_MARKETS = 1000
TOP_N = 15

REQUEST_TIMEOUT = 15

RANK_WORKERS = 20
SCAN_WORKERS = 5

PROGRESS_STEP = 50

LIVE_TRADING = False
PAPER_TRACKING = True


# ============================================================
# PRECISION SETTINGS
# ============================================================

# ورود زودهنگام
EARLY_5M_MIN = 0.20
EARLY_5M_MAX = 3.00

# اگر 5 دقیقه‌ای بیش از این رشد کرده باشد، تعقیب قیمت محسوب می‌شود
CHASE_5M_LIMIT = 5.00

# 15M
MIN_15M = 0.30
MAX_15M = 18.00

# 30M
MIN_30M = 0.50
MAX_30M = 25.00

# فاصله از سقف اخیر
NEAR_HIGH_DISTANCE = 1.80

# شکست معتبر
BREAKOUT_MIN = 0.15

# پولبک
PULLBACK_MIN = -1.80
PULLBACK_MAX = 1.00

# امتیازها
BUY_SCORE = 10
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
        r = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        return r.status_code == 200

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


def percent_change(old_price, new_price):
    if old_price <= 0:
        return 0.0

    return ((new_price - old_price) / old_price) * 100.0


# ============================================================
# TABDEAL API
# ============================================================

session = requests.Session()


def api_get(path, params=None):

    url = BASE_URL + path

    try:
        r = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        r.raise_for_status()

        return r.json()

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

    symbols = []

    if isinstance(data, dict):

        if isinstance(data.get("symbols"), list):
            symbols = data["symbols"]

        elif isinstance(data.get("data"), list):
            symbols = data["data"]

        elif isinstance(data.get("result"), list):
            symbols = data["result"]

    elif isinstance(data, list):
        symbols = data

    result = []

    for item in symbols:

        if isinstance(item, str):

            symbol = item.upper()

            if symbol.endswith("USDT"):
                result.append(symbol)

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

        if status not in ("TRADING", "1", "ACTIVE"):
            continue

        result.append(symbol)

    # حذف تکراری
    result = list(dict.fromkeys(result))

    return result[:MAX_MARKETS]


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

def quick_rank_symbol(symbol):

    prices = get_trades(symbol)

    if len(prices) < 40:
        return None

    current = prices[-1]

    # approximate trade windows
    p5 = prices[-6]
    p15 = prices[-16]
    p30 = prices[-31]

    move5 = percent_change(p5, current)
    move15 = percent_change(p15, current)
    move30 = percent_change(p30, current)

    # --------------------------------------------------------
    # HARD ANTI-CHASE
    # --------------------------------------------------------

    if move5 > CHASE_5M_LIMIT:
        return {
            "symbol": symbol,
            "price": current,
            "move5": move5,
            "move15": move15,
            "move30": move30,
            "score": -20,
            "rejected": True,
        }

    score = 0

    # 5M direction
    if move5 > 0:
        score += 2

    if EARLY_5M_MIN <= move5 <= EARLY_5M_MAX:
        score += 4

    elif move5 < 0:
        score -= 2

    # 15M trend
    if move15 > MIN_15M:
        score += 3

    if move15 > move5:
        score += 2

    # 30M trend
    if move30 > MIN_30M:
        score += 2

    # avoid parabolic 30M
    if move30 > MAX_30M:
        score -= 6

    # healthy relationship
    if move15 > 0 and move30 > 0:
        score += 2

    # 5M too strong
    if move5 > 4:
        score -= 5

    return {
        "symbol": symbol,
        "price": current,
        "move5": move5,
        "move15": move15,
        "move30": move30,
        "score": score,
        "rejected": False,
    }


# ============================================================
# TOP MARKET SELECTION
# ============================================================

def select_top_markets(markets):

    total = len(markets)

    telegram(
        "🔄 ATI " + VERSION + "\n"
        "📊 RANKING TOP CANDIDATES\n"
        "📈 Markets: " + str(total) + "\n"
        "⏳ Starting..."
    )

    results = []

    completed = 0
    last_progress = 0

    with ThreadPoolExecutor(
        max_workers=RANK_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                quick_rank_symbol,
                symbol
            ): symbol
            for symbol in markets
        }

        for future in as_completed(futures):

            completed += 1

            try:
                result = future.result()

                if result is not None:
                    results.append(result)

            except Exception:
                pass

            if (
                completed - last_progress
                >= PROGRESS_STEP
                or completed == total
            ):

                last_progress = completed

                progress = (
                    completed / total * 100
                    if total
                    else 100
                )

                telegram(
                    "🔄 ATI " + VERSION + "\n"
                    "📊 RANKING TOP CANDIDATES\n"
                    "⏳ Progress: "
                    + str(completed)
                    + "/"
                    + str(total)
                    + "\n"
                    "📈 "
                    + f"{progress:.0f}%"
                    + " completed\n"
                    "🎯 Candidates: "
                    + str(len(results))
                )

    # حذف rejected های شدید
    valid = [
        x for x in results
        if not x.get("rejected", False)
    ]

    valid.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return valid[:TOP_N]


# ============================================================
# STRUCTURE ANALYSIS
# ============================================================

def analyze_structure(prices):

    if len(prices) < 50:
        return {
            "recent_high": 0,
            "recent_low": 0,
            "distance_high": 999,
            "breakout": False,
            "pullback": False,
            "holding": False,
        }

    current = prices[-1]

    # سقف قبل از آخرین بخش
    previous_zone = prices[-31:-6]

    if not previous_zone:
        return {
            "recent_high": 0,
            "recent_low": 0,
            "distance_high": 999,
            "breakout": False,
            "pullback": False,
            "holding": False,
        }

    recent_high = max(previous_zone)
    recent_low = min(previous_zone)

    distance_high = percent_change(
        recent_high,
        current
    )

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    breakout = current > recent_high

    # --------------------------------------------------------
    # PULLBACK
    # --------------------------------------------------------

    pullback_prices = prices[-10:]

    if len(pullback_prices) >= 5:

        local_high = max(
            pullback_prices[:-3]
        )

        latest = pullback_prices[-1]

        pullback_move = percent_change(
            local_high,
            latest
        )

        pullback = (
            PULLBACK_MIN
            <= pullback_move
            <= PULLBACK_MAX
        )

    else:
        pullback = False

    # --------------------------------------------------------
    # HOLDING
    # --------------------------------------------------------

    recent_low_test = min(
        prices[-8:]
    )

    holding = (
        current >= recent_low_test
    )

    return {
        "recent_high": recent_high,
        "recent_low": recent_low,
        "distance_high": distance_high,
        "breakout": breakout,
        "pullback": pullback,
        "holding": holding,
    }


# ============================================================
# DEEP PRECISION SCAN
# ============================================================

def deep_scan(candidate):

    symbol = candidate["symbol"]

    prices = get_trades(symbol)

    if len(prices) < 60:
        return None

    current = prices[-1]

    p5 = prices[-6]
    p15 = prices[-16]
    p30 = prices[-31]

    move5 = percent_change(
        p5,
        current
    )

    move15 = percent_change(
        p15,
        current
    )

    move30 = percent_change(
        p30,
        current
    )

    structure = analyze_structure(
        prices
    )

    score = 0
    reasons = []

    # ========================================================
    # HARD REJECTIONS
    # ========================================================

    if move5 > CHASE_5M_LIMIT:

        return {
            "symbol": symbol,
            "price": current,
            "move5": move5,
            "move15": move15,
            "move30": move30,
            "score": -99,
            "signal": "REJECT",
            "reason": "5M CHASE",
            "sl": 0,
            "tp1": 0,
            "tp2": 0,
        }

    if move30 > MAX_30M:

        return {
            "symbol": symbol,
            "price": current,
            "move5": move5,
            "move15": move15,
            "move30": move30,
            "score": -99,
            "signal": "REJECT",
            "reason": "30M PARABOLIC",
            "sl": 0,
            "tp1": 0,
            "tp2": 0,
        }

    # ========================================================
    # EARLY ENTRY
    # ========================================================

    if EARLY_5M_MIN <= move5 <= EARLY_5M_MAX:
        score += 3
        reasons.append("5M EARLY")

    # ========================================================
    # 15M TREND
    # ========================================================

    if move15 > MIN_15M:
        score += 2
        reasons.append("15M UP")

    if move15 > move5:
        score += 2
        reasons.append("15M > 5M")

    # ========================================================
    # 30M TREND
    # ========================================================

    if move30 > MIN_30M:
        score += 2
        reasons.append("30M UP")

    # ========================================================
    # HEALTHY MOMENTUM
    # ========================================================

    if (
        move5 > 0
        and move15 > 0
        and move30 > 0
    ):
        score += 2
        reasons.append("MULTI TF UP")

    # ========================================================
    # NEAR RECENT HIGH
    # ========================================================

    distance_high = structure["distance_high"]

    if (
        -NEAR_HIGH_DISTANCE
        <= distance_high
        <= 1.50
    ):
        score += 2
        reasons.append("NEAR HIGH")

    # ========================================================
    # BREAKOUT
    # ========================================================

    if structure["breakout"]:

        score += 3
        reasons.append("BREAKOUT")

    # ========================================================
    # PULLBACK
    # ========================================================

    if structure["pullback"]:

        score += 3
        reasons.append("PULLBACK")

    # ========================================================
    # HOLDING
    # ========================================================

    if structure["holding"]:

        score += 1
        reasons.append("HOLD")

    # ========================================================
    # BAD CHASE ZONES
    # ========================================================

    if move5 > 3.0:

        score -= 3

    if move5 < 0:

        score -= 3

    if move15 < 0:

        score -= 3

    # ========================================================
    # SIGNAL CLASSIFICATION
    # ========================================================

    signal = "NONE"

    # Confirmed BUY:
    # needs trend + structure confirmation
    if (
        score >= BUY_SCORE
        and move5 <= EARLY_5M_MAX
        and move15 > 0
        and move30 > 0
        and (
            structure["breakout"]
            or structure["pullback"]
        )
    ):
        signal = "CONFIRMED BUY"

    # Early entry:
    # good momentum but structure still developing
    elif (
        score >= EARLY_SCORE
        and EARLY_5M_MIN <= move5 <= EARLY_5M_MAX
        and move15 > 0
        and move30 > 0
    ):
        signal = "EARLY ENTRY"

    # Watch:
    # only if price is near useful structure
    elif (
        score >= WATCH_SCORE
        and move5 <= EARLY_5M_MAX
        and move15 > 0
        and (
            structure["breakout"]
            or structure["pullback"]
            or distance_high <= NEAR_HIGH_DISTANCE
        )
    ):
        signal = "WATCH"

    else:
        signal = "NONE"

    # ========================================================
    # SL / TP
    # ========================================================

    if structure["recent_low"] > 0:

        structural_sl = (
            structure["recent_low"] * 0.997
        )

        # جلوگیری از SL خیلی دور
        max_sl_distance = current * 0.012

        if (
            current - structural_sl
            > max_sl_distance
        ):
            sl = current * 0.995

        else:
            sl = structural_sl

    else:

        sl = current * 0.995

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
        "reason": " + ".join(reasons),
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "distance_high": distance_high,
        "breakout": structure["breakout"],
        "pullback": structure["pullback"],
    }


# ============================================================
# DEEP SCAN ALL TOP CANDIDATES
# ============================================================

def scan_candidates(candidates):

    results = []

    total = len(candidates)

    telegram(
        "🔎 ATI " + VERSION + "\n"
        "🎯 DEEP PRECISION SCAN\n"
        "📊 Candidates: "
        + str(total)
        + "\n"
        "🚫 ANTI-CHASE: ON"
    )

    with ThreadPoolExecutor(
        max_workers=SCAN_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                deep_scan,
                candidate
            )
            for candidate in candidates
        ]

        for future in as_completed(futures):

            try:

                result = future.result()

                if result is not None:
                    results.append(result)

            except Exception:
                pass

    return results


# ============================================================
# FORMAT PRICE
# ============================================================

def fmt_price(value):

    if value >= 100:
        return f"{value:.4f}"

    if value >= 1:
        return f"{value:.6f}"

    if value >= 0.01:
        return f"{value:.8f}"

    return f"{value:.10f}"


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(item, rank):

    symbol = item["symbol"]

    price = fmt_price(
        item["price"]
    )

    sl = fmt_price(
        item["sl"]
    )

    tp1 = fmt_price(
        item["tp1"]
    )

    tp2 = fmt_price(
        item["tp2"]
    )

    text = (
        f"#{rank}\n"
        f"🪙 {symbol}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: {price}\n"
        f"📈 5M: {item['move5']:+.2f}%\n"
        f"📊 15M: {item['move15']:+.2f}%\n"
        f"📊 30M: {item['move30']:+.2f}%\n"
        f"🛑 SL: {sl}\n"
        f"🎯 TP1: {tp1}\n"
        f"🎯 TP2: {tp2}\n"
        f"📌 {item['reason']}"
    )

    return text


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    telegram(
        "⚡ ATI CRYPTO BOT "
        + VERSION
        + "\n"
        "🎯 PRECISION EARLY ENTRY\n"
        "🚀 BREAKOUT + PULLBACK\n"
        "🚫 ANTI-CHASE\n"
        "📡 TABDEAL API: CONNECTING...\n"
        "⏱ TIMEFRAME: 5m\n"
        "📊 PAPER TRACKING: ON\n"
        "🔧 REAL ORDERS: DISABLED\n"
        "🕐 "
        + now_utc()
    )

    # ========================================================
    # MARKETS
    # ========================================================

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
        "⚡ ATI CRYPTO BOT "
        + VERSION
        + "\n"
        "📡 TABDEAL API: OK\n"
        "📊 USDT MARKETS: "
        + str(len(markets))
        + "\n"
        "🎯 MODE: PRECISION ENTRY\n"
        "🚫 5M CHASE > "
        + str(CHASE_5M_LIMIT)
        + "% REJECT"
    )

    # ========================================================
    # RANKING
    # ========================================================

    candidates = select_top_markets(
        markets
    )

    if not candidates:

        telegram(
            "⚠️ ATI "
            + VERSION
            + "\n"
            "❌ NO VALID CANDIDATES"
        )

        return

    telegram(
        "🎯 ATI "
        + VERSION
        + "\n"
        "📊 TOP "
        + str(len(candidates))
        + " CANDIDATES SELECTED\n"
        "🔎 DEEP PRECISION SCAN STARTING..."
    )

    # ========================================================
    # DEEP SCAN
    # ========================================================

    results = scan_candidates(
        candidates
    )

    # حذف rejected
    valid_results = [
        x for x in results
        if x["signal"] != "REJECT"
    ]

    valid_results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    confirmed = [
        x for x in valid_results
        if x["signal"] == "CONFIRMED BUY"
    ]

    early = [
        x for x in valid_results
        if x["signal"] == "EARLY ENTRY"
    ]

    watch = [
        x for x in valid_results
        if x["signal"] == "WATCH"
    ]

    # ========================================================
    # FINAL MESSAGE
    # ========================================================

    message = (
        "⚡ ATI CRYPTO BOT "
        + VERSION
        + "\n"
        "🎯 PRECISION EARLY ENTRY\n"
        "🚀 BREAKOUT + PULLBACK\n"
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

    # ========================================================
    # CONFIRMED BUY
    # ========================================================

    message += (
        "━━━━━━━━━━━━━━━━━━\n"
        "🟢 CONFIRMED BUY\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if confirmed:

        for i, item in enumerate(
            confirmed[:5],
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

    # ========================================================
    # EARLY ENTRY
    # ========================================================

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

    # ========================================================
    # WATCH
    # ========================================================

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

    # ========================================================
    # STATS
    # ========================================================

    elapsed = time.time() - start_time

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
# RUN
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
