import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V37.0
# UPWARD COIN SCANNER
# ============================================================

VERSION = "V37.0"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 720
MAX_MARKETS = 1000
TOP_RESULTS = 5

REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.03

MIN_SCORE = 6

# Safety:
# V37 NEVER sends real orders.
REAL_TRADING = False
ORDER_EXECUTION = False


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-CRYPTO-BOT/37.0",
        "Accept": "application/json",
    }
)


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/sendMessage"
        )

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        return response.ok

    except Exception:
        return False


# ============================================================
# SAFE JSON
# ============================================================

def get_json(url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            return None

        try:
            return response.json()
        except Exception:
            return None

    except Exception:
        return None


# ============================================================
# GENERIC HELPERS
# ============================================================

def as_list(value):
    if isinstance(value, list):
        return value

    if isinstance(value, tuple):
        return list(value)

    if isinstance(value, dict):
        for key in (
            "data",
            "result",
            "results",
            "items",
            "symbols",
            "markets",
            "ticker",
            "tickers",
        ):
            item = value.get(key)

            if isinstance(item, list):
                return item

        return []

    return []


def safe_float(value, default=None):
    try:
        if value is None:
            return default

        if isinstance(value, bool):
            return default

        return float(value)

    except Exception:
        return default


def safe_int(value, default=None):
    try:
        return int(float(value))
    except Exception:
        return default


def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def pct_change(old, new):
    if old is None or new is None:
        return 0.0

    if old == 0:
        return 0.0

    return ((new - old) / old) * 100.0


# ============================================================
# SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(value):
    if value is None:
        return None

    text = str(value).upper().strip()

    text = text.replace("-", "")
    text = text.replace("_", "")
    text = text.replace("/", "")

    if text.endswith("USDT"):
        return text

    return None


def extract_symbol(item):
    if isinstance(item, str):
        return normalize_symbol(item)

    if not isinstance(item, dict):
        return None

    for key in (
        "symbol",
        "pair",
        "market",
        "instrument",
        "code",
        "name",
    ):
        value = item.get(key)

        symbol = normalize_symbol(value)

        if symbol:
            return symbol

    return None


# ============================================================
# MARKET DISCOVERY
# ============================================================

def get_markets():
    """
    Tries several public Tabdeal endpoints.

    The parser accepts both:
        list
    and:
        {"data": [...]}
        {"result": [...]}
        {"symbols": [...]}

    This prevents:
        'list' object has no attribute 'get'
    """

    endpoints = [
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/markets",
        "/r/api/v1/symbols",
        "/r/api/v1/tickers",
    ]

    symbols = set()

    for endpoint in endpoints:

        data = get_json(BASE_URL + endpoint)

        if data is None:
            continue

        items = as_list(data)

        # Direct list of strings
        for item in items:

            symbol = extract_symbol(item)

            if symbol and symbol.endswith("USDT"):
                symbols.add(symbol)

        if symbols:
            break

    # Remove obviously invalid values
    symbols = {
        s
        for s in symbols
        if s
        and s.endswith("USDT")
        and len(s) > 4
        and len(s) < 30
    }

    symbols = sorted(symbols)

    if MAX_MARKETS:
        symbols = symbols[:MAX_MARKETS]

    return symbols


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):
    """
    Known working Tabdeal public endpoint:
        /r/api/v1/trades
    """

    data = get_json(
        BASE_URL + "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if data is None:
        return []

    return as_list(data)


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if isinstance(item, list):

        if len(item) < 2:
            return None

        price = safe_float(item[0])
        qty = safe_float(item[1])

        timestamp = None

        if len(item) >= 3:
            timestamp = safe_int(item[2])

        if price is None or qty is None:
            return None

        return {
            "price": price,
            "qty": abs(qty),
            "timestamp": timestamp,
        }

    if not isinstance(item, dict):
        return None

    price = None
    qty = None
    timestamp = None

    for key in (
        "price",
        "p",
        "trade_price",
        "rate",
    ):
        if key in item:
            price = safe_float(item.get(key))
            if price is not None:
                break

    for key in (
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
    ):
        if key in item:
            qty = safe_float(item.get(key))
            if qty is not None:
                break

    for key in (
        "timestamp",
        "time",
        "T",
        "created_at",
        "createdAt",
    ):
        if key in item:
            timestamp = safe_int(item.get(key))
            if timestamp is not None:
                break

    if price is None or qty is None:
        return None

    return {
        "price": price,
        "qty": abs(qty),
        "timestamp": timestamp,
    }


# ============================================================
# TIMESTAMP
# ============================================================

def normalize_timestamp(ts):

    if ts is None:
        return None

    # milliseconds
    if ts > 10_000_000_000:
        return ts / 1000.0

    return float(ts)


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade is None:
            continue

        ts = normalize_timestamp(
            trade["timestamp"]
        )

        if ts is None:
            continue

        trade["timestamp"] = ts

        parsed.append(trade)

    if not parsed:
        return []

    parsed.sort(
        key=lambda x: x["timestamp"]
    )

    buckets = {}

    for trade in parsed:

        bucket = int(
            trade["timestamp"] // 300
        ) * 300

        if bucket not in buckets:
            buckets[bucket] = {
                "timestamp": bucket,
                "open": trade["price"],
                "high": trade["price"],
                "low": trade["price"],
                "close": trade["price"],
                "volume": 0.0,
                "trades": 0,
            }

        candle = buckets[bucket]

        price = trade["price"]
        qty = trade["qty"]

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
        candle["trades"] += 1

    candles = list(buckets.values())

    candles.sort(
        key=lambda x: x["timestamp"]
    )

    # Remove current unfinished 5m candle.
    current_bucket = int(
        time.time() // 300
    ) * 300

    candles = [
        c
        for c in candles
        if c["timestamp"] < current_bucket
    ]

    return candles[-CANDLE_LIMIT:]


# ============================================================
# RESAMPLE
# ============================================================

def resample_candles(candles, minutes):

    if not candles:
        return []

    seconds = minutes * 60

    buckets = {}

    for candle in candles:

        bucket = int(
            candle["timestamp"] // seconds
        ) * seconds

        if bucket not in buckets:

            buckets[bucket] = {
                "timestamp": bucket,
                "open": candle["open"],
                "high": candle["high"],
                "low": candle["low"],
                "close": candle["close"],
                "volume": 0.0,
            }

        out = buckets[bucket]

        out["high"] = max(
            out["high"],
            candle["high"],
        )

        out["low"] = min(
            out["low"],
            candle["low"],
        )

        out["close"] = candle["close"]

        out["volume"] += candle["volume"]

    result = list(buckets.values())

    result.sort(
        key=lambda x: x["timestamp"]
    )

    return result


# ============================================================
# MOMENTUM
# ============================================================

def momentum(candles, bars):

    if len(candles) <= bars:
        return 0.0

    old = candles[-bars - 1]["close"]
    new = candles[-1]["close"]

    return pct_change(old, new)


# ============================================================
# VOLUME RATIO
# ============================================================

def volume_ratio(candles, lookback=20):

    if len(candles) < lookback + 1:
        return 0.0

    current = candles[-1]["volume"]

    previous = [
        c["volume"]
        for c in candles[-lookback - 1:-1]
        if c["volume"] > 0
    ]

    if not previous:
        return 0.0

    avg = sum(previous) / len(previous)

    if avg <= 0:
        return 0.0

    return current / avg


# ============================================================
# BREAKOUT
# ============================================================

def breakout_strength(candles, lookback=20):

    if len(candles) < lookback + 2:
        return False, 0.0

    previous = candles[
        -lookback - 1:-1
    ]

    highest = max(
        c["high"]
        for c in previous
    )

    current = candles[-1]

    if current["close"] > highest:

        strength = pct_change(
            highest,
            current["close"],
        )

        return True, strength

    return False, 0.0


# ============================================================
# RETEST
# ============================================================

def retest_signal(candles, lookback=20):

    if len(candles) < lookback + 5:
        return False

    previous = candles[
        -lookback - 5:-1
    ]

    resistance = max(
        c["high"]
        for c in previous
    )

    current = candles[-1]

    # Price must remain close to the broken resistance.
    distance = abs(
        pct_change(
            resistance,
            current["close"],
        )
    )

    if current["close"] >= resistance:
        return True

    if distance <= 1.0:
        return True

    return False


# ============================================================
# HIGHER HIGH / HIGHER LOW
# ============================================================

def structure_up(candles):

    if len(candles) < 8:
        return False

    recent = candles[-6:]

    first_high = max(
        c["high"]
        for c in recent[:3]
    )

    last_high = max(
        c["high"]
        for c in recent[3:]
    )

    first_low = min(
        c["low"]
        for c in recent[:3]
    )

    last_low = min(
        c["low"]
        for c in recent[3:]
    )

    return (
        last_high > first_high
        and last_low >= first_low
    )


# ============================================================
# SCORE ENGINE
# ============================================================

def analyze_symbol(symbol, candles):

    if len(candles) < 60:
        return None

    c5 = candles

    c15 = resample_candles(
        candles,
        15,
    )

    c60 = resample_candles(
        candles,
        60,
    )

    if len(c15) < 8:
        return None

    if len(c60) < 3:
        return None

    m5 = momentum(c5, 1)
    m15 = momentum(c15, 1)
    m60 = momentum(c60, 1)

    vol = volume_ratio(c5)

    is_breakout, breakout_pct = (
        breakout_strength(c5)
    )

    is_retest = retest_signal(c5)

    structure = structure_up(c5)

    score = 0

    # 5m momentum
    if m5 > 1.0:
        score += 1

    # 15m momentum
    if m15 > 2.0:
        score += 1

    # 1h momentum
    if m60 > 3.0:
        score += 1

    # volume
    if vol >= 1.20:
        score += 1

    # breakout
    if is_breakout:
        score += 1

    # retest
    if is_retest:
        score += 1

    # structure
    if structure:
        score += 1

    # Too much vertical movement = danger
    if m5 >= 15.0:
        score -= 1

    if m5 >= 25.0:
        score -= 2

    score = max(
        0,
        min(7, score),
    )

    if score >= 7:
        setup = "ENTRY"

    elif score >= 6:
        setup = "WATCH"

    else:
        setup = "NO TRADE"

    price = c5[-1]["close"]

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "m5": m5,
        "m15": m15,
        "m60": m60,
        "volume": vol,
        "breakout": is_breakout,
        "breakout_pct": breakout_pct,
        "retest": is_retest,
        "structure": structure,
        "setup": setup,
        "candles": len(c5),
    }


