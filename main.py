import os
import time
import json
import hashlib
from datetime import datetime, timezone

import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# ATI CRYPTO BOT V40.1.1
# CLEAN BREAKOUT + RETEST
# EARLY ENTRY
# ANTI-FAKE BREAKOUT
# ANTI-CHASE
# PAPER TRACKER
# ============================================================

VERSION = "V40.1.1"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

# ============================================================
# MARKET SCAN
# ============================================================

MAX_MARKETS = 1000

LIGHT_TRADE_LIMIT = 250
DEEP_TRADE_LIMIT = 1000

# CHANGED:
# Deep Scan = TOP 10
DEEP_SCAN_COUNT = 10

MAX_WORKERS = 24

REQUEST_TIMEOUT = 15

# 5 minute scan
SCAN_INTERVAL = 300


# ============================================================
# TELEGRAM
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
).strip()

TELEGRAM_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
).strip()


# ============================================================
# MODES
# ============================================================

PAPER_TRACKING = True

REAL_ORDERS = False


# ============================================================
# STATE
# ============================================================

STATE_FILE = "active_signal.json"


# ============================================================
# SIGNAL FILTERS
# ============================================================

CONFIRMED_MIN_SCORE = 16
EARLY_MIN_SCORE = 12
WATCH_MIN_SCORE = 11


# ============================================================
# ANTI CHASE
# ============================================================

CHASE_5M_LIMIT = 3.0


# ============================================================
# PAPER RISK
# ============================================================

SL_PERCENT = 0.50
TP1_PERCENT = 0.75
TP2_PERCENT = 1.25


# ============================================================
# PAPER LIMITS
# ============================================================

MAX_OPEN_PAPER = 20

DUPLICATE_COOLDOWN = 30 * 60


# ============================================================
# SESSION
# ============================================================

SESSION = requests.Session()

SESSION.headers.update(
    {
        "User-Agent": "ATI-Crypto-Bot-V40.1.1",
        "Accept": "application/json",
    }
)


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def utc_string():
    return utc_now().strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


def now_ts():
    return int(time.time())


# ============================================================
# TELEGRAM
# ============================================================

def telegram_send(message):

    if (
        not TELEGRAM_BOT_TOKEN
        or not TELEGRAM_CHAT_ID
    ):
        print("TELEGRAM CONFIG MISSING")
        print(message)
        return False

    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:

        r = SESSION.post(
            url,
            json=payload,
            timeout=REQUEST_TIMEOUT,
        )

        if r.status_code == 200:
            return True

        print(
            f"Telegram ERROR {r.status_code}: "
            f"{r.text[:300]}"
        )

    except Exception as e:

        print(
            f"Telegram ERROR: {e}"
        )

    return False


# ============================================================
# HTTP
# ============================================================

def api_get(
    path,
    params=None,
):

    url = BASE_URL + path

    try:

        r = SESSION.get(
            url,
            params=params or {},
            timeout=REQUEST_TIMEOUT,
        )

        if r.status_code != 200:
            return None

        return r.json()

    except Exception:

        return None


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_markets():

    data = api_get(
        "/r/api/v1/exchangeInfo",
        {
            "limit": 1000,
        },
    )

    if not data:
        return []

    symbols = []

    if isinstance(data, dict):

        raw = data.get(
            "symbols"
        )

        if isinstance(raw, list):

            symbols = raw

        elif isinstance(
            data.get("data"),
            dict,
        ):

            raw = data["data"].get(
                "symbols"
            )

            if isinstance(raw, list):
                symbols = raw

        elif isinstance(
            data.get("data"),
            list,
        ):

            symbols = data["data"]

    elif isinstance(data, list):

        symbols = data

    result = []

    for item in symbols:

        if not isinstance(
            item,
            dict,
        ):
            continue

        symbol = (
            item.get("symbol")
            or item.get("market")
            or item.get("code")
        )

        if not symbol:
            continue

        symbol = (
            str(symbol)
            .upper()
            .replace("_", "")
        )

        status = str(
            item.get(
                "status",
                "TRADING",
            )
        ).upper()

        if status not in (
            "TRADING",
            "ENABLED",
            "ACTIVE",
        ):
            continue

        if not symbol.endswith(
            "USDT"
        ):
            continue

        bad_suffixes = (
            "UPUSDT",
            "DOWNUSDT",
            "BULLUSDT",
            "BEARUSDT",
        )

        if symbol.endswith(
            bad_suffixes
        ):
            continue

        result.append(symbol)

    return sorted(
        list(
            set(result)
        )
    )[:MAX_MARKETS]


