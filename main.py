import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.6.1
# TELEGRAM TEST + STRICT ENTRY SCANNER
# ============================================================

VERSION = "V38.6.1"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
CANDLE_LIMIT = 720
MAX_MARKETS = 1000

BUY_MIN_SCORE = 13
WATCH_MIN_SCORE = 10

TOP_RESULTS = 10

MAX_5M_MOVE = 5.0
MAX_15M_MOVE = 10.0
MAX_1H_MOVE = 18.0

BUY_MAX_ENTRY_DISTANCE = 1.00
WATCH_MAX_ENTRY_DISTANCE = 1.25

MAX_BREAKOUT_DISTANCE = 1.50
MAX_RETEST_DISTANCE = 1.00

REQUEST_TIMEOUT = 15


# ============================================================
# TELEGRAM SECRETS
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-CRYPTO-BOT/38.6.1",
        "Accept": "application/json",
    }
)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "❌ TELEGRAM_BOT_TOKEN IS EMPTY"
        )

        return False

    if not TELEGRAM_CHAT_ID:

        print(
            "❌ TELEGRAM_CHAT_ID IS EMPTY"
        )

        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
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

        print(
            "TELEGRAM HTTP STATUS:",
            response.status_code
        )

        if response.ok:

            print(
                "✅ TELEGRAM MESSAGE SENT"
            )

            return True

        print(
            "❌ TELEGRAM ERROR:",
            response.text[:500]
        )

        return False

    except Exception as e:

        print(
            "❌ TELEGRAM CONNECTION ERROR:",
            str(e)
        )

        return False


# ============================================================
# TELEGRAM STARTUP TEST
# ============================================================

def telegram_startup_test():

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message = (
        "🟢 ATI BOT TELEGRAM TEST\n\n"
        f"⚡ VERSION: {VERSION}\n"
        "📡 TELEGRAM: CONNECTING\n"
        "🔧 TEST MODE: ON\n"
        f"🕐 {now}\n\n"
        "✅ اگر این پیام را می‌بینی، "
        "تلگرام ربات وصل است."
    )

    return send_telegram(message)


# ============================================================
# TABDEAL API
# ============================================================

def get_json(path, params=None):

    url = BASE_URL + path

    try:

        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:

        print(
            f"API ERROR {path}: {e}"
        )

        return None


# ============================================================
# MARKET DISCOVERY
# ============================================================

def extract_symbols(data):

    symbols = []

    if isinstance(data, list):

        items = data

    elif isinstance(data, dict):

        items = None

        for key in [
            "symbols",
            "data",
            "result",
            "markets",
            "items",
        ]:

            value = data.get(key)

            if isinstance(value, list):

                items = value
                break

        if items is None:
            items = []

    else:

        items = []

    for item in items:

        if isinstance(item, str):

            symbol = item.upper()

        elif isinstance(item, dict):

            symbol = ""

            for key in [
                "symbol",
                "market",
                "pair",
                "name",
            ]:

                value = item.get(key)

                if isinstance(value, str):

                    symbol = value.upper()
                    break

        else:

            continue

        if (
            symbol.endswith("USDT")
            and symbol.isalnum()
            and len(symbol) >= 7
        ):

            symbols.append(symbol)

    return sorted(
        set(symbols)
    )


