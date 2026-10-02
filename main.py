import os
import time
import hmac
import hashlib
import math
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.38
# AL BROOKS PRICE ACTION
# ============================================================
#
# CORE:
#   Trend
#   Trading Range
#   HH / HL / LH / LL
#   Breakout
#   Failed Breakout
#   Pullback
#   Signal Bar
#   Breakout -> Pullback -> Continuation
#
# IMPORTANT:
#   NO EMA
#   NO RSI
#   NO MACD
#   NO FAKE BUY
#   REAL ORDERS DISABLED
#
# ============================================================

VERSION = "V40.2.38"

BASE_URL = "https://api1.tabdeal.org"

# ---------------- SAFETY ----------------

REAL_ORDERS = False
BUY_LOCK = True

# ---------------- SCAN ----------------

SCAN_UNIVERSE = 40
TOP_RESULTS = 10

TRADE_LIMIT = 1000
MIN_CANDLES = 30

REQUEST_TIMEOUT = 12
MAX_WORKERS = 8

# ---------------- PRICE ACTION ----------------

SWING_LEFT = 2
SWING_RIGHT = 2

TREND_LOOKBACK = 12
RESISTANCE_LOOKBACK = 12
PULLBACK_LOOKBACK = 5

BREAKOUT_TOLERANCE = 0.25
PULLBACK_TOLERANCE = 0.80
CHASE_LIMIT = 2.20

# ---------------- TELEGRAM ----------------

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

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ============================================================
# GLOBAL SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "ATI-Crypto-Bot-V40.2.38",
    "Accept": "application/json",
})


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def pct(a, b):
    if not b:
        return 0.0
    return ((a - b) / b) * 100.0


def fmt_pct(value):
    return f"{value:+.2f}%"


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM: credentials missing")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        r = SESSION.post(
            url,
            json=payload,
            timeout=TELEGRAM_TIMEOUT,
        )

        if r.status_code == 200:
            return True

        print("TELEGRAM ERROR:", r.status_code, r.text[:300])
        return False

    except Exception as e:
        print("TELEGRAM EXCEPTION:", str(e))
        return False


# ============================================================
# TABDEAL API
# ============================================================

def get_server_time():
    url = f"{BASE_URL}/r/api/v1/time"

    try:
        r = SESSION.get(
            url,
            timeout=REQUEST_TIMEOUT,
        )

        if r.status_code != 200:
            return int(time.time() * 1000)

        data = r.json()

        if isinstance(data, dict):
            for key in (
                "serverTime",
                "timestamp",
                "time",
                "data",
            ):
                if key in data:
                    value = data[key]

                    if isinstance(value, dict):
                        for k in (
                            "serverTime",
                            "timestamp",
                            "time",
                        ):
                            if k in value:
                                value = value[k]
                                break

                    try:
                        return int(value)
                    except Exception:
                        pass

        return int(time.time() * 1000)

    except Exception:
        return int(time.time() * 1000)


def make_signature(timestamp, recv_window=5000):
    query = (
        f"timestamp={int(timestamp)}"
        f"&recvWindow={int(recv_window)}"
    )

    return hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


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
        params.update(extra_params)

    # Signature must be calculated from timestamp + recvWindow.
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
        r = SESSION.get(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:300]}"

        try:
            return r.json(), None
        except Exception:
            return None, "Invalid JSON response"

    except Exception as e:
        return None, str(e)


def public_get(path, params=None):
    url = f"{BASE_URL}{path}"

    try:
        r = SESSION.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:200]}"

        try:
            return r.json(), None
        except Exception:
            return None, "Invalid JSON"

    except Exception as e:
        return None, str(e)


# ============================================================
# AUTH TEST
# ============================================================

