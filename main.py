import os
import json
import requests
from datetime import datetime, timezone

# =========================================================
# ATI CRYPTO BOT - STAGE 8.1
# STRONG PRICE ACTION
# PAPER / TEST ONLY
# =========================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"
SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

ACTIVE_FILE = "active_signal.json"
STATS_FILE = "ati_stats.json"


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Telegram secrets missing")
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
            print("✅ Telegram message sent")
            return True

        print("❌ Telegram error:", response.text)
        return False

    except Exception as e:
        print("❌ Telegram exception:", e)
        return False


# =========================================================
# TABDEAL MARKET DATA
# =========================================================

def get_trades():
    try:
        url = f"{BASE_URL}/r/api/v1/trades"

        response = requests.get(
            url,
            params={
                "symbol": SYMBOL,
                "limit": 1000
            },
            timeout=20
        )

        print("Tabdeal:", response.status_code)

        response.raise_for_status()

        data = response.json()

        if isinstance(data, dict):
            for key in ["data", "results", "trades"]:
                if key in data:
                    data = data[key]
                    break

        if not isinstance(data, list):
            print("❌ Unexpected market data")
            return []

        return data

    except Exception as e:
        print("❌ Tabdeal error:", e)
        return []


# =========================================================
# FLEXIBLE TRADE PARSER
# =========================================================

def parse_trade(item):

    try:
        price = None
        timestamp = None

        if isinstance(item, dict):

            price = (
                item.get("price")
                or item.get("p")
                or item.get("rate")
            )

            timestamp = (
                item.get("timestamp")
                or item.get("time")
                or item.get("T")
            )

        elif isinstance(item, list):

            # Common trade format:
            # [id, price, qty, time]
            if len(item) >= 2:
                price = item[1]

            if len(item) >= 4:
                timestamp = item[3]

        if price is None:
            return None

        price = float(price)

        if timestamp is None:
            timestamp = 0
        else:
            timestamp = float(timestamp)

        # milliseconds -> seconds
        if timestamp > 100000000000:
            timestamp = timestamp / 1000

        return {
            "price": price,
            "time": timestamp
        }

    except Exception:
        return None


# =========================================================
# BUILD 5M CANDLES
# =========================================================

def build_candles(trades):

    parsed = []

    for item in trades:
        trade = parse_trade(item)

        if trade and trade["price"] > 0:
            parsed.append(trade)

    if not parsed:
        return []

    parsed.sort(key=lambda x: x["time"])

    candles = {}

    for trade in parsed:

        ts = trade["time"]

        bucket = int(ts // 300) * 300

        price = trade["price"]

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }

        else:

            candle = candles[bucket]

            candle["high"] = max(candle["high"], price)
            candle["low"] = min(candle["low"], price)
            candle["close"] = price

    result = list(candles.values())

    result.sort(key=lambda x: x["time"])

    return result


# =========================================================
# STRONG SIGNAL ENGINE
# =========================================================

