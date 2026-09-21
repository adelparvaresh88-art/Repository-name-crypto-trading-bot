import os
import requests

print("=== ATI BOT TEST ===")

names = [
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TABDIL_API_KEY",
    "TABDIL_API_SECRET",
]

for name in names:
    value = os.getenv(name)
    print(name, "OK" if value else "MISSING")

token = os.getenv("TELEGRAM_BOT_TOKEN")
chat_id = os.getenv("TELEGRAM_CHAT_ID")

if not token or not chat_id:
    raise Exception("Telegram Secrets are missing")

url = f"https://api.telegram.org/bot{token}/sendMessage"

response = requests.post(
    url,
    data={
        "chat_id": chat_id,
        "text": "✅ ATI BOT TEST\nTelegram connection OK"
    },
    timeout=20
)

print("Telegram HTTP:", response.status_code)
print(response.text)

if response.status_code != 200:
    raise Exception("Telegram connection failed")

print("=== TEST FINISHED ===")
