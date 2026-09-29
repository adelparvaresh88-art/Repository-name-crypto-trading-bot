import os
import json
import time
import math
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V40.2.8
# OPPORTUNITY ENGINE + PERSISTENT BUY RESULT TRACKER
# ============================================================

VERSION = "V40.2.8"

BASE_URL = "https://api1.tabdeal.org"

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

HISTORY_FILE = "paper_history.json"

REQUEST_TIMEOUT = 15
MAX_SYMBOLS = 529

# Real trading is intentionally disabled.
REAL_ORDERS = False

# Strategy settings
MIN_CANDLES = 12
SCAN_WATCH_LIMIT = 3
MAX_HISTORY = 500

# BUY thresholds
CONFIRMED_SCORE = 10
EARLY_SCORE = 9
WATCH_SCORE = 6

# ============================================================
# HTTP SESSION
# ============================================================

session = requests.Session()
session.headers.update({
    "User-Agent": "ATI-Crypto-Bot-V40.2.8"
})


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_text():
    return utc_now().strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM CONFIG: MISSING")
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
        response = session.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 200:
            return True

        print(
            "TELEGRAM ERROR:",
            response.status_code,
            response.text[:500]
        )
        return False

    except Exception as exc:
        print("TELEGRAM EXCEPTION:", repr(exc))
        return False


# ============================================================
# JSON HISTORY
# ============================================================

def default_history():
    return {
        "version": VERSION,
        "signals": [],
        "updated_at": utc_text()
    }


def load_history():
    if not os.path.exists(HISTORY_FILE):
        return default_history()

    try:
        with open(
            HISTORY_FILE,
            "r",
            encoding="utf-8"
        ) as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return default_history()

        if not isinstance(data.get("signals"), list):
            data["signals"] = []

        return data

    except Exception as exc:
        print("HISTORY LOAD ERROR:", repr(exc))
        return default_history()


def save_history(history):
    history["version"] = VERSION
    history["updated_at"] = utc_text()

    try:
        with open(
            HISTORY_FILE,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                history,
                f,
                ensure_ascii=False,
                indent=2
            )

        return True

    except Exception as exc:
        print("HISTORY SAVE ERROR:", repr(exc))
        return False


# ============================================================
# TABDEAL API
# ============================================================

def api_get(path, params=None):
    url = BASE_URL + path

    try:
        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT
        )

        response.raise_for_status()
        return response.json()

    except Exception as exc:
        print(
            "API ERROR:",
            path,
            repr(exc)
        )
        return None


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_usdt_markets():
    data = api_get("/r/api/v1/exchangeInfo")

    if not data:
        return []

    raw = data

    if isinstance(data, dict):
        for key in (
            "symbols",
            "data",
            "result",
            "markets"
        ):
            if key in data:
                raw = data[key]
                break

    if isinstance(raw, dict):
        raw = list(raw.values())

    if not isinstance(raw, list):
        return []

    markets = []

    for item in raw:
        if isinstance(item, str):
            symbol = item.upper()
        elif isinstance(item, dict):
            symbol = (
                item.get("symbol")
                or item.get("market")
                or item.get("pair")
                or ""
            )
            symbol = str(symbol).upper()
        else:
            continue

        if not symbol.endswith("USDT"):
            continue

        # Ignore leveraged-looking symbols.
        if any(
            x in symbol
            for x in (
                "3LUSDT",
                "3SUSDT",
                "5LUSDT",
                "5SUSDT"
            )
        ):
            continue

        if symbol not in markets:
            markets.append(symbol)

    markets.sort()

    return markets[:MAX_SYMBOLS]


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):
    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000
        }
    )

    if data is None:
        return []

    raw = data

    if isinstance(data, dict):
        for key in (
            "data",
            "result",
            "trades"
        ):
            if key in data:
                raw = data[key]
                break

    if not isinstance(raw, list):
        return []

    return raw


# ============================================================
# TRADE PARSER
# ============================================================

