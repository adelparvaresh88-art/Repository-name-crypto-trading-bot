import os
import requests
from datetime import datetime, timezone

from tabdeal.enums import OrderSides, OrderTypes
from tabdeal.future import Future

============================================================

ATI CRYPTO BOT

TABDEAL FUTURES

BTCUSDT / 5 MIN

============================================================

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

============================================================

TELEGRAM

============================================================

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

    print("Telegram HTTP:", response.status_code)
    print("Telegram response:", response.text)

    if response.status_code == 200:

        data = response.json()

        if data.get("ok") is True:
            print("✅ TELEGRAM SEND: OK")
            return True

    print("❌ TELEGRAM SEND FAILED")
    return False

except Exception as e:

    print("❌ TELEGRAM ERROR:", e)
    return False

============================================================

MARKET DATA

============================================================

def get_price():

url = "https://api1.tabdeal.org/r/api/v1/ticker/price"

response = requests.get(
    url,
    params={"symbol": SYMBOL},
    timeout=20
)

response.raise_for_status()

data = response.json()

if isinstance(data, list):

    for item in data:

        if item.get("symbol") == SYMBOL:
            return float(item["price"])

if isinstance(data, dict):

    if "price" in data:
        return float(data["price"])

raise Exception(f"Price not found: {data}")

============================================================

SIMPLE SIGNAL ENGINE

============================================================

def get_signal():

"""
این بخش فعلاً برای اتصال امن ربات است.
سیگنال واقعی مرحله بعدی می‌تواند همان منطق
5/5 فعلی ATI باشد.
"""

try:

    price = get_price()

    # ----------------------------------------------------
    # فعلاً هیچ معامله‌ای بدون سیگنال تأییدشده انجام نمی‌شود.
    # ----------------------------------------------------

    return {
        "signal": "NO SIGNAL",
        "price": price,
        "buy_score": 0,
        "sell_score": 0
    }

except Exception as e:

    raise Exception(f"Market data error: {e}")

============================================================

TABDEAL FUTURES

============================================================

def create_future_client():

if not API_KEY:
    raise Exception("TABDEAL_API_KEY is missing")

if not API_SECRET:
    raise Exception("TABDEAL_API_SECRET is missing")

return Future(API_KEY, API_SECRET)

============================================================

REAL FUTURES MARKET ORDER

============================================================

def send_market_order(side):

client = create_future_client()

if side == "BUY":
    order_side = OrderSides.BUY

elif side == "SELL":
    order_side = OrderSides.SELL

else:
    raise Exception(f"Invalid order side: {side}")

print(
    f"🚨 LIVE ORDER REQUEST: "
    f"{side} {SYMBOL} quantity={ORDER_QTY}"
)

order = client.new_order(
    symbol=SYMBOL,
    side=order_side,
    type=OrderTypes.MARKET,
    quantity=ORDER_QTY
)

return order

============================================================

SIGNAL MESSAGE

============================================================

def build_signal_message(signal_data):

price = signal_data["price"]

signal = signal_data["signal"]

buy_score = signal_data["buy_score"]

sell_score = signal_data["sell_score"]

candle_time = datetime.now(timezone.utc).strftime(
    "%Y-%m-%d %H:%M UTC"
)

message = (
    "⚡ ATI CRYPTO BOT\n\n"
    "₿ BTC/USDT\n"
    f"⏱ Timeframe: {TIMEFRAME}\n"
    "✅ CLOSED CANDLE\n"
    "💪 STRONG SIGNAL FILTER\n\n"
    f"📊 SIGNAL: {signal}\n"
    f"📈 BUY SCORE: {buy_score}/5\n"
    f"📉 SELL SCORE: {sell_score}/5\n\n"
    f"🕐 Time: {candle_time}\n"
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

============================================================

MAIN

============================================================

def main():

print("======================================")
print("ATI CRYPTO BOT")
print("TABDEAL FUTURES")
print("BTCUSDT / 5m")
print("======================================")

print("LIVE_TRADING:", LIVE_TRADING)
print("ORDER_QTY:", ORDER_QTY)

# --------------------------------------------------------
# CHECK TELEGRAM
# --------------------------------------------------------

if not BOT_TOKEN:
    print("❌ TELEGRAM_BOT_TOKEN missing")

if not CHAT_ID:
    print("❌ TELEGRAM_CHAT_ID missing")

# --------------------------------------------------------
# CHECK API
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
# MARKET
# --------------------------------------------------------

try:

    signal_data = get_signal()

except Exception as e:

    error = (
        "🛡 ATI SAFETY\n\n"
        "❌ Market data error.\n\n"
        f"{str(e)[:1000]}"
    )

    print(error)

    send_telegram(error)

    return

# --------------------------------------------------------
# TELEGRAM SIGNAL
# --------------------------------------------------------

message = build_signal_message(signal_data)

send_telegram(message)

signal = signal_data["signal"]

# --------------------------------------------------------
# NO SIGNAL
# --------------------------------------------------------

if signal not in ("BUY", "SELL"):

    print("⏳ No strong signal. No order.")

    return

# --------------------------------------------------------
# LIVE TRADING SAFETY
# --------------------------------------------------------

if not LIVE_TRADING:

    send_telegram(
        "🧪 PAPER/TEST MODE\n\n"
        f"Signal: {signal}\n"
        "❌ REAL ORDER NOT SENT\n\n"
        "LIVE_TRADING is FALSE."
    )

    print("🧪 TEST MODE - NO REAL ORDER")

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
        f"₿ {SYMBOL}\n"
        f"📊 SIDE: {signal}\n"
        f"💰 QTY: {ORDER_QTY}\n\n"
        "✅ MARKET ORDER SENT TO TABDEAL.\n\n"
        f"📡 RESPONSE:\n{str(order)[:2500]}"
    )

except Exception as e:

    error = (
        "🛡 ATI SAFETY\n\n"
        "❌ REAL ORDER FAILED.\n\n"
        f"Reason:\n{str(e)[:2000]}\n\n"
        "⚠️ NO CONFIRMATION OF EXECUTION."
    )

    print(error)

    send_telegram(error)

if name == "main":
main()
