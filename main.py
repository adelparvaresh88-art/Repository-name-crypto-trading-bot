import os
import json
import urllib.request
import urllib.parse

# ==========================================
# ATI CRYPTO BOT V17
# ==========================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

CANDLE_COUNT = 30


# ==========================================
# HTTP GET
# ==========================================

def http_get(url, timeout=15):

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "ATI-CRYPTO-BOT/17.0",
            "Accept": "application/json"
        }
    )

    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(
            response.read().decode("utf-8")
        )


# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        raise Exception("TELEGRAM_BOT_TOKEN is missing")

    if not TELEGRAM_CHAT_ID:
        raise Exception("TELEGRAM_CHAT_ID is missing")

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    data = urllib.parse.urlencode({
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "User-Agent": "ATI-CRYPTO-BOT/17.0"
        }
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode("utf-8")


# ==========================================
# COINBASE
# ==========================================

def get_coinbase_data():

    url = (
        "https://api.exchange.coinbase.com/"
        "products/BTC-USD/candles"
        "?granularity=300"
    )

    data = http_get(url)

    if not isinstance(data, list) or len(data) < 12:
        raise Exception(
            "Coinbase returned insufficient candle data"
        )

    candles = []

    for item in data:

        if len(item) < 6:
            continue

        candles.append({
            "time": float(item[0]),
            "low": float(item[1]),
            "high": float(item[2]),
            "open": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[5])
        })

    candles.sort(key=lambda x: x["time"])

    return candles[-CANDLE_COUNT:], "COINBASE"


# ==========================================
# KRAKEN FALLBACK
# ==========================================

def get_kraken_data():

    url = (
        "https://api.kraken.com/0/public/OHLC"
        "?pair=XBTUSD&interval=5"
    )

    data = http_get(url)

    if data.get("error"):
        raise Exception(
            "Kraken API error: " + str(data["error"])
        )

    result = data.get("result", {})

    pair_data = None

    for key, value in result.items():

        if key != "last":
            pair_data = value
            break

    if not pair_data or len(pair_data) < 12:
        raise Exception(
            "Kraken returned insufficient candle data"
        )

    candles = []

    for item in pair_data:

        if len(item) < 7:
            continue

        candles.append({
            "time": float(item[0]),
            "open": float(item[1]),
            "high": float(item[2]),
            "low": float(item[3]),
            "close": float(item[4]),
            "volume": float(item[6])
        })

    candles.sort(key=lambda x: x["time"])

    return candles[-CANDLE_COUNT:], "KRAKEN"


# ==========================================
# MARKET DATA
# ==========================================

def get_market_data():

    errors = []

    try:

        candles, source = get_coinbase_data()

        return candles, candles[-1]["close"], source

    except Exception as error:

        errors.append(
            "Coinbase: " + str(error)
        )

    try:

        candles, source = get_kraken_data()

        return candles, candles[-1]["close"], source

    except Exception as error:

        errors.append(
            "Kraken: " + str(error)
        )

    raise Exception(
        " | ".join(errors)
    )


# ==========================================
# SIGNAL ENGINE V17
# ==========================================

def calculate_signal(candles):

    if len(candles) < 12:
        raise Exception(
            "Not enough candles"
        )

    # آخرین کندل ممکن است در حال تشکیل باشد.
    # فقط کندل‌های بسته‌شده استفاده می‌شوند.
    closed = candles[:-1]

    if len(closed) < 10:
        raise Exception(
            "Not enough closed candles"
        )

    last = closed[-1]
    prev = closed[-2]
    c3 = closed[-3]
    c4 = closed[-4]
    c5 = closed[-5]

    buy = 0
    sell = 0

    # --------------------------------------
    # 1. LAST CANDLE
    # --------------------------------------

    if last["close"] > last["open"]:
        buy += 1

    elif last["close"] < last["open"]:
        sell += 1

    # --------------------------------------
    # 2. PREVIOUS CANDLE
    # --------------------------------------

    if prev["close"] > prev["open"]:
        buy += 1

    elif prev["close"] < prev["open"]:
        sell += 1

    # --------------------------------------
    # 3. MOMENTUM
    # --------------------------------------

    if (
        last["close"] > prev["close"]
        and prev["close"] > c3["close"]
    ):
        buy += 1

    elif (
        last["close"] < prev["close"]
        and prev["close"] < c3["close"]
    ):
        sell += 1

    # --------------------------------------
    # 4. SHORT-TERM DIRECTION
    # --------------------------------------

    if last["close"] > c4["close"]:
        buy += 1

    elif last["close"] < c4["close"]:
        sell += 1

    # --------------------------------------
    # 5. BREAKOUT / BREAKDOWN
    # --------------------------------------

    recent_high = max(
        prev["high"],
        c3["high"],
        c4["high"],
        c5["high"]
    )

    recent_low = min(
        prev["low"],
        c3["low"],
        c4["low"],
        c5["low"]
    )

    breakout_up = last["close"] > recent_high
    breakout_down = last["close"] < recent_low

    if breakout_up:
        buy += 1

    if breakout_down:
        sell += 1

    # --------------------------------------
    # 6. BODY STRENGTH
    # --------------------------------------

    candle_range = last["high"] - last["low"]
    body = abs(
        last["close"] - last["open"]
    )

    strong_body = False

    if candle_range > 0:
        body_percent = (
            body / candle_range
        ) * 100

        if body_percent >= 45:
            strong_body = True

    # --------------------------------------
    # V17 FILTER
    # --------------------------------------

    signal = "NO_STRONG_SIGNAL"

    # BUY:
    # حداقل 3 امتیاز
    # و هیچ برتری مشخصی برای SELL وجود نداشته باشد.
    if buy >= 3 and buy > sell:

        if strong_body or breakout_up:
            signal = "BUY"

    # SELL:
    # حداقل 3 امتیاز
    # و هیچ برتری مشخصی برای BUY وجود نداشته باشد.
    elif sell >= 3 and sell > buy:

        if strong_body or breakout_down:
            signal = "SELL"

    return (
        signal,
        buy,
        sell,
        last
    )


