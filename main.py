import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V35.5
# ============================================================

VERSION = "V35.5"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
CANDLE_LIMIT = 60

TOP_RESULTS = 2
MAX_MARKETS = 1000

MIN_SCORE = 4
MIN_MOVE_PERCENT = 0.20

REQUEST_TIMEOUT = 15
SCAN_DELAY = 0.03

# REAL FUTURES SETTINGS
LEVERAGE = 3

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false")
    .strip()
    .lower()
    in ("1", "true", "yes", "on")
)

ORDER_QTY = os.getenv(
    "ORDER_QTY",
    "0.001"
).strip()

TABDEAL_API_KEY = os.getenv(
    "TABDEAL_API_KEY",
    ""
).strip()

TABDEAL_API_SECRET = os.getenv(
    "TABDEAL_API_SECRET",
    ""
).strip()

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN is missing")
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID is missing")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        if response.ok:
            print("Telegram: OK")
            return True

        print(
            "Telegram ERROR:",
            response.status_code,
            response.text
        )

        return False

    except Exception as e:

        print("Telegram ERROR:", e)
        return False


# ============================================================
# HELPERS
# ============================================================

def to_float(value, default=0.0):

    try:
        return float(value)
    except Exception:
        return default


def clean_symbol(symbol):

    if not symbol:
        return ""

    return str(symbol).replace("/", "").replace("-", "").upper()


def api_get(path, params=None):

    url = BASE_URL + path

    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# RESPONSE PARSING
# ============================================================

