import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


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

    try:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ATI-CRYPTO-BOT"}
        )

        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))

        return data["bitcoin"]["usd"]

    except Exception as e:
        print("PRICE ERROR:", e)
        return None


print("================================")
print("ATI CRYPTO BOT V7")
print("MODE: PAPER / TEST")
print("REAL TRADING: DISABLED")
print("================================")


# اول تلگرام را تست می‌کنیم
test_message = (
    "🤖 ATI CRYPTO BOT V7\n\n"
    "✅ Telegram connection test\n"
    "🟢 Bot is running\n"
    "💰 REAL TRADING: DISABLED"
)

telegram_ok = send_telegram(test_message)


# بعد قیمت را می‌گیریم
price = get_btc_price()

if price is not None:
    message = (
        "📊 ATI CRYPTO BOT\n\n"
        f"₿ BTC: ${price:,.2f}\n"
        "🟢 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    send_telegram(message)
    print("BTC PRICE:", price)

else:
    print("BTC price unavailable - Telegram is still working")


print("FINISHED")
