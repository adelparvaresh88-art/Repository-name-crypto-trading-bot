import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.9
# EARLY ENTRY + CONFIRMED BREAKOUT SCANNER
# TELEGRAM HEARTBEAT EVERY 5 MINUTES
# SCANNER ONLY - REAL ORDERS DISABLED
# ============================================================

VERSION = "V38.9"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 720
MAX_MARKETS = 1000
REQUEST_TIMEOUT = 15

CONFIRMED_BUY_MIN_SCORE = 10
EARLY_BUY_MIN_SCORE = 9
WATCH_MIN_SCORE = 7

TOP_RESULTS = 5

MAX_5M_MOVE = 6.0
MAX_15M_MOVE = 12.0
MAX_1H_MOVE = 20.0

EARLY_RESISTANCE_DISTANCE = 1.20
MAX_CONFIRMED_DISTANCE = 2.50
MAX_EARLY_DISTANCE = 1.50
RETEST_DISTANCE = 1.50

TELEGRAM_MAX_LENGTH = 3900
SCAN_INTERVAL_SECONDS = 300

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

session = requests.Session()
session.headers.update(
    {
        "User-Agent": "ATI-CRYPTO-BOT/38.9",
        "Accept": "application/json",
    }
)


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM: missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return []

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    chunks = []

    if len(message) <= TELEGRAM_MAX_LENGTH:
        chunks = [message]
    else:
        current = ""

        for line in message.splitlines():
            if len(current) + len(line) + 1 > TELEGRAM_MAX_LENGTH:
                if current:
                    chunks.append(current)

                current = line
            else:
                current = current + ("\n" if current else "") + line

        if current:
            chunks.append(current)

    message_ids = []

    for chunk in chunks:
        try:
            response = session.post(
                url,
                json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": chunk,
                    "disable_web_page_preview": True,
                },
                timeout=REQUEST_TIMEOUT,
            )

            response.raise_for_status()

            data = response.json()

            if data.get("ok"):
                result = data.get("result", {})
                message_id = result.get("message_id")

                if message_id is not None:
                    message_ids.append(message_id)

                print("TELEGRAM: message sent")

            else:
                print("TELEGRAM ERROR:", data)

        except Exception as exc:
            print("TELEGRAM SEND ERROR:", exc)

    return message_ids


def edit_telegram_message(message_id, message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/editMessageText"
    )

    try:
        response = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "message_id": message_id,
                "text": message[:TELEGRAM_MAX_LENGTH],
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if not response.ok:
            print(
                "TELEGRAM EDIT HTTP ERROR:",
                response.status_code,
            )
            print(response.text[:500])
            return False

        data = response.json()

        if data.get("ok"):
            print("TELEGRAM: heartbeat updated")
            return True

        print("TELEGRAM EDIT ERROR:", data)
        return False

    except Exception as exc:
        print("TELEGRAM EDIT ERROR:", exc)
        return False


def build_heartbeat():
    return (
        "🟢 ATI CRYPTO BOT "
        + VERSION
        + "\n\n"
        + "📡 TABDEAL API: CONNECTING...\n"
        + "📊 SCAN: STARTING\n"
        + "⏱ TIMEFRAME: 5m\n"
        + "🔄 NEXT SCAN: ABOUT 5 MINUTES\n"
        + "🔧 REAL ORDERS: DISABLED\n\n"
        + "🕐 "
        + utc_now()
    )


def get_json(path, params=None):
    url = BASE_URL + path

    response = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


def extract_symbols(data):
    symbols = []

    if isinstance(data, dict):
        for key in (
            "symbols",
            "data",
            "result",
            "markets",
            "items",
        ):
            value = data.get(key)

            if isinstance(value, list):
                symbols.extend(value)

            elif isinstance(value, dict):
                symbols.extend(value.values())

        if not symbols and "symbol" in data:
            symbols.append(data)

    elif isinstance(data, list):
        symbols = data

    output = []

    for item in symbols:
        symbol = None

        if isinstance(item, str):
            symbol = item

        elif isinstance(item, dict):
            for key in (
                "symbol",
                "s",
                "market",
                "pair",
                "code",
            ):
                value = item.get(key)

                if isinstance(value, str):
                    symbol = value
                    break

        if not symbol:
            continue

        symbol = symbol.upper().replace("/", "")

        if symbol.endswith("USDT") and len(symbol) > 4:
            if symbol not in output:
                output.append(symbol)

    return output


