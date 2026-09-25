import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V37.7
# TABDEAL USDT UPWARD SCANNER
# ============================================================

VERSION = "V37.7"

BASE_URL = "https://api1.tabdeal.org"

MAX_MARKETS = 1000
TOP_RESULTS = 5
MIN_SCORE = 6

TRADE_LIMIT = 1000
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.03

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT-V37.7",
    "Accept": "application/json",
})


# ============================================================
# TIME
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


# ============================================================
# SAFE FLOAT
# ============================================================

def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        return float(value)

    except Exception:
        return default


# ============================================================
# API GET
# ============================================================

def api_get(path, params=None):

    url = BASE_URL + path

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    except Exception as exc:

        print(
            f"API ERROR {path}: {exc}"
        )

        return None


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

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:

            print("Telegram: OK")
            return True

        print(
            "Telegram ERROR:",
            response.text,
        )

        return False

    except Exception as exc:

        print(
            "Telegram ERROR:",
            exc,
        )

        return False


# ============================================================
# TABDEAL MARKET LIST
# ============================================================

def load_usdt_markets():

    print()
    print("Loading Tabdeal exchangeInfo...")

    data = api_get(
        "/r/api/v1/exchangeInfo"
    )

    if data is None:

        print(
            "exchangeInfo returned None"
        )

        return []

    # --------------------------------------------------------
    # Tabdeal official API normally returns a LIST
    # --------------------------------------------------------

    if isinstance(data, list):

        market_items = data

    elif isinstance(data, dict):

        market_items = []

        for key in (
            "data",
            "result",
            "symbols",
            "markets",
        ):

            value = data.get(key)

            if isinstance(value, list):

                market_items = value
                break

    else:

        market_items = []

    if not market_items:

        print(
            "No market data found."
        )

        print(
            "Response type:",
            type(data).__name__,
        )

        return []

    markets = []

    for item in market_items:

        if not isinstance(item, dict):
            continue

        symbol = item.get(
            "symbol",
            ""
        )

        status = str(
            item.get(
                "status",
                "TRADING"
            )
        ).upper()

        quote_asset = str(
            item.get(
                "quoteAsset",
                ""
            )
        ).upper()

        if not isinstance(symbol, str):
            continue

        symbol = (
            symbol
            .upper()
            .replace("_", "")
            .replace("-", "")
            .replace("/", "")
        )

        # ----------------------------------------------------
        # Only USDT
        # ----------------------------------------------------

        if quote_asset:

            if quote_asset != "USDT":
                continue

        else:

            if not symbol.endswith("USDT"):
                continue

        # ----------------------------------------------------
        # Only trading markets
        # ----------------------------------------------------

        if status not in (
            "TRADING",
            "ENABLED",
            "ACTIVE",
        ):

            continue

        if not symbol.endswith("USDT"):
            continue

        if symbol not in markets:

            markets.append(symbol)

    markets = sorted(
        set(markets)
    )

    markets = markets[:MAX_MARKETS]

    print(
        f"MARKETS OK: {len(markets)} USDT markets"
    )

    return markets


# ============================================================
# LOAD TRADES
# ============================================================

def load_trades(symbol):

    data = api_get(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    )

    if isinstance(data, list):

        return data

    if isinstance(data, dict):

        for key in (
            "data",
            "result",
            "trades",
            "items",
        ):

            value = data.get(key)

            if isinstance(value, list):

                return value

    return []


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = safe_float(
        item.get("price")
    )

    quantity = safe_float(
        item.get("qty")
    )

    timestamp = item.get(
        "time"
    )

    if timestamp is None:

        timestamp = item.get(
            "timestamp"
        )

    if price <= 0:
        return None

    if quantity <= 0:
        quantity = 1.0

    timestamp = safe_float(
        timestamp
    )

    if timestamp <= 0:
        return None

    # milliseconds -> seconds

    if timestamp > 100000000000:

        timestamp /= 1000

    return {
        "price": price,
        "quantity": quantity,
        "timestamp": timestamp,
    }


# ============================================================
# BUILD 5 MINUTE CANDLES
# ============================================================

