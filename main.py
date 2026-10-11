import os
import sys
import json
import time
import math
import threading
import subprocess

from datetime import datetime, timezone

import requests
import websocket


# ==================================================
# ATI FUTURES V22
# TABDEAL FUTURES - LIVE WEBSOCKET - MACD 12/26/9
# SIGNAL ONLY - REAL TRADING DISABLED
# ==================================================

VERSION = "ATI FUTURES V22"

BASE_URL = "https://api1.tabdeal.org"
BROADCAST_URL = "wss://api1.tabdeal.org/special_margin/broadcast/"

LIVE_TRADING = False

MAX_MARKETS = 75
SCAN_SECONDS = 180

TIMEFRAME_SECONDS = 300
MAX_CANDLES = 100
MIN_CANDLES_FOR_MACD = 35

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

STOP_LOSS_PCT = 0.006
TAKE_PROFIT_PCT = 0.012

STATE_FILE = "ati_futures_state.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Prevent inherited proxy variables from breaking WebSocket.
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

print_lock = threading.Lock()
state_lock = threading.Lock()

socket_apps = []
worker_threads = []

state = {}
runtime = {}

errors = []
signals_found = []
telegram_alerts = []


def utc_now():
    return datetime.now(timezone.utc)


def utc_text():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


def log(*args):
    with print_lock:
        print(*args, flush=True)


def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram secrets are missing.")
        return False

    try:
        response = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=15,
        )

        if not response.ok:
            log("Telegram error:", response.status_code,
                response.text[:300])
            return False

        return True

    except Exception as exc:
        log("Telegram exception:", repr(exc))
        return False


def discover_markets():
    url = f"{BASE_URL}/r/fapi/v1/exchangeInfo"

    response = requests.get(url, timeout=20)
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict):
        raise RuntimeError("Invalid exchangeInfo response")

    symbols = data.get("symbols", [])

    if not isinstance(symbols, list):
        raise RuntimeError("exchangeInfo symbols is not a list")

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

    markets = sorted(set(markets))

    if not markets:
        raise RuntimeError("No eligible USDT futures markets found")

    return markets[:MAX_MARKETS]


def load_state():
    global state

    try:
        if not os.path.exists(STATE_FILE):
            state = {}
            log("No saved state yet; starting fresh.")
            return

        with open(STATE_FILE, "r", encoding="utf-8") as file:
            loaded = json.load(file)

        if not isinstance(loaded, dict):
            state = {}
            return

        state = loaded

        log("Saved state loaded for", len(state), "markets.")

    except Exception as exc:
        log("State load error:", repr(exc))
        state = {}


