import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    try:
        request = urllib.request.Request(
            url,
            data=data,
            method="POST"
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))

        return result.get("ok") is True

    except Exception as e:
        print("TELEGRAM ERROR:", str(e))
        return False


def get_btc_price():
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin&vs_currencies=usd"
    )

    try:
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "ATI-Crypto-Bot/1.0"
            }
        )

        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))

        return data["bitcoin"]["usd"], None

    except Exception as e:
        return None, str(e)


print("ATI CRYPTO BOT STARTED")

price, error = get_btc_price()

if price is not None:

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        f"💰 BTC: ${price:,.2f}\n\n"
        "🟢 BUY / 🔴 SELL / ⚪ HOLD\n"
        "فعلاً حالت آزمایشی است\n"
        "🚫 معامله واقعی خاموش است\n\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

else:

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        "❌ خطا در دریافت قیمت BTC\n\n"
        f"🔎 ERROR:\n{error}\n\n"
        "🚫 معامله واقعی خاموش است"
    )

if not send_telegram(message):
    raise SystemExit(1)

print("ATI CRYPTO BOT FINISHED")
