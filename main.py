import os
import time
import requests
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT V26
# ============================================================
# Tabdeal REAL PUBLIC MARKET DATA
#
# IMPORTANT:
# Tabdeal public trades endpoint:
# https://api1.tabdeal.org/r/api/v1/trades
#
# We build 5m candles from real Tabdeal trades.
#
# MODE:
# PAPER / TEST
# REAL TRADING DISABLED
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"

TRADE_LIMIT = 1000
MIN_CANDLES = 35

MIN_SIGNAL_SCORE = 4

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM ERROR: TELEGRAM_BOT_TOKEN is missing")
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM ERROR: TELEGRAM_CHAT_ID is missing")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:

        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=20
        )

        print("TELEGRAM HTTP:", response.status_code)

        if response.ok:
            return True

        print("TELEGRAM RESPONSE:", response.text[:500])
        return False

    except Exception as e:

        print("TELEGRAM ERROR:", e)
        return False


# ============================================================
# TABDEAL PUBLIC TRADES
# ============================================================

def get_tabdeal_trades():

    url = (
        f"{BASE_URL}/r/api/v1/trades"
        f"?symbol={SYMBOL}"
        f"&limit={TRADE_LIMIT}"
    )

    print("TABDEAL TRADES URL:")
    print(url)

    try:

        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent": "ATI-CRYPTO-BOT/26"
            }
        )

    except Exception as e:

        raise RuntimeError(
            f"Tabdeal connection failed: {e}"
        )

    if response.status_code != 200:

        raise RuntimeError(
            f"Tabdeal trades API HTTP "
            f"{response.status_code}: "
            f"{response.text[:300]}"
        )

    try:

        data = response.json()

    except Exception:

        raise RuntimeError(
            "Tabdeal returned invalid JSON"
        )

    if not isinstance(data, list):

        raise RuntimeError(
            f"Unexpected Tabdeal response: "
            f"{str(data)[:500]}"
        )

    if len(data) < 10:

        raise RuntimeError(
            f"Too few trades returned: {len(data)}"
        )

    return data


# ============================================================
# PARSE TRADE
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):

        raise ValueError("Invalid trade object")

    price = item.get("price")
    quantity = item.get("qty")

    timestamp = (
        item.get("time")
        or item.get("timestamp")
    )

    if price is None:
        raise ValueError("Trade price missing")

    if timestamp is None:
        raise ValueError("Trade timestamp missing")

    return {
        "price": float(price),
        "qty": float(quantity or 0),
        "time": int(float(timestamp))
    }


# ============================================================
# BUILD 5 MINUTE CANDLES
# ============================================================

def build_5m_candles(raw_trades):

    trades = []

    for item in raw_trades:

        try:
            trade = parse_trade(item)
            trades.append(trade)

        except Exception as e:

            print(
                "Skipped invalid trade:",
                e
            )

    if len(trades) < 10:

        raise RuntimeError(
            "Not enough valid trades"
        )

    # --------------------------------------------------------
    # Sort oldest -> newest
    # --------------------------------------------------------

    trades.sort(
        key=lambda x: x["time"]
    )

    candles = {}

    FIVE_MIN_MS = 5 * 60 * 1000

    for trade in trades:

        bucket = (
            trade["time"] // FIVE_MIN_MS
        ) * FIVE_MIN_MS

        price = trade["price"]
        qty = trade["qty"]

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
                "trade_count": 1
            }

        else:

            c = candles[bucket]

            c["high"] = max(
                c["high"],
                price
            )

            c["low"] = min(
                c["low"],
                price
            )

            c["close"] = price

            c["volume"] += qty

            c["trade_count"] += 1

    result = list(candles.values())

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# ============================================================
# CHECK CLOSED CANDLE
# ============================================================

def get_closed_candles(candles):

    now_ms = int(
        time.time() * 1000
    )

    FIVE_MIN_MS = 5 * 60 * 1000

    current_bucket = (
        now_ms // FIVE_MIN_MS
    ) * FIVE_MIN_MS

    closed = []

    for candle in candles:

        if candle["time"] < current_bucket:

            closed.append(candle)

    return closed


# ============================================================
# HELPERS
# ============================================================

def average(values):

    if not values:
        return 0.0

    return sum(values) / len(values)


def percent_change(old, new):

    if old == 0:
        return 0.0

    return (
        (new - old) / old
    ) * 100.0


def candle_range(c):

    return max(
        c["high"] - c["low"],
        0.00000001
    )


def candle_body(c):

    return abs(
        c["close"] - c["open"]
    )


def is_bullish(c):

    return c["close"] > c["open"]


