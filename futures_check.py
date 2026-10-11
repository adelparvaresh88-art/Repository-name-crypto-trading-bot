import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone

BASE_URL = "https://api1.tabdeal.org"

API_KEY = os.getenv("TABDIL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDIL_API_SECRET", "").strip()

print("ATI FUTURES CONNECTION CHECK")
print("=" * 35)
print("Time:", datetime.now(timezone.utc).isoformat())
print("API Key:", "Present" if API_KEY else "Missing")
print("API Secret:", "Present" if API_SECRET else "Missing")

# Test public API only; no orders are placed.
try:
    response = requests.get(
        BASE_URL + "/r/api/v1/time",
        timeout=15
    )
    print("Server time HTTP:", response.status_code)
    print("Server response:", response.text[:500])
except Exception as exc:
    print("Server time error:", str(exc))

print("\nREAL ORDERS: DISABLED")
print("No orders will be submitted.")
print("This test does not verify Futures trading access.")