import os
import json
import urllib.request
import urllib.parse
import traceback

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

SL_PERCENT = 0.50
TP_PERCENT = 1.00

MIN_SCORE = 3
MIN_MOVE_PERCENT = 0.05


def send_telegram(message):
    if not BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN is missing")

    if not CHAT_ID:
        raise Exception("TELEGRAM_CHAT_ID is missing")

    url = "https://api.telegram.org/bot" + BOT_TOKEN + "/sendMessage"

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        result = response.read().decode("utf-8")

    result_data = json.loads(result)

    if not result_data.get("ok"):
        raise Exception("Telegram API error: " + result)

    return result


def get_data():
    url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=5"

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("error"):
        raise Exception("Kraken API error: " + str(data["error"]))

    result = data.get("result")

    if not result:
        raise Exception("Kraken returned empty data")

    pair_key = None

    for key in result:
        if key != "last":
            pair_key = key
            break

    if not pair_key:
        raise Exception("BTC data not found")

    candles = result[pair_key]

    if len(candles) < 30:
        raise Exception("Not enough candle data")

    return candles[:-1]


def calculate_signal(candles):

    closes = [float(c[4]) for c in candles]
    opens = [float(c[1]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    current = closes[-1]

    sma5 = sum(closes[-5:]) / 5
    sma20 = sum(closes[-20:]) / 20

    buy_score = 0
    sell_score = 0

    # 1. روند کوتاه مدت
    if sma5 > sma20:
        buy_score += 1
    elif sma5 < sma20:
        sell_score += 1

    # 2. جهت آخرین کندل
    if closes[-1] > opens[-1]:
        buy_score += 1
    elif closes[-1] < opens[-1]:
        sell_score += 1

    # 3. قدرت حرکت
    previous = closes[-2]
    move = ((current - previous) / previous) * 100

    if move >= MIN_MOVE_PERCENT:
        buy_score += 1
    elif move <= -MIN_MOVE_PERCENT:
        sell_score += 1

    # 4. شکست سقف/کف
    previous_high = max(highs[-6:-1])
    previous_low = min(lows[-6:-1])

    if current > previous_high:
        buy_score += 1

    elif current < previous_low:
        sell_score += 1

    # 5. تأیید دو کندل اخیر
    if closes[-1] > opens[-1] and closes[-2] > opens[-2]:
        buy_score += 1

    elif closes[-1] < opens[-1] and closes[-2] < opens[-2]:
        sell_score += 1

    # فقط وقتی امتیاز برتر حداقل 3 باشد
    if buy_score >= MIN_SCORE and buy_score > sell_score:
        signal = "BUY"

    elif sell_score >= MIN_SCORE and sell_score > buy_score:
        signal = "SELL"

    else:
        signal = "HOLD"

    return (
        signal,
        current,
        buy_score,
        sell_score,
        abs(move)
    )


def main():

    print("================================")
    print("      ⚡ ATI CRYPTO BOT V17")
    print("================================")

    candles = get_data()

    (
        signal,
        current,
        buy_score,
        sell_score,
        move_percent
    ) = calculate_signal(candles)

    print("BTC:", round(current, 2))
    print("BUY SCORE:", buy_score, "/5")
    print("SELL SCORE:", sell_score, "/5")
    print("MOVE:", round(move_percent, 3), "%")
    print("SIGNAL:", signal)

    if signal == "BUY":

        stop_loss = current * (1 - SL_PERCENT / 100)
        take_profit = current * (1 + TP_PERCENT / 100)

        signal_line = "🟢 SIGNAL: BUY"

        trade_info = (
            f"💰 Entry: ${current:,.2f}\n"
            f"🛑 SL: ${stop_loss:,.2f}\n"
            f"🎯 TP: ${take_profit:,.2f}"
        )

    elif signal == "SELL":

        stop_loss = current * (1 + SL_PERCENT / 100)
        take_profit = current * (1 - TP_PERCENT / 100)

        signal_line = "🔴 SIGNAL: SELL"

        trade_info = (
            f"💰 Entry: ${current:,.2f}\n"
            f"🛑 SL: ${stop_loss:,.2f}\n"
            f"🎯 TP: ${take_profit:,.2f}"
        )

    else:

        signal_line = "⚪ SIGNAL: HOLD"

        trade_info = (
            "⏸ No strong setup yet\n"
            "👀 Bot is monitoring BTC"
        )

    message = (
        "⚡ ATI CRYPTO BOT V17\n\n"
        f"₿ BTC: ${current:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE CONFIRMED\n\n"
        f"{signal_line}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n"
        f"📊 MOVE: {move_percent:.3f}%\n\n"
        f"{trade_info}\n\n"
        "🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    send_telegram(message)

    print("✅ Telegram message sent")
    print("================================")


if __name__ == "__main__":

    try:
        main()

    except Exception as error:

        print("================================")
        print("❌ ATI BOT ERROR")
        print(str(error))
        print("================================")

        traceback.print_exc()

        raise
