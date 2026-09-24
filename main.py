import os
import time
import math
import requests
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT V35.1
# TABDEAL - FULL USDT MARKET SCANNER
# CLOSED 5m CANDLE
# BREAKOUT + MOMENTUM
# ============================================================

BOT_VERSION = "V35.1"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# ------------------------------------------------------------
# SAFETY
# ------------------------------------------------------------

ENABLE_REAL_TRADING = False

REQUEST_TIMEOUT = 15
MAX_MARKETS = 1000
CANDLE_LIMIT = 60

TOP_RESULTS = 2

# Minimum filters
MIN_QUOTE_VOLUME = 1000.0
MIN_MOVE_PERCENT = 0.20
MIN_SCORE = 4

# ------------------------------------------------------------
# HTTP SESSION
# ------------------------------------------------------------

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT/35.1",
    "Accept": "application/json",
})


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM credentials missing")
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
        r = session.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        print("Telegram:", r.status_code)

        if r.ok:
            return True

        print(r.text[:500])
        return False

    except Exception as e:
        print("Telegram error:", e)
        return False


# ============================================================
# SAFE NUMBER
# ============================================================

def num(value, default=0.0):
    try:
        if value is None:
            return default

        if isinstance(value, bool):
            return default

        return float(value)

    except Exception:
        return default


# ============================================================
# SAFE TEXT
# ============================================================

def text_value(value, default=""):
    if value is None:
        return default

    try:
        return str(value)
    except Exception:
        return default


# ============================================================
# GENERIC API REQUEST
# ============================================================

def api_get(path, params=None):
    url = BASE_URL + path

    try:
        r = session.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if not r.ok:
            raise RuntimeError(
                f"HTTP {r.status_code}: {r.text[:300]}"
            )

        return r.json()

    except Exception as e:
        raise RuntimeError(str(e))


# ============================================================
# RESPONSE NORMALIZER
#
# IMPORTANT:
# Tabdeal responses may be:
#
#   list
#   {"data": [...]}
#   {"result": [...]}
#   {"symbols": [...]}
#   {"data": {"symbols": [...]}}
#
# Never call .get() directly on unknown response.
# ============================================================

def find_list(obj, depth=0):
    if depth > 6:
        return []

    if isinstance(obj, list):
        return obj

    if isinstance(obj, dict):

        preferred = [
            "data",
            "result",
            "symbols",
            "markets",
            "items",
            "rows",
            "tickers",
        ]

        for key in preferred:
            if key in obj:
                value = obj[key]

                if isinstance(value, list):
                    return value

                if isinstance(value, dict):
                    found = find_list(value, depth + 1)

                    if found:
                        return found

        for value in obj.values():

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                found = find_list(value, depth + 1)

                if found:
                    return found

    return []


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    possible_paths = [
        "/api/v1/exchangeInfo",
        "/api/v1/exchange/info",
    ]

    last_error = None

    for path in possible_paths:

        try:
            raw = api_get(path)

            markets = find_list(raw)

            if markets:
                print(
                    f"Exchange info OK: "
                    f"{len(markets)} raw records"
                )

                return markets

        except Exception as e:
            last_error = e

    raise RuntimeError(
        f"Could not read exchange markets: {last_error}"
    )


# ============================================================
# SYMBOL EXTRACTION
# ============================================================

def extract_symbol(item):

    if isinstance(item, str):
        return item.upper()

    if not isinstance(item, dict):
        return ""

    possible = [
        "symbol",
        "market",
        "code",
        "name",
        "pair",
    ]

    for key in possible:

        value = item.get(key)

        if isinstance(value, str):
            return value.upper()

    return ""


# ============================================================
# ACTIVE USDT MARKETS
# ============================================================

def get_usdt_markets():

    raw_markets = get_exchange_info()

    symbols = []

    for item in raw_markets:

        symbol = extract_symbol(item)

        if not symbol:
            continue

        symbol = symbol.replace("-", "").replace("/", "")

        if not symbol.endswith("USDT"):
            continue

        # Avoid malformed symbols
        if len(symbol) < 6:
            continue

        if symbol not in symbols:
            symbols.append(symbol)

    symbols = symbols[:MAX_MARKETS]

    print(
        f"USDT MARKETS FOUND: {len(symbols)}"
    )

    return symbols


# ============================================================
# KLINES
# ============================================================

