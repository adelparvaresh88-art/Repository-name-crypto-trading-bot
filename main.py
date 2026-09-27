import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.1.2
# BREAKOUT + RETEST / UPWARD SCANNER
# TABDEAL
# ============================================================

VERSION = "V38.1.2"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
CANDLE_LIMIT = 120

BUY_MIN_SCORE = 11
WATCH_MIN_SCORE = 8

CHASE_LIMIT_5M = 7.0
TOP_RESULTS = 5

REQUEST_TIMEOUT = 15


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM SECRETS NOT SET")
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
        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            print("✅ TELEGRAM SENT")
            return True

        print("❌ TELEGRAM ERROR:", response.text[:500])
        return False

    except Exception as e:
        print("❌ TELEGRAM CONNECTION ERROR:", str(e))
        return False


# ============================================================
# HTTP
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/38.1.2",
        "Accept": "application/json",
    }
)


def api_get(path, params=None):
    url = BASE_URL + path

    try:
        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:
        print("❌ API ERROR:", path, str(e))
        return None


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_markets():
    """
    Tries several public Tabdeal endpoints.
    This prevents the bot from crashing if one endpoint
    returns a different JSON structure.
    """

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


def extract_market_list(data):
    """
    Safely extracts symbols from different JSON formats.
    """

    result = []

    if isinstance(data, list):
        raw_items = data

    elif isinstance(data, dict):
        raw_items = None

        for key in [
            "symbols",
            "markets",
            "data",
            "result",
            "items",
        ]:
            value = data.get(key)

            if isinstance(value, list):
                raw_items = value
                break

        if raw_items is None:
            return []

    else:
        return []

    for item in raw_items:

        if isinstance(item, str):
            symbol = item.upper()

        elif isinstance(item, dict):
            symbol = (
                item.get("symbol")
                or item.get("market")
                or item.get("name")
                or item.get("pair")
                or ""
            )

            symbol = str(symbol).upper()

        else:
            continue

        symbol = symbol.replace("-", "").replace("_", "")

        if symbol.endswith("USDT"):
            result.append(symbol)

    return sorted(set(result))


# ============================================================
# TRADES -> 5M CANDLES
# ============================================================

def get_trades(symbol):
    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if not isinstance(data, list):
        return []

    return data


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
    except Exception:
        return None

    if not timestamp:
        return None

    try:
        timestamp = float(timestamp)

        if timestamp < 10000000000:
            timestamp *= 1000

    except Exception:
        return None

    return {
        "price": price,
        "qty": abs(quantity),
        "time": int(timestamp),
    }


