import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SYMBOL = "BTCUSDT"


def get_price():
    # منبع اول: Binance
    try:
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={SYMBOL}"
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())

        return float(data["price"])

    except Exception as e:
        print("Binance failed:", str(e))

    # منبع دوم: CoinGecko
    try:
        url = (
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin&vs_currencies=usd"
        )

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0"}
        )

        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())

        return float(data["bitcoin"]["usd"])

    except Exception as e:
        print("CoinGecko failed:", str(e))

    return None


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets are missing.")
        return

    url = (
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        f"?chat_id={urllib.parse.quote(CHAT_ID)}"
        f"&text={urllib.parse.quote(message)}"
    )

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(req, timeout=15) as response:
        print(response.read().decode())


def main():
    print("================================")
    print("ATI CRYPTO BOT")
    print("================================")

    price = get_price()

    if price is None:
        message = (
            "⚠️ ATI CRYPTO BOT\n\n"
            "دریافت قیمت با مشکل مواجه شد.\n"
            "معامله واقعی انجام نشد."
        )
        send_telegram(message)
        return

    print("BTC PRICE:", price)

    message = (
        "🟢 ATI CRYPTO BOT\n\n"
        f"₿ BTC: ${price:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        "⚪ SIGNAL: HOLD\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    send_telegram(message)


if __name__ == "__main__":
    main()
