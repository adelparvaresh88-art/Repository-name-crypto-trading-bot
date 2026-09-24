import os
import time
import requests
from datetime import datetime, timezone

# ============================================================
# ATI CRYPTO BOT V35.2
# TABDEAL FULL USDT MARKET SCANNER
# CLOSED 5m CANDLE
# BREAKOUT + MOMENTUM ENGINE
# ============================================================

VERSION = "V35.2"

BASE_URL = "https://api1.tabdeal.org"
EXCHANGE_INFO_PATH = "/r/api/v1/exchangeInfo"

TIMEFRAME = "5m"
CANDLE_LIMIT = 60

TOP_RESULTS = 2
MAX_MARKETS = 1000

MIN_SCORE = 4
MIN_MOVE_PERCENT = 0.20
MIN_VOLUME = 1000.0

REQUEST_TIMEOUT = 15
SCAN_DELAY = 0.03

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Real trading intentionally disabled in this scanner version.
ENABLE_REAL_TRADING = False

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT-V35.2",
    "Accept": "application/json",
})


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials are missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:
        response = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        print("Telegram HTTP:", response.status_code)

        if response.ok:
            return True

        print("Telegram response:", response.text[:500])
        return False

    except Exception as exc:
        print("Telegram error:", exc)
        return False


# ============================================================
# SAFE CONVERSION
# ============================================================

def to_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def clean_symbol(value):
    if value is None:
        return ""

    try:
        return (
            str(value)
            .upper()
            .replace("/", "")
            .replace("-", "")
            .replace("_", "")
            .strip()
        )
    except Exception:
        return ""


# ============================================================
# API
# ============================================================

def api_get(path, params=None):
    url = BASE_URL + path

    response = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:
        return response.json()
    except Exception as exc:
        raise RuntimeError(
            f"Invalid JSON response: {exc}"
        )


# ============================================================
# MARKET EXTRACTION
#
# IMPORTANT:
# exchangeInfo may return a LIST directly.
# NEVER call .get() on the root response.
# ============================================================

def extract_market_list(payload):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):
        for key in (
            "data",
            "result",
            "symbols",
            "markets",
            "items",
            "rows",
        ):
            value = payload.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                nested = extract_market_list(value)
                if nested:
                    return nested

    return []


def get_exchange_info():
    payload = api_get(EXCHANGE_INFO_PATH)

    markets = extract_market_list(payload)

    if not markets:
        print(
            "EXCHANGE INFO RESPONSE TYPE:",
            type(payload).__name__,
        )

        if isinstance(payload, dict):
            print(
                "EXCHANGE INFO KEYS:",
                list(payload.keys())[:30],
            )

        elif isinstance(payload, list):
            print(
                "EXCHANGE INFO LIST LENGTH:",
                len(payload),
            )

        raise RuntimeError(
            "exchangeInfo returned no market list"
        )

    return markets


# ============================================================
# MARKET SYMBOL
# ============================================================

def market_symbol(item):
    if isinstance(item, str):
        return clean_symbol(item)

    if not isinstance(item, dict):
        return ""

    for key in (
        "symbol",
        "market",
        "pair",
        "code",
        "name",
    ):
        value = item.get(key)

        if isinstance(value, str):
            symbol = clean_symbol(value)

            if symbol:
                return symbol

    return ""


def market_status(item):
    if not isinstance(item, dict):
        return ""

    for key in (
        "status",
        "state",
        "marketStatus",
    ):
        value = item.get(key)

        if value is not None:
            return str(value).upper()

    return ""


def is_usdt_market(item):
    symbol = market_symbol(item)

    if not symbol.endswith("USDT"):
        return False

    status = market_status(item)

    if status:
        allowed = {
            "TRADING",
            "ACTIVE",
            "ENABLED",
            "ONLINE",
            "OPEN",
        }

        if status not in allowed:
            return False

    return True


# ============================================================
# GET ALL USDT MARKETS
# ============================================================

def get_usdt_markets():

    raw_markets = get_exchange_info()

    symbols = []

    for item in raw_markets:

        if not is_usdt_market(item):
            continue

        symbol = market_symbol(item)

        if not symbol:
            continue

        if symbol not in symbols:
            symbols.append(symbol)

    symbols = symbols[:MAX_MARKETS]

    print(
        "USDT MARKETS:",
        len(symbols),
    )

    return symbols


# ============================================================
# KLINES
# ============================================================

def extract_rows(payload):
    if isinstance(payload, list):
        return payload

    if isinstance(payload, dict):

        for key in (
            "data",
            "result",
            "klines",
            "candles",
            "rows",
            "items",
        ):
            value = payload.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):
                nested = extract_rows(value)

                if nested:
                    return nested

    return []


