import os
import time
from datetime import datetime, timezone

import requests


# ============================================================
# ATI CRYPTO BOT V38.1.1
# BREAKOUT + RETEST SCANNER
# ============================================================

VERSION = "V38.1.1"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

MAX_MARKETS = 1000
TOP_BUYS = 3
TOP_WATCH = 3

TRADE_LIMIT = 1000
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.02

BUY_MIN_SCORE = 11
WATCH_MIN_SCORE = 8

MAX_5M_CHASE = 7.0
MIN_15M_MOMENTUM = 1.0
MIN_1H_MOMENTUM = 1.0

MIN_CANDLES = 20

SL_PERCENT = 0.50
TP1_PERCENT = 0.80
TP2_PERCENT = 1.50


# ============================================================
# ENV
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot/38.1.1",
        "Accept": "application/json",
    }
)


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# API GET
# ============================================================

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
        print("Telegram configuration missing.")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = SESSION.post(
            url,
            data=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if response.ok:
            return True

        print("Telegram ERROR:", response.text)

        return False

    except Exception as exc:
        print("Telegram ERROR:", exc)

        return False


# ============================================================
# MARKET DISCOVERY
# ============================================================

def load_usdt_markets():

    data = api_get(
        "/r/api/v1/exchangeInfo"
    )

    symbols = []

    if isinstance(data, dict):

        if isinstance(data.get("symbols"), list):
            symbols = data["symbols"]

        elif isinstance(data.get("data"), list):
            symbols = data["data"]

        elif isinstance(data.get("markets"), list):
            symbols = data["markets"]

        elif isinstance(data.get("result"), list):
            symbols = data["result"]

        elif isinstance(data.get("list"), list):
            symbols = data["list"]

    elif isinstance(data, list):
        symbols = data

    result = []

    blocked_status = {
        "BREAK",
        "BREAKING",
        "HALT",
        "HALTED",
        "CLOSED",
    }

    for item in symbols:

        symbol = ""
        status = ""

        if isinstance(item, str):

            symbol = item.strip().upper()

        elif isinstance(item, dict):

            symbol = str(
                item.get("symbol")
                or item.get("name")
                or item.get("market")
                or ""
            ).strip().upper()

            status = str(
                item.get("status")
                or ""
            ).strip().upper()

        if not symbol:
            continue

        if not symbol.endswith("USDT"):
            continue

        if status in blocked_status:
            continue

        result.append(symbol)

    result = sorted(set(result))

    return result[:MAX_MARKETS]


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

    quantity = (
        item.get("qty")
        or item.get("quantity")
        or item.get("q")
        or 0
    )

    timestamp = (
        item.get("time")
        or item.get("timestamp")
        or item.get("T")
    )

    try:
        price = float(price)
        quantity = float(quantity)

    except Exception:
        return None

    if timestamp is None:

        timestamp = time.time()

    else:

        try:
            timestamp = float(timestamp)

            if timestamp > 100000000000:
                timestamp /= 1000

        except Exception:
            timestamp = time.time()

    return {
        "price": price,
        "quantity": quantity,
        "time": timestamp,
    }


# ============================================================
# LOAD TRADES
# ============================================================

def load_trades(symbol):

    data = api_get(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": TRADE_LIMIT,
        },
    )

    trades = []

    if isinstance(data, list):

        trades = data

    elif isinstance(data, dict):

        if isinstance(data.get("data"), list):
            trades = data["data"]

        elif isinstance(data.get("trades"), list):
            trades = data["trades"]

        elif isinstance(data.get("result"), list):
            trades = data["result"]

        elif isinstance(data.get("list"), list):
            trades = data["list"]

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade:
            parsed.append(trade)

    parsed.sort(
        key=lambda x: x["time"]
    )

    return parsed


# ============================================================
# BUILD 5M CANDLES
# ============================================================

def build_candles(trades):

    buckets = {}

    for trade in trades:

        timestamp = trade["time"]

        bucket = int(
            timestamp // 300
        ) * 300

        price = trade["price"]
        quantity = trade["quantity"]

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": quantity,
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

            candle["volume"] += quantity

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ============================================================
# MOMENTUM
# ============================================================

