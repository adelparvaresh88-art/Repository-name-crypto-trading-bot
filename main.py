import os
import json
import urllib.request


SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 50

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def get_price_data():
    url = (
        "https://api.binance.com/api/v3/klines"
        "?symbol=BTCUSDT&interval=5m&limit=50"
    )

    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    if not TOKEN or not CHAT_ID:
        print("Telegram Secrets are missing.")
        return

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(url, data=data)

    with urllib.request.urlopen(request, timeout=20) as response:
        print("Telegram message sent.")
        print(response.read().decode())


def main():
    candles = get_price_data()

    # آخرین کندل بسته‌شده
    last = candles[-2]
    previous = candles[-3]

    current = float(last[4])
    previous_price = float(previous[4])

    change = ((current - previous_price) / previous_price) * 100

    closes = [float(candle[4]) for candle in candles[:-1]]

    short_average = sum(closes[-5:]) / 5
    long_average = sum(closes[-15:]) / 15

    buy_score = 0
    sell_score = 0

    if short_average > long_average:
        buy_score += 2

    if current > previous_price:
        buy_score += 1

    if change >= 0.08:
        buy_score += 2

    if short_average < long_average:
        sell_score += 2

    if current < previous_price:
        sell_score += 1

    if change <= -0.08:
        sell_score += 2

    signal = "HOLD"

    if buy_score >= 3 and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= 3 and sell_score > buy_score:
        signal = "SELL"

    print("================================")
    print("ATI CRYPTO BOT")
    print("BTC:", current)
    print("BUY SCORE:", buy_score, "/5")
    print("SELL SCORE:", sell_score, "/5")
    print("SIGNAL:", signal)
    print("================================")

    if signal == "HOLD":
        return

    message = (
        "⚡ ATI CRYPTO BOT V12\n\n"
        f"₿ BTC: ${current:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE CONFIRMED\n\n"
        f"📢 SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n"
        f"📊 MOVE: {change:.3f}%\n\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    send_telegram(message)


if __name__ == "__main__":
    main()