def get_klines(symbol):

    paths = [
        "/api/v1/klines",
        "/api/v1/market/klines",
    ]

    last_error = None

    params_list = [
        {
            "symbol": symbol,
            "interval": TIMEFRAME,
            "limit": CANDLE_LIMIT,
        },
        {
            "symbol": symbol,
            "timeframe": TIMEFRAME,
            "limit": CANDLE_LIMIT,
        },
    ]

    for path in paths:

        for params in params_list:

            try:

                raw = api_get(
                    path,
                    params=params
                )

                rows = find_list(raw)

                if rows:
                    return rows

            except Exception as e:
                last_error = e

    print(
        f"{symbol}: candle error: {last_error}"
    )

    return []


# ============================================================
# CANDLE PARSER
# ============================================================

def parse_candle(row):

    if isinstance(row, list):

        if len(row) < 5:
            return None

        try:

            return {
                "time": num(row[0]),
                "open": num(row[1]),
                "high": num(row[2]),
                "low": num(row[3]),
                "close": num(row[4]),
                "volume": num(
                    row[5]
                    if len(row) > 5
                    else 0
                ),
            }

        except Exception:
            return None

    if isinstance(row, dict):

        return {
            "time": num(
                row.get("time",
                row.get("timestamp",
                row.get("openTime", 0)))
            ),

            "open": num(
                row.get("open",
                row.get("o", 0))
            ),

            "high": num(
                row.get("high",
                row.get("h", 0))
            ),

            "low": num(
                row.get("low",
                row.get("l", 0))
            ),

            "close": num(
                row.get("close",
                row.get("c", 0))
            ),

            "volume": num(
                row.get("volume",
                row.get("v", 0))
            ),
        }

    return None


# ============================================================
# CLEAN CANDLES
# ============================================================

def clean_candles(rows):

    candles = []

    for row in rows:

        candle = parse_candle(row)

        if not candle:
            continue

        if candle["close"] <= 0:
            continue

        if candle["high"] <= 0:
            continue

        if candle["low"] <= 0:
            continue

        candles.append(candle)

    candles.sort(
        key=lambda x: x["time"]
    )

    # Remove possible duplicate timestamps
    result = []

    seen = set()

    for c in candles:

        t = c["time"]

        if t in seen:
            continue

        seen.add(t)
        result.append(c)

    return result


# ============================================================
# INDICATOR HELPERS
# No EMA required.
# ============================================================

def highest(values):
    return max(values) if values else 0


def lowest(values):
    return min(values) if values else 0


def average(values):

    if not values:
        return 0

    return sum(values) / len(values)


def percent_change(old, new):

    if old == 0:
        return 0

    return ((new - old) / old) * 100


# ============================================================
# MARKET ANALYSIS
# ============================================================

