import os
import json
import time
import threading
import requests
import websocket
from datetime import datetime, timezone

BASE = "https://api1.tabdeal.org"
BROADCAST_URL = BASE + "/special_margin/broadcast/"
DEPTH_WS_URL = BASE + "/special_margin/stream/"

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TEST_SECONDS = 20
LIVE_TRADING = False

http = requests.Session()
received = {"trades": [], "depth": [], "errors": []}


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def telegram(message):
    print(message)
    if not TOKEN or not CHAT_ID:
        print("Telegram secrets are missing.")
        return

    try:
        r = http.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": message[:3900]},
            timeout=12
        )
        print("Telegram status:", r.status_code)
    except Exception as e:
        print("Telegram error:", repr(e))


def get_markets():
    url = BASE + "/r/fapi/v1/exchangeInfo"
    r = http.get(url, timeout=15)
    print("ExchangeInfo HTTP:", r.status_code)
    r.raise_for_status()

    data = r.json()
    rows = data.get("symbols", []) if isinstance(data, dict) else data

    markets = []
    for row in rows:
        if not isinstance(row, dict):
            continue

        symbol = str(row.get("symbol", "")).upper()
        quote = str(row.get("quoteAsset", "")).upper()
        status = str(row.get("status", "")).upper()

        if (
            symbol.endswith("_USDT")
            and quote == "USDT"
            and status in ("TRADING", "ACTIVE", "ENABLED")
        ):
            markets.append(symbol)

    return list(dict.fromkeys(markets))


def decode_message(message):
    try:
        return json.loads(message)
    except Exception:
        return {"raw": message[:500]}


def test_broadcast(symbol):
    print("\nTESTING FUTURES TRADE BROADCAST:", symbol)
    done = threading.Event()
    ws_state = {"opened": False, "closed": False}

    def on_open(ws):
        ws_state["opened"] = True
        print("BROADCAST CONNECTED")
        # طبق مستندات رسمی، پیام اشتراک متن ساده است.
        ws.send(symbol)

    def on_message(ws, message):
        data = decode_message(message)
        print("BROADCAST MESSAGE:", json.dumps(data, ensure_ascii=False)[:800])

        if isinstance(data, dict):
            if "error" in data:
                received["errors"].append(
                    "Broadcast: " + str(data.get("error"))
                )
            elif "trade" in data:
                received["trades"].append(data["trade"])
            elif "trades" in data:
                trades = data["trades"]
                if isinstance(trades, list):
                    received["trades"].extend(trades)
                else:
                    received["trades"].append(trades)
            else:
                received["trades"].append(data)

        if len(received["trades"]) >= 3:
            done.set()
            ws.close()

    def on_error(ws, error):
        text = "Broadcast WS error: " + str(error)
        print(text)
        received["errors"].append(text)
        done.set()

    def on_close(ws, code, msg):
        ws_state["closed"] = True
        print("BROADCAST CLOSED:", code, msg)
        done.set()

    app = websocket.WebSocketApp(
        BROADCAST_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    thread = threading.Thread(
        target=lambda: app.run_forever(ping_interval=10, ping_timeout=5),
        daemon=True
    )
    thread.start()

    done.wait(TEST_SECONDS)

    try:
        app.close()
    except Exception:
        pass

    thread.join(timeout=3)

    print(
        "BROADCAST SUMMARY:",
        "connected=", ws_state["opened"],
        "messages=", len(received["trades"]),
        "closed=", ws_state["closed"]
    )


def test_depth(symbol):
    print("\nTESTING FUTURES DEPTH STREAM:", symbol)
    done = threading.Event()
    state = {"opened": False}

    def on_open(ws):
        state["opened"] = True
        request = {
            "method": "SUBSCRIBE",
            "params": [
                f"special_margin@{symbol}@depth@1000ms"
            ],
            "id": 1
        }
        ws.send(json.dumps(request))
        print("DEPTH SUBSCRIBE SENT:", json.dumps(request))

    def on_message(ws, message):
        data = decode_message(message)
        print("DEPTH MESSAGE:", json.dumps(data, ensure_ascii=False)[:700])

        if isinstance(data, dict):
            if "error" in data or "code" in data:
                received["errors"].append(
                    "Depth: " + json.dumps(data, ensure_ascii=False)[:300]
                )
            elif data.get("id") == 1 or "depthUpdate" in str(data):
                received["depth"].append(data)

        if len(received["depth"]) >= 2:
            done.set()
            ws.close()

    def on_error(ws, error):
        text = "Depth WS error: " + str(error)
        print(text)
        received["errors"].append(text)
        done.set()

    def on_close(ws, code, msg):
        print("DEPTH CLOSED:", code, msg)
        done.set()

    app = websocket.WebSocketApp(
        DEPTH_WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    thread = threading.Thread(
        target=lambda: app.run_forever(ping_interval=10, ping_timeout=5),
        daemon=True
    )
    thread.start()

    done.wait(TEST_SECONDS)

    try:
        app.close()
    except Exception:
        pass

    thread.join(timeout=3)

    print(
        "DEPTH SUMMARY:",
        "connected=", state["opened"],
        "messages=", len(received["depth"])
    )


def main():
    print("=" * 50)
    print("ATI TABDEAL FUTURES V20")
    print("Time:", now())
    print("REAL TRADING: OFF")
    print("=" * 50)

    telegram(
        "🚀 ATI FUTURES V20\n"
        f"Time: {now()}\n"
        "Testing official futures WebSocket feeds.\n"
        "Real trading: OFF"
    )

    markets = get_markets()
    print("USDT futures markets:", len(markets))
    print("First markets:", markets[:15])

    if not markets:
        raise RuntimeError("No eligible futures USDT markets found.")

    symbol = "BTC_USDT" if "BTC_USDT" in markets else markets[0]

    # ابتدا اتصال معاملات، سپس دفتر سفارش را آزمایش می‌کنیم.
    test_broadcast(symbol)
    test_depth(symbol)

    report = [
        "🧪 ATI FUTURES V20 RESULTS",
        f"Time: {now()}",
        f"Markets: {len(markets)}",
        f"Test symbol: {symbol}",
        f"Broadcast messages: {len(received['trades'])}",
        f"Depth messages: {len(received['depth'])}",
        f"WebSocket errors: {len(received['errors'])}",
        "REAL TRADING: OFF",
        "",
    ]

    if received["trades"]:
        report.append("BROADCAST SAMPLE:")
        report.append(
            json.dumps(received["trades"][0], ensure_ascii=False)[:700]
        )
    else:
        report.append("No trade messages received during test.")

    if received["depth"]:
        report.append("")
        report.append("DEPTH SAMPLE:")
        report.append(
            json.dumps(received["depth"][0], ensure_ascii=False)[:700]
        )
    else:
        report.append("No depth messages received during test.")

    if received["errors"]:
        report.append("")
        report.append("ERRORS:")
        report.extend(received["errors"][:5])

    final_report = "\n".join(report)
    print("\n" + final_report)
    telegram(final_report)


if __name__ == "__main__":
    main()
