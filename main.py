import os
import time
import requests

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ==========================================
# ATI FUTURES V18 - DATA ENGINE
# Public Binance USD-M Futures market data
# Ichimoku 9/26/52
# NO REAL ORDERS
# ==========================================

BASE_URL = "https://fapi.binance.com"

INTERVAL = "5m"
SCAN_LIMIT = 75
CANDLE_LIMIT = 100
WORKERS = 12

ORDER_USDT = 2.0
LEVERAGE = 3
REAL_TRADING = False

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-FUTURES-V18/1.0"
})


def now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are not configured.")
        return

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_TOKEN}/sendMessage"
    )

    try:
        requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=15
        ).raise_for_status()
    except Exception as exc:
        print(f"Telegram error: {exc}")


def api_get(path, params=None):
    response = session.get(
        BASE_URL + path,
        params=params or {},
        timeout=15
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict) and "code" in data:
        raise RuntimeError(
            f"API error {data.get('code')}: "
            f"{data.get('msg', '')}"
        )

    return data


def discover_markets():
    info = api_get("/fapi/v1/exchangeInfo")
    tickers = api_get("/fapi/v1/ticker/24hr")

    if not isinstance(info, dict):
        raise RuntimeError("Invalid exchangeInfo response")

    if not isinstance(tickers, list):
        raise RuntimeError("Invalid ticker response")

    eligible = set()

    for item in info.get("symbols", []):
        if item.get("status") != "TRADING":
            continue

        if item.get("quoteAsset") != "USDT":
            continue

        if item.get("contractType") != "PERPETUAL":
            continue

        symbol = item.get("symbol", "")

        if symbol.endswith("USDT"):
            eligible.add(symbol)

    ranked = []

    for item in tickers:
        symbol = item.get("symbol", "")

        if symbol not in eligible:
            continue

        try:
            volume = float(item.get("quoteVolume", 0))
        except (TypeError, ValueError):
            continue

        ranked.append((symbol, volume))

    ranked.sort(key=lambda item: item[1], reverse=True)

    markets = [symbol for symbol, _ in ranked[:SCAN_LIMIT]]

    if not markets:
        raise RuntimeError(
            "No eligible USDT perpetual markets found"
        )

    return markets


def get_candles(symbol):
    data = api_get(
        "/fapi/v1/klines",
        {
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": CANDLE_LIMIT
        }
    )

    if not isinstance(data, list) or len(data) < 60:
        raise RuntimeError(
            f"Insufficient candle data: {len(data) if isinstance(data, list) else 0}"
        )

    candles = []

    for row in data:
        candles.append({
            "open_time": int(row[0]),
            "open": float(row[1]),
            "high": float(row[2]),
            "low": float(row[3]),
            "close": float(row[4]),
            "volume": float(row[5]),
            "close_time": int(row[6])
        })

    # Do not analyze the currently forming candle.
    current_ms = int(time.time() * 1000)

    candles = [
        candle for candle in candles
        if candle["close_time"] < current_ms
    ]

    if len(candles) < 60:
        raise RuntimeError("Not enough closed candles")

    return candles


def midpoint(candles, period, index):
    start = index - period + 1

    if start < 0:
        return None

    window = candles[start:index + 1]

    highest = max(c["high"] for c in window)
    lowest = min(c["low"] for c in window)

    return (highest + lowest) / 2.0


def ichimoku_signal(candles):
    # Last closed candle
    i = len(candles) - 1

    price = candles[i]["close"]

    tenkan = midpoint(candles, 9, i)
    kijun = midpoint(candles, 26, i)

    previous_tenkan = midpoint(candles, 9, i - 1)
    previous_kijun = midpoint(candles, 26, i - 1)

    # Ichimoku cloud values aligned to the current candle.
    cloud_index = i - 26

    span_a_index = cloud_index
    span_b_index = cloud_index

    tenkan_cloud = midpoint(candles, 9, span_a_index)
    kijun_cloud = midpoint(candles, 26, span_a_index)
    span_b = midpoint(candles, 52, span_b_index)

    if any(value is None for value in (
        tenkan,
        kijun,
        previous_tenkan,
        previous_kijun,
        tenkan_cloud,
        kijun_cloud,
        span_b
    )):
        return None, price

    span_a = (tenkan_cloud + kijun_cloud) / 2.0

    cloud_top = max(span_a, span_b)
    cloud_bottom = min(span_a, span_b)

    bullish_cross = (
        tenkan > kijun
        and previous_tenkan <= previous_kijun
    )

    bearish_cross = (
        tenkan < kijun
        and previous_tenkan >= previous_kijun
    )

    if price > cloud_top and bullish_cross:
        return "BUY", price

    if price < cloud_bottom and bearish_cross:
        return "SELL", price

    return None, price


