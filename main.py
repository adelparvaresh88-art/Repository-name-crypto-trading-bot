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
MIN_MOVE_PERCENT = 0.05


def send_telegram(message):
    if not BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN is missing")

    if not CHAT_ID:
        raise Exception("TELEGRAM_CHAT_ID is missing")

    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode()


def get_data():
    url = (
        "https://api.binance.com/api/v3/klines"
        "?symbol=BTCUSDT&interval=5m&limit=60"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())

    if not isinstance(data, list):
        raise Exception("Invalid Binance data")

    if len(data) < 40:
        raise Exception("Not enough candle data")

    return data[:-1]


def calculate_signal(candles):

    closes = [float(c[4]) for c in candles]
    opens = [float(c[1]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    current = closes[-1]
    previous = closes[-2]

    sma5 = sum(closes[-5:]) / 5
    sma20 = sum(closes[-20:]) / 20

    buy_score = 0
    sell_score = 0

    # 1 - Trend
    if sma5 > sma20:
        buy_score += 1
    elif sma5 < sma20:
        sell_score += 1

    # 2 - Current candle
    if closes[-1] > opens[-1]:
        buy_score += 1
    elif closes[-1] < opens[-1]:
        sell_score += 1

    # 3 - Price momentum
    change = ((current - previous) / previous) * 100

    if change >= MIN_MOVE_PERCENT:
        buy_score += 1
    elif change <= -MIN_MOVE_PERCENT:
        sell_score += 1

    # 4 - Breakout
    previous_high = max(highs[-6:-1])
    previous_low = min(lows[-6:-1])

    if current > previous_high:
        buy_score += 1

    if current < previous_low:
        sell_score += 1

    # 5 - Candle body strength
    candle_range = highs[-1] - lows[-1]

    if candle_range > 0:
        body = abs(closes[-1] - opens[-1])
        body_percent = (body / candle_range) * 100

        if body_percent >= 50:

            if closes[-1] > opens[-1]:
                buy_score += 1

            elif closes[-1] < opens[-1]:
                sell_score += 1

    # Final signal
    if buy_score >= MIN_SCORE and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= MIN_SCORE and sell_score > buy_score:
        signal = "SELL"

    else:
        signal = "HOLD"

    return (
        signal,
        current,
        buy_score,
        sell_score,
        abs(change)
    )


def main():

    print("================================")
    print("      ⚡ ATI CRYPTO BOT V15")
    print("================================")

    candles = get_data()

    print("✅ BTC 5m data received")

    (
        signal,
        current,
        buy_score,
        sell_score,
        move_percent
    ) = calculate_signal(candles)

    print("BTC:", round(current, 2))
    print("BUY SCORE:", buy_score, "/5")
    print("SELL SCORE:", sell_score, "/5")
    print("MOVE:", round(move_percent, 3), "%")
    print("SIGNAL:", signal)

    if signal == "BUY":

        stop_loss = current * (1 - SL_PERCENT / 100)
        take_profit = current * (1 + TP_PERCENT / 100)

        signal_text = "🟢 SIGNAL: BUY"

    elif signal == "SELL":

        stop_loss = current * (1 + SL_PERCENT / 100)
        take_profit = current * (1 - TP_PERCENT / 100)

        signal_text = "🔴 SIGNAL: SELL"

    else:

        stop_loss = 0
        take_profit = 0

        signal_text = "⚪ SIGNAL: HOLD"

    if signal == "HOLD":

        trade_info = "⏸ Waiting for stronger setup"

    else:

        trade_info = (
            f"💰 Entry: ${current:,.2f}\n"
            f"🛑 SL: ${stop_loss:,.2f}\n"
            f"🎯 TP: ${take_profit:,.2f}"
        )

    message = (
        "⚡ ATI CRYPTO BOT V15\n\n"
        f"₿ BTC: ${current:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE CONFIRMED\n\n"
        f"{signal_text}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n"
        f"📊 MOVE: {move_percent:.3f}%\n\n"
        f"{trade_info}\n\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    send_telegram(message)

    print("✅ Telegram message sent")
    print("================================")


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("================================")
        print("❌ ATI BOT ERROR")
        print(str(error))
        print("================================")

        traceback.print_exc()

        raise
