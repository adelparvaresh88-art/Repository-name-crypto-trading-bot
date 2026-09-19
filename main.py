import os
import json
import urllib.request
from datetime import datetime, timezone

# =========================
# SETTINGS
# =========================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 30

# =========================
# TELEGRAM
# =========================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ TELEGRAM SECRETS ARE MISSING")
        return False

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

        print("✅ TELEGRAM:", result)
        return True

    except Exception as error:
        print("❌ TELEGRAM ERROR:", str(error))
        return False


# =========================
# BINANCE PRICE
# =========================

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


# =========================
# SIGNAL
# =========================

def get_signal(candles):
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

    return signal, current, short_avg, long_avg


# =========================
# MAIN
# =========================

def main():

    print("================================")
    print("ATI CRYPTO BOT")
    print("MODE: PAPER / TEST")
    print("REAL TRADING: DISABLED")
    print("================================")

    candles = get_candles()

    signal, current, short_avg, long_avg = get_signal(candles)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        "₿ BTC: $" + f"{current:,.2f}" + "\n"
        "⏱ Timeframe: 5m\n\n"
        "📊 SIGNAL: " + signal + "\n\n"
        "📈 Short Avg: $" + f"{short_avg:,.2f}" + "\n"
        "📉 Long Avg: $" + f"{long_avg:,.2f}" + "\n\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED\n\n"
        "🕐 " + now
    )

    print(message)

    send_telegram(message)


# =========================
# SAFE START
# =========================

if __name__ == "__main__":
    try:
        main()

    except Exception as error:
        print("================================")
        print("❌ BOT ERROR:")
        print(str(error))
        print("================================")
        raise
