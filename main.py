import urllib.request
import json
from datetime import datetime

URL = "https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=5m&limit=30"

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
        candles = json.loads(response.read().decode())

    closes = [float(candle[4]) for candle in candles]

    print("--------------------------------")
    print("SYMBOL: BTCUSDT")
    print("TIMEFRAME: 5m")
    print("CANDLES:", len(closes))
    print("CURRENT PRICE:", closes[-1])
    print("PREVIOUS PRICE:", closes[-2])
    print("--------------------------------")
    print("CANDLE CONNECTION: OK")
    print("NO REAL TRADE")
    print("================================")

except Exception as e:
    print("--------------------------------")
    print("ERROR TYPE:", type(e).__name__)
    print("ERROR DETAILS:", str(e))
    print("--------------------------------")
