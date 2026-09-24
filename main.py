import os
import time
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ATI CRYPTO BOT V30
# UPWARD COIN SCANNER
# 5M CLOSED CANDLE
# BREAKOUT + MOMENTUM + VOLATILITY
# PAPER / TEST ONLY
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

TRADE_LIMIT = 250
MIN_CANDLES = 20

MAX_WORKERS = 16
MAX_RESULTS = 5

# برای جلوگیری از ورود به ارزهای خیلی کم‌تحرک
MIN_MOVE_5M = 0.15

# درصدهای پایه برای حد ضرر/سود
SL_ATR_MULT = 1.20
TP_ATR_MULT = 2.40

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT-V30"
})


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM: secrets missing")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        r = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=10
        )

        return r.ok

    except Exception as e:
        print("Telegram error:", e)
        return False


# ============================================================
# TABDEAL API
# ============================================================

def get_exchange_info():
    url = f"{BASE_URL}/r/api/v1/exchangeInfo"

    r = session.get(
        url,
        timeout=15
    )

    r.raise_for_status()

    data = r.json()

    if isinstance(data, dict):
        if "symbols" in data:
            data = data["symbols"]
        elif "data" in data:
            data = data["data"]

    if not isinstance(data, list):
        raise RuntimeError("Invalid exchangeInfo response")

    return data


def get_trades(symbol):
    url = f"{BASE_URL}/r/api/v1/trades"

    r = session.get(
        url,
        params={
            "symbol": symbol,
            "limit": TRADE_LIMIT
        },
        timeout=8
    )

    r.raise_for_status()

    data = r.json()

    if isinstance(data, dict):
        if "data" in data:
            data = data["data"]
        elif "trades" in data:
            data = data["trades"]

    if not isinstance(data, list):
        return []

    return data


# ============================================================
# CANDLE BUILDER
# ============================================================

def build_candles(trades):

    buckets = {}

    for t in trades:

        try:
            price = float(t["price"])
            qty = float(t.get("qty", 0))
            ts = int(t["time"])

        except Exception:
            continue

        bucket = (ts // 300000) * 300000

        if bucket not in buckets:
            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty
            }

        else:
            c = buckets[bucket]

            if price > c["high"]:
                c["high"] = price

            if price < c["low"]:
                c["low"] = price

            c["close"] = price
            c["volume"] += qty

    candles = list(buckets.values())

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ============================================================
# CLOSED CANDLE
# ============================================================

def get_closed_candles(candles):

    if len(candles) < MIN_CANDLES:
        return []

    now_ms = int(time.time() * 1000)

    closed = []

    for c in candles:

        if c["time"] + 300000 <= now_ms:
            closed.append(c)

    return closed


# ============================================================
# ATR / VOLATILITY
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return 0

    trs = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        high = current["high"]
        low = current["low"]
        prev_close = previous["close"]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close)
        )

        trs.append(tr)

    if len(trs) < period:
        return 0

    return sum(trs[-period:]) / period


# ============================================================
# ANALYSIS
# ============================================================

