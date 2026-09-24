import os
import requests
from datetime import datetime, timezone

# =========================================================
# ATI CRYPTO BOT V29
# UPWARD COIN SCANNER
# TABDEAL USDT MARKET SCANNER
# PAPER / TEST ONLY
# REAL TRADING DISABLED
# =========================================================

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

TRADE_LIMIT = 1000
MIN_CANDLES = 35

# Maximum number of USDT markets to analyze
MAX_SYMBOLS = 20

# Minimum 24h movement to enter scanner priority
MIN_24H_CHANGE = 1.0

# Breakout settings
BREAKOUT_LOOKBACK = 7
BREAKOUT_BUFFER = 0.03

# Retest
RETEST_TOLERANCE = 0.25

# Momentum
MOMENTUM_LOOKBACK = 6
MOMENTUM_THRESHOLD = 0.10

# Maximum results sent to Telegram
MAX_RESULTS = 5

# SL / TP
SL_PERCENT_MIN = 0.40
TP_PERCENT_MIN = 0.60

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(message):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM credentials missing")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=20
        )

        response.raise_for_status()

        return True

    except Exception as e:

        print("Telegram error:", e)

        return False


# =========================================================
# GENERIC GET
# =========================================================

def api_get(path, params=None):

    url = f"{BASE_URL}{path}"

    response = requests.get(
        url,
        params=params,
        timeout=20
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# GET MARKET INFORMATION
# =========================================================

def get_market_information():

    data = api_get(
        "/r/api/v1/exchangeInfo"
    )

    if isinstance(data, dict):

        if "data" in data:
            data = data["data"]

        elif "result" in data:
            data = data["result"]

        elif "symbols" in data:
            data = data["symbols"]

    if not isinstance(data, list):

        raise RuntimeError(
            "Unexpected exchangeInfo response"
        )

    return data


# =========================================================
# EXTRACT SYMBOL
# =========================================================

def get_symbol(item):

    if not isinstance(item, dict):
        return None

    symbol = (
        item.get("symbol")
        or item.get("Symbol")
    )

    if not symbol:
        return None

    return str(symbol).upper().replace("_", "")


# =========================================================
# CHECK WHETHER MARKET IS ACTIVE
# =========================================================

def is_active_market(item):

    if not isinstance(item, dict):
        return True

    status = (
        item.get("status")
        or item.get("Status")
    )

    if status is None:
        return True

    return str(status).upper() in [
        "TRADING",
        "ACTIVE",
        "ENABLED"
    ]


# =========================================================
# GET USDT SYMBOLS
# =========================================================

def get_usdt_symbols():

    markets = get_market_information()

    symbols = []

    for item in markets:

        if not is_active_market(item):
            continue

        symbol = get_symbol(item)

        if not symbol:
            continue

        if not symbol.endswith("USDT"):
            continue

        if symbol == "USDTUSDT":
            continue

        symbols.append(symbol)

    symbols = sorted(
        list(set(symbols))
    )

    return symbols


# =========================================================
# GET RECENT TRADES
# =========================================================

def get_trades(symbol):

    return api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": TRADE_LIMIT
        }
    )


# =========================================================
# PARSE TRADE
# =========================================================

def parse_trade(trade):

    price = None
    timestamp = None

    if isinstance(trade, dict):

        for key in [
            "price",
            "p"
        ]:

            if key in trade:

                try:

                    price = float(
                        trade[key]
                    )

                    break

                except:
                    pass

        for key in [
            "timestamp",
            "time",
            "T",
            "created_at"
        ]:

            if key in trade:

                try:

                    timestamp = int(
                        float(
                            trade[key]
                        )
                    )

                    break

                except:
                    pass

    elif isinstance(trade, list):

        if len(trade) >= 2:

            try:

                price = float(
                    trade[0]
                )

                timestamp = int(
                    float(
                        trade[1]
                    )
                )

            except:
                pass

    if price is None or timestamp is None:
        return None

    # Convert seconds to milliseconds
    if timestamp < 10_000_000_000:
        timestamp *= 1000

    return price, timestamp


# =========================================================
# BUILD 5M CANDLES
# =========================================================

def build_5m_candles(trades):

    buckets = {}

    for raw_trade in trades:

        parsed = parse_trade(
            raw_trade
        )

        if not parsed:
            continue

        price, timestamp = parsed

        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price
            }

        else:

            candle = buckets[bucket]

            if price > candle["high"]:
                candle["high"] = price

            if price < candle["low"]:
                candle["low"] = price

            candle["close"] = price

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    # Remove current forming candle
    if candles:

        now_ms = int(
            datetime.now(
                timezone.utc
            ).timestamp() * 1000
        )

        current_bucket = (
            now_ms // 300000
        ) * 300000

        candles = [
            candle
            for candle in candles
            if candle["time"] < current_bucket
        ]

    return candles


