import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.3
# DATA + MINIMUM CANDLE SAFETY
# ============================================================

VERSION = "V40.2.3"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

MAX_MARKETS = 529
MAX_WORKERS = 6

TRADE_LIMIT = 1000
REQUEST_TIMEOUT = 15

SCAN_INTERVAL_SECONDS = 300
REQUEST_DELAY = 0.08
MAX_RETRIES = 4

TOP_RESULTS = 15

# ------------------------------------------------------------
# DATA SAFETY
# ------------------------------------------------------------

RECENT_MINUTES = 30
MIN_CANDLES_FOR_SIGNAL = 12

# ------------------------------------------------------------
# SIGNAL
# ------------------------------------------------------------

BREAKOUT_LOOKBACK = 12

MIN_5M_CHANGE = 0.15
MAX_5M_CHANGE = 7.0

MIN_BUY_PRESSURE = 58.0
MIN_CANDLE_POSITION = 0.65

CONFIRMED_SCORE = 8
EARLY_SCORE = 7

SL_PERCENT = 0.60
TP1_PERCENT = 1.00
TP2_PERCENT = 1.60

REAL_ORDERS = False


# ============================================================
# TELEGRAM ENV
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT/40.2.3",
    "Accept": "application/json",
})


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_string():
    return utc_now().strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# HELPERS
# ============================================================

def safe_float(value, default=0.0):

    try:
        if value is None:
            return default

        return float(value)

    except Exception:
        return default


def normalize_symbol(symbol):

    if not symbol:
        return ""

    return (
        str(symbol)
        .upper()
        .replace("-", "")
        .replace("_", "")
        .replace("/", "")
        .replace(" ", "")
    )


def sleep_small():
    time.sleep(REQUEST_DELAY)


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
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
            timeout=15,
        )

        return response.ok

    except Exception:
        return False


def send_long_telegram(message):

    max_length = 3900

    if len(message) <= max_length:

        send_telegram(message)

        return

    while message:

        part = message[:max_length]

        message = message[max_length:]

        send_telegram(part)

        time.sleep(0.5)


# ============================================================
# HTTP ENGINE
# ============================================================

def get_json(path, params=None):

    url = BASE_URL + path

    last_error = ""

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

        try:

            sleep_small()

            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            status = response.status_code

            # Rate limit
            if status == 429:

                wait_time = min(
                    5 * attempt,
                    20
                )

                time.sleep(wait_time)

                continue

            # Server error
            if status >= 500:

                last_error = (
                    f"HTTP {status}"
                )

                time.sleep(
                    min(2 * attempt, 8)
                )

                continue

            response.raise_for_status()

            return response.json(), ""

        except Exception as exc:

            last_error = str(exc)

            if attempt < MAX_RETRIES:

                time.sleep(
                    min(2 * attempt, 8)
                )

    return None, last_error


# ============================================================
# EXCHANGE INFO
# ============================================================

def extract_exchange_symbols(data):

    results = []

    def walk(obj):

        if isinstance(obj, list):

            for item in obj:
                walk(item)

            return

        if not isinstance(obj, dict):
            return

        for key in (
            "symbol",
            "pair",
            "market",
            "instrument",
            "code",
            "name",
        ):

            value = obj.get(key)

            if isinstance(value, str):

                symbol = normalize_symbol(
                    value
                )

                if symbol.endswith("USDT"):
                    results.append(symbol)

        for key in (
            "symbols",
            "data",
            "result",
            "markets",
            "instruments",
            "rows",
            "items",
        ):

            value = obj.get(key)

            if isinstance(
                value,
                (list, dict)
            ):
                walk(value)

    walk(data)

    unique = []

    seen = set()

    for symbol in results:

        if symbol not in seen:

            seen.add(symbol)

            unique.append(symbol)

    return unique


def get_usdt_markets():

    data, error = get_json(
        "/r/api/v1/exchangeInfo"
    )

    if data is None:

        return [], (
            "EXCHANGE INFO ERROR: "
            + error
        )

    symbols = extract_exchange_symbols(
        data
    )

    symbols = [
        s for s in symbols
        if s.endswith("USDT")
    ]

    symbols = list(
        dict.fromkeys(symbols)
    )

    if MAX_MARKETS > 0:

        symbols = symbols[:MAX_MARKETS]

    return symbols, ""


