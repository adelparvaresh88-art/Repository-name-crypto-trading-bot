import os
import math
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ATI CRYPTO BOT V31
# STRICT UPWARD COIN SCANNER
# 5M CLOSED CANDLE
# BREAKOUT + MOMENTUM + VOLUME + RETEST
# PAPER / TEST ONLY
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
TRADE_LIMIT = 250
MIN_CANDLES = 30

MAX_WORKERS = 12
TOP_RESULTS = 10

# Minimum 5m movement
MIN_UP_MOVE = 0.20

# Strict filters
MIN_QUALITY_BUY = 6
MIN_QUALITY_WATCH = 5

# Breakout
BREAKOUT_BUFFER = 0.0015       # 0.15%
MAX_BREAKOUT_DISTANCE = 0.025  # avoid chasing >2.5%

# Candle strength
MIN_BODY_RATIO = 0.55

# Momentum
MOMENTUM_LOOKBACK = 3
MIN_MOMENTUM = 0.15

# Volume
VOLUME_LOOKBACK = 10
MIN_VOLUME_RATIO = 1.10

# ATR
ATR_PERIOD = 14
SL_ATR = 1.20
TP1_ATR = 1.50
TP2_ATR = 2.40

# Retest
RETEST_TOLERANCE = 0.006

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

        if not r.ok:
            print("Telegram HTTP:", r.status_code)
            print(r.text[:500])

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
# SYMBOL FILTER
# ============================================================

def get_usdt_symbols():

    markets = get_exchange_info()

    symbols = []

    for item in markets:

        if not isinstance(item, dict):
            continue

        symbol = str(
            item.get("symbol", "")
        ).upper()

        status = str(
            item.get("status", "")
        ).upper()

        quote = str(
            item.get("quoteAsset", "")
        ).upper()

        if (
            symbol.endswith("USDT")
            and quote == "USDT"
            and status == "TRADING"
        ):
            symbols.append(symbol)

    return sorted(set(symbols))


# ============================================================
# CANDLES
# ============================================================

def get_klines(symbol):

    endpoints = [
        "/r/api/v1/klines",
        "/api/v1/klines",
    ]

    params = {
        "symbol": symbol,
        "interval": TIMEFRAME,
        "limit": TRADE_LIMIT
    }

    last_error = None

    for endpoint in endpoints:

        try:

            url = BASE_URL + endpoint

            r = session.get(
                url,
                params=params,
                timeout=12
            )

            if r.ok:

                data = r.json()

                if isinstance(data, dict):

                    if "data" in data:
                        data = data["data"]

                    elif "result" in data:
                        data = data["result"]

                if isinstance(data, list) and len(data) >= MIN_CANDLES:
                    return normalize_klines(data)

            last_error = (
                f"{endpoint} HTTP {r.status_code}"
            )

        except Exception as e:
            last_error = str(e)

    raise RuntimeError(
        f"Klines failed for {symbol}: {last_error}"
    )


# ============================================================
# NORMALIZE CANDLES
# ============================================================

def normalize_klines(data):

    candles = []

    for k in data:

        try:

            if isinstance(k, dict):

                o = float(
                    k.get("open")
                    or k.get("o")
                )

                h = float(
                    k.get("high")
                    or k.get("h")
                )

                l = float(
                    k.get("low")
                    or k.get("l")
                )

                c = float(
                    k.get("close")
                    or k.get("c")
                )

                v = float(
                    k.get("volume")
                    or k.get("v")
                    or 0
                )

                t = int(
                    k.get("openTime")
                    or k.get("timestamp")
                    or k.get("t")
                    or 0
                )

            else:

                o = float(k[1])
                h = float(k[2])
                l = float(k[3])
                c = float(k[4])
                v = float(k[5])
                t = int(k[0])

            candles.append({
                "time": t,
                "open": o,
                "high": h,
                "low": l,
                "close": c,
                "volume": v
            })

        except Exception:
            continue

    if len(candles) < MIN_CANDLES:
        raise RuntimeError("Not enough valid candles")

    # Remove possible currently-open candle.
    # The scanner works on CLOSED candles only.
    now_ms = int(
        datetime.now(timezone.utc).timestamp() * 1000
    )

    timeframe_ms = 5 * 60 * 1000

    if candles:

        last = candles[-1]

        if (
            last["time"] > 0
            and now_ms < last["time"] + timeframe_ms
        ):
            candles = candles[:-1]

    return candles


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=ATR_PERIOD):

    if len(candles) < period + 1:
        return 0

    trs = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(
                current["high"] -
                previous["close"]
            ),
            abs(
                current["low"] -
                previous["close"]
            )
        )

        trs.append(tr)

    if len(trs) < period:
        return 0

    return sum(
        trs[-period:]
    ) / period


