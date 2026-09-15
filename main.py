import os
import json
import urllib.request
import urllib.error
from datetime import datetime

SYMBOL = "BTCUSDT"
LIMIT = 30
INTERVAL = "5m"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_price_data():
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}"
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))

        if not data:
            raise Exception("No price data received")

        return data

    except urllib.error.HTTPError as e:
        raise Exception(f"Binance HTTP Error {e.code}")

    except Exception as e:
        raise Exception(f"Price data error: {e}")


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram is not configured.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = response.read().decode("utf-8")
            print("Telegram:", result)

    except Exception as e:
        print("Telegram error:", e)


def main():
    print("=" * 40)
    print("ATI CRYPTO BOT")
    print("=" * 40)
    print("MODE: PAPER / TEST")
    print("TRADING: DISABLED")
    print("TIME:", datetime.utcnow())

    candles = get_price_data()

    closes = [float(candle[4]) for candle in candles]

    current_price = closes[-1]
    previous_price = closes[-2]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-15:]) / 15

    if short_avg > long_avg and current_price > previous_price:
        signal = "BUY"

    elif short_avg < long_avg and current_price < previous_price:
        signal = "SELL"

    else:
        signal = "HOLD"

    message = (
        f"ATI CRYPTO BOT\n\n"
        f"Symbol: {SYMBOL}\n"
        f"Price: {current_price}\n"
        f"Signal: {signal}\n"
        f"Mode: PAPER / TEST\n"
        f"Trading: DISABLED"
    )

    print(message)

    send_telegram(message)


if __name__ == "__main__":
    main()