# ============================================================
# TRADE EXTRACTION
# ============================================================

def extract_trade_list(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "data",
            "result",
            "trades",
            "rows",
            "items",
        ):

            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


# ============================================================
# TIMESTAMP
# ============================================================

def normalize_timestamp(value):

    try:
        ts = float(value)

    except Exception:
        return None

    if ts <= 0:
        return None

    # Seconds -> milliseconds
    if ts < 10_000_000_000:

        ts *= 1000

    # Microseconds -> milliseconds
    elif ts > 10_000_000_000_000:

        ts /= 1000

    # Extra protection for nanoseconds
    if ts > 10_000_000_000_000:

        ts /= 1000

    return int(ts)


# ============================================================
# NORMALIZE TRADE
# ============================================================

def normalize_trade(item):

    if not isinstance(item, dict):
        return None

    price = safe_float(
        item.get(
            "price",
            item.get("p")
        )
    )

    qty = safe_float(
        item.get(
            "qty",
            item.get(
                "quantity",
                item.get("q", 0)
            )
        )
    )

    if price <= 0 or qty <= 0:
        return None

    timestamp_value = item.get(
        "time"
    )

    if timestamp_value is None:

        timestamp_value = item.get(
            "timestamp",
            item.get(
                "transactTime",
                item.get("T")
            )
        )

    timestamp = normalize_timestamp(
        timestamp_value
    )

    if timestamp is None:
        return None

    maker = item.get(
        "isBuyerMaker",
        item.get(
            "buyerMaker",
            item.get("m", False)
        )
    )

    if isinstance(maker, str):

        maker = (
            maker.lower() == "true"
        )

    return {
        "price": price,
        "qty": qty,
        "time": timestamp,
        "isBuyerMaker": bool(maker),
    }


# ============================================================
# GET TRADES
# ============================================================

def get_symbol_trades(symbol):

    data, error = get_json(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    )

    trades = extract_trade_list(
        data
    )

    normalized = []

    for item in trades:

        trade = normalize_trade(item)

        if trade:
            normalized.append(trade)

    if normalized:

        return (
            symbol,
            normalized,
            ""
        )

    # --------------------------------------------------------
    # FALLBACK
    # --------------------------------------------------------

    tabdeal_symbol = symbol

    if symbol.endswith("USDT"):

        tabdeal_symbol = (
            symbol[:-4]
            + "_USDT"
        )

    data2, error2 = get_json(
        "/r/api/v1/trades",
        params={
            "tabdealSymbol":
                tabdeal_symbol,
            "limit":
                TRADE_LIMIT,
        },
    )

    trades2 = extract_trade_list(
        data2
    )

    normalized2 = []

    for item in trades2:

        trade = normalize_trade(item)

        if trade:

            normalized2.append(
                trade
            )

    if normalized2:

        return (
            symbol,
            normalized2,
            ""
        )

    return (
        symbol,
        [],
        error2 or error
    )


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    if not trades:
        return []

    now_ms = int(
        time.time() * 1000
    )

    cutoff_ms = (
        now_ms
        - RECENT_MINUTES
        * 60
        * 1000
    )

    recent = [
        t for t in trades
        if t["time"] >= cutoff_ms
    ]

    # --------------------------------------------------------
    # FALLBACK TO LATEST VALID TRADES
    # --------------------------------------------------------

    if len(recent) < 5:

        recent = sorted(
            trades,
            key=lambda x:
            x["time"]
        )[-500:]

    if not recent:
        return []

    buckets = {}

    five_minutes_ms = (
        5 * 60 * 1000
    )

    for trade in recent:

        bucket = (
            trade["time"]
            // five_minutes_ms
        ) * five_minutes_ms

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
                "buy_volume": 0.0,
                "sell_volume": 0.0,
                "trades": 0,
            }

        candle = buckets[bucket]

        price = trade["price"]
        qty = trade["qty"]

        candle["high"] = max(
            candle["high"],
            price
        )

        candle["low"] = min(
            candle["low"],
            price
        )

        candle["close"] = price

        candle["volume"] += qty

        candle["trades"] += 1

        if trade["isBuyerMaker"]:

            candle[
                "sell_volume"
            ] += qty

        else:

            candle[
                "buy_volume"
            ] += qty

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x:
        x["time"]
    )

    return candles


