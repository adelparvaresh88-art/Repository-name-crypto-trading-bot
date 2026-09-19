import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 30


def send_telegram(message):
    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


def get_candles():
    url = (
        "https://api.binance.com/api/v3/klines"
        "?symbol=" + SYMBOL +
        "&interval=" + INTERVAL +
        "&limit=" + str(LIMIT)
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def get_signal(candles):
    closes = [float(c[4]) for c in candles]

    price = closes[-1]
    previous = closes[-2]

    avg5 = sum(closes[-5:]) / 5
    avg15 = sum(closes[-15:]) / 15

    if avg5 > avg15 and price > previous:
        return "BUY", price

    if avg5 < avg15 and price < previous:
        return "SELL", price

    return "HOLD", price


def main():

    if not BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN is missing")

    if not CHAT_ID:
        raise Exception("TELEGRAM_CHAT_ID is missing")

    candles = get_candles()

    signal, price = get_signal(candles)

    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        "₿ BTC: $" + f"{price:,.2f}" + "\n"
        "⏱ Timeframe: 5m\n\n"
        "📊 SIGNAL: " + signal + "\n\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED\n\n"
        "🕐 " + now
    )

    print(message)

    result = send_telegram(message)

    print("TELEGRAM OK")
    print(result)


if __name__ == "__main__":
    main()
