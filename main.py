import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# ==========================================
# ATI CRYPTO BOT V16
# ==========================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TIMEFRAME = "5m"
CANDLE_COUNT = 30

# ------------------------------------------
# HTTP GET
# ------------------------------------------

def http_get(url, timeout=15):
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ATI-CRYPTO-BOT/16.0",
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read().decode("utf-8")
        return json.loads(data)


# ------------------------------------------
# TELEGRAM
# ------------------------------------------

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN is missing")

    if not TELEGRAM_CHAT_ID:
        raise Exception("TELEGRAM_CHAT_ID is missing")

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "ATI-CRYPTO-BOT/16.0"
        }
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = response.read().decode("utf-8")

    return result


# ------------------------------------------
# COINBASE DATA
# ------------------------------------------

def get_coinbase_data():

    url = (
        "https://api.exchange.coinbase.com/"
        "products/BTC-USD/candles"
        "?granularity=300"
    )

    data = http_get(url)

    if not isinstance(data, list) or len(data) < 10:
        raise Exception("Coinbase returned insufficient candle data")

    candles = []

    for item in data:

        # Coinbase:
        # [time, low, high, open, close, volume]

        if len(item) < 6:
            continue

        candles.append({
            "time": float(item[0]),
            "low": float(item[1]),
            "high": float(item[2]),
            "open": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5])
        })

    candles.sort(key=lambda x: x["time"])

    return candles[-CANDLE_COUNT:], "COINBASE"


# ------------------------------------------
# KRAKEN FALLBACK
# ------------------------------------------

def get_kraken_data():

    url = (
        "https://api.kraken.com/0/public/OHLC"
        "?pair=XBTUSD&interval=5"
    )

    data = http_get(url)

    if not isinstance(data, dict):
        raise Exception("Invalid Kraken response")

    if data.get("error"):
        raise Exception("Kraken API error: " + str(data["error"]))

    result = data.get("result", {})

    pair_data = None

    for key, value in result.items():
        if key != "last":
            pair_data = value
            break

    if not pair_data or len(pair_data) < 10:
        raise Exception("Kraken returned insufficient candle data")

    candles = []

    for item in pair_data:

        # Kraken:
        # time, open, high, low, close, vwap, volume, count

        if len(item) < 7:
            continue

        candles.append({
            "time": float(item[0]),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[6])
        })

    candles.sort(key=lambda x: x["time"])

    return candles[-CANDLE_COUNT:], "KRAKEN"


# ------------------------------------------
# MARKET DATA WITH AUTOMATIC FALLBACK
# ------------------------------------------

def get_market_data():

    errors = []

    try:
        candles, source = get_coinbase_data()

        price = candles[-1]["close"]

        return candles, price, source

    except Exception as error:
        errors.append("Coinbase: " + str(error))

    try:
        candles, source = get_kraken_data()

        price = candles[-1]["close"]

        return candles, price, source

    except Exception as error:
        errors.append("Kraken: " + str(error))

    raise Exception(" | ".join(errors))


# ------------------------------------------
# CANDLE ANALYSIS
# ------------------------------------------

def candle_direction(candle):

    if candle["close"] > candle["open"]:
        return "BULL"

    if candle["close"] < candle["open"]:
        return "BEAR"

    return "FLAT"


def body_percent(candle):

    high = candle["high"]
    low = candle["low"]
    open_price = candle["open"]
    close_price = candle["close"]

    total_range = high - low

    if total_range <= 0:
        return 0

    body = abs(close_price - open_price)

    return (body / total_range) * 100


# ------------------------------------------
# SIGNAL ENGINE
# ------------------------------------------

def calculate_signal(candles):

    if len(candles) < 12:
        raise Exception("Not enough candles for signal calculation")

    # Use CLOSED candles only.
    # The latest returned candle can still be forming.
    closed = candles[:-1]

    if len(closed) < 10:
        raise Exception("Not enough closed candles")

    last = closed[-1]
    previous = closed[-2]
    c3 = closed[-3]
    c4 = closed[-4]
    c5 = closed[-5]

    buy_score = 0
    sell_score = 0

    # --------------------------------------
    # 1. LAST CANDLE DIRECTION
    # --------------------------------------

    if last["close"] > last["open"]:
        buy_score += 1

    if last["close"] < last["open"]:
        sell_score += 1

    # --------------------------------------
    # 2. PREVIOUS CANDLE DIRECTION
    # --------------------------------------

    if previous["close"] > previous["open"]:
        buy_score += 1

    if previous["close"] < previous["open"]:
        sell_score += 1

    # --------------------------------------
    # 3. THREE-CANDLE MOMENTUM
    # --------------------------------------

    if (
        last["close"] > previous["close"]
        and previous["close"] > c3["close"]
    ):
        buy_score += 1

    if (
        last["close"] < previous["close"]
        and previous["close"] < c3["close"]
    ):
        sell_score += 1

    # --------------------------------------
    # 4. SHORT PRICE ACTION
    # --------------------------------------

    if last["close"] > c4["close"]:
        buy_score += 1

    if last["close"] < c4["close"]:
        sell_score += 1

    # --------------------------------------
    # 5. BREAK OF RECENT HIGH / LOW
    # --------------------------------------

    recent_high = max(
        previous["high"],
        c3["high"],
        c4["high"],
        c5["high"]
    )

    recent_low = min(
        previous["low"],
        c3["low"],
        c4["low"],
        c5["low"]
    )

    if last["close"] > recent_high:
        buy_score += 1

    if last["close"] < recent_low:
        sell_score += 1

    # --------------------------------------
    # STRONG SIGNAL FILTER
    # --------------------------------------

    if buy_score >= 4 and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= 4 and sell_score > buy_score:
        signal = "SELL"

    else:
        signal = "NO_STRONG_SIGNAL"

    return signal, buy_score, sell_score, last