def get_klines(symbol):

    paths = (
        "/r/api/v1/klines",
        "/api/v1/klines",
        "/r/api/v1/candles",
    )

    parameter_sets = (
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
    )

    last_error = None

    for path in paths:

        for params in parameter_sets:

            try:

                payload = api_get(
                    path,
                    params,
                )

                rows = extract_rows(payload)

                if rows:
                    return rows

            except Exception as exc:
                last_error = exc

    print(
        symbol,
        "KLINE ERROR:",
        last_error,
    )

    return []


# ============================================================
# CANDLE PARSER
# ============================================================

def parse_candle(row):

    if isinstance(row, list):

        if len(row) < 5:
            return None

        return {
            "time": to_float(row[0]),
            "open": to_float(row[1]),
            "high": to_float(row[2]),
            "low": to_float(row[3]),
            "close": to_float(row[4]),
            "volume": (
                to_float(row[5])
                if len(row) > 5
                else 0.0
            ),
        }

    if isinstance(row, dict):

        return {
            "time": to_float(
                row.get(
                    "time",
                    row.get(
                        "timestamp",
                        row.get(
                            "openTime",
                            0,
                        ),
                    ),
                )
            ),
            "open": to_float(
                row.get(
                    "open",
                    row.get("o", 0),
                )
            ),
            "high": to_float(
                row.get(
                    "high",
                    row.get("h", 0),
                )
            ),
            "low": to_float(
                row.get(
                    "low",
                    row.get("l", 0),
                )
            ),
            "close": to_float(
                row.get(
                    "close",
                    row.get("c", 0),
                )
            ),
            "volume": to_float(
                row.get(
                    "volume",
                    row.get("v", 0),
                )
            ),
        }

    return None


def clean_candles(rows):

    candles = []
    seen = set()

    for row in rows:

        candle = parse_candle(row)

        if candle is None:
            continue

        if candle["close"] <= 0:
            continue

        if candle["high"] <= 0:
            continue

        if candle["low"] <= 0:
            continue

        timestamp = candle["time"]

        if timestamp in seen:
            continue

        seen.add(timestamp)
        candles.append(candle)

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ============================================================
# MATH
# ============================================================

def average(values):
    if not values:
        return 0.0

    return sum(values) / len(values)


def pct_change(old, new):
    if old == 0:
        return 0.0

    return (
        (new - old)
        / old
        * 100.0
    )


# ============================================================
# ANALYSIS
# ============================================================

def analyze_market(symbol, candles):

    if len(candles) < 25:
        return None

    # Ignore currently forming candle.
    closed = candles[:-1]

    if len(closed) < 20:
        return None

    current = closed[-1]

    previous = closed[-2]

    price = current["close"]

    if price <= 0:
        return None

    recent5 = closed[-5:]
    recent10 = closed[-10:]
    recent20 = closed[-20:]

    move5 = pct_change(
        recent5[0]["close"],
        price,
    )

    move10 = pct_change(
        recent10[0]["close"],
        price,
    )

    move20 = pct_change(
        recent20[0]["close"],
        price,
    )

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    previous_high = max(
        x["high"]
        for x in closed[-11:-1]
    )

    breakout = (
        price > previous_high
    )

    # --------------------------------------------------------
    # CANDLE STRENGTH
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

    bullish = (
        current["close"]
        > current["open"]
    )

    strong_candle = (
        bullish
        and body_ratio >= 0.45
    )

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    rising_structure = (
        recent5[-1]["high"]
        >= recent5[0]["high"]
        and
        recent5[-1]["low"]
        >= recent5[0]["low"]
    )

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    old_volume = average(
        x["volume"]
        for x in recent20[:10]
    )

    new_volume = average(
        x["volume"]
        for x in recent20[-5:]
    )

    volume_expansion = (
        old_volume > 0
        and
        new_volume >= old_volume * 1.15
    )

    current_volume = current["volume"]

    if current_volume < MIN_VOLUME:
        return None

    # --------------------------------------------------------
    # CLOSE POSITION
    # --------------------------------------------------------

    close_near_high = False

    if candle_range > 0:

        position = (
            current["close"]
            - current["low"]
        ) / candle_range

        close_near_high = (
            position >= 0.70
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

    # Avoid extremely extended moves.
    if move20 < 8.0:
        score += 1

    # --------------------------------------------------------
    # STRONG SETUP FILTER
    # --------------------------------------------------------

    if score < MIN_SCORE:
        return None

    if move5 < MIN_MOVE_PERCENT:
        return None

    if not (
        breakout
        or strong_candle
        or volume_expansion
    ):
        return None

    # --------------------------------------------------------
    # RANGE / SL / TP
    # --------------------------------------------------------

    ranges = [
        x["high"] - x["low"]
        for x in closed[-14:]
    ]

    average_range = average(ranges)

    if average_range <= 0:
        average_range = price * 0.005

    sl_distance = max(
        average_range * 1.5,
        price * 0.006,
    )

    tp_distance = max(
        average_range * 2.4,
        price * 0.010,
    )

    entry = price

    stop_loss = (
        entry - sl_distance
    )

    take_profit = (
        entry + tp_distance
    )

    risk_percent = (
        sl_distance
        / entry
        * 100
    )

    reward_percent = (
        tp_distance
        / entry
        * 100
    )

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
        "previous_close": previous["close"],
    }