# ============================================================
# TRADES
# ============================================================

def get_trades(
    symbol,
    limit,
):

    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": limit,
        },
    )

    if not isinstance(
        data,
        list,
    ):
        return []

    result = []

    for x in data:

        if not isinstance(
            x,
            dict,
        ):
            continue

        try:

            price = float(
                x.get(
                    "price",
                    0,
                )
            )

            qty = float(
                x.get(
                    "qty",
                    0,
                )
            )

            ts = x.get(
                "time"
            )

            if ts is None:

                ts = x.get(
                    "timestamp"
                )

            ts = int(ts)

            if ts < 10000000000:
                ts *= 1000

            if price <= 0:
                continue

            result.append(
                {
                    "price": price,
                    "qty": qty,
                    "time": ts,
                }
            )

        except Exception:

            continue

    result.sort(
        key=lambda x: x["time"]
    )

    return result


# ============================================================
# CANDLE AGGREGATION
# ============================================================

def build_candles(
    trades,
    minutes,
):

    if not trades:
        return []

    bucket_ms = (
        minutes
        * 60
        * 1000
    )

    buckets = {}

    for t in trades:

        bucket = (
            t["time"]
            // bucket_ms
        ) * bucket_ms

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": t["price"],
                "high": t["price"],
                "low": t["price"],
                "close": t["price"],
                "volume": t["qty"],
            }

        else:

            c = buckets[bucket]

            c["high"] = max(
                c["high"],
                t["price"],
            )

            c["low"] = min(
                c["low"],
                t["price"],
            )

            c["close"] = t["price"]

            c["volume"] += t["qty"]

    candles = list(
        buckets.values()
    )

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


# ============================================================
# HELPERS
# ============================================================

def pct_change(
    a,
    b,
):

    if a == 0:
        return 0.0

    return (
        (b - a)
        / a
    ) * 100.0


def body_size(c):

    return abs(
        c["close"]
        - c["open"]
    )


def candle_range(c):

    return max(
        c["high"]
        - c["low"],
        1e-12,
    )


def upper_wick(c):

    return (
        c["high"]
        - max(
            c["open"],
            c["close"],
        )
    )


def remove_current_candle(
    candles,
    minutes,
):

    if not candles:
        return []

    current_bucket = (
        int(
            time.time()
            * 1000
        )
        // (
            minutes
            * 60
            * 1000
        )
    ) * (
        minutes
        * 60
        * 1000
    )

    return [
        c
        for c in candles
        if c["time"]
        < current_bucket
    ]


# ============================================================
# STRUCTURE
# ============================================================

def recent_high(
    candles,
    lookback=12,
):

    if len(candles) < (
        lookback + 1
    ):
        return None

    section = candles[
        -lookback - 1:-1
    ]

    return max(
        x["high"]
        for x in section
    )


def is_clean_candle(c):

    rng = candle_range(c)

    body = body_size(c)

    if rng <= 0:
        return False

    body_ratio = (
        body / rng
    )

    return (
        c["close"]
        > c["open"]
        and body_ratio >= 0.45
        and (
            upper_wick(c)
            / rng
        ) <= 0.40
    )


def bullish_structure(
    candles,
):

    if len(candles) < 8:
        return False

    a = candles[-6]
    b = candles[-3]
    c = candles[-1]

    return (
        b["high"]
        >= a["high"]
        and c["high"]
        >= b["high"]
        and c["close"]
        >= b["close"]
    )


