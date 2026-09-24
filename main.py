import os
import time
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================================================
# ATI CRYPTO BOT V33
# STRICT UPWARD COIN SCANNER
# BREAKOUT + MOMENTUM + VOLUME + RETEST
# =========================================================

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
TRADE_LIMIT = 250
MIN_CANDLES = 40

MAX_WORKERS = 12

MAX_STRONG_BUYS = 3
MAX_EARLY_BUYS = 5

# -------------------------
# STRONG BUY SETTINGS
# -------------------------

MIN_BREAKOUT_PCT = 0.0015       # 0.15%
MIN_BODY_RATIO = 0.55           # 55%
MIN_CLOSE_POSITION = 0.65       # close near high
MIN_MOMENTUM_PCT = 0.0015       # 0.15%
MIN_VOLUME_RATIO = 1.20

MAX_CHASE_PCT = 0.015            # don't chase >1.5%

# -------------------------
# EARLY BUY SETTINGS
# -------------------------

EARLY_DISTANCE = 0.0025          # 0.25%
EARLY_MOMENTUM_PCT = 0.0010      # 0.10%
EARLY_VOLUME_RATIO = 1.05

# -------------------------
# TECHNICAL SETTINGS
# -------------------------

MOMENTUM_LOOKBACK = 3
VOLUME_LOOKBACK = 10
RESISTANCE_LOOKBACK = 20
ATR_PERIOD = 14

SL_ATR = 1.20
TP1_ATR = 1.50
TP2_ATR = 2.40

# =========================================================
# ENV
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# =========================================================
# HELPERS
# =========================================================

def format_price(price):
    if price >= 1000:
        return f"{price:,.2f}"

    if price >= 100:
        return f"{price:,.3f}"

    if price >= 1:
        return f"{price:.4f}"

    if price >= 0.01:
        return f"{price:.6f}"

    if price >= 0.0001:
        return f"{price:.8f}"

    if price >= 0.000001:
        return f"{price:.10f}"

    if price >= 0.00000001:
        return f"{price:.12f}"

    return f"{price:.16f}"


def pct(value):
    return f"{value * 100:.2f}%"


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM credentials missing")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }

    try:
        r = requests.post(url, json=payload, timeout=20)

        if r.status_code == 200:
            print("TELEGRAM: OK")
            return True

        print("TELEGRAM ERROR:", r.status_code, r.text)
        return False

    except Exception as e:
        print("TELEGRAM ERROR:", e)
        return False


# =========================================================
# TABDEAL API
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT-V33"
})


def get_exchange_info():
    url = f"{BASE_URL}/r/api/v1/exchangeInfo"

    r = session.get(url, timeout=20)
    r.raise_for_status()

    return r.json()


def get_klines(symbol):
    url = f"{BASE_URL}/r/api/v1/klines"

    params = {
        "symbol": symbol,
        "interval": TIMEFRAME,
        "limit": TRADE_LIMIT
    }

    r = session.get(url, params=params, timeout=20)

    if r.status_code != 200:
        return None

    try:
        data = r.json()
    except Exception:
        return None

    return data


# =========================================================
# MARKET DISCOVERY
# =========================================================

def get_usdt_symbols():

    data = get_exchange_info()

    symbols = []

    if isinstance(data, dict):
        raw_symbols = data.get("symbols", [])
    else:
        raw_symbols = data

    for item in raw_symbols:

        try:
            symbol = item.get("symbol", "")
            status = item.get("status", "TRADING")

            if not symbol.endswith("USDT"):
                continue

            if status not in ("TRADING", "ENABLED", ""):
                continue

            # Ignore leveraged tokens
            bad_words = [
                "UPUSDT",
                "DOWNUSDT",
                "BULLUSDT",
                "BEARUSDT"
            ]

            if any(x in symbol for x in bad_words):
                continue

            symbols.append(symbol)

        except Exception:
            continue

    return sorted(set(symbols))


# =========================================================
# CANDLE PARSER
# =========================================================

def parse_candles(raw):

    candles = []

    if not raw:
        return candles

    for c in raw:

        try:
            candles.append({
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
                "time": int(c[0])
            })
        except Exception:
            continue

    return candles


