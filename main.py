import os
import json
import requests
from datetime import datetime, timezone

# =========================================================
# ATI CRYPTO BOT V16
# BTC/USDT - 5 MIN
# PRICE ACTION + STRUCTURE + BREAKOUT
# PAPER / TEST ONLY
# =========================================================

BOT_VERSION = "V16"

BASE_URL = "https://api1.tabdeal.org"
SYMBOL = "BTCUSDT"
TIMEFRAME_MINUTES = 5

HISTORY_FILE = "active_signal.json"
MAX_HISTORY = 300

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ---------------------------------------------------------
# HTTP
# ---------------------------------------------------------

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT/16.0"
})


def get_json(url, params=None, timeout=20):
    response = SESSION.get(
        url,
        params=params,
        timeout=timeout
    )
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------
# TABDEAL PRICE
# ---------------------------------------------------------

def get_current_price():
    data = get_json(
        f"{BASE_URL}/r/api/v1/depth",
        {
            "symbol": SYMBOL,
            "limit": 5
        }
    )

    bids = data.get("bids", [])
    asks = data.get("asks", [])

    if not bids or not asks:
        raise ValueError("Empty order book")

    bid = float(bids[0][0])
    ask = float(asks[0][0])

    return (bid + ask) / 2


# ---------------------------------------------------------
# TABDEAL TRADES
# ---------------------------------------------------------

def get_trades():
    data = get_json(
        f"{BASE_URL}/r/api/v1/trades",
        {
            "symbol": SYMBOL,
            "limit": 1000
        }
    )

    if not isinstance(data, list):
        raise ValueError("Trades API returned invalid data")

    return data


# ---------------------------------------------------------
# TRADE PARSER
# ---------------------------------------------------------

def parse_trade(trade):
    price = None
    quantity = None
    timestamp = None

    if isinstance(trade, dict):

        price = (
            trade.get("price")
            or trade.get("p")
        )

        quantity = (
            trade.get("qty")
            or trade.get("quantity")
            or trade.get("q")
        )

        timestamp = (
            trade.get("time")
            or trade.get("timestamp")
            or trade.get("T")
        )

    elif isinstance(trade, list) and len(trade) >= 2:

        price = trade[0]
        quantity = trade[1]

        if len(trade) >= 3:
            timestamp = trade[2]

    if price is None:
        return None

    try:
        price = float(price)
    except Exception:
        return None

    try:
        quantity = float(quantity) if quantity is not None else 0.0
    except Exception:
        quantity = 0.0

    if timestamp is None:
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)

    try:
        timestamp = int(float(timestamp))
    except Exception:
        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)

    # Convert seconds to milliseconds if necessary
    if timestamp < 10_000_000_000:
        timestamp *= 1000

    return {
        "price": price,
        "quantity": quantity,
        "timestamp": timestamp
    }


# ---------------------------------------------------------
# BUILD 5 MIN CANDLES
# ---------------------------------------------------------

