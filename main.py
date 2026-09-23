import os
import json
import requests
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT V15
# TABDEAL BTCUSDT
# PERSISTENT 5M CANDLE HISTORY
# PAPER / TEST ONLY
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME_MINUTES = 5

TRADES_LIMIT = 1000
TIMEOUT = 15

HISTORY_FILE = "active_signal.json"

MAX_HISTORY = 300

MIN_SCORE = 4

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing")
        return False

    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID missing")
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
                "text": message
            },
            timeout=TIMEOUT
        )

        if response.status_code == 200:
            print("✅ Telegram OK")
            return True

        print("❌ Telegram error:", response.text)
        return False

    except Exception as e:

        print("❌ Telegram exception:", e)
        return False


# ============================================================
# CURRENT PRICE
# ============================================================

def get_current_price():

    url = f"{BASE_URL}/r/api/v1/depth"

    try:

        response = requests.get(
            url,
            params={
                "symbol": SYMBOL,
                "limit": 5
            },
            timeout=TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not bids or not asks:
            return None

        bid = float(bids[0][0])
        ask = float(asks[0][0])

        return (bid + ask) / 2

    except Exception as e:

        print("❌ Price API error:", e)
        return None


# ============================================================
# RECENT TRADES
# ============================================================

def get_trades():

    url = f"{BASE_URL}/r/api/v1/trades"

    try:

        response = requests.get(
            url,
            params={
                "symbol": SYMBOL,
                "limit": TRADES_LIMIT
            },
            timeout=TIMEOUT
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, list):
            return []

        return data

    except Exception as e:

        print("❌ Trades API error:", e)
        return []


# ============================================================
# BUILD 5M CANDLES FROM TRADES
# ============================================================

def build_5m_candles(trades):

    candles = {}

    bucket_size = TIMEFRAME_MINUTES * 60 * 1000

    for trade in trades:

        try:

            price = float(trade["price"])
            qty = float(trade.get("qty", 0))
            timestamp = int(trade["time"])

        except (KeyError, TypeError, ValueError):

            continue

        bucket = (
            timestamp // bucket_size
        ) * bucket_size

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty
            }

        else:

            candle = candles[bucket]

            candle["high"] = max(
                candle["high"],
                price
            )

            candle["low"] = min(
                candle["low"],
                price
            )

            candle["close"] = price

            candle["volume"] += qty

    result = list(candles.values())

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# ============================================================
# HISTORY LOAD
# ============================================================

def load_history():

    if not os.path.exists(HISTORY_FILE):

        return []

    try:

        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            data = json.load(file)

        if isinstance(data, list):
            return data

        return []

    except Exception as e:

        print("⚠️ History read error:", e)
        return []


# ============================================================
# HISTORY SAVE
# ============================================================

def save_history(history):

    history = sorted(
        history,
        key=lambda x: x["time"]
    )

    # Remove duplicate candle timestamps
    unique = {}

    for candle in history:
        unique[str(candle["time"])] = candle

    history = list(unique.values())

    history.sort(
        key=lambda x: x["time"]
    )

    # Keep latest history
    history = history[-MAX_HISTORY:]

    try:

        with open(
            HISTORY_FILE,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                history,
                file,
                indent=2
            )

        print(
            f"✅ History saved: {len(history)} candles"
        )

    except Exception as e:

        print("❌ History save error:", e)


# ============================================================
# MERGE NEW CANDLES INTO HISTORY
# ============================================================

def merge_history(history, new_candles):

    merged = {}

    # Existing history
    for candle in history:

        try:
            key = int(candle["time"])
            merged[key] = candle

        except Exception:
            continue

    # New data
    for candle in new_candles:

        try:
            key = int(candle["time"])
            merged[key] = candle

        except Exception:
            continue

    result = list(merged.values())

    result.sort(
        key=lambda x: x["time"]
    )

    return result[-MAX_HISTORY:]


# ============================================================
# REMOVE CURRENT OPEN CANDLE
# ============================================================

def get_closed_candles(candles):

    now_ms = int(
        datetime.now(timezone.utc).timestamp()
        * 1000
    )

    bucket_size = TIMEFRAME_MINUTES * 60 * 1000

    current_bucket = (
        now_ms // bucket_size
    ) * bucket_size

    return [
        candle
        for candle in candles
        if int(candle["time"]) < current_bucket
    ]


# ============================================================
# CANDLE HELPERS
# ============================================================

