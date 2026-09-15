import os
import json
import urllib.request
from datetime import datetime

SYMBOL = "BTCUSDT"
LIMIT = 30

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_klines():
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval=5m&limit={LIMIT}"
    )

    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings are missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    data = json.dumps({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode())

        print("Telegram message sent:", result.get("ok"))
        return result.get("ok", False)

    except Exception as e:
        print("Telegram error:", str(e))
        return False


def main():
    print("================================")
    print("ATI CRYPTO BOT")
    print("MODE: PAPER / TEST")
    print("REAL TRADING: DISABLED")
    print("================================")

    try:
        candles = get_klines()

        closes = [float(candle[4]) for candle in candles]

        current = closes[-1]
        previous = closes[-2]

        short_avg = sum(closes[-5:]) / 5
        long_avg = sum(closes[-15:]) / 15

        if short_avg > long_avg and current > previous:
            signal = "BUY"
        elif short_avg < long_avg and current < previous:
            signal = "SELL"
        else:
            signal = "HOLD"

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        message = (
            "🤖 ATI CRYPTO BOT\n\n"
            f"Symbol: {SYMBOL}\n"
            f"Time: {now}\n"
            f"Price: {current}\n"
            f"Signal: {signal}\n\n"
            "MODE: PAPER / TEST\n"
            "REAL TRADING: DISABLED"
        )

        print(message)

        if signal in ("BUY", "SELL"):
            send_telegram(message)

    except Exception as e:
        print("BOT ERROR:", str(e))
        raise


if __name__ == "__main__":
    main()
