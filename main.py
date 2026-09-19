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

STATE_FILE = "bot_state.json"


def get_data():
    url = "https://api.kraken.com/0/public/OHLC?pair=XBTUSD&interval=5"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        data = json.loads(response.read().decode())

    if data.get("error"):
        raise Exception(str(data["error"]))

    result = data["result"]
    pair_key = [key for key in result.keys() if key != "last"][0]

    candles = result[pair_key]

    if len(candles) < 30:
        raise Exception("داده کافی دریافت نشد.")

    # آخرین کندل ممکن است هنوز در حال تشکیل باشد.
    # آن را حذف می‌کنیم تا فقط کندل بسته‌شده بررسی شود.
    closed_candles = candles[:-1]

    if len(closed_candles) < 25:
        raise Exception("کندل بسته‌شده کافی نیست.")

    return closed_candles


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        raise Exception("Telegram secrets تنظیم نشده.")

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": message
    }).encode()

    req = urllib.request.Request(
        url,
        data=data,
        headers={"User-Agent": "ATI-CRYPTO-BOT/1.0"}
    )

    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read().decode()


def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "last_signal": "NONE",
            "last_candle": ""
        }

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            return json.load(file)

    except Exception:
        return {
            "last_signal": "NONE",
            "last_candle": ""
        }


def save_state(signal, candle_time):
    state = {
        "last_signal": signal,
        "last_candle": str(candle_time)
    }

    with open(STATE_FILE, "w", encoding="utf-8") as file:
        json.dump(state, file)


def calculate_signal(candles):
    closes = [float(c[4]) for c in candles]
    opens = [float(c[1]) for c in candles]
    highs = [float(c[2]) for c in candles]
    lows = [float(c[3]) for c in candles]

    current = closes[-1]
    previous = closes[-2]

    short_avg = sum(closes[-5:]) / 5
    long_avg = sum(closes[-15:]) / 15

    buy_score = 0
    sell_score = 0

    # 1 - روند
    if short_avg > long_avg:
        buy_score += 1
    elif short_avg < long_avg:
        sell_score += 1

    # 2 - جهت قیمت
    if current > previous:
        buy_score += 1
    elif current < previous:
        sell_score += 1

    # 3 - جهت کندل بسته‌شده
    if closes[-1] > opens[-1]:
        buy_score += 1
    elif closes[-1] < opens[-1]:
        sell_score += 1

    # 4 - شکست سقف/کف 10 کندل قبلی
    recent_high = max(highs[-11:-1])
    recent_low = min(lows[-11:-1])

    if current > recent_high:
        buy_score += 1

    if current < recent_low:
        sell_score += 1

    # 5 - حرکت دو کندل اخیر
    if closes[-1] > closes[-3]:
        buy_score += 1
    elif closes[-1] < closes[-3]:
        sell_score += 1

    print("BUY SCORE:", buy_score, "/5")
    print("SELL SCORE:", sell_score, "/5")

    if buy_score >= MIN_SCORE and buy_score > sell_score:
        return "BUY", buy_score, sell_score

    if sell_score >= MIN_SCORE and sell_score > buy_score:
        return "SELL", buy_score, sell_score

    return "HOLD", buy_score, sell_score


def calculate_levels(price, signal):
    if signal == "BUY":
        sl = price * (1 - SL_PERCENT / 100)
        tp = price * (1 + TP_PERCENT / 100)

    elif signal == "SELL":
        sl = price * (1 + SL_PERCENT / 100)
        tp = price * (1 - TP_PERCENT / 100)

    else:
        return None, None

    return sl, tp


def main():
    print("================================")
    print("ATI CRYPTO BOT V9 STARTED")
    print("5m CLOSED CANDLE MODE")
    print("================================")

    candles = get_data()

    # این کندل کاملاً بسته شده است
    candle_time = candles[-1][0]
    price = float(candles[-1][4])

    signal, buy_score, sell_score = calculate_signal(candles)

    state = load_state()

    last_signal = state.get("last_signal", "NONE")
    last_candle = state.get("last_candle", "")

    # HOLD پیام نمی‌دهد
    if signal == "HOLD":
        print("HOLD - TELEGRAM MESSAGE SKIPPED")
        return

    # جلوگیری از BUY/SELL تکراری روی همان کندل
    if (
        signal == last_signal
        and str(candle_time) == str(last_candle)
    ):
        print("DUPLICATE SIGNAL - TELEGRAM MESSAGE SKIPPED")
        return

    sl, tp = calculate_levels(price, signal)

    if signal == "BUY":
        icon = "🟢"
    else:
        icon = "🔴"

    message = (
        "⚡ ATI CRYPTO BOT V9\n\n"
        f"₿ BTC: ${price:,.2f}\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE CONFIRMED\n\n"
        f"{icon} SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n\n"
        f"💰 Entry: ${price:,.2f}\n"
        f"🛑 SL: ${sl:,.2f}\n"
        f"🎯 TP: ${tp:,.2f}\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING: DISABLED"
    )

    print(message)

    send_telegram(message)

    save_state(signal, candle_time)


try:
    main()

except Exception as error:
    print("BOT ERROR:")
    print(traceback.format_exc())

    try:
        send_telegram(
            "⚠️ ATI CRYPTO BOT V9\n\n"
            "خطای دقیق:\n\n"
            + str(error)
        )
    except Exception:
        pass
