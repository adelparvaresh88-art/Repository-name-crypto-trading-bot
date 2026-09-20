import os
import json
import urllib.request
import urllib.parse
import traceback

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SL_PERCENT = 0.50
TP_PERCENT = 1.00

MIN_SCORE = 4
MIN_MOVE_PERCENT = 0.08


def send_telegram(message):
    if not BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN is missing")

    if not CHAT_ID:
        raise Exception("TELEGRAM_CHAT_ID is missing")

    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = response.read().decode()

    return result


def get_data():
    url = (
        "https://api.binance.com/api/v3/klines"
        "?symbol=BTCUSDT&interval=5m&limit=50"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode())

    if not isinstance(data, list):
        raise Exception("Binance returned invalid data")

    if len(data) < 30:
        raise Exception("Not enough candle data")

    # حذف کندل در حال تشکیل
    return data[:-1]


def calculate_signal(candles):
    closes = [float(c[4]) for c in candles]
    opens = [float(c[1]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    current = closes[-1]
    previous = closes[-2]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-20:]) / 20

    buy_score = 0
    sell_score = 0

    # 1 - Trend
    if short_avg > long_avg:
        buy_score += 1
    elif short_avg < long_avg:
        sell_score += 1

    # 2 - Price direction
    if current > previous:
        buy_score += 1
    elif current < previous:
        sell_score += 1

    # 3 - Candle direction
    if closes[-1] > opens[-1]:
        buy_score += 1
    elif closes[-1] < opens[-1]:
        sell_score += 1

    # 4 - Breakout
    recent_high = max(highs[-11:-1])
    recent_low = min(lows[-11:-1])

    if current > recent_high:
        buy_score += 1
    elif current < recent_low:
        sell_score += 1

    # 5 - Move strength
    move_percent = abs((current - previous) / previous) * 100

    if move_percent >= MIN_MOVE_PERCENT:
        if current > previous:
            buy_score += 1
        elif current < previous:
            sell_score += 1

    if buy_score >= MIN_SCORE and buy_score > sell_score:
        signal = "BUY"
    elif sell_score >= MIN_SCORE and sell_score > buy_score:
        signal = "SELL"
    else:
        signal = "HOLD"

    return signal, current, buy_score, sell_score, move_percent


def main():

    print("================================")
    print("      ATI CRYPTO BOT V14")
    print("================================")

    # ---------------------------------------
    # تست مستقیم تلگرام
    # ---------------------------------------

    print("📡 Testing Telegram...")

    test_message = (
        "⚡ ATI CRYPTO BOT V14\n\n"
        "✅ TELEGRAM CONNECTION TEST\n"
        "📡 Telegram connection is working.\n\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    telegram_result = send_telegram(test_message)

    print("✅ Telegram test sent")
    print(telegram_result)

    # ---------------------------------------
    # دریافت قیمت و کندل
    # ---------------------------------------

    print("📡 Getting BTC 5m candles...")

    candles = get_data()

    print("✅ BTC candle data received")
    print("📊 Candles:", len(candles))

    signal, current, buy_score, sell_score, move_percent = calculate_signal(
        candles
    )

    print("================================")
    print("₿ BTC:", round(current, 2))
    print("📈 BUY SCORE:", buy_score, "/5")
    print("📉 SELL SCORE:", sell_score, "/5")
    print("📊 MOVE:", round(move_percent, 3), "%")
    print("🚦 SIGNAL:", signal)
    print("================================")

    # ---------------------------------------
    # BUY
    # ---------------------------------------

    if signal == "BUY":

        stop_loss = current * (1 - SL_PERCENT / 100)
        take_profit = current * (1 + TP_PERCENT / 100)

        signal_text = "🟢 SIGNAL: BUY"

        trade_info = (
            f"💰 Entry: ${current:,.2f}\n"
            f"🛑 SL: ${stop_loss:,.2f}\n"
            f"🎯 TP: ${take_profit:,.2f}"
        )

    # ---------------------------------------
    # SELL
    # ---------------------------------------

    elif signal == "SELL":

        stop_loss = current * (1 + SL_PERCENT / 100)
        take_profit = current * (1 - TP_PERCENT / 100)

        signal_text = "🔴 SIGNAL: SELL"

        trade_info = (
            f"💰 Entry: ${current:,.2f}\n"
            f"🛑 SL: ${stop_loss:,.2f}\n"
            f"🎯 TP: ${take_profit:,.2f}"
        )

    # ---------------------------------------
    # HOLD
    # ---------------------------------------

    else:

        signal_text = "⚪ SIGNAL: HOLD"

        trade_info = (
            "⏸ No strong signal yet\n"
            "👀 Bot is monitoring BTC"
        )

    # ---------------------------------------
    # ارسال پیام سیگنال
    # ---------------------------------------

    message = (
        "⚡ ATI CRYPTO BOT V14\n\n"
        f"₿ BTC: ${current:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE CONFIRMED\n\n"
        f"{signal_text}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n"
        f"📊 MOVE: {move_percent:.3f}%\n\n"
        f"{trade_info}\n\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    print("📨 Sending signal to Telegram...")

    result = send_telegram(message)

    print("✅ Signal sent")
    print(result)

    print("================================")
    print("✅ ATI BOT FINISHED SUCCESSFULLY")
    print("================================")


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("================================")
        print("❌ ATI BOT ERROR")
        print("================================")
        print(str(error))
        print("================================")

        traceback.print_exc()

        raise