def save_state():
    temp_file = STATE_FILE + ".tmp"

    try:
        with state_lock:
            snapshot = json.loads(json.dumps(state))

        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(
                snapshot,
                file,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        os.replace(temp_file, STATE_FILE)

        log("State saved:", len(state), "markets.")
        return True

    except Exception as exc:
        log("State save error:", repr(exc))
        return False


def parse_trade_time(value):
    try:
        if value is None:
            return utc_now().timestamp()

        if isinstance(value, (int, float)):
            # Handle seconds or milliseconds.
            if value > 10_000_000_000:
                value = value / 1000.0
            return float(value)

        text = str(value).strip()

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        parsed = datetime.fromisoformat(text)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.timestamp()

    except Exception:
        return utc_now().timestamp()


def candle_bucket(timestamp):
    return int(timestamp // TIMEFRAME_SECONDS) * TIMEFRAME_SECONDS


def new_candle(bucket, price, amount=0.0):
    return {
        "t": int(bucket),
        "o": float(price),
        "h": float(price),
        "l": float(price),
        "c": float(price),
        "v": float(amount),
    }


def ensure_market_state(symbol):
    with state_lock:
        if symbol not in state or not isinstance(state[symbol], dict):
            state[symbol] = {
                "candles": [],
                "current": None,
                "last_signal": 0,
            }

        item = state[symbol]

        if not isinstance(item.get("candles"), list):
            item["candles"] = []

        return item


def append_closed_candle(symbol, candle):
    item = ensure_market_state(symbol)

    candles = item["candles"]

    # Do not duplicate a candle if a run resumes around a boundary.
    if candles and int(candles[-1].get("t", 0)) >= int(candle["t"]):
        return

    candles.append(candle)

    if len(candles) > MAX_CANDLES:
        del candles[:-MAX_CANDLES]


def advance_market_time(symbol, target_bucket):
    """
    Close the previous candle after its five-minute interval ends.
    Fill empty intervals with zero-volume candles at the last close.
    """
    item = ensure_market_state(symbol)
    current = item.get("current")

    if not current:
        return

    current_bucket = int(current["t"])

    if target_bucket <= current_bucket:
        return

    last_close = float(current["c"])

    append_closed_candle(symbol, current)

    next_bucket = current_bucket + TIMEFRAME_SECONDS

    while next_bucket < target_bucket:
        empty = new_candle(next_bucket, last_close, 0.0)
        append_closed_candle(symbol, empty)
        next_bucket += TIMEFRAME_SECONDS

    item["current"] = None


def process_trade(symbol, trade):
    try:
        price = float(trade.get("price", 0))
        amount = float(trade.get("amount", 0))

        if not math.isfinite(price) or price <= 0:
            return

        if not math.isfinite(amount) or amount < 0:
            amount = 0.0

        timestamp = parse_trade_time(trade.get("updated"))
        bucket = candle_bucket(timestamp)

        item = ensure_market_state(symbol)

        with state_lock:
            current = item.get("current")

            if current is None:
                # Do not append a partial candle from an old trade.
                current = new_candle(bucket, price, amount)
                item["current"] = current
                return

            old_bucket = int(current["t"])

            if bucket < old_bucket:
                return

            if bucket > old_bucket:
                append_closed_candle(symbol, current)

                last_close = float(current["c"])
                next_bucket = old_bucket + TIMEFRAME_SECONDS

                while next_bucket < bucket:
                    empty = new_candle(next_bucket, last_close, 0.0)
                    append_closed_candle(symbol, empty)
                    next_bucket += TIMEFRAME_SECONDS

                current = new_candle(bucket, price, amount)
                item["current"] = current
                return

            current["h"] = max(float(current["h"]), price)
            current["l"] = min(float(current["l"]), price)
            current["c"] = price
            current["v"] = float(current.get("v", 0)) + amount

    except Exception as exc:
        log("Trade processing error", symbol, repr(exc))


def ema(values, period):
    if not values:
        return []

    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]

    for value in values[1:]:
        result.append(
            alpha * float(value) +
            (1.0 - alpha) * result[-1]
        )

    return result


def calculate_macd(closes):
    if len(closes) < MIN_CANDLES_FOR_MACD:
        return None

    fast_line = ema(closes, MACD_FAST)
    slow_line = ema(closes, MACD_SLOW)

    macd_line = [
        fast_line[i] - slow_line[i]
        for i in range(len(closes))
    ]

    signal_line = ema(macd_line, MACD_SIGNAL)

    histogram = [
        macd_line[i] - signal_line[i]
        for i in range(len(closes))
    ]

    return {
        "macd": macd_line,
        "signal": signal_line,
        "histogram": histogram,
    }


def format_price(value):
    value = float(value)

    if value >= 1000:
        return f"{value:.4f}"

    if value >= 1:
        return f"{value:.6f}".rstrip("0").rstrip(".")

    return f"{value:.10f}".rstrip("0").rstrip(".")


def evaluate_signals(markets):
    found = []
    now_bucket = candle_bucket(utc_now().timestamp())

    for symbol in markets:
        item = ensure_market_state(symbol)

        with state_lock:
            candles = list(item.get("candles", []))
            last_signal = int(item.get("last_signal", 0))

        # MACD must use closed candles, not the live partial candle.
        if len(candles) < MIN_CANDLES_FOR_MACD:
            continue

        latest = candles[-1]
        previous = candles[-2]

        latest_time = int(latest["t"])

        # Avoid signals from stale candles.
        if now_bucket - latest_time > 2 * TIMEFRAME_SECONDS:
            continue

        closes = [float(candle["c"]) for candle in candles]
        macd = calculate_macd(closes)

        if macd is None:
            continue

        i = len(closes) - 1

        previous_macd = macd["macd"][i - 1]
        previous_signal = macd["signal"][i - 1]

        current_macd = macd["macd"][i]
        current_signal = macd["signal"][i]

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

        if direction is None:
            continue

        if latest_time <= last_signal:
            continue

        entry = float(latest["c"])

        if direction == "BUY":
            stop = entry * (1.0 - STOP_LOSS_PCT)
            target = entry * (1.0 + TAKE_PROFIT_PCT)
        else:
            stop = entry * (1.0 + STOP_LOSS_PCT)
            target = entry * (1.0 - TAKE_PROFIT_PCT)

        found.append({
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "target": target,
            "candle_time": latest_time,
            "histogram": macd["histogram"][i],
        })

    return found


def record_signals(found):
    messages = []

    for signal in found:
        symbol = signal["symbol"]
        direction = signal["direction"]
        candle_time = int(signal["candle_time"])

        item = ensure_market_state(symbol)

        with state_lock:
            if candle_time <= int(item.get("last_signal", 0)):
                continue

            item["last_signal"] = candle_time

        label = "🟢 BUY" if direction == "BUY" else "🔴 SELL"

        message = (
            f"⚡ ATI FUTURES V22 SIGNAL\n\n"
            f"💎 {symbol}\n"
            f"{label}\n"
            f"⏱️ Timeframe: 5M\n"
            f"📊 Strategy: MACD 12/26/9 crossover\n\n"
            f"📍 Entry reference: {format_price(signal['entry'])}\n"
            f"🛑 Suggested SL: {format_price(signal['stop'])}\n"
            f"🎯 Suggested TP: {format_price(signal['target'])}\n\n"
            f"📉 MACD histogram: {signal['histogram']:.8f}\n"
            f"🕐 Candle: {datetime.fromtimestamp(candle_time, timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n\n"
            f"🔒 REAL TRADING: OFF\n"
            f"⚠️ Signal only; not an order."
        )

        messages.append(message)

    return messages


def websocket_worker(symbol):
    result = runtime[symbol]

    def on_open(ws):
        result["connected"] = True
        result["opened_at"] = time.time()
        log("WS connected:", symbol)

        try:
            # Official Tabdeal broadcast feed uses plain-text symbol.
            ws.send(symbol)
        except Exception as exc:
            result["errors"] += 1
            log("Subscribe error:", symbol, repr(exc))

    def on_message(ws, message):
        try:
            data = json.loads(message)

            if isinstance(data, dict):
                trade = data.get("trade")

                if isinstance(trade, dict):
                    received_symbol = str(
                        trade.get("symbol",