# ============================================================
# RESISTANCE
# ============================================================

def find_resistance(candles):

    # Exclude the signal candle itself
    history = candles[:-1]

    if len(history) < 15:
        return None

    recent = history[-20:]

    resistance = max(
        c["high"]
        for c in recent
    )

    return resistance


# ============================================================
# SUPPORT
# ============================================================

def find_support(candles):

    history = candles[:-1]

    if len(history) < 10:
        return None

    recent = history[-20:]

    return min(
        c["low"]
        for c in recent
    )


# ============================================================
# CANDLE STRENGTH
# ============================================================

def candle_strength(candle):

    high = candle["high"]
    low = candle["low"]
    open_price = candle["open"]
    close = candle["close"]

    candle_range = high - low

    if candle_range <= 0:
        return False, 0

    body = abs(
        close - open_price
    )

    body_ratio = body / candle_range

    close_position = (
        close - low
    ) / candle_range

    bullish = (
        close > open_price
        and body_ratio >= MIN_BODY_RATIO
        and close_position >= 0.65
    )

    score = int(
        min(
            100,
            body_ratio * 100
        )
    )

    return bullish, score


# ============================================================
# MOMENTUM
# ============================================================

def calculate_momentum(candles):

    if len(candles) < MOMENTUM_LOOKBACK + 1:
        return 0

    current = candles[-1]["close"]

    previous = candles[
        -1 - MOMENTUM_LOOKBACK
    ]["close"]

    if previous <= 0:
        return 0

    return (
        (current - previous)
        / previous
    ) * 100


# ============================================================
# VOLUME CONFIRMATION
# ============================================================

def volume_confirmation(candles):

    if len(candles) < VOLUME_LOOKBACK + 1:
        return False, 0

    current_volume = candles[-1]["volume"]

    previous = [
        c["volume"]
        for c in candles[
            -1 - VOLUME_LOOKBACK:-1
        ]
    ]

    if not previous:
        return False, 0

    avg_volume = sum(previous) / len(previous)

    if avg_volume <= 0:
        return False, 0

    ratio = current_volume / avg_volume

    return (
        ratio >= MIN_VOLUME_RATIO,
        ratio
    )


# ============================================================
# RETEST CHECK
# ============================================================

def retest_confirmation(
    candles,
    resistance,
    price
):

    if resistance <= 0:
        return False

    distance = abs(
        price - resistance
    ) / resistance

    # Price close to breakout level
    if distance <= RETEST_TOLERANCE:

        # Previous candle touched/approached resistance
        previous = candles[-2]

        previous_touch = (
            previous["low"]
            <= resistance * 1.003
        )

        return previous_touch

    # If price has already moved above resistance,
    # allow only a controlled breakout.
    if price > resistance:

        breakout_distance = (
            price - resistance
        ) / resistance

        if (
            breakout_distance
            <= MAX_BREAKOUT_DISTANCE
        ):
            return True

    return False


# ============================================================
# SCORE ENGINE
# ============================================================

