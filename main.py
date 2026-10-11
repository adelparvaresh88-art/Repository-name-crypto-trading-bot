import os
import sys
import json
import time
import math
import threading
from datetime import datetime, timezone

import requests
import websocket


# =========================================================
# ATI FUTURES V22.1
# TABDEAL FUTURES | LIVE TRADES | 5M MACD
# SIGNAL ONLY - REAL ORDERS DISABLED
# =========================================================

VERSION = "ATI FUTURES V22.1"

BASE_URL = "https://api1.tabdeal.org"
BROADCAST_URL = (
    "wss://api1.tabdeal.org/special_margin/broadcast/"
)

LIVE_TRADING = False

MAX_MARKETS = 75
SCAN_SECONDS = 180

TIMEFRAME_SECONDS = 300
MAX_CANDLES = 150
MIN_CANDLES_FOR_MACD = 35

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

STOP_LOSS_PCT = 0.006
TAKE_PROFIT_PCT = 0.012

STATE_FILE = "ati_futures_state.json"

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


# Remove inherited proxy settings that can break WebSocket.
for key in list(os.environ):
    if key.lower() in (
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "ws_proxy",
        "wss_proxy",
    ):
        os.environ.pop(key, None)

os.environ["NO_PROXY"] = (
    "api1.tabdeal.org,localhost,127.0.0.1"
)
os.environ["no_proxy"] = (
    "api1.tabdeal.org,localhost,127.0.0.1"
)


# RLock avoids deadlocks when candle functions call
# other functions that also need the state lock.
state_lock = threading.RLock()
print_lock = threading.Lock()

state = {}
runtime = {}

socket_apps = []
worker_threads = []


def log(*args):
    with print_lock:
        print(*args, flush=True)


def utc_now():
    return datetime.now(timezone.utc)


def utc_text():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("WARNING: Telegram secrets are missing.")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_TOKEN}/sendMessage"
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

        if not response.ok:
            log(
                "Telegram HTTP error:",
                response.status_code,
                response.text[:300],
            )
            return False

        return True

    except Exception as exc:
        log("Telegram error:", repr(exc))
        return False


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
            "exchangeInfo symbols is not a list"
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

    markets = sorted(set(markets))

    if not markets:
        raise RuntimeError(
            "No eligible USDT futures markets found"
        )

    return markets[:MAX_MARKETS]


def load_state():
    global state

    if not os.path.exists(STATE_FILE):
        state = {}
        log("No saved candle history; starting fresh.")
        return

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            loaded = json.load(file)

        if not isinstance(loaded, dict):
            raise ValueError("Saved state is not a dictionary")

        state = loaded

        # Repair malformed market entries.
        for symbol, item in list(state.items()):
            if not isinstance(item, dict):
                state.pop(symbol, None)
                continue

            if not isinstance(item.get("candles"), list):
                item["candles"] = []

            if not isinstance(item.get("current"), dict):
                item["current"] = None

            item.setdefault("last_signal", 0)

        log("Saved state loaded:", len(state), "markets")

    except Exception as exc:
        log("State loading error:", repr(exc))
        state = {}


