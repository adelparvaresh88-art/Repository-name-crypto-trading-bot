import os
import time
import json
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V40.1.2
# CLEAN BREAKOUT + RETEST
# EARLY ENTRY
# ANTI-FAKE BREAKOUT
# ANTI-CHASE
# PAPER TRACKING
# DEEP SCAN TOP 10
# TELEGRAM SAFE LOOP
# ============================================================

VERSION = "V40.1.2"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

MAX_MARKETS = 1000

LIGHT_TRADE_LIMIT = 250
DEEP_TRADE_LIMIT = 1000

# IMPORTANT: exactly 10 coins for deep scan
DEEP_SCAN_COUNT = 10

MAX_WORKERS = 24
REQUEST_TIMEOUT = 15

SCAN_INTERVAL = 300

PAPER_TRACKING = True
REAL_ORDERS = False

STATE_FILE = "active_signal.json"

# ============================================================
# SIGNAL SETTINGS
# ============================================================

CONFIRMED_MIN_SCORE = 16
EARLY_MIN_SCORE = 12
WATCH_MIN_SCORE = 11

CHASE_5M_LIMIT = 3.0

SL_PERCENT = 0.50
TP1_PERCENT = 0.75
TP2_PERCENT = 1.25

MAX_OPEN_PAPER = 20

DUPLICATE_COOLDOWN = 30 * 60


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update({
    "User-Agent": "ATI-Crypto-Bot/40.1.2"
})


# ============================================================
# BASIC HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_text():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def request_json(path, params=None):
    url = BASE_URL + path

    try:
        response = SESSION.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()

        return response.json()

    except Exception:
        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(text):
    """
    Telegram is isolated from the scanner.
    A Telegram failure must NEVER stop the bot.
    """

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }

    try:
        response = SESSION.post(
            url,
            json=payload,
            timeout=15
        )

        return response.ok

    except Exception:
        return False


# ============================================================
# START MESSAGE
# ============================================================

def send_start_message():

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: {TIMEFRAME}\n"
        f"🕯 CLOSED CANDLE: YES\n"
        f"📊 PAPER TRACKING: ON\n"
        f"🔧 REAL ORDERS: DISABLED\n\n"
        f"🕐 {utc_text()}"
    )

    send_telegram(message)


# ============================================================
# MARKET DATA
# ============================================================

def get_markets():

    data = request_json(
        "/r/api/v1/exchangeInfo"
    )

    if data is None:
        return []

    symbols = []

    if isinstance(data, dict):

        if isinstance(data.get("symbols"), list):
            symbols = data["symbols"]

        elif isinstance(data.get("data"), list):
            symbols = data["data"]

        elif isinstance(data.get("data"), dict):

            if isinstance(data["data"].get("symbols"), list):
                symbols = data["data"]["symbols"]

    elif isinstance(data, list):
        symbols = data

    markets = []

    for item in symbols:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("name")
            or item.get("pair")
        )

        if not symbol:
            continue

        symbol = str(symbol).upper()

        if not symbol.endswith("USDT"):
            continue

        status = str(
            item.get("status", "TRADING")
        ).upper()

        if status not in (
            "TRADING",
            "1",
            "ACTIVE",
            "ENABLED"
        ):
            continue

        markets.append(symbol)

    markets = sorted(set(markets))

    return markets[:MAX_MARKETS]


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol, limit):

    data = request_json(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": limit
        }
    )

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        if isinstance(data.get("data"), list):
            return data["data"]

        if isinstance(data.get("trades"), list):
            return data["trades"]

    return []


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = safe_float(
        item.get("price")
        or item.get("p")
    )

    qty = safe_float(
        item.get("qty")
        or item.get("quantity")
        or item.get("q")
    )

    timestamp = (
        item.get("time")
        or item.get("timestamp")
        or item.get("T")
    )

    timestamp = safe_float(timestamp)

    if timestamp <= 0:
        timestamp = time.time() * 1000

    if timestamp < 10_000_000_000:
        timestamp *= 1000

    if price <= 0:
        return None

    return {
        "price": price,
        "qty": qty,
        "time": timestamp
    }


# ============================================================
# CANDLE BUILDER
# ============================================================

