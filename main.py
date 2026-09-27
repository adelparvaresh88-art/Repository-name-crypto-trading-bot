import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.4
# BALANCED PRECISION BREAKOUT + RETEST SCANNER
# ============================================================

VERSION = "V38.4"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 120
MAX_MARKETS = 1000
TOP_RESULTS = 5

# ------------------------------------------------------------
# SCORE
# ------------------------------------------------------------

BUY_MIN_SCORE = 13
WATCH_MIN_SCORE = 10

# ------------------------------------------------------------
# MOMENTUM FILTERS
# ------------------------------------------------------------

MIN_5M_MOVE = 0.10
MIN_15M_MOVE = 0.30
MIN_1H_MOVE = 0.50

MAX_5M_MOVE = 5.0
MAX_15M_MOVE = 10.0
MAX_1H_MOVE = 18.0

# ------------------------------------------------------------
# BREAKOUT / RETEST
# ------------------------------------------------------------

MAX_BREAKOUT_DISTANCE = 1.50
MAX_RETEST_DISTANCE = 1.00
MIN_BREAKOUT_DISTANCE = 0.05

# ------------------------------------------------------------
# VOLUME
# ------------------------------------------------------------

VOLUME_MULTIPLIER = 1.10
WEAK_VOLUME_LIMIT = 0.70

# ------------------------------------------------------------
# REQUEST SETTINGS
# ------------------------------------------------------------

REQUEST_TIMEOUT = 15
MARKET_SLEEP = 0.015


# ============================================================
# HELPERS
# ============================================================

def pct_change(old, new):
    if old == 0:
        return 0.0
    return ((new - old) / old) * 100.0


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        print("⚠️ TELEGRAM SECRETS NOT SET")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        if response.ok:
            return True

        print("TELEGRAM ERROR:", response.text[:500])
        return False

    except Exception as e:
        print("TELEGRAM ERROR:", str(e))
        return False


# ============================================================
# TABDEAL REQUEST
# ============================================================

def tabdeal_get(path, params=None):
    url = BASE_URL + path

    try:
        response = requests.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        response.raise_for_status()

        return response.json()

    except Exception as e:
        print(f"TABDEAL ERROR {path}: {e}")
        return None


# ============================================================
# MARKET DISCOVERY
# ============================================================

def extract_symbols(data):

    symbols = []

    if isinstance(data, dict):

        for key in [
            "symbols",
            "data",
            "result",
            "markets",
        ]:
            value = data.get(key)

            if isinstance(value, list):
                data = value
                break

    if not isinstance(data, list):
        return symbols

    for item in data:

        if isinstance(item, str):
            symbol = item.upper()

        elif isinstance(item, dict):

            symbol = (
                item.get("symbol")
                or item.get("name")
                or item.get("code")
                or item.get("market")
                or ""
            )

            if isinstance(symbol, dict):
                symbol = (
                    symbol.get("symbol")
                    or symbol.get("name")
                    or ""
                )

            symbol = str(symbol).upper()

        else:
            continue

        symbol = symbol.replace("-", "").replace("/", "")

        if symbol.endswith("USDT"):
            symbols.append(symbol)

    return list(dict.fromkeys(symbols))


def get_usdt_markets():

    paths = [
        "/r/api/v1/exchangeInfo",
        "/r/api/v1/symbols",
        "/r/api/v1/markets",
    ]

    all_symbols = []

    for path in paths:

        data = tabdeal_get(path)

        if data is None:
            continue

        found = extract_symbols(data)

        if found:
            all_symbols.extend(found)

    symbols = list(dict.fromkeys(all_symbols))

    # Remove obvious non-trading / leveraged symbols
    filtered = []

    for symbol in symbols:

        if not symbol.endswith("USDT"):
            continue

        if any(x in symbol for x in [
            "UPUSDT",
            "DOWNUSDT",
            "BULLUSDT",
            "BEARUSDT",
        ]):
            continue

        filtered.append(symbol)

    return filtered[:MAX_MARKETS]


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):

    data = tabdeal_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if not isinstance(data, list):
        return []

    return data


