import os
import json
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone

import requests
import websocket

# ==========================================
# ATI FUTURES V22.2
# Trades -> 5M candles -> MACD
# REAL TRADING: OFF
# ==========================================

VERSION = "ATI FUTURES V22.2"
BASE_URL = "https://api1.tabdeal.org"
WS_URL = "wss://api1.tabdeal.org/special_margin/stream/"

INTERVAL_MS = 5 * 60 * 1000
MAX_CANDLES = 200
MAX_MARKETS = 75
REPORT_SECONDS = 60

# This version NEVER submits orders.
REAL_TRADING = False

lock = threading.Lock()
candles = defaultdict(lambda: deque(maxlen=MAX_CANDLES))
current_candles = {}
last_trade_time = {}
connected_markets = set()
ever_connected_markets = set()

stats = {
    "raw": 0,
    "parsed": 0,
    "errors": 0,
    "signals": 0,
}

last_signal_candle = {}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def get_json(path, timeout=15):
    url = BASE_URL + path
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()


def discover_markets():
    """
    Discover USDT futures markets using the documented Futures API.
    If the exchange returns an unexpected format, stop instead of
    silently scanning the wrong market list.
    """
    data = get_json("/r/fapi/v1/exchangeInfo")

    if isinstance(data, dict):
        items = data.get("symbols", [])
    elif isinstance(data, list):
        items = data
    else:
        raise RuntimeError(
            "Unexpected exchangeInfo format: "
            + type(data).__name__
        )

    result = []

    for item in items:
        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol", "")).upper()
        status = str(item.get("status", "")).upper()
        quote = str(item.get("quoteAsset", "")).upper()
        contract = str(item.get("contractType", "")).upper()

        if not symbol.endswith("USDT"):
            continue

        if status and status not in ("TRADING", "ENABLED"):
            continue

        if quote and quote != "USDT":
            continue

        if contract and contract not in (
            "PERPETUAL", "CURRENT_QUARTER",
            "NEXT_QUARTER"
        ):
            continue

        result.append(symbol)

    result = sorted(set(result))

    if not result:
        raise RuntimeError(
            "No eligible USDT futures markets found. "
            "Check the Futures endpoint and response format."
        )

    return result[:MAX_MARKETS]


def parse_trade(message):
    """
    Accept common exchange trade formats.
    Returns (symbol, timestamp_ms, price, quantity).
    """
    if not isinstance(message, dict):
        return None

    data = message.get("data", message)

    if not isinstance(data, dict):
        return None

    symbol = (
        data.get("s")
        or data.get("symbol")
        or message.get("symbol")
    )

    price = data.get("p", data.get("price"))
    qty = data.get("q", data.get("qty", data.get("quantity")))
    timestamp = data.get(
        "T",
        data.get("E", data.get("time", data.get("timestamp")))
    )

    if not symbol or price is None or qty is None or timestamp is None:
        return None

    try:
        timestamp = int(timestamp)
        price = float(price)
        qty = float(qty)

        # Convert seconds to milliseconds when necessary.
        if timestamp < 10_000_000_000:
            timestamp *= 1000

        if price <= 0 or qty < 0:
            return None

        return str(symbol).upper(), timestamp, price, qty

    except (ValueError, TypeError):
        return None


def finalize_candle(symbol, candle):
    row = {
        "time": candle["time"],
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["volume"],
    }

    history = candles[symbol]

    if history and history[-1]["time"] == row["time"]:
        history[-1] = row
    elif not history or row["time"] > history[-1]["time"]:
        history.append(row)

    print(
        f"CANDLE CLOSED {symbol} "
        f"{datetime.fromtimestamp(row['time']/1000, timezone.utc)} "
        f"O={row['open']} H={row['high']} "
        f"L={row['low']} C={row['close']} "
        f"V={row['volume']}"
    )


def process_trade(trade):
    symbol, timestamp, price, qty = trade
    bucket = (timestamp // INTERVAL_MS) * INTERVAL_MS

    with lock:
        stats["parsed"] += 1
        last_trade_time[symbol] = timestamp

        old = current_candles.get(symbol)

        if old is None:
            current_candles[symbol] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }
            return

        if bucket < old["time"]:
            # Ignore late/out-of-order trades.
            return

        if bucket == old["time"]:
            old["high"] = max(old["high"], price)
            old["low"] = min(old["low"], price)
            old["close"] = price
            old["volume"] += qty
            return

        # A later trade means the previous candle period ended.
        finalize_candle(symbol, old)

        # Fill missing intervals with no-trade candles.
        # OHLC remains the last known close; volume is zero.
        next_bucket = old["time"] + INTERVAL_MS
        last_close = old["close"]

        while next_bucket < bucket:
            empty = {
                "time": next_bucket,
                "open": last_close,
                "high": last_close,
                "low": last_close,
                "close": last_close,
                "volume": 0.0,
            }
            finalize_candle(symbol, empty)
            next_bucket += INTERVAL_MS

        current_candles[symbol] = {
            "time": bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": qty,
        }


def ema(values, period):
    if len(values) < period:
        return None

    alpha = 2.0 / (period + 1.0)
    result = sum(values[:period]) / period

    for value in values[period:]:
        result = value * alpha + result * (1.0 - alpha)

    return result


