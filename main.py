import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V37.5
# SMART UPWARD COIN SCANNER
# ============================================================

VERSION = "V37.5"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

CANDLE_LIMIT = 720
MAX_MARKETS = 1000
MAX_WORKERS = 15

TOP_RESULTS = 5

MIN_SCORE = 6

# Maximum acceptable distance from entry to SL
MAX_SL_PERCENT = 5.0

# Late-entry filters
MAX_5M_MOVE = 3.5
MAX_BREAKOUT_ENTRY = 3.0

# Real trading stays OFF
REAL_TRADING = False
ORDER_EXECUTION = False

REQUEST_TIMEOUT = 12


# ============================================================
# ENV
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-CRYPTO-BOT/37.5",
        "Accept": "application/json",
    }
)


# ============================================================
# BASIC HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def pct_change(old, new):
    old = safe_float(old)
    new = safe_float(new)

    if old == 0:
        return 0.0

    return ((new - old) / old) * 100.0


def fmt_price(value):
    value = safe_float(value)

    if value == 0:
        return "0"

    if value >= 1000:
        return f"{value:.2f}"

    if value >= 100:
        return f"{value:.4f}"

    if value >= 1:
        return f"{value:.6f}"

    if value >= 0.01:
        return f"{value:.7f}"

    if value >= 0.0001:
        return f"{value:.8f}"

    return f"{value:.10f}"


def clamp(value, low, high):
    return max(low, min(high, value))


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are missing.")
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
        response = session.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print("Telegram ERROR:", response.status_code, response.text[:300])

    except Exception as exc:
        print("Telegram ERROR:", exc)

    return False


# ============================================================
# TABDEAL API
# ============================================================

def api_get(path, params=None):
    url = BASE_URL + path

    try:
        response = session.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:
            return None

        return response.json()

    except Exception:
        return None


# ============================================================
# MARKET DISCOVERY
# ============================================================

def extract_symbol(item):
    if isinstance(item, str):
        return item.upper()

    if not isinstance(item, dict):
        return ""

    for key in (
        "symbol",
        "market",
        "pair",
        "instrument",
        "code",
    ):
        value = item.get(key)

        if isinstance(value, str):
            return value.upper()

    return ""


