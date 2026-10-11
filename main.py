import os
import time
import json
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ATI TABDEAL FUTURES MACD
# MACD: 12 / 26 / 9
# Timeframe: 5 minutes
# REAL TRADING: OFF — NO ORDERS

BASE_URL = "https://api1.tabdeal.org"
MARKET_URL = f"{BASE_URL}/r/fapi/v1/exchangeInfo"
KLINES_URL = f"{BASE_URL}/r/fapi/v1/klines"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

MAX_MARKETS = int(os.getenv("MAX_MARKETS", "75"))
KLINES_LIMIT = int(os.getenv("KLINES_LIMIT", "100"))
ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

INTERVAL = "5m"
TIMEOUT = 15
MAX_WORKERS = 8

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-Tabdeal-Futures-MACD/2.0"
})


def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def telegram(message):
    print(message, flush=True)

    if not BOT_TOKEN or not CHAT_ID:
        print(
            "WARNING: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is missing.",
            flush=True
        )
        return

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": message[:4000],
                "disable_web_page_preview": True
            },
            timeout=15
        )
        response.raise_for_status()
        print("Telegram message sent.", flush=True)

    except Exception as exc:
        print(
            f"Telegram error: {type(exc).__name__}: {exc}",
            flush=True
        )


def get_json(url, params=None):
    response = session.get(
        url,
        params=params,
        timeout=TIMEOUT
    )

    print(
        f"HTTP {response.status_code}: {response.url}",
        flush=True
    )

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code} from {response.url}: "
            f"{response.text[:1000]}"
        )

    try:
        return response.json()
    except ValueError:
        raise RuntimeError(
            f"Response was not JSON: {response.text[:1000]}"
        )


def extract_market_rows(data):
    """
    Supports common exchangeInfo response structures.
    Does not assume the response is always a list.
    """
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    for key in (
        "symbols",
        "data",
        "markets",
        "result",
        "contracts",
        "list"
    ):
        value = data.get(key)

        if isinstance(value, list):
            return value

        if isinstance(value, dict):
            for nested_key in (
                "symbols",
                "markets",
                "list",
                "contracts"
            ):
                nested = value.get(nested_key)

                if isinstance(nested, list):
                    return nested

    return []


def discover_markets():
    data = get_json(MARKET_URL)
    rows = extract_market_rows(data)

    print(
        "EXCHANGE INFO RESPONSE TYPE:",
        type(data).__name__,
        flush=True
    )

    print(
        "EXCHANGE INFO TOP LEVEL:",
        list(data.keys()) if isinstance(data, dict) else "not a dict",
        flush=True
    )

    print(
        "EXCHANGE INFO FIRST 3 ROWS:",
        json.dumps(rows[:3], ensure_ascii=False, default=str)[:4000],
        flush=True
    )

    if not rows:
        raise RuntimeError(
            "No market rows could be extracted from exchangeInfo. "
            f"Response: {json.dumps(data, ensure_ascii=False, default=str)[:1500]}"
        )

    markets = []
    rejected_examples = []

    for item in rows:
        if not isinstance(item, dict):
            continue

        # Accept several possible symbol field names.
        symbol = str(
            item.get("symbol")
            or item.get("s")
            or item.get("contractCode")
            or item.get("market")
            or item.get("pair")
            or ""
        ).upper().strip()

        quote = str(
            item.get("quoteAsset")
            or item.get("quote")
            or ""
        ).upper().strip()

        if not symbol:
            base = str(
                item.get("baseAsset")
                or item.get("base")
                or ""
            ).upper().strip()

            if base and quote:
                symbol = base + quote

        # Do not reject a market solely because its status field
        # uses an unfamiliar value.
        if symbol.endswith("USDT") and symbol.isalnum():
            markets.append(symbol)
        elif len(rejected_examples) < 5:
            rejected_examples.append({
                "symbol": symbol,
                "quote": quote,
                "status": item.get("status"),
                "keys": list(item.keys())
            })

    markets = sorted(set(markets))

    print(
        "USDT MARKET CANDIDATES:",
        len(markets),
        markets[:30],
        flush=True
    )

    if not markets:
        raise RuntimeError(
            "ExchangeInfo returned data, but no symbols ending in USDT "
            "were recognized. "
            f"Rejected examples: "
            f"{json.dumps(rejected_examples, ensure_ascii=False, default=str)}"
        )

    return markets[:MAX_MARKETS], len(rows)


def ema(values, period):
    if len(values) < period:
        raise ValueError(
            f"EMA({period}) needs more values; got {len(values)}"
        )

    alpha = 2.0 / (period + 1.0)
    current = sum(values[:period]) / period

    result = [None] * (period - 1)
    result.append(current)

    for value in values[period:]:
        current = alpha * value + (1.0 - alpha) * current
        result.append(current)

    return result


