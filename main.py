import os
import time
from datetime import datetime, timezone

import requests

VERSION = "V35.3"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 60
TOP_RESULTS = 2
MAX_MARKETS = 1000

MIN_SCORE = 4
MIN_MOVE_PERCENT = 0.20

REQUEST_TIMEOUT = 15
SCAN_DELAY = 0.03

# ============================================================
# REAL FUTURES SETTINGS
# ============================================================

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false").strip().lower()
    in ("1", "true", "yes", "on")
)

LEVERAGE = 3

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
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Crypto-Bot/35.3"
})


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):

        print(
            "TELEGRAM ERROR: missing token/chat id"
        )

        return False

    url = (
        "https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:

        response = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        data = response.json()

        if not isinstance(data, dict):

            print(
                "TELEGRAM ERROR: invalid response"
            )

            return False

        if not data.get("ok"):

            print(
                "TELEGRAM ERROR:",
                data
            )

            return False

        return True

    except Exception as e:

        print(
            "TELEGRAM ERROR:",
            e
        )

        return False


# ============================================================
# HELPERS
# ============================================================

def to_float(
    value,
    default=0.0
):

    try:

        if value is None:
            return default

        if value == "":
            return default

        return float(value)

    except (
        TypeError,
        ValueError
    ):

        return default


def clean_symbol(value):

    if value is None:
        return ""

    return (
        str(value)
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
    )


def api_get(
    path,
    params=None
):

    url = BASE_URL + path

    response = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# SAFE LIST EXTRACTION
# ============================================================

def first_list(value):

    if isinstance(value, list):
        return value

    if not isinstance(value, dict):
        return []

    for key in (
        "data",
        "result",
        "rows",
        "items",
        "symbols",
        "markets",
        "candles",
        "klines",
    ):

        child = value.get(key)

        if isinstance(child, list):
            return child

        if isinstance(child, dict):

            nested = first_list(child)

            if nested:
                return nested

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
        "/api/v1/exchangeInfo",
    ]

    errors = []

    for path in paths:

        try:

            data = api_get(path)

            return data

        except Exception as e:

            errors.append(
                f"{path}: {e}"
            )

    raise RuntimeError(
        "exchangeInfo failed | "
        + " | ".join(errors)
    )


# ============================================================
# MARKET PARSING
# ============================================================

def market_symbol(item):

    if isinstance(item, str):

        return clean_symbol(item)

    if not isinstance(item, dict):
        return ""

    for key in (
        "symbol",
        "s",
        "market",
        "pair",
        "name",
        "tabdealSymbol",
    ):

        value = item.get(key)

        if value is not None:

            symbol = clean_symbol(value)

            if symbol:
                return symbol

    return ""


def market_status(item):

    if not isinstance(item, dict):
        return ""

    for key in (
        "status",
        "state",
    ):

        value = item.get(key)

        if value is not None:

            return str(
                value
            ).upper()

    return ""


def is_usdt_market(item):

    symbol = market_symbol(item)

    if not symbol:
        return False

    if not symbol.endswith("USDT"):
        return False

    status = market_status(item)

    if status:

        allowed = {
            "TRADING",
            "ENABLED",
            "ACTIVE",
            "ONLINE",
        }

        if status not in allowed:
            return False

    return True


def get_usdt_markets():

    data = get_exchange_info()

    items = extract_market_list(data)

    markets = []

    seen = set()

    for item in items:

        if not is_usdt_market(item):
            continue

        symbol = market_symbol(item)

        if (
            symbol
            and symbol not in seen
        ):

            seen.add(symbol)

            markets.append(symbol)

    return markets[:MAX_MARKETS]


# ============================================================
# CANDLES
# ============================================================

def get_klines(symbol):

    paths = [
        "/r/api/v1/klines",
        "/api/v1/klines",
        "/r/api/v1/candles",
    ]

    params_variants = [

        {
            "symbol": symbol,
            "interval": TIMEFRAME,
            "limit": CANDLE_LIMIT,
        },

        {
            "symbol": symbol,
            "timeframe": TIMEFRAME,
            "limit": CANDLE_LIMIT,
        },

    ]

    for path in paths:

        for params in params_variants:

            try:

                data = api_get(
                    path,
                    params
                )

                rows = extract_rows(data)

                if rows:
                    return rows

            except Exception:

                continue

    return []


# ============================================================
# CANDLE PARSER
# ============================================================

