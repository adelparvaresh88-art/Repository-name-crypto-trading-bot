import os
import time
import json
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ATI TABDEAL FUTURES MACD
# MACD: 12 / 26 / 9
# Timeframe: 5 minutes
# LIVE TRADING: OFF
# NO ORDERS WILL BE PLACED

BASE_URL = "https://api1.tabdeal.org/r/fapi/v1"
MARKET_URL = f"{BASE_URL}/exchangeInfo"
KLINES_URL = f"{BASE_URL}/klines"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

MAX_MARKETS = int(os.getenv("MAX_MARKETS", "75"))
KLINES_LIMIT = int(os.getenv("KLINES_LIMIT", "100"))
ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

TIMEOUT = 15
MAX_WORKERS = 8
INTERVAL = "5m"

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-Tabdeal-Futures-MACD/3.0"
})


def now_utc():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def telegram(message):
    print(message, flush=True)

    if not BOT_TOKEN or not CHAT_ID:
        print(
            "WARNING: Telegram secrets are missing.",
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
            f"TELEGRAM ERROR: {type(exc).__name__}: {exc}",
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
            f"HTTP {response.status_code}; "
            f"URL={response.url}; "
            f"BODY={response.text[:1000]}"
        )

    try:
        return response.json()
    except ValueError:
        raise RuntimeError(
            f"API did not return JSON: {response.text[:1000]}"
        )


def extract_market_rows(data):
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
                "contracts",
                "list"
            ):
                nested = value.get(nested_key)

                if isinstance(nested, list):
                    return nested

    return []


def normalize_symbol(raw_symbol):
    """
    BTC_USDT -> BTCUSDT
    BTC-USDT -> BTCUSDT
    BTCUSDT   -> BTCUSDT
    """
    return (
        str(raw_symbol)
        .upper()
        .strip()
        .replace("_", "")
        .replace("-", "")
        .replace("/", "")
        .replace(" ", "")
    )


def discover_markets():
    data = get_json(MARKET_URL)
    rows = extract_market_rows(data)

    print(
        "EXCHANGE INFO TYPE:",
        type(data).__name__,
        flush=True
    )

    print(
        "EXCHANGE INFO KEYS:",
        list(data.keys()) if isinstance(data, dict) else "not a dict",
        flush=True
    )

    print(
        "EXCHANGE INFO FIRST 3 ROWS:",
        json.dumps(
            rows[:3],
            ensure_ascii=False,
            default=str
        )[:3000],
        flush=True
    )

    if not rows:
        raise RuntimeError(
            "ExchangeInfo returned no recognizable market rows. "
            f"Response={json.dumps(data, ensure_ascii=False, default=str)[:1500]}"
        )

    markets = []
    raw_by_normalized = {}
    rejected = []

    for item in rows:
        if not isinstance(item, dict):
            continue

        raw_symbol = str(
            item.get("symbol")
            or item.get("s")
            or item.get("contractCode")
            or item.get("market")
            or item.get("pair")
            or ""
        ).strip()

        quote = str(
            item.get("quoteAsset")
            or item.get("quote")
            or ""
        ).upper().strip()

        status = str(
            item.get("status") or ""
        ).upper().strip()

        if status and status not in (
            "TRADING",
            "ENABLED",
            "ACTIVE"
        ):
            continue

        normalized = normalize_symbol(raw_symbol)

        # Accept BTC_USDT after normalizing the underscore.
        if not normalized.endswith("USDT"):
            if len(rejected) < 5:
                rejected.append(raw_symbol)
            continue

        if not normalized.isalnum():
            continue

        if quote and quote != "USDT":
            continue

        markets.append(normalized)

        # Preserve original exchange symbol as an alternate
        # in case the candle endpoint expects an underscore.
        raw_by_normalized[normalized] = raw_symbol

    markets = sorted(set(markets))

    print(
        "USDT MARKETS FOUND:",
        len(markets),
        markets[:30],
        flush=True
    )

    print(
        "REJECTED SYMBOL EXAMPLES:",
        rejected,
        flush=True
    )

    if not markets:
        raise RuntimeError(
            "No USDT markets found after symbol normalization. "
            f"First rows={json.dumps(rows[:5], ensure_ascii=False, default=str)[:1500]}"
        )

    return markets[:MAX_MARKETS], len(rows), raw_by_normalized


