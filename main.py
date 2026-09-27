import os
import time
import math
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V38.1.2
# BREAKOUT + RETEST SCANNER
# TABDEAL SPOT MARKET DATA
# ============================================================

VERSION = "V38.1.2"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

CANDLE_LIMIT = 120
TRADE_LIMIT = 500

MAX_MARKETS = 1000
TOP_RESULTS = 10

BUY_MIN_SCORE = 11
WATCH_MIN_SCORE = 8

CHASE_LIMIT_5M = 7.0

REQUEST_TIMEOUT = 15
MAX_WORKERS = 8

# ------------------------------------------------------------
# Telegram
# ------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# ------------------------------------------------------------
# Safety
# ------------------------------------------------------------

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

# IMPORTANT:
# V38.1.2 DOES NOT PLACE ORDERS.
ORDER_EXECUTION_ENABLED = False


# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": "ATI-Bot/38.1.2",
        "Accept": "application/json",
    }
)


# ============================================================
# HELPERS
# ============================================================

def now_text():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        if value is None:
            return default

        if isinstance(value, bool):
            return default

        return float(value)

    except Exception:
        return default


def safe_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default


def pct_change(old, new):
    old = safe_float(old)
    new = safe_float(new)

    if old == 0:
        return 0.0

    return ((new - old) / old) * 100.0


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM CONFIG ERROR")
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
        response = session.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 200:
            return True

        print(
            "TELEGRAM ERROR:",
            response.status_code,
            response.text[:500],
        )

    except Exception as exc:
        print("TELEGRAM EXCEPTION:", exc)

    return False


# ============================================================
# TABDEAL REQUEST
# ============================================================

def tabdeal_get(path, params=None):
    url = BASE_URL + path

    try:
        response = session.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            print(
                "TABDEAL HTTP ERROR:",
                response.status_code,
                path,
                response.text[:300],
            )
            return None

        try:
            return response.json()

        except Exception:
            print(
                "TABDEAL JSON ERROR:",
                path,
                response.text[:300],
            )
            return None

    except requests.RequestException as exc:
        print("TABDEAL REQUEST ERROR:", path, exc)
        return None

    except Exception as exc:
        print("TABDEAL UNKNOWN ERROR:", path, exc)
        return None


# ============================================================
# NORMALIZE EXCHANGE INFO
# ============================================================

def extract_market_list(data):
    """
    Handles different possible Tabdeal exchangeInfo structures.

    Possible forms:
      [...]
      {"symbols": [...]}
      {"data": [...]}
      {"result": [...]}
      {"markets": [...]}
      {"data": {"symbols": [...]}}
    """

    if data is None:
        return []

    # --------------------------------------------------------
    # Direct list
    # --------------------------------------------------------

    if isinstance(data, list):
        return data

    # --------------------------------------------------------
    # Dictionary
    # --------------------------------------------------------

    if isinstance(data, dict):

        for key in (
            "symbols",
            "markets",
            "data",
            "result",
            "items",
        ):

            value = data.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, dict):

                for nested_key in (
                    "symbols",
                    "markets",
                    "data",
                    "result",
                    "items",
                ):

                    nested = value.get(nested_key)

                    if isinstance(nested, list):
                        return nested

    return []


# ============================================================
# MARKET SYMBOL NORMALIZATION
# ============================================================

def normalize_symbol(item):
    if isinstance(item, str):
        return item.upper().replace("_", "")

    if not isinstance(item, dict):
        return ""

    candidates = (
        item.get("symbol"),
        item.get("market"),
        item.get("pair"),
        item.get("name"),
    )

    for value in candidates:

        if isinstance(value, str):

            symbol = value.upper().replace("_", "")

            if symbol.endswith("USDT"):
                return symbol

    return ""


def is_active_market(item):
    if not isinstance(item, dict):
        return True

    status = str(
        item.get("status")
        or item.get("state")
        or ""
    ).upper()

    if not status:
        return True

    blocked = {
        "BREAK",
        "HALT",
        "HALTED",
        "CLOSED",
        "DISABLED",
        "OFFLINE",
    }

    return status not in blocked


