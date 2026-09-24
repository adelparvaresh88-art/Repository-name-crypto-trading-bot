import os
import time
from datetime import datetime, timezone

import requests

from tabdeal.future import Future
from tabdeal.enums import OrderSides, OrderTypes


VERSION = "V35.3-REAL"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
CANDLE_LIMIT = 60

TOP_RESULTS = 2
MAX_MARKETS = 1000

MIN_SCORE = 4
MIN_MOVE_PERCENT = 0.20

REQUEST_TIMEOUT = 15
SCAN_DELAY = 0.03

# =========================================================
# SAFETY
# =========================================================

ENABLE_REAL_TRADING = (
    os.getenv("ENABLE_REAL_TRADING", "false").strip().lower() == "true"
)

# مبلغ اسمی هر معامله به USDT
TRADE_QUOTE_USDT = float(
    os.getenv("TRADE_QUOTE_USDT", "10")
)

# =========================================================
# TELEGRAM
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()


# =========================================================
# TABDEAL KEYS
# =========================================================

TABDEAL_API_KEY = os.getenv(
    "TABDEAL_API_KEY", ""
).strip()

TABDEAL_API_SECRET = os.getenv(
    "TABDEAL_API_SECRET", ""
).strip()


session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Crypto-Bot/35.3"
})


# =========================================================
# TELEGRAM
# =========================================================

def send_telegram(text):

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

        response = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return True

    except Exception as e:

        print("Telegram error:", e)

        return False


# =========================================================
# HELPERS
# =========================================================

def to_float(value):

    try:
        return float(value)

    except Exception:
        return None


def clean_symbol(value):

    if value is None:
        return ""

    return str(value).upper().replace("/", "")


def api_get(path, params=None):

    url = BASE_URL + path

    response = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# =========================================================
# EXCHANGE INFO
# =========================================================

def extract_market_list(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "symbols",
            "data",
            "result",
            "markets",
        ):

            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


def get_exchange_info():

    paths = [
        "/r/api/v1/exchangeInfo",
        "/api/v1/exchangeInfo",
    ]

    last_error = None

    for path in paths:

        try:

            data = api_get(path)

            markets = extract_market_list(data)

            if markets:
                return markets

        except Exception as e:

            last_error = e

    raise RuntimeError(
        "Could not read Tabdeal exchangeInfo: "
        + str(last_error)
    )


# =========================================================
# MARKET FILTER
# =========================================================

def market_symbol(item):

    if isinstance(item, str):
        return clean_symbol(item)

    if not isinstance(item, dict):
        return ""

    for key in (
        "symbol",
        "market",
        "code",
        "name",
    ):

        if key in item:

            value = clean_symbol(item[key])

            if value:
                return value

    return ""


def market_status(item):

    if not isinstance(item, dict):
        return ""

    for key in (
        "status",
        "state",
    ):

        if key in item:
            return str(item[key]).upper()

    return ""


def is_usdt_market(item):

    symbol = market_symbol(item)

    if not symbol.endswith("USDT"):
        return False

    status = market_status(item)

    if status:

        allowed = {
            "TRADING",
            "ENABLED",
            "ACTIVE",
            "1",
        }

        if status not in allowed:
            return False

    return True


def get_usdt_markets():

    markets = get_exchange_info()

    result = []

    for item in markets:

        if is_usdt_market(item):

            symbol = market_symbol(item)

            if symbol:
                result.append(symbol)

    result = list(dict.fromkeys(result))

    return result[:MAX_MARKETS]


# =========================================================
# KLINES
# =========================================================

def extract_rows(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "data",
            "result",
            "klines",
            "candles",
        ):

            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


def get_klines(symbol):

    variants = [

        (
            "/r/api/v1/klines",
            {
                "symbol": symbol,
                "interval": TIMEFRAME,
                "limit": CANDLE_LIMIT,
            },
        ),

        (
            "/api/v1/klines",
            {
                "symbol": symbol,
                "interval": TIMEFRAME,
                "limit": CANDLE_LIMIT,
            },
        ),

        (
            "/r/api/v1/candles",
            {
                "symbol": symbol,
                "timeframe": TIMEFRAME,
                "limit": CANDLE_LIMIT,
            },
        ),
    ]

    last_error = None

    for path, params in variants:

        try:

            data = api_get(
                path,
                params=params,
            )

            rows = extract_rows(data)

            if rows:
                return rows

        except Exception as e:

            last_error = e

    raise RuntimeError(
        f"Klines failed for {symbol}: {last_error}"
    )


# =========================================================
# CANDLE PARSER
# =========================================================

