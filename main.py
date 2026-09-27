import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.9
# EARLY ENTRY + CONFIRMED BREAKOUT
# AUTO 5 MINUTE SCANNER
# ============================================================

VERSION = "V38.9"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

CANDLE_LIMIT = 720
MAX_MARKETS = 1000

REQUEST_TIMEOUT = 15

# ============================================================
# SIGNAL SCORE
# ============================================================

CONFIRMED_BUY_MIN_SCORE = 10
EARLY_BUY_MIN_SCORE = 9
WATCH_MIN_SCORE = 7

TOP_RESULTS = 5

# ============================================================
# MOMENTUM LIMITS
# ============================================================

MAX_5M_MOVE = 6.0
MAX_15M_MOVE = 12.0
MAX_1H_MOVE = 20.0

# ============================================================
# EARLY ENTRY
# ============================================================

EARLY_RESISTANCE_DISTANCE = 1.20

MAX_CONFIRMED_DISTANCE = 2.50

MAX_EARLY_DISTANCE = 1.50

# ============================================================
# RETEST
# ============================================================

RETEST_DISTANCE = 1.50

# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)

TELEGRAM_MAX_LENGTH = 3900

# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT/38.9",
    "Accept": "application/json",
})


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:

        print(
            "ERROR: TELEGRAM_BOT_TOKEN IS EMPTY"
        )

        return False

    if not TELEGRAM_CHAT_ID:

        print(
            "ERROR: TELEGRAM_CHAT_ID IS EMPTY"
        )

        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    chunks = []

    while len(message) > TELEGRAM_MAX_LENGTH:

        cut = message.rfind(
            "\n",
            0,
            TELEGRAM_MAX_LENGTH
        )

        if cut <= 0:
            cut = TELEGRAM_MAX_LENGTH

        chunks.append(
            message[:cut]
        )

        message = message[cut:].lstrip()

    if message:
        chunks.append(message)

    success = True

    for chunk in chunks:

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk,
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
                    "TELEGRAM MESSAGE SENT"
                )

            else:

                print(
                    "TELEGRAM ERROR:",
                    response.text[:500]
                )

                success = False

        except Exception as e:

            print(
                "TELEGRAM CONNECTION ERROR:",
                str(e)
            )

            success = False

    return success


def telegram_startup_test():

    message = (
        "🟢 ATI BOT TELEGRAM TEST\n\n"
        f"⚡ VERSION: {VERSION}\n"
        "📡 TELEGRAM: OK\n"
        "🔧 AUTO SCAN: ON\n"
        "⏱ SCHEDULE: 5 MIN\n"
        f"🕐 {utc_now()}\n\n"
        "✅ Telegram connection is working."
    )

    return send_telegram(message)


# ============================================================
# API
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

        items = []

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

        data = get_json(endpoint)

        symbols = extract_symbols(data)

        if symbols:

            print(
                f"MARKET ENDPOINT OK: "
                f"{endpoint}"
            )

            return symbols[:MAX_MARKETS]

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

    if isinstance(data, dict):

        for key in [
            "data",
            "result",
            "trades",
            "items",
        ]:

            value = data.get(key)

            if isinstance(value, list):

                data = value

                break

    if not isinstance(data, list):

        return []

    return data


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):

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

    if timestamp > 10000000000:
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

        trade = parse_trade(item)

        if trade:

            parsed.append(
                trade
            )

    if not parsed:
        return []

    parsed.sort(
        key=lambda x: x["time"]
    )

    buckets = {}

    for trade in parsed:

        bucket = (
            int(
                trade["time"]
                // 300
            )
            * 300
        )

        if bucket not in buckets:

            buckets[bucket] = {

                "open":
                    trade["price"],

                "high":
                    trade["price"],

                "low":
                    trade["price"],

                "close":
                    trade["price"],

                "volume":
                    0.0,

                "time":
                    bucket,
            }

        candle = buckets[bucket]

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

        candle

        for candle in candles

        if candle["time"]
        + 300
        <= now
    ]

    return closed[-CANDLE_LIMIT:]


# ============================================================
# HELPERS
# ============================================================

def pct_change(old, new):

    if old == 0:
        return 0.0

    return (
        (new - old)
        / old
        * 100.0
    )


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
# STRUCTURE
# ============================================================