def candle_range(c):

    return max(
        float(c["high"]) - float(c["low"]),
        0.00000001
    )


def candle_body(c):

    return abs(
        float(c["close"])
        - float(c["open"])
    )


def body_ratio(c):

    return candle_body(c) / candle_range(c)


def bullish(c):

    return float(c["close"]) > float(c["open"])


def bearish(c):

    return float(c["close"]) < float(c["open"])


def upper_wick(c):

    return (
        float(c["high"])
        - max(
            float(c["open"]),
            float(c["close"])
        )
    )


def lower_wick(c):

    return (
        min(
            float(c["open"]),
            float(c["close"])
        )
        - float(c["low"])
    )


# ============================================================
# SMA
# ============================================================

def sma(candles, length):

    if len(candles) < length:
        return None

    values = [
        float(c["close"])
        for c in candles[-length:]
    ]

    return sum(values) / len(values)


# ============================================================
# V15 SIGNAL ENGINE
# ============================================================

def calculate_signal(candles):

    if len(candles) < 20:

        return {
            "signal": "NO SIGNAL",
            "buy": 0,
            "sell": 0,
            "trend": "WAITING"
        }

    c1 = candles[-1]
    c2 = candles[-2]
    c3 = candles[-3]
    c4 = candles[-4]
    c5 = candles[-5]

    buy = 0
    sell = 0

    # ========================================================
    # 1. TREND
    # ========================================================

    sma5 = sma(candles, 5)
    sma10 = sma(candles, 10)
    sma20 = sma(candles, 20)

    trend = "SIDEWAYS"

    if (
        sma5 is not None
        and sma10 is not None
        and sma20 is not None
    ):

        if (
            float(c1["close"]) > sma5
            and sma5 > sma10
            and sma10 > sma20
        ):

            buy += 1
            trend = "UPTREND"

        elif (
            float(c1["close"]) < sma5
            and sma5 < sma10
            and sma10 < sma20
        ):

            sell += 1
            trend = "DOWNTREND"

    # ========================================================
    # 2. STRUCTURE
    # ========================================================

    higher_high = (
        float(c1["high"]) > float(c2["high"])
        and float(c2["high"]) >= float(c3["high"])
    )

    higher_low = (
        float(c1["low"]) > float(c2["low"])
        and float(c2["low"]) >= float(c3["low"])
    )

    lower_high = (
        float(c1["high"]) < float(c2["high"])
        and float(c2["high"]) <= float(c3["high"])
    )

    lower_low = (
        float(c1["low"]) < float(c2["low"])
        and float(c2["low"]) <= float(c3["low"])
    )

    if higher_high and higher_low:
        buy += 1

    if lower_high and lower_low:
        sell += 1

    # ========================================================
    # 3. MOMENTUM
    # ========================================================

    if (
        float(c1["close"])
        > float(c2["close"])
        > float(c3["close"])
    ):
        buy += 1

    if (
        float(c1["close"])
        < float(c2["close"])
        < float(c3["close"])
    ):
        sell += 1

    # ========================================================
    # 4. BREAKOUT
    # ========================================================

    previous_high = max(
        float(c2["high"]),
        float(c3["high"]),
        float(c4["high"]),
        float(c5["high"])
    )

    previous_low = min(
        float(c2["low"]),
        float(c3["low"]),
        float(c4["low"]),
        float(c5["low"])
    )

    if float(c1["close"]) > previous_high:
        buy += 1

    if float(c1["close"]) < previous_low:
        sell += 1

    # ========================================================
    # 5. CANDLE STRENGTH
    # ========================================================

    ratio = body_ratio(c1)

    if (
        bullish(c1)
        and ratio >= 0.60
        and lower_wick(c1)
        <= candle_body(c1) * 0.80
    ):
        buy += 1

    if (
        bearish(c1)
        and ratio >= 0.60
        and upper_wick(c1)
        <= candle_body(c1) * 0.80
    ):
        sell += 1

    # ========================================================
    # FINAL FILTER
    # ========================================================

    signal = "NO SIGNAL"

    if buy >= MIN_SCORE and buy > sell:
        signal = "BUY"

    elif sell >= MIN_SCORE and sell > buy:
        signal = "SELL"

    return {
        "signal": signal,
        "buy": buy,
        "sell": sell,
        "trend": trend
    }


# ============================================================
# SL / TP
# ============================================================

