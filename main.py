import os
import requests
from datetime import datetime, timezone

from tabdeal.enums import OrderSides, OrderTypes
from tabdeal.future import Future


# ============================================================
# ATI CRYPTO BOT
# TABDEAL FUTURES
# BTCUSDT - 5 MIN CLOSED CANDLE
# ============================================================

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

API_KEY = os.getenv("TABDEAL_API_KEY")
API_SECRET = os.getenv("TABDEAL_API_SECRET")

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LIVE_TRADING = os.getenv("LIVE_TRADING", "FALSE").upper() == "TRUE"

ORDER_QTY = os.getenv("ORDER_QTY", "0.001")

SL_PERCENT = 0.005
TP_PERCENT = 0.010

SIGNAL_THRESHOLD = 4

BINANCE_KLINES = "https://api.binance.com/api/v3/klines"


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing")
        return False

    if not CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID missing")
        return False

    try:

        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print("Telegram:", response.status_code)

        if response.status_code == 200:

            data = response.json()

            if data.get("ok") is True:
                print("✅ TELEGRAM SEND OK")
                return True

        print("❌ TELEGRAM SEND FAILED")
        print(response.text)

        return False

    except Exception as e:

        print("❌ TELEGRAM ERROR:", e)
        return False


# ============================================================
# MARKET DATA
# ============================================================