# =========================================================
# CANDLE DIRECTION
# =========================================================

def candle_direction(candle):

    if candle["close"] > candle["open"]:
        return "BULLISH"

    if candle["close"] < candle["open"]:
        return "BEARISH"

    return "NEUTRAL"


# =========================================================
# CANDLE STRENGTH
# =========================================================

def candle_strength(candle):

    candle_range = (
        candle["high"] -
        candle["low"]
    )

    if candle_range <= 0:
        return "WEAK"

    body = abs(
        candle["close"] -
        candle["open"]
    )

    ratio = body / candle_range

    if ratio >= 0.65:
        return "STRONG"

    if ratio >= 0.35:
        return "MEDIUM"

    return "WEAK"


# =========================================================
# PERCENT CHANGE
# =========================================================

def percent_change(old, new):

    if old == 0:
        return 0

    return (
        (new - old) /
        old
    ) * 100


# =========================================================
# ANALYZE SYMBOL
# =========================================================

def analyze_symbol(
    symbol,
    candles,
    change_24h=None
):

    if len(candles) < MIN_CANDLES:
        return None

    last = candles[-1]

    # -----------------------------------------------------
    # SUPPORT / RESISTANCE
    # -----------------------------------------------------

    recent = candles[-24:]

    support = min(
        c["low"]
        for c in recent
    )

    resistance = max(
        c["high"]
        for c in recent
    )

    # -----------------------------------------------------
    # TREND
    # -----------------------------------------------------

    first_10 = candles[-20:-10]
    last_10 = candles[-10:]

    avg_first = (
        sum(
            c["close"]
            for c in first_10
        )
        /
        len(first_10)
    )

    avg_last = (
        sum(
            c["close"]
            for c in last_10
        )
        /
        len(last_10)
    )

    trend_change = percent_change(
        avg_first,
        avg_last
    )

    if trend_change > 0.20:

        trend = "BULLISH"

    elif trend_change < -0.20:

        trend = "BEARISH"

    else:

        trend = "SIDEWAYS"

    # -----------------------------------------------------
    # STRUCTURE
    # -----------------------------------------------------

    structure_data = candles[-12:]

    first_half = structure_data[:6]
    second_half = structure_data[6:]

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
        second_high > first_high
        and
        second_low > first_low
    ):

        structure = "BULLISH"

    elif (
        second_high < first_high
        and
        second_low < first_low
    ):

        structure = "BEARISH"

    else:

        structure = "MIXED"

    # -----------------------------------------------------
    # BREAKOUT
    # -----------------------------------------------------

    previous = candles[
        -(BREAKOUT_LOOKBACK + 1):-1
    ]

    previous_high = max(
        c["high"]
        for c in previous
    )

    previous_low = min(
        c["low"]
        for c in previous
    )

    bullish_breakout = (
        last["close"]
        >
        previous_high *
        (
            1 +
            BREAKOUT_BUFFER / 100
        )
    )

    bearish_breakout = (
        last["close"]
        <
        previous_low *
        (
            1 -
            BREAKOUT_BUFFER / 100
        )
    )

    if bullish_breakout:
        breakout = "BULLISH"

    elif bearish_breakout:
        breakout = "BEARISH"

    else:
        breakout = "NONE"

    # -----------------------------------------------------
    # RETEST
    # -----------------------------------------------------

    retest = "NONE"

    if bullish_breakout:

        distance = (
            abs(
                last["low"] -
                previous_high
            )
            /
            previous_high
        ) * 100

        if distance <= RETEST_TOLERANCE:
            retest = "BULLISH"

    elif bearish_breakout:

        distance = (
            abs(
                last["high"] -
                previous_low
            )
            /
            previous_low
        ) * 100

        if distance <= RETEST_TOLERANCE:
            retest = "BEARISH"

    # -----------------------------------------------------
    # MOMENTUM
    # -----------------------------------------------------

    momentum_start = candles[
        -MOMENTUM_LOOKBACK - 1
    ]["close"]

    momentum_change = percent_change(
        momentum_start,
        last["close"]
    )

    if momentum_change >= MOMENTUM_THRESHOLD:

        momentum = "BULLISH"

    elif momentum_change <= -MOMENTUM_THRESHOLD:

        momentum = "BEARISH"

    else:

        momentum = "NEUTRAL"

    # -----------------------------------------------------
    # CANDLE
    # -----------------------------------------------------

    direction = candle_direction(
        last
    )

    strength = candle_strength(
        last
    )

    # -----------------------------------------------------
    # RANGE POSITION
    # -----------------------------------------------------

    total_range = (
        resistance -
        support
    )

    if total_range > 0:

        range_position = (
            (
                last["close"] -
                support
            )
            /
            total_range
        ) * 100

    else:

        range_position = 50

    # -----------------------------------------------------
    # BULLISH CONDITIONS
    # -----------------------------------------------------

    buy_conditions = 0

    if trend == "BULLISH":
        buy_conditions += 1

    if structure == "BULLISH":
        buy_conditions += 1

    if bullish_breakout:
        buy_conditions += 1

    if retest == "BULLISH":
        buy_conditions += 1

    if momentum == "BULLISH":
        buy_conditions += 1

    if direction == "BULLISH":
        buy_conditions += 1

    if strength in [
        "STRONG",
        "MEDIUM"
    ]:
        buy_conditions += 1

    # -----------------------------------------------------
    # SELL CONDITIONS
    # -----------------------------------------------------

    sell_conditions = 0

    if trend == "BEARISH":
        sell_conditions += 1

    if structure == "BEARISH":
        sell_conditions += 1

    if bearish_breakout:
        sell_conditions += 1

    if retest == "BEARISH":
        sell_conditions += 1

    if momentum == "BEARISH":
        sell_conditions += 1

    if direction == "BEARISH":
        sell_conditions += 1

    if strength in [
        "STRONG",
        "MEDIUM"
    ]:
        sell_conditions += 1

    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

    signal = "NO SIGNAL"

    reason = "No confirmed setup"

    # Strong BUY
    if (
        bullish_breakout
        and
        direction == "BULLISH"
        and
        strength in [
            "STRONG",
            "MEDIUM"
        ]
        and
        (
            retest == "BULLISH"
            or
            momentum == "BULLISH"
        )
    ):

        signal = "BUY"

        reason = (
            "Bullish breakout confirmed"
        )

    # WATCH BUY
    elif (
        not bullish_breakout
        and
        trend == "BULLISH"
        and
        structure == "BULLISH"
        and
        momentum == "BULLISH"
        and
        direction == "BULLISH"
        and
        strength in [
            "STRONG",
            "MEDIUM"
        ]
    ):

        signal = "WATCH BUY"

        reason = (
            "Strong bullish setup "
            "before breakout"
        )

    # -----------------------------------------------------
    # SCANNER SCORE
    # -----------------------------------------------------

    scanner_score = 0

    if trend == "BULLISH":
        scanner_score += 1

    if structure == "BULLISH":
        scanner_score += 1

    if bullish_breakout:
        scanner_score += 2

    if retest == "BULLISH":
        scanner_score += 1

    if momentum == "BULLISH":
        scanner_score += 1

    if direction == "BULLISH":
        scanner_score += 1

    if strength in [
        "STRONG",
        "MEDIUM"
    ]:
        scanner_score += 1

    # Bonus for 24h positive movement
    if (
        change_24h is not None
        and
        change_24h >= MIN_24H_CHANGE
    ):
        scanner_score += 1

    return {
        "symbol": symbol,
        "price": last["close"],
        "candles": len(candles),
        "trend": trend,
        "structure": structure,
        "breakout": breakout,
        "retest": retest,
        "momentum": momentum,
        "momentum_change": momentum_change,
        "direction": direction,
        "strength": strength,
        "range_position": range_position,
        "resistance": resistance,
        "support": support,
        "buy_conditions": buy_conditions,
        "sell_conditions": sell_conditions,
        "signal": signal,
        "reason": reason,
        "scanner_score": scanner_score,
        "change_24h": change_24h
    }


