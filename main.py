import urllib.request
import json
from datetime import datetime

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 50

URL = (
    f"https://api.binance.com/api/v3/klines"
    f"?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}"
)

print("================================")
print("        ATI CRYPTO BOT")
print("================================")
print("MODE: PAPER / TEST")
print("TRADING: DISABLED")
print("TIME:", datetime.now())
print("--------------------------------")

try:
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        candles = json.loads(response.read().decode())

    data = []

    for c in candles:
        data.append({
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4])
        })

    # آخرین کندل بسته‌شده
    c = data[-2]
    p1 = data[-3]
    p2 = data[-4]

    price = c["close"]

    # -----------------------------
    # تشخیص کف اصلی
    # -----------------------------
    main_bottom = (
        p2["low"] > p1["low"]
        and c["low"] > p1["low"]
        and c["close"] > c["open"]
    )

    # -----------------------------
    # تشخیص سقف اصلی
    # -----------------------------
    main_top = (
        p2["high"] < p1["high"]
        and c["high"] < p1["high"]
        and c["close"] < c["open"]
    )

    signal = "NO SIGNAL"
    stop_loss = None
    take_profit = None

    # BUY بعد از تشکیل کف و تأیید کندل صعودی
    if main_bottom:
        signal = "BUY"

        stop_loss = p1["low"]
        risk = price - stop_loss

        if risk > 0:
            take_profit = price + (risk * 2)

    # SELL بعد از تشکیل سقف و تأیید کندل نزولی
    elif main_top:
        signal = "SELL"

        stop_loss = p1["high"]
        risk = stop_loss - price

        if risk > 0:
            take_profit = price - (risk * 2)

    print("SYMBOL:", SYMBOL)
    print("TIMEFRAME:", INTERVAL)
    print("CANDLES:", len(data))
    print("CURRENT CLOSED PRICE:", price)

    print("--------------------------------")
    print("SIGNAL:", signal)

    if signal != "NO SIGNAL":
        print("ENTRY:", price)
        print("STOP LOSS:", stop_loss)
        print("TAKE PROFIT:", take_profit)

    print("--------------------------------")
    print("CANDLE CONNECTION: OK")
    print("REAL TRADING: DISABLED")
    print("================================")

except Exception as e:
    print("--------------------------------")
    print("ERROR TYPE:", type(e).__name__)
    print("ERROR DETAILS:", str(e))
    print("================================")