def build_5m_candles(trades):

    candles = {}

    for raw_trade in trades:

        trade = parse_trade(raw_trade)

        if trade is None:
            continue

        ts = trade["timestamp"]
        price = trade["price"]
        qty = trade["quantity"]

        bucket = (ts // 300000) * 300000

        if bucket not in candles:

            candles[bucket] = {
                "timestamp": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty
            }

        else:

            candle = candles[bucket]

            candle["high"] = max(
                candle["high"],
                price
            )

            candle["low"] = min(
                candle["low"],
                price
            )

            candle["close"] = price

            candle["volume"] += qty

    return sorted(
        candles.values(),
        key=lambda x: x["timestamp"]
    )


# ---------------------------------------------------------
# HISTORY
# ---------------------------------------------------------

def load_history():

    if not os.path.exists(HISTORY_FILE):
        return []

    try:
        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if isinstance(data, list):
            return data

    except Exception:
        pass

    return []


def save_history(history):

    history = sorted(
        history,
        key=lambda x: x["timestamp"]
    )

    history = history[-MAX_HISTORY:]

    with open(
        HISTORY_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            history,
            f,
            ensure_ascii=False,
            indent=2
        )


def merge_history(old_history, new_candles):

    merged = {}

    for candle in old_history:
        try:
            merged[int(candle["timestamp"])] = candle
        except Exception:
            continue

    for candle in new_candles:
        merged[int(candle["timestamp"])] = candle

    result = sorted(
        merged.values(),
        key=lambda x: x["timestamp"]
    )

    return result[-MAX_HISTORY:]


# ---------------------------------------------------------
# CLOSED CANDLES ONLY
# ---------------------------------------------------------

def get_closed_candles(candles):

    now_ms = int(
        datetime.now(timezone.utc).timestamp() * 1000
    )

    current_bucket = (
        now_ms // 300000
    ) * 300000

    return [
        candle
        for candle in candles
        if int(candle["timestamp"]) < current_bucket
    ]


# ---------------------------------------------------------
# HELPERS
# ---------------------------------------------------------

def candle_range(c):
    return max(
        float(c["high"]) - float(c["low"]),
        0.00000001
    )


def candle_body(c):
    return abs(
        float(c["close"]) - float(c["open"])
    )


def body_ratio(c):
    return candle_body(c) / candle_range(c)


def is_bullish(c):
    return float(c["close"]) > float(c["open"])


def is_bearish(c):
    return float(c["close"]) < float(c["open"])


def percent_change(a, b):

    if b == 0:
        return 0.0

    return ((a - b) / b) * 100.0


# ---------------------------------------------------------
# MARKET STRUCTURE
# ---------------------------------------------------------

def detect_structure(candles):

    if len(candles) < 12:
        return "SIDEWAYS"

    closes = [
        float(c["close"])
        for c in candles
    ]

    highs = [
        float(c["high"])
        for c in candles
    ]

    lows = [
        float(c["low"])
        for c in candles
    ]

    recent_high = max(highs[-6:])
    previous_high = max(highs[-12:-6])

    recent_low = min(lows[-6:])
    previous_low = min(lows[-12:-6])

    close = closes[-1]

    bullish_points = 0
    bearish_points = 0

    if recent_high > previous_high:
        bullish_points += 1

    if recent_low > previous_low:
        bullish_points += 1

    if recent_high < previous_high:
        bearish_points += 1

    if recent_low < previous_low:
        bearish_points += 1

    if close > previous_high:
        bullish_points += 2

    if close < previous_low:
        bearish_points += 2

    if bullish_points >= 3 and bullish_points > bearish_points:
        return "UPTREND"

    if bearish_points >= 3 and bearish_points > bullish_points:
        return "DOWNTREND"

    return "SIDEWAYS"


# ---------------------------------------------------------
# SUPPORT / RESISTANCE
# ---------------------------------------------------------

def get_levels(candles):

    lookback = candles[-12:]

    resistance = max(
        float(c["high"])
        for c in lookback[:-1]
    )

    support = min(
        float(c["low"])
        for c in lookback[:-1]
    )

    return support, resistance


# ---------------------------------------------------------
# RANGE POSITION
# ---------------------------------------------------------

def range_position(candles):

    lookback = candles[-12:]

    high = max(
        float(c["high"])
        for c in lookback
    )

    low = min(
        float(c["low"])
        for c in lookback
    )

    close = float(candles[-1]["close"])

    total = high - low

    if total <= 0:
        return 50.0

    return ((close - low) / total) * 100.0


# ---------------------------------------------------------
# MOMENTUM
# ---------------------------------------------------------

def momentum_direction(candles):

    if len(candles) < 6:
        return "NEUTRAL"

    close_now = float(candles[-1]["close"])
    close_3 = float(candles[-4]["close"])

    change = percent_change(
        close_now,
        close_3
    )

    if change >= 0.18:
        return "BULLISH"

    if change <= -0.18:
        return "BEARISH"

    return "NEUTRAL"


# ---------------------------------------------------------
# BREAKOUT
# ---------------------------------------------------------

def breakout_direction(candles):

    if len(candles) < 8:
        return "NONE"

    last = candles[-1]

    previous = candles[-6:-1]

    resistance = max(
        float(c["high"])
        for c in previous
    )

    support = min(
        float(c["low"])
        for c in previous
    )

    close = float(last["close"])

    if close > resistance:
        return "BUY"

    if close < support:
        return "SELL"

    return "NONE"


# ---------------------------------------------------------
# CANDLE STRENGTH
# ---------------------------------------------------------

def candle_strength(candles):

    last = candles[-1]

    ratio = body_ratio(last)

    if ratio < 0.55:
        return "WEAK"

    if is_bullish(last):
        return "BULLISH"

    if is_bearish(last):
        return "BEARISH"

    return "WEAK"


# ---------------------------------------------------------
# TOP / BOTTOM PROTECTION
# ---------------------------------------------------------

def top_bottom_filter(candles):

    position = range_position(candles)

    # Near top -> don't chase BUY
    if position >= 88:
        return "TOP"

    # Near bottom -> don't chase SELL
    if position <= 12:
        return "BOTTOM"

    return "NORMAL"


# ---------------------------------------------------------
# SIGNAL ENGINE V16
# ---------------------------------------------------------

def calculate_signal(candles):

    if len(candles) < 25:

        return {
            "signal": "NO SIGNAL",
            "trend": "UNKNOWN",
            "buy_score": 0,
            "sell_score": 0,
            "reason": "Not enough candles"
        }

    trend = detect_structure(candles)

    support, resistance = get_levels(candles)

    last = candles[-1]

    close = float(last["close"])

    momentum = momentum_direction(candles)

    breakout = breakout_direction(candles)

    strength = candle_strength(candles)

    location = top_bottom_filter(candles)

    buy_score = 0
    sell_score = 0

    # =====================================================
    # BUY CONDITIONS
    # =====================================================

    # 1 - Structure
    if trend == "UPTREND":
        buy_score += 1

    # 2 - Breakout
    if breakout == "BUY":
        buy_score += 1

    # 3 - Momentum
    if momentum == "BULLISH":
        buy_score += 1

    # 4 - Candle strength
    if strength == "BULLISH":
        buy_score += 1

    # 5 - Price above resistance / continuation
    if close > resistance:
        buy_score += 1

    # =====================================================
    # SELL CONDITIONS
    # =====================================================

    # 1 - Structure
    if trend == "DOWNTREND":
        sell_score += 1

    # 2 - Breakout
    if breakout == "SELL":
        sell_score += 1

    # 3 - Momentum
    if momentum == "BEARISH":
        sell_score += 1

    # 4 - Candle strength
    if strength == "BEARISH":
        sell_score += 1

    # 5 - Price below support / continuation
    if close < support:
        sell_score += 1

    # =====================================================
    # TOP / BOTTOM SAFETY
    # =====================================================

    if location == "TOP":
        buy_score = min(
            buy_score,
            3
        )

    if location == "BOTTOM":
        sell_score = min(
            sell_score,
            3
        )

    # Never trade sideways
    if trend == "SIDEWAYS":
        return {
            "signal": "NO SIGNAL",
            "trend": trend,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "reason": "Sideways market"
        }

    # Strong BUY
    if (
        buy_score >= 4
        and buy_score > sell_score
        and location != "TOP"
    ):
        return {
            "signal": "BUY",
            "trend": trend,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "reason": "Strong bullish structure"
        }

    # Strong SELL
    if (
        sell_score >= 4
        and sell_score > buy_score
        and location != "BOTTOM"
    ):
        return {
            "signal": "SELL",
            "trend": trend,
            "buy_score": buy_score,
            "sell_score": sell_score,
            "reason": "Strong bearish structure"
        }

    return {
        "signal": "NO SIGNAL",
        "trend": trend,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "reason": "No strong confirmation"
    }


# ---------------------------------------------------------
# SL / TP
# ---------------------------------------------------------

def calculate_sl_tp(candles, signal):

    last = candles[-1]

    entry = float(last["close"])

    recent = candles[-6:]

    recent_high = max(
        float(c["high"])
        for c in recent
    )

    recent_low = min(
        float(c["low"])
        for c in recent
    )

    if signal == "BUY":

        risk = entry - recent_low

        if risk <= 0:
            risk = entry * 0.004

        sl = recent_low
        tp = entry + (risk * 2.0)

        return entry, sl, tp

    if signal == "SELL":

        risk = recent_high - entry

        if risk <= 0:
            risk = entry * 0.004

        sl = recent_high
        tp = entry - (risk * 2.0)

        return entry, sl, tp

    return entry, None, None


# ---------------------------------------------------------
# TELEGRAM
# ---------------------------------------------------------

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        raise ValueError(
            "TELEGRAM_BOT_TOKEN is missing"
        )

    if not TELEGRAM_CHAT_ID:
        raise ValueError(
            "TELEGRAM_CHAT_ID is missing"
        )

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    response = SESSION.post(
        url,
        data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message
        },
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise ValueError(
            "Telegram API returned failure"
        )


# ---------------------------------------------------------
# FORMAT
# ---------------------------------------------------------

def format_price(value):

    if value is None:
        return "-"

    return f"${value:,.2f}"


def candle_time(timestamp):

    dt = datetime.fromtimestamp(
        timestamp / 1000,
        tz=timezone.utc
    )

    return dt.strftime(
        "%Y-%m-%d %H:%M UTC"
    )


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------

def main():

    api_ok = False
    trades_ok = False

    # -----------------------------------------------------
    # PRICE
    # -----------------------------------------------------

    try:

        current_price = get_current_price()
        api_ok = True

    except Exception as e:

        message = (
            "🛡 ATI SAFETY\n\n"
            "❌ BTCUSDT price could not be read.\n\n"
            f"API ERROR: {str(e)}"
        )

        try:
            send_telegram(message)
        except Exception:
            pass

        raise

    # -----------------------------------------------------
    # TRADES
    # -----------------------------------------------------

    try:

        trades = get_trades()

        if not trades:
            raise ValueError(
                "Trades API returned no data"
            )

        trades_ok = True

    except Exception as e:

        message = (
            "🛡 ATI SAFETY\n\n"
            "❌ Trades API could not be read.\n\n"
            f"API ERROR: {str(e)}"
        )

        try:
            send_telegram(message)
        except Exception:
            pass

        raise

    # -----------------------------------------------------
    # BUILD CANDLES
    # -----------------------------------------------------

    new_candles = build_5m_candles(trades)

    if not new_candles:

        raise ValueError(
            "No 5m candles could be created"
        )

    # -----------------------------------------------------
    # HISTORY
    # -----------------------------------------------------

    old_history = load_history()

    merged_history = merge_history(
        old_history,
        new_candles
    )

    save_history(merged_history)

    closed_candles = get_closed_candles(
        merged_history
    )

    if len(closed_candles) < 25:

        message = (
            "⚡ ATI CRYPTO BOT V16\n\n"
            "₿ BTC/USDT\n"
            "⏱ Timeframe: 5m\n"
            "✅ CLOSED CANDLE\n"
            "🧠 PRICE ACTION ENGINE\n\n"
            "📡 TABDEAL API: OK\n"
            "📊 TRADES API: OK\n\n"
            f"📚 Stored Candles: {len(closed_candles)}\n\n"
            "⏳ Waiting for more candle history...\n\n"
            "🛡 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED"
        )

        send_telegram(message)
        return

    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

    result = calculate_signal(
        closed_candles
    )

    signal = result["signal"]
    trend = result["trend"]
    buy_score = result["buy_score"]
    sell_score = result["sell_score"]

    last_candle = closed_candles[-1]

    entry, sl, tp = calculate_sl_tp(
        closed_candles,
        signal
    )

    # -----------------------------------------------------
    # SIGNAL DETAILS
    # -----------------------------------------------------

    if signal == "BUY":

        signal_text = "🟢 STRONG BUY"

        trade_block = (
            "🟢 BUY SIGNAL\n"
            f"💰 Entry: {format_price(entry)}\n"
            f"🛑 SL: {format_price(sl)}\n"
            f"🎯 TP: {format_price(tp)}"
        )

    elif signal == "SELL":

        signal_text = "🔴 STRONG SELL"

        trade_block = (
            "🔴 SELL SIGNAL\n"
            f"💰 Entry: {format_price(entry)}\n"
            f"🛑 SL: {format_price(sl)}\n"
            f"🎯 TP: {format_price(tp)}"
        )

    else:

        signal_text = "⚪ NO SIGNAL"

        trade_block = "⏳ NO TRADE"

    # -----------------------------------------------------
    # MESSAGE
    # -----------------------------------------------------

    message = (
        f"⚡ ATI CRYPTO BOT {BOT_VERSION}\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "🧠 PRICE ACTION + STRUCTURE ENGINE\n\n"
        "📡 TABDEAL API: OK\n"
        "📊 TRADES API: OK\n\n"
        f"🕐 Candle: {candle_time(last_candle['timestamp'])}\n\n"
        f"📚 Stored Candles: {len(closed_candles)}\n\n"
        f"💰 Current: {format_price(current_price)}\n"
        f"💵 Candle Close: {format_price(last_candle['close'])}\n\n"
        f"📊 TREND: {trend}\n\n"
        f"📈 BUY SCORE: {buy_score}/5\n"
        f"📉 SELL SCORE: {sell_score}/5\n\n"
        f"📊 SIGNAL: {signal_text}\n\n"
        f"{trade_block}\n\n"
        "🛡 MODE: PAPER / TEST\n"
        "🚫 REAL TRADING DISABLED\n\n"
        "📡 TELEGRAM: OK"
    )

    send_telegram(message)


if __name__ == "__main__":
    main()