def breakout_confirmed(
    candles,
):

    if len(candles) < 14:
        return False

    resistance = recent_high(
        candles,
        12,
    )

    if resistance is None:
        return False

    last = candles[-1]

    return (
        last["close"]
        > resistance
        and last["close"]
        > last["open"]
    )


def retest_hold(
    candles,
):

    if len(candles) < 16:
        return False

    resistance = recent_high(
        candles[:-2],
        12,
    )

    if resistance is None:
        return False

    previous = candles[-2]
    last = candles[-1]

    touched = (
        previous["low"]
        <= resistance * 1.003
    )

    held = (
        last["close"]
        > resistance
    )

    return (
        touched
        and held
    )


def near_resistance(
    candles,
):

    if len(candles) < 14:
        return False

    resistance = recent_high(
        candles,
        12,
    )

    last = candles[-1]

    if resistance is None:
        return False

    distance = (
        abs(
            resistance
            - last["close"]
        )
        / last["close"]
    ) * 100

    return distance <= 1.5


# ============================================================
# TIMEFRAME STATS
# ============================================================

def timeframe_stats(
    candles,
):

    if len(candles) < 8:

        return {
            "change": 0.0,
            "healthy": False,
        }

    last = candles[-1]

    start_index = max(
        0,
        len(candles) - 4,
    )

    start = candles[
        start_index
    ]["open"]

    change = pct_change(
        start,
        last["close"],
    )

    healthy = (
        last["close"]
        > last["open"]
        and change > 0
    )

    return {
        "change": change,
        "healthy": healthy,
    }


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(
    symbol,
    trades,
):

    if len(trades) < 40:
        return None

    candles5 = build_candles(
        trades,
        5,
    )

    candles5 = remove_current_candle(
        candles5,
        5,
    )

    candles15 = build_candles(
        trades,
        15,
    )

    candles15 = remove_current_candle(
        candles15,
        15,
    )

    candles30 = build_candles(
        trades,
        30,
    )

    candles30 = remove_current_candle(
        candles30,
        30,
    )

    if (
        len(candles5) < 20
        or len(candles15) < 8
        or len(candles30) < 5
    ):
        return None

    last5 = candles5[-1]

    price = last5["close"]

    if price <= 0:
        return None

    s5 = timeframe_stats(
        candles5
    )

    s15 = timeframe_stats(
        candles15
    )

    s30 = timeframe_stats(
        candles30
    )

    change5 = s5["change"]
    change15 = s15["change"]
    change30 = s30["change"]

    score = 0

    reasons = []

    # 5M CLEAN
    if is_clean_candle(
        last5
    ):

        score += 2
        reasons.append(
            "5M CLEAN"
        )

    # 15M UP
    if change15 > 0.5:

        score += 2
        reasons.append(
            "15M UP"
        )

    # 15M > 5M
    if change15 > change5:

        score += 2
        reasons.append(
            "15M > 5M"
        )

    # 30M HEALTHY
    if change30 > 0.5:

        score += 2
        reasons.append(
            "30M HEALTHY"
        )

    # MULTI TF
    positive_tf = sum(
        [
            change5 > 0,
            change15 > 0,
            change30 > 0,
        ]
    )

    if positive_tf >= 3:

        score += 2
        reasons.append(
            "MULTI TF"
        )

    # NEAR RESISTANCE
    if near_resistance(
        candles5
    ):

        score += 1
        reasons.append(
            "NEAR RESISTANCE"
        )

    # BREAKOUT
    breakout = breakout_confirmed(
        candles5
    )

    if breakout:

        score += 2
        reasons.append(
            "BREAKOUT CONFIRMED"
        )

    # RETEST
    retest = retest_hold(
        candles5
    )

    if retest:

        score += 2
        reasons.append(
            "RETEST"
        )

    # HOLD
    resistance = recent_high(
        candles5,
        12,
    )

    hold = False

    if resistance:

        hold = (
            price
            >= resistance * 0.997
        )

    if hold:

        score += 1
        reasons.append(
            "HOLD"
        )

    # BULLISH STRUCTURE
    if bullish_structure(
        candles5
    ):

        score += 1
        reasons.append(
            "BULLISH STRUCTURE"
        )

    # ANTI CHASE
    if change5 > CHASE_5M_LIMIT:
        return None

    # BASIC TREND
    if change15 <= 0:
        return None

    if change30 <= 0:
        return None

    # SIGNAL TYPE
    confirmed = (
        score
        >= CONFIRMED_MIN_SCORE
        and breakout
        and retest
        and hold
    )

    early = (
        score
        >= EARLY_MIN_SCORE
        and breakout
        and hold
        and not confirmed
    )

    watch = (
        score
        >= WATCH_MIN_SCORE
        and breakout
        and not confirmed
        and not early
    )

    if not (
        confirmed
        or early
        or watch
    ):
        return None

    # PRICE LEVELS
    sl = (
        price
        * (
            1
            - SL_PERCENT / 100
        )
    )

    tp1 = (
        price
        * (
            1
            + TP1_PERCENT / 100
        )
    )

    tp2 = (
        price
        * (
            1
            + TP2_PERCENT / 100
        )
    )

    return {
        "symbol": symbol,
        "price": price,
        "score": score,
        "change5": change5,
        "change15": change15,
        "change30": change30,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "confirmed": confirmed,
        "early": early,
        "watch": watch,
        "reasons": reasons,
        "timestamp": now_ts(),
    }


