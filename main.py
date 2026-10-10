import os
import time
import requests
from datetime import datetime, timezone

# ATI FUTURES V17
# Data diagnostics + Ichimoku 9/26/52
# REAL TRADING DISABLED until data is verified.

BASES = [
    "https://api1.tabdeal.org",
]

ORDER_USDT = 2.0
LEVERAGE = 3
INTERVAL = "5m"
REAL_TRADING = False

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

session = requests.Session()
session.headers.update({"User-Agent": "ATI-FUTURES-V17/1.0"})


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials are not configured.")
        return

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    try:
        response = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )
        response.raise_for_status()
    except Exception as exc:
        print(f"Telegram error: {exc}")


def get_json(path, params=None):
    errors = []

    for base in BASES:
        for prefix in ("/r/fapi/v1/", "/fapi/v1/"):
            url = base + prefix + path

            try:
                response = session.get(
                    url,
                    params=params or {},
                    timeout=10,
                )

                if response.status_code == 404:
                    errors.append(f"{url}: HTTP 404")
                    continue

                response.raise_for_status()
                data = response.json()

                if isinstance(data, dict) and data.get("code"):
                    errors.append(
                        f"{url}: {data.get('msg', data)}"
                    )
                    continue

                return data, None

            except Exception as exc:
                errors.append(f"{url}: {exc}")

    return None, " || ".join(errors[-4:])


def discover_markets():
    data, error = get_json("exchangeInfo")

    if error:
        raise RuntimeError(
            "Futures exchangeInfo failed: " + error
        )

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = data.get("symbols", [])
    else:
        items = []

    markets = []

    for item in items:
        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol", "")).upper()
        status = str(item.get("status", "")).upper()
        quote = str(item.get("quoteAsset", "")).upper()

        if not symbol.endswith("USDT"):
            continue

        if quote and quote != "USDT":
            continue

        if status and status not in ("TRADING", "ENABLED"):
            continue

        if item.get("contractType"):
            if str(item["contractType"]).upper() not in (
                "PERPETUAL",
                "CURRENT_QUARTER",
                "NEXT_QUARTER",
            ):
                continue

        markets.append(symbol)

    if not markets:
        raise RuntimeError(
            "exchangeInfo returned no eligible USDT futures markets."
        )

    return sorted(set(markets))[:75]


def get_candles(symbol):
    # Try documented-style futures kline endpoint candidates.
    candidates = [
        ("klines", {
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": 100,
        }),
        ("klines", {
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": 100,
        }),
    ]

    errors = []

    for endpoint, params in candidates:
        data, error = get_json(endpoint, params)

        if error:
            errors.append(error)
            continue

        if not isinstance(data, list) or len(data) < 60:
            errors.append(
                f"{endpoint}: invalid or insufficient candle data"
            )
            continue

        candles = []

        try:
            for row in data:
                if isinstance(row, list) and len(row) >= 6:
                    candles.append({
                        "high": float(row[2]),
                        "low": float(row[3]),
                        "close": float(row[4]),
                    })
                elif isinstance(row, dict):
                    candles.append({
                        "high": float(row["high"]),
                        "low": float(row["low"]),
                        "close": float(row["close"]),
                    })

            if len(candles) >= 60:
                return candles, None

        except (ValueError, KeyError, TypeError) as exc:
            errors.append(str(exc))

    return None, " | ".join(errors[-3:])


def ichimoku_signal(candles):
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]

    def midpoint(period, end):
        start = end - period + 1

        if start < 0:
            return None

        return (
            max(highs[start:end + 1])
            + min(lows[start:end + 1])
        ) / 2

    i = len(candles) - 2  # Last closed candle.

    tenkan = midpoint(9, i)
    kijun = midpoint(26, i)

    span_a = (tenkan + kijun) / 2
    span_b = midpoint(52, i)

    price = closes[i]
    previous_tenkan = midpoint(9, i - 1)
    previous_kijun = midpoint(26, i - 1)

    if span_b is None or previous_tenkan is None:
        return None, price

    cloud_top = max(span_a, span_b)
    cloud_bottom = min(span_a, span_b)

    bullish = (
        price > cloud_top
        and tenkan > kijun
        and previous_tenkan <= previous_kijun
    )

    bearish = (
        price < cloud_bottom
        and tenkan < kijun
        and previous_tenkan >= previous_kijun
    )

    if bullish:
        return "BUY", price

    if bearish:
        return "SELL", price

    return None, price


def main():
    started = time.time()

    telegram(
        "🚀 ATI FUTURES V17 started\n"
        f"Time: {now()}\n"
        "REAL TRADING: OFF\n"
        "Mode: Futures data diagnostics + Ichimoku"
    )

    try:
        markets = discover_markets()
    except Exception as exc:
        message = (
            "❌ ATI FUTURES V17 MARKET DISCOVERY ERROR\n\n"
            f"{exc}\n\nTime: {now()}"
        )
        print(message)
        telegram(message)
        return

    ready = 0
    errors = []
    signals = []

    for symbol in markets:
        candles, error = get_candles(symbol)

        if error:
            errors.append((symbol, error))
            continue

        ready += 1

        try:
            signal, price = ichimoku_signal(candles)

            if signal:
                signals.append((symbol, signal, price))

        except Exception as exc:
            errors.append((symbol, str(exc)))

    elapsed = time.time() - started

    lines = [
        "💓 ATI FUTURES V17",
        f"🕐 {now()}",
        f"📊 Markets: {len(markets)}",
        f"📈 5M Ready: {ready}",
        f"🟢 BUY: {sum(1 for x in signals if x[1] == 'BUY')}",
        f"🔴 SELL: {sum(1 for x in signals if x[1] == 'SELL')}",
        f"❌ Errors: {len(errors)}",
        f"⏱️ Scan: {elapsed:.2f}s",
        "",
        f"💵 ORDER: {ORDER_USDT} USDT",
        f"⚡ LEVERAGE: {LEVERAGE}x",
        "🔒 REAL: OFF",
        "",
    ]

    if signals:
        lines.append("📣 ICHIMOKU SIGNALS")
        for symbol, signal, price in signals[:10]:
            emoji = "🟢" if signal == "BUY" else "🔴"
            lines.append(
                f"{emoji} {symbol}: {signal} | Price: {price}"
            )
    else:
        lines.append("☁️ No confirmed Ichimoku signal.")

    if errors:
        lines.extend(["", "🧪 ERROR SAMPLE"])
        for symbol, error in errors[:3]:
            lines.append(f"• {symbol}: {error[:700]}")

    report = "\n".join(lines)
    print(report)
    telegram(report)


if __name__ == "__main__":
    main()