def trade_values(item):
    if not isinstance(item, dict):
        return None

    price_keys = (
        "price",
        "p"
    )

    qty_keys = (
        "qty",
        "quantity",
        "amount",
        "q",
        "volume"
    )

    time_keys = (
        "time",
        "timestamp",
        "T",
        "created_at"
    )

    price = None
    qty = None
    timestamp = None

    for key in price_keys:
        if key in item:
            try:
                price = float(item[key])
                break
            except Exception:
                pass

    for key in qty_keys:
        if key in item:
            try:
                qty = float(item[key])
                break
            except Exception:
                pass

    for key in time_keys:
        if key in item:
            try:
                timestamp = float(item[key])
                break
            except Exception:
                pass

    if price is None:
        return None

    if qty is None:
        qty = 0.0

    if timestamp is None:
        timestamp = time.time() * 1000

    if timestamp < 10_000_000_000:
        timestamp *= 1000

    return {
        "price": price,
        "qty": abs(qty),
        "timestamp": timestamp
    }


# ============================================================
# BUILD 5-MIN CANDLES
# ============================================================

def build_candles(trades):
    parsed = []

    for item in trades:
        value = trade_values(item)

        if value:
            parsed.append(value)

    if not parsed:
        return []

    parsed.sort(
        key=lambda x: x["timestamp"]
    )

    buckets = {}

    for trade in parsed:
        bucket = int(
            trade["timestamp"] // 300000
        ) * 300000

        buckets.setdefault(
            bucket,
            []
        ).append(trade)

    candles = []

    for timestamp in sorted(buckets):
        group = buckets[timestamp]

        prices = [
            x["price"]
            for x in group
            if x["price"] > 0
        ]

        if not prices:
            continue

        volume = sum(
            x["qty"]
            for x in group
        )

        candles.append({
            "timestamp": timestamp,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": volume
        })

    return candles


# ============================================================
# BUY PRESSURE
# ============================================================

def calculate_pressure(trades):
    if not trades:
        return None

    buy_volume = 0.0
    sell_volume = 0.0
    total = 0.0

    for item in trades:
        if not isinstance(item, dict):
            continue

        qty = 0.0

        for key in (
            "qty",
            "quantity",
            "amount",
            "q",
            "volume"
        ):
            if key in item:
                try:
                    qty = abs(float(item[key]))
                    break
                except Exception:
                    pass

        if qty <= 0:
            continue

        total += qty

        side = str(
            item.get("side")
            or item.get("S")
            or ""
        ).lower()

        if side in (
            "buy",
            "bid"
        ):
            buy_volume += qty

        elif side in (
            "sell",
            "ask"
        ):
            sell_volume += qty

        else:
            # When exchange does not provide side,
            # do not invent pressure.
            continue

    directional = buy_volume + sell_volume

    if directional <= 0:
        return None

    return (
        buy_volume /
        directional
    ) * 100.0


# ============================================================
# STRATEGY
# ============================================================