# ============================================================
# LIGHT SCAN
# ============================================================

def light_scan(
    symbol,
):

    trades = get_trades(
        symbol,
        LIGHT_TRADE_LIMIT,
    )

    if not trades:
        return None

    candles = build_candles(
        trades,
        5,
    )

    candles = remove_current_candle(
        candles,
        5,
    )

    if len(candles) < 8:
        return None

    last = candles[-1]

    if last["open"] <= 0:
        return None

    change = pct_change(
        candles[-4]["open"],
        last["close"],
    )

    if change <= 0:
        return None

    momentum = (
        min(
            max(
                change,
                0,
            ),
            5,
        )
        * 2
    )

    clean = (
        1
        if is_clean_candle(last)
        else 0
    )

    return {
        "symbol": symbol,
        "rank_score": (
            momentum
            + clean
        ),
    }


# ============================================================
# DEEP SCAN
# ============================================================

def deep_scan(
    symbol,
):

    trades = get_trades(
        symbol,
        DEEP_TRADE_LIMIT,
    )

    if not trades:
        return None

    return analyze_symbol(
        symbol,
        trades,
    )


# ============================================================
# STATE
# ============================================================

def default_state():

    return {
        "open": {},
        "closed": [],
        "seen": {},
        "stats": {
            "trades": 0,
            "tp1": 0,
            "tp2": 0,
            "sl": 0,
        },
    }


def load_state():

    if not os.path.exists(
        STATE_FILE
    ):
        return default_state()

    try:

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if not isinstance(
            data,
            dict,
        ):
            return default_state()

        state = default_state()

        state.update(data)

        if not isinstance(
            state.get("open"),
            dict,
        ):
            state["open"] = {}

        if not isinstance(
            state.get("closed"),
            list,
        ):
            state["closed"] = []

        if not isinstance(
            state.get("seen"),
            dict,
        ):
            state["seen"] = {}

        if not isinstance(
            state.get("stats"),
            dict,
        ):
            state["stats"] = (
                default_state()["stats"]
            )

        return state

    except Exception as e:

        print(
            f"STATE LOAD ERROR: {e}"
        )

        return default_state()


def save_state(
    state,
):

    try:

        temp = (
            STATE_FILE
            + ".tmp"
        )

        with open(
            temp,
            "w",
            encoding="utf-8",
        ) as f:

            json.dump(
                state,
                f,
                ensure_ascii=False,
                indent=2,
            )

        os.replace(
            temp,
            STATE_FILE,
        )

    except Exception as e:

        print(
            f"STATE SAVE ERROR: {e}"
        )