def auth_test():
    print("AUTH TEST: STARTING")

    data, error = signed_get("/r/api/v1/account")

    if error:
        print("AUTH FAILED:", error)

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
    data, error = public_get("/r/api/v1/exchangeInfo")

    if error:
        print("EXCHANGE INFO ERROR:", error)
        return []

    markets = []

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

        symbol = str(symbol).upper()

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
    for item in markets:
        unique[item["symbol"]] = item

    return list(unique.values())


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):
    if not isinstance(item, dict):
        return None

    price = None
    qty = None
    timestamp = None

    for key in (
        "price",
        "p",
        "tradePrice",
        "lastPrice",
    ):
        if key in item:
            price = safe_float(item[key])
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
            qty = safe_float(item[key])
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
                timestamp = int(float(item[key]))
            except Exception:
                timestamp = None
            break

    if price is None or price <= 0:
        return None

    if qty is None or qty <= 0:
        qty = 1.0

    if timestamp is None:
        return None

    # Convert seconds to milliseconds.
    if timestamp < 10_000_000_000:
        timestamp *= 1000

    return {
        "price": price,
        "qty": qty,
        "time": timestamp,
    }


# ============================================================
# GET TRADES
# ============================================================

def get_trades(symbol):
    attempts = [
        {"tabdealSymbol": symbol, "limit": TRADE_LIMIT},
        {"symbol": symbol, "limit": TRADE_LIMIT},
        {"market": symbol, "limit": TRADE_LIMIT},
        {"tabdeal_symbol": symbol, "limit": TRADE_LIMIT},
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
            parsed = parse_trade(item)

            if parsed:
                trades.append(parsed)

        if trades:
            trades.sort(key=lambda x: x["time"])
            return trades

    return []


# ============================================================
# BUILD 5M CANDLES
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
            trade["qty"] * trade["price"]
        )

        candle["trades"] += 1

    candles = sorted(
        buckets.values(),
        key=lambda x: x["time"],
    )

    # Remove currently forming candle.
    if candles:
        current_bucket = (
            int(time.time() * 1000) // 300000
        ) * 300000

        candles = [
            c for c in candles
            if c["time"] < current_bucket
        ]

    return candles


# ============================================================
# PRICE ACTION
# ============================================================

def candle_range(c):
    return max(
        c["high"] - c["low"],
        1e-12,
    )


def candle_position(c):
    rng = candle_range(c)

    return (
        (c["close"] - c["low"]) / rng
    )


def is_bull_signal_bar(c):
    """
    Brooks-style bullish signal bar.

    We do NOT use body percentage as a hard filter.
    This works with trade-derived candles where open/close
    can sometimes be unreliable.
    """

    rng = candle_range(c)

    close_near_high = (
        (c["high"] - c["close"]) / rng
    ) <= 0.35

    upper_tail_reasonable = (
        (c["high"] - c["close"]) / rng
    ) <= 0.55

    return (
        close_near_high
        and upper_tail_reasonable
        and candle_position(c) >= 0.55
    )


def is_bear_signal_bar(c):
    rng = candle_range(c)

    close_near_low = (
        (c["close"] - c["low"]) / rng
    ) <= 0.35

    return (
        close_near_low
        and candle_position(c) <= 0.45
    )


def swing_highs(candles):
    result = []

    if len(candles) < 5:
        return result

    for i in range(2, len(candles) - 2):
        h = candles[i]["high"]

        if (
            h >= candles[i - 1]["high"]
            and h >= candles[i - 2]["high"]
            and h >= candles[i + 1]["high"]
            and h >= candles[i + 2]["high"]
        ):
            result.append({
                "index": i,
                "price": h,
            })

    return result


def swing_lows(candles):
    result = []

    if len(candles) < 5:
        return result

    for i in range(2, len(candles) - 2):
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

    highs = swing_highs(candles[-TREND_LOOKBACK:])
    lows = swing_lows(candles[-TREND_LOOKBACK:])

    if len(highs) < 2 or len(lows) < 2:
        # Fallback to simple structure.
        closes = [
            c["close"]
            for c in candles[-8:]
        ]

        if closes[-1] > closes[0]:
            return "UP"

        if closes[-1] < closes[0]:
            return "DOWN"

        return "RANGE"

    h1 = highs[-2]["price"]
    h2 = highs[-1]["price"]

    l1 = lows[-2]["price"]
    l2 = lows[-1]["price"]

    if h2 > h1 and l2 > l1:
        return "UP"

    if h2 < h1 and l2 < l1:
        return "DOWN"

    return "RANGE"


# ============================================================
# RESISTANCE / SUPPORT
# ============================================================

