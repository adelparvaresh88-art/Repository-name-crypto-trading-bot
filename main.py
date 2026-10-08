import os
import time
import math
import hmac
import hashlib
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# =========================================================
# ATI FUTURES V7.9
# DIRECT FUTURES 5M + ICHIMOKU 9/26/52
# REAL ORDERS OFF
# =========================================================

BASE_URL = "https://api1.tabdeal.org"

# ---------- SETTINGS ----------
TIMEFRAME = "5m"
KLINES_LIMIT = 100

SCAN_UNIVERSE = int(os.getenv("SCAN_UNIVERSE", "75"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "20"))

MIN_SCORE = int(os.getenv("MIN_SCORE", "6"))

LEVERAGE = int(os.getenv("LEVERAGE", "3"))
ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))

REAL_TRADING = os.getenv("REAL_TRADING", "false").lower() == "true"

# Ichimoku
TENKAN = 9
KIJUN = 26
SENKOU_B = 52

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TIMEOUT = 8

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-FUTURES-V7.9",
    "Accept": "application/json",
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram_send(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = (
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        )

        r = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
                "disable_web_page_preview": "true",
            },
            timeout=10,
        )

        return r.ok

    except Exception:
        return False


# =========================================================
# HTTP
# =========================================================

def get_json(path, params=None):
    url = BASE_URL + path

    r = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    if r.status_code != 200:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:180]}"
        )

    data = r.json()

    if isinstance(data, dict):
        if data.get("code") not in (None, 0):
            raise RuntimeError(
                f"API {data.get('code')}: "
                f"{data.get('msg') or data.get('message')}"
            )

    return data


# =========================================================
# FUTURES EXCHANGE INFO
# =========================================================

def get_futures_markets():

    # Official Futures route
    data = get_json("/fapi/v1/exchangeInfo")

    symbols = data.get("symbols", [])

    result = []

    for s in symbols:

        try:
            symbol = s.get("symbol", "")
            status = str(s.get("status", "")).upper()

            quote = str(
                s.get("quoteAsset", "")
            ).upper()

            contract = str(
                s.get("contractType", "")
            ).upper()

            if not symbol:
                continue

            if status not in ("TRADING", "ENABLED"):
                continue

            if quote != "USDT":
                continue

            # Prefer perpetual futures
            if contract and contract not in (
                "PERPETUAL",
                "PERPETUAL_CONTRACT",
            ):
                continue

            result.append(symbol)

        except Exception:
            continue

    # اگر contractType در پاسخ نبود، دوباره فقط USDTها
    if not result:

        for s in symbols:

            symbol = s.get("symbol", "")
            quote = str(
                s.get("quoteAsset", "")
            ).upper()

            if (
                symbol
                and quote == "USDT"
            ):
                result.append(symbol)

    # حذف duplicate
    result = list(dict.fromkeys(result))

    # محدود کردن تعداد
    result = result[:SCAN_UNIVERSE]

    return result


# =========================================================
# DIRECT FUTURES 5M KLINES
# =========================================================

def get_klines(symbol):

    params = {
        "symbol": symbol,
        "interval": TIMEFRAME,
        "limit": KLINES_LIMIT,
    }

    # مسیر رسمی Futures
    data = get_json(
        "/fapi/v1/klines",
        params,
    )

    if not isinstance(data, list):
        raise RuntimeError("Invalid klines response")

    if len(data) < SENKOU_B + 5:
        raise RuntimeError(
            f"Not enough candles: {len(data)}"
        )

    candles = []

    for row in data:

        if not isinstance(row, list):
            continue

        if len(row) < 6:
            continue

        candles.append({
            "time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
        })

    if len(candles) < SENKOU_B + 5:
        raise RuntimeError("Bad candle data")

    candles.sort(
        key=lambda x: x["time"]
    )

    # حذف کندل در حال تشکیل
    now_ms = int(time.time() * 1000)

    candles = [
        c for c in candles
        if c["time"] + 300000 <= now_ms
    ]

    if len(candles) < SENKOU_B + 5:
        raise RuntimeError(
            "Not enough CLOSED 5M candles"
        )

    return candles


# =========================================================
# ICHIMOKU
# =========================================================

def midpoint(candles, end_index, period):

    start = end_index - period + 1

    if start < 0:
        return None

    highs = [
        candles[i]["high"]
        for i in range(start, end_index + 1)
    ]

    lows = [
        candles[i]["low"]
        for i in range(start, end_index + 1)
    ]

    return (
        max(highs) +
        min(lows)
    ) / 2.0