# ============================================================
# SIGNAL ID
# ============================================================

def signal_id(
    signal,
):

    raw = (
        f"{signal['symbol']}-"
        f"{round(signal['price'], 12)}-"
        f"{signal['timestamp'] // 300}"
    )

    return hashlib.sha256(
        raw.encode()
    ).hexdigest()[:16]


# ============================================================
# PAPER REGISTER
# ============================================================

def register_paper_signal(
    signal,
    state,
):

    symbol = signal["symbol"]

    if symbol in state["open"]:
        return False

    if (
        len(state["open"])
        >= MAX_OPEN_PAPER
    ):
        return False

    last_seen = state[
        "seen"
    ].get(
        symbol,
        0,
    )

    if (
        now_ts()
        - last_seen
        < DUPLICATE_COOLDOWN
    ):
        return False

    sid = signal_id(
        signal
    )

    state["open"][symbol] = {

        "id": sid,

        "symbol": symbol,

        "side": "BUY",

        "entry": signal["price"],

        "sl": signal["sl"],

        "tp1": signal["tp1"],

        "tp2": signal["tp2"],

        "score": signal["score"],

        "type": (
            "CONFIRMED BUY"
            if signal["confirmed"]
            else (
                "EARLY ENTRY"
                if signal["early"]
                else "WATCH"
            )
        ),

        "opened_at": now_ts(),

        "tp1_hit": False,
    }

    state["seen"][symbol] = (
        now_ts()
    )

    return True


# ============================================================
# PAPER POSITION
# ============================================================

def update_paper_position(
    position,
    price,
):

    if price <= 0:
        return None

    sl = float(
        position["sl"]
    )

    tp1 = float(
        position["tp1"]
    )

    tp2 = float(
        position["tp2"]
    )

    if price <= sl:
        return "SL"

    if price >= tp2:
        return "TP2"

    if (
        price >= tp1
        and not position.get(
            "tp1_hit",
            False,
        )
    ):
        return "TP1"

    return None


def close_position(
    symbol,
    result,
    price,
    state,
):

    position = state[
        "open"
    ].get(
        symbol
    )

    if not position:
        return

    position[
        "close_price"
    ] = price

    position[
        "result"
    ] = result

    position[
        "closed_at"
    ] = now_ts()

    if result == "TP1":

        position[
            "tp1_hit"
        ] = True

        return

    if result == "TP2":

        state["stats"][
            "tp2"
        ] += 1

        state["stats"][
            "trades"
        ] += 1

    elif result == "SL":

        state["stats"][
            "sl"
        ] += 1

        state["stats"][
            "trades"
        ] += 1

    else:

        return

    state["closed"].append(
        position
    )

    state["open"].pop(
        symbol,
        None,
    )


# ============================================================
# CURRENT PRICE
# ============================================================

def get_current_price(
    symbol,
):

    data = api_get(
        "/r/api/v1/depth",
        {
            "symbol": symbol,
            "limit": 1,
        },
    )

    if not isinstance(
        data,
        dict,
    ):
        return None

    bids = data.get(
        "bids"
    )

    if not isinstance(
        bids,
        list,
    ) or not bids:
        return None

    try:

        return float(
            bids[0][0]
        )

    except Exception:

        return None


# ============================================================
# UPDATE OPEN POSITIONS
# ============================================================