def analyze_symbol(symbol, trades):
    candles = build_candles(trades)

    if len(candles) < MIN_CANDLES:
        return None

    # Closed candles only.
    closed = candles[:-1]

    if len(closed) < MIN_CANDLES:
        return None

    last = closed[-1]
    previous = closed[-2]

    recent = closed[-12:]

    price = last["close"]

    if price <= 0:
        return None

    high_values = [
        c["high"]
        for c in recent[:-1]
    ]

    resistance = max(
        high_values
    )

    previous_high = max(
        c["high"]
        for c in closed[-6:-1]
    )

    previous_low = min(
        c["low"]
        for c in closed[-6:-1]
    )

    move_5m = (
        (
            last["close"] -
            previous["close"]
        )
        /
        previous["close"]
    ) * 100.0

    pressure = calculate_pressure(
        trades[-300:]
    )

    # Pressure fallback based on candle body.
    if pressure is None:
        bullish = 0
        total = 0

        for c in closed[-12:]:
            total += 1

            if c["close"] > c["open"]:
                bullish += 1

        if total:
            pressure = (
                bullish /
                total
            ) * 100.0
        else:
            pressure = 50.0

    score = 0

    # Momentum
    if move_5m > 0.15:
        score += 1

    if move_5m > 0.50:
        score += 1

    # Pressure
    if pressure >= 55:
        score += 1

    if pressure >= 60:
        score += 1

    # Candle structure
    if last["close"] > last["open"]:
        score += 1

    if last["close"] > previous["high"]:
        score += 2

    # Recent higher structure
    if last["close"] > previous_high:
        score += 2

    if last["low"] >= previous_low:
        score += 1

    # Volume expansion
    volumes = [
        c["volume"]
        for c in closed[-6:-1]
        if c["volume"] > 0
    ]

    if volumes:
        avg_volume = (
            sum(volumes) /
            len(volumes)
        )

        if avg_volume > 0 and (
            last["volume"] >=
            avg_volume * 1.15
        ):
            score += 1

    score = min(score, 11)

    breakout = (
        last["close"] >
        resistance
    )

    resistance_distance = (
        (
            resistance -
            price
        )
        /
        price
    ) * 100.0

    # Confirmed breakout.
    confirmed = (
        breakout and
        score >= CONFIRMED_SCORE and
        pressure >= 58
    )

    # Early entry:
    # strong structure but breakout is not yet fully confirmed.
    early = (
        not confirmed and
        score >= EARLY_SCORE and
        pressure >= 60 and
        move_5m > 0.15
    )

    # Watch:
    watch = (
        not confirmed and
        not early and
        score >= WATCH_SCORE
    )

    # Risk model.
    # Conservative SL below recent structural low.
    structural_low = min(
        c["low"]
        for c in closed[-5:]
    )

    if structural_low <= 0:
        return None

    risk = price - structural_low

    if risk <= 0:
        risk = price * 0.006

    # Avoid absurdly large stop.
    max_risk = price * 0.012

    if risk > max_risk:
        risk = max_risk

    sl = price - risk

    tp1 = price + (
        risk * 1.67
    )

    tp2 = price + (
        risk * 2.67
    )

    return {
        "symbol": symbol,
        "price": price,
        "move_5m": move_5m,
        "pressure": pressure,
        "score": score,
        "breakout": breakout,
        "resistance": resistance,
        "resistance_distance": resistance_distance,
        "candles": len(candles),
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "confirmed": confirmed,
        "early": early,
        "watch": watch
    }


# ============================================================
# SIGNAL ID
# ============================================================

def make_signal_id(signal):
    # Same symbol + entry price rounded.
    # Prevents duplicate signal records every 5 minutes.
    return (
        f"{signal['symbol']}_"
        f"{round(signal['price'], 12)}"
    )


# ============================================================
# REGISTER NEW BUY
# ============================================================

def register_buy(history, signal, signal_type):
    signal_id = make_signal_id(signal)

    for old in history["signals"]:
        if old.get("id") == signal_id:
            return False

    record = {
        "id": signal_id,
        "symbol": signal["symbol"],
        "type": signal_type,
        "entry": signal["price"],
        "sl": signal["sl"],
        "tp1": signal["tp1"],
        "tp2": signal["tp2"],
        "created_at": utc_text(),
        "status": "OPEN",
        "result": None,
        "closed_at": None,
        "pnl_percent": None,
        "tp1_hit": False
    }

    history["signals"].append(record)

    # Keep file manageable.
    if len(history["signals"]) > MAX_HISTORY:
        history["signals"] = (
            history["signals"][-MAX_HISTORY:]
        )

    return True


# ============================================================
# UPDATE OPEN SIGNALS
# ============================================================

def update_open_signals(history, market_data):
    changed = False

    for signal in history["signals"]:
        if signal.get("status") != "OPEN":
            continue

        symbol = signal.get("symbol")

        if symbol not in market_data:
            continue

        info = market_data[symbol]

        price = info["price"]
        high = info["high"]
        low = info["low"]

        entry = float(signal["entry"])
        sl = float(signal["sl"])
        tp1 = float(signal["tp1"])
        tp2 = float(signal["tp2"])

        # TP1 notification only.
        if not signal.get("tp1_hit"):
            if high >= tp1:
                signal["tp1_hit"] = True
                changed = True

        # IMPORTANT:
        # If TP2 and SL are both touched in the same candle,
        # mark it as AMBIGUOUS instead of pretending we know
        # which happened first.
        hit_tp2 = high >= tp2
        hit_sl = low <= sl

        if hit_tp2 and hit_sl:
            signal["status"] = "AMBIGUOUS"
            signal["result"] = "TP2/SL SAME CANDLE"
            signal["closed_at"] = utc_text()
            signal["pnl_percent"] = None
            changed = True

        elif hit_tp2:
            signal["status"] = "TP2"
            signal["result"] = "TP2"
            signal["closed_at"] = utc_text()

            signal["pnl_percent"] = (
                (tp2 - entry) /
                entry
            ) * 100.0

            changed = True

        elif hit_sl:
            signal["status"] = "SL"
            signal["result"] = "SL"
            signal["closed_at"] = utc_text()

            signal["pnl_percent"] = (
                (sl - entry) /
                entry
            ) * 100.0

            changed = True

        else:
            # Keep OPEN.
            signal["last_price"] = price

    return changed