def higher_high(candles):

    if len(candles) < 12:
        return False

    recent = candles[-6:]

    previous = candles[
        -12:-6
    ]

    recent_high = max(
        candle["high"]
        for candle in recent
    )

    previous_high = max(
        candle["high"]
        for candle in previous
    )

    return (
        recent_high
        > previous_high
    )


def higher_low(candles):

    if len(candles) < 12:
        return False

    recent = candles[-6:]

    previous = candles[
        -12:-6
    ]

    recent_low = min(
        candle["low"]
        for candle in recent
    )

    previous_low = min(
        candle["low"]
        for candle in previous
    )

    return (
        recent_low
        > previous_low
    )


# ============================================================
# RESISTANCE
# ============================================================

def find_resistance(candles):

    if len(candles) < 25:
        return None

    previous = candles[
        -21:-1
    ]

    return max(
        candle["high"]
        for candle in previous
    )


# ============================================================
# BREAKOUT STATUS
# ============================================================

def breakout_status(
    price,
    resistance
):

    if resistance <= 0:

        return (
            "NONE",
            0.0
        )

    distance = pct_change(
        resistance,
        price
    )

    if (
        price > resistance
        and distance
        <= MAX_CONFIRMED_DISTANCE
    ):

        return (
            "CONFIRMED",
            distance
        )

    if (
        price < resistance
        and abs(distance)
        <= EARLY_RESISTANCE_DISTANCE
    ):

        return (
            "EARLY",
            distance
        )

    return (
        "NONE",
        distance
    )


# ============================================================
# RETEST
# ============================================================

