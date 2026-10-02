import os
import time
import hmac
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.37
# ============================================================
# SINGLE STRATEGY:
#
#        BOS -> BREAKOUT -> PULLBACK -> CONTINUATION
#
# NO EMA
# NO MULTI-STRATEGY
# CLOSED 5M CANDLES
# TABDIL AUTH
# SCANNER / PAPER ONLY
# REAL ORDERS LOCKED
# ============================================================

VERSION = "V40.2.37"

BASE_URL = "https://api1.tabdeal.org"

# ============================================================
# SAFETY
# ============================================================

REAL_ORDERS = False
BUY_LOCK = True

# ============================================================
# SCANNER
# ============================================================

SCAN_UNIVERSE = 40
TOP_RESULTS = 10

TRADE_LIMIT = 1000
MIN_CANDLES = 25

REQUEST_TIMEOUT = 12
MAX_WORKERS = 8

# ============================================================
# STRATEGY SETTINGS
# ============================================================

# Resistance / structure
STRUCTURE_LOOKBACK = 12
PULLBACK_LOOKBACK = 4

# Breakout zone
MIN_BREAKOUT = -0.15
MAX_BREAKOUT = 1.80

# Pullback tolerance around broken resistance
PULLBACK_TOLERANCE = 0.80

# Continuation requirements
MIN_CONTINUATION_MOVE = 0.05

# Momentum
MIN_M5_MOMENTUM = 0.00
MIN_M15_MOMENTUM = 0.00
MIN_1H_MOMENTUM = 0.00

# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()

# ============================================================
# API
# ============================================================

API_KEY = os.getenv(
    "TABDIL_API_KEY",
    ""
).strip()

API_SECRET = os.getenv(
    "TABDIL_API_SECRET",
    ""
).strip()

# Fallback only
if not API_KEY:
    API_KEY = os.getenv(
        "TABDEAL_API_KEY",
        ""
    ).strip()

if not API_SECRET:
    API_SECRET = os.getenv(
        "TABDEAL_API_SECRET",
        ""
    ).strip()


session = requests.Session()

session.headers.update({
    "User-Agent": f"ATI-Crypto-Bot/{VERSION}"
})


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN:
        return False

    if not TELEGRAM_CHAT_ID:
        return False

    try:
        url = (
            "https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage"
        )

        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True
            },
            timeout=15
        )

        return response.ok

    except Exception:
        return False


def telegram_long(message):
    limit = 3900

    if len(message) <= limit:
        telegram_send(message)
        return

    while message:
        part = message[:limit]
        message = message[limit:]

        telegram_send(part)

        time.sleep(0.4)


# ============================================================
# SAFE CONVERSION
# ============================================================

def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():

    url = f"{BASE_URL}/r/api/v1/time"

    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, (int, float)):
        return int(data)

    if isinstance(data, dict):

        for key in (
            "serverTime",
            "timestamp",
            "time"
        ):

            if key in data:

                value = data[key]

                if isinstance(value, dict):

                    for subkey in (
                        "serverTime",
                        "timestamp",
                        "time"
                    ):

                        if subkey in value:
                            value = value[subkey]
                            break

                try:
                    return int(value)
                except Exception:
                    pass

    raise RuntimeError(
        "SERVER_TIME_NOT_FOUND"
    )


# ============================================================
# SIGNED GET
# ============================================================