def analyze_market(symbol, candles):

    if len(candles) < 25:
        return None

    # --------------------------------------------------------
    # CLOSED CANDLE
    # Last candle is excluded to avoid unfinished candle.
    # --------------------------------------------------------

    closed = candles[:-1]

    if len(closed) < 20:
        return None

    current = closed[-1]
    previous = closed[-2]

    price = current["close"]

    if price <= 0:
        return None

    # --------------------------------------------------------
    # Recent candles
    # --------------------------------------------------------

    recent5 = closed[-5:]
    recent10 = closed[-10:]
    recent20 = closed[-20:]

    highs10 = [
        x["high"]
        for x in recent10
    ]

    highs20 = [
        x["high"]
        for x in recent20
    ]

    lows10 = [
        x["low"]
        for x in recent10
    ]

    lows20 = [
        x["low"]
        for x in recent20
    ]

    volumes20 = [
        x["volume"]
        for x in recent20
    ]

    # --------------------------------------------------------
    # 1. Momentum
    # --------------------------------------------------------

    move5 = percent_change(
        recent5[0]["close"],
        price
    )

    move10 = percent_change(
        recent10[0]["close"],
        price
    )

    # --------------------------------------------------------
    # 2. Breakout
    # --------------------------------------------------------

    previous_high10 = highest(
        [
            x["high"]
            for x in closed[-11:-1]
        ]
    )

    breakout = (
        price > previous_high10
    )

    # --------------------------------------------------------
    # 3. Candle strength
    # --------------------------------------------------------

    candle_range = (
        current["high"]
        - current["low"]
    )

    body = abs(
        current["close"]
        - current["open"]
    )

    body_ratio = (
        body / candle_range
        if candle_range > 0
        else 0
    )

    bullish_candle = (
        current["close"]
        > current["open"]
    )

    strong_candle = (
        bullish_candle
        and body_ratio >= 0.45
    )

    # --------------------------------------------------------
    # 4. Higher highs / higher lows
    # --------------------------------------------------------

    rising_structure = (
        recent5[-1]["high"]
        >= recent5[0]["high"]
        and
        recent5[-1]["low"]
        >= recent5[0]["low"]
    )

    # --------------------------------------------------------
    # 5. Volume expansion
    # --------------------------------------------------------

    old_volume = average(
        volumes20[:10]
    )

    new_volume = average(
        volumes20[-5:]
    )

    volume_expansion = (
        old_volume > 0
        and new_volume >= old_volume * 1.15
    )

    # --------------------------------------------------------
    # 6. Close near high
    # --------------------------------------------------------

    close_near_high = False

    if candle_range > 0:

        close_position = (
            current["close"]
            - current["low"]
        ) / candle_range

        close_near_high = (
            close_position >= 0.70
        )

    # --------------------------------------------------------
    # 7. Not already too extended
    # --------------------------------------------------------

    move20 = percent_change(
        recent20[0]["close"],
        price
    )

    not_overextended = (
        move20 < 8.0
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0

    if move5 >= MIN_MOVE_PERCENT:
        score += 1

    if move10 > 0:
        score += 1

    if breakout:
        score += 1

    if strong_candle:
        score += 1

    if volume_expansion:
        score += 1

    if rising_structure:
        score += 1

    if close_near_high:
        score += 1

    if not_overextended:
        score += 1

    # --------------------------------------------------------
    # Volume filter
    # --------------------------------------------------------

    current_volume = current["volume"]

    if current_volume < MIN_QUOTE_VOLUME:
        return None

    # --------------------------------------------------------
    # Require strong upward setup
    # --------------------------------------------------------

    if score < MIN_SCORE:
        return None

    if move5 < MIN_MOVE_PERCENT:
        return None

    if not (
        breakout
        or
        strong_candle
        or
        volume_expansion
    ):
        return None

    # --------------------------------------------------------
    # Entry
    # --------------------------------------------------------

    entry = price

    # ATR-like range using recent candles
    ranges = [
        x["high"] - x["low"]
        for x in closed[-14:]
    ]

    avg_range = average(ranges)

    if avg_range <= 0:
        avg_range = entry * 0.005

    # Conservative SL/TP
    sl_distance = max(
        avg_range * 1.5,
        entry * 0.006
    )

    tp_distance = max(
        avg_range * 2.4,
        entry * 0.010
    )

    stop_loss = entry - sl_distance
    take_profit = entry + tp_distance

    risk_percent = (
        sl_distance / entry
    ) * 100

    reward_percent = (
        tp_distance / entry
    ) * 100

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "move5": move5,
        "move10": move10,
        "move20": move20,
        "breakout": breakout,
        "strong_candle": strong_candle,
        "volume_expansion": volume_expansion,
        "rising_structure": rising_structure,
        "close_near_high": close_near_high,
        "entry": entry,
        "sl": stop_loss,
        "tp": take_profit,
        "risk_percent": risk_percent,
        "reward_percent": reward_percent,
        "volume": current_volume,
        "candle_time": current["time"],
    }


# ============================================================
# SCAN ONE MARKET
# ============================================================

def scan_symbol(symbol):

    try:

        rows = get_klines(symbol)

        candles = clean_candles(rows)

        if len(candles) < 25:
            return None

        result = analyze_market(
            symbol,
            candles
        )

        return result

    except Exception as e:

        print(
            f"{symbol}: analysis error: {e}"
        )

        return None


# ============================================================
# FORMAT PRICE
# ============================================================

def fmt_price(value):

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:,.4f}"

    if value >= 0.01:
        return f"{value:,.6f}"

    return f"{value:.10f}"


# ============================================================
# BUILD TELEGRAM MESSAGE
# ============================================================

