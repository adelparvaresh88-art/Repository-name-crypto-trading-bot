import os
import json
import urllib.request
from datetime import datetime

SYMBOL = "BTCUSDT"
LIMIT = 30

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_price_data():
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval=5m&limit={LIMIT}"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-Crypto-Bot"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("TELEGRAM SETTINGS NOT FOUND")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = json.dumps({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode())

        if result.get("ok"):
            print("TELEGRAM: MESSAGE SENT")
        else:
            print("TELEGRAM ERROR:", result)

    except Exception as error:
        print("TELEGRAM ERROR:", error)


def main():
    print("================================")
    print("ATI CRYPTO BOT")
    print("MODE: PAPER / TEST")
    print("REAL TRADING: DISABLED")
    print("================================")

    candles = get_price_data()

    closes = [float(candle[4]) for candle in candles]

    current_price = closes[-1]
    previous_price = closes[-2]

    short_average = sum(closes[-5:]) / 5
    long_average = sum(closes[-15:]) / 15

    if short_average > long_average and current_price > previous_price:
        signal = "BUY"
    elif short_average < long_average and current_price < previous_price:
        signal = "SELL"
    else:
        signal = "HOLD"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        f"Symbol: {SYMBOL}\n"
        f"Time: {now}\n"
        f"Price: {current_price:.2f}\n"
        f"Signal: {signal}\n\n"
        "MODE: PAPER / TEST\n"
        "REAL TRADING: DISABLED"
    )

    print(message)

    send_telegram(message)


if __name__ == "__main__":
    main()