def ema(values, period):
    if len(values) < period:
        raise ValueError(
            f"EMA({period}) needs {period} values; got {len(values)}"
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

    fast_ema = ema(closes, 12)
    slow_ema = ema(closes, 26)

    macd_values = []
    macd_indices = []

    for index in range(len(closes)):
        if (
            fast_ema[index] is not None
            and slow_ema[index] is not None
        ):
            macd_values.append(
                fast_ema[index] - slow_ema[index]
            )
            macd_indices.append(index)

    signal_values = ema(macd_values, 9)
    valid = []

    for index, macd_value, signal_value in zip(
        macd_indices,
        macd_values,
        signal_values
    ):
        if signal_value is not None:
            valid.append(
                (index, macd_value, signal_value)
            )

    if len(valid) < 2:
        raise ValueError("Not enough valid MACD signal values")

    previous = valid[-2]
    current = valid[-1]

    previous_macd = previous[1]
    previous_signal = previous[2]
    current_macd = current[1]
    current_signal = current[2]

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


def parse_candle_rows(data):
    if isinstance(data, dict):
        for key in (
            "data",
            "klines",
            "result",
            "rows",
            "list"
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

        raise ValueError(
            "Unrecognized candle JSON: "
            + json.dumps(
                data,
                ensure_ascii=False,
                default=str
            )[:1000]
        )

    if isinstance(data, list):
        return data

    raise ValueError(
        f"Unexpected candle response type: {type(data).__name__}"
    )


def fetch_closed_candles(symbol, raw_symbol=None):
    symbols_to_try = [symbol]

    if raw_symbol and raw_symbol != symbol:
        symbols_to_try.append(raw_symbol)

    last_error = None

    for candidate in symbols_to_try:
        try:
            data = get_json(
                KLINES_URL,
                params={
                    "symbol": candidate,
                    "interval": INTERVAL,
                    "limit": KLINES_LIMIT
                }
            )

            rows = parse_candle_rows(data)
            candles = []

            for row in rows:
                try:
                    if isinstance(row, dict):
                        open_time = int(
                            row.get(
                                "openTime",
                                row.get("open_time", row.get("t"))
                            )
                        )

                        close_price = float(
                            row.get("close", row.get("c"))
                        )

                        close_time_value = row.get(
                            "closeTime",
                            row.get("close_time", row.get("T"))
                        )

                        if close_time_value is None:
                            close_time = (
                                open_time + 5 * 60 * 1000
                            )
                        else:
                            close_time = int(close_time_value)

                    elif (
                        isinstance(row, (list, tuple))
                        and len(row) >= 5
                    ):
                        open_time = int(row[0])
                        close_price = float(row[4])

                        if len(row) >= 7:
                            close_time = int(row[6])
                        else:
                            close_time = (
                                open_time + 5 * 60 * 1000
                            )
                    else:
                        continue

                    if open_time < 10_000_000_000:
                        open_time *= 1000

                    if close_time < 10_000_000_000:
                        close_time *= 1000

                    if close_price > 0:
                        candles.append(
                            (
                                open_time,
                                close_time,
                                close_price
                            )
                        )

                except (
                    TypeError,
                    ValueError,
                    KeyError,
                    IndexError
                ):
                    continue

            candles.sort(key=lambda candle: candle[0])

            now_ms = int(time.time() * 1000)

            closed = [
                candle for candle in candles
                if candle[1] < now_ms
            ]

            if len(closed) < 40:
                raise ValueError(
                    f"{candidate}: only {len(closed)} closed candles; "
                    f"raw rows={len(rows)}"
                )

            return [candle[2] for candle in closed]

        except Exception as exc:
            last_error = exc

    raise RuntimeError(
        f"Could not fetch 5m candles for {symbol}. "
        f"Last error: {type(last_error).__name__}: {last_error}"
    )


def scan_symbol(symbol, raw_symbol=None):
    try:
        closes = fetch_closed_candles(
            symbol,
            raw_symbol
        )

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
        "MACD: 12 / 26 / 9\n"
        "Timeframe: 5m\n"
        "REAL TRADING: OFF\n"
        "Checking futures markets..."
    )

    try:
        markets, total_rows, raw_symbols = discover_markets()

    except Exception as exc:
        telegram(
            "❌ ATI TABDEAL MARKET ERROR\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"Time: {now_utc()}\n"
            "No orders were placed."
        )
        raise

    results = []
    errors = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                scan_symbol,
                symbol,
                raw_symbols.get(symbol)
            ): symbol
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
        f"Market rows: {total_rows}",
        f"Markets selected: {len(markets)}",
        f"Candles ready: {len(results)}",
        f"Errors: {len(errors)}",
        f"Scan time: {elapsed:.1f}s",
        "",
        f"Order setting: {ORDER_USDT} USDT",
        f"Leverage setting: {LEVERAGE}x",
        "REAL TRADING: OFF",
        ""
    ]

    if signals:
        lines.append("🔥 MACD CROSSOVER SIGNALS")

        for item in signals[:15]:
            icon = (
                "🟢"
                if item["direction"] == "BUY"
                else "🔴"
            )

            lines.extend([
                "",
                f"{icon} {item['symbol']} — {item['direction']}",
                f"Price: {item['price']:.10g}",
                f"MACD: {item['macd']:.10g}",
                f"Signal: {item['signal']:.10g}",
                f"Histogram: {item['histogram']:.10g}"
            ])

    else:
        lines.append(
            "No new MACD crossover on the latest closed candles."
        )

    if errors:
        lines.extend([
            "",
            "⚠️ First errors:"
        ])

        for item in errors[:5]:
            lines.append(
                f"{item['symbol']}: {item['error'][:220]}"
            )

    lines.extend([
        "",
        "Signal-only mode. No orders were placed."
    ])

    telegram("\n".join(lines))


if __name__ == "__main__":
    main()
