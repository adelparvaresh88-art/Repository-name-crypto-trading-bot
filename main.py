import os
import json
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone

import requests
import websocket


# ============================================================
# ATI FUTURES V23
# TABDEAL FUTURES
#
# DATA:
#   Tabdeal Futures ExchangeInfo
#   WebSocket Trade Stream
#
# CANDLE:
#   5 MINUTES
#
# STRATEGY:
#   MACD 12 / 26 / 9
#
# IMPORTANT:
#   CLOSED CANDLES ONLY
#
# REAL TRADING:
#   OFF
#
# NO ORDER ENDPOINT IS USED
# ============================================================


VERSION = "ATI FUTURES V23"

BASE_URL = "https://api1.tabdeal.org"

# This is the stream URL used by the supplied V22 code.
# We DO NOT assume that it is correct.
# The program prints the raw stream messages so it can be verified.
WS_URL = "wss://api1.tabdeal.org/special_margin/stream/"

TIMEFRAME_MS = 5 * 60 * 1000

MAX_CANDLES = 200
MAX_MARKETS = 75

REPORT_SECONDS = 60

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# SAFETY:
REAL_TRADING = False


# ============================================================
# GLOBAL STATE
# ============================================================

lock = threading.Lock()

MARKETS = []

candles = defaultdict(lambda: deque(maxlen=MAX_CANDLES))
current_candles = {}

connected_markets = set()
ever_connected_markets = set()

last_trade_time = {}

last_signal_candle = {}

stats = {
    "raw": 0,
    "parsed": 0,
    "errors": 0,
    "signals": 0,
    "unknown_messages": 0,
}

last_raw_message = ""


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# HTTP
# ============================================================

def get_json(path, timeout=15):
    url = BASE_URL + path

    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": "ATI-Futures/23"
        },
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# MARKET DISCOVERY
# ============================================================

def discover_markets():

    print()
    print("Discovering Tabdeal Futures markets...")
    print("Endpoint:", BASE_URL + "/r/fapi/v1/exchangeInfo")

    data = get_json("/r/fapi/v1/exchangeInfo")

    if not isinstance(data, dict):
        raise RuntimeError(
            "exchangeInfo returned unexpected type: "
            + type(data).__name__
        )

    symbols = data.get("symbols")

    if not isinstance(symbols, list):
        raise RuntimeError(
            "exchangeInfo has no valid 'symbols' list"
        )

    result = []

    for item in symbols:

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

        if not symbol:
            continue

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
            "No eligible USDT Futures markets found."
        )

    result = result[:MAX_MARKETS]

    print("Eligible markets:", len(result))
    print(
        "Markets:",
        ", ".join(result[:15])
    )

    return result


# ============================================================
# NUMBER HELPERS
# ============================================================

def to_float(value):

    try:
        return float(value)
    except (
        TypeError,
        ValueError,
    ):
        return None


def to_timestamp_ms(value):

    try:
        ts = int(float(value))
    except (
        TypeError,
        ValueError,
    ):
        return None

    # seconds -> milliseconds
    if ts < 10_000_000_000:
        ts *= 1000

    return ts


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(message):

    if not isinstance(message, dict):
        return None

    # --------------------------------------------------------
    # Possible containers
    # --------------------------------------------------------

    candidates = []

    data = message.get("data")

    if isinstance(data, dict):
        candidates.append(data)

    candidates.append(message)

    # Sometimes stream messages contain:
    #
    # {
    #   "data": {
    #       ...
    #   }
    # }
    #
    # or direct:
    #
    # {
    #   "symbol": "...",
    #   "price": "...",
    #   ...
    # }

    for obj in candidates:

        if not isinstance(obj, dict):
            continue

        symbol = (
            obj.get("symbol")
            or obj.get("s")
            or obj.get("S")
        )

        price = (
            obj.get("price")
            or obj.get("p")
            or obj.get("P")
        )

        quantity = (
            obj.get("qty")
            or obj.get("quantity")
            or obj.get("q")
            or obj.get("Q")
            or obj.get("volume")
        )

        timestamp = (
            obj.get("timestamp")
            or obj.get("time")
            or obj.get("T")
            or obj.get("E")
            or obj.get("eventTime")
        )

        if (
            symbol is None
            or price is None
            or quantity is None
            or timestamp is None
        ):
            continue

        price = to_float(price)
        quantity = to_float(quantity)
        timestamp = to_timestamp_ms(timestamp)

        if price is None:
            continue

        if quantity is None:
            continue

        if timestamp is None:
            continue

        if price <= 0:
            continue

        if quantity < 0:
            continue

        symbol = str(symbol).upper()

        # Only accept discovered markets.
        if symbol not in MARKETS:
            continue

        return (
            symbol,
            timestamp,
            price,
            quantity,
        )

    return None