# ============================================================
# BUY PRESSURE
# ============================================================

def calculate_buy_pressure(
    candle
):

    buy = candle[
        "buy_volume"
    ]

    sell = candle[
        "sell_volume"
    ]

    total = buy + sell

    if total <= 0:
        return 50.0

    return (
        buy / total
    ) * 100.0


# ============================================================
# ANALYZE MARKET
# ============================================================

def analyze_market(
    symbol,
    trades
):

    candles = build_5m_candles(
        trades
    )

    # --------------------------------------------------------
    # HARD DATA FILTER
    # --------------------------------------------------------

    if len(candles) < MIN_CANDLES_FOR_SIGNAL:

        return {
            "symbol": symbol,
            "signal": "INSUFFICIENT DATA",
            "score": 0,
            "price": 0,
            "change_5m": 0,
            "buy_pressure": 0,
            "candle_position": 0,
            "breakout": False,
            "candles": len(candles),
            "trades": len(trades),
            "sl": 0,
            "tp1": 0,
            "tp2": 0,
        }

    current = candles[-1]

    previous = candles[-2]

    close = current["close"]

    open_price = current["open"]

    high = current["high"]

    low = current["low"]

    if close <= 0:
        return None

    previous_close = (
        previous["close"]
    )

    if previous_close <= 0:
        return None

    change_5m = (
        (
            close
            - previous_close
        )
        / previous_close
    ) * 100.0

    candle_range = (
        high - low
    )

    if candle_range <= 0:

        candle_position = 0.5

    else:

        candle_position = (
            (close - low)
            / candle_range
        )

    buy_pressure = (
        calculate_buy_pressure(
            current
        )
    )

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    lookback = candles[
        -BREAKOUT_LOOKBACK - 1:
        -1
    ]

    if len(lookback) >= (
        BREAKOUT_LOOKBACK
    ):

        previous_high = max(
            c["high"]
            for c in lookback
        )

        breakout = (
            close > previous_high
        )

    else:

        breakout = False

    # --------------------------------------------------------
    # CONDITIONS
    # --------------------------------------------------------

    momentum_positive = (
        change_5m
        >= MIN_5M_CHANGE
    )

    momentum_not_chasing = (
        change_5m
        <= MAX_5M_CHANGE
    )

    strong_close = (
        candle_position
        >= MIN_CANDLE_POSITION
    )

    pressure_ok = (
        buy_pressure
        >= MIN_BUY_PRESSURE
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    if breakout:
        score += 3

    if momentum_positive:
        score += 2

    if pressure_ok:
        score += 1

    if strong_close:
        score += 1

    if momentum_not_chasing:
        score += 1

    if close > open_price:
        score += 1

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    confirmed = (
        breakout
        and momentum_positive
        and momentum_not_chasing
        and pressure_ok
        and strong_close
        and score >= CONFIRMED_SCORE
    )

    early = (
        breakout
        and momentum_not_chasing
        and pressure_ok
        and score >= EARLY_SCORE
        and not confirmed
    )

    watch = (
        (
            breakout
            or momentum_positive
            or pressure_ok
        )
        and score >= 5
        and not confirmed
        and not early
    )

    signal = "NONE"

    if confirmed:

        signal = "CONFIRMED BUY"

    elif early:

        signal = "EARLY ENTRY"

    elif watch:

        signal = "WATCH"

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    sl = (
        close
        * (
            1
            - SL_PERCENT / 100
        )
    )

    tp1 = (
        close
        * (
            1
            + TP1_PERCENT / 100
        )
    )

    tp2 = (
        close
        * (
            1
            + TP2_PERCENT / 100
        )
    )

    return {
        "symbol": symbol,
        "signal": signal,
        "score": score,
        "price": close,
        "change_5m": change_5m,
        "buy_pressure": buy_pressure,
        "candle_position": candle_position,
        "breakout": breakout,
        "candles": len(candles),
        "trades": len(trades),
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


# ============================================================
# FORMAT RESULT
# ============================================================

def format_result(item):

    return (
        f"🟢 {item['symbol']}\n"
        f"💰 PRICE: "
        f"{item['price']:.8g}\n"
        f"📈 5m: "
        f"{item['change_5m']:+.2f}%\n"
        f"🎯 SCORE: "
        f"{item['score']}\n"
        f"💚 BUY PRESSURE: "
        f"{item['buy_pressure']:.0f}%\n"
        f"🚀 BREAKOUT: "
        f"{'YES' if item['breakout'] else 'NO'}\n"
        f"🕯 CANDLES: "
        f"{item['candles']}\n"
        f"🛡 SL: "
        f"{item['sl']:.8g}\n"
        f"🎯 TP1: "
        f"{item['tp1']:.8g}\n"
        f"🎯 TP2: "
        f"{item['tp2']:.8g}"
    )


# ============================================================
# STATS
# ============================================================

LAST_STATS = {
    "markets": 0,
    "requested": 0,
    "responses": 0,
    "valid_trades": 0,
    "data_markets": 0,
    "insufficient": 0,
    "candles": 0,
}


# ============================================================
# SCAN
# ============================================================

def run_scan():

    global LAST_STATS

    markets, error = (
        get_usdt_markets()
    )

    if not markets:

        send_telegram(
            f"⚠️ ATI BOT {VERSION}\n\n"
            f"❌ NO USDT MARKETS FOUND\n\n"
            f"{error}\n\n"
            f"🔄 RETRY NEXT SCAN\n"
            f"🕐 {utc_string()}"
        )

        return

    LAST_STATS = {
        "markets": len(markets),
        "requested": len(markets),
        "responses": 0,
        "valid_trades": 0,
        "data_markets": 0,
        "insufficient": 0,
        "candles": 0,
    }

    results = []

    # --------------------------------------------------------
    # PARALLEL REQUESTS
    # --------------------------------------------------------

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                get_symbol_trades,
                symbol
            ): symbol
            for symbol in markets
        }

        for future in as_completed(
            futures
        ):

            try:

                symbol, trades, error = (
                    future.result()
                )

                if not trades:
                    continue

                LAST_STATS[
                    "responses"
                ] += 1

                LAST_STATS[
                    "valid_trades"
                ] += len(trades)

                analysis = analyze_market(
                    symbol,
                    trades
                )

                if not analysis:
                    continue

                if (
                    analysis["signal"]
                    == "INSUFFICIENT DATA"
                ):

                    LAST_STATS[
                        "insufficient"
                    ] += 1

                    continue

                LAST_STATS[
                    "data_markets"
                ] += 1

                LAST_STATS[
                    "candles"
                ] += analysis[
                    "candles"
                ]

                if (
                    analysis["signal"]
                    != "NONE"
                ):

                    results.append(
                        analysis
                    )

            except Exception:

                continue

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    confirmed = sorted(
        [
            x for x in results
            if x["signal"]
            == "CONFIRMED BUY"
        ],
        key=lambda x: (
            x["score"],
            x["change_5m"],
            x["buy_pressure"],
        ),
        reverse=True,
    )

    early = sorted(
        [
            x for x in results
            if x["signal"]
            == "EARLY ENTRY"
        ],
        key=lambda x: (
            x["score"],
            x["change_5m"],
            x["buy_pressure"],
        ),
        reverse=True,
    )

    watch = sorted(
        [
            x for x in results
            if x["signal"]
            == "WATCH"
        ],
        key=lambda x: (
            x["score"],
            x["change_5m"],
            x["buy_pressure"],
        ),
        reverse=True,
    )

    confirmed = confirmed[
        :TOP_RESULTS
    ]

    early = early[
        :TOP_RESULTS
    ]

    watch = watch[
        :TOP_RESULTS
    ]

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    lines = [
        f"⚡ ATI CRYPTO BOT {VERSION}",
        "",
        "🚀 CLEAN DATA + SIGNAL SCANNER",
        "",
        "📡 TABDEAL API: OK",
        f"📊 USDT MARKETS: "
        f"{len(markets)}",
        f"📥 REQUESTED: "
        f"{LAST_STATS['requested']}",
        f"📡 RESPONSES: "
        f"{LAST_STATS['responses']}",
        f"📦 VALID TRADES: "
        f"{LAST_STATS['valid_trades']}",
        f"📊 MARKETS WITH DATA: "
        f"{LAST_STATS['data_markets']}",
        f"⚠️ INSUFFICIENT DATA: "
        f"{LAST_STATS['insufficient']}",
        f"🕯 TOTAL CANDLES: "
        f"{LAST_STATS['candles']}",
        "",
        "🛡 MINIMUM CANDLES: 12",
        "⏱ TIMEFRAME: 5m",
        "💓 HEARTBEAT: ON",
        "🔧 REAL ORDERS: DISABLED",
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🟢 CONFIRMED BUY",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if confirmed:

        for item in confirmed:

            lines.append(
                format_result(item)
            )

            lines.append("")

    else:

        lines.append("NONE\n")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        "⚡ EARLY ENTRY",
        "━━━━━━━━━━━━━━━━━━",
    ])

    if early:

        for item in early:

            lines.append(
                format_result(item)
            )

            lines.append("")

    else:

        lines.append("NONE\n")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        "🟡 WATCH",
        "━━━━━━━━━━━━━━━━━━",
    ])

    if watch:

        for item in watch:

            lines.append(
                format_result(item)
            )

            lines.append("")

    else:

        lines.append("NONE\n")

    lines.extend([
        "━━━━━━━━━━━━━━━━━━",
        f"🕐 {utc_string()}",
    ])

    send_long_telegram(
        "\n".join(lines)
    )