# =========================================================
# GET 24H CHANGE
# =========================================================

def get_24h_change(symbol):

    # Try common Tabdeal public ticker endpoint.
    endpoints = [
        "/r/api/v1/ticker/24hr",
        "/r/api/v1/ticker"
    ]

    for endpoint in endpoints:

        try:

            data = api_get(
                endpoint,
                {"symbol": symbol}
            )

            if isinstance(data, dict):

                if "data" in data:
                    data = data["data"]

                elif "result" in data:
                    data = data["result"]

                for key in [
                    "priceChangePercent",
                    "price_change_percent",
                    "changePercent",
                    "change_percentage"
                ]:

                    if key in data:

                        return float(
                            data[key]
                        )

        except:

            continue

    return None


# =========================================================
# SL / TP
# =========================================================

def calculate_levels(
    price,
    signal,
    candles
):

    recent = candles[-14:]

    ranges = [
        c["high"] -
        c["low"]
        for c in recent
        if c["high"] >
        c["low"]
    ]

    if ranges:

        atr = (
            sum(ranges) /
            len(ranges)
        )

    else:

        atr = price * 0.004

    sl_distance = max(
        atr * 1.5,
        price *
        (SL_PERCENT_MIN / 100)
    )

    tp_distance = max(
        atr * 2.5,
        price *
        (TP_PERCENT_MIN / 100)
    )

    if signal == "BUY":

        sl = price - sl_distance
        tp = price + tp_distance

    else:

        sl = price + sl_distance
        tp = price - tp_distance

    return sl, tp