def signed_get(
    path,
    extra_params=None
):

    if not API_KEY:
        raise RuntimeError(
            "TABDIL_API_KEY_MISSING"
        )

    if not API_SECRET:
        raise RuntimeError(
            "TABDIL_API_SECRET_MISSING"
        )

    timestamp = get_server_time()

    params = {}

    if extra_params:
        params.update(
            extra_params
        )

    params["timestamp"] = int(
        timestamp
    )

    params["recvWindow"] = 5000

    query = "&".join(
        f"{key}={params[key]}"
        for key in params
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    response = session.get(
        f"{BASE_URL}{path}",
        params=params,
        headers={
            "X-MBX-APIKEY": API_KEY
        },
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code == 401:
        raise RuntimeError(
            "HTTP_401_INVALID_SIGNATURE"
        )

    response.raise_for_status()

    return response.json()


# ============================================================
# AUTH TEST
# ============================================================

def auth_test():

    data = signed_get(
        "/r/api/v1/account"
    )

    if isinstance(data, dict):

        code = data.get(
            "code"
        )

        if code not in (
            None,
            0,
            "0"
        ):

            raise RuntimeError(
                f"ACCOUNT_CODE_{code}"
            )

    return True


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    response = session.get(
        f"{BASE_URL}/r/api/v1/exchangeInfo",
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()


def extract_symbols(data):

    raw = []

    if isinstance(data, list):

        raw = data

    elif isinstance(data, dict):

        for key in (
            "symbols",
            "data",
            "result",
            "items"
        ):

            value = data.get(key)

            if isinstance(value, list):
                raw = value
                break

            if isinstance(value, dict):

                for subkey in (
                    "symbols",
                    "data",
                    "result",
                    "items"
                ):

                    subvalue = value.get(
                        subkey
                    )

                    if isinstance(
                        subvalue,
                        list
                    ):

                        raw = subvalue
                        break

                if raw:
                    break

    result = []
    seen = set()

    for item in raw:

        if isinstance(item, str):

            symbol = item.upper()

            if symbol.endswith("USDT"):

                if symbol not in seen:
                    seen.add(symbol)
                    result.append(symbol)

            continue

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("market")
            or item.get("name")
            or item.get("tabdealSymbol")
        )

        if not symbol:
            continue

        symbol = str(
            symbol
        ).upper()

        status = str(
            item.get(
                "status",
                "TRADING"
            )
        ).upper()

        quote = str(
            item.get(
                "quoteAsset",
                item.get(
                    "quote",
                    ""
                )
            )
        ).upper()

        if not symbol.endswith("USDT"):
            continue

        if status in (
            "BREAK",
            "HALT",
            "STOPPED",
            "DISABLED"
        ):
            continue

        if quote and quote != "USDT":
            continue

        if symbol not in seen:
            seen.add(symbol)
            result.append(symbol)

    return result


# ============================================================
# TRADE API
# ============================================================

def parse_trade_list(data):

    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in (
        "data",
        "trades",
        "result",
        "items"
    ):

        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):

            nested = parse_trade_list(
                value
            )

            if nested:
                return nested

    return []


def get_recent_trades(symbol):

    attempts = [
        {"tabdealSymbol": symbol},
        {"symbol": symbol},
        {"market": symbol},
        {"tabdeal_symbol": symbol}
    ]

    last_error = "UNKNOWN"

    for extra in attempts:

        try:

            params = dict(
                extra
            )

            params["limit"] = TRADE_LIMIT

            response = session.get(
                f"{BASE_URL}/r/api/v1/trades",
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code != 200:

                last_error = (
                    f"HTTP_{response.status_code}"
                )

                continue

            data = response.json()

            trades = parse_trade_list(
                data
            )

            if trades:
                return trades

        except Exception as exc:

            last_error = str(
                exc
            )

    raise RuntimeError(
        f"TRADE_API_ERROR:{last_error}"
    )


# ============================================================
# TRADE PARSING
# ============================================================

def trade_price(item):

    if not isinstance(item, dict):
        return 0.0

    for key in (
        "price",
        "p",
        "tradePrice",
        "lastPrice"
    ):

        if key in item:

            value = safe_float(
                item[key]
            )

            if value > 0:
                return value

    return 0.0


def trade_quantity(item):

    if not isinstance(item, dict):
        return 0.0

    for key in (
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
        "baseQty"
    ):

        if key in item:

            value = safe_float(
                item[key]
            )

            if value > 0:
                return value

    return 0.0


def trade_time(item):

    if not isinstance(item, dict):
        return None

    for key in (
        "time",
        "timestamp",
        "T",
        "tradeTime",
        "createdAt"
    ):

        if key not in item:
            continue

        try:

            value = float(
                item[key]
            )

            if value < 10000000000:
                value *= 1000

            return int(value)

        except Exception:
            continue

    return None


# ============================================================
# 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    buckets = {}

    for item in trades:

        price = trade_price(
            item
        )

        quantity = trade_quantity(
            item
        )

        timestamp = trade_time(
            item
        )

        if price <= 0:
            continue

        if timestamp is None:
            continue

        bucket = (
            timestamp
            // (5 * 60 * 1000)
        ) * (5 * 60 * 1000)

        if bucket not in buckets:

            buckets[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
                "quote_volume": 0.0,
                "time": bucket
            }

        candle = buckets[bucket]

        candle["high"] = max(
            candle["high"],
            price
        )

        candle["low"] = min(
            candle["low"],
            price
        )

        candle["close"] = price

        candle["volume"] += quantity

        candle["quote_volume"] += (
            price * quantity
        )

    candles = [
        buckets[key]
        for key in sorted(buckets)
    ]

    # Remove current open candle.
    now_ms = int(
        time.time() * 1000
    )

    current_bucket = (
        now_ms
        // (5 * 60 * 1000)
    ) * (5 * 60 * 1000)

    candles = [
        candle
        for candle in candles
        if candle["time"] < current_bucket
    ]

    return candles


# ============================================================
# CANDLE FUNCTIONS
# ============================================================

def candle_body_percent(candle):

    high = candle["high"]
    low = candle["low"]

    if high <= low:
        return 0.0

    return (
        abs(
            candle["close"]
            - candle["open"]
        )
        / (high - low)
    ) * 100.0


def bullish(candle):
    return candle["close"] > candle["open"]


def bearish(candle):
    return candle["close"] < candle["open"]


def percent_change(old, new):

    if old <= 0:
        return 0.0

    return (
        (new - old)
        / old
    ) * 100.0


# ============================================================
# MOMENTUM
# ============================================================

def momentum_5m(candles):

    if len(candles) < 2:
        return 0.0

    return percent_change(
        candles[-2]["close"],
        candles[-1]["close"]
    )


def momentum_15m(candles):

    if len(candles) < 4:
        return 0.0

    return percent_change(
        candles[-4]["close"],
        candles[-1]["close"]
    )


def momentum_1h(candles):

    if len(candles) < 13:
        return 0.0

    return percent_change(
        candles[-13]["close"],
        candles[-1]["close"]
    )


# ============================================================
# STRUCTURE
# ============================================================

def resistance(candles):

    if len(candles) < (
        STRUCTURE_LOOKBACK + 1
    ):
        return 0.0

    previous = candles[
        -(STRUCTURE_LOOKBACK + 1):-1
    ]

    return max(
        candle["high"]
        for candle in previous
    )


def recent_swing_low(candles):

    if len(candles) < PULLBACK_LOOKBACK:
        return 0.0

    previous = candles[
        -PULLBACK_LOOKBACK:
    ]

    return min(
        candle["low"]
        for candle in previous
    )


# ============================================================
# VOLUME
# ============================================================

def average_volume(
    candles,
    count=10
):

    if len(candles) < 2:
        return 0.0

    previous = candles[
        -(count + 1):-1
    ]

    if not previous:
        return 0.0

    values = [
        safe_float(
            candle["volume"]
        )
        for candle in previous
    ]

    if not values:
        return 0.0

    return (
        sum(values)
        / len(values)
    )


def volume_ratio(candles):

    if len(candles) < 3:
        return 0.0

    current = safe_float(
        candles[-1]["volume"]
    )

    avg = average_volume(
        candles,
        10
    )

    if avg <= 0:
        return 0.0

    return current / avg


# ============================================================
# SINGLE STRATEGY
# BOS -> BREAKOUT -> PULLBACK -> CONTINUATION
# ============================================================

def analyze_symbol(symbol):

    result = {
        "symbol": symbol,
        "ok": False,
        "state": "FILTERED",
        "score": 0,
        "price": 0.0,
        "resistance": 0.0,
        "breakout": 0.0,
        "volume": 0.0,
        "body": 0.0,
        "m5": 0.0,
        "m15": 0.0,
        "m1h": 0.0,
        "setup": "NONE",
        "reason": "",
        "candles": 0
    }

    try:

        trades = get_recent_trades(
            symbol
        )

        candles = build_5m_candles(
            trades
        )

        result["candles"] = len(
            candles
        )

        if len(candles) < MIN_CANDLES:

            result["reason"] = (
                "NOT_ENOUGH_CANDLES"
            )

            return result

        last = candles[-1]

        price = safe_float(
            last["close"]
        )

        if price <= 0:

            result["reason"] = (
                "INVALID_PRICE"
            )

            return result

        level = resistance(
            candles
        )

        if level <= 0:

            result["reason"] = (
                "NO_RESISTANCE"
            )

            return result

        breakout = (
            (price - level)
            / level
        ) * 100.0

        m5 = momentum_5m(
            candles
        )

        m15 = momentum_15m(
            candles
        )

        m1h = momentum_1h(
            candles
        )

        volume = volume_ratio(
            candles
        )

        body = candle_body_percent(
            last
        )

        is_green = bullish(
            last
        )

        is_red = bearish(
            last
        )

        # ----------------------------------------------------
        # Structure BEFORE current candle
        # ----------------------------------------------------

        previous_closes = [
            candle["close"]
            for candle in candles[
                -(STRUCTURE_LOOKBACK + 1):-1
            ]
        ]

        previous_high = max(
            candle["high"]
            for candle in candles[
                -(STRUCTURE_LOOKBACK + 1):-1
            ]
        )

        # ----------------------------------------------------
        # Was resistance broken?
        # ----------------------------------------------------

        breakout_detected = (
            price >= previous_high
        )

        # ----------------------------------------------------
        # Pullback detection
        #
        # Current candle can be:
        # - above resistance
        # - slightly below resistance
        # - touching resistance
        #
        # while recent candle lows prove price
        # interacted with the broken level.
        # ----------------------------------------------------

        recent = candles[
            -PULLBACK_LOOKBACK:
        ]

        recent_low = min(
            candle["low"]
            for candle in recent
        )

        pullback_distance = (
            abs(recent_low - level)
            / level
        ) * 100.0

        touched_level = (
            pullback_distance
            <= PULLBACK_TOLERANCE
        )

        # ----------------------------------------------------
        # Continuation
        # ----------------------------------------------------

        continuation = (
            is_green
            and m5 > MIN_M5_MOMENTUM
            and price >= level
        )

        # ----------------------------------------------------
        # Trend
        # ----------------------------------------------------

        trend_up = (
            m15 > MIN_M15_MOMENTUM
            and m1h > MIN_1H_MOMENTUM
        )

        # ----------------------------------------------------
        # Chase protection
        # ----------------------------------------------------

        chasing = (
            breakout > MAX_BREAKOUT
        )

        # ----------------------------------------------------
        # Score
        #
        # This score is NOT another strategy.
        # It ranks the quality of the SAME setup.
        # ----------------------------------------------------

        score = 0
        reasons = []

        # 1. 1H trend
        if m1h > 0:
            score += 3
        else:
            score -= 2
            reasons.append(
                "1H_DOWN"
            )

        if m1h >= 2.0:
            score += 1

        # 2. 15M trend
        if m15 > 0:
            score += 3
        else:
            score -= 2
            reasons.append(
                "15M_DOWN"
            )

        if m15 >= 1.0:
            score += 1

        # 3. 5M continuation
        if m5 > 0:
            score += 3
        else:
            score -= 2
            reasons.append(
                "5M_DOWN"
            )

        if m5 >= 0.30:
            score += 1

        # 4. Structure
        if breakout_detected:
            score += 3
        elif breakout >= -0.30:
            score += 2
            reasons.append(
                "NEAR_BOS"
            )
        else:
            score -= 2
            reasons.append(
                "BELOW_STRUCTURE"
            )

        # 5. Pullback
        if touched_level:
            score += 3
        else:
            reasons.append(
                "NO_PULLBACK"
            )

        # 6. Continuation candle
        if is_green:
            score += 2
        else:
            score -= 1
            reasons.append(
                "NO_GREEN_CONFIRMATION"
            )

        # 7. Body
        if body >= 50:
            score += 2
        elif body >= 25:
            score += 1
        else:
            reasons.append(
                "SMALL_BODY"
            )

        # 8. Volume
        if volume >= 1.50:
            score += 2
        elif volume >= 0.70:
            score += 1
        else:
            reasons.append(
                "LOW_VOLUME"
            )

        # 9. Chase
        if chasing:
            score -= 4
            reasons.append(
                "CHASE"
            )

        score = max(
            0,
            min(
                20,
                score
            )
        )

        # ----------------------------------------------------
        # CLASSIFICATION
        # ----------------------------------------------------

        # STRONG:
        # complete setup:
        # BOS + pullback + continuation + trend
        if (
            breakout_detected
            and touched_level
            and continuation
            and trend_up
            and not chasing
            and body >= 25
            and score >= 14
        ):

            state = "STRONG"

            setup = (
                "BOS+PULLBACK+CONTINUATION"
            )

        # EARLY:
        # near BOS / pullback zone,
        # trend is aligned,
        # continuation is beginning.
        elif (
            breakout >= -0.30
            and touched_level
            and trend_up
            and m5 > 0
            and is_green
            and not chasing
            and score >= 10
        ):

            state = "EARLY"

            setup = (
                "BREAKOUT/PULLBACK"
            )

        # WATCH:
        # ranked candidate but setup incomplete.
        elif (
            trend_up
            and score >= 7
        ):

            state = "WATCH"

            setup = (
                "SETUP_INCOMPLETE"
            )

        else:

            state = "FILTERED"

            setup = "NONE"

        result.update({
            "ok": True,
            "state": state,
            "score": score,
            "price": price,
            "resistance": level,
            "breakout": breakout,
            "volume": volume,
            "body": body,
            "m5": m5,
            "m15": m15,
            "m1h": m1h,
            "setup": setup,
            "reason": (
                ",".join(reasons)
                if reasons
                else "OK"
            )
        })

        return result

    except Exception as exc:

        result["reason"] = str(
            exc
        )[:180]

        return result


# ============================================================
# FORMAT
# ============================================================

def format_result(
    index,
    item
):

    if item["state"] == "STRONG":

        icon = "🟢"
        label = "STRONG"

    elif item["state"] == "EARLY":

        icon = "🟡"
        label = "EARLY"

    else:

        icon = "⚪"
        label = "WATCH"

    return (
        f"{index}. "
        f"{item['symbol']} "
        f"{icon} {label}\n"
        f"Score: {item['score']}/20\n"
        f"Setup: {item['setup']}\n"
        f"Price: {item['price']:.10g}\n"
        f"Resistance: {item['resistance']:.10g}\n"
        f"Breakout: {item['breakout']:+.2f}%\n"
        f"Volume: {item['volume']:.2f}x\n"
        f"Body: {item['body']:.0f}%\n"
        f"5m: {item['m5']:+.2f}% | "
        f"15m: {item['m15']:+.2f}% | "
        f"1h: {item['m1h']:+.2f}%\n"
        f"State: {item['reason']}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    start_time = time.time()

    # --------------------------------------------------------
    # START
    # --------------------------------------------------------

    telegram_send(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🧠 ONE STRATEGY ONLY\n"
        f"📐 BOS → BREAKOUT → PULLBACK → CONTINUATION\n"
        f"🕯 CLOSED 5M CANDLES\n"
        f"🚫 NO EMA\n"
        f"🔎 SCAN UNIVERSE: {SCAN_UNIVERSE}\n"
        f"🎯 TOP {TOP_RESULTS}\n\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 BUY LOCK: ACTIVE\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    try:

        telegram_send(
            f"🔐 ATI AUTH TEST {VERSION}\n\n"
            f"🔑 KEY PAIR: TABDIL\n"
            f"🔐 HMAC-SHA256\n"
            f"🔢 SERVER TIMESTAMP\n"
            f"🔒 REAL BUY: DISABLED\n"
            f"🕐 {utc_now()}"
        )

        auth_test()

        telegram_send(
            f"✅ ATI API AUTH SUCCESS {VERSION}\n"
            f"🟢 WORKING PAIR: TABDIL\n"
            f"📡 ACCOUNT API: OK\n"
            f"🔒 REAL ORDERS: DISABLED\n"
            f"🕐 {utc_now()}"
        )

    except Exception as exc:

        telegram_send(
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ {str(exc)[:600]}\n\n"
            f"🛑 SCAN STOPPED\n"
            f"🔒 REAL ORDERS: DISABLED\n"
            f"🕐 {utc_now()}"
        )

        return

    # --------------------------------------------------------
    # EXCHANGE INFO
    # --------------------------------------------------------

    try:

        exchange_data = (
            get_exchange_info()
        )

        symbols = extract_symbols(
            exchange_data
        )

        telegram_send(
            f"📊 EXCHANGE INFO OK {VERSION}\n"
            f"🟢 USDT MARKETS: {len(symbols)}\n"
            f"🔎 STRATEGY SCAN STARTING...\n"
            f"📐 BOS → PULLBACK → CONTINUATION\n"
            f"🔒 REAL ORDERS: DISABLED"
        )

    except Exception as exc:

        telegram_send(
            f"🚨 EXCHANGE INFO ERROR {VERSION}\n"
            f"❌ {str(exc)[:500]}\n"
            f"🔒 REAL ORDERS: DISABLED"
        )

        return

    if not symbols:

        telegram_send(
            f"❌ NO USDT MARKETS FOUND\n"
            f"🛑 SCAN STOPPED"
        )

        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    scan_symbols = symbols[
        :SCAN_UNIVERSE
    ]

    analyzed = []
    errors = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol
            ): symbol
            for symbol in scan_symbols
        }

        for future in as_completed(
            futures
        ):

            try:

                item = future.result()

                if item["ok"]:
                    analyzed.append(
                        item
                    )
                else:
                    errors += 1

            except Exception:
                errors += 1

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    strong = [
        x for x in analyzed
        if x["state"] == "STRONG"
    ]

    early = [
        x for x in analyzed
        if x["state"] == "EARLY"
    ]

    watch = [
        x for x in analyzed
        if x["state"] == "WATCH"
    ]

    filtered = [
        x for x in analyzed
        if x["state"] == "FILTERED"
    ]

    def rank_key(item):

        return (
            item["score"],
            item["m15"],
            item["m1h"],
            item["breakout"],
            item["volume"]
        )

    strong.sort(
        key=rank_key,
        reverse=True
    )

    early.sort(
        key=rank_key,
        reverse=True
    )

    watch.sort(
        key=rank_key,
        reverse=True
    )

    # Strong -> Early -> Watch
    top = (
        strong
        + early
        + watch
    )[:TOP_RESULTS]

    elapsed = (
        time.time()
        - start_time
    )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    telegram_send(
        f"📊 STRATEGY RESULT {VERSION}\n\n"
        f"🟢 MARKETS: {len(symbols)}\n"
        f"🔎 CHECKED: {len(scan_symbols)}\n"
        f"📈 ANALYZED: {len(analyzed)}\n"
        f"❌ API ERRORS: {errors}\n\n"
        f"🟢 STRONG: {len(strong)}\n"
        f"🟡 EARLY: {len(early)}\n"
        f"⚪ WATCH: {len(watch)}\n"
        f"❌ FILTERED: {len(filtered)}\n"
        f"⏱ TIME: {elapsed:.1f}s\n\n"
        f"📐 STRATEGY:\n"
        f"BOS → BREAKOUT → PULLBACK → CONTINUATION\n\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 NO ORDER WAS SENT\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # TOP 10
    # --------------------------------------------------------

    if top:

        message = (
            f"🏆 ATI TOP {TOP_RESULTS} "
            f"{VERSION}\n\n"
            f"📐 ONE STRATEGY:\n"
            f"BOS → BREAKOUT → PULLBACK "
            f"→ CONTINUATION\n\n"
        )

        for index, item in enumerate(
            top,
            start=1
        ):

            message += (
                format_result(
                    index,
                    item
                )
                + "\n\n"
            )

        telegram_long(
            message.rstrip()
        )

    else:

        telegram_send(
            f"🏆 ATI TOP {TOP_RESULTS} "
            f"{VERSION}\n\n"
            f"❌ NO CANDIDATE FOUND\n\n"
            f"📐 Strategy:\n"
            f"BOS → BREAKOUT → PULLBACK "
            f"→ CONTINUATION\n\n"
            f"🔒 REAL BUY: DISABLED\n"
            f"🛑 SCANNER ONLY\n"
            f"🕐 {utc_now()}"
        )

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    telegram_send(
        f"✅ ATI {VERSION} COMPLETE\n"
        f"📊 CHECKED: {len(scan_symbols)}\n"
        f"📈 ANALYZED: {len(analyzed)}\n"
        f"🟢 STRONG: {len(strong)}\n"
        f"🟡 EARLY: {len(early)}\n"
        f"⚪ WATCH: {len(watch)}\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 NO ORDER WAS SENT\n"
        f"🕐 {utc_now()}"
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
