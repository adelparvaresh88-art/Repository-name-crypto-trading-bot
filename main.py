import os
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets are missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()


def get_depth():
    url = f"{BASE_URL}/v1/depth"

    params = {
        "symbol": "BTCIRT",
        "limit": 500
    }

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()
    return response.json()


def test_market():
    data = get_depth()

    if not data:
        raise Exception("Empty market data")

    return data


def main():
    print("================================")
    print("ATI BOT - TABDEEL MARKET")
    print("================================")

    try:
        if not BOT_TOKEN:
            raise Exception("TELEGRAM_BOT_TOKEN is missing")

        if not CHAT_ID:
            raise Exception("TELEGRAM_CHAT_ID is missing")

        # تست بازار
        market = test_market()

        print("Telegram: READY")
        print("Tabdeal Market API: OK")
        print("Depth data: OK")

        message = (
            "✅ ATI BOT - TABDEEL\n\n"
            "✅ Telegram: OK\n"
            "✅ Tabdeal Market API: OK\n"
            "📊 BTCIRT order book: OK\n\n"
            "🧪 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

        send_telegram(message)

        print("Telegram message sent successfully")

    except requests.exceptions.HTTPError as e:
        print("HTTP ERROR:")
        print(e)

        try:
            send_telegram(
                "⚠️ ATI BOT ERROR\n\n"
                f"HTTPError: {e}\n\n"
                "🚫 REAL TRADING DISABLED"
            )
        except Exception:
            pass

    except Exception as e:
        print("BOT ERROR:")
        print(e)

        try:
            send_telegram(
                "⚠️ ATI BOT ERROR\n\n"
                f"{type(e).__name__}: {e}\n\n"
                "🚫 REAL TRADING DISABLED"
            )
        except Exception:
            pass


if __name__ == "__main__":
    main()