# =========================================================
# REMOVE OPEN CANDLE
# =========================================================

def get_closed_candles(candles):

    if len(candles) < 3:
        return []

    now_ms = int(time.time() * 1000)

    timeframe_ms = 5 * 60 * 1000

    closed = []

    for candle in candles:

        candle_open = candle["time"]

        candle_close = candle_open + timeframe_ms

        if candle_close <= now_ms:
            closed.append(candle)

    return closed


# =========================================================
# ATR
# =========================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):

        high = candles[i]["high"]
        low = candles[i]["low"]
        prev_close = candles[i - 1]["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period


# =========================================================
# CANDLE STRENGTH
# =========================================================

def candle_strength(candle):

    o = candle["open"]
    h = candle["high"]
    l = candle["low"]
    c = candle["close"]

    candle_range = h - l

    if candle_range <= 0:
        return False, 0, 0

    body = abs(c - o)

    body_ratio = body / candle_range

    close_position = (c - l) / candle_range

    bullish = (
        c > o
        and body_ratio >= MIN_BODY_RATIO
        and close_position >= MIN_CLOSE_POSITION
    )

    return bullish, body_ratio, close_position


# =========================================================
# MOMENTUM
# =========================================================

def calculate_momentum(candles):

    if len(candles) < MOMENTUM_LOOKBACK + 1:
        return None

    current = candles[-1]["close"]
    previous = candles[-1 - MOMENTUM_LOOKBACK]["close"]

    if previous <= 0:
        return None

    return (current - previous) / previous


# =========================================================
# VOLUME
# =========================================================

def calculate_volume_ratio(candles):

    if len(candles) < VOLUME_LOOKBACK + 1:
        return None

    current_volume = candles[-1]["volume"]

    previous_volumes = [
        c["volume"]
        for c in candles[-1 - VOLUME_LOOKBACK:-1]
    ]

    if not previous_volumes:
        return None

    average_volume = sum(previous_volumes) / len(previous_volumes)

    if average_volume <= 0:
        return None

    return current_volume / average_volume


# =========================================================
# TREND
# =========================================================

def bullish_trend(candles):

    if len(candles) < 6:
        return False

    c0 = candles[-1]["close"]
    c3 = candles[-4]["close"]
    c5 = candles[-6]["close"]

    return (
        c0 > c3
        and c3 > c5
    )


# =========================================================
# ANALYZE SYMBOL
# =========================================================

def analyze_symbol(symbol):

    try:

        raw = get_klines(symbol)

        if not raw:
            return None

        candles = parse_candles(raw)

        candles = get_closed_candles(candles)

        if len(candles) < MIN_CANDLES:
            return None

        current = candles[-1]

        price = current["close"]

        previous_candles = candles[:-1]

        # -----------------------------------------
        # RESISTANCE
        # -----------------------------------------

        resistance_window = previous_candles[-RESISTANCE_LOOKBACK:]

        resistance = max(
            c["high"]
            for c in resistance_window
        )

        support = min(
            c["low"]
            for c in resistance_window
        )

        # -----------------------------------------
        # BASIC METRICS
        # -----------------------------------------

        breakout_pct = (
            (price - resistance) / resistance
            if resistance > 0
            else 0
        )

        distance_to_resistance = (
            (resistance - price) / resistance
            if resistance > 0
            else 999
        )

        momentum = calculate_momentum(candles)

        volume_ratio = calculate_volume_ratio(candles)

        trend = bullish_trend(candles)

        strong_candle, body_ratio, close_position = candle_strength(
            current
        )

        atr = calculate_atr(candles, ATR_PERIOD)

        if momentum is None:
            return None

        if volume_ratio is None:
            return None

        if atr is None or atr <= 0:
            return None

        # -----------------------------------------
        # 5M MOVE
        # -----------------------------------------

        previous_close = candles[-2]["close"]

        if previous_close <= 0:
            return None

        move_5m = (
            (price - previous_close) / previous_close
        )

        # Ignore dead candles
        if move_5m < -0.01:
            return None

        # -----------------------------------------
        # OVEREXTENDED
        # -----------------------------------------

        extension_from_support = (
            (price - support) / support
            if support > 0
            else 0
        )

        if extension_from_support > MAX_CHASE_PCT:
            overextended = True
        else:
            overextended = False

        # =================================================
        # STRONG BUY
        # =================================================

        strong_buy = (
            breakout_pct >= MIN_BREAKOUT_PCT
            and strong_candle
            and momentum >= MIN_MOMENTUM_PCT
            and volume_ratio >= MIN_VOLUME_RATIO
            and trend
            and not overextended
        )

        # =================================================
        # EARLY BUY
        # =================================================

        near_resistance = (
            distance_to_resistance >= 0
            and distance_to_resistance <= EARLY_DISTANCE
        )

        early_volume_ok = (
            volume_ratio >= EARLY_VOLUME_RATIO
        )

        early_momentum_ok = (
            momentum >= EARLY_MOMENTUM_PCT
        )

        early_candle_ok = (
            strong_candle
            or body_ratio >= 0.45
        )

        early_buy = (
            not strong_buy
            and near_resistance
            and early_momentum_ok
            and trend
            and early_volume_ok
            and early_candle_ok
            and not overextended
        )

        if not strong_buy and not early_buy:
            return None

        # =================================================
        # SL / TP
        # =================================================

        sl = price - (atr * SL_ATR)

        tp1 = price + (atr * TP1_ATR)

        tp2 = price + (atr * TP2_ATR)

        # -----------------------------------------
        # QUALITY SCORE
        # -----------------------------------------

        score = 0

        if breakout_pct >= MIN_BREAKOUT_PCT:
            score += 1

        if strong_candle:
            score += 1

        if momentum >= MIN_MOMENTUM_PCT:
            score += 1

        if volume_ratio >= MIN_VOLUME_RATIO:
            score += 1

        if trend:
            score += 1

        if not overextended:
            score += 1

        # -----------------------------------------
        # RETURN
        # -----------------------------------------

        return {
            "symbol": symbol,
            "price": price,
            "resistance": resistance,
            "support": support,
            "breakout_pct": breakout_pct,
            "distance": distance_to_resistance,
            "momentum": momentum,
            "volume_ratio": volume_ratio,
            "body_ratio": body_ratio,
            "close_position": close_position,
            "move_5m": move_5m,
            "atr": atr,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "trend": trend,
            "strong_buy": strong_buy,
            "early_buy": early_buy,
            "score": score,
            "candle_time": current["time"]
        }

    except Exception as e:

        print(f"{symbol}: ERROR {e}")

        return None


# =========================================================
# SCANNER
# =========================================================

def scan_market(symbols):

    strong = []

    early = []

    scanned = 0

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(analyze_symbol, symbol): symbol
            for symbol in symbols
        }

        for future in as_completed(futures):

            scanned += 1

            try:

                result = future.result()

                if not result:
                    continue

                if result["strong_buy"]:
                    strong.append(result)

                elif result["early_buy"]:
                    early.append(result)

            except Exception as e:

                symbol = futures[future]

                print(
                    f"{symbol}: SCAN ERROR {e}"
                )

    # =====================================================
    # SORT
    # =====================================================

    strong.sort(
        key=lambda x: (
            x["score"],
            x["breakout_pct"],
            x["momentum"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    early.sort(
        key=lambda x: (
            x["score"],
            x["momentum"],
            x["volume_ratio"],
            -x["distance"]
        ),
        reverse=True
    )

    return (
        strong[:MAX_STRONG_BUYS],
        early[:MAX_EARLY_BUYS],
        scanned
    )


# =========================================================
# MESSAGE
# =========================================================

def build_message(
    symbols_count,
    strong,
    early,
    scanned
):

    now = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    lines = []

    lines.append("⚡ ATI CRYPTO BOT V33")
    lines.append("")
    lines.append("🚀 SMART UPWARD COIN SCANNER")
    lines.append("⏱ Timeframe: 5m")
    lines.append("✅ CLOSED CANDLE")
    lines.append("💥 BREAKOUT + MOMENTUM + VOLUME")
    lines.append("🧠 EARLY BREAKOUT WATCH")
    lines.append("")
    lines.append("📡 TABDEAL API: OK")
    lines.append(f"📊 USDT MARKETS: {symbols_count}")
    lines.append(f"🔎 SCANNED: {scanned}")
    lines.append(f"🕐 Scan: {now}")
    lines.append("")

    # =====================================================
    # STRONG BUY
    # =====================================================

    if strong:

        lines.append("🔥 STRONG BUY")

        for i, x in enumerate(strong, 1):

            lines.append("")
            lines.append(
                f"🟢 #{i} {x['symbol']}"
            )

            lines.append(
                f"💰 Entry: ${format_price(x['price'])}"
            )

            lines.append(
                f"🚀 Breakout: {pct(x['breakout_pct'])}"
            )

            lines.append(
                f"📈 Momentum: {pct(x['momentum'])}"
            )

            lines.append(
                f"📊 Volume: {x['volume_ratio']:.2f}x"
            )

            lines.append(
                f"💪 Strength: {x['body_ratio'] * 100:.0f}%"
            )

            lines.append(
                f"⭐ Score: {x['score']}/6"
            )

            lines.append(
                f"🛑 SL: ${format_price(x['sl'])}"
            )

            lines.append(
                f"🎯 TP1: ${format_price(x['tp1'])}"
            )

            lines.append(
                f"🎯 TP2: ${format_price(x['tp2'])}"
            )

    else:

        lines.append(
            "🟢 STRONG BUY: NONE"
        )

    # =====================================================
    # EARLY BUY
    # =====================================================

    lines.append("")

    if early:

        lines.append("🟡 EARLY BUY / WATCH")

        for i, x in enumerate(early, 1):

            lines.append("")

            lines.append(
                f"🟡 #{i} {x['symbol']}"
            )

            lines.append(
                f"💰 Price: ${format_price(x['price'])}"
            )

            lines.append(
                f"📏 To Resistance: {pct(x['distance'])}"
            )

            lines.append(
                f"📈 Momentum: {pct(x['momentum'])}"
            )

            lines.append(
                f"📊 Volume: {x['volume_ratio']:.2f}x"
            )

            lines.append(
                f"⭐ Score: {x['score']}/6"
            )

            lines.append(
                "⏳ WAIT FOR BREAKOUT CONFIRMATION"
            )

    else:

        lines.append(
            "🟡 EARLY BUY / WATCH: NONE"
        )

    # =====================================================
    # NO TRADE
    # =====================================================

    if not strong and not early:

        lines.append("")
        lines.append(
            "⚪ NO STRONG UPWARD SETUP"
        )

        lines.append(
            "⏳ WAITING FOR CONFIRMATION"
        )

    # =====================================================
    # SAFETY
    # =====================================================

    lines.append("")
    lines.append("🛡 MODE: PAPER / TEST")
    lines.append("🚫 REAL TRADING DISABLED")
    lines.append("📡 TELEGRAM: OK")

    return "\n".join(lines)


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 60)
    print("ATI CRYPTO BOT V33")
    print("SMART UPWARD COIN SCANNER")
    print("=" * 60)

    if not TELEGRAM_BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN missing")
        return

    if not TELEGRAM_CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID missing")
        return

    try:

        exchange_info = get_exchange_info()

        if not exchange_info:
            print("TABDEAL API FAILED")
            return

        print("TABDEAL API: OK")

        symbols = get_usdt_symbols()

        print(
            f"USDT MARKETS: {len(symbols)}"
        )

        if not symbols:
            print("No USDT markets found")
            return

        strong, early, scanned = scan_market(
            symbols
        )

        print(
            f"SCANNED: {scanned}"
        )

        print(
            f"STRONG BUY: {len(strong)}"
        )

        print(
            f"EARLY BUY: {len(early)}"
        )

        message = build_message(
            len(symbols),
            strong,
            early,
            scanned
        )

        print("")
        print(message)
        print("")

        send_telegram(message)

    except Exception as e:

        error_message = (
            "🛡 ATI SAFETY\n\n"
            "❌ BOT ERROR\n\n"
            f"{str(e)}"
        )

        print(error_message)

        send_telegram(error_message)


if __name__ == "__main__":
    main()