def analyze_symbol(symbol):

    try:

        candles = get_klines(symbol)

        if len(candles) < MIN_CANDLES:
            return None

        signal_candle = candles[-1]

        price = signal_candle["close"]

        resistance = find_resistance(
            candles
        )

        support = find_support(
            candles
        )

        if not resistance or not support:
            return None

        if price <= 0:
            return None

        move = (
            (
                price
                - candles[-2]["close"]
            )
            / candles[-2]["close"]
        ) * 100

        if move < MIN_UP_MOVE:
            return None

        # ----------------------------------------------------
        # CONDITIONS
        # ----------------------------------------------------

        breakout = (
            price
            >= resistance
            * (1 + BREAKOUT_BUFFER)
        )

        bullish_candle, candle_score = (
            candle_strength(signal_candle)
        )

        momentum = calculate_momentum(
            candles
        )

        momentum_ok = (
            momentum >= MIN_MOMENTUM
        )

        volume_ok, volume_ratio = (
            volume_confirmation(candles)
        )

        retest_ok = retest_confirmation(
            candles,
            resistance,
            price
        )

        trend_bullish = (
            candles[-1]["close"]
            > candles[-5]["close"]
        )

        # ----------------------------------------------------
        # QUALITY
        # ----------------------------------------------------

        quality = 0

        if breakout:
            quality += 1

        if bullish_candle:
            quality += 1

        if momentum_ok:
            quality += 1

        if volume_ok:
            quality += 1

        if retest_ok:
            quality += 1

        if trend_bullish:
            quality += 1

        # Extra price structure confirmation
        if price > resistance:
            quality += 1

        # ----------------------------------------------------
        # STRICT BUY
        # ----------------------------------------------------

        strong_buy = (
            breakout
            and bullish_candle
            and momentum_ok
            and volume_ok
            and trend_bullish
            and quality >= MIN_QUALITY_BUY
        )

        # ----------------------------------------------------
        # WATCH BUY
        # ----------------------------------------------------

        watch_buy = (
            not strong_buy
            and quality >= MIN_QUALITY_WATCH
            and trend_bullish
            and momentum_ok
        )

        # Do not chase extreme moves
        if breakout:

            breakout_distance = (
                price - resistance
            ) / resistance

            if breakout_distance > MAX_BREAKOUT_DISTANCE:
                strong_buy = False

        atr = calculate_atr(candles)

        if atr <= 0:
            return None

        # ----------------------------------------------------
        # SL / TP
        # ----------------------------------------------------

        sl = price - (
            atr * SL_ATR
        )

        tp1 = price + (
            atr * TP1_ATR
        )

        tp2 = price + (
            atr * TP2_ATR
        )

        if sl <= 0:
            return None

        candle_time = datetime.fromtimestamp(
            signal_candle["time"] / 1000,
            tz=timezone.utc
        )

        return {
            "symbol": symbol,
            "price": price,
            "move": move,
            "resistance": resistance,
            "support": support,
            "atr": atr,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "breakout": breakout,
            "bullish_candle": bullish_candle,
            "momentum": momentum,
            "momentum_ok": momentum_ok,
            "volume_ratio": volume_ratio,
            "volume_ok": volume_ok,
            "retest_ok": retest_ok,
            "trend_bullish": trend_bullish,
            "quality": quality,
            "signal": (
                "BUY"
                if strong_buy
                else "WATCH BUY"
                if watch_buy
                else "NO SIGNAL"
            ),
            "candle_time": candle_time
        }

    except Exception as e:

        print(
            f"{symbol} ERROR: {e}"
        )

        return None


# ============================================================
# FORMAT PRICE
# ============================================================

def fmt_price(value):

    if value >= 1000:
        return f"{value:.2f}"

    if value >= 1:
        return f"{value:.4f}"

    if value >= 0.01:
        return f"{value:.6f}"

    return f"{value:.10f}"


# ============================================================
# SCAN
# ============================================================