def percent_change(old_price, new_price):

    if old_price == 0:
        return 0.0

    return (
        (new_price - old_price)
        / old_price
    ) * 100.0


def calculate_momentum(candles):

    if len(candles) < 14:
        return None

    current = candles[-1]

    m5_base = candles[-2]
    m15_base = candles[-4]
    m1h_base = candles[-13]

    m5 = percent_change(
        m5_base["close"],
        current["close"],
    )

    m15 = percent_change(
        m15_base["close"],
        current["close"],
    )

    m1h = percent_change(
        m1h_base["close"],
        current["close"],
    )

    return {
        "m5": m5,
        "m15": m15,
        "m1h": m1h,
    }


# ============================================================
# BREAKOUT LEVEL
# ============================================================

def get_breakout_level(candles):

    if len(candles) < 8:
        return 0.0

    lookback = candles[-7:-2]

    return max(
        candle["high"]
        for candle in lookback
    )


# ============================================================
# BREAKOUT
# ============================================================

def detect_breakout(candles):

    if len(candles) < 8:
        return False

    current = candles[-1]

    level = get_breakout_level(
        candles
    )

    if level <= 0:
        return False

    return current["close"] > level


# ============================================================
# HIGHER HIGH
# ============================================================

def detect_higher_high(candles):

    if len(candles) < 3:
        return False

    current = candles[-1]
    previous = candles[-2]

    return (
        current["high"] > previous["high"]
        and
        current["close"] >= previous["close"]
    )


# ============================================================
# RETEST
# ============================================================

def detect_retest(candles):

    if len(candles) < 9:
        return False

    level = get_breakout_level(
        candles
    )

    if level <= 0:
        return False

    previous = candles[-2]
    current = candles[-1]

    tolerance = level * 0.004

    previous_low_near = (
        abs(previous["low"] - level)
        <= tolerance
    )

    current_low_near = (
        abs(current["low"] - level)
        <= tolerance
    )

    condition_1 = (
        previous_low_near
        and
        current["close"] > level
    )

    condition_2 = (
        previous["close"] > level
        and
        current_low_near
        and
        current["close"] >= level
    )

    return (
        condition_1
        or
        condition_2
    )


# ============================================================
# PULLBACK
# ============================================================

def detect_pullback(candles):

    if len(candles) < 3:
        return False

    previous = candles[-2]
    current = candles[-1]

    previous_bearish = (
        previous["close"]
        < previous["open"]
    )

    current_bullish = (
        current["close"]
        > current["open"]
    )

    condition_1 = (
        previous_bearish
        and
        current_bullish
    )

    condition_2 = (
        current["low"]
        >= previous["low"]
    )

    return (
        condition_1
        or
        condition_2
    )


# ============================================================
# BULLISH CONFIRMATION
# ============================================================

def bullish_confirmation(candles):

    if len(candles) < 2:
        return False

    candle = candles[-1]

    candle_range = (
        candle["high"]
        - candle["low"]
    )

    if candle_range <= 0:
        return False

    body = abs(
        candle["close"]
        - candle["open"]
    )

    body_ratio = (
        body
        / candle_range
    )

    return (
        candle["close"] > candle["open"]
        and
        body_ratio >= 0.35
    )


# ============================================================
# SCORE
# ============================================================

def calculate_score(
    m5,
    m15,
    m1h,
    bullish,
    breakout,
    retest,
    pullback,
    higher_high,
):

    score = 0

    # 5M momentum
    if m5 > 0:
        score += 2

    if m5 >= 0.5:
        score += 1

    # 15M momentum
    if m15 >= 1.0:
        score += 2

    if m15 >= 3.0:
        score += 1

    # 1H momentum
    if m1h >= 1.0:
        score += 1

    if m1h >= 5.0:
        score += 1

    # Bullish candle
    if bullish:
        score += 2

    # Structure
    if breakout:
        score += 3

    if retest:
        score += 3

    if pullback:
        score += 1

    if higher_high:
        score += 1

    return score


# ============================================================
# RISK LEVELS
# ============================================================