def save_state():
    temporary = STATE_FILE + ".tmp"

    try:
        with state_lock:
            snapshot = json.loads(json.dumps(state))

        with open(
            temporary,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                snapshot,
                file,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        os.replace(temporary, STATE_FILE)

        log("State saved:", len(state), "markets")
        return True

    except Exception as exc:
        log("State saving error:", repr(exc))
        return False


def ensure_market_state(symbol):
    with state_lock:
        item = state.get(symbol)

        if not isinstance(item, dict):
            item = {
                "candles": [],
                "current": None,
                "last_signal": 0,
            }
            state[symbol] = item

        if not isinstance(item.get("candles"), list):
            item["candles"] = []

        if not isinstance(item.get("current"), dict):
            item["current"] = None

        item.setdefault("last_signal", 0)

        return item


def parse_trade_time(value):
    try:
        if value is None:
            return utc_now().timestamp()

        if isinstance(value, (int, float)):
            if value > 10_000_000_000:
                value = value / 1000.0

            return float(value)

        text = str(value).strip()

        if text.endswith("Z"):
            text = text[:-1] + "+00:00"

        parsed = datetime.fromisoformat(text)

        if parsed.tzinfo is None:
            parsed = parsed.replace(
                tzinfo=timezone.utc
            )

        return parsed.timestamp()

    except Exception:
        log("Invalid trade timestamp:", repr(value))
        return None


def candle_bucket(timestamp):
    return (
        int(timestamp // TIMEFRAME_SECONDS)
        * TIMEFRAME_SECONDS
    )


def new_candle(bucket, price, amount):
    return {
        "t": int(bucket),
        "o": float(price),
        "h": float(price),
        "l": float(price),
        "c": float(price),
        "v": float(amount),
    }


def append_closed_candle(symbol, candle):
    item = ensure_market_state(symbol)
    candles = item["candles"]

    if not candle:
        return

    bucket = int(candle["t"])

    if candles:
        last_bucket = int(candles[-1]["t"])

        if bucket <= last_bucket:
            return

    candles.append(candle)

    if len(candles) > MAX_CANDLES:
        del candles[:-MAX_CANDLES]

    log(
        "Candle closed:",
        symbol,
        datetime.fromtimestamp(
            bucket,
            timezone.utc,
        ).strftime("%H:%M UTC"),
        "close=",
        candle["c"],
        "volume=",
        candle["v"],
    )


def process_trade(symbol, trade):
    try:
        price = float(trade.get("price", 0))
        amount = float(trade.get("amount", 0))

        if not math.isfinite(price) or price <= 0:
            return

        if not math.isfinite(amount) or amount < 0:
            amount = 0.0

        timestamp = parse_trade_time(
            trade.get("updated")
        )

        if timestamp is None:
            return

        bucket = candle_bucket(timestamp)

        with state_lock:
            item = ensure_market_state(symbol)
            current = item.get("current")

            if current is None:
                item["current"] = new_candle(
                    bucket,
                    price,
                    amount,
                )
                return

            current_bucket = int(current["t"])

            # Ignore late or out-of-order trades.
            if bucket < current_bucket:
                return

            if bucket == current_bucket:
                current["h"] = max(
                    float(current["h"]),
                    price,
                )

                current["l"] = min(
                    float(current["l"]),
                    price,
                )

                current["c"] = price

                current["v"] = (
                    float(current.get("v", 0))
                    + amount
                )

                return

            # A newer 5-minute interval arrived.
            append_closed_candle(symbol, current)

            # Do not fabricate candles for intervals
            # in which no trade data was received.
            item["current"] = new_candle(
                bucket,
                price,
                amount,
            )

    except Exception as exc:
        log(
            "Trade processing error:",
            symbol,
            repr(exc),
        )


def close_expired_candles():
    now_bucket = candle_bucket(
        utc_now().timestamp()
    )

    with state_lock:
        for symbol in list(state.keys()):
            item = ensure_market_state(symbol)
            current = item.get("current")

            if not current:
                continue

            bucket = int(current["t"])

            if bucket < now_bucket:
                append_closed_candle(
                    symbol,
                    current,
                )
                item["current"] = None


def ema(values, period):
    if not values:
        return []

    alpha = 2.0 / (period + 1.0)

    output = [float(values[0])]

    for value in values[1:]:
        output.append(
            alpha * float(value)
            + (1.0 - alpha) * output[-1]
        )

    return output


def calculate_macd(closes):
    if len(closes) < MIN_CANDLES_FOR_MACD:
        return None

    fast = ema(closes, MACD_FAST)
    slow = ema(closes, MACD_SLOW)

    macd_line = [
        fast[i] - slow[i]
        for i in range(len(closes))
    ]

    signal_line = ema(
        macd_line,
        MACD_SIGNAL,
    )

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

    for symbol in markets:
        with state_lock:
            item = ensure_market_state(symbol)
            candles = list(item["candles"])
            last_signal = int(item.get("last_signal", 0))

        if len(candles) < MIN_CANDLES_FOR_MACD:
            continue

        closes = [
            float(candle["c"])
            for candle in candles
        ]

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

        candle_time = int(candles[-1]["t"])

        if candle_time <= last_signal:
            continue

        # The latest candle must be closed and reasonably fresh.
        now_bucket = candle_bucket(
            utc_now().timestamp()
        )

        if candle_time >= now_bucket:
            continue

        if now_bucket - candle_time > 2 * TIMEFRAME_SECONDS:
            continue

        entry = float(candles[-1]["c"])

        if direction == "BUY":
            stop = entry * (1 - STOP_LOSS_PCT)
            target = entry * (1 + TAKE_PROFIT_PCT)
        else:
            stop = entry * (1 + STOP_LOSS_PCT)
            target = entry * (1 - TAKE_PROFIT_PCT)

        found.append({
            "symbol": symbol,
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "target": target,
            "candle_time": candle_time,
            "histogram": macd["histogram"][i],
        })

    return found


def make_signal_message(signal):
    direction = signal["direction"]

    label = (
        "🟢 BUY"
        if direction == "BUY"
        else "🔴 SELL"
    )

    candle_text = datetime.fromtimestamp(
        signal["candle_time"],
        timezone.utc,
    ).strftime("%Y-%m-%d %H:%M UTC")

    return (
        "⚡ ATI FUTURES V22.1 SIGNAL\n\n"
        f"💎 {signal['symbol']}\n"
        f"{label}\n"
        "⏱️ Timeframe: 5M\n"
        "📊 Strategy: MACD 12/26/9\n\n"
        f"📍 Entry reference: "
        f"{format_price(signal['entry'])}\n"
        f"🛑 Suggested SL: "
        f"{format_price(signal['stop'])}\n"
        f"🎯 Suggested TP: "
        f"{format_price(signal['target'])}\n\n"
        f"📉 MACD histogram: "
        f"{signal['histogram']:.8f}\n"
        f"🕐 Candle: {candle_text}\n\n"
        "🔒 REAL TRADING: OFF\n"
        "⚠️ Signal only; no order was placed."
    )


def send_new_signals(markets):
    found = evaluate_signals(markets)
    sent = 0

    for signal in found:
        symbol = signal["symbol"]
        candle_time = int(signal["candle_time"])

        with state_lock:
            item = ensure_market_state(symbol)
