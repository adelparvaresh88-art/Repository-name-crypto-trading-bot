import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.1
# BREAKOUT + RETEST + MOMENTUM
# UPWARD COIN SCANNER
# ============================================================

VERSION = "V38.1"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

MAX_MARKETS = 1000
TOP_BUYS = 3
TOP_WATCH = 3

TRADE_LIMIT = 1000
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.02

# ------------------------------------------------------------
# SCORE SETTINGS
# ------------------------------------------------------------

BUY_MIN_SCORE = 11
WATCH_MIN_SCORE = 8

# جلوگیری از ورود بعد از جهش شدید 5 دقیقه‌ای
MAX_5M_CHASE = 7.0

# حداقل مومنتوم
MIN_15M_MOMENTUM = 1.0
MIN_1H_MOMENTUM = 1.0

# حداقل تعداد کندل
MIN_CANDLES = 20

# ------------------------------------------------------------
# RISK
# ------------------------------------------------------------

SL_PERCENT = 0.50
TP1_PERCENT = 0.80
TP2_PERCENT = 1.50

# ------------------------------------------------------------
# TELEGRAM
# ------------------------------------------------------------

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


# ============================================================
# HTTP SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/38.1",
        "Accept": "application/json",
    }
)


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def safe_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default


def api_get(path, params=None):
    url = BASE_URL + path

    response = SESSION.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ TELEGRAM SETTINGS NOT FOUND")
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
    }

    try:
        response = SESSION.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            print("✅ TELEGRAM SENT")
            return True

        print(
            "❌ TELEGRAM ERROR:",
            response.status_code,
            response.text[:300],
        )

    except Exception as e:
        print("❌ TELEGRAM EXCEPTION:", e)

    return False


# ============================================================
# MARKET LIST
# ============================================================

def load_usdt_markets():

    try:
        data = api_get(
            "/r/api/v1/exchangeInfo"
        )

    except Exception as e:
        print("❌ TABDEAL MARKET ERROR:", e)
        return []

    markets = []

    # --------------------------------------------------------
    # Handle different possible Tabdeal response structures
    # --------------------------------------------------------

    raw = data

    if isinstance(data, dict):

        for key in (
            "symbols",
            "data",
            "markets",
            "result",
            "list",
        ):
            if key in data:
                raw = data[key]
                break

    if isinstance(raw, dict):

        for key in (
            "symbols",
            "data",
            "markets",
            "result",
            "list",
        ):
            if key in raw:
                raw = raw[key]
                break

    # --------------------------------------------------------
    # String symbol list
    # --------------------------------------------------------

    if isinstance(raw, list):

        for item in raw:

            if isinstance(item, str):

                symbol = item.upper()

                if symbol.endswith("USDT"):
                    markets.append(symbol)

                continue

            if not isinstance(item, dict):
                continue

            symbol = str(
                item.get("symbol")
                or item.get("name")
                or item.get("market")
                or ""
            ).upper()

            if not symbol:
                continue

            quote = str(
                item.get("quoteAsset")
                or item.get("quote")
                or ""
            ).upper()

            status = str(
                item.get("status")
                or ""
            ).upper()

            if status in (
                "BREAK",
                "BREAKING",
                "HALT",
                "HALTED",
                "CLOSED",
            ):
                continue

            if symbol.endswith("USDT") or quote == "USDT":
                markets.append(symbol)

    markets = sorted(set(markets))

    if len(markets) > MAX_MARKETS:
        markets = markets[:MAX_MARKETS]

    return markets


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):

    if not isinstance(item, dict):
        return None

    price = (
        item.get("price")
        or item.get("p")
    )

    qty = (
        item.get("qty")
        or item.get("quantity")
        or item.get("q")
    )

    timestamp = (
        item.get("time")
        or item.get("timestamp")
        or item.get("T")
    )

    price = safe_float(price)
    qty = safe_float(qty)
    timestamp = safe_float(timestamp)

    if price <= 0:
        return None

    if timestamp <= 0:
        return None

    # milliseconds → seconds
    if timestamp > 100000000000:
        timestamp = timestamp / 1000.0

    return {
        "price": price,
        "qty": qty,
        "time": timestamp,
    }


# ============================================================
# LOAD TRADES
# ============================================================

