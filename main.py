import os
import json
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone

import requests
import websocket


# ============================================================
# ATI FUTURES V22.3
# TABDEAL FUTURES
#
# TRADE STREAM -> 5M CANDLES -> MACD 12/26/9
#
# REAL TRADING: OFF
# NO ORDER ENDPOINT IS CALLED
# ============================================================

VERSION = "ATI FUTURES V22.3"

BASE_URL = "https://api1.tabdeal.org"
WS_URL = "wss://api1.tabdeal.org/special_margin/stream/"

INTERVAL_MS = 5 * 60 * 1000
MAX_CANDLES = 200
MAX_MARKETS = 75

REPORT_SECONDS = 60
RECONNECT_SECONDS = 5

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ------------------------------------------------------------
# SAFETY
# ------------------------------------------------------------

REAL_TRADING = False

# This version NEVER sends an order.
# No order endpoint exists anywhere in this file.

# ------------------------------------------------------------
# GLOBAL STATE
# ------------------------------------------------------------

lock = threading.RLock()

MARKETS = []

candles = defaultdict(lambda: deque(maxlen=MAX_CANDLES))
current_candles = {}

last_trade_time = {}

connected_markets = set()
ever_connected_markets = set()

last_signal_candle = {}

stats = {
    "raw": 0,
    "parsed": 0,
    "errors": 0,
    "signals": 0,
    "subscription_ok": 0,
    "subscription_errors": 0,
}


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def candle_time_text(timestamp_ms):
    return datetime.fromtimestamp(
        timestamp_ms / 1000,
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# HTTP
# ============================================================

def get_json(path, timeout=15):
    url = BASE_URL + path

    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": "ATI-FUTURES-V22.3"
        },
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# MARKET DISCOVERY
# ============================================================

def discover_markets():

    print("Checking Futures exchangeInfo...")

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

    if not isinstance(items, list):

        raise RuntimeError(
            "exchangeInfo symbols is not a list"
        )

    result = []

    for item in items:

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

        contract = str(
            item.get("contractType", "")
        ).upper()

        # ----------------------------------------------------
        # Normalize symbols such as BTC_USDT -> BTCUSDT
        # ----------------------------------------------------

        symbol = symbol.replace("_", "")

        if not symbol.endswith("USDT"):
            continue

        if status and status not in (
            "TRADING",
            "ENABLED",
        ):
            continue

        if quote and quote != "USDT":
            continue

        if contract and contract not in (
            "PERPETUAL",
            "CURRENT_QUARTER",
            "NEXT_QUARTER",
        ):
            continue

        result.append(symbol)

    result = sorted(set(result))

    if not result:

        raise RuntimeError(
            "No eligible USDT futures markets found."
        )

    result = result[:MAX_MARKETS]

    return result


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(message):

    if not isinstance(message, dict):
        return None

    # Typical Tabdeal format:
    #
    # {
    #   "stream": "...",
    #   "data": {...}
    # }

    data = message.get(
        "data",
        message
    )

    if not isinstance(data, dict):
        return None

    symbol = (
        data.get("s")
        or data.get("symbol")
        or message.get("symbol")
    )

    price = (
        data.get("p")
        if data.get("p") is not None
        else data.get("price")
    )

    qty = (
        data.get("q")
        if data.get("q") is not None
        else data.get("qty")
    )

    if qty is None:
        qty = data.get("quantity")

    timestamp = (
        data.get("T")
        if data.get("T") is not None
        else data.get("E")
    )

    if timestamp is None:
        timestamp = data.get("time")

    if timestamp is None:
        timestamp = data.get("timestamp")

    if (
        not symbol
        or price is None
        or qty is None
        or timestamp is None
    ):
        return None

    try:

        symbol = str(symbol).upper().replace("_", "")

        timestamp = int(float(timestamp))
        price = float(price)
        qty = float(qty)

        # Seconds -> milliseconds
        if timestamp < 10_000_000_000:
            timestamp *= 1000

        if price <= 0:
            return None

        if qty < 0:
            return None

        return (
            symbol,
            timestamp,
            price,
            qty,
        )

    except (
        ValueError,
        TypeError,
    ):

        return None


# ============================================================
# CANDLE CREATION
# ============================================================

