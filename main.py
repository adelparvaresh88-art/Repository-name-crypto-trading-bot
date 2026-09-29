import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.5
# OPPORTUNITY ENGINE
# ============================================================

VERSION = "V40.2.5"

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
# MARKET MOVEMENT
# ------------------------------------------------------------

MIN_5M_CHANGE = 0.10
MAX_5M_CHANGE = 7.0

# ------------------------------------------------------------
# PRESSURE
# ------------------------------------------------------------

MIN_BUY_PRESSURE = 58.0
STRONG_BUY_PRESSURE = 65.0
EARLY_BUY_PRESSURE = 62.0
WATCH_BUY_PRESSURE = 55.0

PRESSURE_TRADES = 80

# ------------------------------------------------------------
# STRUCTURE
# ------------------------------------------------------------

BREAKOUT_LOOKBACK = 12

# Early entry can be close to resistance
EARLY_RESISTANCE_DISTANCE = 0.45

# Watch can be slightly farther away
WATCH_RESISTANCE_DISTANCE = 0.90

# ------------------------------------------------------------
# CANDLE QUALITY
# ------------------------------------------------------------

MIN_BODY_RATIO = 0.25
MIN_CANDLE_POSITION = 0.60

# ------------------------------------------------------------
# SCORES
# ------------------------------------------------------------

CONFIRMED_SCORE = 8
EARLY_SCORE = 7
WATCH_SCORE = 5

# ------------------------------------------------------------
# RISK LEVELS
# ------------------------------------------------------------

SL_PERCENT = 0.60
TP1_PERCENT = 1.00
TP2_PERCENT = 1.60

# Avoid chasing a very extended 5m candle
MAX_CANDLE_EXTENSION = 2.50

# ------------------------------------------------------------
# REAL TRADING
# ------------------------------------------------------------

REAL_ORDERS = False


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


# ============================================================
# STATS
# ============================================================

LAST_STATS = {
    "requested": 0,
    "responses": 0,
    "valid_trades": 0,
    "markets_with_data": 0,
    "insufficient": 0,
    "unknown_pressure": 0,
    "candles": 0,
    "confirmed": 0,
    "early": 0,
    "watch": 0,
    "rejected": 0,
}


# ============================================================
# HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def now_text():
    return utc_now().strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


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
        print(message)
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
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
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print(
            "Telegram error:",
            response.status_code,
            response.text[:300],
        )

        return False

    except Exception as e:

        print(
            "Telegram exception:",
            e
        )

        return False


# ============================================================
# API
# ============================================================

def get_json(path, params=None):

    url = BASE_URL + path

    for attempt in range(
        1,
        MAX_RETRIES + 1
    ):

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

            if response.status_code in (
                429,
                500,
                502,
                503,
                504,
            ):

                time.sleep(
                    min(2 * attempt, 8)
                )

                continue

            print(
                f"API ERROR "
                f"{response.status_code}: "
                f"{response.text[:200]}"
            )

            return None

        except requests.RequestException as e:

            if attempt >= MAX_RETRIES:
                print(
                    "REQUEST ERROR:",
                    e
                )
                return None

            time.sleep(
                min(2 * attempt, 8)
            )

        except Exception as e:

            print(
                "JSON ERROR:",
                e
            )

            return None

    return None


# ============================================================
# MARKET DISCOVERY
# ============================================================

def find_symbol_objects(obj):

    found = []

    if isinstance(obj, dict):

        keys = {
            str(k).lower()
            for k in obj.keys()
        }

        symbol_keys = {
            "symbol",
            "pair",
            "market",
            "instrument",
            "code",
            "name",
        }

        if keys.intersection(
            symbol_keys
        ):
            found.append(obj)

        for value in obj.values():

            found.extend(
                find_symbol_objects(value)
            )

    elif isinstance(obj, list):

        for item in obj:

            found.extend(
                find_symbol_objects(item)
            )

    return found