# ============================================================
# GET MARKETS
# ============================================================

def get_usdt_markets():

    data = tabdeal_get(
        "/r/api/v1/exchangeInfo"
    )

    if data is None:
        raise RuntimeError(
            "TABDEAL MARKET DATA ERROR: empty response"
        )

    raw_markets = extract_market_list(data)

    if not raw_markets:

        # Some API responses may require an explicit symbol.
        # Test BTCUSDT so the error becomes useful.
        test = tabdeal_get(
            "/r/api/v1/exchangeInfo",
            {"symbol": "BTCUSDT"},
        )

        if test is not None:

            test_list = extract_market_list(test)

            if test_list:
                raw_markets = test_list

    if not raw_markets:
        raise RuntimeError(
            "TABDEAL MARKET DATA ERROR: "
            "exchangeInfo returned no market list"
        )

    symbols = []

    for item in raw_markets:

        if not is_active_market(item):
            continue

        symbol = normalize_symbol(item)

        if not symbol:
            continue

        if not symbol.endswith("USDT"):
            continue

        if symbol not in symbols:
            symbols.append(symbol)

    symbols.sort()

    return symbols[:MAX_MARKETS]


# ============================================================
# TRADES -> 5M CANDLES
# ============================================================

def parse_trade(item):

    if isinstance(item, dict):

        price = (
            item.get("price")
            or item.get("p")
            or item.get("lastPrice")
        )

        qty = (
            item.get("qty")
            or item.get("quantity")
            or item.get("q")
            or item.get("amount")
        )

        timestamp = (
            item.get("time")
            or item.get("timestamp")
            or item.get("T")
            or item.get("tradeTime")
        )

        return (
            safe_float(price),
            safe_float(qty, 1.0),
            safe_int(timestamp),
        )

    if isinstance(item, list):

        if len(item) >= 3:

            return (
                safe_float(item[1]),
                safe_float(item[2], 1.0),
                safe_int(item[0]),
            )

    return 0.0, 0.0, 0


def normalize_timestamp(ts):

    if ts <= 0:
        return 0

    # milliseconds
    if ts > 10_000_000_000:
        return ts // 1000

    return ts


def trades_to_candles(trades):

    parsed = []

    for item in trades:

        price, qty, timestamp = parse_trade(item)

        if price <= 0:
            continue

        timestamp = normalize_timestamp(timestamp)

        if timestamp <= 0:
            continue

        parsed.append(
            (
                timestamp,
                price,
                qty,
            )
        )

    if not parsed:
        return []

    parsed.sort(key=lambda x: x[0])

    buckets = {}

    bucket_seconds = 5 * 60

    for timestamp, price, qty in parsed:

        bucket = (
            timestamp // bucket_seconds
        ) * bucket_seconds

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

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ============================================================
# GET CANDLES FOR SYMBOL
# ============================================================

def get_candles(symbol):

    data = tabdeal_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    )

    if data is None:
        return []

    trades = []

    if isinstance(data, list):
        trades = data

    elif isinstance(data, dict):

        for key in (
            "data",
            "trades",
            "result",
            "items",
        ):

            value = data.get(key)

            if isinstance(value, list):
                trades = value
                break

    if not trades:
        return []

    candles = trades_to_candles(
        trades
    )

    return candles[-CANDLE_LIMIT:]


# ============================================================
# TECHNICAL HELPERS
# ============================================================

def highest(candles, count):
    if len(candles) < count:
        return 0.0

    return max(
        c["high"]
        for c in candles[-count:]
    )


def lowest(candles, count):
    if len(candles) < count:
        return 0.0

    return min(
        c["low"]
        for c in candles[-count:]
    )


def average(values):

    values = [
        safe_float(x)
        for x in values
        if safe_float(x) > 0
    ]

    if not values:
        return 0.0

    return sum(values) / len(values)


def candle_body(c):
    return abs(
        c["close"] - c["open"]
    )