def calculate_risk_levels(price):

    sl = price * (
        1
        - SL_PERCENT / 100
    )

    tp1 = price * (
        1
        + TP1_PERCENT / 100
    )

    tp2 = price * (
        1
        + TP2_PERCENT / 100
    )

    return sl, tp1, tp2


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(symbol):

    try:

        trades = load_trades(
            symbol
        )

        if len(trades) < 20:
            return None

        candles = build_candles(
            trades
        )

        if len(candles) < MIN_CANDLES:
            return None

        momentum = calculate_momentum(
            candles
        )

        if not momentum:
            return None

        m5 = momentum["m5"]
        m15 = momentum["m15"]
        m1h = momentum["m1h"]

        # Do not chase very fast 5M moves
        if m5 > MAX_5M_CHASE:
            return None

        # Minimum higher timeframe momentum
        if m15 < MIN_15M_MOMENTUM:
            return None

        if m1h < MIN_1H_MOMENTUM:
            return None

        breakout = detect_breakout(
            candles
        )

        retest = detect_retest(
            candles
        )

        pullback = detect_pullback(
            candles
        )

        higher_high = detect_higher_high(
            candles
        )

        bullish = bullish_confirmation(
            candles
        )

        score = calculate_score(
            m5=m5,
            m15=m15,
            m1h=m1h,
            bullish=bullish,
            breakout=breakout,
            retest=retest,
            pullback=pullback,
            higher_high=higher_high,
        )

        current_price = candles[-1]["close"]

        sl, tp1, tp2 = calculate_risk_levels(
            current_price
        )

        reasons = []

        if m5 > 0:
            reasons.append(
                "5M UP"
            )

        if m15 >= 1:
            reasons.append(
                "15M MOMENTUM"
            )

        if m1h >= 1:
            reasons.append(
                "1H MOMENTUM"
            )

        if bullish:
            reasons.append(
                "BULLISH CANDLE"
            )

        if breakout:
            reasons.append(
                "BREAKOUT"
            )

        if retest:
            reasons.append(
                "RETEST"
            )

        if pullback:
            reasons.append(
                "PULLBACK"
            )

        if higher_high:
            reasons.append(
                "HIGHER HIGH"
            )

        # ====================================================
        # CONFIRMED BUY
        # ====================================================

        if (
            score >= BUY_MIN_SCORE
            and
            breakout
            and
            retest
            and
            bullish
            and
            m15 >= MIN_15M_MOMENTUM
            and
            m1h >= MIN_1H_MOMENTUM
        ):

            return {
                "symbol": symbol,
                "status": "BUY",
                "score": score,
                "price": current_price,
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

        # ====================================================
        # WATCH
        # ====================================================

        if (
            score >= WATCH_MIN_SCORE
            and
            breakout
            and
            not retest
            and
            m15 >= MIN_15M_MOMENTUM
        ):

            return {
                "symbol": symbol,
                "status": "WATCH",
                "score": score,
                "price": current_price,
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

        return None

    except Exception as exc:

        print(
            f"{symbol} ERROR: {exc}"
        )

        return None


# ============================================================
# FORMAT RESULT
# ============================================================

def format_result(item, rank):

    status = item["status"]

    if status == "BUY":
        title = "🟢 CONFIRMED BUY"
    else:
        title = "🟡 WATCH"

    reasons = ", ".join(
        item["reasons"]
    )

    text = (
        f"{title}\n\n"
        f"#{rank}\n"
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item['score']}\n"
        f"💰 PRICE: {item['price']:.10f}\n\n"
        f"📈 5M: {item['m5']:+.2f}%\n"
        f"📊 15M: {item['m15']:+.2f}%\n"
        f"🕐 1H: {item['m1h']:+.2f}%\n\n"
        f"🚀 BREAKOUT: "
        f"{'YES' if item['breakout'] else 'NO'}\n"
        f"🔄 RETEST: "
        f"{'YES' if item['retest'] else 'NO'}\n"
        f"↩️ PULLBACK: "
        f"{'YES' if item['pullback'] else 'NO'}\n"
        f"📈 HIGHER HIGH: "
        f"{'YES' if item['higher_high'] else 'NO'}\n\n"
        f"🛑 SL: {item['sl']:.10f}\n"
        f"🎯 TP1: {item['tp1']:.10f}\n"
        f"🎯 TP2: {item['tp2']:.10f}\n\n"
        f"🧠 {reasons}"
    )

    return text


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        f"ATI CRYPTO BOT {VERSION}"
    )

    print(
        "Starting scanner..."
    )

    # --------------------------------------------------------
    # TELEGRAM STARTUP TEST
    # --------------------------------------------------------

    startup_message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 BREAKOUT + RETEST SCANNER\n\n"
        f"⏱ {utc_now()}\n"
        f"📡 TABDEAL API: CONNECTING...\n"
        f"🧪 SCANNER MODE ONLY\n"
        f"🔒 REAL TRADING: DISABLED"
    )

    send_telegram(
        startup_message
    )

    # --------------------------------------------------------
    # MARKET LOAD
    # --------------------------------------------------------

    try:

        markets = load_usdt_markets()

    except Exception as exc:

        error_message = (
            f"🔴 ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL MARKET SCAN FAILED\n\n"
            f"⏱ {utc_now()}\n"
            f"❌ ERROR:\n{exc}\n\n"
            f"📡 ENDPOINT:\n"
            f"/r/api/v1/exchangeInfo"
        )

        print(error_message)

        send_telegram(
            error_message
        )

        return

    if not markets:

        error_message = (
            f"🔴 ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ NO USDT MARKETS FOUND\n\n"
            f"⏱ {utc_now()}\n"
            f"📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: 0"
        )

        print(error_message)

        send_telegram(
            error_message
        )

        return

    # --------------------------------------------------------
    # HEARTBEAT
    # --------------------------------------------------------

    heartbeat = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 BREAKOUT + RETEST SCANNER\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n\n"
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}\n"
        f"🚫 5M CHASE LIMIT: {MAX_5M_CHASE}%\n\n"
        f"🔎 SCANNING..."
    )

    send_telegram(
        heartbeat
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    buys = []
    watches = []

    total = len(markets)

    for index, symbol in enumerate(
        markets,
        start=1,
    ):

        print(
            f"[{index}/{total}] {symbol}"
        )

        result = analyze_symbol(
            symbol
        )

        if result:

            if result["status"] == "BUY":
                buys.append(result)

            elif result["status"] == "WATCH":
                watches.append(result)

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
    # FINAL MESSAGE
    # --------------------------------------------------------

    message = (
        f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
        f"🚀 BREAKOUT + RETEST SCANNER\n\n"
        f"📡 TABDEAL API: OK\n"
        f"📊 USDT MARKETS: {len(markets)}\n\n"
        f"🟢 BUY MIN SCORE: {BUY_MIN_SCORE}\n"
        f"🟡 WATCH MIN SCORE: {WATCH_MIN_SCORE}\n"
        f"🚫 5M CHASE LIMIT: {MAX_5M_CHASE}%\n\n"
    )

    # --------------------------------------------------------
    # BUY RESULTS
    # --------------------------------------------------------

    if buys:

        message += (
            "━━━━━━━━━━━━━━━━━━\n"
            "🟢 CONFIRMED BUYS\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )

        for index, item in enumerate(
            buys,
            start=1,
        ):

            message += (
                format_result(
                    item,
                    index,
                )
                + "\n\n"
            )

    else:

        message += (
            "━━━━━━━━━━━━━━━━━━\n"
            "🟢 CONFIRMED BUY\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "❌ No confirmed BUY "
            "at this scan.\n\n"
        )

    # --------------------------------------------------------
    # WATCH RESULTS
    # --------------------------------------------------------

    if watches:

        message += (
            "━━━━━━━━━━━━━━━━━━\n"
            "🟡 WATCH LIST\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
        )

        for index, item in enumerate(
            watches,
            start=1,
        ):

            message += (
                format_result(
                    item,
                    index,
                )
                + "\n\n"
            )

    else:

        message += (
            "━━━━━━━━━━━━━━━━━━\n"
            "🟡 WATCH LIST\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "❌ No WATCH setup.\n\n"
        )

    # --------------------------------------------------------
    # FOOTER
    # --------------------------------------------------------

    message += (
        "━━━━━━━━━━━━━━━━━━\n"
        f"🕐 SCAN: {utc_now()}\n"
        "🔒 REAL TRADING: DISABLED\n"
        "🧪 SCANNER MODE ONLY"
    )

    print(message)

    send_telegram(
        message
    )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()
