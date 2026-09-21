import os
import time
import hmac
import hashlib
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

API_KEY = os.getenv("TABDIL_API_KEY")
API_SECRET = os.getenv("TABDIL_API_SECRET")

BASE_URL = "https://api1.tabdeal.org"


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": message},
        timeout=20
    )


def get_account():
    timestamp = int(time.time() * 1000)

    query = f"timestamp={timestamp}"

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    url = f"{BASE_URL}/r/api/v1/account"

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    params = {
        "timestamp": timestamp,
        "signature": signature
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=20
    )

    response.raise_for_status()
    return response.json()


def main():
    try:
        account = get_account()

        balances = account.get("balances", [])

        important = []

        for item in balances:
            free = float(item.get("free", 0))
            freeze = float(item.get("freeze", 0))

            if free > 0 or freeze > 0:
                important.append(
                    f"{item['asset']}: {free} آزاد / {freeze} فریز"
                )

        message = (
            "✅ ATI BOT - TABDEAL CONNECTION\n\n"
            "✅ Telegram: OK\n"
            "✅ Tabdil API: OK\n"
            f"📊 Balances found: {len(important)}\n\n"
        )

        if important:
            message += "\n".join(important[:15])
        else:
            message += "موجودی قابل نمایش پیدا نشد."

        message += "\n\n🚫 REAL TRADING DISABLED"

        send_telegram(message)

    except Exception as e:
        send_telegram(
            "❌ TABDEEL API ERROR\n\n"
            f"{str(e)}\n\n"
            "🚫 REAL TRADING DISABLED"
        )


if __name__ == "__main__":
    main()