def extract_exchange_symbols(data):

    symbols = set()

    for item in find_symbol_objects(data):

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

        normalized = normalize_symbol(
            symbol
        )

        if not normalized.endswith("USDT"):
            continue

        status = ""

        for key in [
            "status",
            "state",
            "active",
            "enabled",
        ]:

            if key in item:

                status = str(
                    item.get(key)
                ).upper()

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

    symbols = extract_exchange_symbols(
        data
    )

    return symbols[:MAX_MARKETS]


# ============================================================
# TRADE PARSER
# ============================================================

def extract_trade_list(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

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

                nested = value.get(
                    nested_key
                )

                if isinstance(
                    nested,
                    list
                ):
                    return nested

    def recursive(obj):

        if isinstance(obj, list):
            return obj

        if isinstance(obj, dict):

            for value in obj.values():

                result = recursive(value)

                if result:
                    return result

        return []

    return recursive(data)


def normalize_timestamp(value):

    if value is None:
        return None

    try:
        ts = float(value)
    except Exception:
        return None

    if ts < 10_000_000_000:
        return ts

    if ts < 10_000_000_000_000:
        return ts / 1000.0

    if ts < 10_000_000_000_000_000:
        return ts / 1_000_000.0

    return ts / 1_000_000_000.0


def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = None
    qty = None
    timestamp = None
    buyer_maker = None

    # PRICE
    for key in [
        "price",
        "p",
        "rate",
        "px",
    ]:

        if key in item:

            price = safe_float(
                item.get(key)
            )

            if price is not None:
                break

    # QUANTITY
    for key in [
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
    ]:

        if key in item:

            qty = safe_float(
                item.get(key)
            )

            if qty is not None:
                break

    # TIME
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

    # BUYER MAKER
    for key in [
        "isBuyerMaker",
        "buyerMaker",
        "m",
        "is_buyer_maker",
    ]:

        if key not in item:
            continue

        value = item.get(key)

        if isinstance(value, bool):

            buyer_maker = value
            break

        if isinstance(value, int):

            buyer_maker = bool(value)
            break

        if isinstance(value, str):

            value = value.strip().lower()

            if value in {
                "true",
                "1",
                "yes",
            }:

                buyer_maker = True
                break

            if value in {
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

    raw = extract_trade_list(data)

    if not raw:

        fallback_symbol = (
            symbol[:-4] + "_USDT"
            if symbol.endswith("USDT")
            else symbol
        )

        data = get_json(
            "/r/api/v1/trades",
            {
                "tabdealSymbol":
                    fallback_symbol,
                "limit":
                    TRADE_LIMIT,
            },
        )

        raw = extract_trade_list(data)

    if not raw:
        return []

    LAST_STATS["responses"] += 1

    parsed = []

    for item in raw:

        trade = parse_trade(item)

        if trade is not None:
            parsed.append(trade)

    LAST_STATS[
        "valid_trades"
    ] += len(parsed)

    return parsed


# ============================================================
# CANDLES
# ============================================================

def candle_bucket(timestamp):

    if timestamp is None:
        return None

    return int(
        timestamp // 300
    ) * 300


def build_candles(trades):

    timed = [
        t for t in trades
        if t.get("timestamp") is not None
    ]

    if not timed:
        return []

    timed.sort(
        key=lambda x:
        x["timestamp"]
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

            candle["volume"] += qty

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x:
        x["timestamp"]
    )

    return candles


# ============================================================
# PRESSURE ENGINE
# ============================================================

def calculate_buy_pressure(trades):

    valid = [
        t for t in trades
        if t.get("buyer_maker")
        is not None
    ]

    if len(valid) < 10:
        return None

    recent = valid[
        -PRESSURE_TRADES:
    ]

    buy_volume = 0.0
    sell_volume = 0.0

    for trade in recent:

        value = (
            trade["price"]
            *
            trade["qty"]
        )

        # buyer_maker False = aggressive BUY
        if trade["buyer_maker"] is False:

            buy_volume += value

        # buyer_maker True = aggressive SELL
        elif trade["buyer_maker"] is True:

            sell_volume += value

    total = (
        buy_volume +
        sell_volume
    )

    if total <= 0:
        return None

    return (
        buy_volume /
        total
    ) * 100.0


# ============================================================
# CANDLE QUALITY
# ============================================================

def candle_metrics(candle):

    high = candle["high"]
    low = candle["low"]
    open_price = candle["open"]
    close = candle["close"]

    rng = high - low

    if rng <= 0:
        return 0.0, 0.0

    body = abs(
        close - open_price
    )

    body_ratio = (
        body / rng
    )

    position = (
        close - low
    ) / rng

    return (
        body_ratio,
        position,
    )


# ============================================================
# STRUCTURE
# ============================================================

def structure_info(candles):

    previous = candles[
        -BREAKOUT_LOOKBACK - 1:-1
    ]

    current = candles[-1]

    if len(previous) < 5:

        return {
            "resistance": None,
            "breakout": False,
            "distance": None,
            "rising": False,
        }

    resistance = max(
        c["high"]
        for c in previous
    )

    price = current["close"]

    if resistance <= 0:

        return {
            "resistance": None,
            "breakout": False,
            "distance": None,
            "rising": False,
        }

    distance = (
        (resistance - price)
        / resistance
    ) * 100.0

    breakout = (
        price > resistance
    )

    closes = [
        c["close"]
        for c in candles[-6:]
    ]

    rising_count = 0

    for i in range(
        1,
        len(closes)
    ):

        if (
            closes[i]
            >
            closes[i - 1]
        ):
            rising_count += 1

    rising = (
        rising_count >= 3
    )

    return {
        "resistance": resistance,
        "breakout": breakout,
        "distance": distance,
        "rising": rising,
    }


# ============================================================
# OPPORTUNITY ENGINE
# ============================================================

def analyze_market(symbol, trades):

    if not trades:

        return {
            "symbol": symbol,
            "status": "NO DATA",
        }

    candles = build_candles(
        trades
    )

    if len(candles) < MIN_CANDLES_FOR_SIGNAL:

        return {
            "symbol": symbol,
            "status": "INSUFFICIENT DATA",
            "candles": len(candles),
        }

    current = candles[-1]
    previous = candles[-2]

    price = current["close"]

    if previous["close"] <= 0:
        return None

    change_5m = (
        (
            price -
            previous["close"]
        )
        /
        previous["close"]
    ) * 100.0

    pressure = calculate_buy_pressure(
        trades
    )

    if pressure is None:

        return {
            "symbol": symbol,
            "status": "UNKNOWN PRESSURE",
            "candles": len(candles),
        }

    body_ratio, position = (
        candle_metrics(current)
    )

    structure = structure_info(
        candles
    )

    resistance = structure[
        "resistance"
    ]

    breakout = structure[
        "breakout"
    ]

    rising = structure[
        "rising"
    ]

    # --------------------------------------------------------
    # Distance from resistance
    # --------------------------------------------------------

    if resistance and resistance > 0:

        distance = (
            (
                resistance -
                price
            )
            /
            resistance
        ) * 100.0

    else:

        distance = None

    # --------------------------------------------------------
    # Extension
    # --------------------------------------------------------

    too_extended = (
        change_5m >
        MAX_CANDLE_EXTENSION
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    # Momentum
    if change_5m >= MIN_5M_CHANGE:
        score += 2

    if change_5m <= MAX_5M_CHANGE:
        score += 1

    # Pressure
    if pressure >= MIN_BUY_PRESSURE:
        score += 2

    if pressure >= STRONG_BUY_PRESSURE:
        score += 1

    # Breakout
    if breakout:
        score += 2

    # Candle quality
    if body_ratio >= MIN_BODY_RATIO:
        score += 1

    if position >= MIN_CANDLE_POSITION:
        score += 1

    # Structure
    if rising:
        score += 1

    # --------------------------------------------------------
    # CONFIRMED BUY
    #
    # Must have real breakout.
    # --------------------------------------------------------

    confirmed = (
        breakout
        and
        pressure >= MIN_BUY_PRESSURE
        and
        change_5m >= MIN_5M_CHANGE
        and
        change_5m <= MAX_5M_CHANGE
        and
        body_ratio >= MIN_BODY_RATIO
        and
        position >= MIN_CANDLE_POSITION
        and
        rising
        and
        score >= CONFIRMED_SCORE
        and
        not too_extended
    )

    # --------------------------------------------------------
    # EARLY BUY
    #
    # Not broken yet, but close to resistance.
    # --------------------------------------------------------

    near_resistance = (
        distance is not None
        and
        distance >= 0
        and
        distance <=
        EARLY_RESISTANCE_DISTANCE
    )

    early = (
        not breakout
        and
        near_resistance
        and
        pressure >= EARLY_BUY_PRESSURE
        and
        change_5m >= MIN_5M_CHANGE
        and
        change_5m <= MAX_5M_CHANGE
        and
        body_ratio >= MIN_BODY_RATIO
        and
        position >= MIN_CANDLE_POSITION
        and
        rising
        and
        score >= EARLY_SCORE
        and
        not too_extended
    )

    # --------------------------------------------------------
    # WATCH
    #
    # Earlier stage.
    # --------------------------------------------------------

    watch_near = (
        distance is not None
        and
        distance >= 0
        and
        distance <=
        WATCH_RESISTANCE_DISTANCE
    )

    watch = (
        not breakout
        and
        watch_near
        and
        pressure >= WATCH_BUY_PRESSURE
        and
        change_5m >= MIN_5M_CHANGE
        and
        change_5m <= MAX_5M_CHANGE
        and
        rising
        and
        score >= WATCH_SCORE
        and
        not too_extended
    )

    if confirmed:

        status = "CONFIRMED BUY"

    elif early:

        status = "EARLY BUY"

    elif watch:

        status = "WATCH"

    else:

        status = "REJECTED"

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
        "price": price,
        "change_5m": change_5m,
        "score": score,
        "buy_pressure": pressure,
        "breakout": breakout,
        "candles": len(candles),
        "body_ratio": body_ratio,
        "candle_position": position,
        "rising": rising,
        "resistance": resistance,
        "distance": distance,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


# ============================================================
# WORKER
# ============================================================

def process_market(symbol):

    try:

        time.sleep(
            REQUEST_DELAY
        )

        trades = get_symbol_trades(
            symbol
        )

        if not trades:
            return None

        return analyze_market(
            symbol,
            trades
        )

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
        "unknown_pressure": 0,
        "candles": 0,
        "confirmed": 0,
        "early": 0,
        "watch": 0,
        "rejected": 0,
    }

    markets = get_usdt_markets()

    if not markets:

        send_telegram(
            f"⚠️ ATI BOT {VERSION}\n"
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
                symbol,
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

                if status == "UNKNOWN PRESSURE":

                    LAST_STATS[
                        "unknown_pressure"
                    ] += 1

                    continue

                if status == "NO DATA":
                    continue

                candles = result.get(
                    "candles",
                    0,
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
                    "FUTURE ERROR:",
                    e
                )

    # --------------------------------------------------------
    # SORT
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
                0,
            ),
            x.get(
                "score",
                0,
            ),
            x.get(
                "buy_pressure",
                0,
            ),
            x.get(
                "change_5m",
                0,
            ),
        ),
        reverse=True,
    )

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    lines.append(
        "🧠 OPPORTUNITY ENGINE"
    )

    lines.append("")

    lines.append(
        "📡 TABDEAL API: OK"
    )

    lines.append(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
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
        f"⚠️ UNKNOWN PRESSURE: "
        f"{LAST_STATS['unknown_pressure']}"
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

    # ========================================================
    # CONFIRMED
    # ========================================================

    lines.append(
        "🟢 CONFIRMED BUY"
    )

    confirmed = [
        r for r in results
        if r["status"] ==
        "CONFIRMED BUY"
    ]

    if not confirmed:

        lines.append("NONE")

    else:

        for r in confirmed[:8]:

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

    # ========================================================
    # EARLY
    # ========================================================

    lines.append("")
    lines.append(
        "⚡ EARLY BUY"
    )

    early = [
        r for r in results
        if r["status"] ==
        "EARLY BUY"
    ]

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
                f"📏 RESISTANCE DIST: "
                f"{r['distance']:.2f}%"
            )

            lines.append(
                "🚀 BREAKOUT: NO"
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

    # ========================================================
    # WATCH
    # ========================================================

    lines.append("")
    lines.append(
        "🟡 WATCH"
    )

    watch = [
        r for r in results
        if r["status"] ==
        "WATCH"
    ]

    if not watch:

        lines.append("NONE")

    else:

        for r in watch[:8]:

            lines.append("")
            lines.append(
                f"🟡 {r['symbol']}"
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
                f"💚 BUY PRESSURE: "
                f"{r['buy_pressure']:.1f}%"
            )

            lines.append(
                f"📏 RESISTANCE DIST: "
                f"{r['distance']:.2f}%"
            )

            lines.append(
                f"🎯 SCORE: "
                f"{r['score']}/12"
            )

            lines.append(
                "🚀 BREAKOUT: NO"
            )

    # ========================================================
    # FOOTER
    # ========================================================

    lines.append("")
    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

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

    markets = get_usdt_markets()

    message = (
        f"💓 ATI BOT HEARTBEAT\n\n"
        f"⚡ VERSION: {VERSION}\n"
        f"📡 STATUS: ALIVE\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"📊 MARKETS: {len(markets)}\n"
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
        f"⚠️ UNKNOWN PRESSURE: "
        f"{LAST_STATS['unknown_pressure']}\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔄 NEXT SCAN: ABOUT 5 MINUTES\n"
        f"🕐 {now_text()}"
    )

    send_telegram(message)


# ============================================================
# STARTUP
# ============================================================

def startup_message():

    message = (
        f"🟢 ATI CRYPTO BOT {VERSION}\n\n"
        f"🧠 OPPORTUNITY ENGINE\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED 5M DATA: YES\n"
        f"🛡 MINIMUM CANDLES: "
        f"{MIN_CANDLES_FOR_SIGNAL}\n"
        f"💚 CONFIRMED PRESSURE: "
        f"{MIN_BUY_PRESSURE:.0f}%+\n"
        f"⚡ EARLY PRESSURE: "
        f"{EARLY_BUY_PRESSURE:.0f}%+\n"
        f"🚀 BREAKOUT ENGINE: ON\n"
        f"💓 HEARTBEAT: ON\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🔄 CONTINUOUS MODE: ON\n"
        f"🕐 {now_text()}"
    )

    send_telegram(message)


# ============================================================
# MAIN LOOP
# ============================================================

def run_forever():

    startup_message()

    while True:

        started = time.time()

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
                f"🔄 RETRYING\n"
                f"🕐 {now_text()}"
            )

        try:

            send_heartbeat()

        except Exception as e:

            print(
                "HEARTBEAT ERROR:",
                e
            )

        elapsed = (
            time.time() -
            started
        )

        wait_time = max(
            10,
            SCAN_INTERVAL_SECONDS -
            int(elapsed)
        )

        print(
            f"Next scan in "
            f"{wait_time} seconds..."
        )

        time.sleep(
            wait_time
        )


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