def build_candles(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade:
            parsed.append(trade)

    if not parsed:
        return []

    candles = {}

    interval_ms = 5 * 60 * 1000

    for trade in parsed:

        bucket = (
            int(trade["time"]) // interval_ms
        ) * interval_ms

        price = trade["price"]
        qty = trade["qty"]

        if bucket not in candles:

            candles[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty
            }

        else:

            candle = candles[bucket]

            candle["high"] = max(
                candle["high"],
                price
            )

            candle["low"] = min(
                candle["low"],
                price
            )

            candle["close"] = price

            candle["volume"] += qty

    result = sorted(
        candles.values(),
        key=lambda x: x["time"]
    )

    # Remove current unfinished candle
    if result:

        current_bucket = (
            int(time.time() * 1000)
            // interval_ms
        ) * interval_ms

        if result[-1]["time"] >= current_bucket:
            result = result[:-1]

    return result


# ============================================================
# PRICE
# ============================================================

def get_current_price(symbol):

    data = request_json(
        "/r/api/v1/depth",
        {
            "symbol": symbol
        }
    )

    if not isinstance(data, dict):
        return 0.0

    bid = safe_float(
        data.get("bidPrice")
        or data.get("bid")
    )

    ask = safe_float(
        data.get("askPrice")
        or data.get("ask")
    )

    if bid > 0 and ask > 0:
        return (bid + ask) / 2

    if bid > 0:
        return bid

    if ask > 0:
        return ask

    return safe_float(
        data.get("lastPrice")
        or data.get("price")
    )


# ============================================================
# MARKET QUICK ANALYSIS
# ============================================================

def quick_market(symbol):

    try:

        trades = get_trades(
            symbol,
            LIGHT_TRADE_LIMIT
        )

        candles = build_candles(trades)

        if len(candles) < 8:
            return None

        last = candles[-1]
        prev = candles[-2]

        price = last["close"]

        change_5m = 0.0

        if prev["close"] > 0:
            change_5m = (
                (last["close"] - prev["close"])
                / prev["close"]
            ) * 100

        return {
            "symbol": symbol,
            "price": price,
            "change_5m": change_5m
        }

    except Exception:
        return None


# ============================================================
# RESISTANCE
# ============================================================

def get_resistance(candles):

    if len(candles) < 8:
        return 0.0

    recent = candles[-8:-1]

    return max(
        c["high"]
        for c in recent
    )


# ============================================================
# DEEP SIGNAL ANALYSIS
# ============================================================

def analyze_symbol(symbol):

    try:

        trades = get_trades(
            symbol,
            DEEP_TRADE_LIMIT
        )

        candles = build_candles(trades)

        if len(candles) < 20:
            return None

        last = candles[-1]
        prev = candles[-2]

        price = last["close"]

        resistance = get_resistance(candles)

        if resistance <= 0:
            return None

        score = 0
        reasons = []

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        change_5m = 0.0

        if prev["close"] > 0:

            change_5m = (
                (price - prev["close"])
                / prev["close"]
            ) * 100

        if change_5m > 0:
            score += 2
            reasons.append("5M UP")

        if change_5m > 0.5:
            score += 2
            reasons.append("MOMENTUM")

        # ----------------------------------------------------
        # STRUCTURE
        # ----------------------------------------------------

        highs = [
            c["high"]
            for c in candles[-6:]
        ]

        lows = [
            c["low"]
            for c in candles[-6:]
        ]

        higher_highs = (
            highs[-1] > highs[-2]
            and highs[-2] >= highs[-3]
        )

        higher_lows = (
            lows[-1] > lows[-2]
            and lows[-2] >= lows[-3]
        )

        if higher_highs:
            score += 3
            reasons.append("HIGHER HIGH")

        if higher_lows:
            score += 3
            reasons.append("HIGHER LOW")

        # ----------------------------------------------------
        # BREAKOUT
        # ----------------------------------------------------

        breakout = (
            price > resistance
        )

        if breakout:

            score += 5
            reasons.append("BREAKOUT")

        # ----------------------------------------------------
        # RETEST / HOLD
        # ----------------------------------------------------

        if breakout:

            distance = (
                (price - resistance)
                / resistance
            ) * 100

            if -0.5 <= distance <= 1.5:

                score += 2
                reasons.append("RETEST/HOLD")

        # ----------------------------------------------------
        # ANTI-CHASE
        # ----------------------------------------------------

        if change_5m > CHASE_5M_LIMIT:

            score -= 5
            reasons.append("CHASE BLOCK")

        # ----------------------------------------------------
        # BODY QUALITY
        # ----------------------------------------------------

        candle_range = (
            last["high"] - last["low"]
        )

        if candle_range > 0:

            body = abs(
                last["close"] - last["open"]
            )

            body_ratio = (
                body / candle_range
            )

            if body_ratio >= 0.55:

                score += 2
                reasons.append("STRONG BODY")

        # ----------------------------------------------------
        # SIGNAL TYPE
        # ----------------------------------------------------

        signal = "NONE"

        if score >= CONFIRMED_MIN_SCORE:
            signal = "CONFIRMED BUY"

        elif score >= EARLY_MIN_SCORE:
            signal = "EARLY ENTRY"

        elif score >= WATCH_MIN_SCORE:
            signal = "WATCH"

        # ----------------------------------------------------
        # LEVELS
        # ----------------------------------------------------

        sl = price * (
            1 - SL_PERCENT / 100
        )

        tp1 = price * (
            1 + TP1_PERCENT / 100
        )

        tp2 = price * (
            1 + TP2_PERCENT / 100
        )

        return {
            "symbol": symbol,
            "signal": signal,
            "score": score,
            "price": price,
            "change_5m": change_5m,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "reasons": reasons
        }

    except Exception:

        return None


# ============================================================
# LIGHT SCAN
# ============================================================

def light_scan(markets):

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                quick_market,
                symbol
            ): symbol

            for symbol in markets
        }

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                continue

    results.sort(
        key=lambda x: x["change_5m"],
        reverse=True
    )

    return results[:DEEP_SCAN_COUNT]