def analyze_symbol(symbol, market_name):

    try:

        trades = get_trades(symbol)

        candles = build_candles(trades)

        candles = get_closed_candles(candles)

        if len(candles) < MIN_CANDLES:
            return None

        current = candles[-1]
        previous = candles[-2]

        price = current["close"]

        # ----------------------------------------------------
        # 5M MOVE
        # ----------------------------------------------------

        move_5m = (
            (current["close"] - current["open"])
            / current["open"]
        ) * 100

        previous_move = (
            (previous["close"] - previous["open"])
            / previous["open"]
        ) * 100

        # ----------------------------------------------------
        # SHORT TREND
        # ----------------------------------------------------

        closes = [
            c["close"]
            for c in candles
        ]

        recent = closes[-6:]

        rising_count = 0

        for i in range(1, len(recent)):

            if recent[i] > recent[i - 1]:
                rising_count += 1

        trend_bullish = rising_count >= 3

        # ----------------------------------------------------
        # STRUCTURE
        # ----------------------------------------------------

        highs = [
            c["high"]
            for c in candles[-8:-1]
        ]

        lows = [
            c["low"]
            for c in candles[-8:-1]
        ]

        resistance = max(highs)
        support = min(lows)

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        bullish_breakout = (
            current["close"] > resistance
        )

        near_breakout = (
            current["close"]
            >= resistance * 0.998
        )

        # ----------------------------------------------------
        # CANDLE
        # ----------------------------------------------------

        candle_range = (
            current["high"] - current["low"]
        )

        if candle_range <= 0:
            return None

        body = abs(
            current["close"] - current["open"]
        )

        body_ratio = body / candle_range

        bullish_candle = (
            current["close"] > current["open"]
        )

        strong_candle = (
            bullish_candle
            and body_ratio >= 0.55
        )

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        bullish_momentum = (
            move_5m >= MIN_MOVE_5M
            and move_5m >= previous_move
        )

        # ----------------------------------------------------
        # VOLUME / ACTIVITY
        # ----------------------------------------------------

        volumes = [
            c["volume"]
            for c in candles[-11:-1]
        ]

        avg_volume = (
            sum(volumes) / len(volumes)
            if volumes else 0
        )

        volume_ok = (
            avg_volume > 0
            and current["volume"] >= avg_volume * 0.8
        )

        # ----------------------------------------------------
        # ATR
        # ----------------------------------------------------

        atr = calculate_atr(candles)

        if atr <= 0:
            return None

        # ----------------------------------------------------
        # BUY LOGIC
        # ----------------------------------------------------

        confirmed_buy = (
            bullish_breakout
            and bullish_candle
            and strong_candle
            and bullish_momentum
            and trend_bullish
        )

        watch_buy = (
            not bullish_breakout
            and near_breakout
            and bullish_candle
            and bullish_momentum
            and trend_bullish
        )

        if not confirmed_buy and not watch_buy:
            return None

        # ----------------------------------------------------
        # SIGNAL
        # ----------------------------------------------------

        if confirmed_buy:
            signal = "BUY"
        else:
            signal = "WATCH BUY"

        # ----------------------------------------------------
        # ENTRY / SL / TP
        # ----------------------------------------------------

        entry = price

        sl = entry - (atr * SL_ATR_MULT)

        tp1 = entry + (atr * 1.60)

        tp2 = entry + (atr * TP_ATR_MULT)

        # ----------------------------------------------------
        # QUALITY
        # ----------------------------------------------------

        quality = 0

        if trend_bullish:
            quality += 1

        if bullish_candle:
            quality += 1

        if strong_candle:
            quality += 1

        if bullish_momentum:
            quality += 1

        if bullish_breakout:
            quality += 1

        if volume_ok:
            quality += 1

        if near_breakout:
            quality += 1

        # ----------------------------------------------------
        # RESULT
        # ----------------------------------------------------

        return {
            "symbol": market_name,
            "signal": signal,
            "price": price,
            "move_5m": move_5m,
            "resistance": resistance,
            "support": support,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "quality": quality,
            "atr": atr,
            "candle_time": current["time"],
            "breakout": bullish_breakout,
            "trend": trend_bullish,
            "momentum": bullish_momentum,
            "volume": volume_ok
        }

    except Exception as e:

        print(
            f"SCAN ERROR {symbol}: {e}"
        )

        return None


# ============================================================
# MARKET FILTER
# ============================================================

def get_usdt_markets():

    markets = get_exchange_info()

    result = []

    for m in markets:

        try:

            status = str(
                m.get("status", "")
            ).upper()

            quote = str(
                m.get("quoteAsset", "")
            ).upper()

            symbol = str(
                m.get("symbol", "")
            ).upper()

            if (
                status == "TRADING"
                and quote == "USDT"
                and symbol
            ):

                result.append(
                    (
                        symbol,
                        symbol
                    )
                )

        except Exception:
            continue

    return result


# ============================================================
# SCANNER
# ============================================================