def load_trades(symbol):

    try:

        data = api_get(
            "/r/api/v1/trades",
            params={
                "symbol": symbol,
                "limit": TRADE_LIMIT,
            },
        )

    except Exception:
        return []

    raw = data

    if isinstance(data, dict):

        for key in (
            "data",
            "trades",
            "result",
            "list",
        ):
            if key in data:
                raw = data[key]
                break

    if not isinstance(raw, list):
        return []

    trades = []

    for item in raw:

        trade = parse_trade(item)

        if trade:
            trades.append(trade)

    trades.sort(
        key=lambda x: x["time"]
    )

    return trades


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    buckets = {}

    for trade in trades:

        ts = int(trade["time"])

        bucket = ts - (ts % 300)

        price = trade["price"]
        qty = trade["qty"]

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }

        else:

            candle = buckets[bucket]

            candle["high"] = max(
                candle["high"],
                price,
            )

            candle["low"] = min(
                candle["low"],
                price,
            )

            candle["close"] = price

            candle["volume"] += qty

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ============================================================
# PERCENT CHANGE
# ============================================================

def percent_change(old, new):

    if old <= 0:
        return 0.0

    return (
        (new - old)
        / old
        * 100.0
    )


# ============================================================
# MOMENTUM
# ============================================================

def calculate_momentum(candles):

    if len(candles) < 13:
        return 0.0, 0.0, 0.0

    current = candles[-1]["close"]

    close_5m = candles[-2]["close"]

    close_15m = candles[-4]["close"]

    close_1h = candles[-13]["close"]

    m5 = percent_change(
        close_5m,
        current,
    )

    m15 = percent_change(
        close_15m,
        current,
    )

    m1h = percent_change(
        close_1h,
        current,
    )

    return m5, m15, m1h


# ============================================================
# STRUCTURE
# ============================================================

def calculate_structure(candles):

    if len(candles) < 8:
        return False, False

    current = candles[-1]

    previous = candles[-2]

    lookback = candles[-7:-2]

    if not lookback:
        return False, False

    previous_high = max(
        c["high"]
        for c in lookback
    )

    previous_low = min(
        c["low"]
        for c in lookback
    )

    breakout = (
        current["close"]
        > previous_high
    )

    higher_high = (
        current["high"]
        > previous["high"]
        and current["close"]
        >= previous["close"]
    )

    return breakout, higher_high


# ============================================================
# BREAKOUT LEVEL
# ============================================================

def get_breakout_level(candles):

    if len(candles) < 8:
        return 0.0

    lookback = candles[-7:-2]

    return max(
        c["high"]
        for c in lookback
    )


# ============================================================
# RETEST
# ============================================================

def check_retest(
    candles,
    breakout_level,
):

    if len(candles) < 5:
        return False

    if breakout_level <= 0:
        return False

    current = candles[-1]

    previous = candles[-2]

    # فاصله قابل قبول از سطح شکست
    tolerance = breakout_level * 0.004

    near_level = (
        abs(
            previous["low"]
            - breakout_level
        )
        <= tolerance
    )

    current_above = (
        current["close"]
        >= breakout_level
    )

    previous_above = (
        previous["close"]
        >= breakout_level
    )

    # حالت اول:
    # قیمت به سطح شکست برگشته
    if near_level and current_above:
        return True

    # حالت دوم:
    # کندل قبل نزدیک سطح بوده
    if (
        previous_above
        and current["low"]
        <= breakout_level + tolerance
        and current["close"]
        >= breakout_level
    ):
        return True

    return False


# ============================================================
# PULLBACK
# ============================================================

def check_pullback(candles):

    if len(candles) < 5:
        return False

    c1 = candles[-1]
    c2 = candles[-2]
    c3 = candles[-3]

    # کندل قبلی اصلاحی و کندل فعلی برگشتی
    pullback = (
        c2["close"] < c2["open"]
        and c1["close"] > c1["open"]
        and c1["close"] > c2["close"]
    )

    # حالت دوم:
    # اصلاح کوچک و حفظ کف
    if (
        c2["low"] >= c3["low"]
        and c1["close"] > c2["close"]
    ):
        pullback = True

    return pullback


# ============================================================
# CANDLE CONFIRMATION
# ============================================================

def bullish_confirmation(candle):

    if not candle:
        return False

    body = (
        candle["close"]
        - candle["open"]
    )

    candle_range = (
        candle["high"]
        - candle["low"]
    )

    if candle_range <= 0:
        return False

    body_ratio = (
        body / candle_range
    )

    return (
        candle["close"]
        > candle["open"]
        and body_ratio >= 0.35
    )


