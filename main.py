import os
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

# =========================================================
# ATI FUTURES V7.6
# ICHIMOKU 5M - SIGNAL MODE
# =========================================================

API_BASE = "https://api1.tabdeal.org"
PUBLIC_BASE = API_BASE + "/r/fapi/v1/"

INTERVAL = "5m"
KLINE_LIMIT = 100

WORKERS = 12
TIMEOUT = 7

# Ichimoku
TENKAN = 9
KIJUN = 26
SENKOU_B = 52

# Signal settings
MIN_SCORE = 4.0
MAX_KIJUN_DISTANCE = 4.0

# Scan
MAX_SYMBOLS = 100

TELEGRAM_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN", ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID", ""
).strip()

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-FUTURES-V7.6",
    "Accept": "application/json",
})


# =========================================================
# TIME
# =========================================================

def now():
    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# =========================================================
# TELEGRAM
# =========================================================

def telegram(text):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        requests.post(
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=8,
        )

    except Exception as e:
        print(
            "Telegram error:",
            e
        )


# =========================================================
# PUBLIC API
# =========================================================

def public_get(path, params=None):

    url = PUBLIC_BASE + path

    r = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    if r.status_code != 200:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:300]}"
        )

    return r.json()


# =========================================================
# SERVER
# =========================================================

def server_ok():

    try:

        data = public_get(
            "time"
        )

        return bool(
            data.get("serverTime")
        )

    except Exception as e:

        print(
            "Server error:",
            e
        )

        return False


# =========================================================
# SYMBOLS
# =========================================================

def get_symbols():

    data = public_get(
        "exchangeInfo"
    )

    result = []

    for item in data.get(
        "symbols",
        []
    ):

        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper()

        symbol = (
            symbol
            .replace("_", "")
            .replace("-", "")
            .replace("/", "")
        )

        if not symbol.endswith(
            "USDT"
        ):
            continue

        status = str(
            item.get(
                "status",
                "TRADING"
            )
        ).upper()

        if status not in (
            "TRADING",
            "ACTIVE",
            "ENABLED",
            "1",
        ):
            continue

        result.append(
            symbol
        )

    return list(
        dict.fromkeys(result)
    )


# =========================================================
# KLINES
# =========================================================

def get_klines(symbol):

    data = public_get(
        "klines",
        {
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": KLINE_LIMIT,
        }
    )

    if not isinstance(
        data,
        list
    ):

        return None

    if len(data) < 60:

        return None

    candles = []

    for x in data:

        candles.append({
            "open": float(x[1]),
            "high": float(x[2]),
            "low": float(x[3]),
            "close": float(x[4]),
            "volume": float(x[5]),
        })

    return candles


# =========================================================
# MIDPOINT
# =========================================================

def midpoint(
    candles,
    period,
    end=None
):

    if end is None:
        end = len(candles)

    if end < period:
        return None

    section = candles[
        end - period:end
    ]

    high = max(
        x["high"]
        for x in section
    )

    low = min(
        x["low"]
        for x in section
    )

    return (
        high + low
    ) / 2


# =========================================================
# ICHIMOKU
# =========================================================

