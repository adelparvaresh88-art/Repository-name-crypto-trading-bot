import os
import time
import json
import hmac
import hashlib
import math
from decimal import Decimal, ROUND_DOWN, InvalidOperation
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.36
# SMART 5M LOGIC - STRONG BULLISH CONFIRMATION
# TABDIL AUTH
# SCANNER ONLY
# REAL ORDERS PERMANENTLY DISABLED
# ============================================================

VERSION = "V40.2.36"

BASE_URL = "https://api1.tabdeal.org"

# ------------------------------------------------------------
# SAFETY LOCK
# ------------------------------------------------------------
REAL_ORDERS = False
BUY_LOCK = True

# ------------------------------------------------------------
# SCANNER SETTINGS
# ------------------------------------------------------------
SCAN_UNIVERSE = 40
TOP_RESULTS = 10
TIMEFRAME_MINUTES = 5

MIN_CANDLES = 13
TRADE_LIMIT = 1000

REQUEST_TIMEOUT = 12
MAX_WORKERS = 8

# ------------------------------------------------------------
# SIGNAL SETTINGS
# ------------------------------------------------------------
STRONG_MIN_SCORE = 14
EARLY_MIN_SCORE = 10
WATCH_MIN_SCORE = 7

MIN_STRONG_BODY = 50.0
MIN_EARLY_BODY = 35.0

MIN_ACCEPTABLE_VOLUME = 0.70
STRONG_VOLUME = 1.50

MAX_CHASE = 1.50

# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# ------------------------------------------------------------
# API CREDENTIALS
# TABDIL is the verified working pair
# ------------------------------------------------------------
API_KEY = os.getenv("TABDIL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDIL_API_SECRET", "").strip()

# Optional fallback only if TABDIL names are absent.
if not API_KEY:
    API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()

if not API_SECRET:
    API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()


session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-Crypto-Bot/" + VERSION
})


# ============================================================
# HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = (
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage"
        )

        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "disable_web_page_preview": True,
        }

        response = requests.post(
            url,
            json=payload,
            timeout=15
        )

        return response.ok

    except Exception:
        return False


def send_long_telegram(message):
    """
    Telegram message limit protection.
    """
    max_len = 3900

    if len(message) <= max_len:
        telegram_send(message)
        return

    parts = []

    while message:
        parts.append(message[:max_len])
        message = message[max_len:]

    for part in parts:
        telegram_send(part)
        time.sleep(0.4)


# ============================================================
# API
# ============================================================

