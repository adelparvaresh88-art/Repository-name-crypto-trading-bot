import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.3
# PRECISION BREAKOUT + RETEST
# ============================================================

VERSION = "V38.3"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
CANDLE_LIMIT = 120

# ------------------------------------------------------------
# SCORE
# ------------------------------------------------------------

BUY_MIN_SCORE = 14
WATCH_MIN_SCORE = 11

# ------------------------------------------------------------
# MOMENTUM FILTERS
# ------------------------------------------------------------

MIN_5M_MOVE = 0.10
MIN_15M_MOVE = 0.30
MIN_1H_MOVE = 0.50

MAX_5M_MOVE = 4.0
MAX_15M_MOVE = 9.0
MAX_1H_MOVE = 18.0

# ------------------------------------------------------------
# BREAKOUT / RETEST
# ------------------------------------------------------------

MAX_BREAKOUT_DISTANCE = 1.0
MAX_RETEST_DISTANCE = 0.60

# حداقل قدرت شکست
MIN_BREAKOUT_DISTANCE = 0.05

# ------------------------------------------------------------
# VOLUME
# ------------------------------------------------------------

VOLUME_MULTIPLIER = 1.15

# ------------------------------------------------------------
# RESULTS
# ------------------------------------------------------------

TOP_RESULTS = 5

REQUEST_TIMEOUT = 15


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
        print("⚠️ TELEGRAM_BOT_TOKEN NOT SET")
        return False

    if not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM_CHAT_ID NOT SET")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:

            print("✅ TELEGRAM SENT")
            return True

        print(
            "❌ TELEGRAM ERROR:",
            response.text[:500]
        )

    except Exception as e:

        print(
            "❌ TELEGRAM CONNECTION ERROR:",
            str(e)
        )

    return False


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/38.3",
        "Accept": "application/json",
    }
)


def api_get(path, params=None):

    try:

        response = session.get(
            BASE_URL + path,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        print(
            f"❌ API ERROR {path}: {str(e)}"
        )

        return None


# ============================================================
# MARKET LIST
# ============================================================

def extract_market_list(data):

    if isinstance(data, list):

        raw_items = data

    elif isinstance(data, dict):

        raw_items = None

        for key in (
            "symbols",
            "markets",
            "data",
            "result",
            "items",
        ):

            value = data.get(key)

            if isinstance(value, list):

                raw_items = value
                break

        if raw_items is None:
            return []

    else:

        return []

    markets = []

    for item in raw_items:

        if isinstance(item, str):

            symbol = item

        elif isinstance(item, dict):

            symbol = (
                item.get("symbol")
                or item.get("market")
                or item.get("name")
                or item.get("pair")
                or ""
            )

        else:

            continue

        symbol = (
            str(symbol)
            .upper()
            .replace("-", "")
            .replace("_", "")
        )

        if symbol.endswith("USDT"):

            markets.append(symbol)

    return sorted(set(markets))


def get_markets():

    endpoints = [
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/symbols",
        "/r/api/v1/markets",
    ]

    for endpoint in endpoints:

        data = api_get(endpoint)

        if data is None:
            continue

        markets = extract_market_list(data)

        if markets:
            return markets

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
        }
    )

    if isinstance(data, list):
        return data

    return []


def normalize_trade(item):

    if not isinstance(item, dict):
        return None

    price = (
        item.get("price")
        or item.get("p")
        or item.get("rate")
    )

    quantity = (
        item.get("qty")
        or item.get("quantity")
        or item.get("amount")
        or item.get("q")
        or 0
    )

    timestamp = (
        item.get("timestamp")
        or item.get("time")
        or item.get("T")
        or item.get("created_at")
    )

    try:

        price = float(price)
        quantity = float(quantity)
        timestamp = float(timestamp)

    except Exception:

        return None

    if price <= 0:
        return None

    if not timestamp:
        return None

    if timestamp < 10000000000:

        timestamp *= 1000

    return {
        "price": price,
        "qty": abs(quantity),
        "time": int(timestamp),
    }


# ============================================================
# TRADES -> 5M CANDLES
# ============================================================