def save_closed_candle(symbol, candle):

    row = {
        "time": candle["time"],
        "open": candle["open"],
        "high": candle["high"],
        "low": candle["low"],
        "close": candle["close"],
        "volume": candle["volume"],
    }

    history = candles[symbol]

    if history:

        if history[-1]["time"] == row["time"]:

            history[-1] = row

        elif row["time"] > history[-1]["time"]:

            history.append(row)

    else:

        history.append(row)

    print(
        f"CANDLE CLOSED | "
        f"{symbol} | "
        f"{candle_time_text(row['time'])} | "
        f"O={row['open']} "
        f"H={row['high']} "
        f"L={row['low']} "
        f"C={row['close']} "
        f"V={row['volume']}"
    )


def process_trade(trade):

    symbol, timestamp, price, qty = trade

    # Ignore symbols not selected by discovery.
    if MARKETS and symbol not in MARKETS:
        return

    bucket = (
        timestamp // INTERVAL_MS
    ) * INTERVAL_MS

    with lock:

        stats["parsed"] += 1

        last_trade_time[symbol] = timestamp

        old = current_candles.get(symbol)

        # ----------------------------------------------------
        # First trade for this symbol
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Old / late trade
        # ----------------------------------------------------

        if bucket < old["time"]:
            return

        # ----------------------------------------------------
        # Same 5M candle
        # ----------------------------------------------------

        if bucket == old["time"]:

            old["high"] = max(
                old["high"],
                price
            )

            old["low"] = min(
                old["low"],
                price
            )

            old["close"] = price

            old["volume"] += qty

            return

        # ----------------------------------------------------
        # New candle started
        # Previous candle is CLOSED
        # ----------------------------------------------------

        save_closed_candle(
            symbol,
            old
        )

        next_bucket = (
            old["time"]
            + INTERVAL_MS
        )

        last_close = old["close"]

        # ----------------------------------------------------
        # Fill missing candle intervals
        # ----------------------------------------------------

        while next_bucket < bucket:

            empty = {
                "time": next_bucket,
                "open": last_close,
                "high": last_close,
                "low": last_close,
                "close": last_close,
                "volume": 0.0,
            }

            save_closed_candle(
                symbol,
                empty
            )

            next_bucket += INTERVAL_MS

        # ----------------------------------------------------
        # New current candle
        # ----------------------------------------------------

        current_candles[symbol] = {
            "time": bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": qty,
        }


# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    alpha = 2.0 / (
        period + 1.0
    )

    result = sum(
        values[:period]
    ) / period

    for value in values[period:]:

        result = (
            value * alpha
            + result * (1.0 - alpha)
        )

    return result


# ============================================================
# MACD SERIES
# ============================================================

def calculate_macd_series(closes):

    if len(closes) < MACD_SLOW:
        return []

    macd_values = []

    for index in range(
        MACD_SLOW - 1,
        len(closes)
    ):

        subset = closes[
            :index + 1
        ]

        fast = calculate_ema(
            subset,
            MACD_FAST
        )

        slow = calculate_ema(
            subset,
            MACD_SLOW
        )

        if fast is None or slow is None:
            continue

        macd_values.append(
            fast - slow
        )

    return macd_values


def calculate_macd(closes):

    macd_values = calculate_macd_series(
        closes
    )

    if len(macd_values) < MACD_SIGNAL:
        return None

    signal = calculate_ema(
        macd_values,
        MACD_SIGNAL
    )

    if signal is None:
        return None

    macd = macd_values[-1]

    return macd, signal


# ============================================================
# MACD SIGNAL SCANNER
# ============================================================

