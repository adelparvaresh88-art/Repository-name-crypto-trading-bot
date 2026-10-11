import os

# Remove proxy settings that can break websocket-client.
for key in list(os.environ):
    if key.lower() in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "ws_proxy",
        "wss_proxy",
    ):
        os.environ.pop(key, None)

os.environ["NO_PROXY"] = "api1.tabdeal.org,localhost,127.0.0.1"
os.environ["no_proxy"] = "api1.tabdeal.org,localhost,127.0.0.1"

import json
import time
import threading
from datetime import datetime, timezone

import requests
import websocket


BASE_URL = "https://api1.tabdeal.org"
WS_BROADCAST = "wss://api1.tabdeal.org/special_margin/broadcast/"
WS_DEPTH = "wss://api1.tabdeal.org/special_margin/stream/"

LIVE_TRADING = False
TEST_SECONDS = 15

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets are missing.")
        return

    url = (
        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"
        f"/sendMessage"
    )

    try:
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )
        print("Telegram status:", response.status_code)
        if not response.ok:
            print("Telegram response:", response.text[:500])
    except Exception as exc:
        print("Telegram error:", repr(exc))


def discover_markets():
    url = f"{BASE_URL}/r/fapi/v1/exchangeInfo"
    response = requests.get(url, timeout=20)
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError(
            "exchangeInfo response is not a JSON object"
        )

    symbols = data.get("symbols", [])

    if not isinstance(symbols, list):
        raise RuntimeError(
            "exchangeInfo has no valid symbols list"
        )

    markets = []

    for item in symbols:
        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol", "")).upper()
        status = str(item.get("status", "")).upper()
        quote = str(item.get("quoteAsset", "")).upper()

        if (
            symbol.endswith("_USDT")
            and quote == "USDT"
            and status == "TRADING"
        ):
            markets.append(symbol)

    if not markets:
        raise RuntimeError(
            "No eligible USDT futures markets found"
        )

    return markets


