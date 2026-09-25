import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V36
# ============================================================

VERSION = "V36.0"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
CANDLE_LIMIT = 60

MAX_MARKETS = 1000
TOP_RESULTS = 5

REQUEST_TIMEOUT = 15
SCAN_DELAY = 0.03

# Real trading
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
        print("TELEGRAM_BOT_TOKEN missing")
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID missing")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:

        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
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

    except Exception as e:

        print(
            "Telegram ERROR:",
            e
        )

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

    return (
        str(symbol)
        .replace("/", "")
        .replace("-", "")
        .upper()
    )


def api_get(path, params=None):

    url = BASE_URL + path

    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()


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
        "exchangeInfo failed: "
        + str(last_error)
    )


# ============================================================
# MARKETS
# ============================================================

def get_usdt_markets():

    data = get_exchange_info()

    rows = first_list(data)

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
            "",
            "TRADING",
            "ENABLED",
            "ACTIVE",
            "ONLINE"
        ):
            continue

        markets.append(symbol)

    return list(
        dict.fromkeys(markets)
    )[:MAX_MARKETS]


# ============================================================
# CANDLE PARSER
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
            "time":
                row.get("time")
                or row.get("timestamp")
                or row.get("openTime")
                or row.get("open_time"),

            "open":
                to_float(
                    row.get("open")
                    or row.get("o")
                ),

            "high":
                to_float(
                    row.get("high")
                    or row.get("h")
                ),

            "low":
                to_float(
                    row.get("low")
                    or row.get("l")
                ),

            "close":
                to_float(
                    row.get("close")
                    or row.get("c")
                ),

            "volume":
                to_float(
                    row.get("volume")
                    or row.get("v")
                )
        }

    return None


# ============================================================
# GET 5M CANDLES
# ============================================================