def resistance_level(candles):
    if len(candles) < RESISTANCE_LOOKBACK + 2:
        return None

    section = candles[
        -(RESISTANCE_LOOKBACK + 1):-1
    ]

    highs = [
        c["high"]
        for c in section
    ]

    if not highs:
        return None

    return max(highs)


def support_level(candles):
    if len(candles) < RESISTANCE_LOOKBACK + 2:
        return None

    section = candles[
        -(RESISTANCE_LOOKBACK + 1):-1
    ]

    lows = [
        c["low"]
        for c in section
    ]

    if not lows:
        return None

    return min(lows)


# ============================================================
# AL BROOKS SETUP
# ============================================================

def analyze_price_action(symbol, candles):
    if len(candles) < MIN_CANDLES:
        return None

    current = candles[-1]
    previous = candles[-2]

    close = current["close"]

    resistance = resistance_level(candles)

    support = support_level(candles)

    if resistance is None or support is None:
        return None

    trend = detect_trend(candles)

    # --------------------------------------------------------
    # Momentum
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Breakout
    # --------------------------------------------------------

    breakout_pct = pct(
        close,
        resistance,
    )

    breakout_detected = (
        close >= resistance
        or previous["close"] >= resistance
    )

    # --------------------------------------------------------
    # Pullback
    # --------------------------------------------------------

    pullback_touched = False

    pullback_distance = 999.0

    recent_start = max(
        1,
        len(candles) - PULLBACK_LOOKBACK - 1,
    )

    for i in range(
        recent_start,
        len(candles) - 1,
    ):
        c = candles[i]

        distance = abs(
            pct(c["low"], resistance)
        )

        if distance <= PULLBACK_TOLERANCE:
            pullback_touched = True
            pullback_distance = min(
                pullback_distance,
                distance,
            )

    # Current candle must reclaim/stay above resistance.
    continuation = (
        close >= resistance
        and m5 > 0
    )

    # --------------------------------------------------------
    # Signal bar
    # --------------------------------------------------------

    signal_bar = is_bull_signal_bar(current)

    previous_signal = is_bull_signal_bar(previous)

    # We use signal bar as a score,
    # NOT as an absolute hard gate.
    signal_quality = (
        signal_bar or previous_signal
    )

    # --------------------------------------------------------
    # Failed breakout
    # --------------------------------------------------------

    failed_breakout = (
        previous["high"] > resistance
        and previous["close"] < resistance
        and close < resistance
    )

    # --------------------------------------------------------
    # Chase protection
    # --------------------------------------------------------

    chase = (
        breakout_pct > CHASE_LIMIT
    )

    # --------------------------------------------------------
    # Volume
    # --------------------------------------------------------

    previous_volumes = [
        c["volume"]
        for c in candles[-11:-1]
        if c["volume"] > 0
    ]

    if previous_volumes:
        avg_volume = (
            sum(previous_volumes)
            / len(previous_volumes)
        )

        volume_ratio = (
            current["volume"] / avg_volume
            if avg_volume > 0
            else 0
        )
    else:
        volume_ratio = 0

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0
    reasons = []

    # Trend
    if trend == "UP":
        score += 4
        reasons.append("UP_TREND")

    elif trend == "RANGE":
        score += 1
        reasons.append("TRADING_RANGE")

    # 15m / 1h context
    if m15 > 0:
        score += 2
        reasons.append("15M_UP")

    if m1h > 0:
        score += 2
        reasons.append("1H_UP")

    # Breakout
    if breakout_detected:
        score += 3
        reasons.append("BREAKOUT")

    elif breakout_pct >= -0.25:
        score += 1
        reasons.append("NEAR_BOS")

    # Pullback
    if pullback_touched:
        score += 3
        reasons.append("PULLBACK")

    # Continuation
    if continuation:
        score += 3
        reasons.append("CONTINUATION")

    elif m5 > 0:
        score += 1
        reasons.append("M5_UP")

    # Signal bar
    if signal_quality:
        score += 2
        reasons.append("SIGNAL_BAR")

    # Volume is supporting evidence only.
    if volume_ratio >= 1.30:
        score += 2
        reasons.append("VOLUME_CONFIRM")

    elif volume_ratio >= 0.80:
        score += 1
        reasons.append("NORMAL_VOLUME")

    # --------------------------------------------------------
    # HARD NEGATIVES
    # --------------------------------------------------------

    if failed_breakout:
        score -= 5
        reasons.append("FAILED_BREAKOUT")

    if chase:
        score -= 4
        reasons.append("CHASE")

    if trend == "DOWN":
        score -= 5
        reasons.append("DOWN_TREND")

    # --------------------------------------------------------
    # CLASSIFICATION
    # --------------------------------------------------------

    setup = "WATCH"

    # Strong Al Brooks style continuation:
    if (
        trend == "UP"
        and breakout_detected
        and pullback_touched
        and continuation
        and not failed_breakout
        and not chase
        and score >= 13
    ):
        setup = "STRONG"

    # Early setup:
    elif (
        trend in ("UP", "RANGE")
        and (
            breakout_detected
            or breakout_pct >= -0.25
        )
        and (
            pullback_touched
            or continuation
        )
        and m5 > 0
        and not failed_breakout
        and not chase
        and score >= 9
    ):
        setup = "EARLY"

    elif (
        score >= 6
        and not failed_breakout
    ):
        setup = "WATCH"

    else:
        setup = "FILTERED"

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    # For a BUY setup, stop is below the broken level.
    # This is analytical only because real orders are disabled.

    if support > 0:
        structural_sl = support
    else:
        structural_sl = close * 0.985

    risk = close - structural_sl

    if risk <= 0:
        risk = close * 0.01

    tp1 = close + (risk * 1.5)
    tp2 = close + (risk * 2.2)

    return {
        "symbol": symbol,
        "setup": setup,
        "score": score,
        "price": close,
        "resistance": resistance,
        "support": support,
        "breakout": breakout_pct,
        "trend": trend,
        "m5": m5,
        "m15": m15,
        "m1h": m1h,
        "volume": volume_ratio,
        "pullback": pullback_touched,
        "pullback_distance": pullback_distance,
        "continuation": continuation,
        "signal_bar": signal_quality,
        "failed_breakout": failed_breakout,
        "chase": chase,
        "sl": structural_sl,
        "tp1": tp1,
        "tp2": tp2,
        "reasons": reasons,
    }


