import os
import json
import urllib.request
import urllib.parse

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_btc_price():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"

    with urllib.request.urlopen(url, timeout=15) as response:
        data = json.loads(response.read().decode())

    return data["bitcoin"]["usd"]


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("ERROR: Telegram secrets are missing")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    params = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(url, data=params, method="POST")

    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode())

    if result.get("ok"):
        return True

    print("Telegram error:", result)
    return False


print("================================")
print("ATI CRYPTO BOT")
print("MODE: PAPER / TEST")
print("TRADING: DISABLED")
print("================================")

try:
    price = get_btc_price()

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        "✅ Bot is working\n"
        "💰 BTC Price: $" + str(price) + "\n"
        "🟢 Trading: DISABLED\n"
        "🧪 Mode: PAPER / TEST"
    )

    print(message)

    if send_telegram(message):
        print("✅ Telegram message sent successfully")
    else:
        print("❌ Telegram message was not sent")

except Exception as e:
    print("ERROR:", str(e))