def trades_to_candles(trades):
    normalized = []

    for item in trades:
        trade = normalize_trade(item)

        if trade and trade["price"] > 0:
            normalized.append(trade)

    if not normalized:
        return []

    normalized.sort(key=lambda x: x["time"])

    candles = {}

    interval = 5 * 60 * 1000

    for trade in normalized:

        bucket = (trade["time"] // interval) * interval

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

    result.sort(key=lambda x: x["time"])

    return result[-CANDLE_LIMIT:]


# ============================================================
# INDICATOR HELPERS
# ============================================================

def pct_change(old, new):
    if old == 0:
        return 0.0

    return ((new - old) / old) * 100.0


def average(values):
    if not values:
        return 0.0

    return sum(values) / len(values)


def candle_body(c):
    return abs(c["close"] - c["open"])


def candle_range(c):
    return max(c["high"] - c["low"], 0.0000000001)


# ============================================================
# SCORING
# ============================================================

def analyze(symbol, candles):

    if len(candles) < 30:
        return None

    # Use CLOSED candles only.
    closed = candles[:-1]

    if len(closed) < 25:
        return None

    last = closed[-1]

    close = last["close"]

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    change_5m = pct_change(
        closed[-2]["close"],
        closed[-1]["close"],
    )

    change_15m = pct_change(
        closed[-4]["close"],
        closed[-1]["close"],
    )

    change_1h = pct_change(
        closed[-13]["close"],
        closed[-1]["close"],
    )

    score = 0

    reasons = []

    # 5M momentum
    if change_5m > 0:
        score += 2
        reasons.append("5M UP")

    if change_5m > 0.30:
        score += 1

    # 15M momentum
    if change_15m > 0:
        score += 2
        reasons.append("15M UP")

    if change_15m > 0.80:
        score += 1

    # 1H momentum
    if change_1h > 0:
        score += 2
        reasons.append("1H UP")

    if change_1h > 1.50:
        score += 1

    # --------------------------------------------------------
    # HIGHER HIGHS
    # --------------------------------------------------------

    recent = closed[-8:]

    highs = [x["high"] for x in recent]
    lows = [x["low"] for x in recent]

    if highs[-1] >= max(highs[:-1]):
        score += 2
        reasons.append("NEW HIGH")

    if lows[-1] > min(lows[:-1]):
        score += 1
        reasons.append("HIGHER LOW")

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    previous_high = max(
        x["high"] for x in closed[-13:-1]
    )

    breakout = close > previous_high

    if breakout:
        score += 3
        reasons.append("BREAKOUT")

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    retest = False

    if len(closed) >= 6:

        breakout_level = max(
            x["high"] for x in closed[-8:-2]
        )

        recent_low = min(
            x["low"] for x in closed[-3:]
        )

        if (
            recent_low <= breakout_level * 1.006
            and close >= breakout_level
        ):
            retest = True
            score += 3
            reasons.append("RETEST")

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    volumes = [
        x["volume"]
        for x in closed[-21:-1]
        if x["volume"] > 0
    ]

    if volumes:

        avg_volume = average(volumes)

        if avg_volume > 0 and last["volume"] > avg_volume * 1.30:
            score += 2
            reasons.append("VOLUME")

    # --------------------------------------------------------
    # CHASE PROTECTION
    # --------------------------------------------------------

    if change_5m > CHASE_LIMIT_5M:
        return {
            "symbol": symbol,
            "score": score,
            "price": close,
            "change_5m": change_5m,
            "change_15m": change_15m,
            "change_1h": change_1h,
            "status": "CHASE",
            "reasons": reasons,
        }

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    recent_low = min(
        x["low"] for x in closed[-8:]
    )

    sl = recent_low

    if sl >= close:
        sl = close * 0.995

    risk = close - sl

    if risk <= 0:
        risk = close * 0.005

    tp1 = close + risk * 1.5
    tp2 = close + risk * 2.5

    if score >= BUY_MIN_SCORE:
        status = "BUY"

    elif score >= WATCH_MIN_SCORE:
        status = "WATCH"

    else:
        status = "NONE"

    return {
        "symbol": symbol,
        "score": score,
        "price": close,
        "change_5m": change_5m,
        "change_15m": change_15m,
        "change_1h": change_1h,
        "status": status,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "reasons": reasons,
    }


# ============================================================
# FORMAT
# ============================================================

def format_price(value):

    if value >= 100:
        return f"{value:.2f}"

    if value >= 1:
        return f"{value:.5f}"

    if value >= 0.01:
        return f"{value:.7f}"

    return f"{value:.10f}"


def format_signal(item, rank):

    status = item["status"]

    if status == "BUY":
        title = "🟢 CONFIRMED BUY"

    elif status == "WATCH":
        title = "🟡 WATCH"

    else:
        title = "⚪ SIGNAL"

    reasons = ", ".join(item["reasons"][:7])

    text = (
        f"{title}\n\n"
        f"#{rank}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: {format_price(item['price'])}\n\n"
        f"📈 5M: {item['change_5m']:+.2f}%\n"
        f"📊 15M: {item['change_15m']:+.2f}%\n"
        f"🕐 1H: {item['change_1h']:+.2f}%\n\n"
        f"🛑 SL: {format_price(item['sl'])}\n"
        f"🎯 TP1: {format_price(item['tp1'])}\n"
        f"🎯 TP2: {format_price(item['tp2'])}\n\n"
        f"🔎 {reasons}"
    )

    return text


# ============================================================
# MAIN SCANNER
# ============================================================

def main():

    print("=" * 60)
    print(f"ATI CRYPTO BOT {VERSION}")
    print("BREAKOUT + RETEST / UPWARD SCANNER")
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

    print(f"📊 USDT MARKETS: {len(markets)}")

    results = []

    total = len(markets)

    for index, symbol in enumerate(markets, start=1):

        try:

            trades = get_trades(symbol)

            if not trades:
                continue

            candles = trades_to_candles(trades)

            if not candles:
                continue

            result = analyze(
                symbol,
                candles,
            )

            if result is None:
                continue

            if result["status"] in ("BUY", "WATCH"):
                results.append(result)

        except Exception as e:
            print(
                f"⚠️ {symbol} ERROR: {str(e)}"
            )

        # Small delay protects API
        if index % 20 == 0:
            print(
                f"🔎 Scanned {index}/{total}"
            )
            time.sleep(0.15)

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["score"],
            x["change_5m"],
            x["change_15m"],
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
    # HEADER
    # --------------------------------------------------------

    now = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 BREAKOUT + RETEST SCANNER\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n\n"
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}\n"
        f"🚫 5M CHASE LIMIT: {CHASE_LIMIT_5M}%\n\n"
        f"🕐 SCAN:\n{now}\n"
    )

    # --------------------------------------------------------
    # BUY RESULTS
    # --------------------------------------------------------

    if buys:

        message += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "🟢 CONFIRMED BUYS\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        for rank, item in enumerate(
            buys[:TOP_RESULTS],
            start=1,
        ):
            message += (
                "\n"
                + format_signal(item, rank)
                + "\n"
            )

    else:

        message += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "🟢 CONFIRMED BUYS\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "❌ No confirmed BUY\n"
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
                f"📈 {item['change_5m']:+.2f}%\n"
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
        f"📡 MARKETS: {len(markets)}\n"
        "\n⚠️ SIGNAL ONLY — NO REAL ORDER"
    )

    print(message)

    telegram_send(message)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