def parse_candle(row):

    if isinstance(row, dict):

        open_price = (
            row.get("open")
            or row.get("o")
        )

        high_price = (
            row.get("high")
            or row.get("h")
        )

        low_price = (
            row.get("low")
            or row.get("l")
        )

        close_price = (
            row.get("close")
            or row.get("c")
        )

        volume = (
            row.get("volume")
            or row.get("v")
            or 0
        )

        timestamp = (
            row.get("timestamp")
            or row.get("time")
            or row.get("t")
            or 0
        )

        return {
            "time": to_float(timestamp) or 0,
            "open": to_float(open_price),
            "high": to_float(high_price),
            "low": to_float(low_price),
            "close": to_float(close_price),
            "volume": to_float(volume) or 0,
        }

    if isinstance(row, (list, tuple)):

        if len(row) < 6:
            return None

        return {
            "time": to_float(row[0]) or 0,
            "open": to_float(row[1]),
            "high": to_float(row[2]),
            "low": to_float(row[3]),
            "close": to_float(row[4]),
            "volume": to_float(row[5]) or 0,
        }

    return None


def clean_candles(rows):

    candles = []

    for row in rows:

        candle = parse_candle(row)

        if not candle:
            continue

        if (
            candle["open"] is None
            or candle["high"] is None
            or candle["low"] is None
            or candle["close"] is None
        ):
            continue

        candles.append(candle)

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# =========================================================
# MATH
# =========================================================

def average(values):

    if not values:
        return 0

    return sum(values) / len(values)


def pct_change(old, new):

    if old == 0:
        return 0

    return ((new - old) / old) * 100


# =========================================================
# MARKET ANALYSIS
# =========================================================

def analyze_market(symbol, rows):

    candles = clean_candles(rows)

    if len(candles) < 20:
        return None

    # آخرین کندل ممکن است هنوز باز باشد
    closed = candles[:-1]

    if len(closed) < 20:
        return None

    c = closed[-1]

    previous = closed[-2]

    price = c["close"]

    score = 0

    reasons = []

    # -----------------------------------------------------
    # 1. BULLISH CANDLE
    # -----------------------------------------------------

    if c["close"] > c["open"]:

        score += 1
        reasons.append("Bullish candle")

    else:

        return None

    # -----------------------------------------------------
    # 2. BODY STRENGTH
    # -----------------------------------------------------

    candle_range = c["high"] - c["low"]

    if candle_range > 0:

        body = abs(
            c["close"] - c["open"]
        )

        body_ratio = body / candle_range

        if body_ratio >= 0.55:

            score += 1
            reasons.append("Strong body")

    # -----------------------------------------------------
    # 3. VOLUME
    # -----------------------------------------------------

    recent_volumes = [
        x["volume"]
        for x in closed[-11:-1]
    ]

    avg_volume = average(
        recent_volumes
    )

    if (
        avg_volume > 0
        and c["volume"] > avg_volume * 1.20
    ):

        score += 1
        reasons.append("Volume expansion")

    # -----------------------------------------------------
    # 4. RISING STRUCTURE
    # -----------------------------------------------------

    if (
        c["high"] > previous["high"]
        and c["low"] > previous["low"]
    ):

        score += 1
        reasons.append("Higher high / higher low")

    # -----------------------------------------------------
    # 5. CLOSE NEAR HIGH
    # -----------------------------------------------------

    if candle_range > 0:

        close_position = (
            c["close"] - c["low"]
        ) / candle_range

        if close_position >= 0.75:

            score += 1
            reasons.append("Close near high")

    # -----------------------------------------------------
    # 6. SHORT MOMENTUM
    # -----------------------------------------------------

    old_price = closed[-6]["close"]

    move = pct_change(
        old_price,
        price
    )

    if move >= MIN_MOVE_PERCENT:

        score += 1
        reasons.append(
            f"Momentum +{move:.2f}%"
        )

    # -----------------------------------------------------
    # STRONG SETUP
    # -----------------------------------------------------

    if score < MIN_SCORE:
        return None

    entry = price

    stop_loss = entry * 0.995

    take_profit = entry * 1.010

    return {
        "symbol": symbol,
        "price": entry,
        "score": score,
        "move": move,
        "sl": stop_loss,
        "tp": take_profit,
        "reasons": reasons,
    }


# =========================================================
# SCAN
# =========================================================

def scan_symbol(symbol):

    try:

        rows = get_klines(symbol)

        return analyze_market(
            symbol,
            rows,
        )

    except Exception as e:

        print(
            f"{symbol}: {e}"
        )

        return None


# =========================================================
# PRICE FORMAT
# =========================================================

def fmt_price(value):

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:,.4f}"

    if value >= 0.01:
        return f"{value:.6f}"

    return f"{value:.10f}"


# =========================================================
# REAL FUTURES ORDER
# =========================================================

