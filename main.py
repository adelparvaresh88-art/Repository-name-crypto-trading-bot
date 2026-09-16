import urllib.request
import json
from datetime import datetime

SYMBOL = "BTCUSDT"
INTERVAL = "5m"
LIMIT = 100


def get_data():
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval={INTERVAL}&limit={LIMIT}"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


def average(values):
    return sum(values) / len(values)


def main():
    print("================================")
    print("ATI CRYPTO BOT V2")
    print("MODE: PAPER / TEST")
    print("TRADING: DISABLED")
    print("================================")

    try:
        candles = get_data()

        if len(candles) < 30:
            print("Not enough market data.")
            return

        closes = [float(c[4]) for c in candles]
        highs = [float(c[2]) for c in candles]
        lows = [float(c[3]) for c in candles]

        price = closes[-1]

        avg_5 = average(closes[-5:])
        avg_15 = average(closes[-15:])
        avg_30 = average(closes[-30:])

        previous_high = max(highs[-6:-1])
        previous_low = min(lows[-6:-1])

        momentum_up = closes[-1] > closes[-2] > closes[-3]
        momentum_down = closes[-1] < closes[-2] < closes[-3]

        if (
            avg_5 > avg_15
            and avg_15 > avg_30
            and price > previous_high
            and momentum_up
        ):
            signal = "BUY"

        elif (
            avg_5 < avg_15
            and avg_15 < avg_30
            and price < previous_low
            and momentum_down
        ):
            signal = "SELL"

        else:
            signal = "HOLD"

        print("Time:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print("Symbol:", SYMBOL)
        print("Price:", price)
        print("5 Avg:", round(avg_5, 2))
        print("15 Avg:", round(avg_15, 2))
        print("30 Avg:", round(avg_30, 2))
        print("Previous High:", previous_high)
        print("Previous Low:", previous_low)
        print("Signal:", signal)
        print("================================")

    except Exception as error:
        print("BOT ERROR:", error)
        print("Bot finished safely.")


if __name__ == "__main__":
    main()