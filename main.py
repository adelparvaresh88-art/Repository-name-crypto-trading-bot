import os
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    r = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=15
    )

    r.raise_for_status()


def get_trades():
    url = f"{BASE_URL}/v1/trade/market-trades"

    params = {
        "symbol": "BTCUSDT",
        "limit": 1000
    }

    response = requests.get(
        url,
        params=params,
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        data = data.get("data", [])

    return data


def main():

    trades = get_trades()

    print(f"Trades received: {len(trades)}")

    if not trades:
        raise Exception("No trades received")

    print("✅ Tabdeal Market API: OK")

    message = (
        "⚡ ATI CRYPTO BOT - STAGE 6 TEST\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ MARKET DATA OK\n\n"
        f"📊 Trades received: {len(trades)}\n\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING DISABLED"
    )

    print(message)

    if BOT_TOKEN and CHAT_ID:
        send_telegram(message)
        print("✅ Telegram: OK")
    else:
        print("❌ Telegram secrets missing")


if __name__ == "__main__":
    main()