# ============================================================
# BUILD 5M CANDLES FROM TRADES
# ============================================================

def build_candles(trades):

    candles = {}

    for trade in trades:

        if not isinstance(trade, dict):
            continue

        price = safe_float(
            trade.get("price")
            or trade.get("p")
            or trade.get("last")
        )

        qty = safe_float(
            trade.get("quantity")
            or trade.get("qty")
            or trade.get("amount")
            or trade.get("q"),
            0.0,
        )

        timestamp = (
            trade.get("timestamp")
            or trade.get("time")
            or trade.get("T")
        )

        if not price or timestamp is None:
            continue

        try:
            timestamp = float(timestamp)

            if timestamp > 100000000000:
                timestamp /= 1000

        except Exception:
            continue

        bucket = int(timestamp // 300) * 300

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
            }

        candle = candles[bucket]

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

    result = sorted(
        candles.values(),
        key=lambda x: x["time"],
    )

    return result[-CANDLE_LIMIT:]


# ============================================================
# CLOSED CANDLES ONLY
# ============================================================

def get_closed_candles(candles):

    if len(candles) < 10:
        return []

    current_bucket = int(time.time() // 300) * 300

    closed = [
        c for c in candles
        if c["time"] < current_bucket
    ]

    return closed


# ============================================================
# MOMENTUM
# ============================================================

def calculate_momentum(candles):

    if len(candles) < 20:
        return None

    last = candles[-1]["close"]

    close_1 = candles[-2]["close"]
    close_3 = candles[-4]["close"]
    close_6 = candles[-7]["close"]
    close_12 = candles[-13]["close"]

    move_5m = pct_change(close_1, last)
    move_15m = pct_change(close_3, last)
    move_30m = pct_change(close_6, last)
    move_1h = pct_change(close_12, last)

    return {
        "5m": move_5m,
        "15m": move_15m,
        "30m": move_30m,
        "1h": move_1h,
    }


# ============================================================
# MARKET STRUCTURE
# ============================================================

def structure_check(candles):

    if len(candles) < 15:
        return False, False

    recent = candles[-6:]
    previous = candles[-12:-6]

    recent_high = max(
        c["high"] for c in recent
    )

    previous_high = max(
        c["high"] for c in previous
    )

    recent_low = min(
        c["low"] for c in recent
    )

    previous_low = min(
        c["low"] for c in previous
    )

    higher_high = recent_high > previous_high
    higher_low = recent_low > previous_low

    return higher_high, higher_low


# ============================================================
# RESISTANCE
# ============================================================

def find_resistance(candles):

    if len(candles) < 20:
        return 0.0

    # Older structure used for resistance.
    # This prevents the current candle from defining
    # its own breakout level.

    base = candles[-15:-5]

    if not base:
        return 0.0

    resistance = max(
        c["high"] for c in base
    )

    return resistance


# ============================================================
# BREAKOUT DETECTION
# ============================================================

def detect_breakout(candles, resistance):

    if resistance <= 0:
        return False

    # Look for a breakout in the recent closed candles.
    recent = candles[-5:-2]

    for candle in recent:

        close = candle["close"]

        distance = pct_change(
            resistance,
            close,
        )

        if (
            close > resistance
            and distance >= MIN_BREAKOUT_DISTANCE
            and distance <= MAX_BREAKOUT_DISTANCE
        ):
            return True

    return False


# ============================================================
# RETEST DETECTION
# ============================================================

def detect_retest(candles, resistance):

    if resistance <= 0:
        return False

    # The retest must happen after breakout,
    # not simply on the same candle.

    retest_zone = candles[-4:-1]

    for candle in retest_zone:

        low_distance = abs(
            pct_change(
                resistance,
                candle["low"],
            )
        )

        close_distance = pct_change(
            resistance,
            candle["close"],
        )

        # Price touched resistance and closed
        # back above it.

        if (
            low_distance <= MAX_RETEST_DISTANCE
            and candle["close"] >= resistance
            and close_distance <= MAX_BREAKOUT_DISTANCE
        ):
            return True

    return False


# ============================================================
# CURRENT CONFIRMATION
# ============================================================

def current_confirmation(candle, resistance):

    if resistance <= 0:
        return False

    close = candle["close"]

    distance = pct_change(
        resistance,
        close,
    )

    if close <= resistance:
        return False

    if distance > MAX_BREAKOUT_DISTANCE:
        return False

    return True


# ============================================================
# CANDLE QUALITY
# ============================================================

def candle_quality(candle):

    candle_range = candle["high"] - candle["low"]

    if candle_range <= 0:
        return 0

    body = abs(
        candle["close"] - candle["open"]
    )

    body_ratio = body / candle_range

    bullish = candle["close"] > candle["open"]

    if bullish and body_ratio >= 0.35:
        return 1

    return 0


# ============================================================
# VOLUME
# ============================================================

def volume_info(candles):

    if len(candles) < 12:
        return 1.0

    current_volume = candles[-1]["volume"]

    previous = [
        c["volume"]
        for c in candles[-11:-1]
        if c["volume"] > 0
    ]

    if not previous:
        return 1.0

    average_volume = sum(previous) / len(previous)

    if average_volume <= 0:
        return 1.0

    return current_volume / average_volume


# ============================================================
# SCORE
# ============================================================

def calculate_score(
    momentum,
    higher_high,
    higher_low,
    breakout,
    retest,
    volume_ratio,
    candle_score,
):

    score = 0
    reasons = []

    # --------------------------------------------------------
    # 5M
    # --------------------------------------------------------

    if momentum["5m"] >= MIN_5M_MOVE:

        score += 1
        reasons.append("5M UP")

        if momentum["5m"] >= 0.50:
            score += 1
            reasons.append("5M STRONG")

    # --------------------------------------------------------
    # 15M
    # --------------------------------------------------------

    if momentum["15m"] >= MIN_15M_MOVE:

        score += 1
        reasons.append("15M UP")

        if momentum["15m"] >= 1.00:
            score += 1
            reasons.append("15M STRONG")

    # --------------------------------------------------------
    # 1H
    # --------------------------------------------------------

    if momentum["1h"] >= MIN_1H_MOVE:

        score += 1
        reasons.append("1H UP")

        if momentum["1h"] >= 2.00:
            score += 1
            reasons.append("1H STRONG")

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    if higher_high:
        score += 2
        reasons.append("HIGHER HIGH")

    if higher_low:
        score += 2
        reasons.append("HIGHER LOW")

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    if breakout:
        score += 2
        reasons.append("BREAKOUT")

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    if retest:
        score += 3
        reasons.append("RETEST")

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    if volume_ratio >= VOLUME_MULTIPLIER:

        score += 2
        reasons.append("VOLUME")

    # --------------------------------------------------------
    # CANDLE
    # --------------------------------------------------------

    if candle_score:

        score += 1
        reasons.append("BULLISH CANDLE")

    return score, reasons


# ============================================================
# SIGNAL ANALYSIS
# ============================================================

def analyze_symbol(symbol):

    trades = get_trades(symbol)

    if len(trades) < 50:
        return None

    candles = build_candles(trades)

    closed = get_closed_candles(candles)

    if len(closed) < 30:
        return None

    momentum = calculate_momentum(closed)

    if not momentum:
        return None

    # --------------------------------------------------------
    # HARD MOMENTUM FILTERS
    # --------------------------------------------------------

    if momentum["5m"] < MIN_5M_MOVE:
        return None

    if momentum["15m"] < MIN_15M_MOVE:
        return None

    if momentum["1h"] < MIN_1H_MOVE:
        return None

    # Avoid chasing extreme pumps.

    if momentum["5m"] > MAX_5M_MOVE:
        return None

    if momentum["15m"] > MAX_15M_MOVE:
        return None

    if momentum["1h"] > MAX_1H_MOVE:
        return None

    # --------------------------------------------------------
    # STRUCTURE
    # --------------------------------------------------------

    higher_high, higher_low = structure_check(
        closed
    )

    if not higher_high:
        return None

    if not higher_low:
        return None

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    resistance = find_resistance(closed)

    if resistance <= 0:
        return None

    breakout = detect_breakout(
        closed,
        resistance,
    )

    if not breakout:
        return None

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    retest = detect_retest(
        closed,
        resistance,
    )

    if not retest:
        return None

    # --------------------------------------------------------
    # CURRENT CANDLE
    # --------------------------------------------------------

    current = closed[-1]

    if not current_confirmation(
        current,
        resistance,
    ):
        return None

    # --------------------------------------------------------
    # VOLUME
    # --------------------------------------------------------

    volume_ratio = volume_info(
        closed
    )

    # Extremely weak volume is rejected,
    # but normal volume is allowed.

    if volume_ratio < WEAK_VOLUME_LIMIT:
        return None

    # --------------------------------------------------------
    # CANDLE QUALITY
    # --------------------------------------------------------

    candle_score = candle_quality(
        current
    )

    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score, reasons = calculate_score(
        momentum=momentum,
        higher_high=higher_high,
        higher_low=higher_low,
        breakout=breakout,
        retest=retest,
        volume_ratio=volume_ratio,
        candle_score=candle_score,
    )

    if score < WATCH_MIN_SCORE:
        return None

    # --------------------------------------------------------
    # PRICE
    # --------------------------------------------------------

    price = current["close"]

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    # Use resistance as a reference and give the trade
    # reasonable breathing room.

    sl = resistance * 0.955

    if sl >= price:
        sl = price * 0.95

    risk = price - sl

    if risk <= 0:
        return None

    risk_pct = (risk / price) * 100

    if risk_pct > 7:
        return None

    tp1 = price + (risk * 1.5)
    tp2 = price + (risk * 2.1)

    breakout_distance = pct_change(
        resistance,
        price,
    )

    return {
        "symbol": symbol,
        "score": score,
        "price": price,
        "move_5m": momentum["5m"],
        "move_15m": momentum["15m"],
        "move_1h": momentum["1h"],
        "resistance": resistance,
        "breakout_distance": breakout_distance,
        "volume_ratio": volume_ratio,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "risk_pct": risk_pct,
        "reasons": reasons,
    }


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(item, rank, signal_type):

    emoji = "🟢" if signal_type == "BUY" else "🟡"

    reasons = " • ".join(
        item["reasons"]
    )

    return (
        f"{emoji} {signal_type}\n\n"
        f"#{rank}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: {item['price']:.10f}\n\n"
        f"📈 5M: {item['move_5m']:+.2f}%\n"
        f"📊 15M: {item['move_15m']:+.2f}%\n"
        f"⏱ 1H: {item['move_1h']:+.2f}%\n\n"
        f"📌 BREAKOUT: {item['resistance']:.10f}\n"
        f"📐 DISTANCE: {item['breakout_distance']:.2f}%\n\n"
        f"🛑 SL: {item['sl']:.10f}\n"
        f"🎯 TP1: {item['tp1']:.10f}\n"
        f"🎯 TP2: {item['tp2']:.10f}\n\n"
        f"📦 VOLUME: {item['volume_ratio']:.2f}x\n"
        f"🧠 {reasons}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print(f"⚡ ATI CRYPTO BOT {VERSION}")
    print("🚀 BALANCED PRECISION BREAKOUT + RETEST")
    print("=" * 60)

    print()
    print("⏱ Timeframe: 5m")
    print("✅ CLOSED CANDLE")
    print("📊 5M + 15M + 1H MOMENTUM")
    print("📐 BREAKOUT + RETEST")
    print("📈 PRICE ACTION + MARKET STRUCTURE")
    print()

    print("📡 TABDEAL API: CHECKING...")

    markets = get_usdt_markets()

    if not markets:

        error_message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET DATA ERROR\n\n"
            f"📡 API: {BASE_URL}\n"
            f"🕐 {now_utc()}"
        )

        print(error_message)
        send_telegram(error_message)
        return

    print("📡 TABDEAL API: OK")
    print(f"📊 USDT MARKETS: {len(markets)}")
    print()

    print(f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}")
    print(f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}")
    print(f"🚫 MAX 5M: {MAX_5M_MOVE}%")
    print(f"🚫 MAX 15M: {MAX_15M_MOVE}%")
    print(f"🚫 MAX 1H: {MAX_1H_MOVE}%")
    print(f"📐 MAX BREAKOUT DISTANCE: {MAX_BREAKOUT_DISTANCE}%")
    print(f"🔄 MAX RETEST DISTANCE: {MAX_RETEST_DISTANCE}%")
    print()

    print(f"🕐 Scan: {now_utc()}")
    print()

    results = []

    total = len(markets)

    for index, symbol in enumerate(markets, start=1):

        try:

            result = analyze_symbol(symbol)

            if result:
                results.append(result)

        except Exception as e:

            print(
                f"⚠️ {symbol}: {str(e)}"
            )

        if index % 50 == 0:
            print(
                f"🔎 Scanned {index}/{total}"
            )

        time.sleep(MARKET_SLEEP)

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    results.sort(
        key=lambda x: (
            x["score"],
            x["move_15m"],
            x["move_1h"],
        ),
        reverse=True,
    )

    buys = [
        x for x in results
        if x["score"] >= BUY_MIN_SCORE
    ]

    watches = [
        x for x in results
        if WATCH_MIN_SCORE <= x["score"] < BUY_MIN_SCORE
    ]

    # --------------------------------------------------------
    # TELEGRAM MESSAGE
    # --------------------------------------------------------

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 BALANCED PRECISION BREAKOUT + RETEST\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n\n"
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}\n"
        f"🚫 MAX 5M: {MAX_5M_MOVE}%\n"
        f"🚫 MAX 15M: {MAX_15M_MOVE}%\n"
        f"🚫 MAX 1H: {MAX_1H_MOVE}%\n\n"
        f"🕐 Scan: {now_utc()}\n"
    )

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    if buys:

        message += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "🟢 CONFIRMED BUYS\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )

        for rank, item in enumerate(
            buys[:TOP_RESULTS],
            start=1,
        ):

            message += (
                format_signal(
                    item,
                    rank,
                    "BUY",
                )
                + "\n\n"
            )

    else:

        message += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "🟢 CONFIRMED BUYS\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "❌ NONE\n"
        )

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    if watches:

        message += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "🟡 WATCH\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )

        for rank, item in enumerate(
            watches[:TOP_RESULTS],
            start=1,
        ):

            message += (
                format_signal(
                    item,
                    rank,
                    "WATCH",
                )
                + "\n\n"
            )

    else:

        message += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "🟡 WATCH\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "❌ NONE\n"
        )

    # --------------------------------------------------------
    # SUMMARY
    # --------------------------------------------------------

    message += (
        "\n━━━━━━━━━━━━━━━━━━\n"
        "📊 SUMMARY\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🟢 BUY: {len(buys)}\n"
        f"🟡 WATCH: {len(watches)}\n"
        f"📊 MARKETS: {len(markets)}\n"
        f"🕐 {now_utc()}\n\n"
        "⚠️ SIGNAL ONLY — NO REAL ORDER"
    )

    print()
    print(message)

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    telegram_ok = send_telegram(message)

    print()

    if telegram_ok:
        print("✅ TELEGRAM SENT")
    else:
        print("⚠️ TELEGRAM NOT SENT")

    print()
    print("=" * 60)
    print(f"✅ ATI BOT {VERSION} FINISHED")
    print("=" * 60)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