# ============================================================
# DEEP SCAN
# ============================================================

def deep_scan(candidates):

    results = []

    with ThreadPoolExecutor(
        max_workers=min(
            MAX_WORKERS,
            DEEP_SCAN_COUNT
        )
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                item["symbol"]
            ): item["symbol"]

            for item in candidates
        }

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception:
                continue

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results


# ============================================================
# STATE
# ============================================================

def load_state():

    try:

        if not os.path.exists(STATE_FILE):
            return {
                "open": [],
                "history": []
            }

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        if not isinstance(data, dict):
            return {
                "open": [],
                "history": []
            }

        data.setdefault("open", [])
        data.setdefault("history", [])

        return data

    except Exception:

        return {
            "open": [],
            "history": []
        }


def save_state(state):

    try:

        temp_file = STATE_FILE + ".tmp"

        with open(
            temp_file,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                state,
                f,
                indent=2
            )

        os.replace(
            temp_file,
            STATE_FILE
        )

    except Exception:
        pass


# ============================================================
# PAPER REGISTER
# ============================================================

def register_signal(signal, state):

    if signal["signal"] not in (
        "CONFIRMED BUY",
        "EARLY ENTRY"
    ):
        return False

    if len(state["open"]) >= MAX_OPEN_PAPER:
        return False

    symbol = signal["symbol"]

    now = time.time()

    for item in state["open"]:

        if item.get("symbol") == symbol:
            return False

    for item in state["history"]:

        if item.get("symbol") != symbol:
            continue

        if now - item.get("time", 0) < DUPLICATE_COOLDOWN:
            return False

    position = {
        "symbol": symbol,
        "entry": signal["price"],
        "sl": signal["sl"],
        "tp1": signal["tp1"],
        "tp2": signal["tp2"],
        "tp1_hit": False,
        "time": now,
        "signal": signal["signal"],
        "score": signal["score"]
    }

    state["open"].append(position)

    save_state(state)

    return True


# ============================================================
# PAPER POSITION UPDATE
# ============================================================

