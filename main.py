import os
import json
import urllib.request
import urllib.parse
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
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is missing")
        return

    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID is missing")
        return

    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = response.read().decode("utf-8")

        print("TELEGRAM OK")
        print(result)

    except Exception as error:
        print("TELEGRAM ERROR:")
        print(str(error))


# =========================
# GET BTC DATA
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
        headers={
            "User-Agent": "ATI-CRYPTO-BOT"
        }
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = response.read().decode("utf-8")

    return json.loads(data)


# =========================
# SIGNAL
# =========================

def calculate_signal(candles):

    closes = []

    for candle in candles:
        closes.append(float(candle[4]))

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

    return signal, current_price, short_average, long_average


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

    signal, price, short_average, long_average = calculate_signal(candles)

    now = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        "₿ BTC: $" + f"{price:,.2f}" + "\n"
        "⏱ Timeframe: 5m\n\n"
        "📊 SIGNAL: " + signal + "\n\n"
        "📈 Short Avg: $" + f"{short_average:,.2f}" + "\n"
        "📉 Long Avg: $" + f"{long_average:,.2f}" + "\n\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED\n\n"
        "🕐 " + now
    )

    print(message)

    send_telegram(message)


# =========================
# START
# =========================

if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("================================")
        print("BOT ERROR:")
        print(str(error))
        print("================================")

        raise