def get_closed_candles():

    params = {
        "symbol": SYMBOL,
        "interval": TIMEFRAME,
        "limit": 30
    }

    response = requests.get(
        BINANCE_KLINES,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    candles = response.json()

    if len(candles) < 10:
        raise Exception("Not enough candles")

    # آخرین کندل ممکن است هنوز باز باشد.
    # بنابراین آن را حذف می‌کنیم.
    closed = candles[:-1]

    return closed


# ============================================================
# SIGNAL ENGINE
# ============================================================

def calculate_signal():

    candles = get_closed_candles()

    c1 = candles[-1]
    c2 = candles[-2]
    c3 = candles[-3]
    c4 = candles[-4]

    o1 = float(c1[1])
    h1 = float(c1[2])
    l1 = float(c1[3])
    close1 = float(c1[4])

    o2 = float(c2[1])
    h2 = float(c2[2])
    l2 = float(c2[3])
    close2 = float(c2[4])

    close3 = float(c3[4])
    close4 = float(c4[4])

    buy_score = 0
    sell_score = 0

    # --------------------------------------------------------
    # 1. آخرین کندل
    # --------------------------------------------------------

    if close1 > o1:
        buy_score += 1

    if close1 < o1:
        sell_score += 1

    # --------------------------------------------------------
    # 2. مقایسه با کندل قبلی
    # --------------------------------------------------------

    if close1 > close2:
        buy_score += 1

    if close1 < close2:
        sell_score += 1

    # --------------------------------------------------------
    # 3. ساختار دو کندل
    # --------------------------------------------------------

    if h1 > h2 and l1 > l2:
        buy_score += 1

    if h1 < h2 and l1 < l2:
        sell_score += 1

    # --------------------------------------------------------
    # 4. مومنتوم کوتاه
    # --------------------------------------------------------

    if close1 > close3:
        buy_score += 1

    if close1 < close3:
        sell_score += 1

    # --------------------------------------------------------
    # 5. روند کوتاه
    # --------------------------------------------------------

    if close1 > close4:
        buy_score += 1

    if close1 < close4:
        sell_score += 1

    # --------------------------------------------------------
    # STRONG SIGNAL
    # --------------------------------------------------------

    signal = "NO SIGNAL"

    if buy_score >= SIGNAL_THRESHOLD and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= SIGNAL_THRESHOLD and sell_score > buy_score:
        signal = "SELL"

    return {
        "signal": signal,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "price": close1,
        "candle_time": c1[0]
    }


# ============================================================
# TABDEAL FUTURES CLIENT
# ============================================================

def get_tabdeal_client():

    if not API_KEY:
        raise Exception("TABDEAL_API_KEY is missing")

    if not API_SECRET:
        raise Exception("TABDEAL_API_SECRET is missing")

    return Future(API_KEY, API_SECRET)


# ============================================================
# FUTURES ORDER
# ============================================================

def send_market_order(signal):

    client = get_tabdeal_client()

    if signal == "BUY":
        side = OrderSides.BUY

    elif signal == "SELL":
        side = OrderSides.SELL

    else:
        raise Exception("Invalid signal")

    print(
        f"🚨 ORDER: {signal} "
        f"{SYMBOL} "
        f"QTY={ORDER_QTY}"
    )

    order = client.new_order(
        symbol=SYMBOL,
        side=side,
        type=OrderTypes.MARKET,
        quantity=ORDER_QTY
    )

    return order


# ============================================================
# MESSAGE
# ============================================================

def build_message(data):

    signal = data["signal"]
    buy = data["buy_score"]
    sell = data["sell_score"]
    price = data["price"]

    candle_dt = datetime.fromtimestamp(
        data["candle_time"] / 1000,
        timezone.utc
    )

    message = (
        "⚡ ATI CRYPTO BOT\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "💪 STRONG SIGNAL FILTER\n\n"
        f"📊 SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy}/5\n"
        f"📉 SELL SCORE: {sell}/5\n\n"
        f"🕐 Candle: {candle_dt.strftime('%H:%M UTC')}\n"
        f"💰 Price: ${price:,.2f}\n"
    )

    if signal == "BUY":

        sl = price * (1 - SL_PERCENT)
        tp = price * (1 + TP_PERCENT)

        message += (
            "\n🟢 BUY SIGNAL\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n"
        )

    elif signal == "SELL":

        sl = price * (1 + SL_PERCENT)
        tp = price * (1 - TP_PERCENT)

        message += (
            "\n🔴 SELL SIGNAL\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n"
        )

    else:

        message += "\n⏳ NO TRADE\n"

    return message


# ============================================================
# MAIN
# ============================================================

def main():

    print("================================")
    print("ATI CRYPTO BOT")
    print("TABDEAL FUTURES")
    print("BTCUSDT / 5m")
    print("================================")

    print("LIVE_TRADING:", LIVE_TRADING)
    print("ORDER_QTY:", ORDER_QTY)

    # --------------------------------------------------------
    # API CHECK
    # --------------------------------------------------------

    if not API_KEY:

        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "❌ TABDEAL_API_KEY is missing.\n"
            "No order was sent."
        )

        return

    if not API_SECRET:

        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "❌ TABDEAL_API_SECRET is missing.\n"
            "No order was sent."
        )

        return

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    try:

        data = calculate_signal()

        print("SIGNAL:", data["signal"])
        print("BUY:", data["buy_score"])
        print("SELL:", data["sell_score"])
        print("PRICE:", data["price"])

    except Exception as e:

        error = (
            "🛡 ATI SAFETY\n\n"
            "❌ SIGNAL ENGINE ERROR\n\n"
            f"{str(e)[:1500]}"
        )

        print(error)
        send_telegram(error)

        return

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    send_telegram(build_message(data))

    signal = data["signal"]

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if signal == "NO SIGNAL":

        print("⏳ NO STRONG SIGNAL")
        return

    # --------------------------------------------------------
    # PAPER MODE
    # --------------------------------------------------------

    if not LIVE_TRADING:

        send_telegram(
            "🧪 PAPER / TEST MODE\n\n"
            f"Signal: {signal}\n"
            f"Buy Score: {data['buy_score']}/5\n"
            f"Sell Score: {data['sell_score']}/5\n\n"
            "❌ REAL ORDER NOT SENT\n"
            "LIVE_TRADING=FALSE"
        )

        print("🧪 PAPER MODE")
        return

    # --------------------------------------------------------
    # REAL ORDER
    # --------------------------------------------------------

    try:

        order = send_market_order(signal)

        print("ORDER RESPONSE:")
        print(order)

        send_telegram(
            "🚨 ATI LIVE TRADE\n\n"
            "₿ BTC/USDT\n"
            f"📊 SIDE: {signal}\n"
            f"💵 QTY: {ORDER_QTY}\n\n"
            "✅ MARKET ORDER SENT.\n\n"
            f"📡 Response:\n{str(order)[:2000]}"
        )

    except Exception as e:

        error = (
            "🛡 ATI SAFETY\n\n"
            "❌ ORDER FAILED\n\n"
            f"Reason:\n{str(e)[:1800]}\n\n"
            "⚠️ Execution was NOT confirmed."
        )

        print(error)
        send_telegram(error)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
