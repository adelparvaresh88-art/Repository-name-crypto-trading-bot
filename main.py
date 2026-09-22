import os
import requests
import time
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT - TABDEAL
# STAGE 8 / PAPER TEST
# ============================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# IMPORTANT:
# Your GitHub Secret is currently named TABDIL_API_KEY.
# We support both names.
TABDEAL_API_KEY = (
    os.getenv("TABDEAL_API_KEY")
    or os.getenv("TABDIL_API_KEY")
)

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

PAPER_MODE = True
REAL_TRADING_ENABLED = False

SIGNAL_THRESHOLD = 4


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram credentials are missing.")
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

        if response.status_code != 200:
            print(response.text)
            return False

        return True

    except Exception as e:
        print("Telegram error:", e)
        return False


# ============================================================
# TABDEAL MARKET DATA
# ============================================================

def get_trades():
    """
    Gets recent BTCUSDT trades from Tabdeal.
    """

    endpoints = [
        f"{BASE_URL}/v1/trades/{SYMBOL}",
        f"{BASE_URL}/v1/trades",
        f"{BASE_URL}/api/v1/trades/{SYMBOL}",
        f"{BASE_URL}/api/v1/trades"
    ]

    last_error = None

    for url in endpoints:

        try:

            params = {
                "symbol": SYMBOL,
                "limit": 1000
            }

            headers = {}

            if TABDEAL_API_KEY:
                headers["Authorization"] = f"Bearer {TABDEAL_API_KEY}"

            response = requests.get(
                url,
                params=params,
                headers=headers,
                timeout=20
            )

            if response.status_code == 200:

                data = response.json()

                if isinstance(data, dict):

                    for key in ["data", "result", "trades"]:
                        if key in data and isinstance(data[key], list):
                            return data[key]

                if isinstance(data, list):
                    return data

            last_error = (
                f"{response.status_code}: "
                f"{response.text[:300]}"
            )

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(
        f"Tabdeal market API failed: {last_error}"
    )


# ============================================================
# BUILD 5 MINUTE CANDLES
# ============================================================

def build_candles(trades):

    candles = {}

    for trade in trades:

        try:

            if isinstance(trade, dict):

                price = (
                    trade.get("price")
                    or trade.get("p")
                    or trade.get("Price")
                )

                quantity = (
                    trade.get("quantity")
                    or trade.get("qty")
                    or trade.get("amount")
                    or trade.get("q")
                )

                timestamp = (
                    trade.get("timestamp")
                    or trade.get("time")
                    or trade.get("T")
                )

            else:
                continue

            if price is None or timestamp is None:
                continue

            price = float(price)

            timestamp = int(timestamp)

            if timestamp > 10_000_000_000:
                timestamp = timestamp // 1000

            candle_time = timestamp - (
                timestamp % 300
            )

            if candle_time not in candles:

                candles[candle_time] = {
                    "time": candle_time,
                    "open": price,
                    "high": price,
                    "low": price,
                    "close": price
                }

            candle = candles[candle_time]

            candle["high"] = max(
                candle["high"],
                price
            )

            candle["low"] = min(
                candle["low"],
                price
            )

            candle["close"] = price

        except Exception:
            continue

    result = list(candles.values())

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# ============================================================
# SIMPLE PRICE-ACTION SIGNAL
# ============================================================

def calculate_signal(candles):

    if len(candles) < 8:
        return {
            "signal": "NO SIGNAL",
            "buy_score": 0,
            "sell_score": 0
        }

    # Last candle is considered the current/open candle.
    # We use the previous closed candle.
    current = candles[-1]
    previous = candles[-2]
    before = candles[-3]

    close = previous["close"]
    open_price = previous["open"]
    high = previous["high"]
    low = previous["low"]

    prev_close = before["close"]

    buy_score = 0
    sell_score = 0

    # --------------------------------------------------------
    # 1 - Candle direction
    # --------------------------------------------------------

    if close > open_price:
        buy_score += 1

    if close < open_price:
        sell_score += 1

    # --------------------------------------------------------
    # 2 - Short momentum
    # --------------------------------------------------------

    if close > prev_close:
        buy_score += 1

    if close < prev_close:
        sell_score += 1

    # --------------------------------------------------------
    # 3 - Recent structure
    # --------------------------------------------------------

    recent = candles[-7:-2]

    recent_high = max(
        c["high"] for c in recent
    )

    recent_low = min(
        c["low"] for c in recent
    )

    if close > recent_high:
        buy_score += 1

    if close < recent_low:
        sell_score += 1

    # --------------------------------------------------------
    # 4 - Candle strength
    # --------------------------------------------------------

    candle_range = high - low

    if candle_range > 0:

        body = abs(close - open_price)

        body_ratio = body / candle_range

        if body_ratio >= 0.55:

            if close > open_price:
                buy_score += 1

            if close < open_price:
                sell_score += 1

    # --------------------------------------------------------
    # 5 - Consecutive direction
    # --------------------------------------------------------

    if (
        candles[-3]["close"]
        > candles[-3]["open"]
        and
        candles[-2]["close"]
        > candles[-2]["open"]
    ):
        buy_score += 1

    if (
        candles[-3]["close"]
        <
        candles[-3]["open"]
        and
        candles[-2]["close"]
        <
        candles[-2]["open"]
    ):
        sell_score += 1

    # --------------------------------------------------------
    # STRONG SIGNAL FILTER
    # --------------------------------------------------------

    if (
        buy_score >= SIGNAL_THRESHOLD
        and
        buy_score > sell_score
    ):

        signal = "BUY"

    elif (
        sell_score >= SIGNAL_THRESHOLD
        and
        sell_score > buy_score
    ):

        signal = "SELL"

    else:

        signal = "NO SIGNAL"

    return {
        "signal": signal,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "price": close,
        "candle_time": previous["time"]
    }


