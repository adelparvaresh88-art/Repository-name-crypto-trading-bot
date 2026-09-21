import os
import requests

API_KEY = os.getenv("TABDIL_API_KEY")
API_SECRET = os.getenv("TABDIL_API_SECRET")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("=== ATI TABDIL CONNECTION TEST ===")

print("TABDIL_API_KEY:", "OK" if API_KEY else "MISSING")
print("TABDIL_API_SECRET:", "OK" if API_SECRET else "MISSING")
print("TELEGRAM_BOT_TOKEN:", "OK" if TOKEN else "MISSING")
print("TELEGRAM_CHAT_ID:", "OK" if CHAT_ID else "MISSING")

if TOKEN and CHAT_ID:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": "✅ ATI BOT\n\nTABDIL SECRETS TEST STARTED"
    }

    r = requests.post(url, data=data, timeout=20)
    print("Telegram:", r.status_code)
    print(r.text)

print("=== TEST FINISHED ===")