# ============================================================
# DISPLAY
# ============================================================

def format_result(index, result):

    return (
        f"{index}. {result['symbol']} | "
        f"{result['setup']}\n"
        f"   💰 {result['price']:.8f}\n"
        f"   📊 Score {result['score']}/7\n"
        f"   5m {result['m5']:+.2f}% | "
        f"15m {result['m15']:+.2f}% | "
        f"1h {result['m60']:+.2f}%\n"
        f"   📈 Vol {result['volume']:.2f}x | "
        f"Candles {result['candles']}\n"
        f"   🚀 Breakout: "
        f"{'YES' if result['breakout'] else 'NO'} | "
        f"Retest: "
        f"{'YES' if result['retest'] else 'NO'} | "
        f"Structure: "
        f"{'UP' if result['structure'] else 'NO'}"
    )


# ============================================================
# MAIN SCANNER
# ============================================================

def run_scanner():

    print()
    print("⚡ ATI CRYPTO BOT V37.0")
    print()
    print("🚀 UPWARD COIN SCANNER")
    print()
    print("⏱ Timeframe: 5m")
    print("✅ CLOSED CANDLE")
    print("📊 5M + 15M + 1H MOMENTUM")
    print("💥 BREAKOUT + RETEST + STRUCTURE")
    print("🔧 CANDLE SOURCE: TABDEAL TRADES → 5M CANDLES")
    print()

    markets = get_markets()

    if not markets:

        error_message = (
            "⚡ ATI CRYPTO BOT V37.0\n\n"
            "❌ TABDEAL MARKET DISCOVERY FAILED\n\n"
            "No USDT markets were returned."
        )

        print(error_message)
        telegram_send(error_message)
        return

    print(
        f"📡 TABDEAL API: OK"
    )

    print(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    print()
    print(
        f"🕐 Scan: {now_utc()}"
    )

    results = []
    unavailable = 0

    for index, symbol in enumerate(markets):

        try:

            trades = get_trades(symbol)

            if not trades:
                unavailable += 1
                continue

            candles = build_candles(
                trades
            )

            if len(candles) < 60:
                unavailable += 1
                continue

            result = analyze_symbol(
                symbol,
                candles,
            )

            if result is None:
                continue

            if result["score"] >= MIN_SCORE:

                results.append(result)

        except Exception as exc:

            # One bad market must NEVER stop
            # the entire scanner.
            print(
                f"⚠️ Skip {symbol}: "
                f"{type(exc).__name__}"
            )

        if index % 50 == 0:
            print(
                f"🔎 Scanned "
                f"{index + 1}/{len(markets)}"
            )

        time.sleep(
            SLEEP_BETWEEN_MARKETS
        )

    # ========================================================
    # SORT
    # ========================================================

    results.sort(
        key=lambda x: (
            x["score"],
            x["m60"],
            x["m15"],
            x["volume"],
        ),
        reverse=True,
    )

    results = results[:TOP_RESULTS]

    # ========================================================
    # MESSAGE
    # ========================================================

    lines = []

    lines.append(
        "⚡ ATI CRYPTO BOT V37.0"
    )

    lines.append("")
    lines.append(
        "🚀 UPWARD COIN SCANNER"
    )

    lines.append("")
    lines.append(
        "⏱ Timeframe: 5m"
    )

    lines.append(
        "✅ CLOSED CANDLE"
    )

    lines.append(
        "📊 5M + 15M + 1H MOMENTUM"
    )

    lines.append(
        "💥 BREAKOUT + RETEST + STRUCTURE"
    )

    lines.append(
        "🔧 CANDLE SOURCE: "
        "TABDEAL TRADES → 5M CANDLES"
    )

    lines.append("")
    lines.append(
        "📡 TABDEAL API: OK"
    )

    lines.append(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    lines.append("")
    lines.append(
        f"🕐 Scan: {now_utc()}"
    )

    lines.append("")
    lines.append(
        f"⚠️ Candle data unavailable: "
        f"{unavailable} markets"
    )

    lines.append("")

    if not results:

        lines.append(
            "🟡 NO STRONG SETUPS"
        )

        lines.append("")
        lines.append(
            "No market passed the V37 "
            "entry filters."
        )

    else:

        lines.append(
            "🔥 STRONG UPWARD SETUPS"
        )

        lines.append("")

        for i, result in enumerate(
            results,
            start=1,
        ):

            lines.append(
                format_result(
                    i,
                    result,
                )
            )

            lines.append("")

        entry = next(
            (
                r
                for r in results
                if r["setup"] == "ENTRY"
            ),
            None,
        )

        if entry:

            lines.append(
                f"🟢 ENTRY CANDIDATE: "
                f"{entry['symbol']}"
            )

        else:

            lines.append(
                "🟡 WATCH ONLY"
            )

    lines.append("")
    lines.append(
        "⚠️ REAL TRADING: DISABLED"
    )

    lines.append(
        "🚫 ORDER EXECUTION: "
        "DISABLED IN V37.0"
    )

    message = "\n".join(lines)

    print()
    print(message)

    telegram_send(message)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        run_scanner()

    except KeyboardInterrupt:

        print(
            "🛑 Scanner stopped."
        )

    except Exception as exc:

        error = (
            "⚡ ATI CRYPTO BOT V37.0\n\n"
            "❌ UNEXPECTED ERROR\n\n"
            f"{type(exc).__name__}: {exc}"
        )

        print(error)

        telegram_send(error)