# ============================================================
# HEARTBEAT
# ============================================================

def send_heartbeat():

    stats = LAST_STATS

    message = (
        f"💓 ATI BOT HEARTBEAT\n\n"
        f"⚡ VERSION: {VERSION}\n"
        f"📡 STATUS: ALIVE\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"📊 MARKETS: "
        f"{stats['markets']}\n"
        f"📥 REQUESTED: "
        f"{stats['requested']}\n"
        f"📡 RESPONSES: "
        f"{stats['responses']}\n"
        f"📦 VALID TRADES: "
        f"{stats['valid_trades']}\n"
        f"📊 DATA: "
        f"{stats['data_markets']}\n"
        f"⚠️ INSUFFICIENT: "
        f"{stats['insufficient']}\n"
        f"🕯 CANDLES: "
        f"{stats['candles']}\n"
        f"🔧 REAL ORDERS: DISABLED\n\n"
        f"🔄 NEXT SCAN: ABOUT 5 MINUTES\n"
        f"🕐 {utc_string()}"
    )

    send_telegram(message)


# ============================================================
# STARTUP
# ============================================================

def send_startup():

    message = (
        f"🟢 ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED/RECENT 5M DATA: YES\n"
        f"🛡 MINIMUM CANDLES: 12\n"
        f"💓 HEARTBEAT: ON\n"
        f"🔧 REAL ORDERS: DISABLED\n\n"
        f"🔄 CONTINUOUS MODE: ON\n"
        f"🕐 {utc_string()}"
    )

    send_telegram(message)


# ============================================================
# CONTINUOUS LOOP
# ============================================================

def run_forever():

    send_startup()

    while True:

        cycle_start = time.time()

        try:

            run_scan()

        except Exception as exc:

            send_telegram(
                f"⚠️ ATI BOT {VERSION}\n\n"
                f"❌ SCAN ERROR\n"
                f"{str(exc)[:1000]}\n\n"
                f"🔄 BOT WILL CONTINUE\n"
                f"🕐 {utc_string()}"
            )

        send_heartbeat()

        elapsed = (
            time.time()
            - cycle_start
        )

        wait_seconds = max(
            10,
            SCAN_INTERVAL_SECONDS
            - int(elapsed)
        )

        time.sleep(
            wait_seconds
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    run_forever()