def calculate_sl_tp(signal, candles):

    entry = float(candles[-1]["close"])

    recent = candles[-5:]

    recent_high = max(
        float(c["high"])
        for c in recent
    )

    recent_low = min(
        float(c["low"])
        for c in recent
    )

    if signal == "BUY":

        risk = entry - recent_low

        if risk <= 0:
            risk = entry * 0.004

        sl = recent_low
        tp = entry + risk * 2

        return entry, sl, tp

    if signal == "SELL":

        risk = recent_high - entry

        if risk <= 0:
            risk = entry * 0.004

        sl = recent_high
        tp = entry - risk * 2

        return entry, sl, tp

    return entry, None, None


# ============================================================
# FORMAT
# ============================================================

def fmt(value):

    if value is None:
        return "-"

    return f"${value:,.2f}"


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("ATI CRYPTO BOT V15")
    print("PERSISTENT 5M HISTORY")
    print("PAPER / TEST")
    print("=" * 60)

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    current_price = get_current_price()

    if current_price is None:

        send_telegram(
            """🛡 ATI SAFETY

❌ BTCUSDT PRICE ERROR

Tabdeal price API failed.

🛑 NO TRADE
"""
        )

        return

    # --------------------------------------------------------
    # TRADES
    # --------------------------------------------------------

    trades = get_trades()

    if not trades:

        send_telegram(
            """🛡 ATI SAFETY

❌ TRADES API ERROR

Tabdeal trades API failed.

🛑 NO TRADE
"""
        )

        return

    # --------------------------------------------------------
    # BUILD NEW CANDLES
    # --------------------------------------------------------

    new_candles = build_5m_candles(trades)

    # --------------------------------------------------------
    # LOAD OLD HISTORY
    # --------------------------------------------------------

    history = load_history()

    print(
        "Old history:",
        len(history)
    )

    # --------------------------------------------------------
    # MERGE
    # --------------------------------------------------------

    history = merge_history(
        history,
        new_candles
    )

    # --------------------------------------------------------
    # CLOSED ONLY
    # --------------------------------------------------------

    closed = get_closed_candles(
        history
    )

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_history(closed)

    print(
        "Closed history:",
        len(closed)
    )

    # --------------------------------------------------------
    # WAIT FOR HISTORY
    # --------------------------------------------------------

    if len(closed) < 20:

        message = f"""⚡ ATI CRYPTO BOT V15

₿ BTC/USDT
⏱ Timeframe: 5m

📡 TABDEAL API: OK
📊 TRADES API: OK

💰 Current: {fmt(current_price)}

📚 STORED 5M CANDLES:
{len(closed)}/20

⏳ BUILDING HISTORY

🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED

📡 TELEGRAM: OK
"""

        send_telegram(message)

        return

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    result = calculate_signal(
        closed
    )

    signal = result["signal"]
    buy = result["buy"]
    sell = result["sell"]
    trend = result["trend"]

    last = closed[-1]

    candle_time = datetime.fromtimestamp(
        int(last["time"]) / 1000,
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    entry, sl, tp = calculate_sl_tp(
        signal,
        closed
    )

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    message = f"""⚡ ATI CRYPTO BOT V15

₿ BTC/USDT
⏱ Timeframe: 5m
✅ CLOSED CANDLE
🧠 PERSISTENT HISTORY ENGINE

📡 TABDEAL API: OK
📊 TRADES API: OK

🕐 Candle: {candle_time}

📚 Stored Candles: {len(closed)}

💰 Current: {fmt(current_price)}
💵 Candle Close: {fmt(entry)}

📊 TREND: {trend}

📈 BUY SCORE: {buy}/5
📉 SELL SCORE: {sell}/5

"""

    if signal == "BUY":

        message += f"""🟢 SIGNAL: BUY

💵 Entry: {fmt(entry)}
🛑 SL: {fmt(sl)}
🎯 TP: {fmt(tp)}

🔥 STRONG BUY
"""

    elif signal == "SELL":

        message += f"""🔴 SIGNAL: SELL

💵 Entry: {fmt(entry)}
🛑 SL: {fmt(sl)}
🎯 TP: {fmt(tp)}

🔥 STRONG SELL
"""

    else:

        message += """⚪ SIGNAL: NO SIGNAL

⏳ NO TRADE
"""

    message += """
🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED

📡 TELEGRAM: OK
"""

    print(message)

    send_telegram(message)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