def is_bearish(c):

    return c["close"] < c["open"]


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:

        c = candles[-1]

        return candle_range(c)

    true_ranges = []

    for i in range(
        len(candles) - period,
        len(candles)
    ):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(
                current["high"]
                - previous["close"]
            ),
            abs(
                current["low"]
                - previous["close"]
            )
        )

        true_ranges.append(tr)

    return average(true_ranges)


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze(candles):

    if len(candles) < MIN_CANDLES:

        raise RuntimeError(
            f"Not enough 5m candles. "
            f"Got {len(candles)}, "
            f"need {MIN_CANDLES}."
        )

    # Last candle is closed because get_closed_candles()
    # removed the currently forming candle.
    closed = candles[-1]

    previous = candles[:-1]

    recent = previous[-24:]

    if len(recent) < 20:

        raise RuntimeError(
            "Not enough historical candles"
        )

    current_price = closed["close"]

    # --------------------------------------------------------
    # SUPPORT / RESISTANCE
    # --------------------------------------------------------

    resistance = max(
        c["high"]
        for c in recent
    )

    support = min(
        c["low"]
        for c in recent
    )

    # --------------------------------------------------------
    # TREND
    # --------------------------------------------------------

    old_closes = [
        c["close"]
        for c in recent[:10]
    ]

    new_closes = [
        c["close"]
        for c in recent[-10:]
    ]

    old_avg = average(old_closes)
    new_avg = average(new_closes)

    trend_change = percent_change(
        old_avg,
        new_avg
    )

    if trend_change > 0.20:

        trend = "BULLISH"

    elif trend_change < -0.20:

        trend = "BEARISH"

    else:

        trend = "SIDEWAYS"

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    first_half = recent[:12]
    second_half = recent[-12:]

    first_high = max(
        c["high"]
        for c in first_half
    )

    second_high = max(
        c["high"]
        for c in second_half
    )

    first_low = min(
        c["low"]
        for c in first_half
    )

    second_low = min(
        c["low"]
        for c in second_half
    )

    if (
        second_high < first_high
        and
        second_low < first_low
    ):

        structure = "BEARISH"

    elif (
        second_high > first_high
        and
        second_low > first_low
    ):

        structure = "BULLISH"

    else:

        structure = "MIXED"

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    breakout_resistance = max(
        c["high"]
        for c in candles[-8:-1]
    )

    breakout_support = min(
        c["low"]
        for c in candles[-8:-1]
    )

    breakout = "NONE"

    if closed["close"] > breakout_resistance:

        breakout = "BULLISH"

    elif closed["close"] < breakout_support:

        breakout = "BEARISH"

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    retest = "NONE"

    if breakout == "BULLISH":

        tolerance = (
            breakout_resistance * 0.0025
        )

        if (
            closed["low"]
            <= breakout_resistance + tolerance
        ):

            retest = "BULLISH"

    elif breakout == "BEARISH":

        tolerance = (
            breakout_support * 0.0025
        )

        if (
            closed["high"]
            >= breakout_support - tolerance
        ):

            retest = "BEARISH"

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    momentum_reference = candles[-7]["close"]

    momentum_change = percent_change(
        momentum_reference,
        closed["close"]
    )

    if momentum_change > 0.18:

        momentum = "BULLISH"

    elif momentum_change < -0.18:

        momentum = "BEARISH"

    else:

        momentum = "NEUTRAL"

    # --------------------------------------------------------
    # CANDLE STRENGTH
    # --------------------------------------------------------

    body = candle_body(closed)
    rng = candle_range(closed)

    body_ratio = body / rng

    if body_ratio >= 0.65:

        candle_strength = "STRONG"

    elif body_ratio >= 0.35:

        candle_strength = "MEDIUM"

    else:

        candle_strength = "WEAK"

    # --------------------------------------------------------
    # RANGE POSITION
    # --------------------------------------------------------

    total_range = max(
        resistance - support,
        0.00000001
    )

    range_position = (
        (
            current_price - support
        )
        / total_range
    ) * 100

    range_position = max(
        0,
        min(100, range_position)
    )

    # --------------------------------------------------------
    # SCORES
    # --------------------------------------------------------

    buy_score = 0
    sell_score = 0

    buy_reasons = []
    sell_reasons = []

    # 1. Trend
    if trend == "BULLISH":

        buy_score += 1
        buy_reasons.append(
            "bullish trend"
        )

    elif trend == "BEARISH":

        sell_score += 1
        sell_reasons.append(
            "bearish trend"
        )

    # 2. Structure
    if structure == "BULLISH":

        buy_score += 1
        buy_reasons.append(
            "bullish structure"
        )

    elif structure == "BEARISH":

        sell_score += 1
        sell_reasons.append(
            "bearish structure"
        )

    # 3. Breakout = 2 points
    if breakout == "BULLISH":

        buy_score += 2
        buy_reasons.append(
            "resistance breakout"
        )

    elif breakout == "BEARISH":

        sell_score += 2
        sell_reasons.append(
            "support breakdown"
        )

    # 4. Momentum
    if momentum == "BULLISH":

        buy_score += 1
        buy_reasons.append(
            "bullish momentum"
        )

    elif momentum == "BEARISH":

        sell_score += 1
        sell_reasons.append(
            "bearish momentum"
        )

    # 5. Candle
    if candle_strength == "STRONG":

        if is_bullish(closed):

            buy_score += 1
            buy_reasons.append(
                "strong bullish candle"
            )

        elif is_bearish(closed):

            sell_score += 1
            sell_reasons.append(
                "strong bearish candle"
            )

    # 6. Range
    if range_position >= 60:

        buy_score += 1
        buy_reasons.append(
            "upper range"
        )

    elif range_position <= 40:

        sell_score += 1
        sell_reasons.append(
            "lower range"
        )

    # 7. Retest BONUS
    # Retest is NOT mandatory.
    if retest == "BULLISH":

        buy_score += 1
        buy_reasons.append(
            "bullish retest"
        )

    elif retest == "BEARISH":

        sell_score += 1
        sell_reasons.append(
            "bearish retest"
        )

    # 8. Closed candle direction
    if is_bullish(closed):

        buy_score += 1
        buy_reasons.append(
            "closed bullish candle"
        )

    elif is_bearish(closed):

        sell_score += 1
        sell_reasons.append(
            "closed bearish candle"
        )

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    signal = "NO SIGNAL"

    reason = "Waiting for stronger confirmation"

    if (
        buy_score >= MIN_SIGNAL_SCORE
        and
        buy_score > sell_score
    ):

        # Prevent buying into strong bearish conditions
        if not (
            structure == "BEARISH"
            and
            momentum == "BEARISH"
            and
            breakout != "BULLISH"
        ):

            signal = "BUY"

            reason = ", ".join(
                buy_reasons[-3:]
            )

    elif (
        sell_score >= MIN_SIGNAL_SCORE
        and
        sell_score > buy_score
    ):

        # Prevent selling into strong bullish conditions
        if not (
            structure == "BULLISH"
            and
            momentum == "BULLISH"
            and
            breakout != "BEARISH"
        ):

            signal = "SELL"

            reason = ", ".join(
                sell_reasons[-3:]
            )

    return {
        "closed": closed,
        "current_price": current_price,
        "resistance": resistance,
        "support": support,
        "trend": trend,
        "structure": structure,
        "breakout": breakout,
        "retest": retest,
        "momentum": momentum,
        "candle_strength": candle_strength,
        "range_position": range_position,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "signal": signal,
        "reason": reason,
        "candle_count": len(candles)
    }


