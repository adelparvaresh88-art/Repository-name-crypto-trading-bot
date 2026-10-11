import os
import time
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ATI TABDEAL FUTURES MACD
# MACD: 12 / 26 / 9
# Timeframe: 5 minutes
# Signal-only mode: NO ORDERS

BASE_URL = "https://api1.tabdeal.org/r/fapi/v1"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

MAX_MARKETS = int(os.getenv("MAX_MARKETS", "75"))
KLINES_LIMIT = int(os.getenv("KLINES_LIMIT", "100"))
ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

INTERVAL = "5m"
TIMEOUT = 12
MAX_WORKERS = 10

session = requests.Session()
session.headers.update({"User-Agent": "ATI-Tabdeal-Futures-MACD/1.0"})


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def telegram(message):
    print(message)

    if not BOT_TOKEN or not CHAT_ID:
        print("WARNING: Telegram secrets are missing.")
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        response.raise_for_status()
        print("Telegram message sent.")
    except Exception as exc:
        print(f"Telegram error: {type(exc).__name__}: {exc}")


def get_json(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def unwrap_market_list(data):
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in ("symbols", "data", "markets", "result"):
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            for nested_key in ("symbols", "markets", "list"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    return nested

    return []


def discover_markets():
    data = get_json(f"{BASE_URL}/exchangeInfo")
    rows = unwrap_market_list(data)

    if not rows:
        raise RuntimeError(
            "ExchangeInfo returned no recognizable market list. "
            f"Response preview: {repr(data)[:700]}"
        )

    eligible = []

    for item in rows:
        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol", "")).upper()
        quote = str(item.get("quoteAsset", "")).upper()
        status = str(item.get("status", "")).upper()
        contract_type = str(item.get("contractType", "")).upper()

        if not symbol.endswith("USDT"):
            continue

        if quote and quote != "USDT":
            continue

        if status and status not in ("TRADING", "ENABLED"):
            continue

        if contract_type and contract_type not in (
            "PERPETUAL",
            "PERPETUAL_CONTRACT",
        ):
            continue

        if symbol.isalnum():
            eligible.append(symbol)

    eligible = sorted(set(eligible))

    if not eligible:
        raise RuntimeError(
            "No eligible USDT futures markets found."
        )

    return eligible[:MAX_MARKETS], len(rows)


def ema(values, period):
    if len(values) < period:
        raise ValueError("Not enough data for EMA")

    alpha = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period
    output = [None] * (period - 1) + [current]

    for value in values[period:]:
        current = value * alpha + current * (1.0 - alpha)
        output.append(current)

    return output


def calculate_macd(closes):
    if len(closes) < 40:
        raise ValueError(
            f"Need at least 40 closes; received {len(closes)}"
        )

    ema12 = ema(closes, 12)
    ema26 = ema(closes, 26)

    macd_values = []
    macd_indices = []

    for index in range(len(closes)):
        if ema12[index] is not None and ema26[index] is not None:
            macd_values.append(ema12[index] - ema26[index])
            macd_indices.append(index)

    signal_values = ema(macd_values, 9)

    valid = []

    for index, macd_value, signal_value in zip(
        macd_indices, macd_values, signal_values
    ):
        if signal_value is not None:
            valid.append((index, macd_value, signal_value))

    if len(valid) < 2:
        raise ValueError("Not enough MACD signal values")

    previous = valid[-2]
    current = valid[-1]

    previous_macd, previous_signal = previous[1], previous[2]
    current_macd, current_signal = current[1], current[2]

    direction = None

    if previous_macd <= previous_signal and current_macd > current_signal:
        direction = "BUY"
    elif previous_macd >= previous_signal and current_macd < current_signal:
        direction = "SELL"

    return {
        "direction": direction,
        "macd": current_macd,
        "signal": current_signal,
        "histogram": current_macd - current_signal,
    }


def fetch_closed_candles(symbol):
    data = get_json(
        f"{BASE_URL}/klines",
        params={
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": KLINES_LIMIT,
        },
    )

    if isinstance(data, dict):
        for key in ("data", "klines", "result", "rows"):
            if isinstance(data.get(key), list):
                data = data[key]
                break

    if not isinstance(data, list):
        raise ValueError(
            f"Unexpected klines response: {type(data).__name__}"
        )

    candles = []

    for row in data:
        if not isinstance(row, (list, tuple)) or len(row) < 7:
            continue

        try:
            open_time = int(row[0])
            close_price = float(row[4])
            close_time = int(row[6])

            if close_price > 0:
                candles.append(
                    (open_time, close_time, close_price)
                )

        except (TypeError, ValueError, IndexError):
            continue

    candles.sort(key=lambda candle: candle[0])

    now_ms = int(time.time() * 1000)

    closed = [
        candle for candle in candles
        if candle[1] < now_ms
    ]

    if len(closed) < 40:
        raise ValueError(
            f"Only {len(closed)} closed candles received"
        )

    return [candle[2] for candle in closed]


def scan_symbol(symbol):
    try:
        closes = fetch_closed_candles(symbol)
        result = calculate_macd(closes)

        return {
            "symbol": symbol,
            "price": closes[-1],
            "candles": len(closes),
            **result,
            "error": None,
        }

    except Exception as exc:
        return {
            "symbol": symbol,
            "error": f"{type(exc).__name__}: {exc}",
        }


def main():
    started = time.monotonic()

    telegram(
        "🚀 ATI TABDEAL FUTURES MACD\n"
        f"Time: {now_utc()}\n"
        "Strategy: MACD 12/26/9\n"
        "Timeframe: 5m\n"
        "Mode: SIGNAL ONLY — NO ORDERS\n"
        "Connecting to Tabdeal Futures..."
    )

    try:
        markets, market_count = discover_markets()

    except Exception as exc:
        telegram(
            "❌ ATI TABDEAL FUTURES MARKET ERROR\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"Time: {now_utc()}\n"
            "No orders were placed."
        )
        raise

    results = []
    errors = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(scan_symbol, symbol): symbol
            for symbol in markets
        }

        for future in as_completed(futures):
            symbol = futures[future]

            try:
                result = future.result()
            except Exception as exc:
                result = {
                    "symbol": symbol,
                    "error": f"{type(exc).__name__}: {exc}",
                }

            if result.get("error"):
                errors.append(result)
            else:
                results.append(result)

    results.sort(key=lambda item: item["symbol"])

    signals = [
        item for item in results
        if item.get("direction") in ("BUY", "SELL")
    ]

    elapsed = time.monotonic() - started

    lines = [
        "💓 ATI TABDEAL FUTURES MACD",
        f"🕐 {now_utc()}",
        "",
        "📊 Strategy: MACD 12/26/9",
        "⏱ Timeframe: 5m",
        f"📚 Markets discovered: {market_count}",
        f"🔎 Markets scanned: {len(markets)}",
        f"✅ Candle data ready: {len(results)}",
        f"❌ Errors: {len(errors)}",
        f"⏱ Scan time: {elapsed:.1f}s",
        "",
        f"💵 Order setting: {ORDER_USDT} USDT",
        f"⚡ Leverage setting: {LEVERAGE}x",
        "🔒 REAL TRADING: OFF",
        "",
    ]

    if signals:
        lines.append("🔥 MACD CROSSOVER SIGNALS")

        for item in signals[:15]:
            icon = "🟢" if item["direction"] == "BUY" else "🔴"

            lines.extend([
                "",
                f"{icon} {item['symbol']} — {item['direction']}",
                f"Price: {item['price']:.10g}",
                f"MACD: {item['macd']:.10g}",
                f"Signal: {item['signal']:.10g}",
                f"Histogram: {item['histogram']:.10g}",
            ])

    else:
        lines.append(
            "☁️ No new MACD crossover on the latest closed candles."
        )

    if errors:
        lines.extend(["", "⚠️ First errors:"])

        for item in errors[:3]:
            lines.append(
                f"{item['symbol']}: {item['error'][:180]}"
            )

    lines.extend([
        "",
        "This version reports signals only.",
        "No orders were placed.",
    ])

    telegram("\n".join(lines))


if __name__ == "__main__":
    main()