# ------------------------------------------
# SL / TP
# ------------------------------------------

def calculate_sl_tp(signal, entry, candles):

    closed = candles[:-1]

    recent = closed[-5:]

    recent_high = max(c["high"] for c in recent)
    recent_low = min(c["low"] for c in recent)

    # Minimum protection distance
    minimum_distance = entry * 0.004

    if signal == "BUY":

        sl = min(
            recent_low,
            entry - minimum_distance
        )

        risk = entry - sl

        if risk <= 0:
            risk = minimum_distance
            sl = entry - risk

        tp = entry + (risk * 2)

    else:

        sl = max(
            recent_high,
            entry + minimum_distance
        )

        risk = sl - entry

        if risk <= 0:
            risk = minimum_distance
            sl = entry + risk

        tp = entry - (risk * 2)

    return sl, tp


# ------------------------------------------
# MAIN
# ------------------------------------------

def main():

    print("========================================")
    print("⚡ ATI CRYPTO BOT V16")
    print("========================================")

    # Telegram test
    try:
        send_telegram(
            "⚡ ATI CRYPTO BOT V16\n\n"
            "🔄 Starting...\n"
            "📡 Checking market data..."
        )

        print("✅ Telegram: OK")

    except Exception as error:

        print("❌ Telegram ERROR:")
        print(str(error))
        raise

    # Market data
    try:

        candles, price, source = get_market_data()

        print("✅ MARKET DATA OK")
        print("📊 SOURCE:", source)
        print("₿ BTC:", price)

    except Exception as error:

        print("❌ MARKET DATA ERROR:")
        print(str(error))

        send_telegram(
            "⚠️ ATI CRYPTO BOT V16\n\n"
            "✅ Telegram: OK\n"
            "❌ MARKET DATA ERROR\n\n"
            "ERROR:\n"
            + str(error)
        )

        raise

    # Signal
    try:

        signal, buy_score, sell_score, candle = calculate_signal(
            candles
        )

        entry = candle["close"]

        print("SIGNAL:", signal)
        print("BUY SCORE:", buy_score)
        print("SELL SCORE:", sell_score)

    except Exception as error:

        print("❌ SIGNAL ERROR:")
        print(str(error))

        send_telegram(
            "⚠️ ATI CRYPTO BOT V16\n\n"
            "✅ MARKET DATA OK\n"
            "❌ SIGNAL ERROR\n\n"
            + str(error)
        )

        raise

    # --------------------------------------
    # NO STRONG SIGNAL
    # --------------------------------------

    if signal == "NO_STRONG_SIGNAL":

        print("ℹ️ No strong BUY/SELL signal.")

        send_telegram(
            "⚪ ATI CRYPTO BOT V16\n\n"
            "₿ BTC: $" + f"{price:,.2f}" + "\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE CONFIRMED\n"
            "💪 STRONG SIGNAL FILTER\n\n"
            "📊 SOURCE: " + source + "\n"
            "📈 BUY SCORE: " + str(buy_score) + "/5\n"
            "📉 SELL SCORE: " + str(sell_score) + "/5\n\n"
            "⚪ NO STRONG SIGNAL\n\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

        return

    # --------------------------------------
    # SL / TP
    # --------------------------------------

    sl, tp = calculate_sl_tp(
        signal,
        entry,
        candles
    )

    move = abs(
        candle["close"] - candle["open"]
    ) / candle["open"] * 100

    if signal == "BUY":
        signal_text = "🟢 SIGNAL: BUY"
    else:
        signal_text = "🔴 SIGNAL: SELL"

    message = (
        "⚡ ATI CRYPTO BOT V16\n\n"
        "₿ BTC: $" + f"{price:,.2f}" + "\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE CONFIRMED\n"
        "💪 STRONG SIGNAL FILTER\n\n"
        "📊 SOURCE: " + source + "\n\n"
        + signal_text + "\n"
        "📈 BUY SCORE: " + str(buy_score) + "/5\n"
        "📉 SELL SCORE: " + str(sell_score) + "/5\n"
        "📊 MOVE: " + f"{move:.3f}" + "%\n\n"
        "💰 Entry: $" + f"{entry:,.2f}" + "\n"
        "🛑 SL: $" + f"{sl:,.2f}" + "\n"
        "🎯 TP: $" + f"{tp:,.2f}" + "\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING DISABLED"
    )

    send_telegram(message)

    print("✅ SIGNAL SENT TO TELEGRAM")
    print("========================================")


# ------------------------------------------
# ERROR HANDLER
# ------------------------------------------

if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("========================================")
        print("❌ BOT ERROR")
        print(str(error))
        print("========================================")

        raise
