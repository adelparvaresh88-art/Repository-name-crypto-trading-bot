import urllib.request
import json
from datetime import datetime

SYMBOL = "BTCUSDT"
LIMIT = 30

URL = (
    "https://api.binance.com/api/v3/klines"
    f"?symbol={SYMBOL}&interval=5m&limit={LIMIT}"
)

print("================================")
print("       ATI CRYPTO BOT")
print("================================")
print("Mode: PAPER / TEST")
print("Trading: DISABLED")
print("Time:", datetime.now())

try:
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        candles = json.loads(response.read().decode())

    closes = [float(candle[4]) for candle in candles]

    current = closes[-1]
    previous = closes[-2]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-15:]) / 15

    if short_avg > long_avg and current > previous:
        signal = "BUY"
    elif short_avg < long_avg and current < previous:
        signal = "SELL"
    else:
        signal = "HOLD"

    print("--------------------------------")
    print("Symbol:", SYMBOL)
    print("Timeframe: 5m")
    print("Current Price:", current)
    print("5-Candle Average:", round(short_avg, 2))
    print("15-Candle Average:", round(long_avg, 2))
    print("--------------------------------")
    print("SIGNAL:", signal)
    print("--------------------------------")
    print("No real trade was placed.")
    print("================================")

except Exception as e:
    print("================================")
    print("ERROR TYPE:", type(e).__name__)
    print("ERROR DETAILS:", repr(e))
    print("================================")
