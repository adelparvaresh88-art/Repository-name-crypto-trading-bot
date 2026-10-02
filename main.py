import os
import time
import hmac
import hashlib
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.40
# AL BROOKS PRICE ACTION - FINAL
# ============================================================
#
# FINAL LOGIC:
#
# Trend
#   ↓
# REAL BOS
#   ↓
# Pullback
#   ↓
# Continuation
#   ↓
# CLOSED 5M CONFIRMATION
#   ↓
# BUY READY
#
# Signal Bar is still used as an extra confirmation,
# but EARLY no longer waits for a perfect Signal Bar.
#
# NO EMA
# NO RSI
# NO MACD
# NO OPEN-CANDLE SIGNAL
#
# REAL ORDERS DISABLED
# BUY LOCK ACTIVE
#
# ============================================================

VERSION = "V40.2.40"

BASE_URL = "https://api1.tabdeal.org"

REAL_ORDERS = False
BUY_LOCK = True

SCAN_UNIVERSE = 40
TOP_RESULTS = 10

TRADE_LIMIT = 1000
MIN_CANDLES = 30

REQUEST_TIMEOUT = 12
MAX_WORKERS = 8

TREND_LOOKBACK = 12
RESISTANCE_LOOKBACK = 12
PULLBACK_LOOKBACK = 5

# ============================================================
# BREAKOUT
# ============================================================

REAL_BOS_MIN = 0.05

NEAR_BOS_MIN = -0.25

PULLBACK_TOLERANCE = 0.80

CHASE_LIMIT = 2.20

# ============================================================
# FINAL CLOSED-CANDLE CONFIRMATION
# ============================================================
#
# This is intentionally lighter than a perfect Signal Bar.
#
# It requires:
# - closed candle
# - positive 5m movement
# - close above previous close
# - reasonable close position
#
# This prevents waiting too long for a textbook signal bar.
# ============================================================

MIN_CONFIRM_CLOSE_POSITION = 0.55

TELEGRAM_TIMEOUT = 15


# ============================================================
# ENV
# ============================================================

API_KEY = (
    os.getenv("TABDIL_API_KEY", "").strip()
    or os.getenv("TABDEAL_API_KEY", "").strip()
)

API_SECRET = (
    os.getenv("TABDIL_API_SECRET", "").strip()
    or os.getenv("TABDEAL_API_SECRET", "").strip()
)

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": f"ATI-Crypto-Bot-{VERSION}",
    "Accept": "application/json",
})


# ============================================================
# BASIC HELPERS
# ============================================================

def now_utc():
    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def pct(a, b):
    if not b:
        return 0.0

    return ((a - b) / b) * 100.0


def fmt_pct(value):
    return f"{value:+.2f}%"


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:

        print("TELEGRAM: credentials missing")

        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:

        response = SESSION.post(
            url,
            json=payload,
            timeout=TELEGRAM_TIMEOUT,
        )

        if response.status_code == 200:

            return True

        print(
            "TELEGRAM ERROR:",
            response.status_code,
            response.text[:300],
        )

        return False

    except Exception as exc:

        print(
            "TELEGRAM EXCEPTION:",
            str(exc),
        )

        return False


# ============================================================
# PUBLIC API
# ============================================================

def public_get(path, params=None):

    url = f"{BASE_URL}{path}"

    try:

        response = SESSION.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:

            return (
                None,
                f"HTTP {response.status_code}: "
                f"{response.text[:200]}",
            )

        try:

            return response.json(), None

        except Exception:

            return None, "Invalid JSON"

    except Exception as exc:

        return None, str(exc)


# ============================================================
# SERVER TIME
# ============================================================

def get_server_time():

    data, error = public_get(
        "/r/api/v1/time"
    )

    if error:

        return int(
            time.time() * 1000
        )

    if isinstance(data, dict):

        for key in (
            "serverTime",
            "timestamp",
            "time",
            "data",
        ):

            if key not in data:
                continue

            value = data[key]

            if isinstance(value, dict):

                for subkey in (
                    "serverTime",
                    "timestamp",
                    "time",
                ):

                    if subkey in value:

                        value = value[subkey]

                        break

            try:

                return int(value)

            except Exception:

                pass

    return int(
        time.time() * 1000
    )