def calculate_strong_signal(candles):

    if len(candles) < 12:
        return "HOLD", 0, 0

    c = candles[-1]

    o = float(c["open"])
    h = float(c["high"])
    l = float(c["low"])
    close = float(c["close"])

    candle_range = h - l

    if candle_range <= 0:
        return "HOLD", 0, 0

    body = abs(close - o)

    upper_wick = h - max(o, close)
    lower_wick = min(o, close) - l

    body_ratio = body / candle_range

    upper_ratio = upper_wick / candle_range
    lower_ratio = lower_wick / candle_range

    buy_score = 0
    sell_score = 0

    # -----------------------------------------------------
    # 1. Candle direction
    # -----------------------------------------------------

    if close > o:
        buy_score += 1

    elif close < o:
        sell_score += 1

    # -----------------------------------------------------
    # 2. Strong body
    # -----------------------------------------------------

    if body_ratio >= 0.55:

        if close > o:
            buy_score += 1

        elif close < o:
            sell_score += 1

    # -----------------------------------------------------
    # 3. Close position
    # -----------------------------------------------------

    close_position = (close - l) / candle_range

    if close_position >= 0.70:
        buy_score += 1

    if close_position <= 0.30:
        sell_score += 1

    # -----------------------------------------------------
    # 4. Three candle momentum
    # -----------------------------------------------------

    c1 = candles[-2]
    c2 = candles[-3]

    if (
        c["close"] > c["open"]
        and c1["close"] > c1["open"]
        and c2["close"] > c2["open"]
    ):
        buy_score += 1

    if (
        c["close"] < c["open"]
        and c1["close"] < c1["open"]
        and c2["close"] < c2["open"]
    ):
        sell_score += 1

    # -----------------------------------------------------
    # 5. Breakout
    # -----------------------------------------------------

    recent_high = max(
        float(x["high"])
        for x in candles[-8:-1]
    )

    recent_low = min(
        float(x["low"])
        for x in candles[-8:-1]
    )

    if close > recent_high:
        buy_score += 1

    if close < recent_low:
        sell_score += 1

    # -----------------------------------------------------
    # 6. Structure
    # -----------------------------------------------------

    p1 = float(candles[-2]["close"])
    p2 = float(candles[-3]["close"])

    if close > p1 > p2:
        buy_score += 1

    if close < p1 < p2:
        sell_score += 1

    # -----------------------------------------------------
    # 7. Wick filter
    # -----------------------------------------------------

    if close > o and upper_ratio <= 0.30:
        buy_score += 1

    if close < o and lower_ratio <= 0.30:
        sell_score += 1

    # -----------------------------------------------------
    # 8. Avoid buying near top / selling near bottom
    # -----------------------------------------------------

    range_high = max(
        float(x["high"])
        for x in candles[-12:-1]
    )

    range_low = min(
        float(x["low"])
        for x in candles[-12:-1]
    )

    total_range = range_high - range_low

    if total_range > 0:

        position = (close - range_low) / total_range

        # BUY only if not too close to top
        if position < 0.80 and close > o:
            buy_score += 1

        # SELL only if not too close to bottom
        if position > 0.20 and close < o:
            sell_score += 1

    # -----------------------------------------------------
    # FINAL FILTER
    # -----------------------------------------------------

    if buy_score >= 6 and buy_score > sell_score:
        return "BUY", buy_score, sell_score

    if sell_score >= 6 and sell_score > buy_score:
        return "SELL", buy_score, sell_score

    return "HOLD", buy_score, sell_score


# =========================================================
# ACTIVE SIGNAL
# =========================================================

def load_active():

    if not os.path.exists(ACTIVE_FILE):
        return None

    try:
        with open(ACTIVE_FILE, "r") as f:
            return json.load(f)

    except Exception:
        return None


def save_active(data):

    with open(ACTIVE_FILE, "w") as f:
        json.dump(data, f, indent=2)


def clear_active():

    if os.path.exists(ACTIVE_FILE):
        os.remove(ACTIVE_FILE)


# =========================================================
# STATISTICS
# =========================================================

def load_stats():

    if os.path.exists(STATS_FILE):

        try:
            with open(STATS_FILE, "r") as f:
                return json.load(f)

        except Exception:
            pass

    # Existing baseline reported by user
    return {
        "tp": 20,
        "sl": 20,
        "buy_tp": 20,
        "buy_sl": 20,
        "sell_tp": 0,
        "sell_sl": 0,
        "net_percent": 10.0
    }


def save_stats(stats):

    with open(STATS_FILE, "w") as f:
        json.dump(stats, f, indent=2)


def update_stats(signal, result):

    stats = load_stats()

    if result == "TP":

        stats["tp"] += 1

        if signal == "BUY":
            stats["buy_tp"] += 1
        else:
            stats["sell_tp"] += 1

        stats["net_percent"] += 1.0

    elif result == "SL":

        stats["sl"] += 1

        if signal == "BUY":
            stats["buy_sl"] += 1
        else:
            stats["sell_sl"] += 1

        stats["net_percent"] -= 0.5

    save_stats(stats)

    return stats


def statistics_message(stats):

    total = stats["tp"] + stats["sl"]

    if total > 0:
        win_rate = stats["tp"] / total * 100
    else:
        win_rate = 0

    return f"""
📊 ATI STATISTICS

🎯 Total Trades: {total}
✅ TP: {stats["tp"]}
❌ SL: {stats["sl"]}

📈 Win Rate: {win_rate:.1f}%

🟢 BUY TP: {stats["buy_tp"]}
🛑 BUY SL: {stats["buy_sl"]}

🔴 SELL TP: {stats["sell_tp"]}
🛑 SELL SL: {stats["sell_sl"]}

💰 Net P/L: {stats["net_percent"]:+.2f}%
"""


# =========================================================
# CHECK ACTIVE TRADE
# =========================================================