# ============================================================
# MARKET DATA FOR OPEN SIGNALS
# ============================================================

def current_market_info(symbol):
    trades = get_trades(symbol)

    if not trades:
        return None

    candles = build_candles(trades)

    if not candles:
        return None

    last = candles[-1]

    return {
        "price": last["close"],
        "high": last["high"],
        "low": last["low"]
    }


# ============================================================
# STATISTICS
# ============================================================

def statistics(history):
    signals = history["signals"]

    total = len(signals)

    tp1 = sum(
        1
        for s in signals
        if s.get("tp1_hit")
    )

    tp2 = sum(
        1
        for s in signals
        if s.get("status") == "TP2"
    )

    sl = sum(
        1
        for s in signals
        if s.get("status") == "SL"
    )

    open_count = sum(
        1
        for s in signals
        if s.get("status") == "OPEN"
    )

    ambiguous = sum(
        1
        for s in signals
        if s.get("status") == "AMBIGUOUS"
    )

    closed = tp2 + sl

    win_rate = (
        (tp2 / closed) * 100
        if closed > 0
        else 0.0
    )

    pnl = 0.0

    for s in signals:
        value = s.get("pnl_percent")

        if isinstance(value, (int, float)):
            pnl += value

    return {
        "total": total,
        "tp1": tp1,
        "tp2": tp2,
        "sl": sl,
        "open": open_count,
        "ambiguous": ambiguous,
        "win_rate": win_rate,
        "pnl": pnl
    }


# ============================================================
# TELEGRAM FORMATTERS
# ============================================================

def format_price(value):
    if value is None:
        return "-"

    if value >= 1000:
        return f"{value:.2f}"

    if value >= 1:
        return f"{value:.6f}"

    if value >= 0.01:
        return f"{value:.8f}"

    return f"{value:.10f}"


def format_signal(signal, title="🟢 BUY"):
    return (
        f"{title} {signal['symbol']}\n"
        f"💰 PRICE: {format_price(signal['price'])}\n"
        f"📈 5m: {signal['move_5m']:+.2f}%\n"
        f"💚 BUY PRESSURE: {signal['pressure']:.1f}%\n"
        f"🎯 SCORE: {signal['score']}/11\n"
        f"🚀 BREAKOUT: "
        f"{'YES' if signal['breakout'] else 'NO'}\n"
        f"🕯 CANDLES: {signal['candles']}\n"
        f"🛡 SL: {format_price(signal['sl'])}\n"
        f"🎯 TP1: {format_price(signal['tp1'])}\n"
        f"🎯 TP2: {format_price(signal['tp2'])}"
    )


