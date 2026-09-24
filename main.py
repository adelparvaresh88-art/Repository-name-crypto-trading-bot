import os
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ATI CRYPTO BOT V32
# STRICT UPWARD COIN SCANNER
# 5M CLOSED CANDLE
# BREAKOUT + MOMENTUM + VOLUME + STRUCTURE
# PAPER / TEST ONLY
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
TRADE_LIMIT = 250
MIN_CANDLES = 40

MAX_WORKERS = 12
MAX_BUYS = 5
MAX_WATCH = 3

# ============================================================
# STRICT SETTINGS
# ============================================================

MIN_5M_MOVE = 0.10

# Breakout must close at least 0.15% above resistance
MIN_BREAKOUT_PCT = 0.0015

# Do not chase a coin that already moved too far
MAX_CHASE_PCT = 0.015

# Candle body / range
MIN_BODY_RATIO = 0.55

# Close must be near the high
MIN_CLOSE_POSITION = 0.65

# Momentum
MOMENTUM_LOOKBACK = 3
MIN_MOMENTUM_PCT = 0.15

# Volume
VOLUME_LOOKBACK = 10
MIN_VOLUME_RATIO = 1.20

# Resistance
RESISTANCE_LOOKBACK = 20

# ATR
ATR_PERIOD = 14

SL_ATR = 1.20
TP1_ATR = 1.50
TP2_ATR = 2.40

# Watch zone:
# price must be very close to resistance
WATCH_MAX_DISTANCE = 0.003

# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN"
)

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID"
)

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT-V32"
})


def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN:
        print("TELEGRAM_BOT_TOKEN MISSING")
        return False

    if not TELEGRAM_CHAT_ID:
        print("TELEGRAM_CHAT_ID MISSING")
        return False

    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=15
        )

        if not response.ok:

            print(
                "Telegram error:",
                response.status_code,
                response.text[:500]
            )

        return response.ok

    except Exception as e:

        print(
            "Telegram exception:",
            e
        )

        return False


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    url = (
        f"{BASE_URL}/r/api/v1/exchangeInfo"
    )

    response = session.get(
        url,
        timeout=20
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):

        if isinstance(
            data.get("symbols"),
            list
        ):
            data = data["symbols"]

        elif isinstance(
            data.get("data"),
            list
        ):
            data = data["data"]

    if not isinstance(data, list):

        raise RuntimeError(
            "Invalid exchangeInfo response"
        )

    return data


def get_usdt_symbols():

    markets = get_exchange_info()

    symbols = []

    for item in markets:

        if not isinstance(
            item,
            dict
        ):
            continue

        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper()

        quote = str(
            item.get(
                "quoteAsset",
                ""
            )
        ).upper()

        status = str(
            item.get(
                "status",
                ""
            )
        ).upper()

        if (
            symbol.endswith("USDT")
            and quote == "USDT"
            and status == "TRADING"
        ):

            symbols.append(symbol)

    return sorted(
        set(symbols)
    )


# ============================================================
# KLINES
# ============================================================

def get_klines(symbol):

    url = (
        f"{BASE_URL}/r/api/v1/klines"
    )

    params = {
        "symbol": symbol,
        "interval": TIMEFRAME,
        "limit": TRADE_LIMIT
    }

    response = session.get(
        url,
        params=params,
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):

        if isinstance(
            data.get("data"),
            list
        ):
            data = data["data"]

        elif isinstance(
            data.get("result"),
            list
        ):
            data = data["result"]

    if not isinstance(
        data,
        list
    ):
        raise RuntimeError(
            f"Invalid klines for {symbol}"
        )

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

        raise RuntimeError(
            f"Not enough candles: {symbol}"
        )

    # ========================================================
    # REMOVE CURRENT OPEN CANDLE
    # ========================================================

    now_ms = int(
        datetime.now(
            timezone.utc
        ).timestamp() * 1000
    )

    candle_ms = 5 * 60 * 1000

    last = candles[-1]

    if (
        last["time"] > 0
        and now_ms <
        last["time"] + candle_ms
    ):

        candles = candles[:-1]

    if len(candles) < MIN_CANDLES:

        raise RuntimeError(
            f"Not enough CLOSED candles: {symbol}"
        )

    return candles


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles):

    if len(candles) < ATR_PERIOD + 1:

        return 0

    true_ranges = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"]
            - current["low"],

            abs(
                current["high"]
                - previous["close"]
            ),

            abs(
                current["low"]
                - previous["close"]
            )
        )

        true_ranges.append(tr)

    if len(true_ranges) < ATR_PERIOD:

        return 0

    return (
        sum(
            true_ranges[-ATR_PERIOD:]
        )
        / ATR_PERIOD
    )