def first_list(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in (
        "data",
        "result",
        "results",
        "items",
        "symbols",
        "markets",
        "rows"
    ):

        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            for subkey in (
                "data",
                "result",
                "items",
                "symbols",
                "markets",
                "rows"
            ):

                subvalue = value.get(subkey)

                if isinstance(subvalue, list):
                    return subvalue

    return []


def extract_market_list(data):

    return first_list(data)


def extract_rows(data):

    return first_list(data)


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    paths = [
        "/r/api/v1/exchangeInfo",
        "/api/v1/exchangeInfo"
    ]

    last_error = None

    for path in paths:

        try:

            data = api_get(path)

            if data:
                return data

        except Exception as e:

            last_error = e

    raise RuntimeError(
        "exchangeInfo failed: " + str(last_error)
    )


# ============================================================
# USDT MARKETS
# ============================================================

def get_usdt_markets():

    data = get_exchange_info()

    rows = extract_market_list(data)

    markets = []

    for row in rows:

        if isinstance(row, str):

            symbol = clean_symbol(row)

            if symbol.endswith("USDT"):
                markets.append(symbol)

            continue

        if not isinstance(row, dict):
            continue

        symbol = (
            row.get("symbol")
            or row.get("pair")
            or row.get("market")
            or row.get("code")
        )

        symbol = clean_symbol(symbol)

        if not symbol.endswith("USDT"):
            continue

        status = str(
            row.get("status", "TRADING")
        ).upper()

        if status not in (
            "TRADING",
            "ENABLED",
            "ACTIVE",
            "ONLINE",
            ""
        ):
            continue

        markets.append(symbol)

    # Remove duplicates
    markets = list(dict.fromkeys(markets))

    return markets[:MAX_MARKETS]


# ============================================================
# KLINES
# ============================================================

def parse_candle(row):

    if isinstance(row, (list, tuple)):

        if len(row) < 5:
            return None

        return {
            "time": row[0],
            "open": to_float(row[1]),
            "high": to_float(row[2]),
            "low": to_float(row[3]),
            "close": to_float(row[4]),
            "volume": to_float(
                row[5] if len(row) > 5 else 0
            )
        }

    if isinstance(row, dict):

        return {
            "time": (
                row.get("time")
                or row.get("timestamp")
                or row.get("openTime")
                or row.get("open_time")
            ),
            "open": to_float(
                row.get("open")
                or row.get("o")
            ),
            "high": to_float(
                row.get("high")
                or row.get("h")
            ),
            "low": to_float(
                row.get("low")
                or row.get("l")
            ),
            "close": to_float(
                row.get("close")
                or row.get("c")
            ),
            "volume": to_float(
                row.get("volume")
                or row.get("v")
            )
        }

    return None


def get_klines(symbol):

    paths = [
        "/r/api/v1/klines",
        "/api/v1/klines",
        "/r/api/v1/candles"
    ]

    param_variants = [
        {
            "symbol": symbol,
            "interval": TIMEFRAME,
            "limit": CANDLE_LIMIT
        },
        {
            "symbol": symbol,
            "timeframe": TIMEFRAME,
            "limit": CANDLE_LIMIT
        }
    ]

    last_error = None

    for path in paths:

        for params in param_variants:

            try:

                data = api_get(
                    path,
                    params=params
                )

                rows = extract_rows(data)

                candles = []

                for row in rows:

                    candle = parse_candle(row)

                    if candle is None:
                        continue

                    if candle["close"] <= 0:
                        continue

                    candles.append(candle)

                if len(candles) >= 10:

                    candles.sort(
                        key=lambda x: to_float(
                            x["time"]
                        )
                    )

                    return candles

            except Exception as e:

                last_error = e

    raise RuntimeError(
        "Klines failed for "
        + symbol
        + ": "
        + str(last_error)
    )


# ============================================================
# ANALYSIS
# ============================================================

def analyze_symbol(symbol):

    candles = get_klines(symbol)

    if len(candles) < 20:
        return None

    # آخرین کندل ممکن است هنوز باز باشد.
    # بنابراین آخرین کندل را حذف می‌کنیم.
    closed = candles[:-1]

    if len(closed) < 15:
        return None

    current = closed[-1]

    previous = closed[-2]

    lookback = closed[-6:-1]

    if len(lookback) < 5:
        return None

    entry = current["close"]

    if entry <= 0:
        return None

    previous_high = max(
        x["high"]
        for x in lookback
    )

    previous_low = min(
        x["low"]
        for x in lookback
    )

    current_open = current["open"]
    current_high = current["high"]
    current_low = current["low"]
    current_close = current["close"]
    current_volume = current["volume"]

    average_volume = sum(
        x["volume"]
        for x in lookback
    ) / len(lookback)

    score = 0
    reasons = []

    # --------------------------------------------------------
    # 1. BREAKOUT
    # --------------------------------------------------------

    breakout = current_close > previous_high

    if breakout:

        score += 2
        reasons.append("BREAKOUT")

    # --------------------------------------------------------
    # 2. VOLUME
    # --------------------------------------------------------

    volume_ok = (
        average_volume > 0
        and current_volume >= average_volume * 1.20
    )

    if volume_ok:

        score += 1
        reasons.append("VOLUME")

    # --------------------------------------------------------
    # 3. BULLISH CANDLE
    # --------------------------------------------------------

    bullish = current_close > current_open

    if bullish:

        score += 1
        reasons.append("BULLISH")

    # --------------------------------------------------------
    # 4. CLOSE NEAR HIGH
    # --------------------------------------------------------

    candle_range = current_high - current_low

    if candle_range > 0:

        close_position = (
            current_close - current_low
        ) / candle_range

    else:

        close_position = 0

    close_near_high = close_position >= 0.65

    if close_near_high:

        score += 1
        reasons.append("CLOSE_HIGH")

    # --------------------------------------------------------
    # 5. RISING STRUCTURE
    # --------------------------------------------------------

    rising_structure = (
        current_close > previous["close"]
        and previous["close"] >=
        closed[-3]["close"]
    )

    if rising_structure:

        score += 1
        reasons.append("RISING")

    # --------------------------------------------------------
    # 6. MOMENTUM
    # --------------------------------------------------------

    move_percent = (
        (current_close - previous["close"])
        / previous["close"]
    ) * 100

    momentum_ok = move_percent >= MIN_MOVE_PERCENT

    if momentum_ok:

        score += 1
        reasons.append("MOMENTUM")

    # --------------------------------------------------------
    # FINAL FILTER
    # --------------------------------------------------------

    if score < MIN_SCORE:
        return None

    if not breakout:
        return None

    if not bullish:
        return None

    if not momentum_ok:
        return None

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    sl = entry * 0.995
    tp = entry * 1.010

    return {
        "symbol": symbol,
        "side": "BUY",
        "entry": entry,
        "sl": sl,
        "tp": tp,
        "score": score,
        "move_percent": move_percent,
        "volume": current_volume,
        "reasons": reasons
    }


# ============================================================
# SCANNER
# ============================================================

def scan_markets(markets):

    results = []

    total = len(markets)

    print("")
    print(
        "Scanning",
        total,
        "USDT markets..."
    )

    for index, symbol in enumerate(markets, 1):

        try:

            signal = analyze_symbol(symbol)

            if signal:

                results.append(signal)

                print(
                    "SIGNAL:",
                    symbol,
                    "score=",
                    signal["score"],
                    "move=",
                    round(
                        signal["move_percent"],
                        3
                    )
                )

        except Exception as e:

            print(
                "Skip",
                symbol,
                ":",
                str(e)
            )

        time.sleep(SCAN_DELAY)

    results.sort(
        key=lambda x: (
            x["score"],
            x["move_percent"]
        ),
        reverse=True
    )

    return results[:TOP_RESULTS]


# ============================================================
# MESSAGE
# ============================================================

def build_message(
    markets,
    results
):

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = f"""
⚡ ATI CRYPTO BOT {VERSION}

🚀 UPWARD COIN SCANNER

⏱ Timeframe: 5m
✅ CLOSED CANDLE
💥 BREAKOUT + MOMENTUM ENGINE

📡 TABDEAL API: OK
📊 USDT MARKETS: {len(markets)}

🕐 Scan:
{now}
"""

    if not results:

        message += """

⚪ NO STRONG UPWARD SETUP

🚫 NO TRADE
"""

        if LIVE_TRADING:
            message += """
🔴 REAL TRADING: ENABLED
"""

        else:
            message += """
🟢 REAL TRADING: DISABLED
"""

        return message

    message += "\n🔥 TOP UPWARD OPPORTUNITIES\n"

    for index, signal in enumerate(
        results,
        1
    ):

        message += f"""

🟢 #{index} {signal["symbol"]}

📈 BUY
⭐ Score: {signal["score"]}

💰 Entry:
{signal["entry"]:.8f}

🛑 SL:
{signal["sl"]:.8f}

🎯 TP:
{signal["tp"]:.8f}

📊 Move:
{signal["move_percent"]:.2f}%

🔎 Reasons:
{", ".join(signal["reasons"])}
"""

    if LIVE_TRADING:

        message += """
🔴 REAL TRADING: ENABLED
⚡ LEVERAGE: 3x
"""

    else:

        message += """
🟢 REAL TRADING: DISABLED
"""

    return message


# ============================================================
# ORDER QTY
# ============================================================

def validate_order_qty():

    quantity = to_float(
        ORDER_QTY,
        0
    )

    if quantity <= 0:

        raise ValueError(
            "ORDER_QTY must be greater than 0"
        )

    return quantity


# ============================================================
# FUTURES CLIENT
# ============================================================

def create_futures_client():

    if not TABDEAL_API_KEY:

        raise RuntimeError(
            "TABDEAL_API_KEY is missing"
        )

    if not TABDEAL_API_SECRET:

        raise RuntimeError(
            "TABDEAL_API_SECRET is missing"
        )

    try:

        from tabdeal.future import Future

        client = Future(
            TABDEAL_API_KEY,
            TABDEAL_API_SECRET
        )

        return client

    except Exception as e:

        raise RuntimeError(
            "Tabdeal Futures SDK import failed: "
            + str(e)
        )


# ============================================================
# REAL FUTURES ORDER
# ============================================================

def place_real_futures_order(
    symbol,
    side
):

    if not LIVE_TRADING:

        return {
            "ok": False,
            "live": False,
            "message":
                "LIVE_TRADING is disabled"
        }

    validate_order_qty()

    client = create_futures_client()

    try:

        from tabdeal.enums import (
            OrderSides,
            OrderTypes
        )

    except Exception as e:

        raise RuntimeError(
            "Could not import Tabdeal enums: "
            + str(e)
        )

    side_upper = side.upper()

    if side_upper == "BUY":

        order_side = OrderSides.BUY

    elif side_upper == "SELL":

        order_side = OrderSides.SELL

    else:

        raise ValueError(
            "Invalid order side: "
            + str(side)
        )

    quantity = str(
        ORDER_QTY
    )

    print("")
    print(
        "================================"
    )
    print(
        "ATI V35.5 REAL FUTURES ORDER"
    )
    print(
        "SYMBOL:",
        symbol
    )
    print(
        "SIDE:",
        side_upper
    )
    print(
        "QUANTITY:",
        quantity
    )
    print(
        "LEVERAGE:",
        LEVERAGE
    )
    print(
        "================================"
    )

    # --------------------------------------------------------
    # SET LEVERAGE
    # --------------------------------------------------------

    print(
        "Setting leverage to 3x..."
    )

    leverage_result = (
        client.change_leverage(
            symbol=symbol,
            leverage=LEVERAGE
        )
    )

    print(
        "Leverage result:"
    )

    print(
        leverage_result
    )

    # --------------------------------------------------------
    # VERIFY LEVERAGE
    # --------------------------------------------------------

    try:

        verified_leverage = (
            client.get_leverage(
                symbol=symbol
            )
        )

        print(
            "Verified leverage:"
        )

        print(
            verified_leverage
        )

    except Exception as e:

        raise RuntimeError(
            "Leverage verification failed. "
            "REAL ORDER NOT SENT. "
            + str(e)
        )

    # --------------------------------------------------------
    # SEND MARKET ORDER
    # --------------------------------------------------------

    print(
        "Sending REAL FUTURES MARKET ORDER..."
    )

    order = client.new_order(

        symbol=symbol,

        side=order_side,

        type=OrderTypes.MARKET,

        quantity=quantity
    )

    print("")
    print(
        "================================"
    )
    print(
        "REAL ORDER SENT"
    )
    print(
        "================================"
    )

    print(
        order
    )

    return {

        "ok": True,

        "live": True,

        "order": order,

        "leverage_result":
            leverage_result,

        "verified_leverage":
            verified_leverage,

        "configured_leverage":
            LEVERAGE
    }


# ============================================================
# ORDER TELEGRAM
# ============================================================

def send_order_result(
    signal,
    result
):

    if not result.get("ok"):

        message = f"""
⚠️ ATI BOT

❌ REAL ORDER NOT SENT

🪙 Symbol:
{signal.get("symbol", "UNKNOWN")}

📈 Side:
{signal.get("side", "UNKNOWN")}

❗ Reason:
{result.get("message", "Unknown error")}
"""

        send_telegram(message)

        return

    order = result.get(
        "order"
    )

    message = f"""
🚨 ATI CRYPTO BOT {VERSION}

✅ REAL FUTURES ORDER SENT

🪙 Symbol:
{signal.get("symbol", "UNKNOWN")}

📈 Side:
{signal.get("side", "UNKNOWN")}

⚡ Leverage:
3x

💰 Quantity:
{ORDER_QTY}

💵 Entry:
{signal.get("entry", "N/A")}

🛑 SL:
{signal.get("sl", "N/A")}

🎯 TP:
{signal.get("tp", "N/A")}

📌 ORDER RESPONSE:
{order}

🔴 REAL TRADING: ON
"""

    send_telegram(
        message
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print(
        "=========================================="
    )
    print(
        "ATI CRYPTO BOT",
        VERSION
    )
    print(
        "=========================================="
    )

    print(
        "LIVE_TRADING:",
        LIVE_TRADING
    )

    print(
        "LEVERAGE:",
        LEVERAGE
    )

    print(
        "ORDER_QTY:",
        ORDER_QTY
    )

    # --------------------------------------------------------
    # GET MARKETS
    # --------------------------------------------------------

    try:

        markets = get_usdt_markets()

    except Exception as e:

        error_message = f"""
⚡ ATI CRYPTO BOT {VERSION}

❌ TABDEAL API ERROR

{str(e)}
"""

        print(
            error_message
        )

        send_telegram(
            error_message
        )

        return

    if not markets:

        error_message = f"""
⚡ ATI CRYPTO BOT {VERSION}

❌ NO USDT MARKETS FOUND
"""

        print(
            error_message
        )

        send_telegram(
            error_message
        )

        return

    print(
        "USDT MARKETS:",
        len(markets)
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    try:

        results = scan_markets(
            markets
        )

    except Exception as e:

        error_message = f"""
⚡ ATI CRYPTO BOT {VERSION}

❌ SCANNER ERROR

{str(e)}
"""

        print(
            error_message
        )

        send_telegram(
            error_message
        )

        return

    # --------------------------------------------------------
    # TELEGRAM SCAN MESSAGE
    # --------------------------------------------------------

    scan_message = build_message(
        markets,
        results
    )

    print(
        scan_message
    )

    send_telegram(
        scan_message
    )

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if not results:

        print(
            "NO TRADE"
        )

        return

    # --------------------------------------------------------
    # TOP SIGNAL
    # --------------------------------------------------------

    signal = results[0]

    symbol = signal[
        "symbol"
    ]

    side = signal[
        "side"
    ]

    # --------------------------------------------------------
    # PAPER MODE
    # --------------------------------------------------------

    if not LIVE_TRADING:

        print("")
        print(
            "================================"
        )
        print(
            "PAPER MODE"
        )
        print(
            "REAL ORDER NOT SENT"
        )
        print(
            "================================"
        )

        return

    # --------------------------------------------------------
    # REAL ORDER
    # --------------------------------------------------------

    try:

        result = place_real_futures_order(
            symbol,
            side
        )

        send_order_result(
            signal,
            result
        )

    except Exception as e:

        print("")
        print(
            "REAL ORDER ERROR:"
        )

        print(
            str(e)
        )

        error_message = f"""
🚨 ATI CRYPTO BOT {VERSION}

❌ REAL FUTURES ORDER ERROR

🪙 Symbol:
{symbol}

📈 Side:
{side}

⚡ Leverage:
3x

❗ ERROR:
{str(e)}

⛔ ORDER STATUS:
NOT CONFIRMED
"""

        send_telegram(
            error_message
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