def update_open_positions(
    state,
):

    if not state["open"]:
        return []

    symbols = list(
        state["open"].keys()
    )

    results = []

    def worker(symbol):

        return (
            symbol,
            get_current_price(
                symbol
            ),
        )

    with ThreadPoolExecutor(
        max_workers=min(
            12,
            len(symbols),
        )
    ) as executor:

        futures = [
            executor.submit(
                worker,
                symbol,
            )
            for symbol in symbols
        ]

        for future in as_completed(
            futures
        ):

            try:

                symbol, price = (
                    future.result()
                )

                if price is None:
                    continue

                position = state[
                    "open"
                ].get(
                    symbol
                )

                if not position:
                    continue

                result = (
                    update_paper_position(
                        position,
                        price,
                    )
                )

                if result == "TP1":

                    position[
                        "tp1_hit"
                    ] = True

                    results.append(
                        {
                            "symbol": symbol,
                            "result": "TP1",
                            "price": price,
                            "entry": position[
                                "entry"
                            ],
                        }
                    )

                elif result == "TP2":

                    results.append(
                        {
                            "symbol": symbol,
                            "result": "TP2",
                            "price": price,
                            "entry": position[
                                "entry"
                            ],
                        }
                    )

                    close_position(
                        symbol,
                        "TP2",
                        price,
                        state,
                    )

                elif result == "SL":

                    results.append(
                        {
                            "symbol": symbol,
                            "result": "SL",
                            "price": price,
                            "entry": position[
                                "entry"
                            ],
                        }
                    )

                    close_position(
                        symbol,
                        "SL",
                        price,
                        state,
                    )

            except Exception as e:

                print(
                    "POSITION UPDATE ERROR:",
                    e,
                )

    return results


# ============================================================
# FORMAT PRICE
# ============================================================

def fmt_price(
    value,
):

    value = float(
        value
    )

    if value >= 1000:
        return f"{value:.2f}"

    if value >= 1:
        return f"{value:.6f}"

    if value >= 0.01:
        return f"{value:.8f}"

    return f"{value:.10f}"


# ============================================================
# SIGNAL MESSAGE
# ============================================================

def signal_block(
    signal,
    number,
    label,
):

    reasons = " + ".join(
        signal["reasons"]
    )

    return (
        f"#{number}\n"
        f"🪙 {signal['symbol']}\n"
        f"⭐ SCORE: {signal['score']}\n"
        f"💰 PRICE: "
        f"{fmt_price(signal['price'])}\n"
        f"📈 5M: "
        f"{signal['change5']:+.2f}%\n"
        f"📊 15M: "
        f"{signal['change15']:+.2f}%\n"
        f"📊 30M: "
        f"{signal['change30']:+.2f}%\n"
        f"🛑 SL: "
        f"{fmt_price(signal['sl'])}\n"
        f"🎯 TP1: "
        f"{fmt_price(signal['tp1'])}\n"
        f"🎯 TP2: "
        f"{fmt_price(signal['tp2'])}\n"
        f"📌 {reasons}"
    )


# ============================================================
# STATS
# ============================================================

def stats_text(
    state,
):

    stats = state["stats"]

    trades = int(
        stats.get(
            "trades",
            0,
        )
    )

    tp1 = int(
        stats.get(
            "tp1",
            0,
        )
    )

    tp2 = int(
        stats.get(
            "tp2",
            0,
        )
    )

    sl = int(
        stats.get(
            "sl",
            0,
        )
    )

    closed = tp2 + sl

    if closed > 0:

        win_rate = (
            tp2
            / closed
        ) * 100

    else:

        win_rate = 0.0

    open_count = len(
        state["open"]
    )

    return (
        f"📊 PAPER STATS\n"
        f"Trades: {trades} | "
        f"TP2: {tp2} | "
        f"SL: {sl} | "
        f"OPEN: {open_count}\n"
        f"🎯 TP1 events: {tp1}\n"
        f"📈 Win Rate: "
        f"{win_rate:.1f}%"
    )


# ============================================================
# TRACKER MESSAGE
# ============================================================

def tracker_message(
    events,
):

    if not events:
        return ""

    lines = [
        "📡 ATI PAPER TRACKER V40.1.1",
        "",
    ]

    for e in events:

        symbol = e[
            "symbol"
        ]

        result = e[
            "result"
        ]

        price = fmt_price(
            e["price"]
        )

        if result == "TP1":

            lines.append(
                f"🟡 TP1 HIT — "
                f"{symbol}"
            )

        elif result == "TP2":

            lines.append(
                f"🟢 TP2 HIT — "
                f"{symbol}"
            )

        elif result == "SL":

            lines.append(
                f"🔴 SL HIT — "
                f"{symbol}"
            )

        lines.append(
            f"💰 PRICE: {price}"
        )

    return "\n".join(
        lines
    )


