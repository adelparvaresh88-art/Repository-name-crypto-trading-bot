import os
import requests
from datetime import datetime, timezone

# =========================================================
# ATI CRYPTO BOT
# TABDEAL FUTURES - STABLE TEST VERSION
# =========================================================

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TABDEAL_API_KEY = os.getenv("TABDEAL_API_KEY")
TABDEAL_API_SECRET = os.getenv("TABDEAL_API_SECRET")

# ---------------------------------------------------------
# SAFETY
# ---------------------------------------------------------
# False = NO REAL ORDER
# True  = REAL ORDER
REAL_TRADING = False

# مقدار بسیار کوچک برای تست
ORDER_QTY = "0.001"

# ---------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------

def telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM ERROR: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        print("Telegram status:", response.status_code)
        print("Telegram response:", response.text)

        return response.ok

    except Exception as e:
        print("Telegram exception:", repr(e))
        return False


# ---------------------------------------------------------
# PUBLIC TABDEAL PRICE
# ---------------------------------------------------------

def get_price():

    urls = [
        "https://api1.tabdeal.org/api/v1/ticker/price",
        "https://api.tabdeal.org/api/v1/ticker/price"
    ]

    for url in urls:

        try:

            response = requests.get(
                url,
                params={"symbol": SYMBOL},
                timeout=15
            )

            print("Price URL:", url)
            print("Price status:", response.status_code)
            print("Price response:", response.text[:500])

            if response.ok:

                data = response.json()

                if isinstance(data, dict):

                    price = (
                        data.get("price")
                        or data.get("lastPrice")
                        or data.get("last")
                    )

                    if price:
                        return float(price)

        except Exception as e:
            print("Price error:", repr(e))

    return None


# ---------------------------------------------------------
# CANDLE DATA
# ---------------------------------------------------------

def get_candles():

    urls = [
        "https://api1.tabdeal.org/api/v1/klines",
        "https://api.tabdeal.org/api/v1/klines"
    ]

    for url in urls:

        try:

            response = requests.get(
                url,
                params={
                    "symbol": SYMBOL,
                    "interval": TIMEFRAME,
                    "limit": 30
                },
                timeout=15
            )

            print("Kline URL:", url)
            print("Kline status:", response.status_code)

            if not response.ok:
                continue

            data = response.json()

            if isinstance(data, list) and len(data) >= 10:
                return data

        except Exception as e:
            print("Kline error:", repr(e))

    return None


# ---------------------------------------------------------
# SIMPLE PRICE-ACTION SIGNAL
# ---------------------------------------------------------

def calculate_signal(candles):

    if not candles or len(candles) < 10:
        return "NO SIGNAL", 0, 0

    try:

        # Tabdeal/Binance style kline:
        # [open_time, open, high, low, close, volume, ...]

        closes = [
            float(c[4])
            for c in candles
        ]

        highs = [
            float(c[2])
            for c in candles
        ]

        lows = [
            float(c[3])
            for c in candles
        ]

        # آخرین کندل بسته شده
        close = closes[-2]

        previous_close = closes[-3]

        recent_high = max(highs[-7:-2])
        recent_low = min(lows[-7:-2])

        buy_score = 0
        sell_score = 0

        # 1 - momentum
        if close > previous_close:
            buy_score += 1

        if close < previous_close:
            sell_score += 1

        # 2 - breakout
        if close > recent_high:
            buy_score += 1

        if close < recent_low:
            sell_score += 1

        # 3 - short trend
        short_avg = sum(closes[-6:-2]) / 4

        if close > short_avg:
            buy_score += 1

        if close < short_avg:
            sell_score += 1

        # 4 - candle strength
        candle_open = float(candles[-2][1])
        candle_high = float(candles[-2][2])
        candle_low = float(candles[-2][3])

        candle_range = candle_high - candle_low

        if candle_range > 0:

            body = abs(close - candle_open)
            body_ratio = body / candle_range

            if body_ratio >= 0.55:

                if close > candle_open:
                    buy_score += 1

                elif close < candle_open:
                    sell_score += 1

        # 5 - price location
        if close > recent_high * 0.998:
            buy_score += 1

        if close < recent_low * 1.002:
            sell_score += 1

        # Strong signal only
        if buy_score >= 4 and buy_score > sell_score:
            signal = "BUY"

        elif sell_score >= 4 and sell_score > buy_score:
            signal = "SELL"

        else:
            signal = "NO SIGNAL"

        return signal, buy_score, sell_score

    except Exception as e:

        print("Signal calculation error:", repr(e))

        return "NO SIGNAL", 0, 0


# ---------------------------------------------------------
# TABDEAL OFFICIAL SDK CONNECTION TEST
# ---------------------------------------------------------

