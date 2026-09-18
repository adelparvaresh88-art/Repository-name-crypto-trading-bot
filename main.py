import os
import json
import urllib.request
import urllib.parse

print("================================")
print("ATI CRYPTO BOT - START")
print("================================")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("BOT TOKEN:", "OK" if BOT_TOKEN else "MISSING")
print("CHAT ID:", "OK" if CHAT_ID else "MISSING")


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

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        print("TELEGRAM RESPONSE:", result)

        if result.get("ok") is True:
            print("SUCCESS: Telegram message sent")
            return True

        print("ERROR: Telegram rejected the message")
        return False

    except Exception as e:
        print("ERROR: Telegram connection failed")
        print("DETAIL:", str(e))
        return False


def get_btc_price():
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin&vs_currencies=usd"
    )

    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))

        return data["bitcoin"]["usd"]

    except Exception as e:
        print("ERROR: BTC price failed")
        print("DETAIL:", str(e))
        return None


price = get_btc_price()

if price is not None:
    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        "✅ Bot is working\n"
        f"💰 BTC Price: ${price}\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 TRADING: DISABLED"
    )
else:
    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        "⚠️ Telegram test message\n"
        "BTC price could not be received."
    )

send_telegram(message)

print("================================")
print("ATI CRYPTO BOT - FINISHED")
print("================================")