# ============================================================
# SCORE ENGINE
# ============================================================

def score_signal(
    candles,
    m5,
    m15,
    m1h,
    breakout,
    retest,
    pullback,
    higher_high,
):

    current = candles[-1]

    score = 0

    reasons = []

    # --------------------------------------------------------
    # 5M MOMENTUM
    # --------------------------------------------------------

    if m5 > 0:
        score += 2
        reasons.append("5M+")

    if m5 >= 0.5:
        score += 1

    # --------------------------------------------------------
    # 15M MOMENTUM
    # --------------------------------------------------------

    if m15 >= 1.0:
        score += 2
        reasons.append("15M+")

    if m15 >= 3.0:
        score += 1

    # --------------------------------------------------------
    # 1H MOMENTUM
    # --------------------------------------------------------

    if m1h >= 1.0:
        score += 1
        reasons.append("1H+")

    if m1h >= 5.0:
        score += 1

    # --------------------------------------------------------
    # BULLISH CANDLE
    # --------------------------------------------------------

    if bullish_confirmation(current):
        score += 2
        reasons.append("BULLISH")

    # --------------------------------------------------------
    # BREAKOUT
    # --------------------------------------------------------

    if breakout:
        score += 3
        reasons.append("BREAKOUT")

    # --------------------------------------------------------
    # RETEST
    # --------------------------------------------------------

    if retest:
        score += 3
        reasons.append("RETEST")

    # --------------------------------------------------------
    # PULLBACK
    # --------------------------------------------------------

    if pullback:
        score += 1
        reasons.append("PULLBACK")

    # --------------------------------------------------------
    # HIGHER HIGH
    # --------------------------------------------------------

    if higher_high:
        score += 1
        reasons.append("HH")

    return score, reasons


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(symbol):

    trades = load_trades(symbol)

    if len(trades) < 20:
        return None

    candles = build_candles(trades)

    if len(candles) < MIN_CANDLES:
        return None

    # --------------------------------------------------------
    # CLOSED CANDLE ONLY
    # --------------------------------------------------------

    closed = candles[:-1]

    if len(closed) < MIN_CANDLES:
        return None

    m5, m15, m1h = calculate_momentum(
        closed
    )

    # --------------------------------------------------------
    # CHASE FILTER
    # --------------------------------------------------------

    if m5 > MAX_5M_CHASE:
        return None

    # --------------------------------------------------------
    # MOMENTUM FILTER
    # --------------------------------------------------------

    if m15 < MIN_15M_MOMENTUM:
        return None

    if m1h < MIN_1H_MOMENTUM:
        return None

    breakout, higher_high = (
        calculate_structure(closed)
    )

    breakout_level = get_breakout_level(
        closed
    )

    retest = check_retest(
        closed,
        breakout_level,
    )

    pullback = check_pullback(
        closed
    )

    score, reasons = score_signal(
        closed,
        m5,
        m15,
        m1h,
        breakout,
        retest,
        pullback,
        higher_high,
    )

    # --------------------------------------------------------
    # BUY RULE
    # --------------------------------------------------------

    buy_confirmed = (
        score >= BUY_MIN_SCORE
        and breakout
        and retest
        and bullish_confirmation(
            closed[-1]
        )
        and m15 >= MIN_15M_MOMENTUM
        and m1h >= MIN_1H_MOMENTUM
    )

    # --------------------------------------------------------
    # WATCH RULE
    # --------------------------------------------------------

    watch_confirmed = (
        score >= WATCH_MIN_SCORE
        and breakout
        and not retest
        and m15 >= MIN_15M_MOMENTUM
    )

    if not buy_confirmed and not watch_confirmed:
        return None

    price = closed[-1]["close"]

    sl = price * (
        1 - SL_PERCENT / 100
    )

    tp1 = price * (
        1 + TP1_PERCENT / 100
    )

    tp2 = price * (
        1 + TP2_PERCENT / 100
    )

    status = (
        "BUY"
        if buy_confirmed
        else "WATCH"
    )

    return {
        "symbol": symbol,
        "status": status,
        "score": score,
        "price": price,
        "m5": m5,
        "m15": m15,
        "m1h": m1h,
        "breakout": breakout,
        "retest": retest,
        "pullback": pullback,
        "higher_high": higher_high,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "reasons": reasons,
    }


# ============================================================
# FORMAT SIGNAL
# ============================================================

