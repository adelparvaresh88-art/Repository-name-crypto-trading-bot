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

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-Crypto-Bot/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read().decode("utf-8")

    return json.loads(data)


def send_telegram(message):
    print("Checking Telegram settings...")

    if not BOT_TOKEN:
        print("❌ ERROR: TELEGRAM_BOT_TOKEN is missing.")
        return False

    if not CHAT_ID:
        print("❌ ERROR: TELEGRAM_CHAT_ID is missing.")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "ATI-Crypto-Bot/1.0"
        }
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        if result.get("ok") is True:
            print("================================")
            print("✅ TELEGRAM MESSAGE SENT")
            print("================================")
            return True

        print("================================")
        print("❌ TELEGRAM API ERROR")
        print(result)
        print("================================")
        return False

    except Exception as error:
        print("================================")
        print("❌ TELEGRAM SEND ERROR")
        print(str(error))
        print("================================")
        return False


def main():
    print("================================")
    print("🤖 ATI CRYPTO BOT")
    print("================================")
    print("MARKET: Binance")
    print("TIMEFRAME: 5m")
    print("REAL TRADING: DISABLED")
    print("--------------------------------")

    candles = get_candles()

    if len(candles) < 15:
        raise Exception("Not enough candle data.")

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
    print("--------------------------------")

    send_telegram(message)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print("================================")
        print("❌ BOT ERROR")
        print(str(error))
        print("================================")
        raise