def get_markets():
    paths = [
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/symbols",
        "/r/api/v1/markets",
    ]

    last_error = None

    for path in paths:
        try:
            data = get_json(path)
            symbols = extract_symbols(data)

            if symbols:
                print("MARKETS ENDPOINT:", path)
                print("USDT MARKETS:", len(symbols))

                return symbols[:MAX_MARKETS]

        except Exception as exc:
            last_error = exc

            print(
                "MARKETS ERROR",
                path,
                ":",
                exc,
            )

    raise RuntimeError(
        "Could not load USDT markets: "
        + str(last_error)
    )


def get_trades(symbol):
    data = get_json(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if isinstance(data, dict):
        for key in (
            "data",
            "result",
            "trades",
            "items",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

    if isinstance(data, list):
        return data

    return []


def parse_trade(item):
    if not isinstance(item, dict):
        return None

    price = None
    quantity = None
    timestamp = None

    for key in (
        "price",
        "p",
        "Price",
    ):
        if key in item:
            price = item[key]
            break

    for key in (
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
    ):
        if key in item:
            quantity = item[key]
            break

    for key in (
        "timestamp",
        "time",
        "T",
        "created_at",
    ):
        if key in item:
            timestamp = item[key]
            break

    try:
        price = float(price)
        quantity = abs(float(quantity or 0))

    except Exception:
        return None

    if price <= 0:
        return None

    if timestamp is None:
        return None

    try:
        timestamp = float(timestamp)

    except Exception:
        return None

    if timestamp < 10000000000:
        timestamp *= 1000

    return timestamp, price, quantity


def build_candles(trades):
    parsed = []

    for item in trades:
        value = parse_trade(item)

        if value:
            parsed.append(value)

    if not parsed:
        return []

    buckets = {}

    for timestamp, price, quantity in parsed:
        bucket = int(timestamp // 300000) * 300000

        if bucket not in buckets:
            buckets[bucket] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
            }

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
        candle["volume"] += quantity

    ordered = []

    for timestamp in sorted(buckets):
        candle = buckets[timestamp]
        candle["timestamp"] = timestamp
        ordered.append(candle)

    if len(ordered) > 1:
        now_ms = time.time() * 1000
        current_bucket = int(now_ms // 300000) * 300000

        if ordered[-1]["timestamp"] >= current_bucket:
            ordered = ordered[:-1]

    return ordered[-CANDLE_LIMIT:]


def pct_change(old, new):
    if old is None or old == 0:
        return 0.0

    return ((new - old) / old) * 100.0


def momentum(candles, periods):
    if len(candles) <= periods:
        return 0.0

    return pct_change(
        candles[-periods - 1]["close"],
        candles[-1]["close"],
    )


def higher_high(candles):
    if len(candles) < 8:
        return False

    recent = candles[-4:]
    previous = candles[-8:-4]

    return (
        max(x["high"] for x in recent)
        > max(x["high"] for x in previous)
    )


def higher_low(candles):
    if len(candles) < 8:
        return False

    recent = candles[-4:]
    previous = candles[-8:-4]

    return (
        min(x["low"] for x in recent)
        > min(x["low"] for x in previous)
    )


def find_resistance(candles, lookback=24):
    if len(candles) < 6:
        return None

    sample = candles[-lookback:]
    highs = [x["high"] for x in sample]

    if not highs:
        return None

    return max(highs)


def breakout_status(candles, resistance):
    if resistance is None or len(candles) < 3:
        return False, False

    last = candles[-1]
    previous = candles[-2]

    confirmed = (
        last["close"] > resistance
        and previous["close"] <= resistance
    )

    above = last["close"] > resistance

    return confirmed, above


def has_retest(candles, resistance):
    if resistance is None or len(candles) < 6:
        return False

    recent = candles[-5:]

    for candle in recent:
        distance = (
            abs(candle["low"] - resistance)
            / resistance
            * 100.0
        )

        if (
            distance <= RETEST_DISTANCE
            and candle["close"] >= resistance
        ):
            return True

    return False


def volume_ratio(candles, lookback=20):
    if len(candles) < lookback + 1:
        return 1.0

    previous = candles[-lookback - 1:-1]

    average = (
        sum(x["volume"] for x in previous)
        / len(previous)
    )

    if average <= 0:
        return 1.0

    return candles[-1]["volume"] / average


def strong_candle(candle):
    candle_range = (
        candle["high"] - candle["low"]
    )

    if candle_range <= 0:
        return False

    body = abs(
        candle["close"] - candle["open"]
    )

    body_ratio = body / candle_range

    close_position = (
        candle["close"] - candle["low"]
    ) / candle_range

    return (
        candle["close"] > candle["open"]
        and body_ratio >= 0.45
        and close_position >= 0.65
    )


def analyze_symbol(symbol):
    trades = get_trades(symbol)

    if len(trades) < 30:
        return None

    candles = build_candles(trades)

    if len(candles) < 30:
        return None

    price = candles[-1]["close"]

    move_5m = momentum(candles, 1)
    move_15m = momentum(candles, 3)
    move_1h = momentum(candles, 12)

    if move_5m > MAX_5M_MOVE:
        return None

    if move_15m > MAX_15M_MOVE:
        return None

    if move_1h > MAX_1H_MOVE:
        return None

    hh = higher_high(candles)
    hl = higher_low(candles)

    resistance = find_resistance(
        candles,
        24,
    )

    if resistance is None or resistance <= 0:
        return None

    distance = (
        (resistance - price)
        / resistance
        * 100.0
    )

    confirmed_breakout, above_resistance = (
        breakout_status(
            candles,
            resistance,
        )
    )

    retest = has_retest(
        candles,
        resistance,
    )

    vol = volume_ratio(candles)

    strong = strong_candle(
        candles[-1]
    )

    score = 0

    if move_5m > 0:
        score += 1

    if move_15m > 0:
        score += 2

    if move_1h > 0:
        score += 2

    if hh:
        score += 1

    if hl:
        score += 1

    if above_resistance:
        score += 2

    if confirmed_breakout:
        score += 2

    if retest:
        score += 2

    if vol >= 1.20:
        score += 1

    if vol >= 1.50:
        score += 1

    if strong:
        score += 1

    signal = None

    if (
        confirmed_breakout
        and distance <= MAX_CONFIRMED_DISTANCE
        and score >= CONFIRMED_BUY_MIN_SCORE
    ):
        signal = "CONFIRMED BUY"

    if signal is None:
        early_conditions = (
            not above_resistance
            and distance >= 0
            and distance <= EARLY_RESISTANCE_DISTANCE
            and move_5m > 0
            and move_15m > 0
            and hh
            and hl
            and strong
            and score >= EARLY_BUY_MIN_SCORE
        )

        if (
            early_conditions
            and distance <= MAX_EARLY_DISTANCE
        ):
            signal = "EARLY BUY"

    if signal is None:
        watch_conditions = (
            distance >= 0
            and distance <= EARLY_RESISTANCE_DISTANCE
            and move_15m > 0
            and (hh or hl)
            and score >= WATCH_MIN_SCORE
        )

        if watch_conditions:
            signal = "WATCH"

    if signal is None:
        return None

    sl = price * 0.955
    tp1 = price * 1.085
    tp2 = price * 1.120

    return {
        "symbol": symbol,
        "signal": signal,
        "score": score,
        "price": price,
        "move_5m": move_5m,
        "move_15m": move_15m,
        "move_1h": move_1h,
        "resistance": resistance,
        "distance": distance,
        "volume": vol,
        "retest": retest,
        "strong": strong,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


def fmt_price(value):
    if value >= 1000:
        return f"{value:.2f}"

    if value >= 1:
        return f"{value:.5f}"

    if value >= 0.01:
        return f"{value:.7f}"

    return f"{value:.10f}"


def format_signal(item, rank):
    signal = item["signal"]

    if signal == "CONFIRMED BUY":
        icon = "🟢"

    elif signal == "EARLY BUY":
        icon = "🟡"

    else:
        icon = "👀"

    return (
        f"{icon} #{rank} {signal}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: {fmt_price(item['price'])}\n"
        f"📈 5M: {item['move_5m']:+.2f}%\n"
        f"📊 15M: {item['move_15m']:+.2f}%\n"
        f"🕐 1H: {item['move_1h']:+.2f}%\n"
        f"🎯 RESISTANCE: "
        f"{fmt_price(item['resistance'])}\n"
        f"📏 DISTANCE: "
        f"{item['distance']:+.2f}%\n"
        f"📦 VOLUME: {item['volume']:.2f}x\n"
        f"🔁 RETEST: "
        f"{'YES' if item['retest'] else 'NO'}\n"
        f"🕯 STRONG CANDLE: "
        f"{'YES' if item['strong'] else 'NO'}\n"
        f"🛑 SL: {fmt_price(item['sl'])}\n"
        f"🎯 TP1: {fmt_price(item['tp1'])}\n"
        f"🎯 TP2: {fmt_price(item['tp2'])}"
    )


def build_result_message(
    markets,
    results,
    elapsed,
):
    confirmed = [
        x
        for x in results
        if x["signal"] == "CONFIRMED BUY"
    ]

    early = [
        x
        for x in results
        if x["signal"] == "EARLY BUY"
    ]

    watch = [
        x
        for x in results
        if x["signal"] == "WATCH"
    ]

    lines = [
        "⚡ ATI CRYPTO BOT " + VERSION,
        "",
        "🚀 EARLY ENTRY + CONFIRMED BREAKOUT",
        "",
        "📡 TABDEAL API: OK",
        "📊 USDT MARKETS: " + str(markets),
        "⏱ TIMEFRAME: 5m",
        "🕯 CLOSED CANDLE: YES",
        "🔧 REAL ORDERS: DISABLED",
        "🕐 " + utc_now(),
        "",
        "━━━━━━━━━━━━━━━━━━",
        "🟢 CONFIRMED BUY",
        "━━━━━━━━━━━━━━━━━━",
    ]

    if confirmed:
        for index, item in enumerate(
            confirmed[:TOP_RESULTS],
            1,
        ):
            lines.append(
                format_signal(item, index)
            )
            lines.append("")

    else:
        lines.append(
            "No confirmed BUY signal."
        )
        lines.append("")

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "🟡 EARLY BUY",
            "━━━━━━━━━━━━━━━━━━",
        ]
    )

    if early:
        for index, item in enumerate(
            early[:TOP_RESULTS],
            1,
        ):
            lines.append(
                format_signal(item, index)
            )
            lines.append("")

    else:
        lines.append(
            "No early BUY signal."
        )
        lines.append("")

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "👀 WATCH",
            "━━━━━━━━━━━━━━━━━━",
        ]
    )

    if watch:
        for index, item in enumerate(
            watch[:TOP_RESULTS],
            1,
        ):
            lines.append(
                format_signal(item, index)
            )
            lines.append("")

    else:
        lines.append(
            "No WATCH signal."
        )
        lines.append("")

    lines.extend(
        [
            "━━━━━━━━━━━━━━━━━━",
            "📌 TOTAL CANDIDATES: "
            + str(len(results)),
            f"⏱ SCAN TIME: {elapsed:.1f}s",
            "🔄 NEXT SCAN: ABOUT 5 MINUTES",
        ]
    )

    return "\n".join(lines)


