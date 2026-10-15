import os
import json
import time
import math
from datetime import datetime, timezone

from tabdeal.future import Future
from tabdeal.enums import OrderSides, OrderTypes


# ============================================================
# ATI FUTURES - TABDEAL OFFICIAL SDK
# MACD 12/26/9
# TIMEFRAME: 5 MINUTES
#
# IMPORTANT:
# REAL_TRADING = false
#
# No Binance
# No /klines
# No EMA
# ============================================================

VERSION = "ATI TABDEAL FUTURES MACD OFFICIAL SDK V1"

API_KEY = os.getenv("TABDIL_API_KEY", "").strip()
API_SECRET = os.getenv("TABDIL_API_SECRET", "").strip()

REAL_TRADING = os.getenv("REAL_TRADING", "false").lower() == "true"

ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

MAX_MARKETS = int(os.getenv("MAX_MARKETS", "25"))

STATE_FILE = "ati_futures_state.json"

MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

TP_PCT = 0.02
SL_PCT = 0.01

BASE_URL = "https://api1.tabdeal.org"


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc)


def now_text():
    return now_utc().strftime("%Y-%m-%d %H:%M:%S UTC")


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    tmp = STATE_FILE + ".tmp"

    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    os.replace(tmp, STATE_FILE)


def clean_symbol(symbol):
    return str(symbol).upper().replace("_", "")


def get_symbols(exchange_info):
    result = []

    for item in exchange_info.get("symbols", []):
        symbol = str(item.get("symbol", "")).upper()

        status = str(item.get("status", "")).upper()
        quote = str(
            item.get("quoteAsset")
            or item.get("quote")
            or ""
        ).upper()

        if not symbol:
            continue

        if status and status not in ("TRADING", "1", "ACTIVE"):
            continue

        if quote and quote != "USDT":
            continue

        if not symbol.endswith("USDT"):
            continue

        result.append(clean_symbol(symbol))

    return sorted(set(result))


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


# ============================================================
# MACD
# ============================================================

def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2.0 / (period + 1.0)

    current = sum(values[:period]) / period

    for price in values[period:]:
        current = (
            (price - current) * multiplier
            + current
        )

    return current


def calculate_macd(closes):
    minimum = MACD_SLOW + MACD_SIGNAL

    if len(closes) < minimum:
        return None

    fast = ema(closes, MACD_FAST)
    slow = ema(closes, MACD_SLOW)

    if fast is None or slow is None:
        return None

    # Build MACD series for signal EMA
    macd_values = []

    for i in range(MACD_SLOW, len(closes) + 1):
        section = closes[:i]

        f = ema(section, MACD_FAST)
        s = ema(section, MACD_SLOW)

        if f is not None and s is not None:
            macd_values.append(f - s)

    if len(macd_values) < MACD_SIGNAL:
        return None

    signal = ema(macd_values, MACD_SIGNAL)

    if signal is None:
        return None

    macd = macd_values[-1]
    histogram = macd - signal

    return {
        "macd": macd,
        "signal": signal,
        "histogram": histogram,
    }


# ============================================================
# DEPTH -> MID PRICE
# ============================================================

def get_mid_price(client, symbol):
    data = client.depth(symbol=symbol, limit=5)

    bids = data.get("bids") or []
    asks = data.get("asks") or []

    if not bids or not asks:
        return None

    best_bid = safe_float(bids[0][0])
    best_ask = safe_float(asks[0][0])

    if best_bid is None or best_ask is None:
        return None

    if best_bid <= 0 or best_ask <= 0:
        return None

    return (best_bid + best_ask) / 2.0


# ============================================================
# 5-MINUTE SYNTHETIC CANDLE
#
# We deliberately do NOT use /klines.
#
# Every GitHub run records the current mid-price.
# The state file builds 5-minute closes.
# ============================================================

def update_5m_candle(state, symbol, price):
    symbol_state = state.setdefault(
        symbol,
        {
            "candles": [],
            "current_bucket": None,
            "current_close": None,
        },
    )

    timestamp = int(time.time())

    bucket = timestamp // 300

    old_bucket = symbol_state.get("current_bucket")

    if old_bucket is None:
        symbol_state["current_bucket"] = bucket
        symbol_state["current_close"] = price
        return False

    if bucket == old_bucket:
        symbol_state["current_close"] = price
        return False

    # Previous 5-minute candle closed
    previous_close = symbol_state.get("current_close")

    if previous_close is not None:
        candles = symbol_state.setdefault("candles", [])

        candles.append(float(previous_close))

        # Keep enough history for MACD
        if len(candles) > 100:
            del candles[:-100]

    symbol_state["current_bucket"] = bucket
    symbol_state["current_close"] = price

    return True


# ============================================================
# SIGNAL
# ============================================================

def get_signal(state, symbol):
    item = state.get(symbol)

    if not item:
        return None

    closes = item.get("candles", [])

    macd_data = calculate_macd(closes)

    if not macd_data:
        return None

    macd = macd_data["macd"]
    signal = macd_data["signal"]
    histogram = macd_data["histogram"]

    previous_histogram = item.get("previous_histogram")

    item["previous_histogram"] = histogram

    if previous_histogram is None:
        return None

    # BUY:
    # MACD above signal + histogram positive and increasing
    if (
        macd > signal
        and histogram > 0
        and histogram > previous_histogram
    ):
        return "BUY", macd_data

    # SELL:
    # MACD below signal + histogram negative and decreasing
    if (
        macd < signal
        and histogram < 0
        and histogram < previous_histogram
    ):
        return "SELL", macd_data

    return None


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not token or not chat_id:
        return

    try:
        import requests

        url = (
            "https://api.telegram.org/bot"
            + token
            + "/sendMessage"
        )

        requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": text,
            },
            timeout=15,
        )

    except Exception as e:
        print("Telegram error:", e)


