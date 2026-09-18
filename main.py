import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# =========================
# SETTINGS
# =========================
SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 50

MIN_SCORE = 3
SL_PERCENT = 1.0
TP_PERCENT = 2.0

# =========================
# TELEGRAM
# =========================
def send_telegram(message):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Telegram secrets not found.")
        return

    url = "https://api.telegram.org/bot" + bot_token + "/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        if result.get("ok"):
            print("Telegram message sent.")
        else:
            print("Telegram error:", result)

    except Exception as error:
        print("Telegram connection error:", error)


# =========================
# GET 5M CANDLES
# =========================
def get_candles():
    url = (
        "https://api.binance.com/api/v3/klines"
        "?symbol=" + SYMBOL +
        "&interval=" + INTERVAL +
        "&limit=" + str(LIMIT)
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-Crypto-Bot/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    candles = []

    for item in data:
        candles.append({
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
        })

    return candles


# =========================
# MAIN
# =========================
def main():

    print("================================")
    print("ATI CRYPTO BOT V6")
    print("TIMEFRAME:", INTERVAL)
    print("MODE: PAPER / TEST")
    print("REAL TRADING: DISABLED")
    print("================================")

    try:
        candles = get_candles()
    except Exception as error:
        print("CANDLE ERROR:", error)
        return

    if len(candles) < 25:
        print("Not enough candles.")
        return

    closes = [c["close"] for c in candles]

    current = closes[-1]
    previous = closes[-2]

    # Moving averages
    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-20:]) / 20

    # Recent highs/lows
    recent_high = max(c["high"] for c in candles[-10:])
    recent_low = min(c["low"] for c in candles[-10:])

    buy_score = 0
    sell_score = 0

    # =========================
    # BUY CONDITIONS
    # =========================

    # 1. Short average above long average
    if short_avg > long_avg:
        buy_score += 1

    # 2. Current price above previous close
    if current > previous:
        buy_score += 1

    # 3. Current price above short average
    if current > short_avg:
        buy_score += 1

    # 4. Price breaking recent high
    if current > recent_high:
        buy_score += 1

    # 5. Last candle bullish
    if candles[-1]["close"] > candles[-1]["open"]:
        buy_score += 1

    # =========================
    # SELL CONDITIONS
    # =========================

    # 1. Short average below long average
    if short_avg < long_avg:
        sell_score += 1

    # 2. Current price below previous close
    if current < previous:
        sell_score += 1

    # 3. Current price below short average
    if current < short_avg:
        sell_score += 1

    # 4. Price breaking recent low
    if current < recent_low:
        sell_score += 1

    # 5. Last candle bearish
    if candles[-1]["close"] < candles[-1]["open"]:
        sell_score += 1

    print("BTC PRICE:", f"${current:,.2f}")
    print("SHORT AVG:", f"${short_avg:,.2f}")
    print("LONG AVG:", f"${long_avg:,.2f}")
    print("BUY SCORE:", buy_score, "/5")
    print("SELL SCORE:", sell_score, "/5")

    signal = "HOLD"
    message = None

    # =========================
    # BUY
    # =========================
    if buy_score >= MIN_SCORE and buy_score > sell_score:

        signal = "BUY"

        stop_loss = current * (1 - SL_PERCENT / 100)
        take_profit = current * (1 + TP_PERCENT / 100)

        message = (
            "🟢 BTC BUY - PAPER\n\n"
            "⏱ Timeframe: 5M\n"
            "💰 Entry: $" + f"{current:,.2f}" + "\n"
            "🛑 Stop Loss: $" + f"{stop_loss:,.2f}" + "\n"
            "🎯 Take Profit: $" + f"{take_profit:,.2f}" + "\n\n"
            "📊 BUY SCORE: "
            + str(buy_score)
            + "/5\n"
            "⚠️ PAPER TEST - NO REAL TRADE"
        )

    # =========================
    # SELL
    # =========================
    elif sell_score >= MIN_SCORE and sell_score > buy_score:

        signal = "SELL"

        stop_loss = current * (1 + SL_PERCENT / 100)
        take_profit = current * (1 - TP_PERCENT / 100)

        message = (
            "🔴 BTC SELL - PAPER\n\n"
            "⏱ Timeframe: 5M\n"
            "💰 Entry: $" + f"{current:,.2f}" + "\n"
            "🛑 Stop Loss: $" + f"{stop_loss:,.2f}" + "\n"
            "🎯 Take Profit: $" + f"{take_profit:,.2f}" + "\n\n"
            "📊 SELL SCORE: "
            + str(sell_score)
            + "/5\n"
            "⚠️ PAPER TEST - NO REAL TRADE"
        )

    # =========================
    # HOLD
    # =========================
    else:

        message = (
            "⚪ BTC HOLD - PAPER\n\n"
            "⏱ Timeframe: 5M\n"
            "💰 BTC: $" + f"{current:,.2f}" + "\n\n"
            "📊 BUY SCORE: "
            + str(buy_score)
            + "/5\n"
            "📊 SELL SCORE: "
            + str(sell_score)
            + "/5\n\n"
            "⚠️ PAPER TEST - NO REAL TRADE"
        )

    print("SIGNAL:", signal)
    print("--------------------------------")
    print(message)
    print("--------------------------------")

    send_telegram(message)

    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    print("BOT TIME:", now)
    print("BOT FINISHED SUCCESSFULLY.")


# =========================
# START
# =========================
if __name__ == "__main__":
    main()
