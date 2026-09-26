import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.2
# BREAKOUT + RETEST SCANNER
# TELEGRAM DELIVERY TEST
# ============================================================

VERSION = "V38.2"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000
TOP_RESULTS = 3

BUY_MIN_SCORE = 11
WATCH_MIN_SCORE = 8

CHASE_LIMIT_5M = 7.0

REQUEST_TIMEOUT = 15

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ============================================================
# BASIC HELPERS
# ============================================================

def now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        if isinstance(value, bool):
            return default

        if isinstance(value, (int, float)):
            return float(value)

        if isinstance(value, str):
            value = value.strip().replace(",", "")
            if not value:
                return default
            return float(value)

        return default
    except Exception:
        return default


def safe_list(value):
    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    return []


def get_json(path, params=None):
    url = BASE_URL + path

    try:
        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
            headers={
                "User-Agent": "ATI-CRYPTO-BOT/38.2"
            },
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:
        print(f"API ERROR {path}: {e}")
        return None


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    """
    Sends Telegram message and prints exact result.
    """

    print("")
    print("=" * 60)
    print("TELEGRAM SEND TEST")
    print("=" * 60)

    if not TELEGRAM_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN is EMPTY")
        return False

    if not TELEGRAM_CHAT_ID:
        print("❌ TELEGRAM_CHAT_ID is EMPTY")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=20,
        )

        print(f"Telegram HTTP: {response.status_code}")

        try:
            data = response.json()
            print(f"Telegram response: {data}")
        except Exception:
            print(f"Telegram raw response: {response.text}")

        if response.status_code == 200:
            try:
                data = response.json()

                if data.get("ok") is True:
                    print("✅ TELEGRAM SEND: SUCCESS")
                    return True

            except Exception:
                pass

        print("❌ TELEGRAM SEND: FAILED")
        return False

    except Exception as e:
        print(f"❌ TELEGRAM CONNECTION ERROR: {e}")
        return False


# ============================================================
# STARTUP TELEGRAM TEST
# ============================================================

def startup_telegram_test():
    """
    This message is ALWAYS sent at startup.
    It does not depend on signal generation.
    """

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🟢 BOT STARTED\n"
        f"📡 Telegram connection test\n"
        f"⏱ {now_text()}\n\n"
        f"✅ If you received this message,\n"
        f"Telegram delivery is working."
    )

    return telegram_send(message)


# ============================================================
# MARKET DISCOVERY
# ============================================================

def extract_markets(data):
    """
    Tabdeal responses can be either:
    - list
    - dict containing list
    - dict containing nested market data
    """

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    possible_keys = [
        "data",
        "result",
        "results",
        "markets",
        "symbols",
        "items",
    ]

    for key in possible_keys:
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            for nested_key in possible_keys:
                nested = value.get(nested_key)

                if isinstance(nested, list):
                    return nested

    return []


def normalize_symbol(value):
    if not isinstance(value, str):
        return ""

    return (
        value
        .upper()
        .replace("/", "")
        .replace("-", "")
        .replace("_", "")
        .strip()
    )


def get_usdt_markets():
    """
    Try several public Tabdeal market endpoints.
    """

    endpoints = [
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
        "/r/api/v1/tickers",
    ]

    for endpoint in endpoints:

        data = get_json(endpoint)

        markets = extract_markets(data)

        if not markets:
            continue

        result = []

        for item in markets:

            if isinstance(item, str):
                symbol = normalize_symbol(item)

            elif isinstance(item, dict):

                symbol = ""

                for key in [
                    "symbol",
                    "market",
                    "pair",
                    "name",
                    "code",
                ]:
                    if key in item:
                        symbol = normalize_symbol(
                            str(item.get(key))
                        )

                        if symbol:
                            break

            else:
                continue

            if not symbol:
                continue

            if not symbol.endswith("USDT"):
                continue

            if symbol in result:
                continue

            result.append(symbol)

            if len(result) >= MAX_MARKETS:
                break

        if result:
            print(
                f"📊 USDT MARKETS: {len(result)}"
            )

            return result

    print("❌ Could not get USDT markets")
    return []