def test_tabdeal_connection():

    if not TABDEAL_API_KEY:
        return False, "TABDEAL_API_KEY is missing"

    if not TABDEAL_API_SECRET:
        return False, "TABDEAL_API_SECRET is missing"

    try:

        from tabdeal.future import Future

        client = Future(
            TABDEAL_API_KEY,
            TABDEAL_API_SECRET
        )

        # Public connection test
        client.ping()

        # Futures market information
        client.exchange_info()

        return True, "TABDEAL FUTURES API CONNECTED"

    except ImportError:

        return False, (
            "tabdeal-python is not installed. "
            "Add tabdeal-python to requirements.txt"
        )

    except Exception as e:

        return False, f"TABDEAL API ERROR: {repr(e)}"


# ---------------------------------------------------------
# REAL ORDER FUNCTION
# ---------------------------------------------------------

def send_real_order(signal):

    if not REAL_TRADING:
        return False, "REAL_TRADING=False"

    if signal not in ("BUY", "SELL"):
        return False, "No valid trading signal"

    if not TABDEAL_API_KEY or not TABDEAL_API_SECRET:
        return False, "Tabdeal API keys are missing"

    try:

        from tabdeal.future import Future
        from tabdeal.enums import OrderSides, OrderTypes

        client = Future(
            TABDEAL_API_KEY,
            TABDEAL_API_SECRET
        )

        if signal == "BUY":
            side = OrderSides.BUY
        else:
            side = OrderSides.SELL

        order = client.new_order(
            symbol=SYMBOL,
            side=side,
            type=OrderTypes.MARKET,
            quantity=ORDER_QTY
        )

        print("REAL ORDER RESPONSE:")
        print(order)

        return True, str(order)

    except Exception as e:

        print("REAL ORDER ERROR:", repr(e))

        return False, repr(e)


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():

    print("=" * 60)
    print("ATI CRYPTO BOT")
    print("TABDEAL FUTURES")
    print("=" * 60)

    # -----------------------------------------------------
    # Telegram test
    # -----------------------------------------------------

    telegram_ok = telegram(
        "⚡ ATI CRYPTO BOT\n\n"
        "Starting bot...\n"
        "Tabdeal Futures connection test."
    )

    print("Telegram OK:", telegram_ok)

    # -----------------------------------------------------
    # API connection
    # -----------------------------------------------------

    api_ok, api_message = test_tabdeal_connection()

    print(api_message)

    # -----------------------------------------------------
    # Price
    # -----------------------------------------------------

    price = get_price()

    if price is None:

        message = (
            "🛡 ATI SAFETY\n\n"
            "❌ BTCUSDT price could not be read.\n\n"
            f"API: {api_message}"
        )

        telegram(message)
        return

    # -----------------------------------------------------
    # Candles
    # -----------------------------------------------------

    candles = get_candles()

    if candles is None:

        telegram(
            "🛡 ATI SAFETY\n\n"
            "❌ 5m candle data could not be read.\n\n"
            f"BTC/USDT: ${price:,.2f}"
        )

        return

    # -----------------------------------------------------
    # Signal
    # -----------------------------------------------------

    signal, buy_score, sell_score = calculate_signal(candles)

    now = datetime.now(timezone.utc)

    candle_time = "UNKNOWN"

    try:
        candle_timestamp = int(candles[-2][0]) / 1000
        candle_time = datetime.fromtimestamp(
            candle_timestamp,
            timezone.utc
        ).strftime("%H:%M UTC")
    except Exception:
        pass

    # -----------------------------------------------------
    # Message
    # -----------------------------------------------------

    if signal == "BUY":

        status = (
            "🟢 BUY SIGNAL\n\n"
            "⚠️ REAL ORDER IS DISABLED"
        )

    elif signal == "SELL":

        status = (
            "🔴 SELL SIGNAL\n\n"
            "⚠️ REAL ORDER IS DISABLED"
        )

    else:

        status = "⏳ NO TRADE"

    message = (
        "⚡ ATI CRYPTO BOT\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "💪 STRONG SIGNAL FILTER\n\n"

        f"📊 SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n\n"

        f"🕐 Candle: {candle_time}\n"
        f"💰 Price: ${price:,.2f}\n\n"

        f"{status}\n\n"

        f"🔐 TABDEAL API: "
        f"{'CONNECTED' if api_ok else 'ERROR'}\n"

        f"📡 TELEGRAM: "
        f"{'OK' if telegram_ok else 'ERROR'}\n"

        f"🔒 REAL TRADING: "
        f"{'ON' if REAL_TRADING else 'OFF'}"
    )

    telegram(message)

    # -----------------------------------------------------
    # REAL ORDER
    # -----------------------------------------------------

    if REAL_TRADING and signal in ("BUY", "SELL"):

        success, result = send_real_order(signal)

        telegram(
            "🤖 ATI ORDER RESULT\n\n"
            f"Signal: {signal}\n"
            f"Success: {success}\n\n"
            f"{result}"
        )


# ---------------------------------------------------------
# RUN
# ---------------------------------------------------------

if __name__ == "__main__":
    main()
