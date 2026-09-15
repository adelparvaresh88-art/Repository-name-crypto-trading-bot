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

output = []


def log(text=""):
    print(text)
    output.append(str(text))


log("================================")
log("        ATI CRYPTO BOT")
log("================================")
log("MODE: PAPER / TEST")
log("TRADING: DISABLED")
log("TIME: " + str(datetime.now()))
log("--------------------------------")

try:
    request = urllib.request.Request(
        URL,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=10) as response:
        candles = json.loads(response.read().decode())

    data = []

    for candle in candles:
        data.append({
            "open": float(candle[1]),
            "high": float(candle[2]),
            "low": float(candle[3]),
            "close": float(candle[4])
        })

    # آخرین کندل بسته‌شده
    c = data[-2]
    p1 = data[-3]
    p2 = data[-4]

    price = c["close"]

    # -----------------------------
    # تشخیص کف
    # -----------------------------
    main_bottom = (
        p2["low"] > p1["low"]
        and c["low"] > p1["low"]
        and c["close"] > c["open"]
    )

    # -----------------------------
    # تشخیص سقف
    # -----------------------------
    main_top = (
        p2["high"] < p1["high"]
        and c["high"] < p1["high"]
        and c["close"] < c["open"]
    )

    signal = "NO SIGNAL"
    stop_loss = None
    take_profit = None

    # -----------------------------
    # BUY
    # -----------------------------
    if main_bottom:
        signal = "BUY"

        stop_loss = p1["low"]
        risk = price - stop_loss

        if risk > 0:
            take_profit = price + (risk * 2)

    # -----------------------------
    # SELL
    # -----------------------------
    elif main_top:
        signal = "SELL"

        stop_loss = p1["high"]
        risk = stop_loss - price

        if risk > 0:
            take_profit = price - (risk * 2)

    log("SYMBOL: " + SYMBOL)
    log("TIMEFRAME: " + INTERVAL)
    log("CANDLES: " + str(len(data)))
    log("CURRENT CLOSED PRICE: " + str(price))
    log("--------------------------------")
    log("SIGNAL: " + signal)

    if signal != "NO SIGNAL":
        log("ENTRY: " + str(price))
        log("STOP LOSS: " + str(stop_loss))
        log("TAKE PROFIT: " + str(take_profit))

    log("--------------------------------")
    log("CANDLE CONNECTION: OK")
    log("REAL TRADING: DISABLED")
    log("================================")

except Exception as e:
    log("--------------------------------")
    log("ERROR TYPE: " + type(e).__name__)
    log("ERROR DETAILS: " + str(e))
    log("================================")


# ---------------------------------
# ذخیره آخرین نتیجه در signal.txt
# ---------------------------------
try:
    with open("signal.txt", "w", encoding="utf-8") as file:
        file.write("\n".join(output))

    print("signal.txt UPDATED")

except Exception as e:
    print("SIGNAL FILE ERROR:", type(e).__name__)
    print("SIGNAL FILE DETAILS:", str(e))
