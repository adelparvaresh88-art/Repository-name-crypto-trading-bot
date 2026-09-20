import os
import json
import urllib.request
import urllib.parse

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ TELEGRAM SECRETS MISSING")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    try:
        request = urllib.request.Request(url, data=data)

        with urllib.request.urlopen(request, timeout=20) as response:
            result = response.read().decode()

        print("✅ TELEGRAM SENT")
        print(result)
        return True

    except Exception as error:
        print("❌ TELEGRAM ERROR:", error)
        return False


def get_btc_price():
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=bitcoin&vs_currencies=usd"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())

    return float(data["bitcoin"]["usd"])


def main():

    print("================================")
    print("⚡ ATI CRYPTO BOT V14")
    print("================================")

    # تست اولیه تلگرام
    send_telegram(
        "⚡ ATI CRYPTO BOT V14\n\n"
        "✅ BOT STARTED\n"
        "📡 Telegram connection OK\n"
        "⏳ Checking BTC..."
    )

    try:
        price = get_btc_price()

        # فعلاً فقط وضعیت بازار را اعلام می‌کنیم
        message = (
            "⚡ ATI CRYPTO BOT V14\n\n"
            f"₿ BTC: ${price:,.2f}\n"
            "⏱ Timeframe: 5m\n"
            "✅ MARKET DATA OK\n\n"
            "📊 SOURCE: COINGECKO\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

        print(message)
        send_telegram(message)

    except Exception as error:

        error_message = (
            "⚠️ ATI CRYPTO BOT V14\n\n"
            "✅ Telegram: OK\n"
            "❌ Market Data Error\n\n"
            f"ERROR:\n{str(error)}"
        )

        print(error_message)
        send_telegram(error_message)


if __name__ == "__main__":
    main()
