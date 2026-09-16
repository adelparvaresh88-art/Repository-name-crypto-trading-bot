import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

SYMBOL = "BTCUSDT"
COINGECKO_ID = "bitcoin"
LIMIT = 30

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_btc_price():
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin&vs_currencies=usd"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-Crypto-Bot/2.0"}
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))

    return float(data["bitcoin"]["usd"])


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("TELEGRAM SETTINGS MISSING")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))

    if result.get("ok"):
        print("TELEGRAM MESSAGE SENT")
        return True

    print("TELEGRAM ERROR:", result)
    return False


def main():
    print("================================")
    print("ATI CRYPTO BOT V3")
    print("MODE: PAPER / TEST")
    print("TRADING: DISABLED")
    print("================================")

    try:
        price = get_btc_price()

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        message = (
            "🤖 ATI CRYPTO BOT\n\n"
            "MODE: PAPER / TEST\n"
            "TRADING: DISABLED\n\n"
            f"₿ BTC: ${price:,.2f}\n"
            f"🕐 {now}\n\n"
            "✅ Market connection OK"
        )

        print(message)

        send_telegram(message)

    except Exception as e:
        print("BOT ERROR:", repr(e))
        print("Bot finished safely.")


if __name__ == "__main__":
    main()