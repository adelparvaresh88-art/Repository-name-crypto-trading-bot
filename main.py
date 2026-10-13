import json
import time
import threading
from datetime import datetime, timezone

import requests
import websocket


# ============================================================
# ATI TABDEAL FUTURES
# WEBSOCKET DIAGNOSTIC V1
#
# PURPOSE:
#   1. Discover Futures markets
#   2. Connect to Tabdeal Futures WebSocket
#   3. Subscribe to trade streams
#   4. Print REAL raw messages
#
# REAL TRADING: OFF
# NO ORDER ENDPOINT
# NO MACD
# NO ORDERS
# ============================================================

VERSION = "ATI TABDEAL FUTURES WS TEST V1"

BASE_URL = "https://api1.tabdeal.org"
WS_URL = "wss://api1.tabdeal.org/special_margin/stream/"

MAX_MARKETS = 75

RECONNECT_SECONDS = 5

lock = threading.RLock()

MARKETS = []

stats = {
    "raw": 0,
    "json": 0,
    "trade_like": 0,
    "errors": 0,
    "subscription_ack": 0,
    "subscription_error": 0,
}

first_raw_printed = False
first_trade_printed = False


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

    print("HTTP GET:", url)

    response = requests.get(
        url,
        timeout=timeout,
        headers={
            "User-Agent": VERSION
        },
    )

    print(
        "HTTP STATUS:",
        response.status_code
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# MARKET DISCOVERY
# ============================================================

def discover_markets():

    print()
    print("=" * 60)
    print("MARKET DISCOVERY")
    print("=" * 60)

    data = get_json(
        "/r/fapi/v1/exchangeInfo"
    )

    if not isinstance(data, dict):

        raise RuntimeError(
            "exchangeInfo is not an object"
        )

    symbols = data.get(
        "symbols",
        []
    )

    if not isinstance(symbols, list):

        raise RuntimeError(
            "exchangeInfo.symbols is not a list"
        )

    result = []

    for item in symbols:

        if not isinstance(item, dict):
            continue

        raw_symbol = str(
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

        # Keep the exchange's normal symbol
        symbol = raw_symbol.replace(
            "_",
            ""
        )

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

    result = sorted(
        set(result)
    )

    if not result:

        raise RuntimeError(
            "No eligible USDT Futures markets found."
        )

    result = result[:MAX_MARKETS]

    print()
    print(
        "Markets discovered:",
        len(result)
    )

    print(
        "First markets:"
    )

    for symbol in result[:15]:

        print(
            "  ",
            symbol
        )

    return result


# ============================================================
# MESSAGE ANALYSIS
# ============================================================

def inspect_message(message):

    global first_trade_printed

    if not isinstance(
        message,
        dict
    ):
        return

    # --------------------------------------------------------
    # Subscription ACK
    # --------------------------------------------------------

    if (
        "result" in message
        and "id" in message
    ):

        if message.get(
            "result"
        ) is None:

            stats[
                "subscription_ack"
            ] += 1

            print()
            print(
                "✅ SUBSCRIPTION ACK:"
            )

            print(
                json.dumps(
                    message,
                    ensure_ascii=False
                )
            )

        else:

            stats[
                "subscription_error"
            ] += 1

            print()
            print(
                "❌ SUBSCRIPTION ERROR:"
            )

            print(
                json.dumps(
                    message,
                    ensure_ascii=False
                )
            )

        return

    # --------------------------------------------------------
    # Common Tabdeal structure:
    #
    # {
    #   "stream": "...",
    #   "data": {...}
    # }
    # --------------------------------------------------------

    data = message.get(
        "data"
    )

    if not isinstance(
        data,
        dict
    ):

        data = message

    symbol = (
        data.get("s")
        or data.get("symbol")
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

    timestamp = (
        data.get("T")
        if data.get("T") is not None
        else data.get("E")
    )

    if timestamp is None:

        timestamp = data.get(
            "time"
        )

    if (
        symbol is not None
        and price is not None
        and qty is not None
    ):

        stats[
            "trade_like"
        ] += 1

        if not first_trade_printed:

            first_trade_printed = True

            print()
            print("=" * 60)
            print(
                "🔥 FIRST TRADE-LIKE MESSAGE"
            )
            print("=" * 60)

            print(
                json.dumps(
                    message,
                    ensure_ascii=False,
                    indent=2
                )[:5000]
            )

            print(
                "=" * 60
            )


# ============================================================
# WEBSOCKET MESSAGE
# ============================================================

def on_message(
    ws,
    raw_message
):

    global first_raw_printed

    try:

        with lock:

            stats["raw"] += 1

        # ----------------------------------------------------
        # FIRST RAW MESSAGE
        # ----------------------------------------------------

        if not first_raw_printed:

            first_raw_printed = True

            print()
            print("=" * 60)
            print(
                "🔥 FIRST RAW WEBSOCKET MESSAGE"
            )
            print("=" * 60)

            print(
                str(raw_message)[:10000]
            )

            print(
                "=" * 60
            )

        # ----------------------------------------------------
        # JSON
        # ----------------------------------------------------

        try:

            message = json.loads(
                raw_message
            )

        except Exception:

            print()
            print(
                "⚠️ NON-JSON MESSAGE:"
            )

            print(
                str(raw_message)[:3000]
            )

            return

        with lock:

            stats["json"] += 1

        inspect_message(
            message
        )

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

def on_error(
    ws,
    error
):

    with lock:

        stats["errors"] += 1

    print()
    print(
        "❌ WEBSOCKET ERROR:"
    )

    print(
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

    print()
    print(
        "⚠️ WEBSOCKET CLOSED"
    )

    print(
        "Code:",
        close_status_code
    )

    print(
        "Message:",
        close_msg
    )


# ============================================================
# WEBSOCKET OPEN
# ============================================================

def on_open(ws):

    print()
    print("=" * 60)
    print(
        "✅ WEBSOCKET CONNECTED"
    )
    print(
        "Time:",
        utc_now()
    )
    print(
        "URL:",
        WS_URL
    )
    print(
        "Markets:",
        len(MARKETS)
    )
    print("=" * 60)

    # --------------------------------------------------------
    # IMPORTANT:
    #
    # First test ONE market only.
    #
    # This makes diagnosis much easier.
    # --------------------------------------------------------

    if not MARKETS:

        print(
            "❌ No markets available."
        )

        return

    symbol = MARKETS[0]

    stream = (
        f"{symbol.lower()}@trade"
    )

    payload = {
        "method": "SUBSCRIBE",
        "params": [
            stream
        ],
        "id": int(
            time.time()
        ),
    }

    print()
    print(
        "TEST STREAM:"
    )

    print(
        stream
    )

    print()
    print(
        "SUBSCRIBE PAYLOAD:"
    )

    print(
        json.dumps(
            payload,
            ensure_ascii=False
        )
    )

    try:

        ws.send(
            json.dumps(
                payload
            )
        )

        print()
        print(
            "✅ SUBSCRIBE SENT"
        )

    except Exception as exc:

        print()
        print(
            "❌ SUBSCRIBE SEND ERROR:"
        )

        print(
            repr(exc)
        )


# ============================================================
# REPORT
# ============================================================

def reporter():

    while True:

        time.sleep(
            30
        )

        with lock:

            snapshot = dict(
                stats
            )

        print()
        print("-" * 60)

        print(
            "WEBSOCKET TEST REPORT"
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
            "Raw messages:",
            snapshot["raw"]
        )

        print(
            "JSON messages:",
            snapshot["json"]
        )

        print(
            "Trade-like messages:",
            snapshot["trade_like"]
        )

        print(
            "Subscription ACK:",
            snapshot[
                "subscription_ack"
            ]
        )

        print(
            "Subscription errors:",
            snapshot[
                "subscription_error"
            ]
        )

        print(
            "Errors:",
            snapshot["errors"]
        )

        print(
            "REAL TRADING: OFF"
        )

        print(
            "ORDER ENDPOINT: NEVER CALLED"
        )

        print("-" * 60)


# ============================================================
# WEBSOCKET LOOP
# ============================================================

def websocket_loop():

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
            )

        except Exception as exc:

            print()
            print(
                "❌ WEBSOCKET LOOP ERROR:"
            )

            print(
                repr(exc)
            )

        print()
        print(
            "Reconnecting in",
            RECONNECT_SECONDS,
            "seconds..."
        )

        time.sleep(
            RECONNECT_SECONDS
        )


# ============================================================
# MAIN
# ============================================================

def main():

    global MARKETS

    print()
    print("#" * 60)
    print(
        VERSION
    )
    print("#" * 60)

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
        "REAL TRADING: OFF"
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

        print()
        print(
            "❌ MARKET DISCOVERY FAILED"
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
        daemon=True
    ).start()

    # --------------------------------------------------------
    # WebSocket
    # --------------------------------------------------------

    websocket_loop()


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":

    main()