def get_klines(symbol):

    paths = [
        "/r/api/v1/klines",
        "/api/v1/klines",
        "/r/api/v1/candles"
    ]

    params_list = [

        {
            "symbol": symbol,
            "interval": "5m",
            "limit": CANDLE_LIMIT
        },

        {
            "symbol": symbol,
            "timeframe": "5m",
            "limit": CANDLE_LIMIT
        }
    ]

    last_error = None

    for path in paths:

        for params in params_list:

            try:

                data = api_get(
                    path,
                    params
                )

                rows = first_list(data)

                candles = []

                for row in rows:

                    candle = parse_candle(row)

                    if not candle:
                        continue

                    if candle["close"] <= 0:
                        continue

                    candles.append(candle)

                if len(candles) >= 20:

                    candles.sort(
                        key=lambda x:
                        to_float(x["time"])
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
# PERCENT MOVE
# ============================================================

def percent_change(old, new):

    if old <= 0:
        return 0.0

    return (
        (new - old)
        / old
    ) * 100.0


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(candles):

    if len(candles) < 10:
        return 0.0

    current_volume = candles[-1]["volume"]

    previous = candles[-6:-1]

    if not previous:
        return 0.0

    avg_volume = sum(
        x["volume"]
        for x in previous
    ) / len(previous)

    if avg_volume <= 0:
        return 0.0

    return current_volume / avg_volume


# ============================================================
# ANALYZE MARKET
# ============================================================

def analyze_symbol(symbol):

    candles = get_klines(symbol)

    # آخرین کندل باز حذف می‌شود
    closed = candles[:-1]

    if len(closed) < 20:
        return None

    current = closed[-1]

    close_now = current["close"]

    if close_now <= 0:
        return None

    # --------------------------------------------------------
    # 5 MINUTE
    # --------------------------------------------------------

    close_5m = closed[-2]["close"]

    move_5m = percent_change(
        close_5m,
        close_now
    )

    # --------------------------------------------------------
    # 15 MINUTE
    # --------------------------------------------------------

    close_15m = closed[-4]["close"]

    move_15m = percent_change(
        close_15m,
        close_now
    )

    # --------------------------------------------------------
    # 1 HOUR
    # --------------------------------------------------------

    close_1h = closed[-13]["close"]

    move_1h = percent_change(
        close_1h,
        close_now
    )

    # --------------------------------------------------------
    # LAST 1 HOUR HIGH
    # --------------------------------------------------------

    hour_candles = closed[-13:-1]

    hour_high = max(
        x["high"]
        for x in hour_candles
    )

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    breakout = close_now > hour_high

    # --------------------------------------------------------
    # BULLISH
    # --------------------------------------------------------

    bullish = (
        current["close"]
        > current["open"]
    )

    # --------------------------------------------------------
    # CLOSE NEAR HIGH
    # --------------------------------------------------------

    candle_range = (
        current["high"]
        - current["low"]
    )

    if candle_range > 0:

        close_position = (
            current["close"]
            - current["low"]
        ) / candle_range

    else:

        close_position = 0

    close_near_high = (
        close_position >= 0.60
    )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    vol_ratio = volume_ratio(
        closed
    )

    volume_strong = (
        vol_ratio >= 1.15
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0
    reasons = []

    if move_5m > 0.30:

        score += 1
        reasons.append("5M UP")

    if move_15m > 0.50:

        score += 1
        reasons.append("15M UP")

    if move_1h > 1.00:

        score += 2
        reasons.append("1H UP")

    if bullish:

        score += 1
        reasons.append("BULLISH")

    if close_near_high:

        score += 1
        reasons.append("HIGH CLOSE")

    if volume_strong:

        score += 1
        reasons.append("VOLUME")

    if breakout:

        score += 2
        reasons.append("BREAKOUT")

    # --------------------------------------------------------
    # MOMENTUM RANK SCORE
    # --------------------------------------------------------

    momentum_score = (
        move_5m * 1.0
        + move_15m * 0.7
        + move_1h * 0.4
        + max(vol_ratio - 1, 0) * 0.5
    )

    # --------------------------------------------------------
    # BUY SETUP
    # --------------------------------------------------------

    buy_setup = (
        score >= 6
        and move_5m > 0
        and move_15m > 0
        and move_1h > 0
        and bullish
    )

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    sl = close_now * 0.995
    tp = close_now * 1.010

    return {

        "symbol": symbol,

        "entry": close_now,

        "move_5m": move_5m,

        "move_15m": move_15m,

        "move_1h": move_1h,

        "volume_ratio": vol_ratio,

        "score": score,

        "momentum_score": momentum_score,

        "breakout": breakout,

        "buy_setup": buy_setup,

        "sl": sl,

        "tp": tp,

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

    for index, symbol in enumerate(
        markets,
        1
    ):

        try:

            result = analyze_symbol(
                symbol
            )

            if result:

                # فقط ارزهایی که حداقل
                # حرکت مثبت دارند
                if (
                    result["move_5m"] > 0
                    or result["move_15m"] > 0
                    or result["move_1h"] > 0
                ):

                    results.append(
                        result
                    )

        except Exception as e:

            print(
                "Skip",
                symbol,
                ":",
                str(e)
            )

        time.sleep(
            SCAN_DELAY
        )

    # اول بر اساس momentum
    results.sort(
        key=lambda x:
        x["momentum_score"],
        reverse=True
    )

    return results[:TOP_RESULTS]


# ============================================================
# TELEGRAM MESSAGE
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
📊 5M + 15M + 1H MOMENTUM

📡 TABDEAL API: OK
📊 USDT MARKETS: {len(markets)}

🕐 Scan:
{now}

🔥 TOP UPWARD COINS
"""

    if not results:

        message += """

⚪ NO POSITIVE MOMENTUM FOUND

🚫 NO TRADE
"""

        return message

    for index, item in enumerate(
        results,
        1
    ):

        setup_text = (
            "🟢 BUY SETUP"
            if item["buy_setup"]
            else "🟡 WATCH"
        )

        message += f"""

━━━━━━━━━━━━━━━━

#{index} {item["symbol"]}

{setup_text}

💰 Price:
{item["entry"]:.8f}

📈 5m:
{item["move_5m"]:+.2f}%

📈 15m:
{item["move_15m"]:+.2f}%

📈 1h:
{item["move_1h"]:+.2f}%

📊 Volume:
{item["volume_ratio"]:.2f}x

⭐ Score:
{item["score"]}

🚀 Momentum:
{item["momentum_score"]:.2f}

💥 Breakout:
{"YES" if item["breakout"] else "NO"}
"""

        if item["buy_setup"]:

            message += f"""

🛑 SL:
{item["sl"]:.8f}

🎯 TP:
{item["tp"]:.8f}

🔎 Reasons:
{", ".join(item["reasons"])}
"""

    message += """

━━━━━━━━━━━━━━━━
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

        return Future(
            TABDEAL_API_KEY,
            TABDEAL_API_SECRET
        )

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

    if side.upper() == "BUY":

        order_side = OrderSides.BUY

    elif side.upper() == "SELL":

        order_side = OrderSides.SELL

    else:

        raise ValueError(
            "Invalid order side"
        )

    # --------------------------------------------------------
    # SET 3X
    # --------------------------------------------------------

    leverage_result = (
        client.change_leverage(
            symbol=symbol,
            leverage=LEVERAGE
        )
    )

    print(
        "Leverage 3x:",
        leverage_result
    )

    # --------------------------------------------------------
    # VERIFY
    # --------------------------------------------------------

    verified_leverage = (
        client.get_leverage(
            symbol=symbol
        )
    )

    print(
        "Verified leverage:",
        verified_leverage
    )

    # --------------------------------------------------------
    # MARKET ORDER
    # --------------------------------------------------------

    order = client.new_order(

        symbol=symbol,

        side=order_side,

        type=OrderTypes.MARKET,

        quantity=str(
            ORDER_QTY
        )
    )

    print(
        "REAL ORDER:",
        order
    )

    return {

        "ok": True,

        "live": True,

        "order": order,

        "leverage":
            verified_leverage
    }


# ============================================================
# ORDER RESULT
# ============================================================

def send_order_result(
    signal,
    result
):

    if not result.get("ok"):

        send_telegram(
            f"""
⚠️ ATI BOT

❌ REAL ORDER NOT SENT

Symbol:
{signal["symbol"]}

Reason:
{result.get("message")}
"""
        )

        return

    send_telegram(
        f"""
🚨 ATI CRYPTO BOT {VERSION}

✅ REAL FUTURES ORDER SENT

🪙 Symbol:
{signal["symbol"]}

📈 Side:
BUY

⚡ Leverage:
3x

💰 Quantity:
{ORDER_QTY}

💵 Entry:
{signal["entry"]:.8f}

🛑 SL:
{signal["sl"]:.8f}

🎯 TP:
{signal["tp"]:.8f}

📌 Order:
{result["order"]}

🔴 REAL TRADING: ON
"""
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
        "LIVE TRADING:",
        LIVE_TRADING
    )

    print(
        "LEVERAGE:",
        LEVERAGE
    )

    print(
        "ORDER QTY:",
        ORDER_QTY
    )

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    try:

        markets = get_usdt_markets()

    except Exception as e:

        message = f"""
⚡ ATI CRYPTO BOT {VERSION}

❌ TABDEAL API ERROR

{str(e)}
"""

        print(message)

        send_telegram(
            message
        )

        return

    print(
        "USDT MARKETS:",
        len(markets)
    )

    if not markets:

        send_telegram(
            f"""
⚡ ATI CRYPTO BOT {VERSION}

❌ NO USDT MARKETS FOUND
"""
        )

        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    try:

        results = scan_markets(
            markets
        )

    except Exception as e:

        message = f"""
⚡ ATI CRYPTO BOT {VERSION}

❌ SCANNER ERROR

{str(e)}
"""

        print(message)

        send_telegram(
            message
        )

        return

    # --------------------------------------------------------
    # SEND TOP 5
    # --------------------------------------------------------

    message = build_message(
        markets,
        results
    )

    print(message)

    send_telegram(
        message
    )

    # --------------------------------------------------------
    # NO RESULTS
    # --------------------------------------------------------

    if not results:

        return

    # --------------------------------------------------------
    # ONLY REAL TRADE IF BUY SETUP
    # --------------------------------------------------------

    if not LIVE_TRADING:

        print(
            "REAL TRADING DISABLED"
        )

        return

    buy_signals = [
        x for x in results
        if x["buy_setup"]
    ]

    if not buy_signals:

        print(
            "No BUY setup"
        )

        return

    # فقط قوی‌ترین BUY
    signal = buy_signals[0]

    try:

        result = (
            place_real_futures_order(
                signal["symbol"],
                "BUY"
            )
        )

        send_order_result(
            signal,
            result
        )

    except Exception as e:

        print(
            "REAL ORDER ERROR:",
            e
        )

        send_telegram(
            f"""
🚨 ATI CRYPTO BOT {VERSION}

❌ REAL FUTURES ORDER ERROR

🪙 Symbol:
{signal["symbol"]}

❗ Error:
{str(e)}

⛔ ORDER NOT CONFIRMED
"""
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
