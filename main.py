import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    try:
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
            result = response.read().decode("utf-8")

        print("TELEGRAM OK")
        print(result)

    except Exception as error:
        print("TELEGRAM ERROR:", str(error))


def get_btc_data():
    url = (
        "https://api.binance.com/api/v3/klines"
        "?symbol=BTCUSDT&interval=5m&limit=30"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read().decode("utf-8")

    candles = json.loads(data)

    closes = [float(candle[4]) for candle in candles]

    price = closes[-1]
    previous = closes[-2]

    avg5 = sum(closes[-5:]) / 5
    avg15 = sum(closes[-15:]) / 15

    if avg5 > avg15 and price > previous:
        signal = "BUY"

    elif avg5 < avg15 and price < previous:
        signal = "SELL"

    else:
        signal = "HOLD"

    return price, signal


def main():

    print("================================")
    print("ATI CRYPTO BOT")
    print("================================")

    if not BOT_TOKEN or not CHAT_ID:
        print("TELEGRAM SECRETS MISSING")
        return

    try:
        price, signal = get_btc_data()

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
        send_telegram(message)

    except Exception as error:

        print("DATA ERROR:", str(error))

        error_message = (
            "⚠️ ATI CRYPTO BOT\n\n"
            "دریافت قیمت با مشکل مواجه شد.\n"
            "معامله واقعی انجام نشد.\n\n"
            "🔧 Error: " + str(error)
        )

        send_telegram(error_message)


if __name__ == "__main__":
    try:
        main()
        print("BOT FINISHED")
    except Exception as error:
        print("FINAL ERROR:", str(error))

    print("WORKFLOW FINISHED")
