import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timezone

# =========================
# SETTINGS
# =========================
SYMBOL = "BTCUSDT"
COINGECKO_ID = "bitcoin"

MIN_SCORE = 3
SL_PERCENT = 1.0
TP_PERCENT = 2.0


# =========================
# GET BTC PRICE
# =========================
def get_btc_price():
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        "?ids=" + COINGECKO_ID +
        "&vs_currencies=usd"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-Crypto-Bot/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    price = data[COINGECKO_ID]["usd"]

    return float(price)


# =========================
# TELEGRAM
# =========================
def send_telegram(message):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("Telegram secrets not found.")
        print("BOT WILL CONTINUE WITHOUT TELEGRAM.")
        return

    url = (
        "https://api.telegram.org/bot"
        + bot_token
        + "/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            result = json.loads(response.read().decode("utf-8"))

        if result.get("ok"):
            print("Telegram message sent successfully.")
        else:
            print("Telegram returned an error.")
            print(result)

    except Exception as error:
        print("Telegram error:", error)


# =========================
# MAIN BOT
# =========================
def main():

    print("================================")
    print("ATI CRYPTO BOT V5")
    print("MODE: PAPER / TEST")
    print("REAL TRADING: DISABLED")
    print("================================")

    try:
        current_price = get_btc_price()
    except Exception as error:
        print("PRICE ERROR:", error)
        return

    print("SYMBOL:", SYMBOL)
    print("BTC PRICE: $", current_price)

    # Simple test signal
    buy_score = 3
    sell_score = 0

    print("BUY SCORE:", buy_score, "/5")
    print("SELL SCORE:", sell_score, "/5")

    signal = "HOLD"
    message = None

    if buy_score >= MIN_SCORE:

        signal = "BUY"

        stop_loss = current_price * (1 - SL_PERCENT / 100)
        take_profit = current_price * (1 + TP_PERCENT / 100)

        message = (
            "🟢 STRONG BUY - PAPER\n\n"
            "💰 Entry: $" + f"{current_price:,.2f}" + "\n"
            "🛑 Stop Loss: $" + f"{stop_loss:,.2f}" + "\n"
            "🎯 Take Profit: $" + f"{take_profit:,.2f}" + "\n\n"
            "📊 BUY SCORE: "
            + str(buy_score)
            + "/5\n"
            "⚠️ PAPER TEST - NO REAL TRADE"
        )

    elif sell_score >= MIN_SCORE:

        signal = "SELL"

        stop_loss = current_price * (1 + SL_PERCENT / 100)
        take_profit = current_price * (1 - TP_PERCENT / 100)

        message = (
            "🔴 STRONG SELL - PAPER\n\n"
            "💰 Entry: $" + f"{current_price:,.2f}" + "\n"
            "🛑 Stop Loss: $" + f"{stop_loss:,.2f}" + "\n"
            "🎯 Take Profit: $" + f"{take_profit:,.2f}" + "\n\n"
            "📊 SELL SCORE: "
            + str(sell_score)
            + "/5\n"
            "⚠️ PAPER TEST - NO REAL TRADE"
        )

    else:

        message = (
            "⚪ HOLD - PAPER\n\n"
            "💰 BTC: $" + f"{current_price:,.2f}" + "\n"
            "📊 BUY SCORE: " + str(buy_score) + "/5\n"
            "📊 SELL SCORE: " + str(sell_score) + "/5\n\n"
            "⚠️ PAPER TEST - NO REAL TRADE"
        )

    print("SIGNAL:", signal)
    print("--------------------------------")
    print(message)
    print("--------------------------------")

    send_telegram(message)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    print("BOT TIME:", now)
    print("BOT FINISHED SUCCESSFULLY.")


# =========================
# START
# =========================
if __name__ == "__main__":
    main()