# ============================================================
# MAIN SCAN
# ============================================================

def run_scan(
    state,
):

    started = time.time()

    print(
        f"\nATI CRYPTO BOT "
        f"{VERSION}"
    )

    print(
        "TABDEAL API: "
        "CONNECTING..."
    )

    markets = get_markets()

    if not markets:

        msg = (
            f"⚠️ ATI CRYPTO BOT "
            f"{VERSION}\n\n"
            f"❌ TABDEAL MARKET "
            f"DATA ERROR\n"
            f"🕐 {utc_string()}"
        )

        telegram_send(
            msg
        )

        return

    print(
        "TABDEAL API: OK"
    )

    print(
        f"USDT MARKETS: "
        f"{len(markets)}"
    )

    # ========================================================
    # LIGHT SCAN
    # ========================================================

    ranked = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {
            executor.submit(
                light_scan,
                symbol,
            ): symbol
            for symbol in markets
        }

        for future in as_completed(
            future_map
        ):

            try:

                result = (
                    future.result()
                )

                if result:

                    ranked.append(
                        result
                    )

            except Exception:

                continue

    ranked.sort(
        key=lambda x:
        x["rank_score"],
        reverse=True,
    )

    # ========================================================
    # TOP 10
    # ========================================================

    top_symbols = [
        x["symbol"]
        for x in ranked[
            :DEEP_SCAN_COUNT
        ]
    ]

    print(
        f"DEEP SCAN: TOP "
        f"{len(top_symbols)}"
    )

    # ========================================================
    # DEEP SCAN
    # ========================================================

    confirmed = []

    early = []

    watch = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        future_map = {
            executor.submit(
                deep_scan,
                symbol,
            ): symbol
            for symbol in top_symbols
        }

        for future in as_completed(
            future_map
        ):

            try:

                result = (
                    future.result()
                )

                if not result:
                    continue

                if result[
                    "confirmed"
                ]:

                    confirmed.append(
                        result
                    )

                elif result[
                    "early"
                ]:

                    early.append(
                        result
                    )

                elif result[
                    "watch"
                ]:

                    watch.append(
                        result
                    )

            except Exception as e:

                print(
                    f"DEEP ERROR: {e}"
                )

    # ========================================================
    # SORT
    # ========================================================

    confirmed.sort(
        key=lambda x:
        x["score"],
        reverse=True,
    )

    early.sort(
        key=lambda x:
        x["score"],
        reverse=True,
    )

    watch.sort(
        key=lambda x:
        x["score"],
        reverse=True,
    )

    confirmed = confirmed[:3]

    early = early[:3]

    watch = watch[:4]

    # ========================================================
    # REGISTER PAPER
    # ========================================================

    if PAPER_TRACKING:

        for group in (
            confirmed,
            early,
        ):

            for signal in group:

                register_paper_signal(
                    signal,
                    state,
                )

    # ========================================================
    # TELEGRAM MESSAGE
    # ========================================================

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}"
    )

    lines.append(
        "🎯 CLEAN BREAKOUT + RETEST"
    )

    lines.append(
        "🚀 EARLY ENTRY"
    )

    lines.append(
        "🛡 ANTI-FAKE BREAKOUT"
    )

    lines.append(
        "🚫 ANTI-CHASE"
    )

    lines.append("")

    lines.append(
        "📡 TABDEAL API: OK"
    )

    lines.append(
        f"📊 USDT MARKETS: "
        f"{len(markets)}"
    )

    lines.append(
        f"🎯 DEEP SCAN: TOP "
        f"{DEEP_SCAN_COUNT}"
    )

    lines.append(
        f"🕐 {utc_string()}"
    )

    lines.append("")

    # ========================================================
    # CONFIRMED
    # ========================================================

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "🟢 CONFIRMED BUY"
    )

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    if confirmed:

        for i, signal in enumerate(
            confirmed,
            1,
        ):

            lines.append(
                signal_block(
                    signal,
                    i,
                    "CONFIRMED BUY",
                )
            )

            lines.append("")

    else:

        lines.append(
            "NONE"
        )

        lines.append("")

    # ========================================================
    # EARLY
    # ========================================================

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "⚡ EARLY ENTRY"
    )

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    if early:

        for i, signal in enumerate(
            early,
            1,
        ):

            lines.append(
                signal_block(
                    signal,
                    i,
                    "EARLY ENTRY",
                )
            )

            lines.append("")

    else:

        lines.append(
            "NONE"
        )

        lines.append("")

    # ========================================================
    # WATCH
    # ========================================================

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        "🟡 WATCH"
    )

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    if watch:

        for i, signal in enumerate(
            watch,
            1,
        ):

            lines.append(
                signal_block(
                    signal,
                    i,
                    "WATCH",
                )
            )

            lines.append("")

    else:

        lines.append(
            "NONE"
        )

        lines.append("")

    # ========================================================
    # STATS
    # ========================================================

    lines.append(
        "━━━━━━━━━━━━━━━━━━"
    )

    lines.append(
        stats_text(
            state
        )
    )

    lines.append(
        f"⏱ Scan time: "
        f"{time.time() - started:.1f} sec"
    )

    lines.append(
        "🔧 REAL ORDERS: DISABLED"
    )

    message = "\n".join(
        lines
    )

    telegram_send(
        message
    )

    save_state(
        state
    )

    print(
        message
    )