# ============================================================
# TRADES -> 5M CANDLES
# ============================================================

def get_trades(symbol):
    data = get_json(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in [
            "data",
            "result",
            "trades",
            "items",
        ]:

            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


def trade_price(item):
    if not isinstance(item, dict):
        return 0.0

    for key in [
        "price",
        "p",
        "lastPrice",
    ]:
        if key in item:
            return safe_float(item.get(key))

    return 0.0


def trade_quantity(item):
    if not isinstance(item, dict):
        return 0.0

    for key in [
        "qty",
        "quantity",
        "amount",
        "q",
        "volume",
    ]:
        if key in item:
            return safe_float(item.get(key))

    return 0.0


def trade_timestamp(item):
    if not isinstance(item, dict):
        return 0

    for key in [
        "timestamp",
        "time",
        "T",
        "createdAt",
        "created_at",
    ]:

        if key not in item:
            continue

        value = safe_float(item.get(key))

        if value <= 0:
            continue

        # milliseconds
        if value > 10_000_000_000:
            value = value / 1000

        return int(value)

    return 0


def trades_to_candles(trades):
    """
    Converts Tabdeal trade list into 5-minute candles.
    """

    if not trades:
        return []

    buckets = {}

    for trade in trades:

        price = trade_price(trade)

        if price <= 0:
            continue

        timestamp = trade_timestamp(trade)

        if timestamp <= 0:
            continue

        quantity = trade_quantity(trade)

        bucket = timestamp - (
            timestamp % 300
        )

        if bucket not in buckets:
            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity,
            }

        candle = buckets[bucket]

        candle["high"] = max(
            candle["high"],
            price,
        )

        candle["low"] = min(
            candle["low"],
            price,
        )

        candle["close"] = price

        candle["volume"] += quantity

    candles = list(buckets.values())

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles[-CANDLE_LIMIT:]


# ============================================================
# TECHNICAL HELPERS
# ============================================================

def percent_change(old, new):
    if old <= 0:
        return 0.0

    return ((new - old) / old) * 100.0


def highest(candles, start, end):
    values = [
        c["high"]
        for c in candles[start:end]
        if c["high"] > 0
    ]

    return max(values) if values else 0.0


def lowest(candles, start, end):
    values = [
        c["low"]
        for c in candles[start:end]
        if c["low"] > 0
    ]

    return min(values) if values else 0.0


def average_volume(candles):
    values = [
        c["volume"]
        for c in candles
        if c["volume"] > 0
    ]

    if not values:
        return 0.0

    return sum(values) / len(values)


# ============================================================
# SIGNAL ANALYSIS
# ============================================================