def get_markets():

    endpoints = [
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/symbols",
        "/r/api/v1/markets",
    ]

    for endpoint in endpoints:

        data = get_json(
            endpoint
        )

        symbols = extract_symbols(
            data
        )

        if symbols:

            return symbols[
                :MAX_MARKETS
            ]

    return []


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):

    data = get_json(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if not isinstance(data, list):

        if isinstance(data, dict):

            for key in [
                "data",
                "result",
                "trades",
                "items",
            ]:

                value = data.get(
                    key
                )

                if isinstance(
                    value,
                    list,
                ):

                    data = value
                    break

    if not isinstance(data, list):

        return []

    return data


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(
        item,
        dict,
    ):

        return None

    price = None
    quantity = None
    timestamp = None

    for key in [
        "price",
        "p",
        "trade_price",
    ]:

        if key in item:

            try:

                price = float(
                    item[key]
                )

                break

            except Exception:
                pass

    for key in [
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
    ]:

        if key in item:

            try:

                quantity = float(
                    item[key]
                )

                break

            except Exception:
                pass

    for key in [
        "time",
        "timestamp",
        "ts",
        "T",
    ]:

        if key in item:

            try:

                timestamp = float(
                    item[key]
                )

                break

            except Exception:
                pass

    if price is None:

        return None

    if quantity is None:

        quantity = 1.0

    if timestamp is None:

        return None

    if timestamp > 10_000_000_000:

        timestamp /= 1000.0

    return {
        "price": price,
        "qty": quantity,
        "time": timestamp,
    }


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(
            item
        )

        if trade:

            parsed.append(
                trade
            )

    if not parsed:

        return []

    buckets = {}

    for trade in parsed:

        bucket = (
            int(
                trade["time"] // 300
            )
            * 300
        )

        if bucket not in buckets:

            buckets[bucket] = {
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
                "time": bucket,
            }

        candle = buckets[
            bucket
        ]

        candle["high"] = max(
            candle["high"],
            trade["price"],
        )

        candle["low"] = min(
            candle["low"],
            trade["price"],
        )

        candle["close"] = (
            trade["price"]
        )

        candle["volume"] += abs(
            trade["qty"]
        )

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    now = time.time()

    closed = [
        c
        for c in candles
        if c["time"] + 300 <= now
    ]

    return closed[
        -CANDLE_LIMIT:
    ]


# ============================================================
# PERCENT CHANGE
# ============================================================

def pct_change(old, new):

    if old == 0:

        return 0.0

    return (
        (new - old)
        / old
        * 100.0
    )


# ============================================================
# MOMENTUM
# ============================================================

def momentum(candles, count):

    if len(candles) < count + 1:

        return 0.0

    old_price = candles[
        -count - 1
    ]["close"]

    new_price = candles[
        -1
    ]["close"]

    return pct_change(
        old_price,
        new_price,
    )


# ============================================================
# HIGHER HIGH
# ============================================================

def higher_high(candles):

    if len(candles) < 12:

        return False

    recent = candles[-6:]
    previous = candles[-12:-6]

    recent_high = max(
        x["high"]
        for x in recent
    )

    previous_high = max(
        x["high"]
        for x in previous
    )

    return (
        recent_high
        > previous_high
    )


# ============================================================
# HIGHER LOW
# ============================================================

def higher_low(candles):

    if len(candles) < 12:

        return False

    recent = candles[-6:]
    previous = candles[-12:-6]

    recent_low = min(
        x["low"]
        for x in recent
    )

    previous_low = min(
        x["low"]
        for x in previous
    )

    return (
        recent_low
        > previous_low
    )


# ============================================================
# BREAKOUT
# ============================================================

def find_breakout(candles):

    if len(candles) < 25:

        return None

    current = candles[-1]

    previous = candles[
        -21:-1
    ]

    resistance = max(
        x["high"]
        for x in previous
    )

    price = current[
        "close"
    ]

    if resistance <= 0:

        return None

    distance = pct_change(
        resistance,
        price,
    )

    if price <= resistance:

        return None

    if distance > MAX_BREAKOUT_DISTANCE:

        return None

    return {
        "breakout": resistance,
        "distance": distance,
    }


# ============================================================
# RETEST
# ============================================================

def has_retest(
    candles,
    breakout_price,
):

    if len(candles) < 5:

        return False

    recent = candles[-5:]

    tolerance = (
        breakout_price
        * MAX_RETEST_DISTANCE
        / 100.0
    )

    for candle in recent:

        touched = (
            candle["low"]
            <= breakout_price
            + tolerance
        )

        held = (
            candle["close"]
            >= breakout_price
        )

        if touched and held:

            return True

    return False


# ============================================================
# VOLUME
# ============================================================

def volume_ratio(candles):

    if len(candles) < 21:

        return 1.0

    current_volume = (
        candles[-1]["volume"]
    )

    previous_volumes = [
        x["volume"]
        for x in candles[
            -21:-1
        ]
        if x["volume"] > 0
    ]

    if not previous_volumes:

        return 1.0

    average_volume = (
        sum(previous_volumes)
        / len(previous_volumes)
    )

    if average_volume <= 0:

        return 1.0

    return (
        current_volume
        / average_volume
    )


# ============================================================
# STRONG CANDLE
# ============================================================

def strong_candle(candle):

    candle_range = (
        candle["high"]
        - candle["low"]
    )

    if candle_range <= 0:

        return False

    body = abs(
        candle["close"]
        - candle["open"]
    )

    body_ratio = (
        body / candle_range
    )

    close_position = (
        candle["close"]
        - candle["low"]
    ) / candle_range

    return (
        body_ratio >= 0.45
        and close_position >= 0.65
        and candle["close"]
        > candle["open"]
    )


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(symbol):

    trades = get_trades(
        symbol
    )

    if len(trades) < 100:

        return None

    candles = build_candles(
        trades
    )

    if len(candles) < 50:

        return None

    current = candles[-1]

    price = current[
        "close"
    ]

    if price <= 0:

        return None

    move_5m = momentum(
        candles,
        1,
    )

    move_15m = momentum(
        candles,
        3,
    )

    move_1h = momentum(
        candles,
        12,
    )

    if move_5m <= 0:

        return None

    if move_15m <= 0:

        return None

    if move_1h <= 0:

        return None

    if move_5m > MAX_5M_MOVE:

        return None

    if move_15m > MAX_15M_MOVE:

        return None

    if move_1h > MAX_1H_MOVE:

        return None

    breakout_info = find_breakout(
        candles
    )

    if not breakout_info:

        return None

    breakout = breakout_info[
        "breakout"
    ]

    breakout_distance = (
        breakout_info[
            "distance"
        ]
    )

    # STRICT ENTRY
    if (
        breakout_distance
        > WATCH_MAX_ENTRY_DISTANCE
    ):

        return None

    retest = has_retest(
        candles,
        breakout,
    )

    if not retest:

        return None

    hh = higher_high(
        candles
    )

    hl = higher_low(
        candles
    )

    vol_ratio = volume_ratio(
        candles
    )

    score = 0

    reasons = []

    if move_5m > 0:

        score += 1
        reasons.append(
            "5M UP"
        )

    if move_5m >= 0.30:

        score += 1
        reasons.append(
            "5M STRONG"
        )

    if move_15m > 0:

        score += 1
        reasons.append(
            "15M UP"
        )

    if move_15m >= 0.50:

        score += 1
        reasons.append(
            "15M STRONG"
        )

    if move_1h > 0:

        score += 1
        reasons.append(
            "1H UP"
        )

    if move_1h >= 1.00:

        score += 1
        reasons.append(
            "1H STRONG"
        )

    if hh:

        score += 2
        reasons.append(
            "HIGHER HIGH"
        )

    if hl:

        score += 2
        reasons.append(
            "HIGHER LOW"
        )

    score += 2
    reasons.append(
        "BREAKOUT"
    )

    score += 2
    reasons.append(
        "RETEST"
    )

    if breakout_distance <= 0.75:

        score += 2
        reasons.append(
            "CLOSE TO BREAKOUT"
        )

    elif (
        breakout_distance
        <= BUY_MAX_ENTRY_DISTANCE
    ):

        score += 1
        reasons.append(
            "GOOD BREAKOUT DISTANCE"
        )

    else:

        reasons.append(
            "LATE ENTRY"
        )

    if vol_ratio >= 1.50:

        score += 1
        reasons.append(
            "VOLUME"
        )

    if strong_candle(current):

        score += 1
        reasons.append(
            "STRONG CANDLE"
        )

    buy_eligible = (
        breakout_distance
        <= BUY_MAX_ENTRY_DISTANCE
    )

    if score < WATCH_MIN_SCORE:

        return None

    sl_price = (
        price * 0.955
    )

    tp1_price = (
        price * 1.085
    )

    tp2_price = (
        price * 1.12
    )

    return {
        "symbol": symbol,
        "price": price,
        "score": score,

        "move_5m": move_5m,
        "move_15m": move_15m,
        "move_1h": move_1h,

        "breakout": breakout,
        "breakout_distance":
            breakout_distance,

        "volume_ratio":
            vol_ratio,

        "higher_high": hh,
        "higher_low": hl,
        "retest": retest,

        "buy_eligible":
            buy_eligible,

        "sl": sl_price,
        "tp1": tp1_price,
        "tp2": tp2_price,

        "reasons": reasons,
    }


# ============================================================
# PRICE FORMAT
# ============================================================

def fmt_price(value):

    if value >= 100:

        return f"{value:.2f}"

    if value >= 1:

        return f"{value:.5f}"

    if value >= 0.01:

        return f"{value:.7f}"

    return f"{value:.10f}"


# ============================================================
# SIGNAL FORMAT
# ============================================================

def format_signal(
    item,
    signal_type,
):

    emoji = (
        "🟢"
        if signal_type == "BUY"
        else "🟡"
    )

    lines = [

        f"{emoji} {signal_type}",

        f"🪙 {item['symbol']}",

        f"⭐ SCORE: "
        f"{item['score']}",

        f"💰 PRICE: "
        f"{fmt_price(item['price'])}",

        "",

        f"📈 5M: "
        f"{item['move_5m']:+.2f}%",

        f"📊 15M: "
        f"{item['move_15m']:+.2f}%",

        f"🕐 1H: "
        f"{item['move_1h']:+.2f}%",

        "",

        f"🚀 BREAKOUT: "
        f"{fmt_price(item['breakout'])}",

        f"📏 DISTANCE: "
        f"{item['breakout_distance']:.2f}%",

        f"📦 VOLUME: "
        f"{item['volume_ratio']:.2f}x",

        "",

        f"🛑 SL: "
        f"{fmt_price(item['sl'])}",

        f"🎯 TP1: "
        f"{fmt_price(item['tp1'])}",

        f"🎯 TP2: "
        f"{fmt_price(item['tp2'])}",

        "",

        "🔎 "
        + " | ".join(
            item["reasons"]
        ),

        "",

        "⚠️ SIGNAL ONLY — "
        "NO REAL ORDER",
    ]

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
        "BREAKOUT + RETEST "
        "STRICT ENTRY SCANNER"
    )

    print("=" * 60)

    # --------------------------------------------------------
    # TELEGRAM TEST FIRST
    # --------------------------------------------------------

    print(
        "📱 SENDING TELEGRAM STARTUP TEST..."
    )

    telegram_ok = (
        telegram_startup_test()
    )

    if telegram_ok:

        print(
            "✅ TELEGRAM STARTUP TEST OK"
        )

    else:

        print(
            "❌ TELEGRAM STARTUP TEST FAILED"
        )

    # --------------------------------------------------------
    # MARKET DATA
    # --------------------------------------------------------

    markets = get_markets()

    if not markets:

        message = (
            f"⚠️ ATI BOT {VERSION}\n\n"
            "❌ TABDEAL MARKET DATA ERROR\n\n"
            "No USDT markets found.\n\n"
            "Telegram connection was tested."
        )

        print(message)

        send_telegram(
            message
        )

        return

    print(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    print(
        f"🟢 BUY MIN SCORE: "
        f"{BUY_MIN_SCORE}"
    )

    print(
        f"🟡 WATCH MIN SCORE: "
        f"{WATCH_MIN_SCORE}"
    )

    print(
        f"🟢 BUY MAX DISTANCE: "
        f"{BUY_MAX_ENTRY_DISTANCE}%"
    )

    print(
        f"🟡 WATCH MAX DISTANCE: "
        f"{WATCH_MAX_ENTRY_DISTANCE}%"
    )

    results = []

    for index, symbol in enumerate(
        markets,
        1,
    ):

        try:

            result = analyze_symbol(
                symbol
            )

            if result:

                results.append(
                    result
                )

        except Exception as e:

            print(
                f"ERROR {symbol}: "
                f"{e}"
            )

        time.sleep(0.03)

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["score"],
            x["volume_ratio"],
            x["move_1h"],
        ),
        reverse=True,
    )

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    buys = [

        x
        for x in results

        if (
            x["score"]
            >= BUY_MIN_SCORE
            and x["buy_eligible"]
        )
    ]

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    watches = [

        x
        for x in results

        if (
            x["score"]
            >= WATCH_MIN_SCORE
            and (
                x["score"]
                < BUY_MIN_SCORE

                or not
                x["buy_eligible"]
            )
        )
    ]

    buys = buys[
        :TOP_RESULTS
    ]

    watches = watches[
        :TOP_RESULTS
    ]

    # --------------------------------------------------------
    # FINAL MESSAGE
    # --------------------------------------------------------

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    message_lines = [

        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}",

        "",

        "🚀 BREAKOUT + RETEST "
        "STRICT ENTRY",

        "",

        "📡 TABDEAL API: OK",

        f"📊 USDT MARKETS: "
        f"{len(markets)}",

        "",

        f"🟢 BUY MIN SCORE: "
        f"{BUY_MIN_SCORE}",

        f"🟡 WATCH MIN SCORE: "
        f"{WATCH_MIN_SCORE}",

        f"🟢 BUY MAX
