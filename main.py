import os
import json
import urllib.request
import urllib.parse
import traceback

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SL_PERCENT = 0.50
TP_PERCENT = 1.00
MIN_SCORE = 3


def get_data():
    url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=5"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode())

    if data.get("error"):
        raise Exception(str(data["error"]))

    result = data["result"]
    pair_key = [key for key in result if key != "last"][0]
    candles = result[pair_key]

    if len(candles) < 30:
        raise Exception("Not enough candle data")

    # Use only closed candles
    return candles[:-1]


def send_telegram(message):
    if not BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN is missing")

    if not CHAT_ID:
        raise Exception("TELEGRAM_CHAT_ID is missing")

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        result = response.read().decode()

    return result


def calculate_signal(candles):
    closes = [float(c[4]) for c in candles]
    opens = [float(c[1]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    current = closes[-1]
    previous = closes[-2]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-15:]) / 15

    buy_score = 0
    sell_score = 0

    # 1. Trend
    if short_avg > long_avg:
        buy_score += 1
    elif short_avg < long_avg:
        sell_score += 1

    # 2. Price direction
    if current > previous:
        buy_score += 1
    elif current < previous:
        sell_score += 1

    # 3. Candle direction
    if closes[-1] > opens[-1]:
        buy_score += 1
    elif closes[-1] < opens[-1]:
        sell_score += 1

    # 4. Breakout
    recent_high = max(highs[-11:-1])
    recent_low = min(lows[-11:-1])

    if current > recent_high:
        buy_score += 1

    if current < recent_low:
        sell_score += 1

    # 5. Recent movement
    if closes[-1] > closes[-3]:
        buy_score += 1
    elif closes[-1] < closes[-3]:
        sell_score += 1

    print("BUY SCORE:", buy_score, "/5")
    print("SELL SCORE:", sell_score, "/5")

    if buy_score >= MIN_SCORE and buy_score > sell_score:
        return "BUY", buy_score, sell_score

    if sell_score >= MIN_SCORE and sell_score > buy_score:
        return "SELL", buy_score, sell_score

    return "HOLD", buy_score, sell_score


def calculate_levels(price, signal):
    if signal == "BUY":
        sl = price * (1 - SL_PERCENT / 100)
        tp = price * (1 + TP_PERCENT / 100)
    elif signal == "SELL":
        sl = price * (1 + SL_PERCENT / 100)
        tp = price * (1 - TP_PERCENT / 100)
    else:
        return None, None

    return sl, tp


def main():
    print("================================")
    print("ATI CRYPTO BOT V10")
    print("CLOSED CANDLE MODE")
    print("PAPER / TEST MODE")
    print("================================")

    candles = get_data()

    price = float(candles[-1][4])
    candle_time = candles[-1][0]

    print("CANDLE:", candle_time)
    print("BTC PRICE:", price)

    signal, buy_score, sell_score = calculate_signal(candles)

    print("SIGNAL:", signal)

    # Do not send HOLD
    if signal == "HOLD":
        print("HOLD - NO TELEGRAM MESSAGE")
        return

    sl, tp = calculate_levels(price, signal)

    if signal == "BUY":
        icon = "🟢"
    else:
        icon = "🔴"

    message = (
        "⚡ ATI CRYPTO BOT V10\n\n"
        f"₿ BTC: ${price:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE CONFIRMED\n\n"
        f"{icon} SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n\n"
        f"💰 Entry: ${price:,.2f}\n"
        f"🛑 SL: ${sl:,.2f}\n"
        f"🎯 TP: ${tp:,.2f}\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    print(message)

    send_telegram(message)

    print("TELEGRAM: SENT SUCCESSFULLY")


try:
    main()

except Exception as error:
    print("================================")
    print("BOT ERROR:")
    print(str(error))
    print("================================")
    print(traceback.format_exc())

    try:
        send_telegram(
            "⚠️ ATI CRYPTO BOT ERROR\n\n"
            + str(error)
        )
    except Exception:
        pass

    raise
