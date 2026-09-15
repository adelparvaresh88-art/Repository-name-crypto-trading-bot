import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 30

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def get_klines():
    url = (
        f"https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}"
    )

    with urllib.request.urlopen(url, timeout=15) as response:
        return json.loads(response.read().decode())


def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings are missing.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }).encode()

    with urllib.request.urlopen(url, data=data, timeout=15) as response:
        print("Telegram:", response.read().decode())


def main():
    candles = get_klines()

    closes = [float(candle[4]) for candle in candles]

    current = closes[-1]
    previous = closes[-2]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-15:]) / 15

    if short_avg > long_avg and current > previous:
        signal = "🟢 BUY"
    elif short_avg < long_avg and current < previous:
        signal = "🔴 SELL"
    else:
        signal = "⚪ HOLD"

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    message = f"""🤖 ATI CRYPTO BOT

🪙 {SYMBOL}
⏱ Timeframe: {INTERVAL}

💰 Price: {current:.4f}

📊 Signal: {signal}

📈 Short Avg: {short_avg:.4f}
📉 Long Avg: {long_avg:.4f}

🕐 {now}

⚠️ PAPER / TEST MODE
Trading is DISABLED.
"""

    print(message)
    send_telegram(message)


if __name__ == "__main__":
    main()