# ============================================================
# CANDLE
# ============================================================

def close_candle(symbol, candle):

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

    dt = datetime.fromtimestamp(
        row["time"] / 1000,
        timezone.utc,
    )

    print(
        f"CANDLE CLOSED | {symbol} | "
        f"{dt.strftime('%Y-%m-%d %H:%M:%S')} | "
        f"O={row['open']} "
        f"H={row['high']} "
        f"L={row['low']} "
        f"C={row['close']} "
        f"V={row['volume']}"
    )


def process_trade(trade):

    symbol, timestamp, price, quantity = trade

    bucket = (
        timestamp // TIMEFRAME_MS
    ) * TIMEFRAME_MS

    new_closed_candle = False

    with lock:

        stats["parsed"] += 1

        last_trade_time[symbol] = timestamp

        old = current_candles.get(symbol)

        # ----------------------------------------------------
        # First trade for symbol
        # ----------------------------------------------------

        if old is None:

            current_candles[symbol] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity,
            }

            return

        # ----------------------------------------------------
        # Old trade
        # ----------------------------------------------------

        if bucket < old["time"]:
            return

        # ----------------------------------------------------
        # Same candle
        # ----------------------------------------------------

        if bucket == old["time"]:

            old["high"] = max(
                old["high"],
                price,
            )

            old["low"] = min(
                old["low"],
                price,
            )

            old["close"] = price

            old["volume"] += quantity

            return

        # ----------------------------------------------------
        # New candle
        # ----------------------------------------------------

        close_candle(
            symbol,
            old,
        )

        new_closed_candle = True

        # IMPORTANT:
        #
        # We DO NOT create artificial candles
        # for missing periods.
        #
        # Artificial candles can distort MACD.

        current_candles[symbol] = {
            "time": bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": quantity,
        }

    # --------------------------------------------------------
    # Scan outside the lock
    # --------------------------------------------------------

    if new_closed_candle:

        scan_symbol(symbol)


# ============================================================
# EMA
# ============================================================

def calculate_ema(values, period):

    if len(values) < period:
        return None

    seed = sum(
        values[:period]
    ) / period

    multiplier = 2.0 / (
        period + 1.0
    )

    value = seed

    for price in values[period:]:

        value = (
            price * multiplier
            + value * (1.0 - multiplier)
        )

    return value


# ============================================================
# MACD SERIES
# ============================================================

def calculate_macd_series(closes):

    if len(closes) < MACD_SLOW:
        return []

    fast_ema = []
    slow_ema = []

    fast_alpha = 2.0 / (
        MACD_FAST + 1.0
    )

    slow_alpha = 2.0 / (
        MACD_SLOW + 1.0
    )

    # --------------------------------------------------------
    # Fast EMA
    # --------------------------------------------------------

    fast = sum(
        closes[:MACD_FAST]
    ) / MACD_FAST

    for index, price in enumerate(
        closes[MACD_FAST - 1:],
        start=MACD_FAST - 1,
    ):

        if index == MACD_FAST - 1:
            value = fast
        else:
            value = (
                price * fast_alpha
                + fast * (1.0 - fast_alpha)
            )
            fast = value

        fast_ema.append(
            (index, value)
        )

    # --------------------------------------------------------
    # Slow EMA
    # --------------------------------------------------------

    slow = sum(
        closes[:MACD_SLOW]
    ) / MACD_SLOW

    for index, price in enumerate(
        closes[MACD_SLOW - 1:],
        start=MACD_SLOW - 1,
    ):

        if index == MACD_SLOW - 1:
            value = slow
        else:
            value = (
                price * slow_alpha
                + slow * (1.0 - slow_alpha)
            )
            slow = value

        slow_ema.append(
            (index, value)
        )

    slow_map = dict(slow_ema)

    macd_values = []

    for index, fast_value in fast_ema:

        if index not in slow_map:
            continue

        macd_values.append(
            (
                index,
                fast_value - slow_map[index],
            )
        )

    if len(macd_values) < MACD_SIGNAL:
        return []

    # --------------------------------------------------------
    # Signal EMA
    # --------------------------------------------------------

    macd_numbers = [
        value
        for _, value in macd_values
    ]

    signal_alpha = 2.0 / (
        MACD_SIGNAL + 1.0
    )

    signal = sum(
        macd_numbers[:MACD_SIGNAL]
    ) / MACD_SIGNAL

    result = []

    for i, (index, macd) in enumerate(
        macd_values
    ):

        if i < MACD_SIGNAL - 1:
            continue

        if i == MACD_SIGNAL - 1:
            signal_value = signal
        else:
            signal_value = (
                macd * signal_alpha
                + signal * (
                    1.0 - signal_alpha
                )
            )
            signal = signal_value

        result.append(
            {
                "index": index,
                "macd": macd,
                "signal": signal_value,
            }
        )

    return result