def format_summary(history):
    stats = statistics(history)

    recent = history["signals"][-8:]

    lines = [
        "📊 BUY RESULT SUMMARY",
        "",
        f"📌 TOTAL BUY: {stats['total']}",
        f"🎯 TP1 HIT: {stats['tp1']}",
        f"🏆 TP2: {stats['tp2']}",
        f"❌ SL: {stats['sl']}",
        f"⏳ OPEN: {stats['open']}",
        f"⚠️ AMBIGUOUS: {stats['ambiguous']}",
        f"📈 WIN RATE: {stats['win_rate']:.1f}%",
        f"💰 PAPER P/L: {stats['pnl']:+.2f}%",
        "",
        "━━━━━━━━━━━━━━"
    ]

    if recent:
        lines.append("📋 RECENT BUY RESULTS")

        for s in recent:
            symbol = s.get("symbol", "?")
            status = s.get("status", "?")
            pnl = s.get("pnl_percent")

            if isinstance(pnl, (int, float)):
                pnl_text = f" | {pnl:+.2f}%"
            else:
                pnl_text = ""

            if s.get("tp1_hit") and status == "OPEN":
                status = "TP1 → OPEN"

            lines.append(
                f"{symbol} | {status}{pnl_text}"
            )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():
    start = time.time()

    print("=" * 60)
    print(f"ATI CRYPTO BOT {VERSION}")
    print("OPPORTUNITY ENGINE")
    print("=" * 60)

    history = load_history()

    # --------------------------------------------------------
    # STARTUP TELEGRAM
    # --------------------------------------------------------

    telegram_send(
        f"⚡ ATI CRYPTO BOT {VERSION}\n"
        f"🧠 OPPORTUNITY ENGINE\n\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED CANDLE: YES\n"
        f"📊 PAPER SIGNALS: ON\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"💓 HEARTBEAT: ON\n"
        f"🔄 CONTINUOUS MODE: ON\n\n"
        f"🕐 {utc_text()}"
    )

    # --------------------------------------------------------
    # MARKET LIST
    # --------------------------------------------------------

    markets = get_usdt_markets()

    if not markets:
        print("NO MARKETS")

        telegram_send(
            f"⚠️ ATI {VERSION}\n\n"
            f"❌ TABDEAL API / MARKET LIST FAILED\n"
            f"🕐 {utc_text()}"
        )

        return

    print("TABDEAL API: OK")
    print("USDT MARKETS:", len(markets))

    # --------------------------------------------------------
    # SCAN ALL MARKETS
    # --------------------------------------------------------

    requested = len(markets)
    responses = 0
    valid_trades = 0
    markets_with_data = 0
    insufficient = 0
    unknown_pressure = 0
    total_candles = 0

    confirmed = []
    early = []
    watch = []

    market_cache = {}

    for index, symbol in enumerate(markets, start=1):

        trades = get_trades(symbol)

        if trades:
            responses += 1

        if not trades:
            insufficient += 1
            continue

        candles = build_candles(trades)

        if not candles:
            insufficient += 1
            continue

        valid_trades += len(trades)
        markets_with_data += 1
        total_candles += len(candles)

        analysis = analyze_symbol(
            symbol,
            trades
        )

        if analysis is None:
            insufficient += 1
            continue

        market_cache[symbol] = {
            "price": analysis["price"],
            "high": candles[-1]["high"],
            "low": candles[-1]["low"]
        }

        if analysis["pressure"] is None:
            unknown_pressure += 1

        if analysis["confirmed"]:
            confirmed.append(analysis)

        elif analysis["early"]:
            early.append(analysis)

        elif analysis["watch"]:
            watch.append(analysis)

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    confirmed.sort(
        key=lambda x: (
            x["score"],
            x["pressure"],
            x["move_5m"]
        ),
        reverse=True
    )

    early.sort(
        key=lambda x: (
            x["score"],
            x["pressure"],
            x["move_5m"]
        ),
        reverse=True
    )

    watch.sort(
        key=lambda x: (
            x["score"],
            x["pressure"],
            -x["resistance_distance"]
        ),
        reverse=True
    )

    # --------------------------------------------------------
    # UPDATE EXISTING OPEN SIGNALS
    # --------------------------------------------------------

    history_changed = False

    if history["signals"]:

        for signal in history["signals"]:
            if signal.get("status") != "OPEN":
                continue

            symbol = signal.get("symbol")

            if symbol in market_cache:
                continue

            info = current_market_info(symbol)

            if info:
                market_cache[symbol] = info

        if update_open_signals(
            history,
            market_cache
        ):
            history_changed = True

    # --------------------------------------------------------
    # REGISTER NEW CONFIRMED BUY SIGNALS
    # --------------------------------------------------------

    new_confirmed = []

    for signal in confirmed:
        if register_buy(
            history,
            signal,
            "CONFIRMED BUY"
        ):
            new_confirmed.append(signal)
            history_changed = True

    # --------------------------------------------------------
    # REGISTER EARLY BUY SIGNALS
    # --------------------------------------------------------

    new_early = []

    for signal in early:
        # Early signals are registered too,
        # but use a separate type.
        if register_buy(
            history,
            signal,
            "EARLY BUY"
        ):
            new_early.append(signal)
            history_changed = True

    # --------------------------------------------------------
    # SAVE HISTORY
    # --------------------------------------------------------

    save_history(history)

    # --------------------------------------------------------
    # CONSOLE OUTPUT
    # --------------------------------------------------------

    print()
    print("TABDEAL API: OK")
    print("USDT MARKETS:", len(markets))
    print("REQUESTED:", requested)
    print("RESPONSES:", responses)
    print("VALID TRADES:", valid_trades)
    print("MARKETS WITH DATA:", markets_with_data)
    print("INSUFFICIENT DATA:", insufficient)
    print("UNKNOWN PRESSURE:", unknown_pressure)
    print("TOTAL CANDLES:", total_candles)
    print("MIN CANDLES:", MIN_CANDLES)

    # --------------------------------------------------------
    # TELEGRAM MAIN REPORT
    # --------------------------------------------------------

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n"
        f"🧠 OPPORTUNITY ENGINE\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"📡 REQUESTED: {requested}\n"
        f"📥 RESPONSES: {responses}\n"
        f"📊 VALID TRADES: {valid_trades}\n"
        f"📊 MARKETS WITH DATA: {markets_with_data}\n"
        f"⚠️ INSUFFICIENT DATA: {insufficient}\n"
        f"⚠️ UNKNOWN PRESSURE: {unknown_pressure}\n"
        f"🕯 TOTAL CANDLES: {total_candles}\n"
        f"🛡 MIN CANDLES: {MIN_CANDLES}\n\n"
    )

    # --------------------------------------------------------
    # CONFIRMED
    # --------------------------------------------------------

    message += "🟢 CONFIRMED BUY\n\n"

    if confirmed:
        for signal in confirmed[:5]:
            message += (
                format_signal(
                    signal,
                    "🟢"
                )
                + "\n\n"
            )
    else:
        message += "NONE\n\n"

    # --------------------------------------------------------
    # EARLY
    # --------------------------------------------------------

    message += "⚡ EARLY BUY\n\n"

    if early:
        for signal in early[:5]:
            message += (
                format_signal(
                    signal,
                    "⚡"
                )
                + "\n\n"
            )
    else:
        message += "NONE\n\n"

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    message += "🟡 WATCH\n\n"

    if watch:
        for signal in watch[:SCAN_WATCH_LIMIT]:
            message += (
                f"🟡 {signal['symbol']}\n"
                f"💰 PRICE: "
                f"{format_price(signal['price'])}\n"
                f"📈 5m: "
                f"{signal['move_5m']:+.2f}%\n"
                f"💚 BUY PRESSURE: "
                f"{signal['pressure']:.1f}%\n"
                f"📏 RESISTANCE DIST: "
                f"{signal['resistance_distance']:.2f}%\n"
                f"🎯 SCORE: "
                f"{signal['score']}/11\n"
                f"🚀 BREAKOUT: "
                f"{'YES' if signal['breakout'] else 'NO'}\n\n"
            )
    else:
        message += "NONE\n\n"

    # --------------------------------------------------------
    # MODE
    # --------------------------------------------------------

    message += (
        "━━━━━━━━━━━━━━━━━━\n"
        "📊 PAPER SIGNALS: ON\n"
        "🔧 REAL ORDERS: DISABLED\n"
        "💓 HEARTBEAT: ON\n"
        "🔄 CONTINUOUS MODE: ON\n"
        f"🕐 {utc_text()}"
    )

    telegram_send(message)

    # --------------------------------------------------------
    # NEW SIGNAL NOTICE
    # --------------------------------------------------------

    if new_confirmed:
        for signal in new_confirmed[:5]:
            telegram_send(
                "🚨 NEW CONFIRMED BUY\n\n"
                +
                format_signal(
                    signal,
                    "🟢"
                )
                +
                "\n\n📊 TRACKING: ON"
            )

    if new_early:
        for signal in new_early[:3]:
            telegram_send(
                "⚡ NEW EARLY BUY\n\n"
                +
                format_signal(
                    signal,
                    "⚡"
                )
                +
                "\n\n📊 TRACKING: ON"
            )

    # --------------------------------------------------------
    # RESULT SUMMARY
    # --------------------------------------------------------

    telegram_send(
        format_summary(history)
    )

    # --------------------------------------------------------
    # FINISH
    # --------------------------------------------------------

    elapsed = time.time() - start

    print()
    print("=" * 60)
    print("SCAN COMPLETE")
    print(f"SCAN TIME: {elapsed:.1f}s")
    print("REAL ORDERS: DISABLED")
    print("HISTORY FILE:", HISTORY_FILE)
    print("=" * 60)


if __name__ == "__main__":
    main()