def calculate_macd(closes):
    if len(closes) < 40:
        raise ValueError(
            f"Need at least 40 closed candles; got {len(closes)}"
        )

    fast = ema(closes, 12)
    slow = ema(closes, 26)

    macd_values = []
    macd_indices = []

    for index in range(len(closes)):
        if fast[index] is not None and slow[index] is not None:
            macd_values.append(fast[index] - slow[index])
            macd_indices.append(index)

    signal_values = ema(macd_values, 9)

    valid = []

    for index, macd_value, signal_value in zip(
        macd_indices,
        macd_values,
        signal_values
    ):
        if signal_value is not None:
            valid.append((index, macd_value, signal_value))

    if len(valid) < 2:
        raise ValueError("Not enough MACD values")

    previous = valid[-2]
    current = valid[-1]

    previous_macd, previous_signal = previous[1], previous[2]
    current_macd, current_signal = current[1], current[2]

    direction = None

    if (
        previous_macd <= previous_signal
        and current_macd > current_signal
    ):
        direction = "BUY"

    elif (
        previous_macd >= previous_signal
        and current_macd < current_signal
    ):
        direction = "SELL"

    return {
        "direction": direction,
        "macd": current_macd,
        "signal": current_signal,
        "histogram": current_macd - current_signal
    }


def fetch_closed_candles(symbol):
    data = get_json(
        KLINES_URL,
        params={
            "symbol": symbol,
            "interval": INTERVAL,
            "limit": KLINES_LIMIT
        }
    )

    if isinstance(data, dict):
        found = False

        for key in ("data", "klines", "result", "rows", "list"):
            value = data.get(key)

            if isinstance(value, list):
                data = value
                found = True
                break

        if not found:
            raise ValueError(
                "Unrecognized kline response: "
                + json.dumps(
                    data,
                    ensure_ascii=False,
                    default=str
                )[:700]
            )

    if not isinstance(data, list):
        raise ValueError(
            f"Kline response is {type(data).__name__}, not a list"
        )

    candles = []

    for row in data:
        try:
            if isinstance(row, dict):
                open_time = int(
                    row.get("openTime", row.get("open_time", row.get("t")))
                )
                close_price = float(
                    row.get("close", row.get("c"))
                )
                close_time_value = row.get(
                    "closeTime",
                    row.get("close_time", row.get("T"))
                )

                if close_time_value is None:
                    close_time = open_time + 5 * 60 * 1000
                else:
                    close_time = int(close_time_value)

            elif isinstance(row, (list, tuple)) and len(row) >= 5:
                open_time = int(row[0])
                close_price = float(row[4])

                if len(row) >= 7:
                    close_time = int(row[6])
                else:
                    close_time = open_time + 5 * 60 * 1000

            else:
                continue

            # Normalize seconds to milliseconds if necessary.
            if open_time < 10_000_000_000:
                open_time *= 1000

            if close_time < 10_000_000_000:
                close_time *= 1000

            if close_price > 0:
                candles.append(
                    (open_time, close_time, close_price)
                )

        except (TypeError, ValueError, KeyError):
            continue

    candles.sort(key=lambda candle: candle[0])

    now_ms = int(time.time() * 1000)

    # Exclude the current, unfinished candle.
    closed = [
        candle for candle in candles
        if candle[1] < now_ms
    ]

    if len(closed) < 40:
        raise ValueError(
            f"Only {len(closed)} closed candles received; "
            f"raw response rows={len(data)}"
        )

    return [candle[2] for candle in closed]


def scan_symbol(symbol):
    try:
        closes = fetch_closed_candles(symbol)
        macd = calculate_macd(closes)

        return {
            "symbol": symbol,
            "price": closes[-1],
            "candles": len(closes),
            **macd,
            "error": None
        }

    except Exception as exc:
        return {
            "symbol": symbol,
            "error": f"{type(exc).__name__}: {exc}"
        }


def main():
    started = time.monotonic()

    telegram(
        "🚀 ATI TABDEAL FUTURES MACD\n"
        f"Time: {now_utc()}\n"
        "Strategy: MACD 12/26/9\n"
        "Timeframe: 5m\n"
        "REAL TRADING: OFF\n"
        "Testing Tabdeal Futures market discovery..."
    )

    try:
        markets, total_rows = discover_markets()

    except Exception as exc:
        message = (
            "❌ ATI TABDEAL FUTURES MARKET ERROR\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"Time: {now_utc()}\n"
            "Check GitHub Actions logs for EXCHANGE INFO FIRST 3 ROWS.\n"
            "No orders were placed."
        )

        telegram(message)
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
                    "error": f"{type(exc).__name__}: {exc}"
                }

            if result.get("error"):
                errors.append(result)
            else:
                results.append(result)

    signals = [
        item for item in results
        if item.get("direction") in ("BUY", "SELL")
    ]

    elapsed = time.monotonic() - started

    lines = [
        "💓 ATI TABDEAL FUTURES MACD",
        f"Time: {now_utc()}",
        "",
        "Strategy: MACD 12/26/9",
        "Timeframe: 5m",
        f"Market rows received: {total_rows}",
        f"USDT markets selected: {len(markets)}",
        f"Candles ready: {len(results)}",
        f"Market/candle errors: {len(errors)}",
        f"Scan time: {elapsed:.1f}s",
        "",
        f"Order size setting: {ORDER_USDT} USDT",
        f"Leverage setting: {LEVERAGE}x",
        "REAL TRADING: OFF",
        ""
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
                f"Histogram: {item['histogram']:.10g}"
            ])
    else:
        lines.append("No new MACD crossover on closed candles.")

    if errors:
        lines.extend(["", "First errors:"])

        for item in errors[:5]:
            lines.append(
                f"{item['symbol']}: {item['error'][:200]}"
            )

    lines.extend([
        "",
        "Signal-only mode. No orders were placed."
    ])

    telegram("\n".join(lines))


if __name__ == "__main__":
    main()