def candle_range(c):
    return max(
        c["high"] - c["low"],
        0.0000000001,
    )


def body_ratio(c):
    return candle_body(c) / candle_range(c)


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(symbol):

    try:

        candles = get_candles(symbol)

        if len(candles) < 25:
            return None

        # --------------------------------------------
        # CLOSED CANDLE
        # --------------------------------------------

        closed = candles[:-1]

        if len(closed) < 24:
            return None

        current = closed[-1]

        prev = closed[-2]

        price = current["close"]

        if price <= 0:
            return None

        # --------------------------------------------
        # MOMENTUM
        # --------------------------------------------

        change_5m = pct_change(
            closed[-2]["close"],
            closed[-1]["close"],
        )

        if len(closed) >= 4:

            change_15m = pct_change(
                closed[-4]["close"],
                closed[-1]["close"],
            )

        else:
            change_15m = 0.0

        if len(closed) >= 13:

            change_1h = pct_change(
                closed[-13]["close"],
                closed[-1]["close"],
            )

        else:
            change_1h = 0.0

        # --------------------------------------------
        # RECENT RANGE
        # --------------------------------------------

        resistance = highest(
            closed[:-1],
            20,
        )

        support = lowest(
            closed[:-1],
            20,
        )

        if resistance <= 0 or support <= 0:
            return None

        # --------------------------------------------
        # BREAKOUT
        # --------------------------------------------

        breakout = (
            current["close"]
            > resistance
        )

        breakout_strength = 0.0

        if resistance > 0:

            breakout_strength = (
                (current["close"] - resistance)
                / resistance
            ) * 100.0

        # --------------------------------------------
        # RETEST
        # --------------------------------------------

        recent_low = min(
            c["low"]
            for c in closed[-3:]
        )

        retest_distance = 0.0

        if resistance > 0:

            retest_distance = abs(
                recent_low - resistance
            ) / resistance * 100.0

        retest = (
            resistance > 0
            and retest_distance <= 1.2
            and current["close"] >= resistance
        )

        # --------------------------------------------
        # BODY
        # --------------------------------------------

        strong_body = (
            body_ratio(current) >= 0.55
        )

        bullish_candle = (
            current["close"]
            > current["open"]
        )

        # --------------------------------------------
        # VOLUME
        # --------------------------------------------

        volumes = [
            c["volume"]
            for c in closed[-21:-1]
        ]

        avg_volume = average(
            volumes
        )

        volume_ok = (
            avg_volume > 0
            and current["volume"]
            >= avg_volume * 1.15
        )

        # --------------------------------------------
        # STRUCTURE
        # --------------------------------------------

        last_high = closed[-2]["high"]
        last_low = closed[-2]["low"]

        structure_up = (
            current["high"] >= last_high
            and current["low"] >= last_low
        )

        # --------------------------------------------
        # SCORE
        # --------------------------------------------

        score = 0

        reasons = []

        # 5M momentum
        if change_5m > 0.20:
            score += 2
            reasons.append("5M+")

        elif change_5m > 0:
            score += 1

        # 15M momentum
        if change_15m > 0.40:
            score += 2
            reasons.append("15M+")

        elif change_15m > 0:
            score += 1

        # 1H momentum
        if change_1h > 0.80:
            score += 2
            reasons.append("1H+")

        elif change_1h > 0:
            score += 1

        # breakout
        if breakout:
            score += 3
            reasons.append("BREAKOUT")

        # breakout strength
        if breakout_strength >= 0.20:
            score += 1
            reasons.append("STRONG-BREAK")

        # retest
        if retest:
            score += 3
            reasons.append("RETEST")

        # volume
        if volume_ok:
            score += 2
            reasons.append("VOLUME")

        # candle
        if bullish_candle:
            score += 1

        if strong_body:
            score += 1
            reasons.append("BODY")

        # structure
        if structure_up:
            score += 1
            reasons.append("STRUCTURE")

        # --------------------------------------------
        # CHASE PROTECTION
        # --------------------------------------------

        chase = (
            change_5m >= CHASE_LIMIT_5M
        )

        if chase:
            score -= 4

        # --------------------------------------------
        # QUALITY FILTER
        # --------------------------------------------

        if price <= 0:
            return None

        # Need at least basic upward structure.
        if (
            change_15m <= 0
            and change_1h <= 0
            and not breakout
        ):
            return None

        # --------------------------------------------
        # SIGNAL TYPE
        # --------------------------------------------

        if score >= BUY_MIN_SCORE:

            signal = "BUY"

        elif score >= WATCH_MIN_SCORE:

            signal = "WATCH"

        else:

            return None

        # --------------------------------------------
        # SL / TP
        # --------------------------------------------

        if support > 0:

            sl_distance = (
                (price - support)
                / price
            ) * 100.0

            sl_distance = clamp(
                sl_distance,
                0.50,
                2.50,
            )

        else:

            sl_distance = 1.0

        # TP based on risk
        risk = sl_distance

        tp1_pct = clamp(
            risk * 1.4,
            0.80,
            3.50,
        )

        tp2_pct = clamp(
            risk * 2.2,
            1.20,
            6.00,
        )

        sl_price = (
            price
            * (1 - sl_distance / 100)
        )

        tp1_price = (
            price
            * (1 + tp1_pct / 100)
        )

        tp2_price = (
            price
            * (1 + tp2_pct / 100)
        )

        return {
            "symbol": symbol,
            "signal": signal,
            "score": score,
            "price": price,
            "change_5m": change_5m,
            "change_15m": change_15m,
            "change_1h": change_1h,
            "resistance": resistance,
            "support": support,
            "breakout": breakout,
            "retest": retest,
            "volume_ok": volume_ok,
            "chase": chase,
            "sl": sl_price,
            "tp1": tp1_price,
            "tp2": tp2_price,
            "sl_pct": sl_distance,
            "tp1_pct": tp1_pct,
            "tp2_pct": tp2_pct,
            "reasons": reasons,
        }

    except Exception as exc:

        print(
            f"ANALYZE ERROR {symbol}:",
            exc,
        )

        return None


