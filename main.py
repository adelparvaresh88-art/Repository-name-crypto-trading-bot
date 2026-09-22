import os
import json
import requests
from datetime import datetime, timezone

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

BASE_URL = "https://api1.tabdeal.org"

SIGNAL_FILE = "active_signal.json"
STATS_FILE = "ati_stats.json"


# ==========================================
# TELEGRAM
# ==========================================

def send_telegram(message):

    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Telegram secrets missing")
        return

    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=15
    )

    response.raise_for_status()

    print("✅ Telegram: OK")


# ==========================================
# STATISTICS
# ==========================================

def load_stats():

    if not os.path.exists(STATS_FILE):

        # آمار فعلی که تا الان ثبت کرده‌ای
        stats = {
            "tp": 20,
            "sl": 20,
            "buy_tp": 20,
            "buy_sl": 20,
            "sell_tp": 0,
            "sell_sl": 0,
            "net_percent": 10.0
        }

        save_stats(stats)

        return stats

    try:

        with open(
            STATS_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception:

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

    with open(
        STATS_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            stats,
            file,
            indent=2
        )


def update_stats(
    signal,
    result,
    entry,
    exit_price
):

    stats = load_stats()

    entry = float(entry)
    exit_price = float(exit_price)

    # ======================================
    # درصد نتیجه معامله
    # ======================================

    if signal == "BUY":

        trade_percent = (
            (exit_price - entry)
            / entry
        ) * 100

    else:

        trade_percent = (
            (entry - exit_price)
            / entry
        ) * 100

    # ======================================
    # TP / SL
    # ======================================

    if result == "TP":

        stats["tp"] += 1

        if signal == "BUY":
            stats["buy_tp"] += 1
        else:
            stats["sell_tp"] += 1

    elif result == "SL":

        stats["sl"] += 1

        if signal == "BUY":
            stats["buy_sl"] += 1
        else:
            stats["sell_sl"] += 1

    # ======================================
    # NET
    # ======================================

    stats["net_percent"] = round(
        float(stats.get("net_percent", 0))
        + trade_percent,
        4
    )

    save_stats(stats)

    return stats, trade_percent


def statistics_message(stats):

    total = stats["tp"] + stats["sl"]

    if total > 0:

        win_rate = (
            stats["tp"] / total
        ) * 100

    else:

        win_rate = 0

    return (
        "📊 ATI STATISTICS\n\n"
        f"🎯 Total Trades: {total}\n"
        f"✅ TP: {stats['tp']}\n"
        f"❌ SL: {stats['sl']}\n\n"
        f"📈 Win Rate: {win_rate:.1f}%\n\n"
        f"🟢 BUY TP: {stats['buy_tp']}\n"
        f"🛑 BUY SL: {stats['buy_sl']}\n"
        f"🔴 SELL TP: {stats['sell_tp']}\n"
        f"🛑 SELL SL: {stats['sell_sl']}\n\n"
        f"💰 Net P/L: {stats['net_percent']:+.2f}%\n\n"
        "🧪 PAPER / TEST\n"
        "🚫 REAL TRADING DISABLED"
    )


# ==========================================
# MARKET DATA
# ==========================================

def get_trades():

    url = f"{BASE_URL}/r/api/v1/trades"

    response = requests.get(
        url,
        params={
            "symbol": "BTCUSDT",
            "limit": 1000
        },
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):

        trades = data.get(
            "data",
            data.get("result", [])
        )

    else:

        trades = data

    if not isinstance(trades, list):

        raise Exception(
            f"Unexpected API response: {data}"
        )

    return trades


def get_price(trade):

    value = (
        trade.get("price")
        or trade.get("p")
    )

    if value is None:
        return None

    return float(value)


def get_time(trade):

    value = (
        trade.get("time")
        or trade.get("timestamp")
        or trade.get("T")
        or trade.get("ts")
    )

    if value is None:
        return None

    value = int(value)

    if value < 100000000000:
        value *= 1000

    return datetime.fromtimestamp(
        value / 1000,
        tz=timezone.utc
    )


# ==========================================
# CANDLES
# ==========================================

def build_candles(trades):

    candles = {}

    for trade in trades:

        price = get_price(trade)
        trade_time = get_time(trade)

        if price is None or trade_time is None:
            continue

        minute = (
            trade_time.minute // 5
        ) * 5

        candle_time = trade_time.replace(
            minute=minute,
            second=0,
            microsecond=0
        )

        if candle_time not in candles:

            candles[candle_time] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }

        else:

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

    return sorted(candles.items())


# ==========================================
# SIGNAL
# ==========================================