def format_signal(item, number):

    status = item["status"]

    emoji = (
        "🟢"
        if status == "BUY"
        else "🟡"
    )

    breakout = (
        "YES"
        if item["breakout"]
        else "NO"
    )

    retest = (
        "YES"
        if item["retest"]
        else "NO"
    )

    pullback = (
        "YES"
        if item["pullback"]
        else "NO"
    )

    return (
        f"#{number}\n"
        f"{emoji} {status}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: {item['price']:.8f}\n"
        f"📈 5M: {item['m5']:+.2f}%\n"
        f"📊 15M: {item['m15']:+.2f}%\n"
        f"⏱ 1H: {item['m1h']:+.2f}%\n\n"
        f"💥 BREAKOUT: {breakout}\n"
        f"🔄 RETEST: {retest}\n"
        f"↩️ PULLBACK: {pullback}\n\n"
        f"🛑 SL: {item['sl']:.8f}\n"
        f"🎯 TP1: {item['tp1']:.8f}\n"
        f"🎯 TP2: {item['tp2']:.8f}\n"
    )


# ============================================================
# MAIN SCANNER
# ============================================================

def main():

    print(
        f"\n⚡ ATI CRYPTO BOT {VERSION}"
    )

    print(
        "🚀 BREAKOUT + RETEST SCANNER"
    )

    print(
        "📡 Loading Tabdeal markets..."
    )

    markets = load_usdt_markets()

    if not markets:

        print(
            "❌ Could not load USDT markets."
        )

        send_telegram(
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET ERROR\n"
            f"Could not load USDT markets.\n\n"
            f"🕐 {now_utc()}"
        )

        return

    print(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    # --------------------------------------------------------
    # Immediate Telegram heartbeat
    # --------------------------------------------------------

    send_telegram(
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 BREAKOUT + RETEST SCANNER\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}\n"
        f"🚫 5M CHASE LIMIT: {MAX_5M_CHASE}%\n\n"
        f"🔎 SCAN STARTED...\n\n"
        f"🕐 {now_utc()}"
    )

    buys = []
    watches = []

    total = len(markets)

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    for index, symbol in enumerate(
        markets,
        start=1,
    ):

        try:

            result = analyze_symbol(
                symbol
            )

            if result:

                if result["status"] == "BUY":
                    buys.append(result)

                elif result["status"] == "WATCH":
                    watches.append(result)

        except Exception as e:

            print(
                f"⚠️ {symbol}: {e}"
            )

        if (
            SLEEP_BETWEEN_MARKETS
            > 0
        ):
            time.sleep(
                SLEEP_BETWEEN_MARKETS
            )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    buys.sort(
        key=lambda x: (
            x["score"],
            x["m15"],
            x["m1h"],
        ),
        reverse=True,
    )

    watches.sort(
        key=lambda x: (
            x["score"],
            x["m15"],
            x["m1h"],
        ),
        reverse=True,
    )

    buys = buys[:TOP_BUYS]

    watches = watches[:TOP_WATCH]

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 BREAKOUT + RETEST SCANNER\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n"
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}\n"
        f"🚫 5M CHASE LIMIT: {MAX_5M_CHASE}%\n\n"
    )

    # --------------------------------------------------------
    # BUY
    # --------------------------------------------------------

    if buys:

        message += (
            "🟢 CONFIRMED BUY\n\n"
        )

        for i, item in enumerate(
            buys,
            start=1,
        ):

            message += (
                format_signal(
                    item,
                    i,
                )
                + "\n"
            )

    else:

        message += (
            "🟢 CONFIRMED BUY\n"
            "❌ NO VALID BUY SIGNAL\n\n"
        )

    # --------------------------------------------------------
    # WATCH
    # --------------------------------------------------------

    if watches:

        message += (
            "🟡 WATCH / WAIT FOR RETEST\n\n"
        )

        for i, item in enumerate(
            watches,
            start=1,
        ):

            message += (
                format_signal(
                    item,
                    i,
                )
                + "\n"
            )

    else:

        message += (
            "🟡 WATCH / WAIT FOR RETEST\n"
            "❌ NONE\n\n"
        )

    # --------------------------------------------------------
    # STATUS
    # --------------------------------------------------------

    message += (
        "🔒 REAL TRADING: DISABLED\n"
        "🧪 SCANNER MODE ONLY\n\n"
        f"🕐 {now_utc()}"
    )

    print("\n" + message)

    send_telegram(
        message
    )


# ============================================================
# ENTRY
# ============================================================

if __name__ == "__main__":
    main()
