import urllib.request
import json
from datetime import datetime

URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

print("================================")
print("       ATI CRYPTO BOT")
print("================================")
print("Status: ONLINE")
print("Mode: TEST")
print("Trading: DISABLED")
print("Time:", datetime.now())

try:
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode())

    price = float(data["price"])

    print("BTC/USDT Price:", price)
    print("================================")
    print("Connection: OK")

except Exception as e:
    print("================================")
    print("ERROR TYPE:", type(e).__name__)
    print("ERROR DETAILS:", repr(e))
    print("================================")