def update_open_positions(state):

    changed = False
    tp1_events = 0

    for position in list(state["open"]):

        symbol = position.get("symbol")

        price = get_current_price(symbol)

        if price <= 0:
            continue

        entry = safe_float(
            position.get("entry")
        )

        sl = safe_float(
            position.get("sl")
        )

        tp1 = safe_float(
            position.get("tp1")
        )

        tp2 = safe_float(
            position.get("tp2")
        )

        # ----------------------------------------------------
        # STOP LOSS
        # ----------------------------------------------------

        if price <= sl:

            position["result"] = "SL"
            position["exit"] = price
            position["close_time"] = time.time()

            state["history"].append(position)
            state["open"].remove(position)

            changed = True

            continue

        # ----------------------------------------------------
        # TP2
        # ----------------------------------------------------

        if price >= tp2:

            position["result"] = "TP2"
            position["exit"] = price
            position["close_time"] = time.time()

            state["history"].append(position)
            state["open"].remove(position)

            changed = True

            continue

        # ----------------------------------------------------
        # TP1
        # ----------------------------------------------------

        if price >= tp1 and not position.get("tp1_hit"):

            position["tp1_hit"] = True

            tp1_events += 1

            changed = True

    if changed:
        save_state(state)

    return tp1_events


# ============================================================
# STATS
# ============================================================

def get_stats(state):

    history = state.get(
        "history",
        []
    )

    total = len(history)

    tp2 = sum(
        1
        for x in history
        if x.get("result") == "TP2"
    )

    sl = sum(
        1
        for x in history
        if x.get("result") == "SL"
    )

    open_count = len(
        state.get("open", [])
    )

    closed = tp2 + sl

    if closed > 0:

        win_rate = (
            tp2 / closed
        ) * 100

    else:

        win_rate = 0.0

    return {
        "trades": total,
        "tp2": tp2,
        "sl": sl,
        "open": open_count,
        "win_rate": win_rate
    }


# ============================================================
# RESULT FORMAT
# ============================================================

def format_coin(item, number):

    symbol = item["symbol"]

    score = item["score"]

    price = item["price"]

    change = item["change_5m"]

    sl = item["sl"]

    tp1 = item["tp1"]

    tp2 = item["tp2"]

    signal = item["signal"]

    return (
        f"#{number}\n"
        f"🪙 {symbol}\n"
        f"⭐ SCORE: {score}\n"
        f"📈 5M: {change:+.2f}%\n"
        f"💰 PRICE: {price:.8f}\n"
        f"🛑 SL: {sl:.8f}\n"
        f"🎯 TP1: {tp1:.8f}\n"
        f"🎯 TP2: {tp2:.8f}\n"
        f"🔎 {', '.join(item['reasons'][:5])}\n"
    )


# ============================================================
# TELEGRAM RESULT MESSAGE
# ============================================================

def build_result_message(
    markets_count,
    candidates,
    results,
    state,
    scan_seconds,
    tp1_events
):

    confirmed = [
        x for x in results
        if x["signal"] == "CONFIRMED BUY"
    ]

    early = [
        x for x in results
        if x["signal"] == "EARLY ENTRY"
    ]

    watch = [
        x for x in results
        if x["signal"] == "WATCH"
    ]

    stats = get_stats(state)

    parts = []

    parts.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    parts.append(
        "🚀 CLEAN BREAKOUT + RETEST"
    )

    parts.append(
        "🎯 EARLY ENTRY"
    )

    parts.append(
        "🛡 ANTI-FAKE BREAKOUT"
    )

    parts.append(
        "🚫 ANTI-CHASE"
    )

    parts.append("")

    parts.append(
        "📡 TABDEAL API: OK"
    )

    parts.append(
        f"📊 USDT MARKETS: {markets_count}"
    )

    parts.append(
        f"🎯 DEEP SCAN: TOP {DEEP_SCAN_COUNT}"
    )

    parts.append(
        f"⏱ TIMEFRAME: {TIMEFRAME}"
    )

    parts.append(
        f"🕐 {utc_text()}"
    )

    parts.append("━━━━━━━━━━━━━━━━━━")

    parts.append("🟢 CONFIRMED BUY")

    if confirmed:

        for i, item in enumerate(
            confirmed[:5],
            1
        ):
            parts.append(
                format_coin(item, i)
            )

    else:

        parts.append("NONE")

    parts.append("━━━━━━━━━━━━━━━━━━")

    parts.append("⚡ EARLY ENTRY")

    if early:

        for i, item in enumerate(
            early[:5],
            1
        ):
            parts.append(
                format_coin(item, i)
            )

    else:

        parts.append("NONE")

    parts.append("━━━━━━━━━━━━━━━━━━")

    parts.append("🟡 WATCH")

    if watch:

        for i, item in enumerate(
            watch[:5],
            1
        ):
            parts.append(
                format_coin(item, i)
            )

    else:

        parts.append("NONE")

    parts.append("━━━━━━━━━━━━━━━━━━")

    parts.append("📊 PAPER STATS")

    parts.append(
        f"Trades: {stats['trades']} | "
        f"TP2: {stats['tp2']} | "
        f"SL: {stats['sl']} | "
        f"OPEN: {stats['open']}"
    )

    parts.append(
        f"TP1 events: {tp1_events}"
    )

    parts.append(
        f"Win Rate: {stats['win_rate']:.1f}%"
    )

    parts.append(
        f"⏱ Scan time: {scan_seconds:.1f} sec"
    )

    parts.append(
        "🔧 REAL ORDERS: DISABLED"
    )

    return "\n".join(parts)