def scan_signals():

    found = []

    with lock:

        symbols = list(
            candles.keys()
        )

        for symbol in symbols:

            history = list(
                candles[symbol]
            )

            # Need enough CLOSED candles.
            if len(history) < 40:
                continue

            # ------------------------------------------------
            # IMPORTANT:
            #
            # history[-1] is the latest CLOSED candle.
            #
            # We compare:
            # candle N-1
            # candle N
            #
            # No current/open candle is used.
            # ------------------------------------------------

            closed = history

            closes = [
                row["close"]
                for row in closed
            ]

            if len(closes) < 40:
                continue

            previous = calculate_macd(
                closes[:-1]
            )

            current = calculate_macd(
                closes
            )

            if (
                previous is None
                or current is None
            ):
                continue

            prev_macd, prev_signal = previous
            curr_macd, curr_signal = current

            candle_time = closed[-1]["time"]

            if (
                last_signal_candle.get(symbol)
                == candle_time
            ):
                continue

            side = None

            # BUY crossover
            if (
                prev_macd <= prev_signal
                and curr_macd > curr_signal
            ):

                side = "BUY"

            # SELL crossover
            elif (
                prev_macd >= prev_signal
                and curr_macd < curr_signal
            ):

                side = "SELL"

            if side:

                last_signal_candle[
                    symbol
                ] = candle_time

                stats["signals"] += 1

                found.append(
                    (
                        symbol,
                        side,
                        closed[-1]["close"],
                        curr_macd,
                        curr_signal,
                        candle_time,
                    )
                )

    # --------------------------------------------------------
    # Print outside lock
    # --------------------------------------------------------

    for (
        symbol,
        side,
        price,
        macd,
        signal,
        candle_time,
    ) in found:

        print(
            "\n"
            "========================================\n"
            f"🔥 MACD SIGNAL {side}\n"
            f"💎 {symbol}\n"
            f"💰 PRICE: {price}\n"
            f"📊 MACD: {macd:.8f}\n"
            f"📈 SIGNAL: {signal:.8f}\n"
            f"🕐 CANDLE: "
            f"{candle_time_text(candle_time)}\n"
            f"🔒 REAL TRADING: OFF\n"
            "========================================"
        )


# ============================================================
# WEBSOCKET MESSAGE
# ============================================================

def on_message(ws, raw_message):

    try:

        with lock:
            stats["raw"] += 1

        message = json.loads(
            raw_message
        )

        if not isinstance(message, dict):
            return

        # ----------------------------------------------------
        # Subscription response
        #
        # Expected:
        # {"result": null, "id": 1}
        # ----------------------------------------------------

        if (
            "result" in message
            and "id" in message
        ):

            if message.get("result") is None:

                with lock:
                    stats[
                        "subscription_ok"
                    ] += 1

                print(
                    "SUBSCRIPTION ACK:",
                    message
                )

            else:

                with lock:
                    stats[
                        "subscription_errors"
                    ] += 1

                print(
                    "SUBSCRIPTION ERROR:",
                    message
                )

            return

        # ----------------------------------------------------
        # Try parsing trade
        # ----------------------------------------------------

        trade = parse_trade(
            message
        )

        if trade is None:

            # Print first few unknown messages
            # to help diagnose the actual Tabdeal format.

            raw_count = stats["raw"]

            if raw_count <= 10:

                print(
                    "UNPARSED MESSAGE:",
                    json.dumps(
                        message,
                        ensure_ascii=False
                    )[:1000]
                )

            return

        symbol = trade[0]

        with lock:

            connected_markets.add(
                symbol
            )

            ever_connected_markets.add(
                symbol
            )

        process_trade(trade)

    except Exception as exc:

        with lock:
            stats["errors"] += 1

        print(
            "MESSAGE ERROR:",
            repr(exc)
        )


# ============================================================
# WEBSOCKET ERROR
# ============================================================

def on_error(ws, error):

    with lock:
        stats["errors"] += 1

    print(
        "WEBSOCKET ERROR:",
        repr(error)
    )


# ============================================================
# WEBSOCKET CLOSE
# ============================================================

def on_close(
    ws,
    close_status_code,
    close_msg
):

    print(
        "WEBSOCKET CLOSED:",
        close_status_code,
        close_msg
    )


# ============================================================
# WEBSOCKET OPEN
# ============================================================

def on_open(ws):

    print(
        "\n"
        "========================================"
    )

    print(
        "WEBSOCKET CONNECTED"
    )

    print(
        "Time:",
        utc_now()
    )

    print(
        "Markets:",
        len(MARKETS)
    )

    print(
        "========================================"
    )

    # --------------------------------------------------------
    # Official Tabdeal-style subscription
    #
    # symbol@trade
    # --------------------------------------------------------

    params = []

    for symbol in MARKETS:

        params.append(
            f"{symbol.lower()}@trade"
        )

    payload = {
        "method": "SUBSCRIBE",
        "params": params,
        "id": int(time.time())
    }

    try:

        ws.send(
            json.dumps(payload)
        )

        print(
            "Subscription sent:",
            len(params),
            "streams"
        )

        if params:

            print(
                "First stream:",
                params[0]
            )

    except Exception as exc:

        print(
            "SUBSCRIPTION SEND ERROR:",
            repr(exc)
        )