def test_broadcast(symbol):
    result = {
        "messages": [],
        "errors": [],
        "opened": False,
    }

    finished = threading.Event()

    def on_open(ws):
        result["opened"] = True
        print("Broadcast WebSocket connected.")
        print("Subscribing to:", symbol)
        ws.send(symbol)

    def on_message(ws, message):
        print("Broadcast raw message:", str(message)[:1000])

        try:
            parsed = json.loads(message)
        except Exception:
            parsed = message

        result["messages"].append(parsed)

        if len(result["messages"]) >= 3:
            finished.set()
            ws.close()

    def on_error(ws, error):
        error_text = repr(error)
        print("Broadcast WebSocket error:", error_text)
        result["errors"].append(error_text)

    def on_close(ws, code, message):
        print("Broadcast closed:", code, message)
        finished.set()

    app = websocket.WebSocketApp(
        WS_BROADCAST,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    def run_socket():
        try:
            app.run_forever(
                http_proxy_host=None,
                http_proxy_port=None,
                proxy_type="http",
                ping_interval=10,
                ping_timeout=5,
            )
        except Exception as exc:
            result["errors"].append(repr(exc))
            print("Broadcast run error:", repr(exc))
        finally:
            finished.set()

    thread = threading.Thread(
        target=run_socket,
        daemon=True,
    )
    thread.start()
    finished.wait(TEST_SECONDS)

    try:
        app.close()
    except Exception:
        pass

    thread.join(timeout=3)
    return result


def test_depth(symbol):
    result = {
        "messages": [],
        "errors": [],
        "opened": False,
    }

    finished = threading.Event()

    def on_open(ws):
        result["opened"] = True
        subscription = {
            "method": "SUBSCRIBE",
            "params": [
                f"special_margin@{symbol}@depth@1000ms"
            ],
            "id": 1,
        }
        ws.send(json.dumps(subscription))
        print("Depth subscription sent:", subscription)

    def on_message(ws, message):
        print("Depth raw message:", str(message)[:1000])

        try:
            parsed = json.loads(message)
        except Exception:
            parsed = message

        result["messages"].append(parsed)

        if len(result["messages"]) >= 3:
            finished.set()
            ws.close()

    def on_error(ws, error):
        error_text = repr(error)
        print("Depth WebSocket error:", error_text)
        result["errors"].append(error_text)

    def on_close(ws, code, message):
        print("Depth closed:", code, message)
        finished.set()

    app = websocket.WebSocketApp(
        WS_DEPTH,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    def run_socket():
        try:
            app.run_forever(
                http_proxy_host=None,
                http_proxy_port=None,
                proxy_type="http",
                ping_interval=10,
                ping_timeout=5,
            )
        except Exception as exc:
            result["errors"].append(repr(exc))
            print("Depth run error:", repr(exc))
        finally:
            finished.set()

    thread = threading.Thread(
        target=run_socket,
        daemon=True,
    )
    thread.start()
    finished.wait(TEST_SECONDS)

    try:
        app.close()
    except Exception:
        pass

    thread.join(timeout=3)
    return result


def main():
    started = now()

    print("=" * 50)
    print("ATI FUTURES V21 — WEBSOCKET CONNECTION TEST")
    print("Time:", started)
    print("Real trading:", LIVE_TRADING)
    print("=" * 50)

    telegram(
        "🧪 ATI FUTURES V21 STARTED\n"
        f"Time: {started}\n"
        "Mode: WebSocket connection test\n"
        "REAL TRADING: OFF"
    )

    errors = []
    broadcast = {"messages": [], "errors": [], "opened": False}
    depth = {"messages": [], "errors": [], "opened": False}

    try:
        markets = discover_markets()
        print("Markets found:", len(markets))
        print("First markets:", markets[:10])
    except Exception as exc:
        message = (
            "❌ ATI V21 MARKET DISCOVERY ERROR\n\n"
            f"{repr(exc)}\nTime: {now()}"
        )
        print(message)
        telegram(message)
        raise

    # BTC_USDT is selected only if it is in the discovered list.
    symbol = "BTC_USDT" if "BTC_USDT" in markets else markets[0]
    print("Test symbol:", symbol)

    print("Testing broadcast WebSocket...")
    broadcast = test_broadcast(symbol)

    print("Testing depth WebSocket...")
    depth = test_depth(symbol)

    errors.extend(
        [f"Broadcast: {e}" for e in broadcast["errors"]]
    )
    errors.extend(
        [f"Depth: {e}" for e in depth["errors"]]
    )

    lines = [
        "🧪 ATI FUTURES V21 RESULTS",
        f"Time: {now()}",
        f"Markets: {len(markets)}",
        f"Test symbol: {symbol}",
        f"Broadcast connected: {broadcast['opened']}",
        f"Broadcast messages: {len(broadcast['messages'])}",
        f"Depth connected: {depth['opened']}",
        f"Depth messages: {len(depth['messages'])}",
        f"WebSocket errors: {len(errors)}",
        "REAL TRADING: OFF",
    ]

    if broadcast["messages"]:
        sample = json.dumps(
            broadcast["messages"][0],
            ensure_ascii=False,
        )
        lines.extend([
            "",
            "BROADCAST SAMPLE:",
            sample[:1200],
        ])

    if depth["messages"]:
        sample = json.dumps(
            depth["messages"][0],
            ensure_ascii=False,
        )
        lines.extend([
            "",
            "DEPTH SAMPLE:",
            sample[:1200],
        ])

    if errors:
        lines.extend(["", "ERRORS:"])
        lines.extend(errors[:8])

    if not broadcast["messages"]:
        lines.extend([
            "",
            "No trade messages received during test.",
        ])

    if not depth["messages"]:
        lines.extend([
            "",
            "No depth messages received during test.",
        ])

    report = "\n".join(lines)
    print(report)
    telegram(report)


if __name__ == "__main__":
    main()