def get_usdt_markets():
    """
    Try several common Tabdeal market endpoints.
    """

    endpoints = [
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
        "/r/api/v1/tickers",
    ]

    for endpoint in endpoints:

        data = api_get(endpoint)

        if data is None:
            continue

        items = data

        if isinstance(data, dict):

            for key in (
                "data",
                "result",
                "results",
                "markets",
                "symbols",
                "tickers",
            ):

                candidate = data.get(key)

                if isinstance(candidate, list):
                    items = candidate
                    break

        if not isinstance(items, list):
            continue

        symbols = []

        for item in items:

            symbol = extract_symbol(item)

            if not symbol:
                continue

            symbol = symbol.replace("/", "").replace("-", "")

            if symbol.endswith("USDT"):
                symbols.append(symbol)

        symbols = sorted(set(symbols))

        if symbols:
            return symbols[:MAX_MARKETS]

    return []


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):
    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if data is None:
        return []

    items = data

    if isinstance(data, dict):

        for key in (
            "data",
            "result",
            "results",
            "trades",
        ):

            candidate = data.get(key)

            if isinstance(candidate, list):
                items = candidate
                break

    if not isinstance(items, list):
        return []

    trades = []

    for item in items:

        if not isinstance(item, dict):
            continue

        price = None
        qty = None
        timestamp = None

        for key in (
            "price",
            "p",
        ):
            if key in item:
                price = safe_float(item.get(key))
                break

        for key in (
            "quantity",
            "qty",
            "amount",
            "q",
            "volume",
        ):
            if key in item:
                qty = safe_float(item.get(key))
                break

        for key in (
            "timestamp",
            "time",
            "T",
            "created_at",
        ):
            if key in item:
                timestamp = safe_float(item.get(key))
                break

        if price is None or price <= 0:
            continue

        if qty is None or qty <= 0:
            qty = 1.0

        if timestamp is None or timestamp <= 0:
            continue

        # milliseconds -> seconds
        if timestamp > 100000000000:
            timestamp /= 1000.0

        trades.append(
            {
                "price": price,
                "qty": qty,
                "time": timestamp,
            }
        )

    trades.sort(key=lambda x: x["time"])

    return trades


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_5m_candles(trades):
    buckets = {}

    for trade in trades:

        timestamp = trade["time"]
        price = trade["price"]
        qty = trade["qty"]

        bucket = int(timestamp // 300) * 300

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
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

    candles = list(buckets.values())

    candles.sort(key=lambda x: x["time"])

    return candles


# ============================================================
# RESAMPLE
# ============================================================

def resample_candles(candles, minutes):
    if not candles:
        return []

    seconds = minutes * 60

    buckets = {}

    for candle in candles:

        bucket = int(candle["time"] // seconds) * seconds

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": candle["volume"],
            }

        else:

            result = buckets[bucket]

            result["high"] = max(
                result["high"],
                candle["high"],
            )

            result["low"] = min(
                result["low"],
                candle["low"],
            )

            result["close"] = candle["close"]
            result["volume"] += candle["volume"]

    result = list(buckets.values())

    result.sort(key=lambda x: x["time"])

    return result


# ============================================================
# CLOSED CANDLE
# ============================================================

def remove_open_candle(candles):
    if len(candles) < 3:
        return candles

    current_bucket = int(time.time() // 300) * 300

    return [
        candle
        for candle in candles
        if candle["time"] < current_bucket
    ]


# ============================================================
# MOMENTUM
# ============================================================

def momentum(candles, periods):
    if len(candles) <= periods:
        return 0.0

    old = candles[-1 - periods]["close"]
    new = candles[-1]["close"]

    return pct_change(old, new)


def candle_body_percent(candle):
    open_price = candle["open"]
    close_price = candle["close"]

    if open_price == 0:
        return 0.0

    return abs(
        (close_price - open_price) / open_price
    ) * 100.0


# ============================================================
# VOLUME
# ============================================================

def volume_ratio(candles):
    if len(candles) < 21:
        return 1.0

    current = candles[-1]["volume"]

    previous = [
        candle["volume"]
        for candle in candles[-21:-1]
    ]

    if not previous:
        return 1.0

    average = sum(previous) / len(previous)

    if average <= 0:
        return 1.0

    return current / average


# ============================================================
# STRUCTURE
# ============================================================

def structure_analysis(candles):
    score = 0
    reasons = []

    if len(candles) < 21:
        return score, reasons

    current = candles[-1]

    # --------------------------------------------------------
    # Higher closes
    # --------------------------------------------------------

    closes = [
        candle["close"]
        for candle in candles[-4:]
    ]

    if (
        closes[-1] > closes[-2]
        and closes[-2] > closes[-3]
    ):
        score += 1
        reasons.append("HIGHER CLOSES")

    # --------------------------------------------------------
    # Higher low
    # --------------------------------------------------------

    previous_low = min(
        candle["low"]
        for candle in candles[-11:-1]
    )

    if current["low"] > previous_low:
        score += 1
        reasons.append("HIGHER LOW")

    # --------------------------------------------------------
    # IMPORTANT:
    # Use EXACTLY the same reference high
    # for NEW HIGH and BREAKOUT.
    # --------------------------------------------------------

    reference_high = max(
        candle["high"]
        for candle in candles[-21:-1]
    )

    current_high = current["high"]

    if current_high > reference_high:
        score += 1
        reasons.append("NEW HIGH")

    return score, reasons


# ============================================================
# BREAKOUT
# ============================================================

def breakout_analysis(candles):
    score = 0
    reasons = []

    if len(candles) < 21:
        return score, 0.0, reasons

    current = candles[-1]

    # Same reference used by structure_analysis()
    reference_high = max(
        candle["high"]
        for candle in candles[-21:-1]
    )

    close = current["close"]
    high = current["high"]

    breakout_pct = pct_change(
        reference_high,
        close,
    )

    high_breakout_pct = pct_change(
        reference_high,
        high,
    )

    # --------------------------------------------------------
    # Only positive breakout gets breakout points.
    # --------------------------------------------------------

    if breakout_pct > 0:

        score += 2
        reasons.append("BREAKOUT")

        if breakout_pct >= 0.50:
            score += 1
            reasons.append("STRONG BREAKOUT")

    # --------------------------------------------------------
    # NEW HIGH is only valid when the same reference is broken.
    # --------------------------------------------------------

    if high_breakout_pct > 0 and breakout_pct > 0:
        if "NEW HIGH" not in reasons:
            score += 1
            reasons.append("NEW HIGH")

    return score, breakout_pct, reasons


# ============================================================
# ENTRY QUALITY
# ============================================================

def entry_quality(
    candles,
    m5,
    m15,
    breakout_pct,
):
    score = 0
    reasons = []

    current = candles[-1]

    body_pct = candle_body_percent(current)

    # Healthy candle
    if body_pct > 0.05:
        score += 1
        reasons.append("HEALTHY BODY")

    # Not too extended on 5m
    if 0 < m5 <= MAX_5M_MOVE:
        score += 1
        reasons.append("GOOD 5M ENTRY")

    # Momentum alignment
    if m5 > 0 and m15 > 0:
        score += 1
        reasons.append("MOMENTUM ALIGNED")

    # Avoid very large candle chase
    if body_pct <= 2.5:
        score += 1
        reasons.append("NO CANDLE CHASE")

    # Avoid very extended breakout
    if breakout_pct <= MAX_BREAKOUT_ENTRY:
        score += 1
        reasons.append("ENTRY NOT EXTENDED")

    return score, reasons


# ============================================================
# LATE ENTRY PENALTY
# ============================================================

def late_entry_penalty(m5, breakout_pct):
    penalty = 0
    reasons = []

    if m5 > 5.0:
        penalty += 2
        reasons.append("5M TOO EXTENDED")

    elif m5 > 3.0:
        penalty += 1
        reasons.append("5M EXTENDED")

    if breakout_pct > 3.0:
        penalty += 1
        reasons.append("BREAKOUT TOO EXTENDED")

    return penalty, reasons


# ============================================================
# RISK / LEVELS
# ============================================================

def calculate_levels(candles, entry):
    """
    SL based on recent structure.
    TP based on REAL risk distance.
    """

    recent_low = min(
        candle["low"]
        for candle in candles[-20:]
    )

    fallback_sl = entry * 0.995

    sl = min(
        recent_low,
        fallback_sl,
    )

    # Make sure SL is below entry.
    if sl >= entry:
        sl = fallback_sl

    risk = entry - sl

    if risk <= 0:
        return None

    risk_pct = (risk / entry) * 100.0

    # Hard maximum risk filter
    if risk_pct > MAX_SL_PERCENT:
        return None

    tp1 = entry + (risk * 1.5)
    tp2 = entry + (risk * 2.5)

    return {
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk_pct": risk_pct,
    }


# ============================================================
# SCORE
# ============================================================

def analyze_symbol(symbol):
    try:

        trades = get_trades(symbol)

        if len(trades) < 100:
            return None

        candles_5m = build_5m_candles(trades)

        candles_5m = remove_open_candle(
            candles_5m
        )

        if len(candles_5m) < 30:
            return None

        candles_5m = candles_5m[-CANDLE_LIMIT:]

        candles_15m = resample_candles(
            candles_5m,
            15,
        )

        candles_1h = resample_candles(
            candles_5m,
            60,
        )

        if (
            len(candles_15m) < 10
            or len(candles_1h) < 5
        ):
            return None

        # ----------------------------------------------------
        # Momentum
        # ----------------------------------------------------

        m5 = momentum(
            candles_5m,
            1,
        )

        m15 = momentum(
            candles_15m,
            1,
        )

        h1 = momentum(
            candles_1h,
            1,
        )

        # ----------------------------------------------------
        # Base score
        # ----------------------------------------------------

        score = 0
        reasons = []

        if m5 > 0:
            score += 1
            reasons.append("5M UP")

        if m5 >= 0.50:
            score += 1
            reasons.append("5M STRONG")

        if m15 > 0:
            score += 1
            reasons.append("15M UP")

        if m15 >= 1.0:
            score += 1
            reasons.append("15M STRONG")

        if h1 > 0:
            score += 1
            reasons.append("1H UP")

        if h1 >= 2.0:
            score += 1
            reasons.append("1H STRONG")

        # ----------------------------------------------------
        # Structure
        # ----------------------------------------------------

        structure_points, structure_reasons = (
            structure_analysis(candles_5m)
        )

        score += structure_points
        reasons.extend(structure_reasons)

        # ----------------------------------------------------
        # Breakout
        # ----------------------------------------------------

        breakout_points, breakout_pct, breakout_reasons = (
            breakout_analysis(candles_5m)
        )

        score += breakout_points
        reasons.extend(
            [
                x
                for x in breakout_reasons
                if x not in reasons
            ]
        )

        # ----------------------------------------------------
        # Volume
        # ----------------------------------------------------

        vol_ratio = volume_ratio(candles_5m)

        if vol_ratio >= 1.20:
            score += 1
            reasons.append("VOLUME UP")

        if vol_ratio >= 2.0:
            score += 1
            reasons.append("HIGH VOLUME")

        # ----------------------------------------------------
        # Entry quality
        # ----------------------------------------------------

        entry_points, entry_reasons = entry_quality(
            candles_5m,
            m5,
            m15,
            breakout_pct,
        )

        score += entry_points

        reasons.extend(
            [
                x
                for x in entry_reasons
                if x not in reasons
            ]
        )

        # ----------------------------------------------------
        # Late entry penalty
        # ----------------------------------------------------

        late_penalty, late_reasons = (
            late_entry_penalty(
                m5,
                breakout_pct,
            )
        )

        score -= late_penalty

        # ----------------------------------------------------
        # Basic direction protection
        # ----------------------------------------------------

        if m5 <= 0 or m15 <= 0 or h1 <= 0:
            return None

        # ----------------------------------------------------
        # Entry
        # ----------------------------------------------------

        entry = candles_5m[-1]["close"]

        levels = calculate_levels(
            candles_5m,
            entry,
        )

        if levels is None:
            return None

        # ----------------------------------------------------
        # Final classification
        # ----------------------------------------------------

        if score < MIN_SCORE:
            return None

        signal_type = "SIGNAL"

        if score < 7:
            signal_type = "WATCH"

        # Very late entries become WATCH instead of SIGNAL.
        if late_penalty >= 2:
            signal_type = "WATCH"

        return {
            "symbol": symbol,
            "score": score,
            "type": signal_type,

            "price": entry,

            "m5": m5,
            "m15": m15,
            "h1": h1,

            "volume": vol_ratio,
            "breakout": breakout_pct,

            "entry": levels["entry"],
            "sl": levels["sl"],
            "tp1": levels["tp1"],
            "tp2": levels["tp2"],
            "risk_pct": levels["risk_pct"],

            "entry_points": entry_points,
            "late_penalty": late_penalty,

            "reasons": reasons,
            "late_reasons": late_reasons,
        }

    except Exception as exc:
        print(f"{symbol} ERROR:", exc)
        return None


# ============================================================
# FORMAT RESULT
# ============================================================

def format_result(index, result):
    symbol = result["symbol"]

    reasons = result["reasons"]

    # Keep Telegram message readable.
    reasons_text = ", ".join(reasons[:10])

    return (
        f"#{index} {symbol} — {result['type']}\n"
        f"⭐ SCORE: {result['score']}\n"
        f"💰 PRICE: {fmt_price(result['price'])}\n"
        f"🎯 ENTRY: {fmt_price(result['entry'])}\n"
        f"📈 5M: {result['m5']:+.2f}%\n"
        f"📊 15M: {result['m15']:+.2f}%\n"
        f"🚀 1H: {result['h1']:+.2f}%\n"
        f"🔊 VOL: {result['volume']:.2f}x\n"
        f"💥 BREAKOUT: {result['breakout']:+.2f}%\n"
        f"🛑 SL: {fmt_price(result['sl'])}\n"
        f"🎯 TP1: {fmt_price(result['tp1'])}\n"
        f"🎯 TP2: {fmt_price(result['tp2'])}\n"
        f"⚠️ RISK: {result['risk_pct']:.2f}%\n"
        f"🧠 ENTRY QUALITY: {result['entry_points']}\n"
        f"🚫 LATE PENALTY: {result['late_penalty']}\n"
        f"🔎 {reasons_text}"
    )


# ============================================================
# MAIN SCAN
# ============================================================

def main():

    start_time = time.time()

    start_message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 SMART UPWARD COIN SCANNER\n\n"
        f"⏱ Timeframe: 5m\n"
        f"✅ CLOSED CANDLE\n"
        f"📊 5M + 15M + 1H MOMENTUM\n"
        f"💥 CONSISTENT BREAKOUT ENGINE\n"
        f"🎯 ENTRY QUALITY ENGINE: ON\n"
        f"🚫 LATE ENTRY FILTER: ON\n"
        f"🛑 MAX SL RISK: {MAX_SL_PERCENT:.1f}%\n"
        f"🔒 REAL TRADING: OFF\n\n"
        f"📡 Starting scan...\n"
        f"🕐 {now_utc()}"
    )

    telegram_send(start_message)

    print(start_message)

    # --------------------------------------------------------
    # Markets
    # --------------------------------------------------------

    markets = get_usdt_markets()

    if not markets:

        error_message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET ERROR\n"
            f"Could not load USDT markets.\n\n"
            f"🕐 {now_utc()}"
        )

        telegram_send(error_message)

        print(error_message)

        return

    print(
        f"Found {len(markets)} USDT markets."
    )

    # --------------------------------------------------------
    # Parallel scan
    # --------------------------------------------------------

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol,
            ): symbol
            for symbol in markets
        }

        for future in as_completed(futures):

            try:

                result = future.result()

                if result is not None:
                    results.append(result)

            except Exception as exc:

                symbol = futures[future]

                print(
                    f"{symbol} FUTURE ERROR:",
                    exc,
                )

    # --------------------------------------------------------
    # Sort
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["type"] == "SIGNAL",
            x["score"],
            x["entry_points"],
            x["volume"],
            x["m5"],
        ),
        reverse=True,
    )

    # --------------------------------------------------------
    # Top results
    # --------------------------------------------------------

    top_results = results[:TOP_RESULTS]

    elapsed = time.time() - start_time

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if not top_results:

        final_message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"🚀 SMART UPWARD COIN SCANNER\n\n"
            f"📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: {len(markets)}\n"
            f"⭐ MIN SCORE: {MIN_SCORE}\n"
            f"🛑 MAX SL RISK: {MAX_SL_PERCENT:.1f}%\n\n"
            f"❌ NO VALID UPWARD SIGNAL\n\n"
            f"🔒 REAL TRADING: OFF\n"
            f"⚡ SCAN TIME: {elapsed:.1f}s\n"
            f"🕐 {now_utc()}"
        )

        telegram_send(final_message)

        print(final_message)

        return

    # --------------------------------------------------------
    # Final message
    # --------------------------------------------------------

    header = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 STRONG UPWARD SCANNER\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"⭐ MIN SCORE: {MIN_SCORE}\n"
        f"🛑 MAX SL RISK: {MAX_SL_PERCENT:.1f}%\n\n"
    )

    blocks = []

    for index, result in enumerate(
        top_results,
        start=1,
    ):
        blocks.append(
            format_result(
                index,
                result,
            )
        )

    final_message = (
        header
        + "\n\n".join(blocks)
        + "\n\n"
        + f"🔒 REAL TRADING: OFF\n"
        + f"⚡ SCAN TIME: {elapsed:.1f}s\n"
        + f"🕐 {now_utc()}"
    )

    telegram_send(final_message)

    print(final_message)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