def calculate_ichimoku(candles, i):

    tenkan = midpoint(
        candles,
        i,
        TENKAN,
    )

    kijun = midpoint(
        candles,
        i,
        KIJUN,
    )

    if tenkan is None or kijun is None:
        return None

    span_a = (
        tenkan + kijun
    ) / 2.0

    span_b = midpoint(
        candles,
        i,
        SENKOU_B,
    )

    if span_b is None:
        return None

    return {
        "tenkan": tenkan,
        "kijun": kijun,
        "span_a": span_a,
        "span_b": span_b,
    }


# =========================================================
# SIGNAL ENGINE
# =========================================================

def analyze_symbol(symbol):

    candles = get_klines(symbol)

    # آخرین کندل کاملاً بسته
    i = len(candles) - 1

    c = candles[i]
    prev = candles[i - 1]

    ichi = calculate_ichimoku(
        candles,
        i,
    )

    ichi_prev = calculate_ichimoku(
        candles,
        i - 1,
    )

    if not ichi or not ichi_prev:
        raise RuntimeError(
            "Ichimoku calculation failed"
        )

    close = c["close"]
    prev_close = prev["close"]

    tenkan = ichi["tenkan"]
    kijun = ichi["kijun"]

    cloud_top = max(
        ichi["span_a"],
        ichi["span_b"],
    )

    cloud_bottom = min(
        ichi["span_a"],
        ichi["span_b"],
    )

    score_buy = 0
    score_sell = 0

    buy_reasons = []
    sell_reasons = []

    # -----------------------------------------------------
    # BUY
    # -----------------------------------------------------

    if close > cloud_top:
        score_buy += 2
        buy_reasons.append("PRICE_ABOVE_CLOUD")

    if tenkan > kijun:
        score_buy += 2
        buy_reasons.append("TENKAN_ABOVE_KIJUN")

    if ichi["span_a"] > ichi["span_b"]:
        score_buy += 1
        buy_reasons.append("BULLISH_CLOUD")

    if close > prev_close:
        score_buy += 1
        buy_reasons.append("MOMENTUM_UP")

    if kijun > ichi_prev["kijun"]:
        score_buy += 1
        buy_reasons.append("KIJUN_RISING")

    # -----------------------------------------------------
    # SELL
    # -----------------------------------------------------

    if close < cloud_bottom:
        score_sell += 2
        sell_reasons.append("PRICE_BELOW_CLOUD")

    if tenkan < kijun:
        score_sell += 2
        sell_reasons.append("TENKAN_BELOW_KIJUN")

    if ichi["span_a"] < ichi["span_b"]:
        score_sell += 1
        sell_reasons.append("BEARISH_CLOUD")

    if close < prev_close:
        score_sell += 1
        sell_reasons.append("MOMENTUM_DOWN")

    if kijun < ichi_prev["kijun"]:
        score_sell += 1
        sell_reasons.append("KIJUN_FALLING")

    # -----------------------------------------------------
    # SELECT SIGNAL
    # -----------------------------------------------------

    signal = None
    score = 0
    reasons = []

    if (
        score_buy >= MIN_SCORE
        and score_buy > score_sell
    ):
        signal = "BUY"
        score = score_buy
        reasons = buy_reasons

    elif (
        score_sell >= MIN_SCORE
        and score_sell > score_buy
    ):
        signal = "SELL"
        score = score_sell
        reasons = sell_reasons

    return {
        "symbol": symbol,
        "signal": signal,
        "score": score,
        "close": close,
        "tenkan": tenkan,
        "kijun": kijun,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
        "reasons": reasons,
    }


# =========================================================
# FAST SCAN
# =========================================================

def scan_symbol(symbol):

    try:

        result = analyze_symbol(symbol)

        return {
            "ok": True,
            "symbol": symbol,
            "result": result,
            "error": None,
        }

    except Exception as e:

        return {
            "ok": False,
            "symbol": symbol,
            "result": None,
            "error": str(e)[:160],
        }


# =========================================================
# FORMAT SIGNAL
# =========================================================