def build_candles(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade:

            parsed.append(
                trade
            )

    if not parsed:
        return []

    parsed.sort(
        key=lambda x: x["timestamp"]
    )

    candles = {}

    bucket_size = 300

    for trade in parsed:

        bucket = (
            int(
                trade["timestamp"]
                / bucket_size
            )
            * bucket_size
        )

        price = trade["price"]
        quantity = trade["quantity"]

        if bucket not in candles:

            candles[bucket] = {
                "timestamp": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity,
            }

        else:

            candle = candles[bucket]

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

    return sorted(
        candles.values(),
        key=lambda x: x["timestamp"],
    )


# ============================================================
# PERCENT CHANGE
# ============================================================

def percent_change(old, new):

    if old <= 0:
        return 0.0

    return (
        (new - old)
        / old
        * 100
    )


# ============================================================
# MOMENTUM
# ============================================================

def get_momentum(
    candles,
    periods,
):

    if len(candles) <= periods:
        return 0.0

    old_price = candles[
        -(periods + 1)
    ]["close"]

    new_price = candles[-1]["close"]

    return percent_change(
        old_price,
        new_price,
    )


# ============================================================
# ANALYZE
# ============================================================

def analyze_market(symbol):

    trades = load_trades(
        symbol
    )

    if not trades:
        return None

    candles = build_candles(
        trades
    )

    if len(candles) < 15:
        return None

    # Ignore current unfinished candle

    closed = candles[:-1]

    if len(closed) < 14:
        return None

    last = closed[-1]
    previous = closed[-2]

    price = last["close"]

    if price <= 0:
        return None

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    m5 = get_momentum(
        closed,
        1
    )

    m15 = get_momentum(
        closed,
        3
    )

    m1h = get_momentum(
        closed,
        12
    )

    score = 0

    # --------------------------------------------------------
    # 5M
    # --------------------------------------------------------

    if m5 > 0.10:
        score += 2

    elif m5 > 0.03:
        score += 1

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    if m15 > 0.30:
        score += 3

    elif m15 > 0.10:
        score += 2

    elif m15 > 0:
        score += 1

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    if m1h > 0.80:
        score += 3

    elif m1h > 0.30:
        score += 2

    elif m1h > 0:
        score += 1

    # --------------------------------------------------------
    # BULLISH CANDLE
    # --------------------------------------------------------

    if last["close"] > last["open"]:

        score += 1

    # --------------------------------------------------------
    # BREAK PREVIOUS HIGH
    # --------------------------------------------------------

    if last["close"] > previous["high"]:

        score += 2

    # --------------------------------------------------------
    # HIGHER HIGH
    # --------------------------------------------------------

    recent = closed[-6:]

    if len(recent) >= 6:

        old_high = max(
            c["high"]
            for c in recent[:-1]
        )

        if last["high"] > old_high:

            score += 2

    # --------------------------------------------------------
    # REQUIRE POSITIVE MOMENTUM
    # --------------------------------------------------------

    if m5 <= 0 and m15 <= 0:

        return None

    if score < MIN_SCORE:

        return None

    # --------------------------------------------------------
    # TARGETS
    # --------------------------------------------------------

    sl = price * 0.995
    tp1 = price * 1.008
    tp2 = price * 1.015

    return {
        "symbol": symbol,
        "score": score,
        "price": price,
        "m5": m5,
        "m15": m15,
        "m1h": m1h,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


# ============================================================
# SCAN
# ============================================================

def scan_markets(markets):

    results = []

    total = len(markets)

    print()
    print(
        f"Scanning {total} markets..."
    )

    for index, symbol in enumerate(
        markets,
        start=1,
    ):

        try:

            result = analyze_market(
                symbol
            )

            if result:

                results.append(
                    result
                )

        except Exception as exc:

            print(
                f"{symbol} ERROR: {exc}"
            )

        if index % 50 == 0:

            print(
                f"Progress: "
                f"{index}/{total}"
            )

        time.sleep(
            SLEEP_BETWEEN_MARKETS
        )

    results.sort(
        key=lambda x: (
            x["score"],
            x["m15"],
            x["m5"],
        ),
        reverse=True,
    )

    return results[
        :TOP_RESULTS
    ]


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def create_message(
    signals,
    market_count,
):

    lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "",
        "🚀 STRONG UPWARD SIGNALS",
        "",
        "📡 TABDEAL API: OK",
        f"📊 USDT MARKETS: {market_count}",
        f"⭐ MIN SCORE: {MIN_SCORE}",
        "",
    ]

    if not signals:

        lines.extend([
            "❌ NO STRONG SIGNAL",
            "",
            "Scanner completed.",
            "",
            f"🕐 {now_utc()}",
        ])

        return "\n".join(
            lines
        )

    for index, signal in enumerate(
        signals,
        start=1,
    ):

        lines.extend([
            f"#{index} SIGNAL",
            f"🪙 {signal['symbol']}",
            f"⭐ SCORE: {signal['score']}",
            f"💰 PRICE: {signal['price']:.8f}",
            f"📈 5M: {signal['m5']:+.2f}%",
            f"📊 15M: {signal['m15']:+.2f}%",
            f"⏱ 1H: {signal['m1h']:+.2f}%",
            "",
            f"🛑 SL: {signal['sl']:.8f}",
            f"🎯 TP1: {signal['tp1']:.8f}",
            f"🎯 TP2: {signal['tp2']:.8f}",
            "",
        ])

    lines.append(
        f"🕐 {now_utc()}"
    )

    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)

    print(
        f"ATI CRYPTO BOT {VERSION}"
    )

    print(
        "TABDEAL USDT UPWARD SCANNER"
    )

    print("=" * 60)

    markets = load_usdt_markets()

    if not markets:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "❌ TABDEAL MARKET ERROR\n"
            "Could not load USDT markets.\n\n"
            f"🕐 {now_utc()}"
        )

        print(message)

        send_telegram(
            message
        )

        return

    print()
    print(
        f"✅ TABDEAL API: OK"
    )

    print(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    signals = scan_markets(
        markets
    )

    message = create_message(
        signals,
        len(markets),
    )

    print()
    print(message)

    send_telegram(
        message
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