# ============================================================
# SL / TP
# ============================================================

def calculate_levels(
    signal,
    entry,
    candles
):

    atr = calculate_atr(
        candles,
        14
    )

    sl_distance = max(
        atr * 1.5,
        entry * 0.004
    )

    tp_distance = max(
        atr * 2.5,
        entry * 0.006
    )

    if signal == "BUY":

        sl = entry - sl_distance
        tp = entry + tp_distance

    elif signal == "SELL":

        sl = entry + sl_distance
        tp = entry - tp_distance

    else:

        return None, None

    return sl, tp


# ============================================================
# FORMAT MESSAGE
# ============================================================

def build_message(
    result,
    candle_time,
    candles
):

    signal = result["signal"]

    message = (
        "⚡ ATI CRYPTO BOT V26\n\n"
        "₿ BTC/USDT\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE\n"
        "👀 PRE-BREAKOUT WATCH ENGINE\n\n"
        "📡 TABDEAL API: OK\n"
        "📊 TRADES API: OK\n\n"
        f"🕐 Candle: {candle_time}\n\n"
        f"📚 Stored Candles: "
        f"{result['candle_count']}\n\n"
        f"💰 Current: "
        f"${result['current_price']:,.2f}\n"
        f"💵 Candle Close: "
        f"${result['closed']['close']:,.2f}\n\n"
        f"📊 TREND: {result['trend']}\n"
        f"🏗 STRUCTURE: {result['structure']}\n"
        f"💥 BREAKOUT: {result['breakout']}\n"
        f"🔄 RETEST: {result['retest']}\n"
        f"🚀 MOMENTUM: {result['momentum']}\n"
        f"🕯 CANDLE: "
        f"{result['candle_strength']}\n"
        f"📍 RANGE POSITION: "
        f"{result['range_position']:.1f}%\n\n"
        f"📏 RESISTANCE: "
        f"${result['resistance']:,.2f}\n"
        f"📏 SUPPORT: "
        f"${result['support']:,.2f}\n\n"
        f"📈 BUY SCORE: "
        f"{result['buy_score']}/8\n"
        f"📉 SELL SCORE: "
        f"{result['sell_score']}/8\n\n"
    )

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    if signal == "BUY":

        sl, tp = calculate_levels(
            "BUY",
            result["current_price"],
            candles
        )

        message += (
            "📊 SIGNAL: 🟢 BUY\n"
            f"📝 REASON: "
            f"{result['reason']}\n\n"
            f"💵 ENTRY: "
            f"${result['current_price']:,.2f}\n"
            f"🛑 STOP LOSS: "
            f"${sl:,.2f}\n"
            f"🎯 TAKE PROFIT: "
            f"${tp:,.2f}\n\n"
            "🛡 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED\n\n"
            "📡 TELEGRAM: OK"
        )

    # --------------------------------------------------------
    # SELL
    # --------------------------------------------------------

    elif signal == "SELL":

        sl, tp = calculate_levels(
            "SELL",
            result["current_price"],
            candles
        )

        message += (
            "📊 SIGNAL: 🔴 SELL\n"
            f"📝 REASON: "
            f"{result['reason']}\n\n"
            f"💵 ENTRY: "
            f"${result['current_price']:,.2f}\n"
            f"🛑 STOP LOSS: "
            f"${sl:,.2f}\n"
            f"🎯 TAKE PROFIT: "
            f"${tp:,.2f}\n\n"
            "🛡 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED\n\n"
            "📡 TELEGRAM: OK"
        )

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    else:

        message += (
            "📊 SIGNAL: ⚪ NO SIGNAL\n"
            f"📝 REASON: "
            f"{result['reason']}\n\n"
            "⏳ NO TRADE\n\n"
            "🛡 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING DISABLED\n\n"
            "📡 TELEGRAM: OK"
        )

    return message


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("ATI CRYPTO BOT V26")
    print("TABDEAL PUBLIC TRADES -> 5m CANDLES")
    print("=" * 60)

    try:

        # ----------------------------------------------------
        # 1. Get real Tabdeal trades
        # ----------------------------------------------------

        raw_trades = get_tabdeal_trades()

        print(
            f"TABDEAL API: OK"
        )

        print(
            f"Trades received: "
            f"{len(raw_trades)}"
        )

        # ----------------------------------------------------
        # 2. Build 5m candles
        # ----------------------------------------------------

        all_candles = build_5m_candles(
            raw_trades
        )

        print(
            f"5m candles built: "
            f"{len(all_candles)}"
        )

        # ----------------------------------------------------
        # 3. Remove current forming candle
        # ----------------------------------------------------

        candles = get_closed_candles(
            all_candles
        )

        print(
            f"Closed candles: "
            f"{len(candles)}"
        )

        if len(candles) < MIN_CANDLES:

            raise RuntimeError(
                "Not enough historical 5m "
                "candles from current public "
                "trade batch. "
                f"Only {len(candles)} closed candles "
                f"were built."
            )

        # ----------------------------------------------------
        # 4. Analyze
        # ----------------------------------------------------

        result = analyze(candles)

        # ----------------------------------------------------
        # 5. Candle time
        # ----------------------------------------------------

        timestamp = (
            result["closed"]["time"]
        )

        candle_dt = datetime.fromtimestamp(
            timestamp / 1000,
            tz=timezone.utc
        )

        candle_time = (
            candle_dt.strftime(
                "%Y-%m-%d %H:%M UTC"
            )
        )

        # ----------------------------------------------------
        # 6. Message
        # ----------------------------------------------------

        message = build_message(
            result,
            candle_time,
            candles
        )

        print("\n")
        print(message)
        print("\n")

        # ----------------------------------------------------
        # 7. Telegram
        # ----------------------------------------------------

        if send_telegram(message):

            print(
                "TELEGRAM: OK"
            )

        else:

            print(
                "TELEGRAM: FAILED"
            )

    except Exception as e:

        print(
            "BOT ERROR:",
            type(e).__name__,
            str(e)
        )

        error_message = (
            "🛡 ATI SAFETY\n\n"
            "❌ BOT ERROR\n\n"
            f"{type(e).__name__}: {e}\n\n"
            "🚫 NO TRADE WAS SENT"
        )

        send_telegram(
            error_message
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
