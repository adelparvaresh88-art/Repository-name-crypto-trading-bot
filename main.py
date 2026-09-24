import os
import time
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ATI CRYPTO BOT V31
# TOP UPWARD COIN SCANNER
# 5M CLOSED CANDLE
# BREAKOUT + MOMENTUM + PRE-BREAKOUT
# PAPER / TEST ONLY
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
TRADE_LIMIT = 250
MIN_CANDLES = 20

MAX_WORKERS = 16
TOP_RESULTS = 10

# حداقل حرکت برای اینکه ارز وارد لیست صعودی شود
MIN_UP_MOVE = 0.05

# ATR
SL_ATR = 1.20
TP1_ATR = 1.50
TP2_ATR = 2.40

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT-V31"
})


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM SECRETS MISSING")
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
# EXCHANGE INFO
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
        raise RuntimeError(
            "Invalid exchangeInfo response"
        )

    return data


# ============================================================
# TRADES
# ============================================================

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
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    buckets = {}

    for t in trades:

        try:
            price = float(t["price"])
            qty = float(
                t.get("qty", t.get("quantity", 0))
            )
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

            c["high"] = max(
                c["high"],
                price
            )

            c["low"] = min(
                c["low"],
                price
            )

            c["close"] = price
            c["volume"] += qty

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ============================================================
# CLOSED CANDLES ONLY
# ============================================================

def closed_candles(candles):

    now_ms = int(
        time.time() * 1000
    )

    result = []

    for c in candles:

        if c["time"] + 300000 <= now_ms:
            result.append(c)

    return result


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return 0

    trs = []

    for i in range(1, len(candles)):

        c = candles[i]
        p = candles[i - 1]

        tr = max(
            c["high"] - c["low"],
            abs(c["high"] - p["close"]),
            abs(c["low"] - p["close"])
        )

        trs.append(tr)

    return (
        sum(trs[-period:]) / period
        if len(trs) >= period
        else 0
    )


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze(symbol):

    try:

        trades = get_trades(symbol)

        candles = build_candles(
            trades
        )

        candles = closed_candles(
            candles
        )

        if len(candles) < MIN_CANDLES:
            return None

        c = candles[-1]
        p = candles[-2]

        price = c["close"]

        # ----------------------------------------------------
        # 5M MOVE
        # ----------------------------------------------------

        move = (
            (c["close"] - c["open"])
            / c["open"]
        ) * 100

        previous_move = (
            (p["close"] - p["open"])
            / p["open"]
        ) * 100

        # ----------------------------------------------------
        # SHORT TREND
        # ----------------------------------------------------

        recent = [
            x["close"]
            for x in candles[-7:]
        ]

        rising = 0

        for i in range(1, len(recent)):

            if recent[i] > recent[i - 1]:
                rising += 1

        trend_bullish = rising >= 3

        # ----------------------------------------------------
        # STRUCTURE
        # ----------------------------------------------------

        lookback = candles[-8:-1]

        resistance = max(
            x["high"]
            for x in lookback
        )

        support = min(
            x["low"]
            for x in lookback
        )

        # ----------------------------------------------------
        # DISTANCE TO RESISTANCE
        # ----------------------------------------------------

        distance_to_resistance = (
            (resistance - price)
            / price
        ) * 100

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        breakout = (
            price > resistance
        )

        near_breakout = (
            0 <= distance_to_resistance <= 0.40
        )

        # ----------------------------------------------------
        # CANDLE STRENGTH
        # ----------------------------------------------------

        candle_range = (
            c["high"] - c["low"]
        )

        if candle_range <= 0:
            return None

        body = abs(
            c["close"] - c["open"]
        )

        body_ratio = (
            body / candle_range
        )

        bullish_candle = (
            c["close"] > c["open"]
        )

        strong_candle = (
            bullish_candle
            and body_ratio >= 0.50
        )

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        momentum = (
            move >= MIN_UP_MOVE
            and move >= previous_move
        )

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        old_volumes = [
            x["volume"]
            for x in candles[-11:-1]
        ]

        avg_volume = (
            sum(old_volumes)
            / len(old_volumes)
            if old_volumes
            else 0
        )

        volume_ok = (
            avg_volume > 0
            and c["volume"]
            >= avg_volume * 0.70
        )

        # ----------------------------------------------------
        # ATR
        # ----------------------------------------------------

        atr = calculate_atr(
            candles
        )

        if atr <= 0:
            return None

        # ----------------------------------------------------
        # UPWARD SCORE
        # فقط برای رتبه‌بندی است
        # ----------------------------------------------------

        score = 0

        if trend_bullish:
            score += 2

        if bullish_candle:
            score += 1

        if strong_candle:
            score += 1

        if momentum:
            score += 2

        if breakout:
            score += 3

        elif near_breakout:
            score += 2

        if volume_ok:
            score += 1

        # ----------------------------------------------------
        # ONLY UPWARD CANDIDATES
        # ----------------------------------------------------

        if not trend_bullish:
            return None

        if move < MIN_UP_MOVE and not breakout:
            return None

        # ----------------------------------------------------
        # SIGNAL
        # ----------------------------------------------------

        if (
            breakout
            and bullish_candle
            and strong_candle
            and momentum
        ):

            signal = "BUY"

        elif (
            near_breakout
            and bullish_candle
            and momentum
        ):

            signal = "WATCH BUY"

        else:

            signal = "UPWARD WATCH"

        # ----------------------------------------------------
        # LEVELS
        # ----------------------------------------------------

        entry = price

        sl = entry - (
            atr * SL_ATR
        )

        tp1 = entry + (
            atr * TP1_ATR
        )

        tp2 = entry + (
            atr * TP2_ATR
        )

        return {
            "symbol": symbol,
            "signal": signal,
            "price": price,
            "move": move,
            "previous_move": previous_move,
            "score": score,
            "trend": trend_bullish,
            "breakout": breakout,
            "near_breakout": near_breakout,
            "momentum": momentum,
            "strong_candle": strong_candle,
            "volume_ok": volume_ok,
            "resistance": resistance,
            "support": support,
            "distance": distance_to_resistance,
            "entry": entry,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "candle_time": c["time"]
        }

    except Exception as e:

        print(
            f"{symbol} ERROR: {e}"
        )

        return None


