import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(
        url,
        data={"chat_id": CHAT_ID, "text": message},
        timeout=20
    )


def get_market_price():
    url = f"{BASE_URL}/r/api/v1/depth"

    params = {
        "symbol": "BTCIRT",
        "limit": 1
    }

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()
    data = response.json()

    bid = float(data["bids"][0][0])
    ask = float(data["asks"][0][0])

    return bid, ask


def main():
    try:
        bid, ask = get_market_price()

        message = (
            "✅ ATI BOT - TABDEAL MARKET TEST\n\n"
            "✅ Telegram: OK\n"
            "✅ Tabdil Market API: OK\n\n"
            f"🟢 BTCIRT BID: {bid:,.0f}\n"
            f"🔴 BTCIRT ASK: {ask:,.0f}\n\n"
            "🚫 REAL TRADING DISABLED"
        )

        send_telegram(message)

    except Exception as e:
        send_telegram(
            "❌ TABDEAL MARKET ERROR\n\n"
            f"{str(e)}\n\n"
            "🚫 REAL TRADING DISABLED"
        )


if __name__ == "__main__":
    main()