def scan_symbol(symbol):
    try:
        candles = get_candles(symbol)
        signal, price = ichimoku_signal(candles)

        return {
            "symbol": symbol,
            "ready": True,
            "signal": signal,
            "price": price,
            "error": None
        }

    except Exception as exc:
        return {
            "symbol": symbol,
            "ready": False,
            "signal": None,
            "price": None,
            "error": str(exc)
        }


def main():
    started = time.time()

    telegram(
        "🚀 ATI FUTURES V18 STARTED\n"
        f"Time: {now()}\n"
        "Data: Binance USD-M Futures\n"
        "Strategy: Ichimoku 9/26/52\n"
        "Timeframe: 5m\n"
        "REAL TRADING: OFF"
    )

    try:
        markets = discover_markets()

    except Exception as exc:
        message = (
            "❌ ATI V18 MARKET DISCOVERY ERROR\n\n"
            f"{str(exc)[:2500]}\n"
            f"Time: {now()}"
        )
        print(message)
        telegram(message)
        return

    results = []

    with ThreadPoolExecutor(max_workers=WORKERS) as executor:
        futures = {
            executor.submit(scan_symbol, symbol): symbol
            for symbol in markets
        }

        for future in as_completed(futures):
            results.append(future.result())

    results.sort(key=lambda item: item["symbol"])

    ready = sum(1 for r in results if r["ready"])
    errors = [r for r in results if not r["ready"]]

    buys = [
        r for r in results
        if r["signal"] == "BUY"
    ]

    sells = [
        r for r in results
        if r["signal"] == "SELL"
    ]

    elapsed = time.time() - started

    lines = [
        "💓 ATI FUTURES V18",
        f"🕐 {now()}",
        "",
        "📡 DATA: BINANCE USD-M FUTURES",
        "☁️ STRATEGY: ICHIMOKU 9/26/52",
        "",
        f"📊 Markets: {len(markets)}",
        f"📈 5M Ready: {ready}",
        f"🟢 BUY: {len(buys)}",
        f"🔴 SELL: {len(sells)}",
        f"❌ Errors: {len(errors)}",
        f"⏱️ Scan: {elapsed:.2f}s",
        "",
        f"💵 ORDER SETTING: {ORDER_USDT} USDT",
        f"⚡ LEVERAGE SETTING: {LEVERAGE}x",
        "🔒 REAL TRADING: OFF",
        "",
        "⚠️ Signals are analysis only.",
        "No orders are submitted to Tabdeal."
    ]

    if buys:
        lines.extend(["", "🟢 BUY SIGNALS"])

        for r in buys[:10]:
            lines.append(
                f"{r['symbol']} | "
                f"Price: {r['price']:.8g}"
            )

    if sells:
        lines.extend(["", "🔴 SELL SIGNALS"])

        for r in sells[:10]:
            lines.append(
                f"{r['symbol']} | "
                f"Price: {r['price']:.8g}"
            )

    if not buys and not sells:
        lines.extend([
            "",
            "☁️ No confirmed Ichimoku crossover."
        ])

    if errors:
        lines.extend(["", "🧪 ERROR SAMPLE"])

        for r in errors[:5]:
            lines.append(
                f"• {r['symbol']}: {r['error'][:350]}"
            )

    report = "\n".join(lines)

    print(report)
    telegram(report)


if __name__ == "__main__":
    main()