def scan_market(symbols):

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol
            ): symbol
            for symbol in symbols
        }

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception as e:

                print(
                    "Worker error:",
                    e
                )

    return results


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def build_message(
    results,
    market_count
):

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    strong = [
        r for r in results
        if r["signal"] == "BUY"
    ]

    watch = [
        r for r in results
        if r["signal"] == "WATCH BUY"
    ]

    strong.sort(
        key=lambda x: (
            x["quality"],
            x["momentum"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    watch.sort(
        key=lambda x: (
            x["quality"],
            x["momentum"]
        ),
        reverse=True
    )

    selected = (
        strong[:TOP_RESULTS]
        if strong
        else watch[:TOP_RESULTS]
    )

    lines = []

    lines.append(
        "⚡ ATI CRYPTO BOT V31"
    )

    lines.append(
        "🚀 STRICT UPWARD COIN SCANNER"
    )

    lines.append(
        "⏱ Timeframe: 5m"
    )

    lines.append(
        "✅ CLOSED CANDLE"
    )

    lines.append(
        "🛡 BREAKOUT + MOMENTUM + VOLUME + RETEST"
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

    if not selected:

        lines.append(
            "⚪ NO STRONG UPWARD SETUP"
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

    lines.append(
        "🔥 TOP UPWARD OPPORTUNITIES"
    )

    for index, r in enumerate(
        selected,
        start=1
    ):

        signal = r["signal"]

        emoji = (
            "🟢"
            if signal == "BUY"
            else "🟡"
        )

        lines.append("")

        lines.append(
            f"{emoji} #{index} {r['symbol']}"
        )

        lines.append(
            f"📊 SIGNAL: {signal}"
        )

        lines.append(
            f"💰 PRICE: ${fmt_price(r['price'])}"
        )

        lines.append(
            f"📈 5M MOVE: {r['move']:+.2f}%"
        )

        lines.append(
            "🏗 TREND: "
            + (
                "BULLISH"
                if r["trend_bullish"]
                else "WEAK"
            )
        )

        lines.append(
            "💥 BREAKOUT: "
            + (
                "CONFIRMED"
                if r["breakout"]
                else "WATCH"
            )
        )

        lines.append(
            "🕯 CANDLE: "
            + (
                "STRONG"
                if r["bullish_candle"]
                else "WEAK"
            )
        )

        lines.append(
            "🚀 MOMENTUM: "
            + (
                "PASS"
                if r["momentum_ok"]
                else "WEAK"
            )
        )

        lines.append(
            f"📊 VOLUME: "
            f"{r['volume_ratio']:.2f}x "
            + (
                "PASS"
                if r["volume_ok"]
                else "WEAK"
            )
        )

        lines.append(
            "🔄 RETEST: "
            + (
                "PASS"
                if r["retest_ok"]
                else "WAIT"
            )
        )

        lines.append(
            f"⭐ QUALITY: {r['quality']}/7"
        )

        lines.append(
            f"🎯 ENTRY: ${fmt_price(r['price'])}"
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
            f"📏 RESISTANCE: ${fmt_price(r['resistance'])}"
        )

        lines.append(
            f"📏 SUPPORT: ${fmt_price(r['support'])}"
        )

        lines.append(
            "🕐 Candle: "
            + r["candle_time"].strftime(
                "%H:%M UTC"
            )
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

    print("=" * 60)
    print("ATI CRYPTO BOT V31")
    print("STRICT UPWARD COIN SCANNER")
    print("=" * 60)

    try:

        symbols = get_usdt_symbols()

        print(
            f"USDT markets: {len(symbols)}"
        )

        if not symbols:

            raise RuntimeError(
                "No USDT markets found"
            )

        results = scan_market(
            symbols
        )

        print(
            f"Analyzed: {len(results)}"
        )

        message = build_message(
            results,
            len(symbols)
        )

        print("")
        print(message)
        print("")

        ok = send_telegram(
            message
        )

        if ok:
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
            f"{str(e)}"
        )

        print(error_message)

        send_telegram(
            error_message
        )


if __name__ == "__main__":
    main()
