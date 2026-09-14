import urllib.request
import json
from datetime import datetime

URL = "https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT"

try:
    with urllib.request.urlopen(URL, timeout=10) as response:
        data = json.loads(response.read().decode())

    price = float(data["price"])

    print("================================")
    print("       ATI CRYPTO BOT")
    print("================================")
    print("Status: ONLINE")
    print("Mode: TEST")
    print("BTC/USDT Price:", price)
    print("Time:", datetime.now())
    print("Trading: DISABLED")
    print("================================")

except Exception as e:
    print("ERROR:", e)