def calculate(candles):

    # Use CLOSED candle
    i = len(candles) - 2

    previous = i - 1

    tenkan = midpoint(
        candles,
        TENKAN,
        i + 1
    )

    kijun = midpoint(
        candles,
        KIJUN,
        i + 1
    )

    span_b = midpoint(
        candles,
        SENKOU_B,
        i + 1
    )

    old_tenkan = midpoint(
        candles,
        TENKAN,
        previous + 1
    )

    old_kijun = midpoint(
        candles,
        KIJUN,
        previous + 1
    )

    if None in (
        tenkan,
        kijun,
        span_b,
        old_tenkan,
        old_kijun,
    ):

        return None

    span_a = (
        tenkan + kijun
    ) / 2

    cloud_top = max(
        span_a,
        span_b
    )

    cloud_bottom = min(
        span_a,
        span_b
    )

    candle = candles[i]

    price = candle["close"]

    bullish = (
        candle["close"]
        >
        candle["open"]
    )

    bearish = (
        candle["close"]
        <
        candle["open"]
    )

    volume_avg = sum(
        x["volume"]
        for x in candles[
            i - 20:i
        ]
    ) / 20

    volume_ok = (
        candle["volume"]
        >=
        volume_avg * 0.8
    )

    bullish_cross = (
        old_tenkan <= old_kijun
        and
        tenkan > kijun
    )

    bearish_cross = (
        old_tenkan >= old_kijun
        and
        tenkan < kijun
    )

    distance = (
        abs(price - kijun)
        /
        kijun
        *
        100
    )

    # =====================================================
    # BUY SCORE
    # =====================================================

    buy = 0

    if price > cloud_top:
        buy += 2.5

    elif price > cloud_bottom:
        buy += 1.5

    if tenkan > kijun:
        buy += 1.5

    if span_a > span_b:
        buy += 1.0

    if bullish_cross:
        buy += 2.0

    if bullish:
        buy += 0.5

    if volume_ok:
        buy += 0.5

    # =====================================================
    # SELL SCORE
    # =====================================================

    sell = 0

    if price < cloud_bottom:
        sell += 2.5

    elif price < cloud_top:
        sell += 1.5

    if tenkan < kijun:
        sell += 1.5

    if span_a < span_b:
        sell += 1.0

    if bearish_cross:
        sell += 2.0

    if bearish:
        sell += 0.5

    if volume_ok:
        sell += 0.5

    # =====================================================
    # KIJUN DISTANCE
    # =====================================================

    if distance > MAX_KIJUN_DISTANCE:

        return {
            "signal": None,
            "reason": "far_kijun",
        }

    # =====================================================
    # SIGNAL
    # =====================================================

    if buy >= MIN_SCORE and buy > sell:

        return {
            "signal": "BUY",
            "score": buy,
            "price": price,
            "tenkan": tenkan,
            "kijun": kijun,
            "cloud_top": cloud_top,
            "cloud_bottom": cloud_bottom,
            "distance": distance,
            "volume_ok": volume_ok,
            "cross": bullish_cross,
        }

    if sell >= MIN_SCORE and sell > buy:

        return {
            "signal": "SELL",
            "score": sell,
            "price": price,
            "tenkan": tenkan,
            "kijun": kijun,
            "cloud_top": cloud_top,
            "cloud_bottom": cloud_bottom,
            "distance": distance,
            "volume_ok": volume_ok,
            "cross": bearish_cross,
        }

    return {
        "signal": None,
        "buy": buy,
        "sell": sell,
    }


# =========================================================
# ANALYZE
# =========================================================

def analyze(symbol):

    try:

        candles = get_klines(
            symbol
        )

        if not candles:

            return {
                "symbol": symbol,
                "status": "error",
            }

        result = calculate(
            candles
        )

        if not result:

            return {
                "symbol": symbol,
                "status": "error",
            }

        if result.get(
            "signal"
        ):

            return {
                "symbol": symbol,
                "status": "signal",
                **result,
            }

        return {
            "symbol": symbol,
            "status": "no_signal",
            **result,
        }

    except Exception as e:

        return {
            "symbol": symbol,
            "status": "error",
            "error": str(e)[:300],
        }


# =========================================================
# SCAN
# =========================================================

