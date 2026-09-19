import os
import json
import urllib.request
import urllib.parse
import traceback

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        return response.read().decode()


def get_price():
    url = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        data = json.loads(response.read().decode())

    return float(data["price"])


def get_candles():
    url = (
        "https://api.binance.com/api/v3/klines"
        "?symbol=BTCUSDT&interval=5m&limit=30"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        return json.loads(response.read().decode())


def main():
    print("ATI CRYPTO BOT STARTED")

    price = get_price()
    candles = get_candles()

    closes = [float(c[4]) for c in candles]

    current = closes[-2]
    previous = closes[-3]

    short_avg = sum(closes[-7:-2]) / 5
    long_avg = sum(closes[-17:-2]) / 15

    if short_avg > long_avg and current > previous:
        signal = "BUY"
        icon = "🟢"

    elif short_avg < long_avg and current < previous:
        signal = "SELL"
        icon = "🔴"

    else:
        signal = "HOLD"
        icon = "⚪"

    message = (
        "⚡ ATI CRYPTO BOT\n\n"
        f"₿ BTC: ${price:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        f"{icon} SIGNAL: {signal}\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    print(message)
    send_telegram(message)


try:
    main()

except Exception as error:
    error_text = traceback.format_exc()

    print("================================")
    print("BOT ERROR")
    print(error_text)
    print("================================")

    try:
        send_telegram(
            "⚠️ ATI CRYPTO BOT\n\n"
            "خطای دقیق:\n\n"
            + str(error)
        )
    except Exception as telegram_error:
        print("Telegram error:", telegram_error)