def calculate_signal(candles):

    if len(candles) < 6:

        return "HOLD", 0, 0

    data = [
        item[1]
        for item in candles
    ]

    last = data[-1]
    previous = data[-2]
    three_back = data[-3]

    buy = 0
    sell = 0

    # 1. Candle direction

    if last["close"] > last["open"]:

        buy += 1

    elif last["close"] < last["open"]:

        sell += 1

    # 2. Close comparison

    if last["close"] > previous["close"]:

        buy += 1

    elif last["close"] < previous["close"]:

        sell += 1

    # 3. High / Low breakout

    if last["high"] > previous["high"]:

        buy += 1

    elif last["low"] < previous["low"]:

        sell += 1

    # 4. Candle strength

    candle_range = (
        last["high"]
        - last["low"]
    )

    if candle_range > 0:

        body = abs(
            last["close"]
            - last["open"]
        )

        strength = (
            body / candle_range
        )

        if strength >= 0.55:

            if last["close"] > last["open"]:

                buy += 1

            elif last["close"] < last["open"]:

                sell += 1

    # 5. Three-candle momentum

    if last["close"] > three_back["close"]:

        buy += 1

    elif last["close"] < three_back["close"]:

        sell += 1

    if buy >= 4 and buy > sell:

        return "BUY", buy, sell

    if sell >= 4 and sell > buy:

        return "SELL", buy, sell

    return "HOLD", buy, sell


# ==========================================
# SL / TP
# ==========================================

def calculate_sl_tp(signal, entry):

    if signal == "BUY":

        sl = entry * 0.995
        tp = entry * 1.010

        return sl, tp

    if signal == "SELL":

        sl = entry * 1.005
        tp = entry * 0.990

        return sl, tp

    return None, None


# ==========================================
# ACTIVE SIGNAL
# ==========================================