# ============================================================
# MAIN LOOP
# ============================================================

def main():

    print(
        f"Starting ATI CRYPTO BOT "
        f"{VERSION}"
    )

    print(
        "PAPER TRACKING: ON"
    )

    print(
        "REAL ORDERS: DISABLED"
    )

    state = load_state()

    # ========================================================
    # START TELEGRAM
    # ========================================================

    telegram_send(
        f"⚡ ATI CRYPTO BOT "
        f"{VERSION}\n\n"
        f"📡 TABDEAL API: "
        f"CONNECTING...\n"
        f"📊 SCAN: STARTING\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED CANDLE: YES\n"
        f"📊 PAPER TRACKING: ON\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🕐 {utc_string()}"
    )

    # ========================================================
    # LOOP
    # ========================================================

    while True:

        try:

            # ------------------------------------------------
            # UPDATE PAPER POSITIONS
            # ------------------------------------------------

            events = (
                update_open_positions(
                    state
                )
            )

            if events:

                telegram_send(
                    tracker_message(
                        events
                    )
                    + "\n\n"
                    + stats_text(
                        state
                    )
                )

                save_state(
                    state
                )

            # ------------------------------------------------
            # NEW SCAN
            # ------------------------------------------------

            run_scan(
                state
            )

            save_state(
                state
            )

            # ------------------------------------------------
            # NEXT 5M SCAN
            # ------------------------------------------------

            now = time.time()

            next_boundary = (
                (
                    int(now)
                    // SCAN_INTERVAL
                )
                + 1
            ) * SCAN_INTERVAL

            wait_seconds = (
                next_boundary
                - now
            )

            if wait_seconds < 5:
                wait_seconds = 5

            print(
                f"NEXT SCAN IN "
                f"{wait_seconds:.0f} SEC"
            )

            time.sleep(
                wait_seconds
            )

        except KeyboardInterrupt:

            print(
                "BOT STOPPED"
            )

            save_state(
                state
            )

            break

        except Exception as e:

            print(
                f"MAIN LOOP ERROR: "
                f"{e}"
            )

            telegram_send(
                f"⚠️ ATI BOT "
                f"{VERSION}\n\n"
                f"❌ MAIN LOOP ERROR\n"
                f"{str(e)[:500]}\n\n"
                f"🔧 REAL ORDERS: "
                f"DISABLED"
            )

            time.sleep(30)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