# ============================================================
# REPORTER
# ============================================================

def reporter():

    while True:

        time.sleep(
            REPORT_SECONDS
        )

        try:

            # First scan signals.
            scan_signals()

            with lock:

                market_count = len(
                    MARKETS
                )

                connected_now = len(
                    connected_markets
                )

                connected_ever = len(
                    ever_connected_markets
                )

                raw = stats["raw"]

                parsed = stats["parsed"]

                errors = stats["errors"]

                signal_count = stats[
                    "signals"
                ]

                subscription_ok = stats[
                    "subscription_ok"
                ]

                subscription_errors = stats[
                    "subscription_errors"
                ]

                closed_count = sum(
                    len(history)
                    for history
                    in candles.values()
                )

                ready = sum(
                    1
                    for history
                    in candles.values()
                    if len(history) >= 40
                )

                current_count = len(
                    current_candles
                )

            print(
                "\n"
                + "=" * 56
            )

            print(
                VERSION
            )

            print(
                "Time:",
                utc_now()
            )

            print(
                "Markets:",
                market_count
            )

            print(
                "Connected now:",
                connected_now
            )

            print(
                "Connected at least once:",
                connected_ever
            )

            print(
                "Raw messages:",
                raw
            )

            print(
                "Parsed trades:",
                parsed
            )

            print(
                "Current candles:",
                current_count
            )

            print(
                "Closed candles stored:",
                closed_count
            )

            print(
                "MACD-ready markets:",
                ready
            )

            print(
                "Signals detected:",
                signal_count
            )

            print(
                "Subscription ACK:",
                subscription_ok
            )

            print(
                "Subscription errors:",
                subscription_errors
            )

            print(
                "WebSocket/message errors:",
                errors
            )

            print(
                "MACD:",
                f"{MACD_FAST}/"
                f"{MACD_SLOW}/"
                f"{MACD_SIGNAL}"
            )

            print(
                "TIMEFRAME: 5M"
            )

            print(
                "REAL TRADING: OFF"
            )

            print(
                "ORDER ENDPOINT: NEVER CALLED"
            )

            print(
                "=" * 56
                + "\n"
            )

        except Exception as exc:

            print(
                "REPORTER ERROR:",
                repr(exc)
            )


# ============================================================
# WEBSOCKET LOOP
# ============================================================

def websocket_loop():

    while True:

        try:

            print(
                "\nConnecting WebSocket..."
            )

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

            print(
                "WEBSOCKET LOOP ERROR:",
                repr(exc)
            )

        print(
            f"Reconnecting in "
            f"{RECONNECT_SECONDS} seconds..."
        )

        time.sleep(
            RECONNECT_SECONDS
        )


# ============================================================
# MAIN
# ============================================================

def main():

    global MARKETS

    print(
        "\n"
        "################################################"
    )

    print(
        VERSION
    )

    print(
        "################################################"
    )

    print(
        "Started:",
        utc_now()
    )

    print(
        "Futures API:",
        BASE_URL
    )

    print(
        "WebSocket:",
        WS_URL
    )

    print(
        "TIMEFRAME: 5M"
    )

    print(
        "MACD:",
        f"{MACD_FAST}/{MACD_SLOW}/{MACD_SIGNAL}"
    )

    print(
        "REAL TRADING:",
        "ON" if REAL_TRADING else "OFF"
    )

    print(
        "ORDER ENDPOINT: NEVER CALLED"
    )

    # --------------------------------------------------------
    # Discover markets
    # --------------------------------------------------------

    try:

        MARKETS = discover_markets()

    except Exception as exc:

        print(
            "\n"
            "❌ MARKET DISCOVERY FAILED"
        )

        print(
            repr(exc)
        )

        return

    print(
        "\n"
        "✅ Markets discovered:",
        len(MARKETS)
    )

    print(
        "First markets:"
    )

    print(
        ", ".join(
            MARKETS[:15]
        )
    )

    # --------------------------------------------------------
    # Start reporter
    # --------------------------------------------------------

    threading.Thread(
        target=reporter,
        daemon=True
    ).start()

    # --------------------------------------------------------
    # Start WebSocket
    # --------------------------------------------------------

    websocket_loop()


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()