def format_signal(x):

    direction = x["signal"]

    emoji = "🟢" if direction == "BUY" else "🔴"

    entry = x["close"]

    # Conservative test levels
    if direction == "BUY":
        sl = entry * 0.99
        tp = entry * 1.02
    else:
        sl = entry * 1.01
        tp = entry * 0.98

    return (
        f"{emoji} ATI FUTURES SIGNAL\n\n"
        f"⚡ {direction}\n"
        f"💎 {x['symbol']}\n"
        f"💰 Entry: {entry:.10g}\n"
        f"🛑 SL: {sl:.10g}\n"
        f"🎯 TP: {tp:.10g}\n\n"
        f"☁️ Ichimoku 9/26/52\n"
        f"Score: {x['score']}\n\n"
        f"📋 " + ", ".join(x["reasons"]) + "\n\n"
        f"🔒 REAL ORDERS: OFF"
    )


# =========================================================
# MAIN
# =========================================================

def main():

    started = time.time()

    try:

        markets = get_futures_markets()

    except Exception as e:

        msg = (
            "❌ ATI FUTURES V7.9 ERROR\n\n"
            "Futures exchangeInfo failed.\n\n"
            f"{str(e)[:500]}"
        )

        print(msg)
        telegram_send(msg)
        return

    if not markets:

        msg = (
            "❌ ATI FUTURES V7.9\n\n"
            "هیچ بازار Futures USDT پیدا نشد."
        )

        print(msg)
        telegram_send(msg)
        return

    print(
        f"💓 ATI FUTURES V7.9\n"
        f"⚡ DIRECT FUTURES 5M\n"
        f"☁️ ICHIMOKU 9 / 26 / 52\n"
        f"📊 Markets: {len(markets)}"
    )

    ok_count = 0
    errors = 0
    signals = []

    error_examples = []

    # اسکن موازی
    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = [
            executor.submit(
                scan_symbol,
                symbol
            )
            for symbol in markets
        ]

        for future in as_completed(futures):

            result = future.result()

            if result["ok"]:

                ok_count += 1

                data = result["result"]

                if data["signal"]:
                    signals.append(data)

            else:

                errors += 1

                if len(error_examples) < 5:
                    error_examples.append(
                        f"{result['symbol']}: "
                        f"{result['error']}"
                    )

    elapsed = time.time() - started

    # مرتب‌سازی سیگنال‌ها
    signals.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    print()
    print("━━━━━━━━━━━━━━━━━━━━")
    print("📊 ATI FUTURES V7.9")
    print("━━━━━━━━━━━━━━━━━━━━")
    print(f"📊 Markets: {len(markets)}")
    print(f"📈 5M OK: {ok_count}")
    print(f"🔥 Signals: {len(signals)}")
    print(f"❌ Errors: {errors}")
    print(f"⏱️ Scan: {elapsed:.2f}s")
    print("━━━━━━━━━━━━━━━━━━━━")

    # -----------------------------------------------------
    # TELEGRAM SUMMARY
    # -----------------------------------------------------

    text = (
        "💓 ATI FUTURES V7.9\n\n"
        "⚡ DIRECT FUTURES → 5M\n"
        "☁️ ICHIMOKU 9 / 26 / 52\n\n"
        f"📊 Markets: {len(markets)}\n"
        f"📈 5M OK: {ok_count}\n"
        f"🔥 Signals: {len(signals)}\n"
        f"❌ Errors: {errors}\n"
        f"⏱️ Scan: {elapsed:.2f}s\n\n"
    )

    # -----------------------------------------------------
    # ERROR DIAGNOSTIC
    # -----------------------------------------------------

    if error_examples:

        text += "🧪 ERROR SAMPLE:\n"

        for e in error_examples:
            text += f"• {e}\n"

        text += "\n"

    # -----------------------------------------------------
    # SIGNALS
    # -----------------------------------------------------

    if signals:

        text += "🔥 TOP FUTURES SIGNALS\n\n"

        for x in signals[:5]:

            text += (
                f"{'🟢' if x['signal']=='BUY' else '🔴'} "
                f"{x['signal']} "
                f"{x['symbol']} "
                f"Score={x['score']}\n"
                f"💰 {x['close']:.10g}\n"
                f"☁️ "
                f"{', '.join(x['reasons'])}\n\n"
            )

    else:

        text += (
            "☁️ NO SIGNAL THIS CYCLE\n\n"
            "Ichimoku conditions not confirmed."
        )

    text += (
        "\n\n"
        "🔒 REAL ORDERS: OFF\n"
        "🕐 "
        + datetime.now(
            timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S UTC")
    )

    print(text)

    telegram_send(text)


if __name__ == "__main__":
    main()
