import urllib.request
import json
from datetime import datetime

URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

print("================================")
print("       ATI CRYPTO BOT")
print("================================")
print("MODE: PAPER / TEST")
print("TRADING: DISABLED")
print("TIME:", datetime.now())

try:
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        data = json.loads(response.read().decode())

    price = float(data["price"])

    print("--------------------------------")
    print("SYMBOL: BTCUSDT")
    print("CURRENT PRICE:", price)
    print("--------------------------------")
    print("PRICE CONNECTION: OK")
    print("NO REAL TRADE")
    print("================================")

except Exception as e:
    print("--------------------------------")
    print("ERROR TYPE:", type(e).__name__)
    print("ERROR DETAILS:", str(e))
    print("--------------------------------")