# ============================================================
# SIGNAL
# ============================================================

def scan_symbol(symbol):

    with lock:

        history = list(
            candles.get(symbol, [])
        )

    # Need enough CLOSED candles.
    if len(history) < 40:
        return

    # All entries in history are closed candles.
    closes = [
        float(row["close"])
        for row in history
    ]

    macd = calculate_macd_series(
        closes
    )

    if len(macd) < 2:
        return

    previous = macd[-2]
    current = macd[-1]

    candle_time = history[-1]["time"]

    with lock:

        if (
            last_signal_candle.get(symbol)
            == candle_time
        ):
            return

    side = None

    # BUY crossover
    if (
        previous["macd"]
        <= previous["signal"]
        and
        current["macd"]
        > current["signal"]
    ):
        side = "BUY"

    # SELL crossover
    elif (
        previous["macd"]
        >= previous["signal"]
        and
        current["macd"]
        < current["signal"]
    ):
        side = "SELL"

    if side is None:
        return

    with lock:

        last_signal_candle[
            symbol
        ] = candle_time

        stats["signals"] += 1

    price = history[-1]["close"]

    dt = datetime.fromtimestamp(
        candle_time / 1000,
        timezone.utc,
    )

    print()
    print("=" * 60)
    print("MACD SIGNAL")
    print("SIDE:", side)
    print("SYMBOL:", symbol)
    print("PRICE:", price)
    print(
        "CANDLE:",
        dt.strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        ),
    )
    print(
        "MACD:",
        f"{current['macd']:.10f}",
    )
    print(
        "SIGNAL:",
        f"{current['signal']:.10f}",
    )
    print("REAL_TRADING:", REAL_TRADING)
    print("ORDER SENT: NO")
    print("=" * 60)
    print()


# ============================================================
# WEBSOCKET MESSAGE
# ============================================================