def execute_real_trade(signal):

    if not ENABLE_REAL_TRADING:

        return {
            "success": False,
            "message": "REAL TRADING DISABLED",
        }

    if not TABDEAL_API_KEY:

        return {
            "success": False,
            "message": "TABDEAL_API_KEY missing",
        }

    if not TABDEAL_API_SECRET:

        return {
            "success": False,
            "message": "TABDEAL_API_SECRET missing",
        }

    symbol = signal["symbol"]

    price = float(
        signal["price"]
    )

    if price <= 0:

        return {
            "success": False,
            "message": "Invalid price",
        }

    # -----------------------------------------------------
    # مقدار BTC/coin بر اساس 10 USDT پیش‌فرض
    # -----------------------------------------------------

    quantity = TRADE_QUOTE_USDT / price

    # مقدار را با 8 رقم اعشار محدود می‌کنیم
    quantity = round(
        quantity,
        8
    )

    if quantity <= 0:

        return {
            "success": False,
            "message": "Invalid quantity",
        }

    try:

        client = Future(
            TABDEAL_API_KEY,
            TABDEAL_API_SECRET,
        )

        print(
            f"REAL FUTURES ORDER: "
            f"{symbol} BUY "
            f"{quantity}"
        )

        order = client.new_order(
            symbol=symbol,
            side=OrderSides.BUY,
            type=OrderTypes.MARKET,
            quantity=str(quantity),
        )

        return {
            "success": True,
            "order": order,
            "quantity": quantity,
        }

    except Exception as e:

        return {
            "success": False,
            "message": (
                type(e).__name__
                + ": "
                + str(e)
            ),
        }


# =========================================================
# TELEGRAM MESSAGE
# =========================================================

def build_message(
    results,
    market_count,
    scan_time,
):

    mode = (
        "🔴 REAL TRADING ENABLED"
        if ENABLE_REAL_TRADING
        else "🛡 REAL TRADING DISABLED"
    )

    text = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        "🚀 UPWARD COIN SCANNER\n"
        f"⏱ Timeframe: {TIMEFRAME}\n"
        "✅ CLOSED CANDLE\n"
        "💥 BREAKOUT + MOMENTUM ENGINE\n\n"
        "📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {market_count}\n"
        f"🕐 Scan: {scan_time}\n\n"
    )

    if not results:

        text += (
            "⚪ NO STRONG UPWARD SETUP\n\n"
            "⏳ NO TRADE\n"
            f"{mode}"
        )

        return text

    text += (
        f"🔥 TOP {len(results)} "
        "UPWARD OPPORTUNITIES\n\n"
    )

    for index, result in enumerate(
        results,
        start=1
    ):

        text += (
            f"🟢 #{index} "
            f"{result['symbol']}\n"
            f"⭐ SCORE: "
            f"{result['score']}/6\n"
            f"💰 ENTRY: "
            f"${fmt_price(result['price'])}\n"
            f"🛑 PLANNED SL: "
            f"${fmt_price(result['sl'])}\n"
            f"🎯 PLANNED TP: "
            f"${fmt_price(result['tp'])}\n"
            f"📈 MOVE: "
            f"{result['move']:.2f}%\n"
            "📚 "
            + ", ".join(result["reasons"])
            + "\n\n"
        )

    text += mode

    return text


# =========================================================
# MAIN
# =========================================================

def main():

    try:

        print(
            f"ATI CRYPTO BOT {VERSION}"
        )

        markets = get_usdt_markets()

        print(
            f"USDT MARKETS: {len(markets)}"
        )

        results = []

        for symbol in markets:

            signal = scan_symbol(
                symbol
            )

            if signal:

                results.append(
                    signal
                )

            time.sleep(
                SCAN_DELAY
            )

        results.sort(
            key=lambda x: (
                x["score"],
                x["move"],
            ),
            reverse=True,
        )

        results = results[
            :TOP_RESULTS
        ]

        scan_time = datetime.now(
            timezone.utc
        ).strftime(
            "%Y-%m-%d %H:%M UTC"
        )

        message = build_message(
            results,
            len(markets),
            scan_time,
        )

        # -------------------------------------------------
        # REAL ORDER
        # فقط برای اولین سیگنال
        # -------------------------------------------------

        if (
            ENABLE_REAL_TRADING
            and results
        ):

            trade_result = (
                execute_real_trade(
                    results[0]
                )
            )

            if trade_result["success"]:

                message += (
                    "\n\n"
                    "🟢 REAL FUTURES ORDER SENT\n"
                    f"💵 Quantity: "
                    f"{trade_result['quantity']}\n"
                    "⚠️ SL/TP are NOT yet submitted "
                    "as separate exchange orders."
                )

            else:

                message += (
                    "\n\n"
                    "🔴 REAL ORDER FAILED\n"
                    f"❌ {trade_result['message']}"
                )

        send_telegram(
            message
        )

        print(message)

    except Exception as e:

        error_message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "❌ BOT ERROR\n\n"
            f"{type(e).__name__}: {e}"
        )

        print(
            error_message
        )

        send_telegram(
            error_message
        )


if __name__ == "__main__":
    main()
