import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.4
# ROOT SIGNAL ENGINE
#
# ROOT FIXES:
# - Robust Tabdeal exchangeInfo parsing
# - Robust trade parsing
# - Correct buy/sell pressure calculation
# - No fake 0% / 100% pressure when direction is unknown
# - Minimum candle protection
# - Real breakout confirmation
# - Breakout + pressure confirmation
# - Clean BUY / WATCH separation
# - Continuous 5m scanner
# - Telegram heartbeat
# - REAL ORDERS DISABLED
# ============================================================

VERSION = "V40.2.4"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

TRADE_LIMIT = 1000
MAX_MARKETS = 529
MAX_WORKERS = 6

REQUEST_TIMEOUT = 15
MAX_RETRIES = 4
REQUEST_DELAY = 0.08

SCAN_INTERVAL_SECONDS = 300

MIN_CANDLES_FOR_SIGNAL = 12

# ------------------------------------------------------------
# SIGNAL SETTINGS
# ------------------------------------------------------------

MIN_5M_CHANGE = 0.15
MAX_5M_CHANGE = 7.0

MIN_BUY_PRESSURE = 58.0
STRONG_BUY_PRESSURE = 65.0

CONFIRMED_SCORE = 8
EARLY_SCORE = 7

BREAKOUT_LOOKBACK = 12

MIN_BODY_RATIO = 0.35
MIN_CANDLE_POSITION = 0.65

SL_PERCENT = 0.60
TP1_PERCENT = 1.00
TP2_PERCENT = 1.60

# Do not chase extremely extended candles
MAX_CANDLE_EXTENSION = 2.50

# Number of recent trades used for pressure
PRESSURE_TRADES = 80

# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Explicitly disabled for this version
REAL_ORDERS = False

# ------------------------------------------------------------
# SESSION STATS
# ------------------------------------------------------------

LAST_STATS = {
    "requested": 0,
    "responses": 0,
    "valid_trades": 0,
    "markets_with_data": 0,
    "insufficient": 0,
    "candles": 0,
    "confirmed": 0,
    "early": 0,
    "watch": 0,
    "rejected": 0,
}


# ============================================================
# BASIC HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def now_text():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def normalize_symbol(value):
    if value is None:
        return ""

    s = str(value).upper().strip()

    for char in ["-", "_", "/", ":", " "]:
        s = s.replace(char, "")

    return s


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM CONFIG MISSING")
        print(message)
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if r.ok:
            return True

        print("Telegram error:", r.status_code, r.text[:300])
        return False

    except Exception as e:
        print("Telegram exception:", e)
        return False


# ============================================================
# HTTP
# ============================================================

def get_json(path, params=None):
    url = BASE_URL + path

    for attempt in range(1, MAX_RETRIES + 1):

        try:
            response = requests.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT,
            )

            if response.status_code == 200:
                try:
                    return response.json()
                except Exception:
                    return None

            if response.status_code in (429, 500, 502, 503, 504):
                wait = min(2 * attempt, 8)
                time.sleep(wait)
                continue

            print(
                f"API ERROR {response.status_code}: "
                f"{response.text[:200]}"
            )

            return None

        except requests.RequestException as e:

            if attempt >= MAX_RETRIES:
                print("REQUEST ERROR:", e)
                return None

            time.sleep(min(2 * attempt, 8))

        except Exception as e:
            print("JSON ERROR:", e)
            return None

    return None


# ============================================================
# EXCHANGE INFO
# ============================================================

def find_symbol_objects(obj):
    """
    Recursively find dictionaries that look like market objects.
    """

    found = []

    if isinstance(obj, dict):

        keys = {
            str(k).lower()
            for k in obj.keys()
        }

        possible_symbol_keys = {
            "symbol",
            "pair",
            "market",
            "instrument",
            "code",
            "name",
        }

        if keys.intersection(possible_symbol_keys):
            found.append(obj)

        for value in obj.values():
            found.extend(find_symbol_objects(value))

    elif isinstance(obj, list):

        for item in obj:
            found.extend(find_symbol_objects(item))

    return found