def build_message(
    results,
    market_count,
    scanned_count,
    error_count,
):

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT {BOT_VERSION}"
    )

    lines.append("")
    lines.append(
        "🚀 UPWARD COIN SCANNER"
    )

    lines.append(
        f"⏱ Timeframe: {TIMEFRAME}"
    )

    lines.append(
        "✅ CLOSED CANDLE"
    )

    lines.append(
        "💥 BREAKOUT + MOMENTUM ENGINE"
    )

    lines.append("")
    lines.append(
        "📡 TABDEAL API: OK"
    )

    lines.append(
        f"📊 USDT MARKETS: {market_count}"
    )

    lines.append(
        f"🔎 SCANNED: {scanned_count}"
    )

    if error_count:
        lines.append(
            f"⚠️ CANDLE ERRORS: {error_count}"
        )

    lines.append(
        f"🕐 Scan: {now}"
    )

    lines.append("")

    if not results:

        lines.append(
            "⚪ NO STRONG UPWARD SETUP"
        )

        lines.append("")
        lines.append(
            "⏳ Waiting for confirmed breakout..."
        )

        return "\n".join(lines)

    lines.append(
        f"🔥 TOP {len(results)} UPWARD OPPORTUNITIES"
    )

    lines.append("")

    for i, r in enumerate(
        results,
        start=1
    ):

        lines.append(
            f"🟢 #{i} {r['symbol']}"
        )

        lines.append(
            f"💰 Price: ${fmt_price(r['price'])}"
        )

        lines.append(
            f"📈 SCORE: {r['score']}/8"
        )

        lines.append(
            f"🚀 5m MOVE: {r['move5']:.2f}%"
        )

        lines.append(
            f"📊 10m MOVE: {r['move10']:.2f}%"
        )

        lines.append(
            f"💥 BREAKOUT: "
            f"{'YES' if r['breakout'] else 'NO'}"
        )

        lines.append(
            f"📦 VOLUME: "
            f"{'EXPANSION' if r['volume_expansion'] else 'NORMAL'}"
        )

        lines.append("")

        lines.append(
            f"🎯 ENTRY: ${fmt_price(r['entry'])}"
        )

        lines.append(
            f"🛑 SL: ${fmt_price(r['sl'])}"
        )

        lines.append(
            f"🎯 TP: ${fmt_price(r['tp'])}"
        )

        lines.append(
            f"⚖️ RISK: {r['risk_percent']:.2f}%"
        )

        lines.append(
            f"💎 REWARD: {r['reward_percent']:.2f}%"
        )

        lines.append("")

    lines.append(
        "🛡 MODE: PAPER / TEST"
    )

    lines.append(
        "🚫 REAL TRADING: DISABLED"
    )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)

    print(
        f"ATI CRYPTO BOT {BOT_VERSION}"
    )

    print(
        "Starting full USDT market scanner..."
    )

    print("=" * 60)

    # --------------------------------------------------------
    # TELEGRAM START TEST
    # --------------------------------------------------------

    if not TELEGRAM_BOT_TOKEN:
        print(
            "WARNING: TELEGRAM_BOT_TOKEN missing"
        )

    if not TELEGRAM_CHAT_ID:
        print(
            "WARNING: TELEGRAM_CHAT_ID missing"
        )

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    try:

        symbols = get_usdt_markets()

    except Exception as e:

        error_message = (
            f"⚡ ATI CRYPTO BOT {BOT_VERSION}\n\n"
            f"❌ TABDEAL API ERROR\n\n"
            f"{e}"
        )

        print(error_message)

        send_telegram(
            error_message
        )

        return

    if not symbols:

        message = (
            f"⚡ ATI CRYPTO BOT {BOT_VERSION}\n\n"
            "❌ NO USDT MARKETS FOUND"
        )

        print(message)

        send_telegram(message)

        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results = []

    scanned_count = 0
    error_count = 0

    total = len(symbols)

    print(
        f"Scanning {total} USDT markets..."
    )

    for index, symbol in enumerate(
        symbols,
        start=1
    ):

        print(
            f"[{index}/{total}] {symbol}"
        )

        try:

            result = scan_symbol(
                symbol
            )

            scanned_count += 1

            if result:
                results.append(result)

        except Exception as e:

            error_count += 1

            print(
                f"{symbol}: {e}"
            )

        # Small delay to reduce API pressure
        time.sleep(0.03)

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["score"],
            x["move5"],
            x["move10"],
        ),
        reverse=True,
    )

    results = results[
        :TOP_RESULTS
    ]

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    message = build_message(
        results=results,
        market_count=total,
        scanned_count=scanned_count,
        error_count=error_count,
    )

    print("")
    print(message)
    print("")

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    send_telegram(message)

    print(
        "ATI BOT FINISHED."
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()