def analyze_symbol(symbol):
    trades = get_trades(symbol)

    candles = trades_to_candles(trades)

    if len(candles) < 25:
        return None

    # Use CLOSED candle
    closed = candles[:-1]

    if len(closed) < 25:
        return None

    current = closed[-1]
    previous = closed[-2]

    price = current["close"]

    if price <= 0:
        return None

    # --------------------------------------------------------
    # 5M MOMENTUM
    # --------------------------------------------------------

    ref_5m = closed[-2]["close"]

    move_5m = percent_change(
        ref_5m,
        price,
    )

    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    ref_15m = closed[-4]["close"]

    move_15m = percent_change(
        ref_15m,
        price,
    )

    # --------------------------------------------------------
    # 1H MOMENTUM
    # --------------------------------------------------------

    ref_1h = closed[-13]["close"]

    move_1h = percent_change(
        ref_1h,
        price,
    )

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    resistance = highest(
        closed,
        -13,
        -1,
    )

    breakout = (
        resistance > 0
        and price > resistance
    )

    # --------------------------------------------------------
    # PREVIOUS HIGH
    # --------------------------------------------------------

    previous_high = previous["high"]

    strong_close = (
        price >= current["low"]
        + (
            current["high"]
            - current["low"]
        ) * 0.65
    )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    avg_vol = average_volume(
        closed[-21:-1]
    )

    volume_ratio = 0.0

    if avg_vol > 0:
        volume_ratio = (
            current["volume"]
            / avg_vol
        )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    reasons = []

    # 5M positive
    if move_5m > 0:
        score += 2
        reasons.append("5M+")

    if move_5m >= 0.30:
        score += 1
        reasons.append("5M MOM")

    # 15M positive
    if move_15m > 0:
        score += 2
        reasons.append("15M+")

    if move_15m >= 0.50:
        score += 1
        reasons.append("15M MOM")

    # 1H positive
    if move_1h > 0:
        score += 2
        reasons.append("1H+")

    if move_1h >= 1.00:
        score += 1
        reasons.append("1H MOM")

    # Breakout
    if breakout:
        score += 3
        reasons.append("BREAKOUT")

    # Strong candle close
    if strong_close:
        score += 1
        reasons.append("STRONG CLOSE")

    # Volume
    if volume_ratio >= 1.20:
        score += 2
        reasons.append("VOLUME")

    elif volume_ratio >= 1.05:
        score += 1
        reasons.append("VOL+")

    # Previous high confirmation
    if price > previous_high:
        score += 1
        reasons.append("HIGH BREAK")

    # --------------------------------------------------------
    # CHASE FILTER
    # --------------------------------------------------------

    if move_5m > CHASE_LIMIT_5M:
        return {
            "symbol": symbol,
            "price": price,
            "score": score,
            "move_5m": move_5m,
            "move_15m": move_15m,
            "move_1h": move_1h,
            "volume_ratio": volume_ratio,
            "signal": "CHASE",
            "reasons": reasons,
        }

    # --------------------------------------------------------
    # SIGNAL TYPE
    # --------------------------------------------------------

    if score >= BUY_MIN_SCORE:
        signal = "BUY"

    elif score >= WATCH_MIN_SCORE:
        signal = "WATCH"

    else:
        signal = "NONE"

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    stop_loss = price * 0.995
    take_profit_1 = price * 1.010
    take_profit_2 = price * 1.020

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "move_5m": move_5m,
        "move_15m": move_15m,
        "move_1h": move_1h,
        "volume_ratio": volume_ratio,
        "signal": signal,
        "stop_loss": stop_loss,
        "tp1": take_profit_1,
        "tp2": take_profit_2,
        "reasons": reasons,
    }


# ============================================================
# SCANNER
# ============================================================

def scan_markets(markets):

    results = []

    total = len(markets)

    print("")
    print("=" * 60)
    print("🚀 STARTING MARKET SCAN")
    print("=" * 60)
    print(f"Markets: {total}")

    for index, symbol in enumerate(
        markets,
        start=1,
    ):

        try:

            result = analyze_symbol(
                symbol
            )

            if result is not None:

                if result["signal"] in [
                    "BUY",
                    "WATCH",
                ]:

                    results.append(result)

            if index % 25 == 0:

                print(
                    f"Scanning: {index}/{total}"
                )

        except Exception as e:

            print(
                f"⚠️ {symbol}: {e}"
            )

    results.sort(
        key=lambda x: (
            x["score"],
            x["move_5m"],
            x["move_15m"],
        ),
        reverse=True,
    )

    return results[:TOP_RESULTS]


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(result, rank):

    symbol = result["symbol"]

    signal = result["signal"]

    score = result["score"]

    price = result["price"]

    move_5m = result["move_5m"]

    move_15m = result["move_15m"]

    move_1h = result["move_1h"]

    volume_ratio = result["volume_ratio"]

    reasons = ", ".join(
        result["reasons"]
    )

    emoji = (
        "🟢"
        if signal == "BUY"
        else "🟡"
    )

    message = (
        f"{emoji} {signal}\n\n"
        f"#{rank}\n"
        f"🪙 {symbol}\n"
        f"⭐ SCORE: {score}\n"
        f"💰 PRICE: {price:.10g}\n\n"
        f"📈 5M: {move_5m:+.2f}%\n"
        f"📊 15M: {move_15m:+.2f}%\n"
        f"⏱ 1H: {move_1h:+.2f}%\n"
        f"📦 VOL: {volume_ratio:.2f}x\n\n"
    )

    if signal == "BUY":

        message += (
            f"🛑 SL: {result['stop_loss']:.10g}\n"
            f"🎯 TP1: {result['tp1']:.10g}\n"
            f"🎯 TP2: {result['tp2']:.10g}\n\n"
        )

    message += (
        f"🔎 {reasons}\n\n"
        f"⚡ ATI BOT {VERSION}"
    )

    return message