# ============================================================
# REAL ORDER
# ============================================================

def execute_order(client, symbol, side, price):
    if not REAL_TRADING:
        print(
            f"PAPER ORDER | {symbol} | {side} | "
            f"price={price}"
        )
        return None

    quantity = ORDER_USDT / price

    if quantity <= 0:
        raise ValueError("Invalid order quantity")

    quantity_text = f"{quantity:.12f}".rstrip("0").rstrip(".")

    order_side = (
        OrderSides.BUY
        if side == "BUY"
        else OrderSides.SELL
    )

    print(
        f"REAL ORDER | {symbol} | {side} | "
        f"qty={quantity_text}"
    )

    order = client.new_order(
        symbol=symbol,
        side=order_side,
        type=OrderTypes.MARKET,
        quantity=quantity_text,
    )

    return order


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print(VERSION)
    print("=" * 60)

    print("Time:", now_text())
    print("API KEY:", "PRESENT" if API_KEY else "MISSING")
    print("REAL TRADING:", REAL_TRADING)
    print("ORDER USDT:", ORDER_USDT)
    print("LEVERAGE:", LEVERAGE)
    print("MACD:", f"{MACD_FAST}/{MACD_SLOW}/{MACD_SIGNAL}")
    print("TIMEFRAME: 5M")
    print("Endpoint: OFFICIAL TABDEAL FUTURES SDK")
    print("KLINES: NOT USED")
    print()

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDIL_API_KEY / TABDIL_API_SECRET missing"
        )

    # --------------------------------------------------------
    # Official Tabdeal Futures client
    # --------------------------------------------------------

    client = Future(
        api_key=API_KEY,
        api_secret=API_SECRET,
        base_url=BASE_URL,
        timeout=20,
    )

    # --------------------------------------------------------
    # Connection
    # --------------------------------------------------------

    print("Testing Futures ping...")

    client.ping()

    print("OK: Futures ping")

    # --------------------------------------------------------
    # Exchange info
    # --------------------------------------------------------

    print("Loading exchange info...")

    info = client.exchange_info()

    symbols = get_symbols(info)

    if not symbols:
        raise RuntimeError(
            "No eligible USDT Futures markets found"
        )

    print("USDT markets:", len(symbols))

    symbols = symbols[:MAX_MARKETS]

    print(
        "Scanning:",
        ", ".join(symbols)
    )

    # --------------------------------------------------------
    # State
    # --------------------------------------------------------

    state = load_state()

    ready = 0
    new_candles = 0
    errors = 0
    buys = []
    sells = []

    # --------------------------------------------------------
    # Scan
    # --------------------------------------------------------

    for symbol in symbols:

        try:

            price = get_mid_price(
                client,
                symbol
            )

            if price is None:
                errors += 1
                print(symbol, "NO MID PRICE")
                continue

            closed = update_5m_candle(
                state,
                symbol,
                price
            )

            if closed:
                new_candles += 1

            candles = state.get(
                symbol,
                {}
            ).get(
                "candles",
                []
            )

            if len(candles) < (
                MACD_SLOW + MACD_SIGNAL
            ):
                print(
                    symbol,
                    f"PRICE={price:.8g}",
                    f"5M_CANDLES={len(candles)}",
                    "WARMING UP"
                )
                continue

            ready += 1

            result = get_signal(
                state,
                symbol
            )

            if result:

                side, macd = result

                print(
                    symbol,
                    side,
                    f"price={price:.8g}",
                    f"MACD={macd['macd']:.8g}",
                    f"SIGNAL={macd['signal']:.8g}",
                    f"HIST={macd['histogram']:.8g}"
                )

                if side == "BUY":
                    buys.append(symbol)

                if side == "SELL":
                    sells.append(symbol)

                if REAL_TRADING:
                    execute_order(
                        client,
                        symbol,
                        side,
                        price
                    )

            else:
                print(
                    symbol,
                    f"PRICE={price:.8g}",
                    "NO SIGNAL"
                )

        except Exception as e:

            errors += 1

            print(
                symbol,
                "ERROR:",
                type(e).__name__,
                str(e)
            )

    # --------------------------------------------------------
    # Save state
    # --------------------------------------------------------

    save_state(state)

    # --------------------------------------------------------
    # Summary
    # --------------------------------------------------------

    print()
    print("=" * 60)
    print("ATI FUTURES SUMMARY")
    print("=" * 60)

    print("Markets:", len(symbols))
    print("Ready:", ready)
    print("New 5M candles:", new_candles)
    print("BUY:", len(buys))
    print("SELL:", len(sells))
    print("Errors:", errors)
    print("REAL TRADING:", REAL_TRADING)

    if buys:
        print("BUY SYMBOLS:", ", ".join(buys))

    if sells:
        print("SELL SYMBOLS:", ", ".join(sells))

    print("=" * 60)

    telegram_text = (
        "🤖 ATI TABDEAL FUTURES\n\n"
        f"🕐 {now_text()}\n"
        f"📊 Markets: {len(symbols)}\n"
        f"📈 Ready: {ready}\n"
        f"🕯 New 5M: {new_candles}\n"
        f"🟢 BUY: {len(buys)}\n"
        f"🔴 SELL: {len(sells)}\n"
        f"❌ Errors: {errors}\n"
        f"⚙️ MACD: 12/26/9\n"
        f"💵 Order: {ORDER_USDT} USDT\n"
        f"⚡ Leverage: {LEVERAGE}x\n"
        f"🔒 REAL: {REAL_TRADING}"
    )

    telegram_send(telegram_text)


if __name__ == "__main__":
    main()
