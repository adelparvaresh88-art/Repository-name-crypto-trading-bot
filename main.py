import os
import json
import urllib.request
import urllib.parse
import traceback

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Risk settings
SL_PERCENT = 0.50
TP_PERCENT = 1.00


def get_data():
    url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=5"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode())

    if data.get("error"):
        raise Exception(str(data["error"]))

    result = data["result"]
    pair_key = [key for key in result.keys() if key != "last"][0]
    candles = result[pair_key]

    if len(candles) < 20:
        raise Exception("داده کافی دریافت نشد.")

    closes = [float(candle[4]) for candle in candles]

    return closes


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        raise Exception("Telegram secrets تنظیم نشده.")

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode()


def calculate_signal(closes):
    current = closes[-1]
    previous = closes[-2]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-15:]) / 15

    if short_avg > long_avg and current > previous:
        return "BUY"

    if short_avg < long_avg and current < previous:
        return "SELL"

    return "HOLD"


def calculate_levels(price, signal):
    if signal == "BUY":
        sl = price * (1 - SL_PERCENT / 100)
        tp = price * (1 + TP_PERCENT / 100)

    elif signal == "SELL":
        sl = price * (1 + SL_PERCENT / 100)
        tp = price * (1 - TP_PERCENT / 100)

    else:
        sl = None
        tp = None

    return sl, tp


def main():
    print("ATI CRYPTO BOT V4 STARTED")

    closes = get_data()

    price = closes[-1]
    signal = calculate_signal(closes)

    sl, tp = calculate_levels(price, signal)

    if signal == "BUY":
        icon = "🟢"

    elif signal == "SELL":
        icon = "🔴"

    else:
        icon = "⚪"

    message = (
        "⚡ ATI CRYPTO BOT V4\n\n"
        f"₿ BTC: ${price:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        f"{icon} SIGNAL: {signal}\n"
    )

    if signal != "HOLD":
        message += (
            f"\n💰 Entry: ${price:,.2f}\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n"
        )

    message += (
        "\n📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    print(message)
    send_telegram(message)


try:
    main()

except Exception as error:
    print("BOT ERROR:")
    print(traceback.format_exc())

    try:
        send_telegram(
            "⚠️ ATI CRYPTO BOT\n\n"
            "خطای دقیق:\n\n"
            + str(error)
        )
    except Exception:
        pass