def load_signal():

    if not os.path.exists(SIGNAL_FILE):

        return None

    try:

        with open(
            SIGNAL_FILE,
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception:

        return None


def save_signal(
    signal,
    entry,
    sl,
    tp,
    candle_time
):

    data = {

        "signal": signal,

        "entry": entry,

        "sl": sl,

        "tp": tp,

        "candle_time": candle_time,

        "created_at":
            datetime.now(
                timezone.utc
            ).isoformat(),

        "active_message_sent": False
    }

    with open(
        SIGNAL_FILE,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            indent=2
        )


def clear_signal():

    if os.path.exists(
        SIGNAL_FILE
    ):

        os.remove(
            SIGNAL_FILE
        )


# ==========================================
# CHECK TP / SL
# ==========================================

def check_active_signal(
    current_price,
    recent_high,
    recent_low
):

    active = load_signal()

    if not active:

        return False

    signal = active["signal"]

    entry = float(
        active["entry"]
    )

    sl = float(
        active["sl"]
    )

    tp = float(
        active["tp"]
    )

    # ======================================
    # BUY
    # ======================================

    if signal == "BUY":

        # TP

        if recent_high >= tp:

            stats, trade_percent = update_stats(
                "BUY",
                "TP",
                entry,
                tp
            )

            message = (
                "🎯 ATI RESULT\n\n"
                "🟢 BUY\n"
                f"Entry: ${entry:,.2f}\n"
                f"TP: ${tp:,.2f}\n"
                f"High: ${recent_high:,.2f}\n\n"
                "✅ TP HIT\n\n"
                f"💰 Trade: +{trade_percent:.2f}%\n\n"
                f"{statistics_message(stats)}"
            )

            send_telegram(message)

            clear_signal()

            return True

        # SL

        if recent_low <= sl:

            stats, trade_percent = update_stats(
                "BUY",
                "SL",
                entry,
                sl
            )

            message = (
                "🛑 ATI RESULT\n\n"
                "🟢 BUY\n"
                f"Entry: ${entry:,.2f}\n"
                f"SL: ${sl:,.2f}\n"
                f"Low: ${recent_low:,.2f}\n\n"
                "❌ SL HIT\n\n"
                f"💰 Trade: {trade_percent:.2f}%\n\n"
                f"{statistics_message(stats)}"
            )

            send_telegram(message)

            clear_signal()

            return True

    # ======================================
    # SELL
    # ======================================

    if signal == "SELL":

        # TP

        if recent_low <= tp:

            stats, trade_percent = update_stats(
                "SELL",
                "TP",
                entry,
                tp
            )

            message = (
                "🎯 ATI RESULT\n\n"
                "🔴 SELL\n"
                f"Entry: ${entry:,.2f}\n"
                f"TP: ${tp:,.2f}\n"
                f"Low: ${recent_low:,.2f}\n\n"
                "✅ TP HIT\n\n"
                f"💰 Trade: +{trade_percent:.2f}%\n\n"
                f"{statistics_message(stats)}"
            )

            send_telegram(message)

            clear_signal()

            return True

        # SL

        if recent_high >= sl:

            stats, trade_percent = update_stats(
                "SELL",
                "SL",
                entry,
                sl
            )

            message = (
                "🛑 ATI RESULT\n\n"
                "🔴 SELL\n"
                f"Entry: ${entry:,.2f}\n"
                f"SL: ${sl:,.2f}\n"
                f"High: ${recent_high:,.2f}\n\n"
                "❌ SL HIT\n\n"
                f"💰 Trade: {trade_percent:.2f}%\n\n"
                f"{statistics_message(stats)}"
            )

            send_telegram(message)

            clear_signal()

            return True

    return False


# ==========================================
# MAIN
# ==========================================

def main():

    print(
        "⚡ ATI CRYPTO BOT - STAGE 8"
    )

    print(
        "₿ BTC/USDT"
    )

    print(
        "⏱ Timeframe: 5m"
    )

    trades = get_trades()

    print(
        f"📊 Trades received: "
        f"{len(trades)}"
    )

    candles = build_candles(
        trades
    )

    print(
        f"🕯 5M candles built: "
        f"{len(candles)}"
    )

    if len(candles) < 6:

        raise Exception(
            "Not enough candles"
        )

    # ======================================
    # CURRENT PRICE
    # ======================================

    prices = []

    for trade in trades:

        price = get_price(trade)

        trade_time = get_time(trade)

        if (
            price is not None
            and trade_time is not None
        ):

            prices.append(
                (
                    trade_time,
                    price
                )
            )

    if not prices:

        raise Exception(
            "Could not get current price"
        )

    prices.sort(
        key=lambda x: x[0]
    )

    current_price = prices[-1][1]

    # ======================================
    # RECENT HIGH / LOW
    # ======================================

    recent_prices = [
        price
        for _, price in prices
    ]

    recent_high = max(
        recent_prices
    )

    recent_low = min(
        recent_prices
    )

    print(
        f"💰 Current: "
        f"${current_price:,.2f}"
    )

    print(
        f"📈 Recent High: "
        f"${recent_high:,.2f}"
    )

    print(
        f"📉 Recent Low: "
        f"${recent_low:,.2f}"
    )

    # ======================================
    # CHECK ACTIVE SIGNAL
    # ======================================

    completed = check_active_signal(
        current_price,
        recent_high,
        recent_low
    )

    if completed:

        print(
            "✅ Active signal completed"
        )

    # ======================================
    # ACTIVE SIGNAL
    # ======================================

    active = load_signal()

    if active:

        print(
            "⏳ Active signal still running"
        )

        print(
            f"📊 Active: "
            f"{active['signal']}"
        )

        print(
            f"💰 Entry: "
            f"${float(active['entry']):,.2f}"
        )

        print(
            f"🛑 SL: "
            f"${float(active['sl']):,.2f}"
        )

        print(
            f"🎯 TP: "
            f"${float(active['tp']):,.2f}"
        )

        if not active.get(
            "active_message_sent",
            False
        ):

            message = (
                "⚡ ATI CRYPTO BOT - STAGE 8\n\n"
                "₿ BTC/USDT\n"
                "⏱ Timeframe: 5m\n"
                "📌 ACTIVE SIGNAL\n\n"
                f"📊 SIGNAL: {active['signal']}\n"
                f"💰 Entry: ${float(active['entry']):,.2f}\n"
                f"🛑 SL: ${float(active['sl']):,.2f}\n"
                f"🎯 TP: ${float(active['tp']):,.2f}\n"
                f"💵 Current: ${current_price:,.2f}\n\n"
                "⏳ Waiting for TP or SL\n\n"
                "🧪 MODE: PAPER / TEST\n"
                "🚫 REAL TRADING DISABLED"
            )

            send_telegram(
                message
            )

            active[
                "active_message_sent"
            ] = True

            with open(
                SIGNAL_FILE,
                "w",
                encoding="utf-8"
            ) as file:

                json.dump(
                    active,
                    file,
                    indent=2
                )

            print(
                "📨 ACTIVE SIGNAL sent once"
            )

        else:

            print(
                "🔕 Duplicate ACTIVE "
                "message blocked"
            )

        return

    # ======================================
    # NEW SIGNAL
    # ======================================

    candle_time, candle = candles[-1]

    entry = candle["close"]

    signal, buy_score, sell_score = (
        calculate_signal(candles)
    )

    sl, tp = calculate_sl_tp(
        signal,
        entry
    )

    # ======================================
    # SAVE STRONG SIGNAL
    # ======================================

    if signal in (
        "BUY",
        "SELL"
    ):

        save_signal(
            signal,
            entry,
            sl,
            tp,
            candle_time.isoformat()
        )

    # ======================================
    # TELEGRAM
    # ======================================

    message = (
        "⚡ ATI CRYPTO BOT - STAGE 8\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "💪 STRONG SIGNAL FILTER\n\n"
        f"📊 SIGNAL: {signal}\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n\n"
        f"🕐 Candle: "
        f"{candle_time.strftime('%H:%M')} UTC\n"
        f"💰 Entry: ${entry:,.2f}\n"
    )

    if signal == "BUY":

        message += (
            "\n🟢 BUY SIGNAL\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n"
        )

    elif signal == "SELL":

        message += (
            "\n🔴 SELL SIGNAL\n"
            f"🛑 SL: ${sl:,.2f}\n"
            f"🎯 TP: ${tp:,.2f}\n"
        )

    else:

        message += (
            "\n⏸ HOLD\n"
            "No strong signal\n"
        )

    message += (
        "\n🧪 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING DISABLED"
    )

    print(message)

    send_telegram(
        message
    )


if __name__ == "__main__":
    main()