def on_message(ws, raw_message):

    global last_raw_message

    try:

        with lock:
            stats["raw"] += 1

        last_raw_message = str(
            raw_message
        )

        try:
            message = json.loads(
                raw_message
            )
        except json.JSONDecodeError:

            with lock:
                stats["unknown_messages"] += 1

            print(
                "NON-JSON WS MESSAGE:",
                str(raw_message)[:500],
            )

            return

        # ----------------------------------------------------
        # Subscription acknowledgement
        # ----------------------------------------------------

        if isinstance(message, dict):

            if (
                "result" in message
                and "id" in message
            ):
                print(
                    "WS SUBSCRIBE RESPONSE:",
                    message,
                )
                return

            event = str(
                message.get("e", "")
            ).lower()

            event_type = str(
                message.get("type", "")
            ).lower()

            if event in (
                "subscribed",
                "subscription",
                "subscribe",
            ):
                print(
                    "WS SUBSCRIPTION:",
                    message,
                )
                return

            if event_type in (
                "subscribed",
                "subscription",
            ):
                print(
                    "WS SUBSCRIPTION:",
                    message,
                )
                return

        trade = parse_trade(
            message
        )

        if trade is None:

            with lock:
                stats["unknown_messages"] += 1

            # Print only a limited amount of
            # unknown messages.
            unknown_count = stats[
                "unknown_messages"
            ]

            if unknown_count <= 10:

                print(
                    "UNPARSED WS MESSAGE:",
                    json.dumps(
                        message,
                        ensure_ascii=False,
                    )[:1000],
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

        process_trade(
            trade
        )

    except Exception as exc:

        with lock:
            stats["errors"] += 1

        print(
            "MESSAGE ERROR:",
            repr(exc),
        )


# ============================================================
# WEBSOCKET ERROR
# ============================================================

def on_error(ws, error):

    with lock:
        stats["errors"] += 1

    print(
        "WEBSOCKET ERROR:",
        repr(error),
    )


# ============================================================
# WEBSOCKET CLOSE
# ============================================================

def on_close(
    ws,
    close_status_code,
    close_msg,
):

    print(
        "WEBSOCKET CLOSED:",
        close_status_code,
        close_msg,
    )


# ============================================================
# WEBSOCKET OPEN
# ============================================================

def on_open(ws):

    print()
    print(
        "WEBSOCKET CONNECTED:",
        utc_now(),
    )

    print(
        "Stream URL:",
        WS_URL,
    )

    # --------------------------------------------------------
    # Current subscription format from V22.
    #
    # IMPORTANT:
    # We log the exact request.
    # If Tabdeal rejects this format, the raw response
    # will show the problem.
    # --------------------------------------------------------

    params = [
        f"{symbol.lower()}@trade"
        for symbol in MARKETS
    ]

    payload = {
        "method": "SUBSCRIBE",
        "params": params,
        "id": 1,
    }

    text = json.dumps(
        payload
    )

    print(
        "SUBSCRIBE REQUEST:"
    )

    print(
        text[:3000]
    )

    try:

        ws.send(text)

        print(
            "SUBSCRIBE SENT:",
            len(params),
            "markets",
        )

    except Exception as exc:

        print(
            "SUBSCRIBE SEND ERROR:",
            repr(exc),
        )


# ============================================================
# REPORTER
# ============================================================

def reporter():

    while True:

        time.sleep(
            REPORT_SECONDS
        )

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
            signals = stats["signals"]
            unknown = stats[
                "unknown_messages"
            ]

            closed = sum(
                len(history)
                for history in candles.values()
            )

            ready = sum(
                1
                for history in candles.values()
                if len(history) >= 40
            )

            active = len(
                current_candles
            )

        print()
        print("=" * 60)
        print(VERSION)
        print("Time:", utc_now())
        print("Markets:", market_count)
        print(
            "Connected now:",
            connected_now,
        )
        print(
            "Connected at least once:",
            connected_ever,
        )
        print(
            "Raw messages:",
            raw,
        )
        print(
            "Parsed trades:",
            parsed,
        )
        print(
            "Unknown messages:",
            unknown,
        )
        print(
            "Active candles:",
            active,
        )
        print(
            "Closed candles:",
            closed,
        )
        print(
            "MACD-ready markets:",
            ready,
        )
        print(
            "Signals:",
            signals,
        )
        print(
            "Errors:",
            errors,
        )
        print(
            "MACD:",
            "12/26/9",
        )
        print(
            "TIMEFRAME:",
            "5m",
        )
        print(
            "REAL TRADING: OFF"
        )
        print(
            "ORDER ENDPOINT: NEVER CALLED"
        )
        print("=" * 60)
        print()


# ============================================================
# MAIN
# ============================================================

def main():

    global MARKETS

    print()
    print("=" * 60)
    print(VERSION)
    print("=" * 60)
    print(
        "Started:",
        utc_now(),
    )
    print(
        "REAL TRADING:",
        "ON"
        if REAL_TRADING
        else "OFF",
    )
    print(
        "MACD: 12/26/9"
    )
    print(
        "TIMEFRAME: 5m"
    )
    print(
        "ORDER ENDPOINT: NEVER CALLED"
    )
    print("=" * 60)

    # --------------------------------------------------------
    # Discover markets
    # --------------------------------------------------------

    try:

        MARKETS = discover_markets()

    except Exception as exc:

        print()
        print(
            "MARKET DISCOVERY FAILED:"
        )
        print(
            repr(exc)
        )

        return

    # --------------------------------------------------------
    # Reporter
    # --------------------------------------------------------

    threading.Thread(
        target=reporter,
        daemon=True,
    ).start()

    # --------------------------------------------------------
    # WebSocket reconnect loop
    # --------------------------------------------------------

    while True:

        try:

            print()
            print(
                "Connecting WebSocket..."
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
                skip_utf8_validation=True,
            )

        except Exception as exc:

            print(
                "WEBSOCKET LOOP ERROR:",
                repr(exc),
            )

        print(
            "WebSocket disconnected."
        )

        print(
            "Reconnect in 5 seconds..."
        )

        time.sleep(5)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