# ============================================================
# HMAC AUTH
# ============================================================

def signed_get(path, extra_params=None):

    if not API_KEY or not API_SECRET:

        return None, "API credentials missing"

    timestamp = get_server_time()

    recv_window = 5000

    params = {
        "timestamp": int(timestamp),
        "recvWindow": recv_window,
    }

    if extra_params:

        params.update(
            extra_params
        )

    # IMPORTANT:
    # Keep the same signing format that was working
    # in V40.2.39.
    sign_query = (
        f"timestamp={int(timestamp)}"
        f"&recvWindow={int(recv_window)}"
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        sign_query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    url = f"{BASE_URL}{path}"

    try:

        response = SESSION.get(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:

            return (
                None,
                f"HTTP {response.status_code}: "
                f"{response.text[:300]}",
            )

        try:

            return response.json(), None

        except Exception:

            return None, "Invalid JSON response"

    except Exception as exc:

        return None, str(exc)


# ============================================================
# AUTH TEST
# ============================================================

def auth_test():

    print("AUTH TEST: STARTING")

    data, error = signed_get(
        "/r/api/v1/account"
    )

    if error:

        print(
            "AUTH FAILED:",
            error,
        )

        send_telegram(
            f"🚨 ATI API AUTH FAILED {VERSION}\n\n"
            f"❌ {error}\n\n"
            f"🔐 HMAC-SHA256\n"
            f"🔢 SERVER TIMESTAMP\n"
            f"🛑 REAL BUY LOCKED\n"
            f"🕐 {now_utc()}"
        )

        return False

    if data is None:

        return False

    print("AUTH TEST: OK")

    return True


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    data, error = public_get(
        "/r/api/v1/exchangeInfo"
    )

    if error:

        print(
            "EXCHANGE INFO ERROR:",
            error,
        )

        return []

    if isinstance(data, list):

        raw = data

    elif isinstance(data, dict):

        raw = (
            data.get("symbols")
            or data.get("data")
            or data.get("markets")
            or []
        )

        if isinstance(raw, dict):

            raw = (
                raw.get("symbols")
                or raw.get("markets")
                or []
            )

    else:

        raw = []

    markets = []

    for item in raw:

        if not isinstance(item, dict):

            continue

        symbol = (
            item.get("symbol")
            or item.get("market")
            or item.get("name")
            or item.get("tabdealSymbol")
            or item.get("tabdeal_symbol")
        )

        if not symbol:

            continue

        symbol = str(
            symbol
        ).upper()

        if not symbol.endswith("USDT"):

            continue

        if any(
            x in symbol
            for x in (
                "UPUSDT",
                "DOWNUSDT",
                "BULLUSDT",
                "BEARUSDT",
            )
        ):

            continue

        markets.append({
            "symbol": symbol,
            "raw": item,
        })

    unique = {}

    for market in markets:

        unique[
            market["symbol"]
        ] = market

    return list(
        unique.values()
    )


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):

        return None

    price = None
    quantity = None
    timestamp = None

    for key in (
        "price",
        "p",
        "tradePrice",
        "lastPrice",
    ):

        if key in item:

            price = safe_float(
                item[key]
            )

            break

    for key in (
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
        "baseQty",
    ):

        if key in item:

            quantity = safe_float(
                item[key]
            )

            break

    for key in (
        "time",
        "timestamp",
        "T",
        "tradeTime",
        "createdAt",
    ):

        if key in item:

            try:

                timestamp = int(
                    float(item[key])
                )

            except Exception:

                timestamp = None

            break

    if price is None or price <= 0:

        return None

    if quantity is None or quantity <= 0:

        quantity = 1.0

    if timestamp is None:

        return None

    if timestamp < 10_000_000_000:

        timestamp *= 1000

    return {
        "price": price,
        "qty": quantity,
        "time": timestamp,
    }


# ============================================================
# GET TRADES
# ============================================================

def get_trades(symbol):

    attempts = [
        {
            "tabdealSymbol": symbol,
            "limit": TRADE_LIMIT,
        },
        {
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
        {
            "market": symbol,
            "limit": TRADE_LIMIT,
        },
        {
            "tabdeal_symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    ]

    for params in attempts:

        data, error = public_get(
            "/r/api/v1/trades",
            params,
        )

        if error:

            continue

        raw = data

        if isinstance(data, dict):

            raw = (
                data.get("data")
                or data.get("trades")
                or data.get("result")
                or []
            )

        if not isinstance(raw, list):

            continue

        trades = []

        for item in raw:

            parsed = parse_trade(
                item
            )

            if parsed:

                trades.append(
                    parsed
                )

        if trades:

            trades.sort(
                key=lambda x: x["time"]
            )

            return trades

    return []


# ============================================================
# BUILD CLOSED 5M CANDLES
# ============================================================

def build_5m_candles(trades):

    buckets = {}

    for trade in trades:

        timestamp = trade["time"]

        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
                "trades": 0,
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

        candle["close"] = trade["price"]

        candle["volume"] += (
            trade["qty"]
            * trade["price"]
        )

        candle["trades"] += 1

    candles = sorted(
        buckets.values(),
        key=lambda x: x["time"],
    )

    # ========================================================
    # IMPORTANT:
    # REMOVE CURRENT UNFINISHED 5M CANDLE
    # ========================================================

    if candles:

        current_bucket = (
            int(time.time() * 1000)
            // 300000
        ) * 300000

        candles = [
            candle
            for candle in candles
            if candle["time"]
            < current_bucket
        ]

    return candles


# ============================================================
# CANDLE / PRICE ACTION
# ============================================================

def candle_range(candle):

    return max(
        candle["high"]
        - candle["low"],
        1e-12,
    )


def candle_position(candle):

    rng = candle_range(
        candle
    )

    return (
        (
            candle["close"]
            - candle["low"]
        )
        / rng
    )


# ============================================================
# BROOKS SIGNAL BAR
# ============================================================

def is_bull_signal_bar(candle):

    rng = candle_range(
        candle
    )

    close_from_high = (
        candle["high"]
        - candle["close"]
    ) / rng

    close_position = candle_position(
        candle
    )

    return (
        close_position >= 0.65
        and close_from_high <= 0.35
    )


# ============================================================
# FINAL CLOSED CANDLE CONFIRMATION
# ============================================================

def closed_candle_confirmation(
    current,
    previous,
):

    current_position = candle_position(
        current
    )

    close_up = (
        current["close"]
        > previous["close"]
    )

    m5_positive = (
        pct(
            current["close"],
            previous["close"],
        ) > 0
    )

    reasonable_close = (
        current_position
        >= MIN_CONFIRM_CLOSE_POSITION
    )

    return (
        close_up
        and m5_positive
        and reasonable_close
    )


# ============================================================
# SWINGS
# ============================================================

def swing_highs(candles):

    result = []

    if len(candles) < 5:

        return result

    for i in range(
        2,
        len(candles) - 2,
    ):

        high = candles[i]["high"]

        if (
            high >= candles[i - 1]["high"]
            and high >= candles[i - 2]["high"]
            and high >= candles[i + 1]["high"]
            and high >= candles[i + 2]["high"]
        ):

            result.append({
                "index": i,
                "price": high,
            })

    return result


def swing_lows(candles):

    result = []

    if len(candles) < 5:

        return result

    for i in range(
        2,
        len(candles) - 2,
    ):

        low = candles[i]["low"]

        if (
            low <= candles[i - 1]["low"]
            and low <= candles[i - 2]["low"]
            and low <= candles[i + 1]["low"]
            and low <= candles[i + 2]["low"]
        ):

            result.append({
                "index": i,
                "price": low,
            })

    return result


# ============================================================
# TREND
# ============================================================

def detect_trend(candles):

    if len(candles) < 15:

        return "UNKNOWN"

    section = candles[
        -TREND_LOOKBACK:
    ]

    highs = swing_highs(
        section
    )

    lows = swing_lows(
        section
    )

    if (
        len(highs) >= 2
        and len(lows) >= 2
    ):

        previous_high = highs[-2]["price"]
        latest_high = highs[-1]["price"]

        previous_low = lows[-2]["price"]
        latest_low = lows[-1]["price"]

        if (
            latest_high > previous_high
            and latest_low > previous_low
        ):

            return "UP"

        if (
            latest_high < previous_high
            and latest_low < previous_low
        ):

            return "DOWN"

        return "RANGE"

    closes = [
        candle["close"]
        for candle in candles[-8:]
    ]

    if closes[-1] > closes[0]:

        return "UP"

    if closes[-1] < closes[0]:

        return "DOWN"

    return "RANGE"


# ============================================================
# RESISTANCE / SUPPORT
# ============================================================

def resistance_level(candles):

    if len(candles) < (
        RESISTANCE_LOOKBACK + 2
    ):

        return None

    section = candles[
        -(RESISTANCE_LOOKBACK + 1):-1
    ]

    highs = [
        candle["high"]
        for candle in section
    ]

    if not highs:

        return None

    return max(highs)


def support_level(candles):

    if len(candles) < (
        RESISTANCE_LOOKBACK + 2
    ):

        return None

    section = candles[
        -(RESISTANCE_LOOKBACK + 1):-1
    ]

    lows = [
        candle["low"]
        for candle in section
    ]

    if not lows:

        return None

    return min(lows)


# ============================================================
# AL BROOKS SETUP
# ============================================================

def analyze_price_action(
    symbol,
    candles,
):

    if len(candles) < MIN_CANDLES:

        return None

    # IMPORTANT:
    # candles[-1] is already CLOSED because
    # build_5m_candles removes the current candle.
    current = candles[-1]
    previous = candles[-2]

    close = current["close"]

    resistance = resistance_level(
        candles
    )

    support = support_level(
        candles
    )

    if (
        resistance is None
        or support is None
    ):

        return None

    trend = detect_trend(
        candles
    )

    # ========================================================
    # MOMENTUM
    # ========================================================

    m5 = pct(
        current["close"],
        previous["close"],
    )

    if len(candles) >= 4:

        m15 = pct(
            current["close"],
            candles[-4]["close"],
        )

    else:

        m15 = 0.0

    if len(candles) >= 13:

        m1h = pct(
            current["close"],
            candles[-13]["close"],
        )

    else:

        m1h = 0.0

    # ========================================================
    # REAL BOS
    # ========================================================

    breakout_pct = pct(
        close,
        resistance,
    )

    real_bos = (
        breakout_pct
        >= REAL_BOS_MIN
    )

    near_bos = (
        breakout_pct
        >= NEAR_BOS_MIN
    )

    previous_breakout_pct = pct(
        previous["close"],
        resistance,
    )

    previous_real_bos = (
        previous_breakout_pct
        >= REAL_BOS_MIN
    )

    breakout_detected = (
        real_bos
        or previous_real_bos
    )

    # ========================================================
    # PULLBACK
    # ========================================================

    pullback_touched = False
    pullback_distance = 999.0

    start = max(
        1,
        len(candles)
        - PULLBACK_LOOKBACK
        - 1,
    )

    for index in range(
        start,
        len(candles) - 1,
    ):

        candle = candles[index]

        distance = abs(
            pct(
                candle["low"],
                resistance,
            )
        )

        if (
            distance
            <= PULLBACK_TOLERANCE
        ):

            pullback_touched = True

            pullback_distance = min(
                pullback_distance,
                distance,
            )

    # ========================================================
    # CONTINUATION
    # ========================================================

    continuation = (
        close >= resistance
        and m5 > 0
    )

    # ========================================================
    # SIGNAL BAR
    # ========================================================

    current_signal = (
        is_bull_signal_bar(
            current
        )
    )

    previous_signal = (
        is_bull_signal_bar(
            previous
        )
    )

    signal_bar = (
        current_signal
        or previous_signal
    )

    # ========================================================
    # FINAL CLOSED-CANDLE CONFIRMATION
    # ========================================================

    closed_confirm = (
        closed_candle_confirmation(
            current,
            previous,
        )
    )

    # ========================================================
    # FINAL BUY-READY STRUCTURE
    # ========================================================
    #
    # This is the important V40.2.40 change.
    #
    # We DO NOT require a textbook Signal Bar.
    #
    # We DO require:
    #
    # UP/RANGE
    # REAL BOS
    # PULLBACK
    # CONTINUATION
    # CLOSED CANDLE CONFIRMATION
    #
    # ========================================================

    buy_ready_structure = (
        trend in (
            "UP",
            "RANGE",
        )
        and breakout_detected
        and pullback_touched
        and continuation
        and closed_confirm
    )

    # ========================================================
    # FAILED BREAKOUT
    # ========================================================

    failed_breakout = (
        (
            previous["high"]
            > resistance
        )
        and (
            previous["close"]
            < resistance
        )
        and (
            close
            < resistance
        )
    )

    # ========================================================
    # CHASE
    # ========================================================

    chase = (
        breakout_pct
        > CHASE_LIMIT
    )

    # ========================================================
    # VOLUME
    # ========================================================

    previous_volumes = [
        candle["volume"]
        for candle in candles[-11:-1]
        if candle["volume"] > 0
    ]

    if previous_volumes:

        avg_volume = (
            sum(previous_volumes)
            / len(previous_volumes)
        )

        volume_ratio = (
            current["volume"]
            / avg_volume
            if avg_volume > 0
            else 0.0
        )

    else:

        volume_ratio = 0.0

    # ========================================================
    # SCORE
    # ========================================================

    score = 0

    reasons = []

    if trend == "UP":

        score += 4

        reasons.append(
            "UP_TREND"
        )

    elif trend == "RANGE":

        score += 1

        reasons.append(
            "TRADING_RANGE"
        )

    if m15 > 0:

        score += 2

        reasons.append(
            "15M_UP"
        )

    if m1h > 0:

        score += 2

        reasons.append(
            "1H_UP"
        )

    if real_bos:

        score += 4

        reasons.append(
            "REAL_BOS"
        )

    elif previous_real_bos:

        score += 4

        reasons.append(
            "PREVIOUS_REAL_BOS"
        )

    elif near_bos:

        score += 1

        reasons.append(
            "NEAR_BOS"
        )

    if pullback_touched:

        score += 3

        reasons.append(
            "PULLBACK"
        )

    if continuation:

        score += 3

        reasons.append(
            "CONTINUATION"
        )

    elif m5 > 0:

        score += 1

        reasons.append(
            "M5_UP"
        )

    if signal_bar:

        score += 3

        reasons.append(
            "SIGNAL_BAR"
        )

    if closed_confirm:

        score += 2

        reasons.append(
            "CLOSED_CONFIRM"
        )

    if volume_ratio >= 1.30:

        score += 2

        reasons.append(
            "VOLUME_CONFIRM"
        )

    elif volume_ratio >= 0.80:

        score += 1

        reasons.append(
            "NORMAL_VOLUME"
        )

    # ========================================================
    # NEGATIVES
    # ========================================================

    if failed_breakout:

        score -= 6

        reasons.append(
            "FAILED_BREAKOUT"
        )

    if chase:

        score -= 4

        reasons.append(
            "CHASE"
        )

    if trend == "DOWN":

        score -= 5

        reasons.append(
            "DOWN_TREND"
        )

    # ========================================================
    # CLASSIFICATION
    # ========================================================

    setup = "FILTERED"

    # ========================================================
    # STRONG
    # ========================================================
    #
    # Strong still requires Signal Bar.
    # This is intentionally stricter.
    # ========================================================

    if (
        trend == "UP"
        and breakout_detected
        and pullback_touched
        and continuation
        and closed_confirm
        and signal_bar
        and not failed_breakout
        and not chase
        and score >= 14
    ):

        setup = "STRONG"

    # ========================================================
    # EARLY
    # ========================================================
    #
    # FINAL CHANGE:
    #
    # Signal Bar is NOT mandatory here.
    #
    # Closed candle confirmation IS mandatory.
    # ========================================================

    elif (
        trend in (
            "UP",
            "RANGE",
        )
        and breakout_detected
        and pullback_touched
        and continuation
        and closed_confirm
        and not failed_breakout
        and not chase
        and score >= 11
    ):

        setup = "EARLY"

    # ========================================================
    # WATCH
    # ========================================================

    elif (
        score >= 6
        and not failed_breakout
    ):

        setup = "WATCH"

    # ========================================================
    # BUY READY
    # ========================================================

    buy_ready = (
        buy_ready_structure
        and not failed_breakout
        and not chase
        and score >= 11
    )

    # ========================================================
    # STRUCTURAL SL / TP
    # ========================================================

    structural_sl = support

    risk = (
        close
        - structural_sl
    )

    if risk <= 0:

        risk = close * 0.01

    tp1 = close + (
        risk * 1.5
    )

    tp2 = close + (
        risk * 2.2
    )

    return {
        "symbol": symbol,

        "setup": setup,

        "score": score,

        "buy_ready": buy_ready,

        "price": close,

        "resistance": resistance,

        "support": support,

        "breakout": breakout_pct,

        "real_bos": real_bos,

        "near_bos": near_bos,

        "trend": trend,

        "m5": m5,

        "m15": m15,

        "m1h": m1h,

        "volume": volume_ratio,

        "pullback": pullback_touched,

        "pullback_distance": pullback_distance,

        "continuation": continuation,

        "signal_bar": signal_bar,

        "closed_confirm": closed_confirm,

        "failed_breakout": failed_breakout,

        "chase": chase,

        "sl": structural_sl,

        "tp1": tp1,

        "tp2": tp2,

        "reasons": reasons,
    }


# ============================================================
# SCAN ONE SYMBOL
# ============================================================

def scan_symbol(market):

    symbol = market["symbol"]

    try:

        trades = get_trades(
            symbol
        )

        if not trades:

            return {
                "symbol": symbol,
                "error": "NO_TRADES",
            }

        candles = build_5m_candles(
            trades
        )

        if len(candles) < MIN_CANDLES:

            return {
                "symbol": symbol,
                "error":
                    f"LOW_CANDLES:{len(candles)}",
            }

        result = analyze_price_action(
            symbol,
            candles,
        )

        if result is None:

            return {
                "symbol": symbol,
                "error": "ANALYSIS_FAILED",
            }

        result["candles"] = len(
            candles
        )

        return result

    except Exception as exc:

        return {
            "symbol": symbol,
            "error": str(exc)[:150],
        }


# ============================================================
# RESULT FORMAT
# ============================================================

def result_line(
    item,
    rank,
):

    ready = ""

    if item.get(
        "buy_ready",
        False,
    ):

        ready = " | BUY READY"

    return (
        f"{rank}. {item['symbol']} | "
        f"{item['setup']} | "
        f"Score {item['score']} | "
        f"5m {fmt_pct(item['m5'])} | "
        f"15m {fmt_pct(item['m15'])} | "
        f"1h {fmt_pct(item['m1h'])} | "
        f"BOS {fmt_pct(item['breakout'])}"
        f"{ready}"
    )


# ============================================================
# REPORT
# ============================================================

def build_report(
    markets_count,
    analyzed_count,
    api_errors,
    results,
    scan_seconds,
):

    strong = [
        item
        for item in results
        if item["setup"] == "STRONG"
    ]

    early = [
        item
        for item in results
        if item["setup"] == "EARLY"
    ]

    watch = [
        item
        for item in results
        if item["setup"] == "WATCH"
    ]

    filtered = [
        item
        for item in results
        if item["setup"] == "FILTERED"
    ]

    buy_ready = [
        item
        for item in results
        if item.get(
            "buy_ready",
            False,
        )
    ]

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    lines.append("")

    lines.append(
        "🧠 AL BROOKS PRICE ACTION"
    )

    lines.append(
        "📐 Trend → REAL BOS → Pullback → Continuation → CLOSED CONFIRM"
    )

    lines.append(
        "⏱ TIMEFRAME: 5m CLOSED CANDLES"
    )

    lines.append(
        "🚫 EMA: OFF"
    )

    lines.append(
        "🔒 REAL ORDERS: DISABLED"
    )

    lines.append(
        "🔒 BUY LOCK: ACTIVE"
    )

    lines.append("")

    lines.append(
        f"📊 USDT MARKETS: {markets_count}"
    )

    lines.append(
        f"🔎 ANALYZED: {analyzed_count}"
    )

    lines.append(
        f"❌ API/SCAN ERRORS: {api_errors}"
    )

    lines.append("")

    lines.append(
        f"🟢 STRONG: {len(strong)}"
    )

    lines.append(
        f"🟡 EARLY: {len(early)}"
    )

    lines.append(
        f"👀 WATCH: {len(watch)}"
    )

    lines.append(
        f"⚪ FILTERED: {len(filtered)}"
    )

    lines.append(
        f"🎯 BUY READY: {len(buy_ready)}"
    )

    lines.append("")

    if strong:

        lines.append(
            "🔥 STRONG SETUPS"
        )

        for i, item in enumerate(
            strong[:TOP_RESULTS],
            1,
        ):

            lines.append(
                result_line(
                    item,
                    i,
                )
            )

        lines.append("")

    if early:

        lines.append(
            "⚡ EARLY SETUPS"
        )

        for i, item in enumerate(
            early[:TOP_RESULTS],
            1,
        ):

            lines.append(
                result_line(
                    item,
                    i,
                )
            )

        lines.append("")

    if buy_ready:

        lines.append(
            "🎯 BUY READY SETUPS"
        )

        for i, item in enumerate(
            buy_ready[:TOP_RESULTS],
            1,
        ):

            lines.append(
                result_line(
                    item,
                    i,
                )
            )

        lines.append("")

        lines.append(
            "🔒 BUY LOCK ACTIVE - NO ORDER SENT"
        )

    if not strong and not early:

        lines.append(
            "ℹ️ NO VALID BUY SETUP YET"
        )

        lines.append(
            "Bot will NOT create a fake BUY."
        )

        lines.append("")

    ranked = sorted(
        results,
        key=lambda x: (
            x["score"],
            x["m5"],
            x["m15"],
            x["m1h"],
        ),
        reverse=True,
    )

    lines.append(
        "🏆 TOP PRICE ACTION"
    )

    shown = 0

    for item in ranked:

        if item["setup"] == "FILTERED":

            continue

        shown += 1

        lines.append(
            result_line(
                item,
                shown,
            )
        )

        if shown >= TOP_RESULTS:

            break

    if shown == 0:

        lines.append(
            "No qualifying setup."
        )

    candidates = [
        item
        for item in ranked
        if item["setup"]
        in (
            "STRONG",
            "EARLY",
            "WATCH",
        )
    ]

    if candidates:

        best = candidates[0]

        lines.append("")

        lines.append(
            "🎯 BEST CURRENT SETUP"
        )

        lines.append(
            f"🪙 {best['symbol']}"
        )

        lines.append(
            f"📌 SETUP: {best['setup']}"
        )

        lines.append(
            f"⭐ SCORE: {best['score']}"
        )

        lines.append(
            f"📈 TREND: {best['trend']}"
        )

        lines.append(
            f"💥 REAL BOS: "
            f"{'YES' if best['real_bos'] else 'NO'}"
        )

        lines.append(
            f"📏 BOS: "
            f"{fmt_pct(best['breakout'])}"
        )

        lines.append(
            f"🔄 PULLBACK: "
            f"{'YES' if best['pullback'] else 'NO'}"
        )

        lines.append(
            f"➡️ CONTINUATION: "
            f"{'YES' if best['continuation'] else 'NO'}"
        )

        lines.append(
            f"🕯 SIGNAL BAR: "
            f"{'YES' if best['signal_bar'] else 'NO'}"
        )

        lines.append(
            f"✅ CLOSED CONFIRM: "
            f"{'YES' if best['closed_confirm'] else 'NO'}"
        )

        lines.append(
            f"🎯 BUY READY: "
            f"{'YES' if best['buy_ready'] else 'NO'}"
        )

        lines.append(
            f"📊 VOL: "
            f"{best['volume']:.2f}x"
        )

        lines.append(
            f"💰 PRICE: "
            f"{best['price']:.8g}"
        )

        lines.append(
            f"🛑 STRUCTURAL SL: "
            f"{best['sl']:.8g}"
        )

        lines.append(
            f"🎯 TP1: "
            f"{best['tp1']:.8g}"
        )

        lines.append(
            f"🎯 TP2: "
            f"{best['tp2']:.8g}"
        )

        lines.append(
            "🧠 "
            + ", ".join(
                best["reasons"][:12]
            )
        )

    lines.append("")

    lines.append(
        f"⏱ SCAN TIME: "
        f"{scan_seconds:.1f}s"
    )

    lines.append(
        f"🕐 {now_utc()}"
    )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    print("=" * 60)

    print(
        f"ATI CRYPTO BOT {VERSION}"
    )

    print(
        "AL BROOKS PRICE ACTION"
    )

    print("=" * 60)

    # ========================================================
    # STARTUP
    # ========================================================

    send_telegram(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🧠 AL BROOKS PRICE ACTION\n"
        f"📐 Trend → REAL BOS → Pullback → Continuation → CLOSED CONFIRM\n"
        f"⏱ 5m CLOSED CANDLES\n"
        f"🚫 EMA OFF\n"
        f"🔒 REAL ORDERS DISABLED\n"
        f"🔒 BUY LOCK ACTIVE\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🕐 {now_utc()}"
    )

    # ========================================================
    # CREDENTIALS
    # ========================================================

    if (
        not API_KEY
        or not API_SECRET
    ):

        message = (
            f"🚨 ATI {VERSION}\n\n"
            f"❌ API credentials missing\n"
            f"🛑 SCAN STOPPED\n"
            f"🕐 {now_utc()}"
        )

        print(message)

        send_telegram(
            message
        )

        return

    # ========================================================
    # AUTH
    # ========================================================

    if not auth_test():

        return

    send_telegram(
        f"✅ ATI {VERSION}\n\n"
        f"📡 TABDEAL API: OK\n"
        f"🔐 AUTH: OK\n"
        f"📊 SCAN: STARTING\n"
        f"🧠 AL BROOKS PRICE ACTION\n"
        f"⏱ CLOSED 5m CONFIRMATION\n"
        f"🕐 {now_utc()}"
    )

    # ========================================================
    # EXCHANGE INFO
    # ========================================================

    markets = get_exchange_info()

    if not markets:

        message = (
            f"🚨 ATI {VERSION}\n\n"
            f"❌ EXCHANGE INFO FAILED\n"
            f"🛑 SCAN STOPPED\n"
            f"🕐 {now_utc()}"
        )

        print(message)

        send_telegram(
            message
        )

        return

    print(
        f"USDT MARKETS FOUND: "
        f"{len(markets)}"
    )

    # ========================================================
    # SELECT 40
    # ========================================================

    markets = sorted(
        markets,
        key=lambda x: x["symbol"],
    )

    selected = markets[
        :SCAN_UNIVERSE
    ]

    print(
        f"REQUESTED: "
        f"{len(selected)}"
    )

    # ========================================================
    # SCAN
    # ========================================================

    results = []

    errors = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                scan_symbol,
                market,
            ): market["symbol"]
            for market in selected
        }

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result is None:

                    errors += 1

                    continue

                if "error" in result:

                    errors += 1

                    print(
                        f"{result['symbol']}: "
                        f"{result['error']}"
                    )

                    continue

                results.append(
                    result
                )

            except Exception as exc:

                errors += 1

                print(
                    "SCAN EXCEPTION:",
                    str(exc),
                )

    # ========================================================
    # RANK
    # ========================================================

    results.sort(
        key=lambda x: (
            x["score"],
            x["m5"],
            x["m15"],
            x["m1h"],
        ),
        reverse=True,
    )

    elapsed = (
        time.time()
        - started
    )

    # ========================================================
    # REPORT
    # ========================================================

    report = build_report(
        markets_count=len(markets),
        analyzed_count=len(results),
        api_errors=errors,
        results=results,
        scan_seconds=elapsed,
    )

    print("")
    print(report)
    print("")

    send_telegram(
        report
    )

    print(
        f"ATI {VERSION} FINISHED"
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()