# ============================================================
# ONE COMPLETE SCAN
# ============================================================

def run_scan():

    scan_start = time.time()

    # --------------------------------------------------------
    # MARKET LIST
    # --------------------------------------------------------

    markets = get_markets()

    if not markets:

        message = (
            f"⚠️ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET DATA ERROR\n\n"
            f"🕐 {utc_text()}"
        )

        send_telegram(message)

        return

    # --------------------------------------------------------
    # PAPER STATE
    # --------------------------------------------------------

    state = load_state()

    tp1_events = 0

    if PAPER_TRACKING:

        try:
            tp1_events = update_open_positions(
                state
            )
        except Exception:
            tp1_events = 0

    # --------------------------------------------------------
    # LIGHT SCAN
    # --------------------------------------------------------

    candidates = light_scan(markets)

    # --------------------------------------------------------
    # IMPORTANT:
    # EVEN IF LIGHT SCAN FAILS,
    # TELEGRAM RESULT MUST STILL BE SENT.
    # --------------------------------------------------------

    if not candidates:

        scan_seconds = (
            time.time() - scan_start
        )

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: {len(markets)}\n"
            f"🎯 DEEP SCAN: TOP {DEEP_SCAN_COUNT}\n\n"
            f"⚠️ NO CANDIDATES FROM LIGHT SCAN\n\n"
            f"📊 PAPER STATS\n"
            f"Trades: {len(state['history'])} | "
            f"OPEN: {len(state['open'])}\n"
            f"⏱ Scan time: {scan_seconds:.1f} sec\n"
            f"🔧 REAL ORDERS: DISABLED\n\n"
            f"🕐 {utc_text()}"
        )

        send_telegram(message)

        return

    # --------------------------------------------------------
    # DEEP SCAN
    # --------------------------------------------------------

    try:

        results = deep_scan(
            candidates[:DEEP_SCAN_COUNT]
        )

    except Exception:

        results = []

    # --------------------------------------------------------
    # REGISTER PAPER SIGNALS
    # --------------------------------------------------------

    if PAPER_TRACKING:

        for item in results:

            try:
                register_signal(
                    item,
                    state
                )
            except Exception:
                continue

    # --------------------------------------------------------
    # FINAL TELEGRAM MESSAGE
    # --------------------------------------------------------

    scan_seconds = (
        time.time() - scan_start
    )

    message = build_result_message(
        markets_count=len(markets),
        candidates=candidates,
        results=results,
        state=state,
        scan_seconds=scan_seconds,
        tp1_events=tp1_events
    )

    # THIS SEND IS PROTECTED.
    # THE LOOP WILL CONTINUE EVEN IF TELEGRAM FAILS.

    send_telegram(message)


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    send_start_message()

    # Small delay so the startup message reaches Telegram
    time.sleep(2)

    while True:

        cycle_start = time.time()

        try:

            run_scan()

        except Exception as error:

            # Never allow an unexpected scan exception
            # to permanently kill the bot.

            error_message = (
                f"⚠️ ATI CRYPTO BOT {VERSION}\n\n"
                f"❌ SCAN ERROR\n"
                f"🔄 BOT WILL CONTINUE\n\n"
                f"🕐 {utc_text()}"
            )

            send_telegram(
                error_message
            )

        elapsed = (
            time.time() - cycle_start
        )

        sleep_time = max(
            5,
            SCAN_INTERVAL - elapsed
        )

        time.sleep(
            sleep_time
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