def scan(symbols):

    start = time.time()

    results = []

    with ThreadPoolExecutor(
        max_workers=WORKERS
    ) as executor:

        jobs = {
            executor.submit(
                analyze,
                s
            ): s
            for s in symbols
        }

        for future in as_completed(
            jobs
        ):

            try:

                results.append(
                    future.result()
                )

            except Exception as e:

                results.append({
                    "symbol": jobs[future],
                    "status": "error",
                    "error": str(e),
                })

    return (
        results,
        time.time() - start
    )


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("=" * 65)
    print("💓 ATI FUTURES V7.6")
    print("⚡ ICHIMOKU 5M SIGNAL SCANNER")
    print("=" * 65)

    print(
        "☁️ Ichimoku: 9 / 26 / 52"
    )

    print(
        "🎯 Minimum score:",
        MIN_SCORE
    )

    print(
        "📏 Max Kijun distance:",
        MAX_KIJUN_DISTANCE,
        "%"
    )

    print(
        "🕐",
        now()
    )

    telegram(
        f"""💓 ATI FUTURES V7.6

⚡ ICHIMOKU 5M
☁️ 9 / 26 / 52

🎯 SIGNAL SCANNER ACTIVE

📡 TABDEAL FUTURES

🕐 {now()}"""
    )

    # -----------------------------------------------------
    # SERVER
    # -----------------------------------------------------

    if not server_ok():

        print(
            "🛑 API OFFLINE"
        )

        telegram(
            f"""🛑 ATI V7.6

❌ FUTURES API OFFLINE

🚫 NO SIGNAL
🚫 NO ORDER

🕐 {now()}"""
        )

        return

    # -----------------------------------------------------
    # SYMBOLS
    # -----------------------------------------------------

    try:

        symbols = get_symbols()

    except Exception as e:

        print(
            "❌ SYMBOL ERROR:",
            e
        )

        telegram(
            f"""🛑 ATI V7.6

❌ MARKET DATA ERROR

🚫 NO ORDER

{str(e)[:500]}"""
        )

        return

    symbols = symbols[
        :MAX_SYMBOLS
    ]

    print(
        "📊 Markets:",
        len(symbols)
    )

    # -----------------------------------------------------
    # SCAN
    # -----------------------------------------------------

    results, elapsed = scan(
        symbols
    )

    good = [
        x for x in results
        if x["status"] != "error"
    ]

    errors = [
        x for x in results
        if x["status"] == "error"
    ]

    signals = [
        x for x in results
        if x["status"] == "signal"
    ]

    print()
    print(
        "📡 Completed:",
        len(results),
        "/",
        len(symbols)
    )

    print(
        "📈 Klines OK:",
        len(good)
    )

    print(
        "🔥 Signals:",
        len(signals)
    )

    print(
        "❌ Errors:",
        len(errors)
    )

    print(
        "⏱️ Scan:",
        f"{elapsed:.2f}s"
    )

    # -----------------------------------------------------
    # API ERROR
    # -----------------------------------------------------

    if errors:

        print(
            "⚠️ API errors detected"
        )

        sample = errors[0]

        print(
            "Sample:",
            sample
        )

    # -----------------------------------------------------
    # SIGNALS
    # -----------------------------------------------------

    signals.sort(
        key=lambda x:
        x.get(
            "score",
            0
        ),
        reverse=True,
    )

    if signals:

        # Send up to 5 strongest signals
        top = signals[:5]

        text = (
            "🔥 ATI FUTURES V7.6\n\n"
            "⚡ ICHIMOKU 5M SIGNALS\n\n"
        )

        for i, s in enumerate(
            top,
            1
        ):

            text += (
                f"{i}️⃣ "
                f"{s['symbol']}\n"
                f"📌 {s['signal']}\n"
                f"⭐ Score: "
                f"{s['score']:.1f}\n"
                f"💰 Price: "
                f"{s['price']}\n"
                f"📏 Kijun: "
                f"{s['distance']:.2f}%\n"
                f"☁️ Cloud: "
                f"{s['cloud_bottom']:.6g}"
                f" - "
                f"{s['cloud_top']:.6g}\n"
                f"🔀 TK Cross: "
                f"{'YES' if s['cross'] else 'NO'}\n"
                f"📊 Volume: "
                f"{'OK' if s['volume_ok'] else 'LOW'}\n\n"
            )

        text += (
            f"📊 Markets: {len(symbols)}\n"
            f"⏱️ Scan: {elapsed:.2f}s\n"
            f"🕐 {now()}"
        )

        print()
        print(text)

        telegram(
            text
        )

    else:

        text = f"""💓 ATI FUTURES V7.6

⚡ ICHIMOKU 5M

📊 Markets: {len(symbols)}
📈 Klines OK: {len(good)}
🔥 Signals: 0
❌ Errors: {len(errors)}

⏱️ Scan: {elapsed:.2f}s

☁️ NO SIGNAL THIS CYCLE

🕐 {now()}"""

        print(
            text
        )

        telegram(
            text
        )


if __name__ == "__main__":
    main()
