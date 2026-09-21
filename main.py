import os
import time
import hmac
import hashlib
import requests


API_KEY = os.getenv("TABDIL_API_KEY")
API_SECRET = os.getenv("TABDIL_API_SECRET")

print("================================")
print("ATI TABDEEL API TEST")
print("================================")

if not API_KEY:
    print("❌ TABDIL_API_KEY MISSING")
    raise SystemExit(1)

if not API_SECRET:
    print("❌ TABDIL_API_SECRET MISSING")
    raise SystemExit(1)

print("✅ API KEY: FOUND")
print("✅ API SECRET: FOUND")

timestamp = int(time.time() * 1000)

params = {
    "timestamp": timestamp
}

query_string = "&".join(
    f"{key}={value}" for key, value in params.items()
)

signature = hmac.new(
    API_SECRET.encode("utf-8"),
    query_string.encode("utf-8"),
    hashlib.sha256
).hexdigest()

params["signature"] = signature

headers = {
    "X-MBX-APIKEY": API_KEY
}

url = "https://api1.tabdeal.org/r/api/v1/account"

try:
    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=15
    )

    print("HTTP STATUS:", response.status_code)

    if response.status_code == 200:
        data = response.json()

        print("================================")
        print("✅ TABDEEL API CONNECTION: OK")
        print("✅ ACCOUNT ACCESS: OK")
        print("================================")

        print("canTrade:", data.get("canTrade"))
        print("accountType:", data.get("accountType"))

    else:
        print("================================")
        print("❌ TABDEEL API ERROR")
        print("================================")
        print(response.text)

except Exception as error:
    print("================================")
    print("❌ CONNECTION ERROR")
    print("================================")
    print(str(error))
    raise