# ============================================================
# SCAN
# ============================================================

def scan_symbol(symbol):

    try:

        rows = get_klines(symbol)

        candles = clean_candles(rows)

        if len(candles) < 25:
            return None

        return analyze_market(
            symbol,
            candles,
        )

    except Exception as exc:

        print(
            symbol,
            "ANALYSIS ERROR:",
            exc,
        )

        return None


# ============================================================
# PRICE FORMAT
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
# MESSAGE
# ============================================================

def build_message(
    results,
    market_count,
    scanned_count,
    errors,
):

    scan_time = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
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

    lines.append(
        f"🕐 Scan: {scan_time}"
    )

    if errors:
        lines.append(
            f"⚠️ CANDLE ERRORS: {errors}"
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

        lines.append("")
        lines.append(
            "🛡 MODE: PAPER / TEST"
        )

        lines.append(
            "🚫 REAL TRADING: DISABLED"
        )

        return "\n".join(lines)

    lines.append(
        f"🔥 TOP {len(results)} "
        "UPWARD OPPORTUNITIES"
    )

    lines.append("")

    for index, result in enumerate(
        results,
        start=1,
    ):

        lines.append(
            f"🟢 #{index} "
            f"{result['symbol']}"
        )

        lines.append(
            f"💰 Price: "
            f"${fmt_price(result['price'])}"
        )

        lines.append(
            f"📈 SCORE: "
            f"{result['score']}/8"
        )

        lines.append(
            f"🚀 5m MOVE: "
            f"{result['move5']:.2f}%"
        )

        lines.append(
            f"📊 10m MOVE: "
            f"{result['move10']:.2f}%"
        )

        lines.append(
            "💥 BREAKOUT: "
            + (
                "YES"
                if result["breakout"]
                else "NO"
            )
        )

        lines.append(
            "📦 VOLUME: "
            + (
                "EXPANSION"
                if result["volume_expansion"]
                else "NORMAL"
            )
        )

        lines.append("")

        lines.append(
            f"🎯 ENTRY: "
            f"${fmt_price(result['entry'])}"
        )

        lines.append(
            f"🛑 SL: "
            f"${fmt_price(result['sl'])}"
        )

        lines.append(
            f"🎯 TP: "
            f"${fmt_price(result['tp'])}"
        )

        lines.append(
            f"⚖️ RISK: "
            f"{result['risk_percent']:.2f}%"
        )

        lines.append(
            f"💎 REWARD: "
            f"{result['reward_percent']:.2f}%"
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
        f"ATI CRYPTO BOT {VERSION}"
    )
    print(
        "FULL USDT MARKET SCANNER"
    )
    print("=" * 60)

    try:

        symbols = get_usdt_markets()

    except Exception as exc:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "❌ TABDEAL API ERROR\n\n"
            f"{exc}"
        )

        print(message)

        send_telegram(message)

        return

    if not symbols:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            "❌ NO USDT MARKETS FOUND"
        )

        print(message)

        send_telegram(message)

        return

    results = []

    scanned = 0
    errors = 0

    total = len(symbols)

    print(
        f"Starting scan of {total} "
        "USDT markets..."
    )

    for index, symbol in enumerate(
        symbols,
        start=1,
    ):

        print(
            f"[{index}/{total}] {symbol}"
        )

        try:

            result = scan_symbol(
                symbol
            )

            scanned += 1

            if result is not None:
                results.append(result)

        except Exception as exc:

            errors += 1

            print(
                symbol,
                "ERROR:",
                exc,
            )

        time.sleep(
            SCAN_DELAY
        )

    results.sort(
        key=lambda item: (
            item["score"],
            item["move5"],
            item["move10"],
        ),
        reverse=True,
    )

    results = results[:TOP_RESULTS]

    message = build_message(
        results=results,
        market_count=total,
        scanned_count=scanned,
        errors=errors,
    )

    print("")
    print(message)
    print("")

    send_telegram(message)

    print(
        "ATI CRYPTO BOT FINISHED."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
```0