def extract_exchange_symbols(data):

    symbols = set()

    objects = find_symbol_objects(data)

    for item in objects:

        symbol = None

        for key in [
            "symbol",
            "pair",
            "market",
            "instrument",
            "code",
            "name",
        ]:
            if key in item:
                symbol = item.get(key)
                if symbol:
                    break

        normalized = normalize_symbol(symbol)

        if not normalized.endswith("USDT"):
            continue

        # ----------------------------------------------
        # Optional status validation
        # ----------------------------------------------

        status = ""

        for key in [
            "status",
            "state",
            "active",
            "enabled",
        ]:
            if key in item:
                status = str(item.get(key)).upper()
                break

        if status in {
            "",
            "TRADING",
            "ACTIVE",
            "ENABLED",
            "1",
            "TRUE",
        }:
            symbols.add(normalized)

    return sorted(symbols)


def get_usdt_markets():

    data = get_json(
        "/r/api/v1/exchangeInfo"
    )

    if data is None:
        return []

    symbols = extract_exchange_symbols(data)

    # Safety: don't scan unexpected huge number
    symbols = symbols[:MAX_MARKETS]

    return symbols


# ============================================================
# TRADE EXTRACTION
# ============================================================

def extract_trade_list(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    # Common containers
    for key in [
        "data",
        "result",
        "trades",
        "items",
        "rows",
        "list",
    ]:
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            for nested_key in [
                "data",
                "result",
                "trades",
                "items",
                "rows",
                "list",
            ]:
                nested = value.get(nested_key)

                if isinstance(nested, list):
                    return nested

    # Last fallback: search recursively
    def recursive_list(obj):

        if isinstance(obj, list):
            return obj

        if isinstance(obj, dict):
            for value in obj.values():
                result = recursive_list(value)

                if result:
                    return result

        return []

    return recursive_list(data)


def normalize_timestamp(value):

    if value is None:
        return None

    try:
        ts = float(value)
    except Exception:
        return None

    # seconds
    if ts < 10_000_000_000:
        return ts

    # milliseconds
    if ts < 10_000_000_000_000:
        return ts / 1000.0

    # microseconds
    if ts < 10_000_000_000_000_000:
        return ts / 1_000_000.0

    # nanoseconds
    return ts / 1_000_000_000.0


def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = None
    qty = None
    timestamp = None
    buyer_maker = None

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    for key in [
        "price",
        "p",
        "rate",
        "px",
    ]:
        if key in item:
            price = safe_float(item.get(key))
            if price is not None:
                break

    # --------------------------------------------------------
    # QUANTITY
    # --------------------------------------------------------

    for key in [
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
    ]:
        if key in item:
            qty = safe_float(item.get(key))
            if qty is not None:
                break

    # --------------------------------------------------------
    # TIME
    # --------------------------------------------------------

    for key in [
        "time",
        "timestamp",
        "transactTime",
        "T",
        "ts",
        "createdAt",
    ]:
        if key in item:
            timestamp = normalize_timestamp(
                item.get(key)
            )

            if timestamp is not None:
                break

    # --------------------------------------------------------
    # BUYER MAKER
    #
    # IMPORTANT:
    #
    # isBuyerMaker = True
    # means buyer was maker
    # therefore aggressive side is SELL.
    #
    # isBuyerMaker = False
    # means aggressive side is BUY.
    # --------------------------------------------------------

    for key in [
        "isBuyerMaker",
        "buyerMaker",
        "m",
        "is_buyer_maker",
    ]:
        if key in item:

            value = item.get(key)

            if isinstance(value, bool):
                buyer_maker = value
                break

            if isinstance(value, int):
                buyer_maker = bool(value)
                break

            if isinstance(value, str):

                v = value.strip().lower()

                if v in {
                    "true",
                    "1",
                    "yes",
                }:
                    buyer_maker = True
                    break

                if v in {
                    "false",
                    "0",
                    "no",
                }:
                    buyer_maker = False
                    break

    if price is None or qty is None:
        return None

    if price <= 0 or qty <= 0:
        return None

    return {
        "price": price,
        "qty": qty,
        "timestamp": timestamp,
        "buyer_maker": buyer_maker,
    }


# ============================================================
# MARKET TRADES
# ============================================================

def get_symbol_trades(symbol):

    LAST_STATS["requested"] += 1

    data = get_json(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    )

    trades_raw = extract_trade_list(data)

    # --------------------------------------------------------
    # Fallback symbol format
    # --------------------------------------------------------

    if not trades_raw:

        fallback_symbol = (
            symbol[:-4] + "_USDT"
            if symbol.endswith("USDT")
            else symbol
        )

        data = get_json(
            "/r/api/v1/trades",
            {
                "tabdealSymbol": fallback_symbol,
                "limit": TRADE_LIMIT,
            },
        )

        trades_raw = extract_trade_list(data)

    if not trades_raw:
        return []

    LAST_STATS["responses"] += 1

    parsed = []

    for item in trades_raw:

        trade = parse_trade(item)

        if trade is not None:
            parsed.append(trade)

    LAST_STATS["valid_trades"] += len(parsed)

    return parsed


# ============================================================
# CANDLE BUILDER
# ============================================================

def candle_bucket(timestamp):

    if timestamp is None:
        return None

    return int(timestamp // 300) * 300


def build_candles(trades):

    if not trades:
        return []

    # Need timestamp
    timed = [
        t for t in trades
        if t.get("timestamp") is not None
    ]

    if not timed:
        return []

    timed.sort(
        key=lambda x: x["timestamp"]
    )

    buckets = {}

    for trade in timed:

        bucket = candle_bucket(
            trade["timestamp"]
        )

        if bucket is None:
            continue

        price = trade["price"]
        qty = trade["qty"]

        if bucket not in buckets:

            buckets[bucket] = {
                "timestamp": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }

        else:

            c = buckets[bucket]

            c["high"] = max(
                c["high"],
                price
            )

            c["low"] = min(
                c["low"],
                price
            )

            c["close"] = price
            c["volume"] += qty

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["timestamp"]
    )

    return candles


# ============================================================
# PRESSURE ENGINE
# ============================================================

def calculate_buy_pressure(trades):

    """
    ROOT FIX:

    Never return fake 0% or 100% when direction
    information is unavailable.

    Uses recent valid trades.

    Buy:
        buyer_maker == False

    Sell:
        buyer_maker == True

    Unknown:
        ignored
    """

    if not trades:
        return None

    recent = [
        t for t in trades
        if t.get("buyer_maker") is not None
    ]

    if len(recent) < 10:
        return None

    recent = recent[-PRESSURE_TRADES:]

    buy_volume = 0.0
    sell_volume = 0.0

    buy_count = 0
    sell_count = 0

    for trade in recent:

        value = (
            trade["price"] *
            trade["qty"]
        )

        if trade["buyer_maker"] is False:

            buy_volume += value
            buy_count += 1

        elif trade["buyer_maker"] is True:

            sell_volume += value
            sell_count += 1

    total_volume = (
        buy_volume +
        sell_volume
    )

    total_count = (
        buy_count +
        sell_count
    )

    if total_volume <= 0:
        return None

    if total_count < 10:
        return None

    pressure = (
        buy_volume /
        total_volume
    ) * 100.0

    return max(
        0.0,
        min(100.0, pressure)
    )


# ============================================================
# CANDLE QUALITY
# ============================================================

def candle_quality(candle):

    high = candle["high"]
    low = candle["low"]
    close = candle["close"]
    open_price = candle["open"]

    rng = high - low

    if rng <= 0:
        return 0.0

    body = abs(
        close - open_price
    )

    body_ratio = body / rng

    position = (
        close - low
    ) / rng

    return (
        body_ratio,
        position,
    )


# ============================================================
# BREAKOUT ENGINE
# ============================================================

def detect_breakout(candles):

    if len(candles) < BREAKOUT_LOOKBACK + 1:
        return False, None

    current = candles[-1]

    previous = candles[
        -BREAKOUT_LOOKBACK - 1:-1
    ]

    if not previous:
        return False, None

    previous_high = max(
        c["high"]
        for c in previous
    )

    current_close = current["close"]

    # Must actually close above previous structure
    breakout = (
        current_close >
        previous_high
    )

    return breakout, previous_high


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(symbol, trades):

    if not trades:
        return {
            "symbol": symbol,
            "status": "NO DATA",
        }

    candles = build_candles(trades)

    if len(candles) < MIN_CANDLES_FOR_SIGNAL:

        return {
            "symbol": symbol,
            "status": "INSUFFICIENT DATA",
            "candles": len(candles),
        }

    # --------------------------------------------------------
    # Current / previous candle
    # --------------------------------------------------------

    current = candles[-1]

    previous = candles[-2]

    price = current["close"]

    previous_close = previous["close"]

    if previous_close <= 0:
        return {
            "symbol": symbol,
            "status": "INVALID",
        }

    change_5m = (
        (price - previous_close)
        / previous_close
    ) * 100.0

    # --------------------------------------------------------
    # Pressure
    # --------------------------------------------------------

    pressure = calculate_buy_pressure(
        trades
    )

    # UNKNOWN PRESSURE = NO SIGNAL
    if pressure is None:

        return {
            "symbol": symbol,
            "status": "UNKNOWN PRESSURE",
            "candles": len(candles),
            "price": price,
            "change_5m": change_5m,
        }

    # --------------------------------------------------------
    # Candle quality
    # --------------------------------------------------------

    body_ratio, candle_position = (
        candle_quality(current)
    )

    # --------------------------------------------------------
    # Breakout
    # --------------------------------------------------------

    breakout, previous_high = (
        detect_breakout(candles)
    )

    # --------------------------------------------------------
    # Structure trend
    # --------------------------------------------------------

    recent_closes = [
        c["close"]
        for c in candles[-6:]
    ]

    rising_closes = 0

    for i in range(1, len(recent_closes)):

        if (
            recent_closes[i]
            >
            recent_closes[i - 1]
        ):
            rising_closes += 1

    rising_structure = (
        rising_closes >= 3
    )

    # --------------------------------------------------------
    # Extension protection
    # --------------------------------------------------------

    candle_extension = (
        abs(change_5m)
    )

    too_extended = (
        candle_extension >
        MAX_CANDLE_EXTENSION
    )

    # --------------------------------------------------------
    # Score
    # --------------------------------------------------------

    score = 0

    if change_5m >= MIN_5M_CHANGE:
        score += 2

    if change_5m <= MAX_5M_CHANGE:
        score += 1

    if pressure >= MIN_BUY_PRESSURE:
        score += 2

    if pressure >= STRONG_BUY_PRESSURE:
        score += 1

    if breakout:
        score += 2

    if candle_position >= MIN_CANDLE_POSITION:
        score += 1

    if body_ratio >= MIN_BODY_RATIO:
        score += 1

    if rising_structure:
        score += 1

    # --------------------------------------------------------
    # Hard rejection rules
    # --------------------------------------------------------

    rejected = False
    rejection_reason = ""

    if change_5m < MIN_5M_CHANGE:

        rejected = True
        rejection_reason = "5M TOO WEAK"

    elif change_5m > MAX_5M_CHANGE:

        rejected = True
        rejection_reason = "CHASE PROTECTION"

    elif pressure < MIN_BUY_PRESSURE:

        rejected = True
        rejection_reason = "LOW BUY PRESSURE"

    elif not breakout:

        rejected = True
        rejection_reason = "NO BREAKOUT"

    elif candle_position < MIN_CANDLE_POSITION:

        rejected = True
        rejection_reason = "WEAK CANDLE CLOSE"

    elif body_ratio < MIN_BODY_RATIO:

        rejected = True
        rejection_reason = "WEAK BODY"

    elif too_extended:

        rejected = True
        rejection_reason = "OVEREXTENDED"

    # --------------------------------------------------------
    # Final classification
    # --------------------------------------------------------

    status = "REJECTED"

    if not rejected:

        if score >= CONFIRMED_SCORE:
            status = "CONFIRMED BUY"

        elif score >= EARLY_SCORE:
            status = "EARLY BUY"

        else:
            status = "WATCH"

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    sl = price * (
        1 -
        SL_PERCENT / 100
    )

    tp1 = price * (
        1 +
        TP1_PERCENT / 100
    )

    tp2 = price * (
        1 +
        TP2_PERCENT / 100
    )

    return {
        "symbol": symbol,
        "status": status,
        "rejected": rejected,
        "reason": rejection_reason,
        "price": price,
        "change_5m": change_5m,
        "score": score,
        "buy_pressure": pressure,
        "breakout": breakout,
        "candles": len(candles),
        "body_ratio": body_ratio,
        "candle_position": candle_position,
        "rising_structure": rising_structure,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


# ============================================================
# MARKET WORKER
# ============================================================

def process_market(symbol):

    try:

        time.sleep(REQUEST_DELAY)

        trades = get_symbol_trades(
            symbol
        )

        if not trades:
            return None

        result = analyze_market(
            symbol,
            trades
        )

        return result

    except Exception as e:

        print(
            f"{symbol} ERROR: {e}"
        )

        return None


# ============================================================
# SCAN
# ============================================================

def run_scan():

    global LAST_STATS

    LAST_STATS = {
        "requested": 0,
        "responses": 0,
        "valid_trades": 0,
        "markets_with_data": 0,
        "insufficient": 0,
        "candles": 0,
        "confirmed": 0,
        "early": 0,
        "watch": 0,
        "rejected": 0,
    }

    markets = get_usdt_markets()

    if not markets:

        send_telegram(
            f"⚠️ ATI BOT {VERSION}\n\n"
            f"❌ NO USDT MARKETS FOUND\n"
            f"🕐 {now_text()}"
        )

        return

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                process_market,
                symbol
            ): symbol
            for symbol in markets
        }

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result is None:
                    continue

                status = result.get(
                    "status"
                )

                if status == "INSUFFICIENT DATA":

                    LAST_STATS[
                        "insufficient"
                    ] += 1

                    continue

                if status == "NO DATA":

                    continue

                if status == "UNKNOWN PRESSURE":

                    continue

                candles = result.get(
                    "candles",
                    0
                )

                if candles > 0:

                    LAST_STATS[
                        "markets_with_data"
                    ] += 1

                    LAST_STATS[
                        "candles"
                    ] += candles

                if status == "CONFIRMED BUY":

                    LAST_STATS[
                        "confirmed"
                    ] += 1

                    results.append(result)

                elif status == "EARLY BUY":

                    LAST_STATS[
                        "early"
                    ] += 1

                    results.append(result)

                elif status == "WATCH":

                    LAST_STATS[
                        "watch"
                    ] += 1

                    results.append(result)

                else:

                    LAST_STATS[
                        "rejected"
                    ] += 1

            except Exception as e:

                print(
                    "SCAN FUTURE ERROR:",
                    e
                )

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    priority = {
        "CONFIRMED BUY": 3,
        "EARLY BUY": 2,
        "WATCH": 1,
    }

    results.sort(
        key=lambda x: (
            priority.get(
                x["status"],
                0
            ),
            x.get(
                "score",
                0
            ),
            x.get(
                "buy_pressure",
                0
            ),
            x.get(
                "change_5m",
                0
            ),
        ),
        reverse=True,
    )

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    lines.append(
        "🧠 ROOT SIGNAL ENGINE"
    )

    lines.append("")

    lines.append(
        "📡 TABDEAL API: OK"
    )

    lines.append(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    lines.append(
        f"📡 REQUESTED: "
        f"{LAST_STATS['requested']}"
    )

    lines.append(
        f"📥 RESPONSES: "
        f"{LAST_STATS['responses']}"
    )

    lines.append(
        f"📊 VALID TRADES: "
        f"{LAST_STATS['valid_trades']}"
    )

    lines.append(
        f"📊 MARKETS WITH DATA: "
        f"{LAST_STATS['markets_with_data']}"
    )

    lines.append(
        f"⚠️ INSUFFICIENT DATA: "
        f"{LAST_STATS['insufficient']}"
    )

    lines.append(
        f"🕯 TOTAL CANDLES: "
        f"{LAST_STATS['candles']}"
    )

    lines.append(
        f"🛡 MIN CANDLES: "
        f"{MIN_CANDLES_FOR_SIGNAL}"
    )

    lines.append("")

    # --------------------------------------------------------
    # Confirmed
    # --------------------------------------------------------

    confirmed = [
        r for r in results
        if r["status"] == "CONFIRMED BUY"
    ]

    lines.append(
        "🟢 CONFIRMED BUY"
    )

    if not confirmed:

        lines.append("NONE")

    else:

        for r in confirmed[:10]:

            lines.append("")

            lines.append(
                f"🟢 {r['symbol']}"
            )

            lines.append(
                f"💰 PRICE: "
                f"{r['price']:.10g}"
            )

            lines.append(
                f"📈 5m: "
                f"{r['change_5m']:+.2f}%"
            )

            lines.append(
                f"🎯 SCORE: "
                f"{r['score']}/12"
            )

            lines.append(
                f"💚 BUY PRESSURE: "
                f"{r['buy_pressure']:.1f}%"
            )

            lines.append(
                "🚀 BREAKOUT: YES"
            )

            lines.append(
                f"🕯 CANDLES: "
                f"{r['candles']}"
            )

            lines.append(
                f"🛡 SL: "
                f"{r['sl']:.10g}"
            )

            lines.append(
                f"🎯 TP1: "
                f"{r['tp1']:.10g}"
            )

            lines.append(
                f"🎯 TP2: "
                f"{r['tp2']:.10g}"
            )

    # --------------------------------------------------------
    # Early
    # --------------------------------------------------------

    early = [
        r for r in results
        if r["status"] == "EARLY BUY"
    ]

    lines.append("")
    lines.append("⚡ EARLY BUY")

    if not early:

        lines.append("NONE")

    else:

        for r in early[:8]:

            lines.append("")

            lines.append(
                f"⚡ {r['symbol']}"
            )

            lines.append(
                f"💰 PRICE: "
                f"{r['price']:.10g}"
            )

            lines.append(
                f"📈 5m: "
                f"{r['change_5m']:+.2f}%"
            )

            lines.append(
                f"🎯 SCORE: "
                f"{r['score']}/12"
            )

            lines.append(
                f"💚 BUY PRESSURE: "
                f"{r['buy_pressure']:.1f}%"
            )

            lines.append(
                "🚀 BREAKOUT: YES"
            )

            lines.append(
                f"🕯 CANDLES: "
                f"{r['candles']}"
            )

            lines.append(
                f"🛡 SL: "
                f"{r['sl']:.10g}"
            )

            lines.append(
                f"🎯 TP1: "
                f"{r['tp1']:.10g}"
            )

            lines.append(
                f"🎯 TP2: "
                f"{r['tp2']:.10g}"
            )

    # --------------------------------------------------------
    # Watch
    # --------------------------------------------------------

    watch = [
        r for r in results
        if r["status"] == "WATCH"
    ]

    lines.append("")
    lines.append("🟡 WATCH")

    if not watch:

        lines.append("NONE")

    else:

        for r in watch[:8]:

            lines.append("")

            lines.append(
                f"🟡 {r['symbol']}"
            )

            lines.append(
                f"📈 5m: "
                f"{r['change_5m']:+.2f}%"
            )

            lines.append(
                f"💚 BUY PRESSURE: "
                f"{r['buy_pressure']:.1f}%"
            )

            lines.append(
                f"🚀 BREAKOUT: "
                f"{'YES' if r['breakout'] else 'NO'}"
            )

            lines.append(
                f"🎯 SCORE: "
                f"{r['score']}/12"
            )

    # --------------------------------------------------------
    # Paper / Real status
    # --------------------------------------------------------

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")

    lines.append(
        "📊 PAPER SIGNALS: ON"
    )

    lines.append(
        "🔧 REAL ORDERS: DISABLED"
    )

    lines.append(
        "💓 HEARTBEAT: ON"
    )

    lines.append(
        "🔄 CONTINUOUS MODE: ON"
    )

    lines.append(
        "🕐 " + now_text()
    )

    send_telegram(
        "\n".join(lines)
    )


# ============================================================
# HEARTBEAT
# ============================================================

def send_heartbeat():

    msg = (
        f"💓 ATI BOT HEARTBEAT\n\n"
        f"⚡ VERSION: {VERSION}\n"
        f"📡 STATUS: ALIVE\n"
        f"⏱ TIMEFRAME: {TIMEFRAME}\n"
        f"📊 MARKETS: "
        f"{len(get_usdt_markets())}\n"
        f"📊 DATA: "
        f"{LAST_STATS['markets_with_data']}\n"
        f"🕯 CANDLES: "
        f"{LAST_STATS['candles']}\n"
        f"🟢 CONFIRMED: "
        f"{LAST_STATS['confirmed']}\n"
        f"⚡ EARLY: "
        f"{LAST_STATS['early']}\n"
        f"🟡 WATCH: "
        f"{LAST_STATS['watch']}\n"
        f"⚠️ INSUFFICIENT: "
        f"{LAST_STATS['insufficient']}\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔄 NEXT SCAN: ABOUT 5 MINUTES\n"
        f"🕐 {now_text()}"
    )

    send_telegram(msg)


# ============================================================
# STARTUP
# ============================================================

def startup_message():

    msg = (
        f"🟢 ATI CRYPTO BOT {VERSION}\n\n"
        f"🧠 ROOT SIGNAL ENGINE\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED 5M DATA: YES\n"
        f"🛡 MINIMUM CANDLES: "
        f"{MIN_CANDLES_FOR_SIGNAL}\n"
        f"💚 MIN BUY PRESSURE: "
        f"{MIN_BUY_PRESSURE:.0f}%\n"
        f"🚀 BREAKOUT CONFIRMATION: ON\n"
        f"💓 HEARTBEAT: ON\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔄 CONTINUOUS MODE: ON\n"
        f"🕐 {now_text()}"
    )

    send_telegram(msg)


# ============================================================
# MAIN LOOP
# ============================================================

def run_forever():

    startup_message()

    while True:

        scan_start = time.time()

        try:

            run_scan()

        except Exception as e:

            print(
                "MAIN LOOP ERROR:",
                e
            )

            send_telegram(
                f"⚠️ ATI BOT {VERSION}\n"
                f"❌ SCAN ERROR\n\n"
                f"{str(e)[:500]}\n\n"
                f"🔄 BOT WILL RETRY\n"
                f"🕐 {now_text()}"
            )

        elapsed = (
            time.time() -
            scan_start
        )

        # Heartbeat after each completed scan
        try:
            send_heartbeat()
        except Exception as e:
            print(
                "HEARTBEAT ERROR:",
                e
            )

        # ----------------------------------------------------
        # Keep 5-minute cycle
        # ----------------------------------------------------

        wait_time = max(
            10,
            SCAN_INTERVAL_SECONDS -
            int(elapsed)
        )

        print(
            f"Next scan in "
            f"{wait_time} seconds..."
        )

        time.sleep(wait_time)


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    try:

        run_forever()

    except KeyboardInterrupt:

        print(
            "ATI BOT STOPPED"
        )

    except Exception as e:

        print(
            "FATAL ERROR:",
            e
        )

        try:

            send_telegram(
                f"🚨 ATI BOT {VERSION}\n"
                f"❌ FATAL ERROR\n\n"
                f"{str(e)[:500]}"
            )

        except Exception:
            pass
