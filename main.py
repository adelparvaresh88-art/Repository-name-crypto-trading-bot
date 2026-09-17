import os
import json
import urllib.request
from datetime import datetime, timezone


BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_btc_price():
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"

    with urllib.request.urlopen(url, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    return float(data["bitcoin"]["usd"])


def send_telegram(message):
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    if not CHAT_ID:
        raise RuntimeError("TELEGRAM_CHAT_ID is missing")

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": CHAT_ID,
        "text": message
    }

    data = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = json.loads(response.read().decode("utf-8"))

    if not result.get("ok"):
        raise RuntimeError(f"Telegram error: {result}")


def main():
    print("=" * 40)
    print("ATI CRYPTO BOT")
    print("MODE: PAPER / TEST")
    print("REAL TRADING: DISABLED")
    print("=" * 40)

    price = get_btc_price()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    message = (
        "🤖 ATI CRYPTO BOT\n\n"
        f"₿ BTC Price: ${price:,.2f}\n"
        f"🕐 Time: {now}\n\n"
        "📊 Status: TEST MODE\n"
        "💰 Real trading: OFF"
    )

    print(message)

    send_telegram(message)

    print("✅ Telegram message sent successfully")


if __name__ == "__main__":
    main()