# ============================================================
# RESISTANCE
# ============================================================

def get_resistance(candles):

    history = candles[
        -(RESISTANCE_LOOKBACK + 1):-1
    ]

    if len(history) < 10:

        return 0

    return max(
        c["high"]
        for c in history
    )


# ============================================================
# SUPPORT
# ============================================================

def get_support(candles):

    history = candles[
        -(RESISTANCE_LOOKBACK + 1):-1
    ]

    if len(history) < 10:

        return 0

    return min(
        c["low"]
        for c in history
    )


# ============================================================
# CANDLE STRENGTH
# ============================================================

def check_candle_strength(candle):

    high = candle["high"]
    low = candle["low"]
    open_price = candle["open"]
    close = candle["close"]

    candle_range = high - low

    if candle_range <= 0:

        return False

    body = abs(
        close - open_price
    )

    body_ratio = (
        body / candle_range
    )

    close_position = (
        (close - low)
        / candle_range
    )

    return (
        close > open_price
        and body_ratio >= MIN_BODY_RATIO
        and close_position >= MIN_CLOSE_POSITION
    )


# ============================================================
# MOMENTUM
# ============================================================

def get_momentum(candles):

    if len(candles) <= MOMENTUM_LOOKBACK:

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
# VOLUME
# ============================================================

def get_volume_ratio(candles):

    if len(candles) < VOLUME_LOOKBACK + 1:

        return 0

    current_volume = candles[-1]["volume"]

    previous_volumes = [
        c["volume"]
        for c in candles[
            -1 - VOLUME_LOOKBACK:-1
        ]
    ]

    average_volume = (
        sum(previous_volumes)
        / len(previous_volumes)
    )

    if average_volume <= 0:

        return 0

    return (
        current_volume
        / average_volume
    )


# ============================================================
# TREND
# ============================================================

def trend_bullish(candles):

    if len(candles) < 6:

        return False

    return (
        candles[-1]["close"]
        > candles[-3]["close"]
        > candles[-5]["close"]
    )


# ============================================================
# ANALYZE
# ============================================================