def get_server_time():
    url = f"{BASE_URL}/r/api/v1/time"

    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        for key in (
            "serverTime",
            "timestamp",
            "time",
            "data"
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

    if isinstance(data, (int, float)):
        return int(data)

    raise RuntimeError("SERVER_TIME_NOT_FOUND")


def signed_get(path, extra_params=None):
    """
    Tabdil/Tabdeal signed GET.

    Signature:
        timestamp=<server>&recvWindow=5000

    HMAC-SHA256
    """

    if not API_KEY or not API_SECRET:
        raise RuntimeError("API_CREDENTIALS_MISSING")

    server_timestamp = get_server_time()

    params = {}

    if extra_params:
        params.update(extra_params)

    params["timestamp"] = int(server_timestamp)
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

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = f"{BASE_URL}{path}"

    response = session.get(
        url,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT
    )

    if response.status_code == 401:
        raise RuntimeError(
            f"AUTH_401:{response.text[:250]}"
        )

    response.raise_for_status()

    return response.json()


def auth_test():
    data = signed_get(
        "/r/api/v1/account"
    )

    if isinstance(data, dict):
        code = data.get("code")

        if code not in (None, 0, "0"):
            raise RuntimeError(
                f"ACCOUNT_CODE:{code}"
            )

    return True


def get_exchange_info():
    url = f"{BASE_URL}/r/api/v1/exchangeInfo"

    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# EXCHANGE INFO PARSER
# ============================================================

def extract_symbols(exchange_data):
    symbols = []

    if isinstance(exchange_data, list):
        raw = exchange_data

    elif isinstance(exchange_data, dict):
        raw = None

        for key in (
            "symbols",
            "data",
            "result",
            "items"
        ):
            value = exchange_data.get(key)

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
                    subvalue = value.get(subkey)
                    if isinstance(subvalue, list):
                        raw = subvalue
                        break

                if raw is not None:
                    break

        if raw is None:
            raw = []

    else:
        raw = []

    for item in raw:
        if isinstance(item, str):
            symbol = item.upper()

            if symbol.endswith("USDT"):
                symbols.append(symbol)

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

        symbol = str(symbol).upper()

        status = str(
            item.get("status", "TRADING")
        ).upper()

        quote = str(
            item.get("quoteAsset")
            or item.get("quote")
            or ""
        ).upper()

        if (
            symbol.endswith("USDT")
            and status not in (
                "BREAK",
                "HALT",
                "STOPPED",
                "DISABLED"
            )
        ):
            if not quote or quote == "USDT":
                symbols.append(symbol)

    # unique
    result = []

    seen = set()

    for symbol in symbols:
        if symbol not in seen:
            seen.add(symbol)
            result.append(symbol)

    return result


# ============================================================
# TRADES API
# ============================================================

def parse_trade_list(data):
    """
    Supports:
      list
      {data: [...]}
      {trades: [...]}
      {result: [...]}
      {items: [...]}
      nested forms
    """

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
            nested = parse_trade_list(value)

            if nested:
                return nested

    return []


def get_recent_trades(symbol):
    """
    V40.2.34-compatible endpoint fallback.
    """

    attempts = [
        {"tabdealSymbol": symbol},
        {"symbol": symbol},
        {"market": symbol},
        {"tabdeal_symbol": symbol},
    ]

    last_error = None

    for extra in attempts:
        try:
            params = dict(extra)
            params["limit"] = TRADE_LIMIT

            url = f"{BASE_URL}/r/api/v1/trades"

            response = session.get(
                url,
                params=params,
                timeout=REQUEST_TIMEOUT
            )

            if response.status_code != 200:
                last_error = (
                    f"HTTP_{response.status_code}"
                )
                continue

            data = response.json()

            trades = parse_trade_list(data)

            if trades:
                return trades

        except Exception as exc:
            last_error = str(exc)

    raise RuntimeError(
        f"TRADE_API_ERROR:{last_error}"
    )


# ============================================================
# TRADE PARSER
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
            value = safe_float(item[key])

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
            value = safe_float(item[key])

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

        value = item[key]

        try:
            value = float(value)

            if value < 10000000000:
                value *= 1000

            return int(value)

        except Exception:
            continue

    return None


# ============================================================
# CANDLE BUILDER
# ============================================================

def build_5m_candles(trades):
    buckets = {}

    for item in trades:
        price = trade_price(item)
        qty = trade_quantity(item)
        timestamp = trade_time(item)

        if price <= 0 or timestamp is None:
            continue

        # 5 minute bucket
        bucket = (
            timestamp // (5 * 60 * 1000)
        ) * (5 * 60 * 1000)

        if bucket not in buckets:
            buckets[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
                "quote_volume": 0.0,
                "time": bucket,
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

        candle["volume"] += qty

        candle["quote_volume"] += (
            price * qty
        )

    candles = [
        buckets[key]
        for key in sorted(buckets)
    ]

    # Current/open candle must NOT be used.
    now_ms = int(time.time() * 1000)

    current_bucket = (
        now_ms // (5 * 60 * 1000)
    ) * (5 * 60 * 1000)

    candles = [
        c for c in candles
        if c["time"] < current_bucket
    ]

    return candles


# ============================================================
# CANDLE METRICS
# ============================================================

def candle_body_percent(candle):
    high = candle["high"]
    low = candle["low"]
    open_price = candle["open"]
    close_price = candle["close"]

    candle_range = high - low

    if candle_range <= 0:
        return 0.0

    return (
        abs(close_price - open_price)
        / candle_range
    ) * 100.0


def is_bullish(candle):
    return candle["close"] > candle["open"]


def is_bearish(candle):
    return candle["close"] < candle["open"]


def average_volume(candles, count=10):
    if not candles:
        return 0.0

    values = [
        safe_float(c["volume"])
        for c in candles[-count:]
    ]

    if not values:
        return 0.0

    return sum(values) / len(values)


def volume_ratio(candles):
    if len(candles) < 2:
        return 0.0

    current = safe_float(
        candles[-1]["volume"]
    )

    previous = candles[:-1][-10:]

    if not previous:
        return 0.0

    avg = average_volume(previous, 10)

    if avg <= 0:
        return 0.0

    return current / avg


def percent_change(old, new):
    if old <= 0:
        return 0.0

    return (
        (new - old)
        / old
    ) * 100.0


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


def resistance_level(candles):
    """
    Previous 12 closed candles.
    Current breakout candle is excluded.
    """

    if len(candles) < 13:
        return None

    previous = candles[-13:-1]

    if not previous:
        return None

    return max(
        c["high"]
        for c in previous
    )


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_symbol(symbol):
    result = {
        "symbol": symbol,
        "ok": False,
        "score": 0,
        "state": "ERROR",
        "price": 0.0,
        "breakout": 0.0,
        "volume": 0.0,
        "body": 0.0,
        "m5": 0.0,
        "m15": 0.0,
        "m1h": 0.0,
        "reason": "UNKNOWN",
        "candles": 0,
    }

    try:
        trades = get_recent_trades(symbol)

        candles = build_5m_candles(trades)

        result["candles"] = len(candles)

        if len(candles) < MIN_CANDLES:
            result["reason"] = "NOT_ENOUGH_CANDLES"
            return result

        last = candles[-1]

        price = safe_float(last["close"])

        if price <= 0:
            result["reason"] = "INVALID_PRICE"
            return result

        resistance = resistance_level(candles)

        if resistance is None or resistance <= 0:
            result["reason"] = "NO_RESISTANCE"
            return result

        breakout = (
            (price - resistance)
            / resistance
        ) * 100.0

        vol = volume_ratio(candles)

        body = candle_body_percent(last)

        m5 = momentum_5m(candles)
        m15 = momentum_15m(candles)
        m1h = momentum_1h(candles)

        bullish = is_bullish(last)
        bearish = is_bearish(last)

        score = 0
        reasons = []

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        if breakout >= 0:
            score += 4
        elif breakout >= -0.50:
            score += 2
            reasons.append("NEAR_RESISTANCE")
        else:
            reasons.append("BELOW_RESISTANCE")

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        if vol >= 1.50:
            score += 2
        elif vol >= 0.70:
            score += 1
        else:
            reasons.append("LOW_VOLUME")

        # ----------------------------------------------------
        # CANDLE DIRECTION
        # IMPORTANT V40.2.36
        # ----------------------------------------------------

        if bullish:
            score += 3
        else:
            score -= 2
            reasons.append("RED_CANDLE")

        # ----------------------------------------------------
        # CANDLE BODY
        # ----------------------------------------------------

        if body >= 60:
            score += 2
        elif body >= 35:
            score += 1
        else:
            reasons.append("WEAK_BODY")

        # ----------------------------------------------------
        # 5M MOMENTUM
        # ----------------------------------------------------

        if m5 > 0:
            score += 2

            if m5 >= 0.30:
                score += 1
        else:
            reasons.append("5M_NOT_UP")

        # ----------------------------------------------------
        # 15M MOMENTUM
        # ----------------------------------------------------

        if m15 > 0:
            score += 3

            if m15 >= 1.00:
                score += 1
        else:
            reasons.append("15M_NOT_UP")

        # ----------------------------------------------------
        # 1H MOMENTUM
        # ----------------------------------------------------

        if m1h > 0:
            score += 2

            if m1h >= 2.00:
                score += 1
        else:
            reasons.append("1H_NOT_UP")

        # ----------------------------------------------------
        # NEGATIVE MOMENTUM PENALTIES
        # ----------------------------------------------------

        if m15 < -0.50:
            score -= 2
            reasons.append("15M_WEAK")

        if m1h < -1.00:
            score -= 2
            reasons.append("1H_WEAK")

        # ----------------------------------------------------
        # CHASE PROTECTION
        # ----------------------------------------------------

        chasing = breakout > MAX_CHASE

        if chasing:
            score -= 3
            reasons.append("CHASE")

        score = int(
            clamp(score, 0, 20)
        )

        # ----------------------------------------------------
        # HARD QUALITY GATES
        # ----------------------------------------------------

        # A red candle can NEVER be STRONG/EARLY.
        if not bullish:
            state = "WATCH"

        # Body below 35% can NEVER be STRONG/EARLY.
        elif body < MIN_EARLY_BODY:
            state = "WATCH"

        # Negative 5m / 15m / 1h prevents entry classification.
        elif m5 <= 0 or m15 <= 0 or m1h <= 0:
            state = "WATCH"

        # Chase protection.
        elif chasing:
            state = "WATCH"

        # ----------------------------------------------------
        # STRONG
        # ----------------------------------------------------

        elif (
            breakout >= 0
            and bullish
            and body >= MIN_STRONG_BODY
            and vol >= STRONG_VOLUME
            and m5 > 0
            and m15 > 0
            and m1h > 0
            and score >= STRONG_MIN_SCORE
        ):
            state = "STRONG"

        # ----------------------------------------------------
        # EARLY WATCH
        # ----------------------------------------------------

        elif (
            breakout >= -0.20
            and bullish
            and body >= MIN_EARLY_BODY
            and vol >= MIN_ACCEPTABLE_VOLUME
            and m5 > 0
            and m15 > 0
            and m1h > 0
            and score >= EARLY_MIN_SCORE
        ):
            state = "EARLY"

        # ----------------------------------------------------
        # WATCH
        # ----------------------------------------------------

        elif (
            score >= WATCH_MIN_SCORE
            and m15 > 0
            and m1h > 0
        ):
            state = "WATCH"

        else:
            state = "FILTERED"

        result.update({
            "ok": True,
            "score": score,
            "state": state,
            "price": price,
            "breakout": breakout,
            "volume": vol,
            "body": body,
            "m5": m5,
            "m15": m15,
            "m1h": m1h,
            "reason": ",".join(reasons) if reasons else "OK",
        })

        return result

    except Exception as exc:
        result["reason"] = str(exc)[:180]
        return result


# ============================================================
# DISPLAY
# ============================================================

def format_result(index, item):
    state = item["state"]

    if state == "STRONG":
        icon = "🟢"
        label = "STRONG"
    elif state == "EARLY":
        icon = "🟡"
        label = "EARLY WATCH"
    else:
        icon = "⚪"
        label = "WATCH"

    reasons = item["reason"]

    if not reasons:
        reasons = "OK"

    return (
        f"{index}. {item['symbol']} {icon} {label}\n"
        f"Score: {item['score']}/20\n"
        f"Price: {item['price']:.10g}\n"
        f"Breakout: {item['breakout']:+.2f}%\n"
        f"Volume: {item['volume']:.2f}x\n"
        f"Body: {item['body']:.0f}%\n"
        f"5m: {item['m5']:+.2f}% | "
        f"15m: {item['m15']:+.2f}% | "
        f"1h: {item['m1h']:+.2f}%\n"
        f"State: {reasons}"
    )


# ============================================================
# MAIN SCAN
# ============================================================

def main():
    start_time = time.time()

    telegram_send(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🧠 SMART 5M LOGIC V2\n"
        f"🕯 CLOSED CANDLE ONLY\n"
        f"🟢 BULLISH CANDLE CONFIRMATION\n"
        f"📊 BODY FILTER: ≥35% EARLY / ≥50% STRONG\n"
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
        exchange_data = get_exchange_info()

        symbols = extract_symbols(
            exchange_data
        )

        telegram_send(
            f"📊 EXCHANGE INFO OK {VERSION}\n"
            f"🟢 USDT MARKETS: {len(symbols)}\n"
            f"🔎 SMART SCAN STARTING...\n"
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
            f"🛑 SCAN STOPPED\n"
            f"🔒 REAL ORDERS: DISABLED"
        )
        return

    # --------------------------------------------------------
    # SCAN UNIVERSE
    # --------------------------------------------------------

    scan_symbols = symbols[:SCAN_UNIVERSE]

    analyzed = []
    api_errors = 0

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

        for future in as_completed(futures):
            try:
                item = future.result()

                if item["ok"]:
                    analyzed.append(item)
                else:
                    api_errors += 1

            except Exception:
                api_errors += 1

    # --------------------------------------------------------
    # CLASSIFICATION
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

    # Strong first, then Early, then Watch.
    strong.sort(
        key=lambda x: (
            x["score"],
            x["breakout"],
            x["volume"]
        ),
        reverse=True
    )

    early.sort(
        key=lambda x: (
            x["score"],
            x["breakout"],
            x["volume"]
        ),
        reverse=True
    )

    watch.sort(
        key=lambda x: (
            x["score"],
            x["m15"],
            x["m1h"]
        ),
        reverse=True
    )

    top = (
        strong
        + early
        + watch
    )[:TOP_RESULTS]

    elapsed = time.time() - start_time

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    telegram_send(
        f"📊 SMART SCAN RESULT {VERSION}\n\n"
        f"🟢 MARKETS: {len(symbols)}\n"
        f"🔎 CHECKED: {len(scan_symbols)}\n"
        f"📈 ANALYZED: {len(analyzed)}\n"
        f"❌ API/TRADE ERRORS: {api_errors}\n\n"
        f"🟢 STRONG: {len(strong)}\n"
        f"🟡 EARLY: {len(early)}\n"
        f"⚪ WATCH: {len(watch)}\n"
        f"❌ FILTERED: {len(filtered)}\n"
        f"⏱ TIME: {elapsed:.1f}s\n\n"
        f"🔒 REAL ORDERS: DISABLED\n"
        f"🛑 NO ORDER WAS SENT\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # TOP RESULTS
    # --------------------------------------------------------

    if top:
        message = (
            f"🎯 ATI SMART TOP {TOP_RESULTS} {VERSION}\n\n"
            f"🧠 NEW RULE:\n"
            f"🔴 RED CANDLE CANNOT BE STRONG/EARLY\n"
            f"📏 BODY <35% CANNOT BE STRONG/EARLY\n"
            f"📈 5m/15m/1h MUST BE POSITIVE\n"
            f"🔊 STRONG VOLUME ≥1.50x\n\n"
        )

        for index, item in enumerate(
            top,
            start=1
        ):
            message += (
                format_result(index, item)
                + "\n\n"
            )

        send_long_telegram(
            message.rstrip()
        )

    else:
        telegram_send(
            f"🎯 ATI SMART TOP {TOP_RESULTS} {VERSION}\n\n"
            f"❌ NO QUALITY CANDIDATE\n\n"
            f"Reason:\n"
            f"🔴 Weak/red candles rejected\n"
            f"📏 Weak body rejected\n"
            f"📉 Negative momentum rejected\n"
            f"🔊 Weak volume cannot become STRONG\n\n"
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


if __name__ == "__main__":
    main()