def build_error_message(error_text):
    return (
        "⚠️ ATI CRYPTO BOT "
        + VERSION
        + "\n\n"
        + "❌ SCAN ERROR\n\n"
        + "📡 TABDEAL API: ERROR\n"
        + "🕐 "
        + utc_now()
        + "\n\n"
        + "DETAIL:\n"
        + str(error_text)[:2500]
        + "\n\n"
        + "🔄 NEXT SCAN: ABOUT 5 MINUTES"
    )


def scan_once():
    started = time.time()

    heartbeat_ids = send_telegram(
        build_heartbeat()
    )

    heartbeat_id = (
        heartbeat_ids[0]
        if heartbeat_ids
        else None
    )

    try:
        markets = get_markets()

        results = []

        total = len(markets)

        for index, symbol in enumerate(
            markets,
            1,
        ):
            try:
                item = analyze_symbol(symbol)

                if item:
                    results.append(item)

            except Exception as exc:
                print(
                    "SYMBOL ERROR",
                    symbol,
                    ":",
                    exc,
                )

            if index % 50 == 0:
                print(
                    "SCANNED:",
                    index,
                    "/",
                    total,
                )

        results.sort(
            key=lambda x: (
                x["score"],
                x["move_15m"],
                x["move_5m"],
            ),
            reverse=True,
        )

        elapsed = time.time() - started

        final_message = build_result_message(
            len(markets),
            results,
            elapsed,
        )

        if heartbeat_id is not None:
            edited = edit_telegram_message(
                heartbeat_id,
                final_message,
            )

            if not edited:
                send_telegram(
                    final_message
                )

        else:
            send_telegram(
                final_message
            )

        print(final_message)

        return True

    except Exception as exc:
        print(
            "SCAN ERROR:",
            exc,
        )

        error_message = build_error_message(
            exc
        )

        if heartbeat_id is not None:
            edited = edit_telegram_message(
                heartbeat_id,
                error_message,
            )

            if not edited:
                send_telegram(
                    error_message
                )

        else:
            send_telegram(
                error_message
            )

        return False


def main():
    print("=" * 60)
    print(
        "ATI CRYPTO BOT "
        + VERSION
    )
    print(
        "STARTED:",
        utc_now(),
    )
    print(
        "MODE: SCANNER ONLY"
    )
    print(
        "REAL ORDERS: DISABLED"
    )
    print("=" * 60)

    while True:
        scan_once()

        print("=" * 60)
        print(
            "SCAN FINISHED:",
            utc_now(),
        )
        print(
            "NEXT SCAN: ABOUT 5 MINUTES"
        )
        print("=" * 60)

        time.sleep(
            SCAN_INTERVAL_SECONDS
        )


if __name__ == "__main__":
    main()
