import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V36.1
# TOP UPWARD COIN SCANNER
# ============================================================

VERSION = "V36.1"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
CANDLE_LIMIT = 60

MAX_MARKETS = 1000
TOP_RESULTS = 5

LEVERAGE = 3

REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.03

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").strip().lower() == "true"

ORDER_QTY = os.getenv("ORDER_QTY", "0.001")

TABDEAL_API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
TABDEAL_API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-CRYPTO-BOT/36.1",
        "Accept": "application/json",
    }
)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM CONFIG ERROR")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        response = session.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            print("TELEGRAM: OK")
            return True

        print("TELEGRAM ERROR:", response.text[:500])
        return False

    except Exception as e:
        print("TELEGRAM EXCEPTION:", str(e))
        return False


# ============================================================
# TABDEAL REQUEST
# ============================================================

def tabdeal_get(path, params=None):
    urls = [
        f"{BASE_URL}{path}",
    ]

    last_error = None

    for url in urls:
        try:
            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 200:
                return response.json()

            last_error = (
                f"HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(last_error or "TABDEAL API ERROR")


# ============================================================
# GENERIC DATA EXTRACTION
# ============================================================

def unwrap_data(data):
    """
    Tabdeal responses can be:
    list
    dict
    dict with data/result/items
    """

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "data",
            "result",
            "items",
            "symbols",
            "markets",
            "rows",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                return value

        return data

    return []


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_usdt_markets():

    paths = [
        "/r/api/v1/exchangeInfo",
        "/api/v1/exchangeInfo",
    ]

    last_error = None

    for path in paths:

        try:

            data = tabdeal_get(path)

            raw = unwrap_data(data)

            markets = []

            if isinstance(raw, dict):

                raw = (
                    raw.get("symbols")
                    or raw.get("markets")
                    or raw.get("data")
                    or []
                )

            if not isinstance(raw, list):
                continue

            for item in raw:

                if isinstance(item, str):

                    symbol = item.upper()

                    if symbol.endswith("USDT"):
                        markets.append(symbol)

                    continue

                if not isinstance(item, dict):
                    continue

                symbol = (
                    item.get("symbol")
                    or item.get("market")
                    or item.get("pair")
                    or item.get("name")
                )

                if not symbol:
                    continue

                symbol = str(symbol).upper()

                quote = str(
                    item.get("quoteAsset")
                    or item.get("quote")
                    or item.get("quoteCurrency")
                    or ""
                ).upper()

                status = str(
                    item.get("status")
                    or "TRADING"
                ).upper()

                if (
                    symbol.endswith("USDT")
                    and (
                        quote == ""
                        or quote == "USDT"
                    )
                    and status not in (
                        "BREAK",
                        "HALT",
                        "OFFLINE",
                    )
                ):
                    markets.append(symbol)

            markets = sorted(set(markets))

            if markets:
                return markets[:MAX_MARKETS]

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(
        f"Unable to get USDT markets: {last_error}"
    )


# ============================================================
# CANDLE PARSER
# ============================================================

def parse_candles(data):

    raw = unwrap_data(data)

    if isinstance(raw, dict):

        for key in (
            "klines",
            "candles",
            "data",
            "result",
            "items",
        ):

            value = raw.get(key)

            if isinstance(value, list):
                raw = value
                break

    if not isinstance(raw, list):
        return []

    candles = []

    for item in raw:

        try:

            # --------------------------------------------
            # LIST FORMAT
            # --------------------------------------------

            if isinstance(item, list):

                if len(item) < 5:
                    continue

                timestamp = item[0]
                open_price = item[1]
                high_price = item[2]
                low_price = item[3]
                close_price = item[4]

                volume = (
                    item[5]
                    if len(item) > 5
                    else 0
                )

            # --------------------------------------------
            # DICT FORMAT
            # --------------------------------------------

            elif isinstance(item, dict):

                timestamp = (
                    item.get("openTime")
                    or item.get("open_time")
                    or item.get("timestamp")
                    or item.get("time")
                    or item.get("t")
                )

                open_price = (
                    item.get("open")
                    or item.get("o")
                )

                high_price = (
                    item.get("high")
                    or item.get("h")
                )

                low_price = (
                    item.get("low")
                    or item.get("l")
                )

                close_price = (
                    item.get("close")
                    or item.get("c")
                )

                volume = (
                    item.get("volume")
                    or item.get("v")
                    or 0
                )

            else:
                continue

            if (
                open_price is None
                or high_price is None
                or low_price is None
                or close_price is None
            ):
                continue

            candles.append(
                {
                    "time": float(timestamp or 0),
                    "open": float(open_price),
                    "high": float(high_price),
                    "low": float(low_price),
                    "close": float(close_price),
                    "volume": float(volume or 0),
                }
            )

        except Exception:
            continue

    candles.sort(key=lambda x: x["time"])

    return candles


# ============================================================
# GET CANDLES
# ============================================================

def get_candles(symbol):

    attempts = [
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

    for path, params in attempts:

        try:

            data = tabdeal_get(
                path,
                params=params,
            )

            candles = parse_candles(data)

            if len(candles) >= 20:
                return candles[-CANDLE_LIMIT:]

        except Exception as e:
            last_error = str(e)

    return []


# ============================================================
# SAFE PERCENT CHANGE
# ============================================================

def percent_change(old_price, new_price):

    try:

        if old_price == 0:
            return 0.0

        return (
            (new_price - old_price)
            / old_price
        ) * 100.0

    except Exception:
        return 0.0


# ============================================================
# ANALYZE MARKET
# ============================================================

def analyze_market(symbol):

    candles = get_candles(symbol)

    if len(candles) < 20:
        return None

    # --------------------------------------------------------
    # CLOSED CANDLES ONLY
    # --------------------------------------------------------

    closed = candles[:-1]

    if len(closed) < 20:
        return None

    latest = closed[-1]
    previous = closed[-2]

    close_price = latest["close"]
    open_price = latest["open"]
    high_price = latest["high"]
    low_price = latest["low"]

    # --------------------------------------------------------
    # 5 MIN
    # --------------------------------------------------------

    move_5m = percent_change(
        previous["close"],
        close_price,
    )

    # --------------------------------------------------------
    # 15 MIN
    # 3 x 5m candles
    # --------------------------------------------------------

    if len(closed) >= 4:

        move_15m = percent_change(
            closed[-4]["close"],
            close_price,
        )

    else:
        move_15m = 0.0

    # --------------------------------------------------------
    # 1 HOUR
    # 12 x 5m candles
    # --------------------------------------------------------

    if len(closed) >= 13:

        move_1h = percent_change(
            closed[-13]["close"],
            close_price,
        )

    else:
        move_1h = 0.0

    # --------------------------------------------------------
    # PREVIOUS 1H HIGH
    # --------------------------------------------------------

    hour_window = closed[-13:-1]

    if hour_window:

        hour_high = max(
            candle["high"]
            for candle in hour_window
        )

    else:
        hour_high = high_price

    breakout = (
        close_price > hour_high
    )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    recent_volumes = [
        candle["volume"]
        for candle in closed[-6:-1]
        if candle["volume"] > 0
    ]

    if recent_volumes:

        avg_volume = (
            sum(recent_volumes)
            / len(recent_volumes)
        )

        if avg_volume > 0:

            volume_ratio = (
                latest["volume"]
                / avg_volume
            )

        else:
            volume_ratio = 0.0

    else:
        volume_ratio = 0.0

    # --------------------------------------------------------
    # CANDLE STRUCTURE
    # --------------------------------------------------------

    bullish = (
        close_price > open_price
    )

    candle_range = high_price - low_price

    if candle_range > 0:

        close_position = (
            (close_price - low_price)
            / candle_range
        )

    else:
        close_position = 0.5

    close_near_high = (
        close_position >= 0.65
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    if move_5m > 0.30:
        score += 1

    if move_15m > 0.50:
        score += 1

    if move_1h > 1.00:
        score += 2

    if bullish:
        score += 1

    if close_near_high:
        score += 1

    if volume_ratio >= 1.15:
        score += 1

    if breakout:
        score += 2

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
    # MOMENTUM RANK
    # --------------------------------------------------------

    positive_5m = max(move_5m, 0)

    positive_15m = max(move_15m, 0)

    positive_1h = max(move_1h, 0)

    volume_bonus = max(
        volume_ratio - 1.0,
        0
    )

    momentum_score = (
        positive_5m
        + (0.70 * positive_15m)
        + (0.40 * positive_1h)
        + (0.50 * volume_bonus)
    )

    # --------------------------------------------------------
    # UPWARD STATUS
    # --------------------------------------------------------

    if (
        move_5m > 0
        and move_15m > 0
        and move_1h > 0
    ):
        direction = "UP"

    elif (
        move_15m > 0
        and move_1h > 0
    ):
        direction = "RECOVERING"

    elif (
        move_5m > 0
        or move_15m > 0
        or move_1h > 0
    ):
        direction = "MIXED"

    else:
        direction = "DOWN"

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    stop_loss = close_price * 0.995

    take_profit = close_price * 1.010

    return {
        "symbol": symbol,
        "price": close_price,

        "move_5m": move_5m,
        "move_15m": move_15m,
        "move_1h": move_1h,

        "volume_ratio": volume_ratio,

        "score": score,
        "momentum_score": momentum_score,

        "breakout": breakout,
        "bullish": bullish,
        "close_near_high": close_near_high,

        "direction": direction,
        "buy_setup": buy_setup,

        "sl": stop_loss,
        "tp": take_profit,
    }


# ============================================================
# FORMAT PERCENT
# ============================================================

def fmt_percent(value):

    if value > 0:
        return f"+{value:.2f}%"

    return f"{value:.2f}%"


# ============================================================
# FORMAT PRICE
# ============================================================

def fmt_price(value):

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:.4f}"

    if value >= 0.01:
        return f"{value:.6f}"

    return f"{value:.10f}"


# ============================================================
# REAL FUTURES ORDER
# ============================================================

def create_real_order(signal):

    symbol = signal["symbol"]

    try:

        from tabdeal.enums import (
            OrderSides,
            OrderTypes,
        )

        from tabdeal.future import Future

    except Exception as e:

        return {
            "success": False,
            "message": (
                "TABDEAL FUTURES SDK ERROR: "
                f"{str(e)}"
            ),
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

    try:

        client = Future(
            TABDEAL_API_KEY,
            TABDEAL_API_SECRET,
        )

        # ----------------------------------------------------
        # SET LEVERAGE 3X
        # ----------------------------------------------------

        client.change_leverage(
            symbol=symbol,
            leverage=LEVERAGE,
        )

        # ----------------------------------------------------
        # VERIFY LEVERAGE
        # ----------------------------------------------------

        try:

            leverage_info = client.get_leverage(
                symbol=symbol
            )

            print(
                "LEVERAGE:",
                leverage_info,
            )

        except Exception as e:

            print(
                "LEVERAGE VERIFY WARNING:",
                str(e),
            )

        # ----------------------------------------------------
        # MARKET BUY
        # ----------------------------------------------------

        order = client.new_order(
            symbol=symbol,
            side=OrderSides.BUY,
            type=OrderTypes.MARKET,
            quantity=str(ORDER_QTY),
        )

        return {
            "success": True,
            "message": "REAL FUTURES ORDER SENT",
            "order": order,
        }

    except Exception as e:

        return {
            "success": False,
            "message": str(e),
        }


# ============================================================
# MAIN
# ============================================================

def main():

    print()
    print("=" * 60)
    print(f"ATI CRYPTO BOT {VERSION}")
    print("=" * 60)
    print()

    # --------------------------------------------------------
    # API TEST
    # --------------------------------------------------------

    try:

        markets = get_usdt_markets()

    except Exception as e:

        error_message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL API ERROR\n\n"
            f"{str(e)}"
        )

        print(error_message)

        send_telegram(error_message)

        return

    print(
        f"TABDEAL API: OK"
    )

    print(
        f"USDT MARKETS: {len(markets)}"
    )

    # --------------------------------------------------------
    # TIME
    # --------------------------------------------------------

    now = datetime.now(
        timezone.utc
    )

    scan_time = now.strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results = []

    scanned = 0

    errors = 0

    for symbol in markets:

        scanned += 1

        try:

            result = analyze_market(symbol)

            if result is not None:

                results.append(result)

        except Exception as e:

            errors += 1

            print(
                f"{symbol}: ERROR {str(e)}"
            )

        time.sleep(
            SLEEP_BETWEEN_MARKETS
        )

    # --------------------------------------------------------
    # IMPORTANT:
    # V36.1 DOES NOT REQUIRE POSITIVE MOMENTUM
    # TO SHOW TOP RESULTS.
    # --------------------------------------------------------

    if not results:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"🚀 UPWARD COIN SCANNER\n\n"
            f"⏱ Timeframe: {TIMEFRAME}\n"
            f"✅ CLOSED CANDLE\n"
            f"📊 5M + 15M + 1H MOMENTUM\n\n"
            f"📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: {len(markets)}\n\n"
            f"🕐 Scan:\n"
            f"{scan_time}\n\n"
            f"❌ NO CANDLE DATA FOUND\n\n"
            f"🚫 NO TRADE"
        )

        print(message)

        send_telegram(message)

        return

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["momentum_score"],
            x["move_1h"],
            x["move_15m"],
            x["move_5m"],
        ),
        reverse=True,
    )

    top_results = results[
        :TOP_RESULTS
    ]

    # --------------------------------------------------------
    # CHECK REAL BUY SETUPS
    # --------------------------------------------------------

    buy_setups = [
        x
        for x in results
        if x["buy_setup"]
    ]

    # --------------------------------------------------------
    # TELEGRAM MESSAGE
    # --------------------------------------------------------

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    lines.append("")

    lines.append(
        "🚀 UPWARD COIN SCANNER"
    )

    lines.append("")

    lines.append(
        f"⏱ Timeframe: {TIMEFRAME}"
    )

    lines.append(
        "✅ CLOSED CANDLE"
    )

    lines.append(
        "📊 5M + 15M + 1H MOMENTUM"
    )

    lines.append("")

    lines.append(
        "📡 TABDEAL API: OK"
    )

    lines.append(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    lines.append("")

    lines.append(
        f"🕐 Scan:\n{scan_time}"
    )

    lines.append("")

    lines.append(
        "🔥 TOP 5 UPWARD COINS"
    )

    lines.append("")

    # --------------------------------------------------------
    # TOP RESULTS
    # --------------------------------------------------------

    for index, item in enumerate(
        top_results,
        start=1,
    ):

        symbol = item["symbol"]

        price = item["price"]

        move_5m = item["move_5m"]

        move_15m = item["move_15m"]

        move_1h = item["move_1h"]

        volume_ratio = item[
            "volume_ratio"
        ]

        score = item["score"]

        momentum = item[
            "momentum_score"
        ]

        direction = item[
            "direction"
        ]

        breakout = item[
            "breakout"
        ]

        buy_setup = item[
            "buy_setup"
        ]

        lines.append(
            f"#{index} {symbol}"
        )

        lines.append(
            f"💰 Price: {fmt_price(price)}"
        )

        lines.append(
            f"5M: {fmt_percent(move_5m)}"
        )

        lines.append(
            f"15M: {fmt_percent(move_15m)}"
        )

        lines.append(
            f"1H: {fmt_percent(move_1h)}"
        )

        lines.append(
            f"📦 Volume: {volume_ratio:.2f}x"
        )

        lines.append(
            f"⭐ Score: {score}/9"
        )

        lines.append(
            f"🚀 Momentum: {momentum:.2f}"
        )

        if breakout:
            lines.append(
                "💥 BREAKOUT: YES"
            )
        else:
            lines.append(
                "💥 BREAKOUT: NO"
            )

        if buy_setup:

            lines.append(
                "🟢 BUY SETUP"
            )

            lines.append(
                f"🛑 SL: {fmt_price(item['sl'])}"
            )

            lines.append(
                f"🎯 TP: {fmt_price(item['tp'])}"
            )

        elif direction == "UP":

            lines.append(
                "🟢 UPWARD MOMENTUM"
            )

        elif direction == "RECOVERING":

            lines.append(
                "🟡 RECOVERING"
            )

        elif direction == "MIXED":

            lines.append(
                "🟠 MIXED MOMENTUM"
            )

        else:

            lines.append(
                "⚪ WEAK/DOWN"
            )

        lines.append("")

    # --------------------------------------------------------
    # SCAN STATISTICS
    # --------------------------------------------------------

    lines.append(
        f"📊 Sc