def trades_to_candles(trades):

    normalized = []

    for item in trades:

        trade = normalize_trade(item)

        if trade:
            normalized.append(trade)

    if not normalized:
        return []

    normalized.sort(
        key=lambda x: x["time"]
    )

    interval = 5 * 60 * 1000

    candles = {}

    for trade in normalized:

        bucket = (
            trade["time"] // interval
        ) * interval

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
            }

        candle = candles[bucket]

        candle["high"] = max(
            candle["high"],
            trade["price"]
        )

        candle["low"] = min(
            candle["low"],
            trade["price"]
        )

        candle["close"] = trade["price"]

        candle["volume"] += trade["qty"]

    result = list(candles.values())

    result.sort(
        key=lambda x: x["time"]
    )

    return result[-CANDLE_LIMIT:]


# ============================================================
# HELPERS
# ============================================================

def pct_change(old, new):

    if old == 0:
        return 0.0

    return (
        (new - old) / old
    ) * 100.0


def average(values):

    if not values:
        return 0.0

    return sum(values) / len(values)


# ============================================================
# PRECISION ANALYZER
# ============================================================

def analyze(symbol, candles):

    # --------------------------------------------------------
    # DATA CHECK
    # --------------------------------------------------------

    if len(candles) < 35:
        return None

    # فقط کندل‌های کاملاً بسته
    closed = candles[:-1]

    if len(closed) < 30:
        return None

    last = closed[-1]

    close = last["close"]

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    move_5m = pct_change(
        closed[-2]["close"],
        closed[-1]["close"]
    )

    move_15m = pct_change(
        closed[-4]["close"],
        closed[-1]["close"]
    )

    move_1h = pct_change(
        closed[-13]["close"],
        closed[-1]["close"]
    )

    # --------------------------------------------------------
    # BASIC MOMENTUM FILTER
    # --------------------------------------------------------

    if move_5m < MIN_5M_MOVE:
        return None

    if move_15m < MIN_15M_MOVE:
        return None

    if move_1h < MIN_1H_MOVE:
        return None

    # --------------------------------------------------------
    # CHASE FILTER
    # --------------------------------------------------------

    if move_5m > MAX_5M_MOVE:
        return None

    if move_15m > MAX_15M_MOVE:
        return None

    if move_1h > MAX_1H_MOVE:
        return None

    score = 0

    reasons = []

    # --------------------------------------------------------
    # MOMENTUM SCORE
    # --------------------------------------------------------

    score += 2
    reasons.append("5M UP")

    if move_5m >= 0.50:

        score += 1

    score += 2
    reasons.append("15M UP")

    if move_15m >= 1.0:

        score += 1

    score += 2
    reasons.append("1H UP")

    if move_1h >= 2.0:

        score += 1

    # --------------------------------------------------------
    # MARKET STRUCTURE
    # --------------------------------------------------------

    recent = closed[-10:]

    previous = closed[-20:-10]

    recent_high = max(
        x["high"] for x in recent
    )

    previous_high = max(
        x["high"] for x in previous
    )

    recent_low = min(
        x["low"] for x in recent
    )

    previous_low = min(
        x["low"] for x in previous
    )

    higher_high = (
        recent_high > previous_high
    )

    higher_low = (
        recent_low > previous_low
    )

    if not higher_high:
        return None

    score += 2
    reasons.append("HIGHER HIGH")

    if higher_low:

        score += 2
        reasons.append("HIGHER LOW")

    else:

        return None

    # ========================================================
    # BREAKOUT
    # ========================================================

    breakout_level = max(
        x["high"]
        for x in closed[-13:-2]
    )

    if breakout_level <= 0:
        return None

    breakout_distance = pct_change(
        breakout_level,
        close
    )

    # قیمت باید بالای شکست باشد
    if breakout_distance <= 0:
        return None

    # شکست خیلی کوچک قابل قبول نیست
    if breakout_distance < MIN_BREAKOUT_DISTANCE:
        return None

    # بیش از 1٪ از شکست دور نشود
    if breakout_distance > MAX_BREAKOUT_DISTANCE:
        return None

    score += 2
    reasons.append("BREAKOUT")

    # ========================================================
    # REAL RETEST
    # ========================================================

    retest_found = False

    retest_index = None

    # فقط کندل‌های قبل از آخرین کندل را بررسی می‌کنیم
    # تا ورود روی شکست لحظه‌ای نباشد.

    for i in range(
        len(closed) - 5,
        len(closed) - 1
    ):

        candle = closed[i]

        low_distance = abs(
            pct_change(
                breakout_level,
                candle["low"]
            )
        )

        close_distance = abs(
            pct_change(
                breakout_level,
                candle["close"]
            )
        )

        # Low باید نزدیک Breakout باشد
        if low_distance <= MAX_RETEST_DISTANCE:

            # کندل باید دوباره بالای شکست بسته شود
            if candle["close"] >= breakout_level:

                # فاصله Close نیز نباید زیاد باشد
                if close_distance <= MAX_RETEST_DISTANCE:

                    retest_found = True
                    retest_index = i
                    break

    if not retest_found:
        return None

    score += 4
    reasons.append("REAL RETEST")

    # ========================================================
    # RETEST MUST BE BEFORE CURRENT CANDLE
    # ========================================================

    if retest_index is None:
        return None

    if retest_index >= len(closed) - 1:
        return None

    # ========================================================
    # CURRENT CANDLE CONFIRMATION
    # ========================================================

    current = closed[-1]

    current_close = current["close"]

    # قیمت فعلی باید بالای شکست بماند
    if current_close <= breakout_level:
        return None

    # فاصله فعلی از شکست
    current_distance = pct_change(
        breakout_level,
        current_close
    )

    if current_distance > MAX_BREAKOUT_DISTANCE:
        return None

    # ========================================================
    # VOLUME
    # ========================================================

    volumes = [
        x["volume"]
        for x in closed[-21:-1]
        if x["volume"] > 0
    ]

    volume_ok = False

    if volumes:

        avg_volume = average(volumes)

        if (
            avg_volume > 0
            and current["volume"]
            >= avg_volume * VOLUME_MULTIPLIER
        ):

            volume_ok = True

            score += 2

            reasons.append("VOLUME")

    # حجم ضعیف اجازه BUY نمی‌دهد
    if not volume_ok:
        return None

    # ========================================================
    # CANDLE QUALITY
    # ========================================================

    candle_range = (
        current["high"]
        - current["low"]
    )

    if candle_range <= 0:
        return None

    body = abs(
        current["close"]
        - current["open"]
    )

    body_ratio = (
        body / candle_range
    )

    # کندل ورود نباید خیلی ضعیف باشد
    if body_ratio < 0.35:
        return None

    # اگر کندل نزولی است، ورود نکن
    if current["close"] <= current["open"]:
        return None

    score += 1
    reasons.append("STRONG CANDLE")

    # ========================================================
    # SL
    # ========================================================

    swing_low = min(
        x["low"]
        for x in closed[-8:]
    )

    sl = swing_low

    if sl >= close:

        sl = close * 0.995

    risk = close - sl

    if risk <= 0:
        return None

    risk_pct = (
        risk / close
    ) * 100.0

    # SL بیش از حد دور نباشد
    if risk_pct > 7.0:
        return None

    # ========================================================
    # TP
    # ========================================================

    tp1 = close + risk * 1.5

    tp2 = close + risk * 2.5

    # ========================================================
    # FINAL SCORE
    # ========================================================

    if score >= BUY_MIN_SCORE:

        status = "BUY"

    elif score >= WATCH_MIN_SCORE:

        status = "WATCH"

    else:

        return None

    return {
        "symbol": symbol,
        "score": score,
        "price": close,
        "move_5m": move_5m,
        "move_15m": move_15m,
        "move_1h": move_1h,
        "breakout_level": breakout_level,
        "distance": current_distance,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk_pct": risk_pct,
        "volume_ok": volume_ok,
        "body_ratio": body_ratio,
        "status": status,
        "reasons": reasons,
    }