# ============================================================
# GET USDT MARKETS
# ============================================================

def get_markets():

    data = get_exchange_info()

    markets = []

    for item in data:

        try:

            symbol = str(
                item.get(
                    "symbol",
                    ""
                )
            ).upper()

            status = str(
                item.get(
                    "status",
                    ""
                )
            ).upper()

            quote = str(
                item.get(
                    "quoteAsset",
                    ""
                )
            ).upper()

            if (
                symbol
                and quote == "USDT"
                and status == "TRADING"
            ):

                markets.append(
                    symbol
                )

        except Exception:
            continue

    return markets


# ============================================================
# SCAN ALL
# ============================================================

def scan(markets):

    results = []

    total = len(markets)

    print(
        f"Scanning {total} markets..."
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze,
                symbol
            ): symbol
            for symbol in markets
        }

        completed = 0

        for future in as_completed(
            futures
        ):

            completed += 1

            try:

                result = future.result()

                if result:
                    results.append(
                        result
                    )

            except Exception as e:

                print(
                    "WORKER ERROR:",
                    e
                )

            if completed % 50 == 0:

                print(
                    f"Progress "
                    f"{completed}/{total}"
                )

    # --------------------------------------------------------
    # اول BUY
    # سپس WATCH BUY
    # سپس UPWARD WATCH
    # --------------------------------------------------------

    priority = {
        "BUY": 3,
        "WATCH BUY": 2,
        "UPWARD WATCH": 1
    }

    results.sort(
        key=lambda x: (
            priority.get(
                x["signal"],
                0
            ),
            x["score"],
            x["move"],
            -x["distance"]
        ),
        reverse=True
    )

    return results[:TOP_RESULTS]


# ============================================================
# PRICE FORMAT
# ============================================================

def price_fmt(value):

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

def make_message(
    results,
    market_count
):

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    lines = []

    lines.append(
        "⚡ ATI CRYPTO BOT V31"
    )

    lines.append(
        "🚀 TOP UPWARD COIN SCANNER"
    )

    lines.append(
        "⏱ Timeframe: 5m"
    )

    lines.append(
        "✅ CLOSED CANDLE"
    )

    lines.append(
        "💥 BREAKOUT + MOMENTUM"
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
            "⚪ NO UPWARD MARKET FOUND"
        )

    else:

        lines.append(
            f"🔥 TOP {len(results)} UPWARD MARKETS"
        )

        lines.append("")

        for i, r in enumerate(
            results,
            1
        ):

            if r["signal"] == "BUY":
                emoji = "🟢"
            elif r["signal"] == "WATCH BUY":
                emoji = "🟡"
            else:
                emoji = "🔵"

            candle_time = datetime.fromtimestamp(
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
                f"💰 PRICE: ${price_fmt(r['price'])}"
            )

            lines.append(
                f"📈 5M MOVE: "
                f"{r['move']:+.2f}%"
            )

            lines.append(
                f"🔥 UPWARD SCORE: "
                f"{r['score']}"
            )

            lines.append(
                f"🏗 TREND: "
                f"{'BULLISH' if r['trend'] else 'MIXED'}"
            )

            lines.append(
                f"💥 BREAKOUT: "
                f"{'YES' if r['breakout'] else 'NO'}"
            )

            lines.append(
                f"📍 TO RESISTANCE: "
                f"{r['distance']:.2f}%"
            )

            lines.append(
                f"🚀 MOMENTUM: "
                f"{'BULLISH' if r['momentum'] else 'WEAK'}"
            )

            lines.append(
                f"🎯 ENTRY: "
                f"${price_fmt(r['entry'])}"
            )

            lines.append(
                f"🛑 SL: "
                f"${price_fmt(r['sl'])}"
            )

            lines.append(
                f"🎯 TP1: "
                f"${price_fmt(r['tp1'])}"
            )

            lines.append(
                f"🎯 TP2: "
                f"${price_fmt(r['tp2'])}"
            )

            lines.append(
                f"📏 RESISTANCE: "
                f"${price_fmt(r['resistance'])}"
            )

            lines.append(
                f"📏 SUPPORT: "
                f"${price_fmt(r['support'])}"
            )

            lines.append(
                f"🕐 Candle: {candle_time}"
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
        "========================================"
    )

    print(
        "ATI CRYPTO BOT V31"
    )

    print(
        "TOP UPWARD COIN SCANNER"
    )

    print(
        "========================================"
    )

    try:

        markets = get_markets()

        if not markets:
            raise RuntimeError(
                "No USDT markets found"
            )

        print(
            f"USDT MARKETS FOUND: "
            f"{len(markets)}"
        )

        results = scan(
            markets
        )

        message = make_message(
            results,
            len(markets)
        )

        print("")
        print(message)
        print("")

        if send_telegram(
            message
        ):

            print(
                "TELEGRAM: OK"
            )

        else:

            print(
                "TELEGRAM: FAILED"
            )

    except Exception as e:

        error = (
            "🛡 ATI SAFETY\n\n"
            "❌ BOT ERROR\n"
            f"{type(e).__name__}: {e}"
        )

        print(error)

        send_telegram(error)


if __name__ == "__main__":
    main()