# ============================================================
# MAIN
# ============================================================

def main():

    print("")
    print("=" * 60)
    print(f"⚡ ATI CRYPTO BOT {VERSION}")
    print("🚀 BREAKOUT + RETEST SCANNER")
    print("=" * 60)

    print(
        f"⏱ Timeframe: {TIMEFRAME}"
    )

    print(
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}"
    )

    print(
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}"
    )

    print(
        f"🚫 5M CHASE LIMIT: {CHASE_LIMIT_5M}%"
    )

    print("")
    print(
        f"📡 TABDEAL: {BASE_URL}"
    )

    # --------------------------------------------------------
    # TELEGRAM TEST FIRST
    # --------------------------------------------------------

    telegram_ok = startup_telegram_test()

    if telegram_ok:
        print(
            "🟢 Telegram startup test PASSED"
        )
    else:
        print(
            "🔴 Telegram startup test FAILED"
        )

    # --------------------------------------------------------
    # API TEST
    # --------------------------------------------------------

    print("")
    print("=" * 60)
    print("TABDEAL API TEST")
    print("=" * 60)

    markets = get_usdt_markets()

    if not markets:

        error_message = (
            f"🔴 ATI BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET SCAN FAILED\n"
            f"⏱ {now_text()}"
        )

        telegram_send(error_message)

        print(
            "❌ No markets found."
        )

        return

    print(
        f"✅ TABDEAL API OK"
    )

    print(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results = scan_markets(
        markets
    )

    print("")
    print("=" * 60)
    print("SCAN RESULT")
    print("=" * 60)

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if not results:

        print(
            "🟡 NO BUY / WATCH SIGNAL"
        )

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"🟡 SCAN COMPLETED\n\n"
            f"📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: {len(markets)}\n"
            f"🔎 BUY/WATCH: NONE\n\n"
            f"⏱ {now_text()}\n\n"
            f"✅ Telegram delivery is working."
        )

        telegram_send(message)

        return

    # --------------------------------------------------------
    # SIGNALS
    # --------------------------------------------------------

    header = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 BREAKOUT + RETEST SCANNER\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}\n"
        f"🚫 5M CHASE LIMIT: {CHASE_LIMIT_5M}%\n\n"
    )

    messages = []

    for rank, result in enumerate(
        results,
        start=1,
    ):

        print(
            f"{rank}. "
            f"{result['signal']} "
            f"{result['symbol']} "
            f"Score={result['score']}"
        )

        messages.append(
            format_signal(
                result,
                rank,
            )
        )

    final_message = (
        header
        + "\n\n".join(messages)
    )

    # --------------------------------------------------------
    # TELEGRAM SIGNAL
    # --------------------------------------------------------

    telegram_send(
        final_message
    )

    print("")
    print("=" * 60)
    print("✅ BOT FINISHED")
    print("=" * 60)


if __name__ == "__main__":

    try:
        main()

    except Exception as e:

        print("")
        print("=" * 60)
        print("🔴 FATAL ERROR")
        print("=" * 60)

        print(
            f"{type(e).__name__}: {e}"
        )

        # Try to notify Telegram
        telegram_send(
            f"🔴 ATI BOT {VERSION}\n\n"
            f"FATAL ERROR\n"
            f"{type(e).__name__}: {e}\n\n"
            f"⏱ {now_text()}"
        )

        raise