# ============================================================
# PRICE FORMAT
# ============================================================

def format_price(value):

    if value >= 100:

        return f"{value:.2f}"

    if value >= 1:

        return f"{value:.5f}"

    if value >= 0.01:

        return f"{value:.7f}"

    return f"{value:.10f}"


# ============================================================
# SIGNAL FORMAT
# ============================================================

def format_signal(item, rank):

    reasons = ", ".join(
        item["reasons"]
    )

    return (
        "🟢 CONFIRMED BUY\n\n"
        f"#{rank}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: "
        f"{format_price(item['price'])}\n\n"
        f"📈 5M: "
        f"{item['move_5m']:+.2f}%\n"
        f"📊 15M: "
        f"{item['move_15m']:+.2f}%\n"
        f"🕐 1H: "
        f"{item['move_1h']:+.2f}%\n\n"
        f"📍 BREAKOUT: "
        f"{format_price(item['breakout_level'])}\n"
        f"↔️ DISTANCE: "
        f"{item['distance']:.2f}%\n"
        f"🔄 RETEST: CONFIRMED\n"
        f"📦 VOLUME: CONFIRMED\n\n"
        f"🛑 SL: "
        f"{format_price(item['sl'])}\n"
        f"🎯 TP1: "
        f"{format_price(item['tp1'])}\n"
        f"🎯 TP2: "
        f"{format_price(item['tp2'])}\n\n"
        f"🔎 {reasons}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)

    print(
        f"ATI CRYPTO BOT {VERSION}"
    )

    print(
        "PRECISION BREAKOUT + RETEST"
    )

    print("=" * 60)

    print(
        "📡 TABDEAL API: CHECKING..."
    )

    markets = get_markets()

    if not markets:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "❌ TABDEAL MARKET DATA ERROR\n\n"
            "Could not load USDT markets."
        )

        print(message)

        telegram_send(message)

        return

    print(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    results = []

    total = len(markets)

    for index, symbol in enumerate(
        markets,
        start=1
    ):

        try:

            trades = get_trades(symbol)

            if not trades:
                continue

            candles = trades_to_candles(
                trades
            )

            if not candles:
                continue

            result = analyze(
                symbol,
                candles
            )

            if result:

                results.append(result)

        except Exception as e:

            print(
                f"⚠️ {symbol} ERROR: "
                f"{str(e)}"
            )

        if index % 20 == 0:

            print(
                f"🔎 Scanned "
                f"{index}/{total}"
            )

            time.sleep(0.15)

    # ========================================================
    # SORT
    # ========================================================

    results.sort(
        key=lambda x: (
            x["score"],
            x["move_15m"],
            x["move_5m"]
        ),
        reverse=True
    )

    buys = [
        x for x in results
        if x["status"] == "BUY"
    ]

    watches = [
        x for x in results
        if x["status"] == "WATCH"
    ]

    # ========================================================
    # HEADER
    # ========================================================

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        "🚀 PRECISION BREAKOUT + RETEST\n\n"
        "📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: "
        f"{len(markets)}\n\n"
        f"🟢 BUY MIN SCORE: "
        f"{BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: "
        f"{WATCH_MIN_SCORE}\n"
        f"🚫 MAX 5M: "
        f"{MAX_5M_MOVE}%\n"
        f"🚫 MAX 15M: "
        f"{MAX_15M_MOVE}%\n"
        f"🚫 MAX 1H: "
        f"{MAX_1H_MOVE}%\n"
        f"📍 MAX BREAKOUT DISTANCE: "
        f"{MAX_BREAKOUT_DISTANCE}%\n"
        f"🔄 MAX RETEST DISTANCE: "
        f"{MAX_RETEST_DISTANCE}%\n\n"
        f"🕐 SCAN:\n"
        f"{now}\n"
    )

    # ========================================================
    # BUYS
    # ========================================================

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "🟢 CONFIRMED BUYS\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if buys:

        for rank, item in enumerate(
            buys[:TOP_RESULTS],
            start=1
        ):

            message += (
                "\n"
                + format_signal(
                    item,
                    rank
                )
                + "\n"
            )

    else:

        message += (
            "❌ No precision BUY\n"
        )

    # ========================================================
    # WATCH
    # ========================================================

    if watches:

        message += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "🟡 WATCH LIST\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        for rank, item in enumerate(
            watches[:TOP_RESULTS],
            start=1
        ):

            message += (
                f"\n#{rank} "
                f"{item['symbol']} "
                f"⭐ {item['score']} "
                f"📈 "
                f"{item['move_5m']:+.2f}%\n"
            )

    # ========================================================
    # SUMMARY
    # ========================================================

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "📊 SUMMARY\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🟢 BUY: {len(buys)}\n"
        f"🟡 WATCH: {len(watches)}\n"
        f"📡 MARKETS: {len(markets)}\n\n"
        "⚠️ SIGNAL ONLY — NO REAL ORDER"
    )

    print(message)

    telegram_send(message)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