def calculate_macd(closes):
    """
    MACD 12,26,9.
    Requires enough CLOSED candles to produce a meaningful signal.
    """
    if len(closes) < 35:
        return None

    macd_line = []

    for i in range(len(closes)):
        subset = closes[:i + 1]

        fast = ema(subset, 12)
        slow = ema(subset, 26)

        if fast is None or slow is None:
            continue

        macd_line.append(fast - slow)

    if len(macd_line) < 9:
        return None

    signal_line = ema(macd_line, 9)

    if signal_line is None:
        return None

    return macd_line[-1], signal_line


def scan_signals():
    """
    Log MACD crossovers on closed candles only.
    No orders are sent.
    """
    found = []

    with lock:
        symbols = list(candles.keys())

        for symbol in symbols:
            history = list(candles[symbol])

            if len(history) < 35:
                continue

            closes = [row["close"] for row in history]
            result = calculate_macd(closes[:-1])

            if result is None:
                continue

            # Calculate MACD on the complete closed-candle series.
            # Keep crossover check simple and explicit.
            previous = calculate_macd(closes[:-2])
            current = calculate_macd(closes[:-1])

            if previous is None or current is None:
                continue

            prev_macd, prev_signal = previous
            curr_macd, curr_signal = current

            candle_time = history[-2]["time"]

            if last_signal_candle.get(symbol) == candle_time:
                continue

            side = None

            if prev_macd <= prev_signal and curr_macd > curr_signal:
                side = "BUY"
            elif prev_macd >= prev_signal and curr_macd < curr_signal:
                side = "SELL"

            if side:
                last_signal_candle[symbol] = candle_time
                stats["signals"] += 1
                found.append(
                    (symbol, side, closes[-2], curr_macd, curr_signal)
                )

    for symbol, side, price, macd, signal in found:
        print(
            f"MACD SIGNAL {side} {symbol} "
            f"price={price} MACD={macd:.8f} "
            f"SIGNAL={signal:.8f} "
            f"REAL_TRADING={REAL_TRADING}"
        )


def on_message(ws, raw_message):
    try:
        with lock:
            stats["raw"] += 1

        message = json.loads(raw_message)

        # Ignore subscription acknowledgements.
        if isinstance(message, dict) and (
            "result" in message and "id" in message
        ):
            return

        trade = parse_trade(message)

        if trade is None:
            return

        symbol = trade[0]

        with lock:
            connected_markets.add(symbol)
            ever_connected_markets.add(symbol)

        process_trade(trade)

    except Exception as exc:
        with lock:
            stats["errors"] += 1
        print("MESSAGE ERROR:", repr(exc))


def on_error(ws, error):
    with lock:
        stats["errors"] += 1
    print("WEBSOCKET ERROR:", repr(error))


def on_close(ws, code, message):
    print("WEBSOCKET CLOSED:", code, message)


def on_open(ws):
    print("WebSocket connected:", utc_now())

    # Futures market stream names can differ by deployment.
    # The subscription format below must be confirmed against the
    # actual Tabdeal Futures stream implementation.
    params = [
        f"{symbol.lower()}@trade"
        for symbol in MARKETS
    ]

    payload = {
        "method": "SUBSCRIBE",
        "params": params,
        "id": 1,
    }

    ws.send(json.dumps(payload))
    print("Subscription sent for", len(params), "markets")


def reporter():
    while True:
        time.sleep(REPORT_SECONDS)

        with lock:
            market_count = len(MARKETS)
            connected_now = len(connected_markets)
            connected_ever = len(ever_connected_markets)
            raw = stats["raw"]
            parsed = stats["parsed"]
            errors = stats["errors"]
            signal_count = stats["signals"]

            closed = sum(len(v) for v in candles.values())
            ready = sum(
                1 for history in candles.values()
                if len(history) >= 35
            )

            current_count = len(current_candles)

        print("\n" + "=" * 48)
        print(VERSION)
        print("Time:", utc_now())
        print("Markets:", market_count)
        print("Connected now:", connected_now)
        print("Connected at least once:", connected_ever)
        print("Raw messages:", raw)
        print("Parsed trades:", parsed)
        print("Current candles:", current_count)
        print("Closed candles stored:", closed)
        print("MACD-ready markets:", ready)
        print("Signals detected:", signal_count)
        print("WebSocket/message errors:", errors)
        print("REAL TRADING: OFF")
        print("=" * 48 + "\n")

        scan_signals()


def main():
    global MARKETS

    print(VERSION)
    print("=" * 48)
    print("Started:", utc_now())
    print("REAL TRADING:", "ON" if REAL_TRADING else "OFF")
    print("Order endpoint: NEVER CALLED")

    try:
        MARKETS = discover_markets()
    except Exception as exc:
        print("MARKET DISCOVERY FAILED:", repr(exc))
        print(
            "No markets will be guessed. "
            "Check the Futures endpoint and response format."
        )
        return

    print("Markets discovered:", len(MARKETS))
    print("First markets:", ", ".join(MARKETS[:10]))

    threading.Thread(target=reporter, daemon=True).start()

    while True:
        try:
            app = websocket.WebSocketApp(
                WS_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )

            app.run_forever(
                ping_interval=20,
                ping_timeout=10,
            )

        except Exception as exc:
            print("WEBSOCKET LOOP ERROR:", repr(exc))

        print("Reconnecting in 5 seconds...")
        time.sleep(5)


if __name__ == "__main__":
    main()