# ============================================================
# FORMAT PRICE
# ============================================================

def format_price(price):

    if price >= 1000:
        return f"{price:.2f}"

    if price >= 1:
        return f"{price:.5f}"

    if price >= 0.01:
        return f"{price:.7f}"

    return f"{price:.10f}"


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(item, rank):

    emoji = (
        "🟢"
        if item["signal"] == "BUY"
        else "🟡"
    )

    lines = [
        f"{emoji} #{rank} {item['signal']}",
        f"🪙 {item['symbol']}",
        f"⭐ SCORE: {item['score']}",
        f"💰 PRICE: {format_price(item['price'])}",
        f"📈 5M: {item['change_5m']:+.2f}%",
        f"📊 15M: {item['change_15m']:+.2f}%",
        f"🕐 1H: {item['change_1h']:+.2f}%",
    ]

    if item["breakout"]:
        lines.append("🚀 BREAKOUT: YES")

    if item["retest"]:
        lines.append("🔄 RETEST: YES")

    if item["volume_ok"]:
        lines.append("📦 VOLUME: STRONG")

    if item["chase"]:
        lines.append("⚠️ CHASE FILTER ACTIVE")

    lines.extend(
        [
            "",
            f"🛑 SL: {format_price(item['sl'])}"
            f" (-{item['sl_pct']:.2f}%)",
            f"🎯 TP1: {format_price(item['tp1'])}"
            f" (+{item['tp1_pct']:.2f}%)",
            f"🎯 TP2: {format_price(item['tp2'])}"
            f" (+{item['tp2_pct']:.2f}%)",
            "",
            "🔎 " + " | ".join(
                item["reasons"][:8]
            ),
        ]
    )

    return "\n".join(lines)


# ============================================================
# MAIN SCANNER
# ============================================================

