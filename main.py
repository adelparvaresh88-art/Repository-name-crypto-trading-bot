import os
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram(message):
    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is missing")
        return False

    if not CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID is missing")
        return False

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print("Telegram HTTP:", response.status_code)
        print("Telegram response:", response.text)

        if response.ok:
            print("✅ TELEGRAM MESSAGE SENT")
            return True
        else:
            print("❌ TELEGRAM SEND FAILED")
            return False

    except Exception as e:
        print("❌ TELEGRAM ERROR:", e)
        return False


def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    message = (
        "⚡ ATI CRYPTO BOT\n\n"
        "🧪 TELEGRAM CONNECTION TEST\n"
        "✅ Bot is running\n"
        "✅ GitHub Actions reached main.py\n\n"
        f"🕐 Time: {now}\n\n"
        "📩 If you received this message, Telegram is OK."
    )

    send_telegram(message)


if __name__ == "__main__":
    main()