def parse_candle(row):

    if isinstance(
        row,
        (list, tuple)
    ):

        if len(row) < 6:
            return None

        return {
            "time": to_float(row[0]),
            "open": to_float(row[1]),
            "high": to_float(row[2]),
            "low": to_float(row[3]),
            "close": to_float(row[4]),
            "volume": to_float(row[5]),
        }

    if isinstance(row, dict):

        return {

            "time": to_float(
                row.get(
                    "openTime",
                    row.get(
                        "time",
                        row.get(
                            "timestamp",
                            0
                        )
                    )
                )
            ),

            "open": to_float(
                row.get(
                    "open",
                    row.get("o")
                )
            ),

            "high": to_float(
                row.get(
                    "high",
                    row.get("h")
                )
            ),

            "low": to_float(
                row.get(
                    "low",
                    row.get("l")
                )
            ),

            "close": to_float(
                row.get(
                    "close",
                    row.get("c")
                )
            ),

            "volume": to_float(
                row.get(
                    "volume",
                    row.get("v")
                )
            ),
        }

    return None


def clean_candles(rows):

    result = []

    if not isinstance(
        rows,
        list
    ):
        return result

    for row in rows:

        candle = parse_candle(row)

        if not candle:
            continue

        if (
            candle["open"] <= 0
            or candle["high"] <= 0
            or candle["low"] <= 0
            or candle["close"] <= 0
        ):
            continue

        result.append(candle)

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# ============================================================
# MATH
# ============================================================

def average(values):

    valid = []

    for value in values:

        if value is None:
            continue

        valid.append(
            to_float(value)
        )

    if not valid:
        return 0.0

    return sum(valid) / len(valid)


def pct_change(
    old,
    new
):

    old = to_float(old)
    new = to_float(new)

    if old == 0:
        return 0.0

    return (
        (new - old)
        / old
    ) * 100.0


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(
    symbol,
    rows
):

    candles = clean_candles(rows)

    if len(candles) < 25:
        return None

    # Last candle is treated as potentially open.
    # We only analyze closed candles.
    closed = candles[:-1]

    if len(closed) < 24:
        return None

    c = closed[-1]
    prev = closed[-2]

    recent = closed[-6:]

    prior = closed[-12:-6]

    if len(prior) < 6:
        return None

    price = c["close"]

    previous_close = prev["close"]

    move = pct_change(
        previous_close,
        price
    )

    range_size = max(
        c["high"] - c["low"],
        1e-12
    )

    body = abs(
        c["close"]
        - c["open"]
    )

    body_ratio = (
        body / range_size
    )

    prior_high = max(
        x["high"]
        for x in closed[-13:-1]
    )

    breakout = (
        c["close"]
        > prior_high
    )

    avg_volume = average(
        x["volume"]
        for x in closed[-21:-1]
    )

    volume_expansion = (
        avg_volume > 0
        and c["volume"]
        >= avg_volume * 1.20
    )

    rising_structure = all(
        recent[i]["close"]
        >= recent[i - 1]["close"]
        for i in range(
            1,
            len(recent)
        )
    )

    recent_low = min(
        x["low"]
        for x in recent
    )

    recent_high = max(
        x["high"]
        for x in recent
    )

    structure_move = pct_change(
        recent_low,
        recent_high
    )

    close_near_high = (
        c["close"]
        >= c["high"]
        - range_size * 0.25
    )

    bullish_candle = (
        c["close"]
        > c["open"]
    )

    momentum = pct_change(
        closed[-4]["close"],
        price
    )

    score = 0

    reasons = []

    if breakout:

        score += 2
        reasons.append(
            "BREAKOUT"
        )

    if (
        bullish_candle
        and body_ratio >= 0.45
    ):

        score += 1
        reasons.append(
            "STRONG BODY"
        )

    if volume_expansion:

        score += 1
        reasons.append(
            "VOLUME"
        )

    if rising_structure:

        score += 1
        reasons.append(
            "RISING STRUCTURE"
        )

    if close_near_high:

        score += 1
        reasons.append(
            "CLOSE NEAR HIGH"
        )

    if momentum >= 0.20:

        score += 1
        reasons.append(
            "MOMENTUM"
        )

    if structure_move >= 0.25:

        score += 1
        reasons.append(
            "UPWARD MOVE"
        )

    if move >= MIN_MOVE_PERCENT:

        score += 1
        reasons.append(
            "5M MOVE"
        )

    if (
        move < MIN_MOVE_PERCENT
        and not breakout
    ):

        return None

    if not bullish_candle:
        return None

    if score < MIN_SCORE:
        return None

    entry = price

    sl = entry * 0.995

    tp = entry * 1.010

    return {

        "symbol": symbol,

        "price": price,

        "entry": entry,

        "sl": sl,

        "tp": tp,

        "score": score,

        "move": move,

        "momentum": momentum,

        "volume_ratio": (
            c["volume"]
            / avg_volume
            if avg_volume > 0
            else 0.0
        ),

        "candle_time": c["time"],

        "reasons": reasons,
    }