def scan_markets(markets):

    results = []

    total = len(markets)

    print(
        f"Scanning {total} USDT markets..."
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {}

        for symbol, market_name in markets:

            future = executor.submit(
                analyze_symbol,
                symbol,
                market_name
            )

            futures[future] = symbol

        completed = 0

        for future in as_completed(futures):

            completed += 1

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception as e:

                print(
                    "Worker error:",
                    e
                )

            if completed % 50 == 0:

                print(
                    f"Progress: "
                    f"{completed}/{total}"
                )

    results.sort(
        key=lambda x: (
            x["signal"] == "BUY",
            x["quality"],
            x["move_5m"],
            x["breakout"]
        ),
        reverse=True
    )

    return results[:MAX_RESULTS]


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
# TELEGRAM MESSAGE
# ============================================================

def build_message(results, market_count):

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    lines = []

    lines.append(
        "⚡ ATI CRYPTO BOT V30"
    )

    lines.append(
        "🚀 UPWARD COIN SCANNER"
    )

    lines.append(
        "⏱ Timeframe: 5m"
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
        f"🕐 Scan: {now}"
    )

    lines.append("")

    if not results:

        lines.append(
            "⚪ NO STRONG UPWARD SETUP"
        )

        lines.append(
            "No confirmed BUY or WATCH BUY found."
        )

    else:

        lines.append(
            f"🔥 TOP {len(results)} UPWARD OPPORTUNITIES"
        )

        lines.append("")

        for i, r in enumerate(
            results,
            start=1
        ):

            emoji = (
                "🟢"
                if r["signal"] == "BUY"
                else "🟡"
            )

            candle_dt = datetime.fromtimestamp(
                r["candle_time"] / 1000,
                timezone.utc
            ).strftime(
                "%H:%M UTC"
            )

            lines.append(
                f"{emoji} #{i} {r['symbol']}"
            )

            lines.append(
                f"📊 SIGNAL: {r['signal']}"
            )

            lines.append(
                f"💰 PRICE: ${fmt_price(r['price'])}"
            )

            lines.append(
                f"📈 5M MOVE: {r['move_5m']:+.2f}%"
            )

            lines.append(
                f"🏗 TREND: "
                f"{'BULLISH' if r['trend'] else 'MIXED'}"
            )

            lines.append(
                f"💥 BREAKOUT: "
                f"{'YES' if r['breakout'] else 'WATCH'}"
            )

            lines.append(
                f"🚀 MOMENTUM: "
                f"{'BULLISH' if r['momentum'] else 'WEAK'}"
            )

            lines.append(
                f"📊 QUALITY: "
                f"{r['quality']}/7"
            )

            lines.append(
                f"🎯 ENTRY: ${fmt_price(r['entry'])}"
            )

            lines.append(
                f"🛑 SL: ${fmt_price(r['sl'])}"
            )

            lines.append(
                f"🎯 TP1: ${fmt_price(r['tp1'])}"
            )

            lines.append(
                f"🎯 TP2: ${fmt_price(r['tp2'])}"
            )

            lines.append(
                f"📏 RESISTANCE: "
                f"${fmt_price(r['resistance'])}"
            )

            lines.append(
                f"📏 SUPPORT: "
                f"${fmt_price(r['support'])}"
            )

            lines.append(
                f"🕐 Candle: {candle_dt}"
            )

            lines.append("")

    lines.append(
        "🛡 MODE: PAPER / TEST"
    )

    lines.append(
        "🚫 REAL TRADING DISABLED"
    )

    lines.append(
        "📡 TELEGRAM: OK"
    )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "================================"
    )

    print(
        "ATI CRYPTO BOT V30"
    )

    print(
        "UPWARD COIN SCANNER"
    )

    print(
        "================================"
    )

    try:

        markets = get_usdt_markets()

        if not markets:

            raise RuntimeError(
                "No USDT markets found"
            )

        print(
            f"USDT markets found: "
            f"{len(markets)}"
        )

        results = scan_markets(
            markets
        )

        message = build_message(
            results,
            len(markets)
        )

        print("")
        print(message)
        print("")

        sent = send_telegram(
            message
        )

        if sent:
            print(
                "TELEGRAM: OK"
            )
        else:
            print(
                "TELEGRAM: FAILED"
            )

    except Exception as e:

        error_message = (
            "🛡 ATI SAFETY\n\n"
            "❌ BOT ERROR\n"
            f"{type(e).__name__}: {e}"
        )

        print(
            error_message
        )

        send_telegram(
            error_message
        )


if __name__ == "__main__":
    main()