def analyze_symbol(symbol):

    try:

        candles = get_klines(
            symbol
        )

        current = candles[-1]

        previous = candles[-2]

        price = current["close"]

        if price <= 0:

            return None

        resistance = get_resistance(
            candles
        )

        support = get_support(
            candles
        )

        if resistance <= 0:

            return None

        # ----------------------------------------------------
        # 5M MOVE
        # ----------------------------------------------------

        move = (
            (
                price
                - previous["close"]
            )
            / previous["close"]
        ) * 100

        if move < MIN_5M_MOVE:

            return None

        # ----------------------------------------------------
        # BREAKOUT DISTANCE
        # ----------------------------------------------------

        breakout_distance = (
            price - resistance
        ) / resistance

        breakout = (
            breakout_distance
            >= MIN_BREAKOUT_PCT
        )

        # ----------------------------------------------------
        # CANDLE
        # ----------------------------------------------------

        candle_ok = check_candle_strength(
            current
        )

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        momentum = get_momentum(
            candles
        )

        momentum_ok = (
            momentum >= MIN_MOMENTUM_PCT
        )

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        volume_ratio = get_volume_ratio(
            candles
        )

        volume_ok = (
            volume_ratio
            >= MIN_VOLUME_RATIO
        )

        # ----------------------------------------------------
        # TREND
        # ----------------------------------------------------

        trend_ok = trend_bullish(
            candles
        )

        # ----------------------------------------------------
        # CHASE FILTER
        # ----------------------------------------------------

        not_overextended = (
            breakout_distance
            <= MAX_CHASE_PCT
        )

        # ----------------------------------------------------
        # BUY
        # ----------------------------------------------------

        buy = (
            breakout
            and candle_ok
            and momentum_ok
            and volume_ok
            and trend_ok
            and not_overextended
        )

        # ----------------------------------------------------
        # WATCH
        #
        # Only coins very close to resistance
        # and with momentum + trend.
        # ----------------------------------------------------

        distance_to_resistance = (
            resistance - price
        ) / resistance

        near_resistance = (
            0 <= distance_to_resistance
            <= WATCH_MAX_DISTANCE
        )

        watch = (
            not buy
            and near_resistance
            and candle_ok
            and momentum_ok
            and volume_ok
            and trend_ok
        )

        if not buy and not watch:

            return None

        # ----------------------------------------------------
        # ATR
        # ----------------------------------------------------

        atr = calculate_atr(
            candles
        )

        if atr <= 0:

            return None

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
            current["time"] / 1000,
            tz=timezone.utc
        )

        # ----------------------------------------------------
        # QUALITY
        # ----------------------------------------------------

        quality = 0

        if breakout:
            quality += 1

        if candle_ok:
            quality += 1

        if momentum_ok:
            quality += 1

        if volume_ok:
            quality += 1

        if trend_ok:
            quality += 1

        if not_overextended:
            quality += 1

        if price > resistance:
            quality += 1

        signal = (
            "BUY"
            if buy
            else "WATCH BUY"
        )

        return {
            "symbol": symbol,
            "signal": signal,
            "price": price,
            "move": move,
            "resistance": resistance,
            "support": support,
            "breakout_distance": breakout_distance,
            "distance_to_resistance": distance_to_resistance,
            "momentum": momentum,
            "volume_ratio": volume_ratio,
            "quality": quality,
            "candle_ok": candle_ok,
            "momentum_ok": momentum_ok,
            "volume_ok": volume_ok,
            "trend_ok": trend_ok,
            "not_overextended": not_overextended,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "candle_time": candle_time
        }

    except Exception as e:

        print(
            f"{symbol}: {e}"
        )

        return None


# ============================================================
# PRICE FORMAT
# ============================================================

def format_price(price):

    if price >= 1000:

        return f"{price:,.2f}"

    if price >= 1:

        return f"{price:.4f}"

    if price >= 0.01:

        return f"{price:.6f}"

    if price >= 0.0001:

        return f"{price:.8f}"

    if price >= 0.000001:

        return f"{price:.10f}"

    return f"{price:.12f}"


# ============================================================
# SCAN
# ============================================================

def scan_market(symbols):

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                analyze_symbol,
                symbol
            )
            for symbol in symbols
        ]

        for future in as_completed(
            futures
        ):

            try:

                result = future.result()

                if result:

                    results.append(
                        result
                    )

            except Exception as e:

                print(
                    "Worker error:",
                    e
                )

    return results