# ============================================================
# SCANNER
# ============================================================

def scan_symbol(symbol):

    try:

        rows = get_klines(symbol)

        if not rows:
            return None

        return analyze_market(
            symbol,
            rows
        )

    except Exception as e:

        print(
            f"SCAN ERROR {symbol}: {e}"
        )

        return None


# ============================================================
# PRICE FORMAT
# ============================================================

def fmt_price(value):

    value = to_float(value)

    if value >= 1000:

        return f"{value:,.2f}"

    if value >= 1:

        return f"{value:,.4f}"

    return (
        f"{value:,.8f}"
        .rstrip("0")
        .rstrip(".")
    )


# ============================================================
# REAL FUTURES CLIENT
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
            "tabdeal-python Future import failed: "
            + str(e)
        )


# ============================================================
# REAL ORDER
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
            f"Invalid order side: {side}"
        )

    quantity = str(
        ORDER_QTY
    )

    print(
        "================================================"
    )

    print(
        "REAL FUTURES ORDER"
    )

    print(
        f"Symbol: {symbol}"
    )

    print(
        f"Side: {side}"
    )

    print(
        f"Quantity: {quantity}"
    )

    print(
        f"Configured leverage: {LEVERAGE}x"
    )

    print(
        "================================================"
    )

    # Official Tabdeal SDK Futures order.
    #
    # NOTE:
    # The official SDK example confirms new_order()
    # for Futures MARKET orders.
    #
    # The currently verified official example does NOT
    # expose a leverage argument here.
    #
    # Therefore we do NOT invent a leverage endpoint.

    order = client.new_order(

        symbol=symbol,

        side=order_side,

        type=OrderTypes.MARKET,

        quantity=quantity,
    )

    return {
        "ok": True,
        "live": True,
        "order": order,
        "leverage": LEVERAGE,
    }


# ============================================================
# TELEGRAM ORDER MESSAGE
# ============================================================

def send_order_result(
    result,
    signal
):

    symbol = signal["symbol"]

    if not result.get("ok"):

        message = (
            f"⚡ ATI BOT {VERSION}\n\n"
            f"❌ ORDER NOT SENT\n\n"
            f"🪙 {symbol}\n"
            f"📈 SIDE: {signal['side']}\n"
            f"💰 PRICE: ${fmt_price(signal['price'])}\n"
            f"⚙️ LEVERAGE: {LEVERAGE}x\n\n"
            f"🛡 LIVE TRADING: "
            f"{LIVE_TRADING}\n"
            f"ℹ️ {result.get('message')}"
        )

        send_telegram(message)

        return

    order = result.get(
        "order"
    )

    message = (
        f"🚨 ATI REAL FUTURES ORDER\n\n"
        f"🪙 SYMBOL: {symbol}\n"
        f"📈 SIDE: {signal['side']}\n"
        f"💰 PRICE: ${fmt_price(signal['price'])}\n"
        f"📦 QTY: {ORDER_QTY}\n"
        f"⚙️ CONFIGURED LEVERAGE: {LEVERAGE}x\n\n"
        f"🎯 SL: ${fmt_price(signal['sl'])}\n"
        f"✅ TP: ${fmt_price(signal['tp'])}\n\n"
        f"🔥 SCORE: {signal['score']}/9\n"
        f"🔎 {' + '.join(signal['reasons'])}\n\n"
        f"🔴 LIVE TRADING: TRUE\n\n"
        f"📋 ORDER RESPONSE:\n"
        f"{order}"
    )

    send_telegram(message)


# ============================================================
# BUILD SCAN MESSAGE
# ============================================================