def check_active(candles):

    active = load_active()

    if not active:
        return False

    signal = active["signal"]

    entry = float(active["entry"])
    sl = float(active["sl"])
    tp = float(active["tp"])

    candle = candles[-1]

    high = float(candle["high"])
    low = float(candle["low"])

    result = None
    exit_price = None

    if signal == "BUY":

        if low <= sl:
            result = "SL"
            exit_price = sl

        elif high >= tp:
            result = "TP"
            exit_price = tp

    elif signal == "SELL":

        if high >= sl:
            result = "SL"
            exit_price = sl

        elif low <= tp:
            result = "TP"
            exit_price = tp

    if not result:
        return True

    if signal == "BUY":

        if result == "TP":
            pnl = 1.0
        else:
            pnl = -0.5

    else:

        if result == "TP":
            pnl = 1.0
        else:
            pnl = -0.5

    stats = update_stats(signal, result)

    emoji = "🎯" if result == "TP" else "❌"

    message = f"""
🛑 ATI RESULT

{"🟢 BUY" if signal == "BUY" else "🔴 SELL"}

Entry: ${entry:,.2f}
SL: ${sl:,.2f}
TP: ${tp:,.2f}

Exit: ${exit_price:,.2f}

{emoji} {result} HIT

💰 Trade: {pnl:+.2f}%

{statistics_message(stats)}

🧪 PAPER / TEST
🚫 REAL TRADING DISABLED
"""

    send_telegram(message)

    clear_active()

    return False


# =========================================================
# CREATE NEW SIGNAL
# =========================================================

def create_signal(signal, buy_score, sell_score, entry, candle):

    if signal == "BUY":

        sl = entry * 0.995
        tp = entry * 1.010

    else:

        sl = entry * 1.005
        tp = entry * 0.990

    active = {
        "signal": signal,
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "candle_time": candle["time"],
        "created_at": datetime.now(timezone.utc).isoformat()
    }

    save_active(active)

    candle_time = datetime.fromtimestamp(
        candle["time"],
        tz=timezone.utc
    ).strftime("%H:%M UTC")

    message = f"""
⚡ ATI CRYPTO BOT - STAGE 8.1

₿ BTC/USDT
⏱ Timeframe: 5m
✅ CLOSED CANDLE
🔥 STRONG PRICE ACTION FILTER

📊 SIGNAL: {signal}

📈 BUY SCORE: {buy_score}/8
📉 SELL SCORE: {sell_score}/8

🕐 Candle: {candle_time}

💰 Entry: ${entry:,.2f}

{"🟢 BUY SIGNAL" if signal == "BUY" else "🔴 SELL SIGNAL"}

🛑 SL: ${sl:,.2f}
🎯 TP: ${tp:,.2f}

⏳ Waiting for TP or SL

🧪 PAPER / TEST
🚫 REAL TRADING DISABLED
"""

    return send_telegram(message)


# =========================================================
# MAIN
# =========================================================

def main():

    print("===================================")
    print("⚡ ATI CRYPTO BOT - STAGE 8.1")
    print("===================================")

    if not BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN missing")

    if not CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID missing")

    trades = get_trades()

    if not trades:
        print("❌ No trades received")
        return

    print("📊 Trades received:", len(trades))

    candles = build_candles(trades)

    print("🕯 5M candles built:", len(candles))

    if len(candles) < 12:
        print("❌ Not enough candles")
        return

    # -----------------------------------------------------
    # ACTIVE TRADE FIRST
    # -----------------------------------------------------

    was_active = load_active()

    if was_active:

        still_active = check_active(candles)

        if still_active:
            print("⏳ Active trade still running")
            return

        # If trade closed, don't immediately open another
        print("✅ Previous trade closed")
        return

    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

    signal, buy_score, sell_score = calculate_strong_signal(candles)

    candle = candles[-1]

    entry = float(candle["close"])

    print("📊 Signal:", signal)
    print("📈 BUY:", buy_score, "/8")
    print("📉 SELL:", sell_score, "/8")
    print("💰 Entry:", entry)

    # -----------------------------------------------------
    # TELEGRAM ONLY FOR STRONG SIGNAL
    # -----------------------------------------------------

    if signal in ["BUY", "SELL"]:

        sent = create_signal(
            signal,
            buy_score,
            sell_score,
            entry,
            candle
        )

        if sent:
            print("✅ Signal sent to Telegram")
        else:
            print("❌ Signal was NOT sent to Telegram")

    else:

        print("⏸ HOLD - no strong signal")


if __name__ == "__main__":
    main()
