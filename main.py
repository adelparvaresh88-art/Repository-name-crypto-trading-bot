import os
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TABDIL_API_KEY = os.getenv("TABDIL_API_KEY")
TABDIL_API_SECRET = os.getenv("TABDIL_API_SECRET")


def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": CHAT_ID,
        "text": message
    }, timeout=15)


def main():
    if not TABDIL_API_KEY or not TABDIL_API_SECRET:
        send_telegram(
            "❌ TABDIL CONNECTION ERROR\n\n"
            "API Key یا API Secret پیدا نشد."
        )
        return

    # فقط تست وجود کلیدها؛ هیچ سفارش یا معامله‌ای ارسال نمی‌شود.
    send_telegram(
        "✅ ATI BOT TEST\n\n"
        "Telegram connection OK\n"
        "✅ Tabdil API keys found\n"
        "🚫 REAL TRADING DISABLED"
    )


if __name__ == "__main__":
    main()