def build_message(
    results,
    market_count,
    scan_time
):

    lines = [

        f"⚡ ATI CRYPTO BOT {VERSION}",

        "🚀 UPWARD COIN SCANNER",

        f"⏱ Timeframe: {TIMEFRAME}",

        "✅ CLOSED CANDLE",

        "💥 BREAKOUT + MOMENTUM ENGINE",

        "",

        "📡 TABDEAL API: OK",

        f"📊 USDT MARKETS: {market_count}",

        f"🕐 Scan: {scan_time}",

        "",
    ]

    if not results:

        lines += [

            "⚪ NO STRONG UPWARD SETUP",

            "",

            "⏳ NO TRADE",

            (
                "🔴 REAL TRADING: "
                + (
                    "ENABLED"
                    if LIVE_TRADING
                    else "DISABLED"
                )
            ),
        ]

        return "\n".join(
            lines
        )

    lines += [

        f"🔥 TOP {len(results)} "
        "UPWARD OPPORTUNITIES",

        "",
    ]

    for i, result in enumerate(
        results,
        1
    ):

        lines += [

            f"🟢 #{i} "
            f"{result['symbol']}",

            (
                f"💰 Price: "
                f"${fmt_price(result['price'])}"
            ),

            (
                f"📈 SCORE: "
                f"{result['score']}/9"
            ),

            (
                f"🚀 MOVE: "
                f"{result['move']:.3f}%"
            ),

            (
                f"📊 MOMENTUM: "
                f"{result['momentum']:.3f}%"
            ),

            (
                f"🔊 VOL: "
                f"{result['volume_ratio']:.2f}x"
            ),

            (
                f"🎯 Entry: "
                f"${fmt_price(result['entry'])}"
            ),

            (
                f"🛑 SL: "
                f"${fmt_price(result['sl'])}"
            ),

            (
                f"✅ TP: "
                f"${fmt_price(result['tp'])}"
            ),

            (
                "🔎 "
                + " + ".join(
                    result["reasons"]
                )
            ),

            "",
        ]

    lines += [

        (
            "🔴 LIVE TRADING: "
            + (
                "TRUE"
                if LIVE_TRADING
                else "FALSE"
            )
        ),

        f"⚙️ CONFIGURED LEVERAGE: "
        f"{LEVERAGE}x",

        f"📦 ORDER QTY: {ORDER_QTY}",
    ]

    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"ATI CRYPTO BOT {VERSION}"
    )

    print(
        "Starting full USDT market scan..."
    )

    print(
        f"LIVE_TRADING = {LIVE_TRADING}"
    )

    print(
        f"LEVERAGE = {LEVERAGE}x"
    )

    print(
        f"ORDER_QTY = {ORDER_QTY}"
    )

    # --------------------------------------------------------
    # MARKET LIST
    # --------------------------------------------------------

    try:

        markets = get_usdt_markets()

    except Exception as e:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL API ERROR\n\n"
            f"{e}"
        )

        print(message)

        send_telegram(message)

        return

    market_count = len(
        markets
    )

    print(
        f"USDT markets: {market_count}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results = []

    total = market_count

    for index, symbol in enumerate(
        markets,
        1
    ):

        result = scan_symbol(
            symbol
        )

        if result:

            results.append(
                result
            )

            results.sort(
                key=lambda x: (
                    x["score"],
                    x["momentum"],
                    x["move"],
                ),
                reverse=True
            )

            results = results[
                :TOP_RESULTS
            ]

        if (
            index % 50 == 0
            or index == total
        ):

            print(
                f"Scanned "
                f"{index}/{total}"
            )

        time.sleep(
            SCAN_DELAY
        )

    # --------------------------------------------------------
    # TELEGRAM SCAN MESSAGE
    # --------------------------------------------------------

    scan_time = (
        datetime.now(
            timezone.utc
        )
        .strftime(
            "%Y-%m-%d %H:%M UTC"
        )
    )

    message = build_message(
        results,
        market_count,
        scan_time
    )

    print(message)

    send_telegram(
        message
    )

    # --------------------------------------------------------
    # REAL TRADE
    # --------------------------------------------------------

    if not results:

        print(
            "No trade."
        )

        return

    # Only the TOP signal can trigger
    # one real order per run.

    signal = results[0]

    signal["side"] = "BUY"

    if not LIVE_TRADING:

        print(
            "LIVE_TRADING is OFF."
        )

        return

    print(
        "REAL TRADING ENABLED."
    )

    try:

        result = place_real_futures_order(
            signal["symbol"],
            signal["side"]
        )

        send_order_result(
            result,
            signal
        )

        print(
            "ORDER RESULT:"
        )

        print(result)

    except Exception as e:

        error_message = (
            f"🚨 ATI REAL ORDER ERROR\n\n"
            f"🪙 {signal['symbol']}\n"
            f"📈 SIDE: {signal['side']}\n"
            f"⚙️ LEVERAGE CONFIG: "
            f"{LEVERAGE}x\n"
            f"📦 QTY: {ORDER_QTY}\n\n"
            f"❌ ERROR:\n"
            f"{e}"
        )

        print(
            error_message
        )

        send_telegram(
            error_message
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
