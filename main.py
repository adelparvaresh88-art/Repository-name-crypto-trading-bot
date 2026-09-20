import os
import urllib.request
import urllib.parse

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Telegram secrets are missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    try:
        request = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(request, timeout=20) as response:
            result = response.read().decode()
            print("✅ Telegram:", result)
    except Exception as error:
        print("❌ Telegram ERROR:", error)


def main():
    print("================================")
    print("⚡ ATI CRYPTO BOT")
    print("📡 TELEGRAM TEST")
    print("================================")

    send_telegram(
        "⚡ ATI CRYPTO BOT\n\n"
        "✅ Telegram connection is working!\n"
        "🤖 Bot is running."
    )


if __name__ == "__main__":
    main()