# =========================================================
# SCANNER
# =========================================================

def scan_markets():

    symbols = get_usdt_symbols()

    print(
        f"Found {len(symbols)} USDT markets"
    )

    # First collect basic 24h changes.
    candidates = []

    for symbol in symbols:

        try:

            change = get_24h_change(
                symbol
            )

            candidates.append(
                (
                    symbol,
                    change
                )
            )

        except:

            continue

    # Prefer positive movers.
    candidates.sort(
        key=lambda x: (
            x[1]
            if x[1] is not None
            else -999
        ),
        reverse=True
    )

    # Limit API load.
    candidates = candidates[
        :MAX_SYMBOLS
    ]

    results = []

    for symbol, change in candidates:

        try:

            print(
                f"Scanning {symbol}..."
            )

            trades = get_trades(
                symbol
            )

            candles = build_5m_candles(
                trades
            )

            analysis = analyze_symbol(
                symbol,
                candles,
                change
            )

            if analysis:

                # Keep only useful upward setups.
                if analysis["signal"] in [
                    "BUY",
                    "WATCH BUY"
                ]:

                    results.append(
                        analysis
                    )

        except Exception as e:

            print(
                f"Skip {symbol}: {e}"
            )

    # Highest scanner score first.
    results.sort(
        key=lambda x: (
            x["scanner_score"],
            x["momentum_change"],
            x["change_24h"]
            if x["change_24h"] is not None
            else -999
        ),
        reverse=True
    )

    return results[:MAX_RESULTS], len(symbols)


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def create_message(
    results,
    total_symbols
):

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = f"""
⚡ ATI CRYPTO BOT V29

🔎 UPWARD COIN SCANNER

⏱ Timeframe: 5m
✅ CLOSED CANDLE
🚀 BREAKOUT + RETEST ENGINE

📡 TABDEAL API: OK
📊 MARKET SCANNER: OK

🕐 Scan:
{now}

🔢 USDT MARKETS FOUND:
{total_symbols}

📊 RESULTS:
"""

    if not results:

        message += """
⚪ NO STRONG UPWARD SETUP

⏳ No confirmed BUY or strong WATCH BUY found.

🚫 NO TRADE
"""

    else:

        for index, result in enumerate(
            results,
            start=1
        ):

            symbol = result["symbol"]

            price = result["price"]

            change = result["change_24h"]

            if change is None:
                change_text = "N/A"
            else:
                change_text = f"{change:+.2f}%"

            message += f"""
━━━━━━━━━━━━━━━━━━
#{index} {symbol}

💰 Price:
${price:,.8f}

📈 24H:
{change_text}

📊 SCORE:
{result["scanner_score"]}/9

📊 Trend:
{result["trend"]}

🏗 Structure:
{result["structure"]}

💥 Breakout:
{result["breakout"]}

🔄 Retest:
{result["retest"]}

🚀 Momentum:
{result["momentum"]}
{result["momentum_change"]:+.3f}%

🕯 Candle:
{result["direction"]} /
{result["strength"]}

📈 BUY CONDITIONS:
{result["buy_conditions"]}/7

📊 SIGNAL:
"""

            if result["signal"] == "BUY":

                sl, tp = calculate_levels(
                    price,
                    "BUY",
                    []
                )

                # Recalculate using minimum percentages
                sl = price * (
                    1 -
                    SL_PERCENT_MIN / 100
                )

                tp = price * (
                    1 +
                    TP_PERCENT_MIN / 100
                )

                message += f"""
🟢 BUY

📝 {result["reason"]}

💰 ENTRY:
${price:,.8f}

🛑 SL:
${sl:,.8f}

🎯 TP:
${tp:,.8f}
"""

            else:

                message += f"""
🟡 WATCH BUY

📝 {result["reason"]}

⏳ Waiting for bullish breakout.
🚫 NO TRADE
"""

    message += """

━━━━━━━━━━━━━━━━━━

🛡 MODE: PAPER / TEST
🚫 REAL TRADING DISABLED

📡 TELEGRAM: OK
"""

    return message


# =========================================================
# MAIN
# =========================================================

def main():

    try:

        results, total_symbols = scan_markets()

        message = create_message(
            results,
            total_symbols
        )

        print(message)

        send_telegram(
            message
        )

    except Exception as e:

        error_message = f"""
🛡 ATI SAFETY

❌ SCANNER ERROR

{type(e).__name__}: {e}

🚫 NO TRADE

🛡 REAL TRADING DISABLED
"""

        print(error_message)

        send_telegram(
            error_message
        )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
