# ATI FUTURES V22.1
# Tabdeal Futures WebSocket Scanner
# MACD 12 / 26 / 9
# Signal-only version. Real order placement is NOT implemented.

import os
import sys
import json
import time
import threading
from datetime import datetime, timezone

import requests
import websocket


# =========================================================
# CONFIGURATION
# =========================================================

VERSION = "ATI FUTURES V22.1"

BASE_URL = "https://api1.tabdeal.org"
EXCHANGE_INFO_URL = BASE_URL + "/r/fapi/v1/exchangeInfo"

BROADCAST_URL = (
    "wss://api1.tabdeal.org/special_margin/broadcast/"
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

MAX_MARKETS = 75
RUN_SECONDS = 180

CANDLE_SECONDS = 300
MAX_CANDLES = 150
MIN_CANDLES_FOR_MACD = 35

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

ORDER_USDT = 2.0
LEVERAGE = 3

STOP_LOSS_PCT = 0.006
TAKE_PROFIT_PCT = 0.012

# IMPORTANT:
# This version does not contain a verified real-order function.
# Do not change this to True expecting it to place orders.
LIVE_TRADING = False

STATE_FILE = "ati_futures_state.json"

HTTP_TIMEOUT = 15
TELEGRAM_TIMEOUT = 15


# =========================================================
# NETWORK SETTINGS
# =========================================================

# GitHub Actions environments can contain proxy variables
# that interfere with the WebSocket connection.
for key in (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
):
    os.environ.pop(key, None)

os.environ["NO_PROXY"] = "*"
os.environ["no_proxy"] = "*"


# =========================================================
# GLOBAL STATE
# =========================================================

state_lock = threading.RLock()
stop_event = threading.Event()

runtime = {}
market_symbols = []

stats = {
    "markets": 0,
    "connected": 0,
    "ever_connected": 0,
    "messages": 0,
    "closed_candles": 0,
    "signals": 0,
    "errors": 0,
    "telegram_errors": 0,
}

started_at = time.time()


# =========================================================
# TIME / LOGGING
# =========================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_text():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


def log(message):
    print(f"[{utc_text()}] {message}", flush=True)


def safe_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# =========================================================
# TELEGRAM
# =========================================================

def telegram_send(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram credentials are missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=TELEGRAM_TIMEOUT,
        )

        if response.status_code != 200:
            log(
                "Telegram HTTP error: "
                + str(response.status_code)
                + " "
                + response.text[:300]
            )
            stats["telegram_errors"] += 1
            return False

        result = response.json()

        if not result.get("ok", False):
            log("Telegram API returned ok=false.")
            stats["telegram_errors"] += 1
            return False

        return True

    except Exception as exc:
        log(f"Telegram error: {exc}")
        stats["telegram_errors"] += 1
        return False


# =========================================================
# MARKET DISCOVERY
# =========================================================

def discover_markets():
    log("Discovering Tabdeal Futures markets...")

    response = requests.get(
        EXCHANGE_INFO_URL,
        timeout=HTTP_TIMEOUT,
        headers={"User-Agent": "ATI-Futures-Bot/22.1"},
    )

    response.raise_for_status()
    data = response.json()

    if isinstance(data, list):
        rows = data

    elif isinstance(data, dict):
        rows = data.get("symbols")

        if not isinstance(rows, list):
            nested = data.get("data")

            if isinstance(nested, dict):
                rows = nested.get("symbols")
            elif isinstance(nested, list):
                rows = nested

    else:
        rows = None

    if not isinstance(rows, list):
        raise RuntimeError(
            "exchangeInfo did not contain a symbols list."
        )

    eligible = []

    for item in rows:
        if not isinstance(item, dict):
            continue

        symbol = str(item.get("symbol", "")).strip()

        if not symbol.endswith("_USDT"):
            continue

        status = str(item.get("status", "TRADING")).upper()

        if status not in ("TRADING", "1", "OPEN", ""):
            continue

        quote = str(
            item.get("quoteAsset", item.get("quote", "USDT"))
        ).upper()

        if quote != "USDT":
            continue

        eligible.append(symbol)

    # Remove duplicates while preserving order.
    eligible = list(dict.fromkeys(eligible))
    eligible = eligible[:MAX_MARKETS]

    if not eligible:
        raise RuntimeError(
            "No eligible USDT Futures markets were found."
        )

    log(f"Eligible markets discovered: {len(eligible)}")
    return eligible


# =========================================================
# STATE STORAGE
# =========================================================

def new_market_state():
    return {
        "candles": [],
        "current": None,
        "last_closed_bucket": -1,
        "last_signal_bucket": -1,
        "connected": False,
        "ever_connected": False,
        "messages": 0,
        "errors": 0,
        "last_price": 0.0,
        "last_trade_time": 0.0,
    }


def load_state():
    if not os.path.exists(STATE_FILE):
        log("No previous state file; starting fresh.")
        return

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as file:
            saved = json.load(file)

        if not isinstance(saved, dict):
            log("State file format is invalid; starting fresh.")
            return

        loaded = 0

        with state_lock:
            for symbol, saved_state in saved.items():
                if not isinstance(saved_state, dict):
                    continue

                candles = saved_state.get("candles", [])

                if not isinstance(candles, list):
                    candles = []

                clean_candles = []

                for candle in candles[-MAX_CANDLES:]:
                    if not isinstance(candle, dict):
                        continue

                    try:
                        clean_candles.append({
                            "bucket": int(candle["bucket"]),
                            "open": float(candle["open"]),
                            "high": float(candle["high"]),
                            "low": float(candle["low"]),
                            "close": float(candle["close"]),
                            "volume": float(
                                candle.get("volume", 0.0)
                            ),
                        })
                    except (KeyError, TypeError, ValueError):
                        continue

                item = new_market_state()
                item["candles"] = clean_candles
                item["last_closed_bucket"] = int(
                    saved_state.get(
                        "last_closed_bucket",
                        clean_candles[-1]["bucket"]
                        if clean_candles else -1,
                    )
                )
                item["last_signal_bucket"] = int(
                    saved_state.get("last_signal_bucket", -1)
                )

                # Do not restore an incomplete candle across runs.
                item["current"] = None

                runtime[symbol] = item
                loaded += 1

        log(f"Loaded saved market states: {loaded}")

    except Exception as exc:
        log(f"State load error: {exc}")


def save_state():
    temp_file = STATE_FILE + ".tmp"

    try:
        output = {}

        with state_lock:
            for symbol, item in runtime.items():
                output[symbol] = {
                    "candles": item["candles"][-MAX_CANDLES:],
                    "last_closed_bucket": item[
                        "last_closed_bucket"
                    ],
                    "last_signal_bucket": item[
                        "last_signal_bucket"
                    ],
                }

        with open(temp_file, "w", encoding="utf-8") as file:
            json.dump(
                output,
                file,
                ensure_ascii=False,
                separators=(",", ":"),
            )

        os.replace(temp_file, STATE_FILE)
        log("State saved.")

    except Exception as exc:
        log(f"State save error: {exc}")


# =========================================================
# CANDLE BUILDING
# =========================================================

def candle_bucket(timestamp):
    return int(timestamp // CANDLE_SECONDS) * CANDLE_SECONDS


def close_candle_locked(symbol, item):
    candle = item.get("current")

    if not candle:
        return None

    bucket = int(candle["bucket"])

    if bucket <= item["last_closed_bucket"]:
        item["current"] = None
        return None

    closed = {
        "bucket": bucket,
        "open": float(candle["open"]),
        "high": float(candle["high"]),
        "low": float(candle["low"]),
        "close": float(candle["close"]),
        "volume": float(candle.get("volume", 0.0)),
    }

    item["candles"].append(closed)
    item["candles"] = item["candles"][-MAX_CANDLES:]
    item["last_closed_bucket"] = bucket
    item["current"] = None

    stats["closed_candles"] += 1

    log(
        f"CANDLE CLOSED {symbol} "
        f"close={closed['close']} "
        f"bucket={bucket}"
    )

    return closed


def process_trade(symbol, price, amount, timestamp):
    if price <= 0 or timestamp <= 0:
        return

    bucket = candle_bucket(timestamp)

    with state_lock:
        item = runtime.get(symbol)

        if item is None:
            item = new_market_state()
            runtime[symbol] = item

        item["last_price"] = price
        item["last_trade_time"] = timestamp
        item["messages"] += 1

        current = item.get("current")

        # Ignore delayed trades for a candle already closed.
        if bucket <= item["last_closed_bucket"]:
            return

        if current is None:
            item["current"] = {
                "bucket": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": max(amount, 0.0),
            }
            return

        current_bucket = int(current["bucket"])

        if bucket < current_bucket:
            return

        if bucket > current_bucket:
            close_candle_locked(symbol, item)

            # A gap does not create fake candles.
            # Start a candle only for the real incoming trade.
            if bucket <= item["last_closed_bucket"]:
                return

            item["current"] = {
                "bucket": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": max(amount, 0.0),
            }
            return

        current["high"] = max(current["high"], price)
        current["low"] = min(current["low"], price)
        current["close"] = price
        current["volume"] += max(amount, 0.0)


def close_expired_candles():
    now = time.time()
    now_bucket = candle_bucket(now)

    with state_lock:
        for symbol, item in runtime.items():
            current = item.get("current")

            if not current:
                continue

            current_bucket = int(current["bucket"])

            if current_bucket < now_bucket:
                close_candle_locked(symbol, item)


# =========================================================
# EMA / MACD
# =========================================================

def ema_series(values, period):
    if len(values) < period:
        return []

    alpha = 2.0 / (period + 1.0)
    result = []

    current = sum(values[:period]) / period
    result.extend([None] * (period - 1))
    result.append(current)

    for value in values[period:]:
        current = alpha * value + (1.0 - alpha) * current
        result.append(current)

    return result


def macd_series(closes):
    if len(closes) < MACD_SLOW + MACD_SIGNAL:
        return None

    fast = ema_series(closes, MACD_FAST)
    slow = ema_series(closes, MACD_SLOW)

    macd_line = []

    for index in range(len(closes)):
        if fast[index] is None or slow[index] is None:
            macd_line.append(None)
        else:
            macd_line.append(fast[index] - slow[index])

    valid_start = next(
        (
            i for i, value in enumerate(macd_line)
            if value is not None
        ),
        None,
    )

    if valid_start is None:
        return None

    valid_macd = macd_line[valid_start:]
    signal_valid = ema_series(valid_macd, MACD_SIGNAL)

    signal_line = [None] * valid_start + signal_valid

    if len(signal_line) != len(macd_line):
        return None

    return macd_line, signal_line


def evaluate_market(symbol):
    with state_lock:
        item = runtime.get(symbol)

        if item is None:
            return None

        candles = list(item["candles"])
        last_signal_bucket = item["last_signal_bucket"]

    if len(candles) < MIN_CANDLES_FOR_MACD:
        return None

    closes = [float(c["close"]) for c in candles]
    result = macd_series(closes)

    if result is None:
        return None

    macd_line, signal_line = result

    if len(closes) < 2:
        return None

    previous = len(closes) - 2
    current = len(closes) - 1

    values = (
        macd_line[previous],
        signal_line[previous],
        macd_line[current],
        signal_line[current],
    )

    if any(value is None for value in values):
        return None

    previous_macd, previous_signal, current_macd, current_signal = values

    direction = None

    # BUY: MACD crosses above signal line on a closed candle.
    if (
        previous_macd <= previous_signal
        and current_macd > current_signal
    ):
        direction = "BUY"

    # SELL: MACD crosses below signal line on a closed candle.
    elif (
        previous_macd >= previous_signal
        and current_macd < current_signal
    ):
        direction = "SELL"

    if direction is None:
        return None

    latest_candle = candles[-1]
    signal_bucket = int(latest_candle["bucket"])

    if signal_bucket <= last_signal_bucket:
        return None

    entry = closes[-1]

    if entry <= 0:
        return None

    if direction == "BUY":
        stop = entry * (1.0 - STOP_LOSS_PCT)
        target = entry * (1.0 + TAKE_PROFIT_PCT)
    else:
        stop = entry * (1.0 + STOP_LOSS_PCT)
        target = entry * (1.0 - TAKE_PROFIT_PCT)

    with state_lock:
        item = runtime.get(symbol)

        if item is None:
            return None

        # Recheck before recording the signal.
        if signal_bucket <= item["last_signal_bucket"]:
            return None

        item["last_signal_bucket"] = signal_bucket

    stats["signals"] += 1

    return {
        "symbol": symbol,
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "macd": current_macd,
        "signal": current_signal,
        "bucket": signal_bucket,
    }


def format_signal(signal):
    direction = signal["direction"]
    icon = "🟢" if direction == "BUY" else "🔴"

    return (
        f"⚡ ATI FUTURES SIGNAL V22.1\n\n"
        f"{icon} {direction}\n"
        f"💎 Market: {signal['symbol']}\n"
        f"⏱ Timeframe: 5 minutes\n"
        f"📌 Reference entry: {signal['entry']:.8g}\n"
        f"🛑 Suggested SL: {signal['stop']:.8g}\n"
        f"🎯 Suggested TP: {signal['target']:.8g}\n\n"
        f"📊 MACD: {signal['macd']:.8g}\n"
        f"📈 Signal line: {signal['signal']:.8g}\n\n"
        f"💵 Intended order size: {ORDER_USDT} USDT\n"
        f"⚙️ Configured leverage: {LEVERAGE}x\n"
        f"🔒 REAL TRADING: OFF\n\n"
        f"⚠️ Signal only; no order was submitted.\n"
        f"🕐 {utc_text()}"
    )


# =========================================================
# WEBSOCKET MESSAGE PARSING
# =========================================================

def parse_trade_message(message, expected_symbol):
    try:
        data = json.loads(message)
    except (TypeError, ValueError):
        return []

    if isinstance(data, list):
        rows = data

    elif isinstance(data, dict):
        trade = data.get("trade")

        if isinstance(trade, dict):
            rows = [trade]
        else:
            trades = data.get("trades")

            if isinstance(trades, list):
                rows = trades
            elif isinstance(trades, dict):
                rows = [trades]
            else:
                # Ignore acknowledgements and unrelated messages.
                return []

    else:
        return []

    parsed = []

    for trade in rows:
        if not isinstance(trade, dict):
            continue

        symbol = str(
            trade.get("symbol", expected_symbol)
        ).strip()

        if symbol != expected_symbol:
            continue

        price = safe_float(trade.get("price"), 0.0)
        amount = safe_float(
            trade.get("amount", trade.get("quantity", 0.0)),
            0.0,
        )

        raw_time = trade.get(
            "updated",
            trade.get("timestamp", trade.get("time")),
        )

        timestamp = parse_timestamp(raw_time)

        if timestamp <= 0:
            timestamp = time.time()

        if price > 0:
            parsed.append((symbol, price, amount, timestamp))

    return parsed


def parse_timestamp(value):
    if value is None:
        return 0.0

    if isinstance(value, (int, float)):
        number = float(value)

        if number > 1e12:
            number /= 1000.0

        if number > 0:
            return number

        return 0.0

    text_value = str(value).strip()

    if not text_value:
        return 0.0

    try:
        # Handle ISO timestamps ending in Z.
        if text_value.endswith("Z"):
            text_value = text_value[:-1] + "+00:00"

        parsed = datetime.fromisoformat(text_value)

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed.timestamp()

    except (ValueError, TypeError):
        try:
            number = float(text_value)

            if number > 1e12:
                number /= 1000.0

            return number if number > 0 else 0.0

        except (ValueError, TypeError):
            return 0.0


# =========================================================
# WEBSOCKET WORKER
# =========================================================

def websocket_worker(symbol):
    retry_delay = 2

    while not stop_event.is_set():
        result = runtime.get(symbol)

        if result is None:
            with state_lock:
                runtime[symbol] = new_market_state()

        def on_open(ws):
            with state_lock:
                item = runtime.get(symbol)

                if item is not None:
                    item["connected"] = True
                    item["ever_connected"] = True

            stats["connected"] += 1
            stats["ever_connected"] += 1

            log(f"WebSocket connected: {symbol}")

            try:
                # Tabdeal broadcast endpoint expects plain symbol text.
                ws.send(symbol)
            except Exception as exc:
                log(f"Subscription send error {symbol}: {exc}")

        def on_message(ws, message):
            stats["messages"] += 1

            trades = parse_trade_message(message, symbol)

            for received_symbol, price, amount, timestamp in trades:
                process_trade(
                    received_symbol,
                    price,
                    amount,
                    timestamp,
                )

        def on_error(ws, error):
            stats["errors"] += 1

            with state_lock:
                item = runtime.get(symbol)

                if item is not None:
                    item["errors"] += 1

            log(f"WebSocket error {symbol}: {error}")

        def on_close(ws, status_code, message):
            with state_lock:
                item = runtime.get(symbol)

                if item is not None:
                    item["connected"] = False

            log(f"WebSocket closed: {symbol}")

        try:
            ws = websocket.WebSocketApp(
                BROADCAST_URL,
                on_open=on_open,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
            )

            ws.run_forever(
                ping_interval=20,
                ping_timeout=10,
            )

        except Exception as exc:
            stats["errors"] += 1
            log(f"Worker exception {symbol}: {exc}")

        if stop_event.is_set():
            break

        time.sleep(retry_delay)
        retry_delay = min(retry_delay + 2, 10)


# =========================================================
# SIGNAL SCAN
# =========================================================

def scan_closed_candles():
    close_expired_candles()

    with state_lock:
        symbols = list(runtime.keys())

    for symbol in symbols:
        signal = evaluate_market(symbol)

        if signal is not None:
            message = format_signal(signal)

            log(
                f"SIGNAL {signal['direction']} "
                f"{signal['symbol']} "
                f"price={signal['entry']}"
            )

            telegram_send(message)


# =========================================================
# REPORT
# =========================================================

def make_report():
    with state_lock:
        symbols = list(runtime.keys())

        connected = sum(
            1 for item in runtime.values()
            if item.get("connected")
        )

        ever_connected = sum(
            1 for item in runtime.values()
            if item.get("ever_connected")
        )

        ready = sum(
            1 for item in runtime.values()
            if len(item.get("candles", []))
            >= MIN_CANDLES_FOR_MACD
        )

        candle_count = sum(
            len(item.get("candles", []))
            for item in runtime.values()
        )

        trade_count = sum(
            item.get("messages", 0)
            for item in runtime.values()
        )

    elapsed = time.time() - started_at

    return (
        f"💓 {VERSION}\n\n"
        f"🕐 {utc_text()}\n"
        f"📊 Markets: {len(symbols)}\n"
        f"🔌 Connected now: {connected}\n"
        f"✅ Connected at least once: {ever_connected}\n"
        f"📩 Raw messages: {stats['messages']}\n"
        f"📈 Parsed trades: {trade_count}\n"
        f"🕯 Closed candles stored: {candle_count}\n"
        f"🧠 Markets MACD-ready: {ready}\n"
        f"⚡ Signals this run: {stats['signals']}\n"
        f"❌ WebSocket errors: {stats['errors']}\n"
        f"📨 Telegram errors: {stats['telegram_errors']}\n"
        f"⏱ Runtime: {elapsed:.1f}s\n\n"
        f"💵 Order size setting: {ORDER_USDT} USDT\n"
        f"⚙️ Leverage setting: {LEVERAGE}x\n"
        f"🔒 REAL TRADING: OFF\n\n"
        f"⚠️ Signal scanner only; no real orders are placed."
    )


# =========================================================
# MAIN
# =========================================================

def main():
    log("=" * 55)
    log(f"Starting {VERSION}")
    log(f"Python: {sys.version.split()[0]}")
    log(f"REAL TRADING: {LIVE_TRADING}")
    log("=" * 55)

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        log(
            "WARNING: TELEGRAM_BOT_TOKEN or "
            "TELEGRAM_CHAT_ID is missing."
        )

    telegram_send(
        f"🚀 {VERSION}\n"
        f"Tabdeal Futures scanner started.\n"
        f"Markets: discovering...\n"
        f"Time: {utc_text()}\n"
        f"REAL TRADING: OFF"
    )

    try:
        symbols = discover_markets()
    except Exception as exc:
        stats["errors"] += 1
        log(f"MARKET DISCOVERY ERROR: {exc}")

        telegram_send(
            f"❌ {VERSION}\n"
            f"MARKET DISCOVERY ERROR\n\n"
            f"{str(exc)[:1000]}\n\n"
            f"Time: {utc_text()}"
        )
        raise

    global market_symbols
    market_symbols = symbols
    stats["markets"] = len(symbols)

    load_state()

    with state_lock:
        for symbol in symbols:
            if symbol not in runtime:
                runtime[symbol] = new_market_state()

    telegram_send(
        f"📡 {VERSION}\n"
        f"Markets discovered: {len(symbols)}\n"
        f"WebSocket scanner starting.\n"
        f"Time: {utc_text()}"
    )

    threads = []

    for symbol in symbols:
        if stop_event.is_set():
            break

        thread = threading.Thread(
            target=websocket_worker,
            args=(symbol,),
            daemon=True,
            name=f"ws-{symbol}",
        )

        thread.start()
        threads.append(thread)

        # Avoid opening all sockets in the exact same instant.
        time.sleep(0.03)

    end_time = time.time() + RUN_SECONDS
    last_report = 0
    last_save = 0

    try:
        while time.time() < end_time:
            scan_closed_candles()

            now = time.time()

            if now - last_save >= 20:
                save_state()
                last_save = now

            if now - last_report >= 60:
                log(make_report())
                last_report = now

            time.sleep(2)

    except KeyboardInterrupt:
        log("Shutdown requested.")

    finally:
        stop_event.set()

        # Give workers a short time to exit.
        for thread in threads:
            thread.join(timeout=1)

        scan_closed_candles()
        save_state()

        report = make_report()
        log(report)
        telegram_send(report)

        log(f"{VERSION} finished.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"FATAL ERROR: {type(exc).__name__}: {exc}")

        telegram_send(
            f"❌ {VERSION} FATAL ERROR\n\n"
            f"{type(exc).__name__}: {str(exc)[:1000]}\n\n"
            f"Time: {utc_text()}"
        )

        raise