# ============================================================
# MESSAGE
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

    buys = [
        x for x in results
        if x["signal"] == "BUY"
    ]

    watches = [
        x for x in results
        if x["signal"] == "WATCH BUY"
    ]

    buys.sort(
        key=lambda x: (
            x["quality"],
            x["momentum"],
            x["volume_ratio"]
        ),
        reverse=True
    )

    watches.sort(
        key=lambda x: (
            x["quality"],
            -abs(
                x["distance_to_resistance"]
            ),
            x["momentum"]
        ),
        reverse=True
    )

    selected = (
        buys[:MAX_BUYS]
        +
        watches[:MAX_WATCH]
    )

    lines = []

    lines.append(
        "⚡ ATI CRYPTO BOT V32"
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
        "💥 BREAKOUT + MOMENTUM + VOLUME"
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
            "⚪ NO STRICT UPWARD SETUP"
        )

        lines.append("")
        lines.append(
            "⏳ WAITING FOR CONFIRMATION"
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

        return "\n".join(
            lines
        )

    lines.append(
        f"🔥 BUY: {len(buys)}"
    )

    lines.append(
        f"🟡 WATCH: {len(watches)}"
    )

    for index, item in enumerate(
        selected,
        1
    ):

        if item["signal"] == "BUY":

            emoji = "🟢"

        else:

            emoji = "🟡"

        lines.append("")

        lines.append(
            f"{emoji} #{index} "
            f"{item['symbol']}"
        )

        lines.append(
            f"📊 SIGNAL: "
            f"{item['signal']}"
        )

        lines.append(
            f"💰 PRICE: "
            f"${format_price(item['price'])}"
        )

        lines.append(
            f"📈 5M MOVE: "
            f"{item['move']:+.2f}%"
        )

        lines.append(
            f"🔥 QUALITY: "
            f"{item['quality']}/7"
        )

        lines.append(
            "🏗 TREND: "
            + (
                "BULLISH"
                if item["trend_ok"]
                else "WEAK"
            )
        )

        lines.append(
            "💥 BREAKOUT: "
            + (
                "CONFIRMED"
                if item["breakout_distance"]
                >= MIN_BREAKOUT_PCT
                else "WAIT"
            )
        )

        if item["breakout_distance"] >= 0:

            lines.append(
                "📍 ABOVE RESISTANCE: "
                f"{item['breakout_distance'] * 100:.2f}%"
            )

        else:

            lines.append(
                "📍 TO RESISTANCE: "
                f"{abs(item['distance_to_resistance']) * 100:.2f}%"
            )

        lines.append(
            "🕯 CANDLE: "
            + (
                "STRONG"
                if item["candle_ok"]
                else "WEAK"
            )
        )

        lines.append(
            "🚀 MOMENTUM: "
            + (
                "BULLISH"
                if item["momentum_ok"]
                else "WEAK"
            )
        )

        lines.append(
            f"📊 VOLUME: "
            f"{item['volume_ratio']:.2f}x"
        )

        lines.append(
            f"🎯 ENTRY: "
            f"${format_price(item['price'])}"
        )

        lines.append(
            f"🛑 SL: "
            f"${format_price(item['sl'])}"
        )

        lines.append(
            f"🎯 TP1: "
            f"${format_price(item['tp1'])}"
        )

        lines.append(
            f"🎯 TP2: "
            f"${format_price(item['tp2'])}"
        )

        lines.append(
            f"📏 RESISTANCE: "
            f"${format_price(item['resistance'])}"
        )

        lines.append(
            f"📏 SUPPORT: "
            f"${format_price(item['support'])}"
        )

        lines.append(
            "🕐 Candle: "
            + item["candle_time"].strftime(
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

    return "\n".join(
        lines
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print(
        "ATI CRYPTO BOT V32"
    )
    print(
        "STRICT UPWARD COIN SCANNER"
    )
    print("=" * 60)

    try:

        symbols = get_usdt_symbols()

        print(
            f"USDT MARKETS: "
            f"{len(symbols)}"
        )

        if not symbols:

            raise RuntimeError(
                "No USDT markets found"
            )

        results = scan_market(
            symbols
        )

        print(
            f"QUALIFIED: "
            f"{len(results)}"
        )

        message = build_message(
            results,
            len(symbols)
        )

        print("")
        print(message)
        print("")

        telegram_ok = send_telegram(
            message
        )

        if telegram_ok:

            print(
                "TELEGRAM: OK"
            )

        else:

            print(
                "TELEGRAM: FAILED"
            )

    except Exception as e:

        print(
            "FATAL ERROR:",
            e
        )

        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "❌ BOT ERROR\n"
            f"{str(e)}"
        )


if __name__ == "__main__":

    main()