def run_scanner():

    print("=" * 60)
    print(f"ATI CRYPTO BOT {VERSION}")
    print("BREAKOUT + RETEST SCANNER")
    print("=" * 60)

    print("TIME:", now_text())

    # --------------------------------------------------------
    # API TEST
    # --------------------------------------------------------

    ping = tabdeal_get(
        "/r/fapi/v1/ping"
    )

    if ping is not None:
        futures_api = "OK"
    else:
        futures_api = "CHECK"

    # Spot market information
    try:

        markets = get_usdt_markets()

    except Exception as exc:

        error_message = (
            f"⚠️ ATI BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET DATA ERROR\n\n"
            f"{str(exc)[:500]}"
        )

        print(error_message)

        telegram_send(
            error_message
        )

        return

    print(
        f"USDT MARKETS: {len(markets)}"
    )

    if not markets:

        message = (
            f"⚠️ ATI BOT {VERSION}\n\n"
            "❌ NO USDT MARKETS FOUND"
        )

        telegram_send(message)

        return

    # --------------------------------------------------------
    # HEADER TELEGRAM
    # --------------------------------------------------------

    header = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 BREAKOUT + RETEST SCANNER\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n\n"
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}\n"
        f"🚫 5M CHASE LIMIT: {CHASE_LIMIT_5M:.1f}%\n\n"
        f"⏱ TIMEFRAME: 5M\n"
        f"✅ CLOSED CANDLE\n"
        f"🛡 ORDER EXECUTION: DISABLED"
    )

    print(header)

    # --------------------------------------------------------
    # SCAN MARKETS
    # --------------------------------------------------------

    results = []

    print(
        f"SCANNING {len(markets)} MARKETS..."
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {
            executor.submit(
                analyze_symbol,
                symbol,
            ): symbol
            for symbol in markets
        }

        completed = 0

        for future in as_completed(
            future_map
        ):

            symbol = future_map[future]

            try:

                result = future.result()

                if result is not None:
                    results.append(result)

            except Exception as exc:

                print(
                    f"SCAN ERROR {symbol}:",
                    exc,
                )

            completed += 1

            if completed % 50 == 0:

                print(
                    f"Progress: "
                    f"{completed}/{len(markets)}"
                )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["score"],
            x["change_15m"],
            x["change_1h"],
        ),
        reverse=True,
    )

    buys = [
        x for x in results
        if x["signal"] == "BUY"
    ]

    watches = [
        x for x in results
        if x["signal"] == "WATCH"
    ]

    # --------------------------------------------------------
    # TELEGRAM MESSAGE
    # --------------------------------------------------------

    message_parts = [
        header,
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🟢 CONFIRMED BUYS",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if buys:

        for index, item in enumerate(
            buys[:TOP_RESULTS],
            start=1,
        ):

            message_parts.append(
                format_signal(
                    item,
                    index,
                )
            )

            message_parts.append(
                "\n━━━━━━━━━━━━━━━━━━"
            )

    else:

        message_parts.append(
            "❌ No confirmed BUY"
        )

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    if watches:

        message_parts.extend(
            [
                "",
                "🟡 WATCH",
                "━━━━━━━━━━━━━━━━━━",
            ]
        )

        for index, item in enumerate(
            watches[:5],
            start=1,
        ):

            message_parts.append(
                format_signal(
                    item,
                    index,
                )
            )

            message_parts.append(
                "\n━━━━━━━━━━━━━━━━━━"
            )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    message_parts.extend(
        [
            "",
            f"📊 SCAN SUMMARY",
            f"Markets: {len(markets)}",
            f"BUY: {len(buys)}",
            f"WATCH: {len(watches)}",
            f"Scored: {len(results)}",
            "",
            f"🕐 {now_text()}",
        ]
    )

    final_message = "\n".join(
        message_parts
    )

    print("\n")
    print(final_message)

    telegram_send(
        final_message
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    try:

        run_scanner()

    except Exception as exc:

        print(
            "FATAL ERROR:",
            exc,
        )

        telegram_send(
            f"🚨 ATI BOT {VERSION}\n\n"
            f"❌ FATAL ERROR\n\n"
            f"{str(exc)[:700]}"
        )
