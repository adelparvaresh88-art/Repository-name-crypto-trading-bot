import urllib.request
import json
from datetime import datetime

SYMBOL = "BTCUSDT"
LIMIT = 30


def get_data():
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={SYMBOL}&interval=5m&limit={LIMIT}"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )

    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode())


def main():
    print("================================")
    print("ATI CRYPTO BOT")
    print("MODE: PAPER / TEST")
    print("TRADING: DISABLED")
    print("================================")

    try:
        candles = get_data()

        closes = [float(candle[4]) for candle in candles]

        current_price = closes[-1]
        previous_price = closes[-2]

        short_avg = sum(closes[-5:]) / 5
        long_avg = sum(closes[-15:]) / 15

        if short_avg > long_avg and current_price > previous_price:
            signal = "BUY"

        elif short_avg < long_avg and current_price < previous_price:
            signal = "SELL"

        else:
            signal = "HOLD"

        print("Time:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        print("Symbol:", SYMBOL)
        print("Price:", current_price)
        print("5 Candle Avg:", round(short_avg, 4))
        print("15 Candle Avg:", round(long_avg, 4))
        print("SIGNAL:", signal)
        print("================================")

    except Exception as error:
        print("ERROR:", str(error))
        raise


if __name__ == "__main__":
    main()
