import requests

BASE_URL = "https://api1.tabdeal.org"

ENDPOINTS = [
    "/r/fapi/v1/exchangeInfo",
    "/r/fapi/v1/klines",
    "/fapi/v1/klines",
    "/r/fapi/v1/depth",
    "/r/fapi/v1/trades",
]

print("ATI TABDEAL FUTURES API CHECK")
print("=" * 45)

for endpoint in ENDPOINTS:
    try:
        response = requests.get(
            BASE_URL + endpoint,
            params={
                "symbol": "BTC_USDT",
                "interval": "5m",
                "limit": 3,
            },
            timeout=12,
        )

        print(f"\nEndpoint: {endpoint}")
        print(f"HTTP: {response.status_code}")
        print(response.text[:500])

    except requests.RequestException as exc:
        print(f"\nEndpoint: {endpoint}")
        print(f"ERROR: {exc}")

print("\nCHECK FINISHED")