# ============================================================
# SCAN ONE MARKET
# ============================================================

def scan_symbol(market):
    symbol = market["symbol"]

    try:
        trades = get_trades(symbol)

        if not trades:
            return {
                "symbol": symbol,
                "error": "NO_TRADES",
            }

        candles = build_5m_candles(trades)

        if len(candles) < MIN_CANDLES:
            return {
                "symbol": symbol,
                "error": f"LOW_CANDLES:{len(candles)}",
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

        result["candles"] = len(candles)

        return result

    except Exception as e:
        return {
            "symbol": symbol,
            "error": str(e)[:150],
        }


# ============================================================
# FORMAT RESULT
# ============================================================

def result_line(item, rank):
    symbol = item["symbol"]

    return (
        f"{rank}. {symbol} | "
        f"{item['setup']} | "
        f"Score {item['score']} | "
        f"5m {fmt_pct(item['m5'])} | "
        f"15m {fmt_pct(item['m15'])} | "
        f"1h {fmt_pct(item['m1h'])} | "
        f"BOS {fmt_pct(item['breakout'])}"
    )


# ============================================================
# TELEGRAM REPORT
# ============================================================

def build_report(
    markets_count,
    analyzed_count,
    api_errors,
    results,
    scan_seconds,
):
    strong = [
        x for x in results
        if x["setup"] == "STRONG"
    ]

    early = [
        x for x in results
        if x["setup"] == "EARLY"
    ]

    watch = [
        x for x in results
        if x["setup"] == "WATCH"
    ]

    filtered = [
        x for x in results
        if x["setup"] == "FILTERED"
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
        "📐 Trend → BOS → Pullback → Continuation"
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

    lines.append("")

    if strong:
        lines.append("🔥 STRONG SETUPS")

        for i, item in enumerate(
            strong[:TOP_RESULTS],
            1,
        ):
            lines.append(
                result_line(item, i)
            )

        lines.append("")

    if early:
        lines.append("⚡ EARLY SETUPS")

        for i, item in enumerate(
            early[:TOP_RESULTS],
            1,
        ):
            lines.append(
                result_line(item, i)
            )

        lines.append("")

    if not strong and not early:
        lines.append(
            "ℹ️ NO VALID BUY SETUP YET"
        )

        lines.append(
            "Bot will NOT create a fake BUY."
        )

        lines.append("")

    # Top candidates regardless of setup.
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

    lines.append("🏆 TOP PRICE ACTION")

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

    # Detailed best setup
    candidates = [
        x for x in ranked
        if x["setup"] in (
            "STRONG",
            "EARLY",
            "WATCH",
        )
    ]

    if candidates:
        best = candidates[0]

        lines.append("")
        lines.append("🎯 BEST CURRENT SETUP")

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
            f"💥 BOS: {fmt_pct(best['breakout'])}"
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
            f"📊 VOL: {best['volume']:.2f}x"
        )

        lines.append(
            f"💰 PRICE: {best['price']:.8g}"
        )

        lines.append(
            f"🛑 STRUCTURAL SL: {best['sl']:.8g}"
        )

        lines.append(
            f"🎯 TP1: {best['tp1']:.8g}"
        )

        lines.append(
            f"🎯 TP2: {best['tp2']:.8g}"
        )

        lines.append(
            "🧠 "
            + ", ".join(best["reasons"][:8])
        )

    lines.append("")
    lines.append(
        f"⏱ SCAN TIME: {scan_seconds:.1f}s"
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
    print(f"ATI CRYPTO BOT {VERSION}")
    print("AL BROOKS PRICE ACTION")
    print("=" * 60)

    # --------------------------------------------------------
    # STARTUP
    # --------------------------------------------------------

    send_telegram(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🧠 AL BROOKS PRICE ACTION\n"
        f"📐 Trend → BOS → Pullback → Continuation\n"
        f"⏱ 5m CLOSED CANDLES\n"
        f"🚫 EMA OFF\n"
        f"🔒 REAL ORDERS DISABLED\n"
        f"🔒 BUY LOCK ACTIVE\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🕐 {now_utc()}"
    )

    # --------------------------------------------------------
    # CREDENTIAL CHECK
    # --------------------------------------------------------

    if not API_KEY or not API_SECRET:
        message = (
            f"🚨 ATI {VERSION}\n\n"
            f"❌ API credentials missing\n"
            f"🛑 SCAN STOPPED\n"
            f"🕐 {now_utc()}"
        )

        print(message)
        send_telegram(message)
        return

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    if not auth_test():
        return

    send_telegram(
        f"✅ ATI {VERSION}\n\n"
        f"📡 TABDEAL API: OK\n"
        f"🔐 AUTH: OK\n"
        f"📊 SCAN: STARTING\n"
        f"🧠 AL BROOKS PRICE ACTION\n"
        f"🕐 {now_utc()}"
    )

    # --------------------------------------------------------
    # EXCHANGE INFO
    # --------------------------------------------------------

    markets = get_exchange_info()

    if not markets:
        message = (
            f"🚨 ATI {VERSION}\n\n"
            f"❌ EXCHANGE INFO FAILED\n"
            f"🛑 SCAN STOPPED\n"
            f"🕐 {now_utc()}"
        )

        print(message)
        send_telegram(message)
        return

    print(
        f"USDT MARKETS FOUND: {len(markets)}"
    )

    # --------------------------------------------------------
    # SELECT 40
    # --------------------------------------------------------

    # Keep a deterministic universe.
    markets = sorted(
        markets,
        key=lambda x: x["symbol"],
    )

    selected = markets[:SCAN_UNIVERSE]

    print(
        f"REQUESTED: {len(selected)}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

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

        for future in as_completed(futures):
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

                results.append(result)

            except Exception as e:
                errors += 1
                print(
                    "SCAN EXCEPTION:",
                    str(e),
                )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["score"],
            x["m5"],
            x["m15"],
            x["m1h"],
        ),
        reverse=True,
    )

    elapsed = time.time() - started

    # --------------------------------------------------------
    # REPORT
    # --------------------------------------------------------

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

    send_telegram(report)

    print(
        f"ATI {VERSION} FINISHED"
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()
