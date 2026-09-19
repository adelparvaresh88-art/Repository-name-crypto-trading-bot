import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SL_PERCENT = 0.6
TP_PERCENT = 1.2


def send_telegram(message):
    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is missing")
        return False

    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID is missing")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    try:
        request = urllib.request.Request(
            url,
            data=data,
            headers={"User-Agent": "ATI-CRYPTO-BOT"},
            method="POST"
        )

        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        print("TELEGRAM RESULT:", result)

        if result.get("ok"):
            print("TELEGRAM MESSAGE SENT")
            return True

        print("TELEGRAM SEND FAILED")
        return False

    except Exception as e:
        print("TELEGRAM ERROR:", e)
        return False


def get_btc_price():
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin&vs_currencies=usd"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    return float(data["bitcoin"]["usd"])


def calculate_signal(price):
    # فعلاً برای تست پایدار ربات
    # منطق اصلی BUY/SELL بعد از تأیید اجرای صحیح اضافه می‌شود.

    if price > 0:
        return "BUY"

    return "HOLD"


print("================================")
print("ATI CRYPTO BOT V12")
print("TIMEFRAME: 5m")
print("MODE: PAPER / TEST")
print("REAL TRADING: DISABLED")
print("================================")


try:
    price = get_btc_price()

    signal = calculate_signal(price)

    print("BTC PRICE:", price)
    print("SIGNAL:", signal)

    if signal == "BUY":

        stop_loss = price * (1 - SL_PERCENT / 100)
        take_profit = price * (1 + TP_PERCENT / 100)

        message = (
            "🟢 BUY SIGNAL\n\n"
            f"₿ BTC: ${price:,.2f}\n"
            "⏱ Timeframe: 5m\n\n"
            f"🎯 Entry: ${price:,.2f}\n"
            f"🛑 Stop Loss: ${stop_loss:,.2f}\n"
            f"💰 Take Profit: ${take_profit:,.2f}\n\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING: DISABLED"
        )

    else:

        message = (
            "⚪ ATI CRYPTO BOT\n\n"
            f"₿ BTC: ${price:,.2f}\n"
            "⏱ Timeframe: 5m\n"
            "⚪ SIGNAL: HOLD\n\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING: DISABLED"
        )

    send_telegram(message)

except Exception as e:

    print("BOT ERROR:", e)

    send_telegram(
        "⚠️ ATI BOT ERROR\n\n"
        f"{e}\n\n"
        "📊 MODE: PAPER / TEST"
    )


print("FINISHED")