# ==========================================
# SL / TP
# ==========================================

def calculate_sl_tp(
    signal,
    entry,
    candles
):

    closed = candles[:-1]
    recent = closed[-5:]

    recent_high = max(
        c["high"] for c in recent
    )

    recent_low = min(
        c["low"] for c in recent
    )

    minimum_distance = entry * 0.004

    if signal == "BUY":

        sl = min(
            recent_low,
            entry - minimum_distance
        )

        risk = entry - sl

        if risk <= 0:
            risk = minimum_distance
            sl = entry - risk

        tp = entry + (risk * 2)

    else:

        sl = max(
            recent_high,
            entry + minimum_distance
        )

        risk = sl - entry

        if risk <= 0:
            risk = minimum_distance
            sl = entry + risk

        tp = entry - (risk * 2)

    return sl, tp


# ==========================================
# MAIN
# ==========================================

def main():

    print("================================")
    print("⚡ ATI CRYPTO BOT V17")
    print("================================")

    # --------------------------------------
    # TELEGRAM TEST
    # --------------------------------------

    try:

        send_telegram(
            "⚡ ATI CRYPTO BOT V17\n\n"
            "🔄 Starting...\n"
            "📡 Checking market data..."
        )

        print("✅ Telegram: OK")

    except Exception as error:

        print("❌ Telegram ERROR:")
        print(str(error))
        raise

    # --------------------------------------
    # MARKET DATA
    # --------------------------------------

    try:

        candles, price, source = (
            get_market_data()
        )

        print("✅ MARKET DATA OK")
        print("📊 SOURCE:", source)
        print("₿ BTC:", price)

    except Exception as error:

        print("❌ MARKET DATA ERROR:")
        print(str(error))

        send_telegram(
            "⚠️ ATI CRYPTO BOT V17\n\n"
            "✅ Telegram: OK\n"
            "❌ MARKET DATA ERROR\n\n"
            "ERROR:\n"
            + str(error)
        )

        raise

    # --------------------------------------
    # SIGNAL
    # --------------------------------------

    try:

        (
            signal,
            buy_score,
            sell_score,
            candle
        ) = calculate_signal(candles)

        entry = candle["close"]

        print(
            "BUY SCORE:",
            buy_score
        )

        print(
            "SELL SCORE:",
            sell_score
        )

        print(
            "SIGNAL:",
            signal
        )

    except Exception as error:

        print("❌ SIGNAL ERROR:")
        print(str(error))

        send_telegram(
            "⚠️ ATI CRYPTO BOT V17\n\n"
            "✅ MARKET DATA OK\n"
            "❌ SIGNAL ERROR\n\n"
            + str(error)
        )

        raise

    # --------------------------------------
    # NO SIGNAL
    # --------------------------------------

    if signal == "NO_STRONG_SIGNAL":

        send_telegram(
            "⚪ ATI CRYPTO BOT V17\n\n"
            "₿ BTC: $"
            + f"{price:,.2f}"
            + "\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE CONFIRMED\n"
            "💪 V17 SIGNAL FILTER\n\n"
            "📊 SOURCE: "
            + source
            + "\n"
            "📈 BUY SCORE: "
            + str(buy_score)
            + "/5\n"
            "📉 SELL SCORE: "
            + str(sell_score)
            + "/5\n\n"
            "⚪ NO STRONG SIGNAL\n\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

        return

    # --------------------------------------
    # SL / TP
    # --------------------------------------

    sl, tp = calculate_sl_tp(
        signal,
        entry,
        candles
    )

    move = (
        abs(
            candle["close"]
            - candle["open"]
        )
        / candle["open"]
    ) * 100

    if signal == "BUY":

        signal_text = "🟢 SIGNAL: BUY"

    else:

        signal_text = "🔴 SIGNAL: SELL"

    # --------------------------------------
    # SEND SIGNAL
    # --------------------------------------

    message = (
        "⚡ ATI CRYPTO BOT V17\n\n"
        "₿ BTC: $"
        + f"{price:,.2f}"
        + "\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE CONFIRMED\n"
        "💪 V17 SIGNAL FILTER\n\n"
        "📊 SOURCE: "
        + source
        + "\n\n"
        + signal_text
        + "\n"
        "📈 BUY SCORE: "
        + str(buy_score)
        + "/5\n"
        "📉 SELL SCORE: "
        + str(sell_score)
        + "/5\n"
        "📊 MOVE: "
        + f"{move:.3f}"
        + "%\n\n"
        "💰 Entry: $"
        + f"{entry:,.2f}"
        + "\n"
        "🛑 SL: $"
        + f"{sl:,.2f}"
        + "\n"
        "🎯 TP: $"
        + f"{tp:,.2f}"
        + "\n\n"
        "📊 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING DISABLED"
    )

    send_telegram(message)

    print(
        "✅ SIGNAL SENT TO TELEGRAM"
    )

    print(
        "================================"
    )


# ==========================================
# ERROR HANDLER
# ==========================================

if __name__ == "__main__":

    try:

        main()

    except Exception as error:

        print(
            "================================"
        )

        print(
            "❌ BOT ERROR"
        )

        print(
            str(error)
        )

        print(
            "================================"
        )

        raise
