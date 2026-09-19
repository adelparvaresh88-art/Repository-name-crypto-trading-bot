import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
INTERVAL = "5m"


def get_candles():
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit=30"
    )

    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets are missing.")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        print("Telegram message sent.")


def main():
    print("ATI CRYPTO BOT")
    print("REAL MARKET SIGNAL")
    print("-------------------------")

    candles = get_candles()

    closes = [float(candle[4]) for candle in candles]

    current = closes[-1]
    previous = closes[-2]

    short_average = sum(closes[-5:]) / 5
    long_average = sum(closes[-15:]) / 15

    if short_average > long_average and current > previous:
        signal = "🟢 BUY"
    elif short_average < long_average and current < previous:
        signal = "🔴 SELL"
    else:
        signal = "⚪ HOLD"

    time_now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        f"₿ BTC: ${current:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        f"📢 SIGNAL: {signal}\n\n"
        f"🕐 {time_now}\n\n"
        "📊 MARKET: REAL DATA\n"
        "🚫 REAL TRADING: DISABLED"
    )

    print(message)

    send_telegram(message)


if __name__ == "__main__":
    main()
