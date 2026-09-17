import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def get_btc_price():
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin&vs_currencies=usd"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-Crypto-Bot/4.0"}
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        data = json.loads(response.read().decode("utf-8"))

    return float(data["bitcoin"]["usd"])


def send_telegram(message):
    print("Checking Telegram settings...")

    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN is missing")
        return False

    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID is missing")
        return False

    print("Telegram token: FOUND")
    print("Telegram chat ID: FOUND")

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

    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            result = json.loads(response.read().decode("utf-8"))

        print("Telegram API response:", result)

        if result.get("ok") is True:
            print("SUCCESS: TELEGRAM MESSAGE SENT")
            return True

        print("ERROR: TELEGRAM REJECTED MESSAGE")
        return False

    except Exception as e:
        print("ERROR: TELEGRAM CONNECTION FAILED")
        print(repr(e))
        return False


def main():
    print("================================")
    print("ATI CRYPTO BOT V4")
    print("MODE: PAPER / TEST")
    print("TRADING: DISABLED")
    print("================================")

    try:
        price = get_btc_price()

        now = datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        )

        message = (
            "🤖 ATI CRYPTO BOT\n\n"
            "MODE: PAPER / TEST\n"
            "TRADING: DISABLED\n\n"
            f"₿ BTC: ${price:,.2f}\n"
            f"🕐 {now}\n\n"
            "✅ Market connection OK"
        )

        print("BTC price:", price)
        print("Sending Telegram message...")

        success = send_telegram(message)

        if success:
            print("================================")
            print("BOT FINISHED SUCCESSFULLY")
            print("================================")
        else:
            print("BOT ERROR: Telegram message was NOT sent")
            raise SystemExit(1)

    except Exception as e:
        print("BOT ERROR:")
        print(repr(e))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