def has_retest(
    candles,
    resistance
):

    if len(candles) < 5:
        return False

    tolerance = (
        resistance
        * RETEST_DISTANCE
        / 100.0
    )

    for candle in candles[-5:]:

        touched = (
            candle["low"]
            <= resistance
            + tolerance
        )

        held = (
            candle["close"]
            >= resistance
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

    previous = [

        candle["volume"]

        for candle in candles[-21:-1]

        if candle["volume"] > 0
    ]

    if not previous:
        return 1.0

    average_volume = (
        sum(previous)
        / len(previous)
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
        body
        / candle_range
    )

    close_position = (
        candle["close"]
        - candle["low"]
    ) / candle_range

    return (
        body_ratio >= 0.40
        and close_position >= 0.60
        and candle["close"]
        > candle["open"]
    )


# ============================================================
# ANALYZE
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

    price = current["close"]

    if price <= 0:
        return None

    move_5m = momentum(
        candles,
        1
    )

    move_15m = momentum(
        candles,
        3
    )

    move_1h = momentum(
        candles,
        12
    )

    if move_5m <= 0:
        return None

    if move_15m <= 0:
        return None

    if move_1h < -2.0:
        return None

    if move_5m > MAX_5M_MOVE:
        return None

    if move_15m > MAX_15M_MOVE:
        return None

    if move_1h > MAX_1H_MOVE:
        return None

    resistance = find_resistance(
        candles
    )

    if resistance is None:
        return None

    status, distance = (
        breakout_status(
            price,
            resistance
        )
    )

    if status == "NONE":
        return None

    hh = higher_high(
        candles
    )

    hl = higher_low(
        candles
    )

    retest = has_retest(
        candles,
        resistance
    )

    vol_ratio = volume_ratio(
        candles
    )

    score = 0

    reasons = []

    # 5M
    score += 1

    reasons.append(
        "5M UP"
    )

    if move_5m >= 0.25:

        score += 1

        reasons.append(
            "5M MOMENTUM"
        )

    # 15M
    score += 1

    reasons.append(
        "15M UP"
    )

    if move_15m >= 0.40:

        score += 1

        reasons.append(
            "15M MOMENTUM"
        )

    # 1H
    score += 1

    if move_1h > 0:

        reasons.append(
            "1H UP"
        )

    else:

        reasons.append(
            "1H RECOVERY"
        )

    if move_1h >= 0.75:

        score += 1

        reasons.append(
            "1H STRONG"
        )

    # HIGHER HIGH
    if hh:

        score += 2

        reasons.append(
            "HIGHER HIGH"
        )

    # HIGHER LOW
    if hl:

        score += 2

        reasons.append(
            "HIGHER LOW"
        )

    # BREAKOUT
    if status == "CONFIRMED":

        score += 3

        reasons.append(
            "BREAKOUT CONFIRMED"
        )

    elif status == "EARLY":

        score += 2

        reasons.append(
            "EARLY BREAKOUT"
        )

    # RETEST
    if retest:

        score += 2

        reasons.append(
            "RETEST CONFIRMED"
        )

    elif status == "EARLY":

        score += 1

        reasons.append(
            "RETEST PENDING"
        )

    # DISTANCE
    abs_distance = abs(
        distance
    )

    if abs_distance <= 0.40:

        score += 2

        reasons.append(
            "VERY CLOSE"
        )

    elif abs_distance <= 0.80:

        score += 1

        reasons.append(
            "GOOD ENTRY DISTANCE"
        )

    # VOLUME
    if vol_ratio >= 1.30:

        score += 1

        reasons.append(
            "VOLUME"
        )

    # CANDLE
    if strong_candle(
        current
    ):

        score += 1

        reasons.append(
            "STRONG CANDLE"
        )

    # ========================================================
    # SIGNAL TYPE
    # ========================================================

    signal_type = None

    if (
        status == "CONFIRMED"
        and score
        >= CONFIRMED_BUY_MIN_SCORE
    ):

        signal_type = (
            "CONFIRMED BUY"
        )

    elif (
        status == "EARLY"
        and score
        >= EARLY_BUY_MIN_SCORE
        and hh
        and hl
    ):

        signal_type = (
            "EARLY BUY"
        )

    elif (
        score
        >= WATCH_MIN_SCORE
    ):

        signal_type = "WATCH"

    if signal_type is None:
        return None

    # ========================================================
    # RISK
    # ========================================================

    sl = price * 0.955

    tp1 = price * 1.085

    tp2 = price * 1.12

    return {

        "symbol": symbol,

        "price": price,

        "score": score,

        "signal_type":
            signal_type,

        "move_5m":
            move_5m,

        "move_15m":
            move_15m,

        "move_1h":
            move_1h,

        "resistance":
            resistance,

        "distance":
            distance,

        "retest":
            retest,

        "volume_ratio":
            vol_ratio,

        "sl": sl,

        "tp1": tp1,

        "tp2": tp2,

        "reasons":
            reasons,
    }


# ============================================================
# FORMAT PRICE
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
# FORMAT SIGNAL
# ============================================================

def format_signal(item):

    signal_type = item[
        "signal_type"
    ]

    if signal_type == (
        "CONFIRMED BUY"
    ):

        emoji = "🟢"

    elif signal_type == (
        "EARLY BUY"
    ):

        emoji = "🟡"

    else:

        emoji = "🟠"

    retest_text = (
        "YES"
        if item["retest"]
        else "PENDING"
    )

    return "\n".join([

        f"{emoji} "
        f"{signal_type}",

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

        f"🚀 RESISTANCE: "
        f"{fmt_price(item['resistance'])}",

        f"📏 DISTANCE: "
        f"{item['distance']:+.2f}%",

        f"🔄 RETEST: "
        f"{retest_text}",

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

        "⚠️ SIGNAL ONLY "
        "— NO REAL ORDER",
    ])


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)

    print(
        f"ATI CRYPTO BOT {VERSION}"
    )

    print(
        "EARLY ENTRY + CONFIRMED BREAKOUT"
    )

    print(
        "AUTO 5 MINUTE SCANNER"
    )

    print("=" * 60)

    # ========================================================
    # TELEGRAM TEST
    # ========================================================

    print(
        "SENDING TELEGRAM STARTUP TEST..."
    )

    telegram_ok = (
        telegram_startup_test()
    )

    if telegram_ok:

        print(
            "TELEGRAM STARTUP TEST OK"
        )

    else:

        print(
            "TELEGRAM STARTUP TEST FAILED"
        )

    # ========================================================
    # MARKETS
    # ========================================================

    markets = get_markets()

    if not markets:

        message = (

            f"⚠️ ATI BOT {VERSION}\n\n"

            "❌ TABDEAL MARKET DATA ERROR\n\n"

            "No USDT markets found.\n\n"

            f"🕐 {utc_now()}"

        )

        print(message)

        send_telegram(
            message
        )

        return

    print(
        f"USDT MARKETS: "
        f"{len(markets)}"
    )

    # ========================================================
    # SCAN
    # ========================================================

    results = []

    total = len(markets)

    scan_started = time.time()

    for index, symbol in enumerate(
        markets,
        1
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

        if index % 50 == 0:

            print(
                f"SCANNED "
                f"{index}/{total} | "
                f"CANDIDATES: "
                f"{len(results)}"
            )

    scan_seconds = (
        time.time()
        - scan_started
    )

    # ========================================================
    # SORT
    # ========================================================

    results.sort(

        key=lambda x: (

            x["score"],

            x["volume_ratio"],

            x["move_5m"],

            x["move_15m"],
        ),

        reverse=True,
    )

    # ========================================================
    # GROUPS
    # ========================================================

    confirmed = [

        item

        for item in results

        if item[
            "signal_type"
        ] == "CONFIRMED BUY"
    ]

    early = [

        item

        for item in results

        if item[
            "signal_type"
        ] == "EARLY BUY"
    ]

    watches = [

        item

        for item in results

        if item[
            "signal_type"
        ] == "WATCH"
    ]

    confirmed = confirmed[
        :TOP_RESULTS
    ]

    early = early[
        :TOP_RESULTS
    ]

    watches = watches[
        :TOP_RESULTS
    ]

    # ========================================================
    # MESSAGE
    # ========================================================

    now = utc_now()

    lines = [

        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}",

        "",

        "🚀 EARLY ENTRY "
        "SCANNER",

        "⚡ 5M + 15M + 1H",

        "⏱ AUTO RUN: 5 MIN",

        "",

        "📡 TABDEAL API: OK",

        f"📊 USDT MARKETS: "
        f"{len(markets)}",

        f"⏱ SCAN TIME: "
        f"{scan_seconds:.1f}s",

        "",

        f"🟢 CONFIRMED BUY: "
        f"{len(confirmed)}",

        f"🟡 EARLY BUY: "
        f"{len(early)}",

        f"🟠 WATCH: "
        f"{len(watches)}",

        "",
        "━━━━━━━━━━━━━━━━━━",
        "🟢 CONFIRMED BUY",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if confirmed:

        for index, item in enumerate(
            confirmed,
            1
        ):

            lines.extend([

                "",

                f"#{index}",

                format_signal(
                    item
                ),
            ])

    else:

        lines.extend([

            "",

            "❌ NO CONFIRMED BUY",
        ])

    lines.extend([

        "",
        "━━━━━━━━━━━━━━━━━━",
        "🟡 EARLY BUY",
        "━━━━━━━━━━━━━━━━━━",
    ])

    if early:

        for index, item in enumerate(
            early,
            1
        ):

            lines.extend([

                "",
                f"#{index}",
                format_signal(
                    item
                ),
            ])

    else:

        lines.extend([

            "",
            "❌ NO EARLY BUY",
        ])

    lines.extend([

        "",
        "━━━━━━━━━━━━━━━━━━",
        "🟠 WATCH",
        "━━━━━━━━━━━━━━━━━━",
    ])

    if watches:

        for index, item in enumerate(
            watches,
            1
        ):

            lines.extend([

                "",
                f"#{index}",
                format_signal(
                    item
                ),
            ])

    else:

        lines.extend([

            "",
            "❌ NO WATCH",
        ])

    lines.extend([

        "",
        "━━━━━━━━━━━━━━━━━━",

        f"📊 TOTAL CANDIDATES: "
        f"{len(results)}",

        f"🟢 CONFIRMED: "
        f"{len(confirmed)}",

        f"🟡 EARLY: "
        f"{len(early)}",

        f"🟠 WATCH: "
        f"{len(watches)}",

        f"🕐 {now}",

        "━━━━━━━━━━━━━━━━━━",

        "",

        "🔒 REAL ORDER: DISABLED",

        "📡 SCANNER MODE ONLY",

        "⏱ NEXT AUTO RUN: ~5 MIN",

    ])

    final_message = "\n".join(
        lines
    )

    print()
    print(final_message)

    # ========================================================
    # FINAL TELEGRAM
    # ========================================================

    if send_telegram(
        final_message
    ):

        print(
            "FINAL TELEGRAM MESSAGE SENT"
        )

    else:

        print(
            "FINAL TELEGRAM MESSAGE FAILED"
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
