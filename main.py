import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.2
# PRECISION BREAKOUT + RETEST SCANNER
# ============================================================

VERSION = "V38.2"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
CANDLE_LIMIT = 120

# سخت‌گیری بیشتر
BUY_MIN_SCORE = 13
WATCH_MIN_SCORE = 10

# جلوگیری از ورود بعد از پامپ
MAX_5M_MOVE = 5.0
MAX_15M_MOVE = 10.0
MAX_1H_MOVE = 18.0

# حداقل قدرت حرکت
MIN_5M_MOVE = 0.15
MIN_15M_MOVE = 0.30
MIN_1H_MOVE = 0.50

TOP_RESULTS = 5
REQUEST_TIMEOUT = 15


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

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM SECRETS NOT SET")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:

        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            print("✅ TELEGRAM SENT")
            return True

        print(
            "❌ TELEGRAM ERROR:",
            response.text[:500],
        )

    except Exception as e:
        print(
            "❌ TELEGRAM CONNECTION ERROR:",
            str(e),
        )

    return False


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/38.2",
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
# MARKETS
# ============================================================

def extract_market_list(data):

    if isinstance(data, list):

        raw = data

    elif isinstance(data, dict):

        raw = None

        for key in (
            "symbols",
            "markets",
            "data",
            "result",
            "items",
        ):

            value = data.get(key)

            if isinstance(value, list):
                raw = value
                break

        if raw is None:
            return []

    else:
        return []

    result = []

    for item in raw:

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
            result.append(symbol)

    return sorted(set(result))


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
        },
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

    if price <= 0 or not timestamp:
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
            trade["price"],
        )

        candle["low"] = min(
            candle["low"],
            trade["price"],
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

def pct(old, new):

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
# PRECISION ANALYSIS
# ============================================================

def analyze(symbol, candles):

    # فقط کندل‌های بسته
    if len(candles) < 35:
        return None

    closed = candles[:-1]

    if len(closed) < 30:
        return None

    last = closed[-1]
    close = last["close"]

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    move_5m = pct(
        closed[-2]["close"],
        closed[-1]["close"],
    )

    move_15m = pct(
        closed[-4]["close"],
        closed[-1]["close"],
    )

    move_1h = pct(
        closed[-13]["close"],
        closed[-1]["close"],
    )

    # --------------------------------------------------------
    # CHASE FILTER
    # --------------------------------------------------------

    if move_5m > MAX_5M_MOVE:
        return None

    if move_15m > MAX_15M_MOVE:
        return None

    if move_1h > MAX_1H_MOVE:
        return None

    # --------------------------------------------------------
    # POSITIVE TREND
    # --------------------------------------------------------

    if move_5m < MIN_5M_MOVE:
        return None

    if move_15m < MIN_15M_MOVE:
        return None

    if move_1h < MIN_1H_MOVE:
        return None

    score = 0
    reasons = []

    # 5M
    score += 2
    reasons.append("5M UP")

    if move_5m >= 0.50:
        score += 1

    # 15M
    score += 2
    reasons.append("15M UP")

    if move_15m >= 1.0:
        score += 1

    # 1H
    score += 2
    reasons.append("1H UP")

    if move_1h >= 2.0:
        score += 1

    # --------------------------------------------------------
    # STRUCTURE
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

    if higher_high:

        score += 2
        reasons.append("HIGHER HIGH")

    else:
        return None

    if higher_low:

        score += 2
        reasons.append("HIGHER LOW")

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    breakout_level = max(
        x["high"]
        for x in closed[-13:-2]
    )

    breakout = close > breakout_level

    if breakout:

        score += 2
        reasons.append("BREAKOUT")

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    retest = False

    # بررسی سه کندل اخیر
    for candle in closed[-4:-1]:

        distance = abs(
            candle["low"]
            - breakout_level
        ) / breakout_level * 100

        if distance <= 0.8:

            if candle["close"] >= breakout_level:

                retest = True
                break

    if retest:

        score += 3
        reasons.append("RETEST")

    else:

        # بدون retest سیگنال BUY صادر نمی‌شود
        return None

    # --------------------------------------------------------
    # VOLUME CONFIRMATION
    # --------------------------------------------------------

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
            and last["volume"]
            >= avg_volume * 1.20
        ):

            volume_ok = True
            score += 2
            reasons.append("VOLUME")

    # --------------------------------------------------------
    # BREAKOUT DISTANCE
    # --------------------------------------------------------

    distance_from_breakout = pct(
        breakout_level,
        close,
    )

    # اگر خیلی از شکست فاصله گرفته باشد
    if distance_from_breakout > 3.0:
        return None

    # --------------------------------------------------------
    # SL
    # --------------------------------------------------------

    swing_low = min(
        x["low"] for x in closed[-8:]
    )

    sl = swing_low

    if sl >= close:
        sl = close * 0.995

    risk = close - sl

    if risk <= 0:
        return None

    risk_pct = (
        risk / close
    ) * 100

    # SL خیلی دور نباشد
    if risk_pct > 8.0:
        return None

    # --------------------------------------------------------
    # TP
    # --------------------------------------------------------

    tp1 = close + risk * 1.5
    tp2 = close + risk * 2.5

    # --------------------------------------------------------
    # FINAL STATUS
    # --------------------------------------------------------

    if score >= BUY_MIN_SCORE:

        status = "BUY"

    elif score >= WATCH_MIN_SCORE:

        status = "WATCH"

    else:

        status = "NONE"

    if status == "NONE":
        return None

    return {
        "symbol": symbol,
        "score": score,
        "price": close,
        "move_5m": move_5m,
        "move_15m": move_15m,
        "move_1h": move_1h,
        "breakout_level": breakout_level,
        "distance": distance_from_breakout,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk_pct": risk_pct,
        "volume_ok": volume_ok,
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
        f"🟢 CONFIRMED BUY\n\n"
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
        f"{item['distance']:.2f}%\n\n"
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
    print(f"ATI CRYPTO BOT {VERSION}")
    print("PRECISION BREAKOUT + RETEST SCANNER")
    print("=" * 60)

    print("📡 TABDEAL API: CHECKING...")

    markets = get_markets()

    if not markets:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET DATA ERROR\n\n"
            f"Could not load USDT markets."
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
        start=1,
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
                candles,
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

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["score"],
            x["move_15m"],
            x["move_5m"],
        ),
        reverse=True,
    )

    buys = [
        x for x in results
        if x["status"] == "BUY"
    ]

    watches = [
        x for x in results
        if x["status"] == "WATCH"
    ]

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 PRECISION BREAKOUT + RETEST\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n\n"
        f"🟢 BUY MIN SCORE: "
        f"{BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: "
        f"{WATCH_MIN_SCORE}\n"
        f"🚫 MAX 5M: "
        f"{MAX_5M_MOVE}%\n"
        f"🚫 MAX 15M: "
        f"{MAX_15M_MOVE}%\n"
        f"🚫 MAX 1H: "
        f"{MAX_1H_MOVE}%\n\n"
        f"🕐 SCAN:\n{now}\n"
    )

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "🟢 CONFIRMED BUYS\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if buys:

        for rank, item in enumerate(
            buys[:TOP_RESULTS],
            start=1,
        ):

            message += (
                "\n"
                + format_signal(
                    item,
                    rank,
                )
                + "\n"
            )

    else:

        message += (
            "❌ No precision BUY\n"
        )

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    if watches:

        message += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "🟡 WATCH LIST\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        for rank, item in enumerate(
            watches[:TOP_RESULTS],
            start=1,
        ):

            message += (
                f"\n#{rank} "
                f"{item['symbol']} "
                f"⭐ {item['score']} "
                f"📈 "
                f"{item['move_5m']:+.2f}%\n"
            )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

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