# ============================================================
# SL / TP
# ============================================================

def calculate_sl_tp(signal, entry):

    # 0.50% stop
    stop_percent = 0.005

    # 1.00% target
    target_percent = 0.010

    if signal == "BUY":

        sl = entry * (1 - stop_percent)
        tp = entry * (1 + target_percent)

    elif signal == "SELL":

        sl = entry * (1 + stop_percent)
        tp = entry * (1 - target_percent)

    else:

        sl = None
        tp = None

    return sl, tp


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(result):

    signal = result["signal"]

    price = result["price"]

    buy_score = result["buy_score"]

    sell_score = result["sell_score"]

    candle_time = datetime.fromtimestamp(
        result["candle_time"],
        tz=timezone.utc
    ).strftime("%H:%M UTC")

    message = (
        "⚡ ATI CRYPTO BOT - STAGE 8\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "💪 STRONG SIGNAL FILTER\n\n"
        f"📊 SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n\n"
        f"🕐 Candle: {candle_time}\n"
        f"💰 Entry: ${price:,.2f}\n"
    )

    if signal in ("BUY", "SELL"):

        sl, tp = calculate_sl_tp(
            signal,
            price
        )

        if signal == "BUY":

            message += (
                "\n🟢 BUY SIGNAL\n"
                f"🛑 SL: ${sl:,.2f}\n"
                f"🎯 TP: ${tp:,.2f}\n"
            )

        else:

            message += (
                "\n🔴 SELL SIGNAL\n"
                f"🛑 SL: ${sl:,.2f}\n"
                f"🎯 TP: ${tp:,.2f}\n"
            )

        message += (
            "\n🧪 MODE: PAPER/TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

    else:

        message += (
            "\n⏳ NO STRONG SIGNAL\n"
            "🧪 MODE: PAPER/TEST"
        )

    return message


# ============================================================
# SAFETY CHECK
# ============================================================

def safety_check():

    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is missing.")
        return False

    if not CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID is missing.")
        return False

    # IMPORTANT:
    # Accept both secret names.
    if not TABDEAL_API_KEY:

        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Trade skipped.\n"
            "❌ TABDIL_API_KEY / TABDEAL_API_KEY is missing."
        )

        return False

    return True


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 50)
    print("ATI CRYPTO BOT - STAGE 8")
    print("=" * 50)

    print(
        "Telegram:",
        "OK" if BOT_TOKEN and CHAT_ID else "MISSING"
    )

    print(
        "Tabdeal API Key:",
        "OK" if TABDEAL_API_KEY else "MISSING"
    )

    print(
        "Paper Mode:",
        PAPER_MODE
    )

    print(
        "Real Trading:",
        REAL_TRADING_ENABLED
    )

    # --------------------------------------------------------
    # SAFETY
    # --------------------------------------------------------

    if not safety_check():

        return

    # --------------------------------------------------------
    # MARKET DATA
    # --------------------------------------------------------

    try:

        trades = get_trades()

        print(
            f"📊 Trades received: {len(trades)}"
        )

    except Exception as e:

        print(
            "Market API error:",
            e
        )

        send_telegram(
            "⚠️ ATI BOT ERROR\n\n"
            f"❌ Market API error\n"
            f"{str(e)[:500]}"
        )

        return

    # --------------------------------------------------------
    # CANDLES
    # --------------------------------------------------------

    candles = build_candles(trades)

    print(
        f"🕯 5M candles built: {len(candles)}"
    )

    if len(candles) < 8:

        send_telegram(
            "⚠️ ATI BOT\n\n"
            "Not enough 5M candles."
        )

        return

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    result = calculate_signal(candles)

    print(
        "Signal:",
        result["signal"]
    )

    print(
        "BUY:",
        result["buy_score"],
        "SELL:",
        result["sell_score"]
    )

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    message = format_signal(result)

    send_telegram(message)

    print("✅ ATI BOT FINISHED")


if __name__ == "__main__":
    main()
