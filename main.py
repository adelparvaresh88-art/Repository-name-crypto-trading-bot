import os
import time
import json
import requests
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ATI CRYPTO BOT V39.6.9
# AUTO TOP 10
# TELEGRAM HEARTBEAT
# EARLY ENTRY + CONFIRMED BREAKOUT
# ============================================================

VERSION = "V39.6.9"

BASE_URL = "https://api1.tabdeal.org"
TIMEFRAME = "5m"

CANDLE_LIMIT = 180
MAX_MARKETS = 1000
TOP_SCAN_MARKETS = 10

REQUEST_TIMEOUT = 10
MAX_WORKERS = 20

TOP_CONFIRMED = 3
TOP_EARLY = 5
TOP_WATCH = 5

CONFIRMED_MIN_SCORE = 11
EARLY_MIN_SCORE = 7
WATCH_MIN_SCORE = 6

BREAKOUT_BUFFER = 0.05

PAPER_TRACKING = True
MAX_HISTORY = 500
STATE_FILE = "paper_trades.json"

LIVE_TRADING = False

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

session = requests.Session()
session.headers.update({
    "User-Agent": f"ATI-Crypto-Bot/{VERSION}",
    "Accept": "application/json",
})


# ============================================================
# TIME
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM CONFIG ERROR: token/chat_id missing")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "disable_web_page_preview": True,
    }

    try:
        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        print(
            f"TELEGRAM STATUS: {response.status_code} "
            f"| {response.text[:300]}"
        )

        return response.ok

    except Exception as e:
        print(f"TELEGRAM ERROR: {e}")
        return False


# ============================================================
# API
# ============================================================

def api_get(path, params=None):
    url = BASE_URL + path

    try:
        response = session.get(
            url,
            params=params,
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code != 200:
            print(
                f"API ERROR {response.status_code}: "
                f"{path} | {response.text[:200]}"
            )
            return None

        return response.json()

    except Exception as e:
        print(f"API EXCEPTION: {path} | {e}")
        return None


# ============================================================
# MARKET PARSER
# ============================================================

def extract_exchange_symbols(data):
    result = []

    if isinstance(data, list):
        for item in data:
            if isinstance(item, str):
                result.append(item.upper())

            elif isinstance(item, dict):
                for key in (
                    "symbol",
                    "market",
                    "code",
                    "name",
                ):
                    value = item.get(key)
                    if value:
                        result.append(str(value).upper())
                        break

    elif isinstance(data, dict):
        for key in (
            "symbols",
            "data",
            "result",
            "markets",
            "items",
        ):
            value = data.get(key)

            if isinstance(value, list):
                result.extend(
                    extract_exchange_symbols(value)
                )

            elif isinstance(value, dict):
                result.extend(
                    extract_exchange_symbols(value)
                )

    return list(dict.fromkeys(result))


# ============================================================
# MARKETS
# ============================================================

def get_markets():
    data = api_get("/r/api/v1/exchangeInfo")

    if data is None:
        return []

    symbols = extract_exchange_symbols(data)

    usdt = []

    for symbol in symbols:
        symbol = symbol.upper()

        if symbol.endswith("USDT"):
            usdt.append(symbol)

    return list(dict.fromkeys(usdt))[:MAX_MARKETS]


# ============================================================
# TRADES
# ============================================================

def get_trades(symbol):
    data = api_get(
        "/r/api/v1/trades",
        params={
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if data is None:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in (
            "data",
            "result",
            "trades",
            "items",
        ):
            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


# ============================================================
# TRADE PARSER
# ============================================================

def parse_trade(item):
    if not isinstance(item, dict):
        return None

    price = None
    qty = None
    timestamp = None

    for key in (
        "price",
        "p",
        "lastPrice",
    ):
        if item.get(key) is not None:
            price = item.get(key)
            break

    for key in (
        "qty",
        "quantity",
        "q",
        "amount",
        "volume",
    ):
        if item.get(key) is not None:
            qty = item.get(key)
            break

    for key in (
        "time",
        "timestamp",
        "ts",
        "T",
        "createdAt",
    ):
        if item.get(key) is not None:
            timestamp = item.get(key)
            break

    try:
        price = float(price)
    except Exception:
        return None

    try:
        qty = float(qty or 0)
    except Exception:
        qty = 0.0

    try:
        timestamp = int(float(timestamp))
    except Exception:
        timestamp = int(time.time() * 1000)

    if timestamp < 100000000000:
        timestamp *= 1000

    return {
        "price": price,
        "qty": qty,
        "time": timestamp,
    }


# ============================================================
# 5M CANDLES
# ============================================================

def build_5m_candles(trades):
    candles = {}

    for raw in trades:
        trade = parse_trade(raw)

        if not trade:
            continue

        bucket = (
            trade["time"] // 300000
        ) * 300000

        price = trade["price"]
        qty = trade["qty"]

        if bucket not in candles:
            candles[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": qty,
            }
        else:
            candle = candles[bucket]

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

    result = sorted(
        candles.values(),
        key=lambda x: x["time"],
    )

    return result[-CANDLE_LIMIT:]


# ============================================================
# AGGREGATE
# ============================================================

def aggregate(candles, factor):
    if not candles:
        return []

    result = []

    for i in range(
        0,
        len(candles),
        factor,
    ):
        chunk = candles[i:i + factor]

        if len(chunk) < factor:
            continue

        result.append({
            "time": chunk[0]["time"],
            "open": chunk[0]["open"],
            "high": max(
                x["high"] for x in chunk
            ),
            "low": min(
                x["low"] for x in chunk
            ),
            "close": chunk[-1]["close"],
            "volume": sum(
                x["volume"] for x in chunk
            ),
        })

    return result


# ============================================================
# PERCENT
# ============================================================

def pct(a, b):
    try:
        if b == 0:
            return 0.0

        return ((a - b) / b) * 100

    except Exception:
        return 0.0


# ============================================================
# ANALYZE
# ============================================================

def analyze_symbol(symbol, trades=None):
    if trades is None:
        trades = get_trades(symbol)

    candles = build_5m_candles(trades)

    if len(candles) < 20:
        return None

    candles = candles[:-1]

    if len(candles) < 20:
        return None

    current = candles[-1]
    previous = candles[-2]

    c15 = aggregate(candles, 3)
    c60 = aggregate(candles, 12)

    if len(c15) < 3 or len(c60) < 2:
        return None

    change5 = pct(
        current["close"],
        previous["close"],
    )

    change15 = pct(
        c15[-1]["close"],
        c15[-2]["close"],
    )

    change60 = pct(
        c60[-1]["close"],
        c60[-2]["close"],
    )

    volumes = [
        x["volume"]
        for x in candles[-21:-1]
    ]

    average_volume = (
        sum(volumes) / len(volumes)
        if volumes
        else 0
    )

    volume_ratio = (
        current["volume"] / average_volume
        if average_volume > 0
        else 0
    )

    lookback = candles[-21:-1]

    resistance = max(
        x["high"] for x in lookback
    )

    resistance_distance = pct(
        resistance,
        current["close"],
    )

    breakout = (
        current["close"]
        >= resistance
        * (1 + BREAKOUT_BUFFER / 100)
    )

    retest = False

    if len(candles) >= 3:
        old = candles[-2]

        retest = (
            old["high"] >= resistance * 0.998
            and current["close"] > old["close"]
            and current["close"] > current["open"]
        )

    candle_range = (
        current["high"]
        - current["low"]
    )

    body = abs(
        current["close"]
        - current["open"]
    )

    strong_bullish = (
        candle_range > 0
        and current["close"] > current["open"]
        and body / candle_range >= 0.55
    )

    score = 0

    if change5 > 0.20:
        score += 2

    if change15 > 0.50:
        score += 2

    if change60 > 1.00:
        score += 2

    if volume_ratio >= 1.2:
        score += 2

    if strong_bullish:
        score += 1

    if breakout:
        score += 3

    if retest:
        score += 2

    if 0 <= resistance_distance <= 1.5:
        score += 1

    confirmed = (
        score >= CONFIRMED_MIN_SCORE
        and 0.2 <= change5 <= 4
        and change15 >= 0.5
        and change60 >= 1
        and 1.2 <= volume_ratio <= 8
        and (breakout or retest)
    )

    early = (
        score >= EARLY_MIN_SCORE
        and -0.1 <= change5 <= 3
        and change15 >= 0.3
        and change60 >= 0.6
        and 0.6 <= volume_ratio <= 8
        and 0.03 <= resistance_distance <= 1.8
    )

    watch = (
        score >= WATCH_MIN_SCORE
        and -0.1 <= change5 <= 3
        and change15 >= 0.2
        and change60 >= 0.5
        and 0.6 <= volume_ratio <= 8
        and 0.03 <= resistance_distance <= 2.2
    )

    if confirmed:
        signal = "CONFIRMED BUY"
    elif early:
        signal = "EARLY ENTRY"
    elif watch:
        signal = "WATCH"
    else:
        return None

    ranges = [
        x["high"] - x["low"]
        for x in candles[-10:]
    ]

    average_range = (
        sum(ranges) / len(ranges)
        if ranges
        else 0
    )

    price = current["close"]

    risk = max(
        average_range * 1.2,
        price * 0.004,
    )

    risk = min(
        risk,
        price * 0.012,
    )

    sl = price - risk
    tp1 = price + risk * 1.5
    tp2 = price + risk * 2.5

    return {
        "symbol": symbol,
        "signal": signal,
        "score": score,
        "price": price,
        "change5": change5,
        "change15": change15,
        "change60": change60,
        "volume_ratio": volume_ratio,
        "resistance_distance": resistance_distance,
        "breakout": breakout,
        "retest": retest,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
    }


# ============================================================
# QUICK RANK
# ============================================================

def quick_rank_symbol(symbol):
    try:
        trades = get_trades(symbol)

        candles = build_5m_candles(trades)

        if len(candles) < 20:
            return None

        candles = candles[:-1]

        if len(candles) < 20:
            return None

        current = candles[-1]
        previous = candles[-2]

        c15 = aggregate(candles, 3)
        c60 = aggregate(candles, 12)

        if len(c15) < 2 or len(c60) < 2:
            return None

        change5 = pct(
            current["close"],
            previous["close"],
        )

        change15 = pct(
            c15[-1]["close"],
            c15[-2]["close"],
        )

        change60 = pct(
            c60[-1]["close"],
            c60[-2]["close"],
        )

        volumes = [
            x["volume"]
            for x in candles[-21:-1]
        ]

        average_volume = (
            sum(volumes) / len(volumes)
            if volumes
            else 0
        )

        volume_ratio = (
            current["volume"] / average_volume
            if average_volume > 0
            else 0
        )

        rank_score = (
            change5 * 2
            + change15 * 1.5
            + change60
            + min(volume_ratio, 5) * 0.5
        )

        return {
            "symbol": symbol,
            "rank_score": rank_score,
            "change5": change5,
            "change15": change15,
            "change60": change60,
            "volume_ratio": volume_ratio,
        }

    except Exception as e:
        print(
            f"RANK ERROR {symbol}: {e}"
        )
        return None


# ============================================================
# TOP 10
# ============================================================

def select_top_markets(markets):
    results = []

    print(
        f"RANKING {len(markets)} USDT MARKETS..."
    )

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                quick_rank_symbol,
                symbol,
            ): symbol
            for symbol in markets
        }

        for future in as_completed(futures):
            try:
                result = future.result()

                if result:
                    results.append(result)

            except Exception as e:
                print(
                    f"RANK FUTURE ERROR: {e}"
                )

    results.sort(
        key=lambda x: x["rank_score"],
        reverse=True,
    )

    return results[:TOP_SCAN_MARKETS]


# ============================================================
# DEEP SCAN
# ============================================================

def deep_scan(top_markets):
    results = []

    print(
        f"DEEP SCAN TOP {len(top_markets)}..."
    )

    with ThreadPoolExecutor(
        max_workers=10
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                item["symbol"],
            ): item["symbol"]
            for item in top_markets
        }

        for future in as_completed(futures):
            symbol = futures[future]

            try:
                result = future.result()

                if result:
                    results.append(result)

            except Exception as e:
                print(
                    f"SCAN ERROR {symbol}: {e}"
                )

    return results


# ============================================================
# PAPER
# ============================================================

def load_state():
    if not PAPER_TRACKING:
        return []

    try:
        if not os.path.exists(STATE_FILE):
            return []

        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        return data if isinstance(data, list) else []

    except Exception as e:
        print(
            f"STATE LOAD ERROR: {e}"
        )
        return []


def save_state(state):
    if not PAPER_TRACKING:
        return

    try:
        with open(
            STATE_FILE,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                state[-MAX_HISTORY:],
                f,
                ensure_ascii=False,
                indent=2,
            )

    except Exception as e:
        print(
            f"STATE SAVE ERROR: {e}"
        )


def paper_add(results):
    state = load_state()

    open_symbols = {
        item.get("symbol")
        for item in state
        if item.get("status") == "OPEN"
    }

    for result in results:
        if result["signal"] not in (
            "CONFIRMED BUY",
            "EARLY ENTRY",
        ):
            continue

        if result["symbol"] in open_symbols:
            continue

        state.append({
            "symbol": result["symbol"],
            "signal": result["signal"],
            "entry": result["price"],
            "sl": result["sl"],
            "tp1": result["tp1"],
            "tp2": result["tp2"],
            "status": "OPEN",
            "time": utc_now(),
        })

        open_symbols.add(
            result["symbol"]
        )

    save_state(state)


def paper_stats():
    state = load_state()

    total = len(state)

    tp = sum(
        1
        for x in state
        if x.get("status") == "TP"
    )

    sl = sum(
        1
        for x in state
        if x.get("status") == "SL"
    )

    open_count = sum(
        1
        for x in state
        if x.get("status") == "OPEN"
    )

    return total, tp, sl, open_count


# ============================================================
# FORMAT
# ============================================================

def format_signal(result):
    return (
        f"🪙 {result['symbol']}\n"
        f"⭐ SCORE: {result['score']}\n"
        f"💰 PRICE: {result['price']:.10g}\n"
        f"📈 5M: {result['change5']:+.2f}%\n"
        f"📊 15M: {result['change15']:+.2f}%\n"
        f"⏱ 1H: {result['change60']:+.2f}%\n"
        f"📦 VOL: {result['volume_ratio']:.2f}x\n"
        f"🛡 SL: {result['sl']:.10g}\n"
        f"🎯 TP1: {result['tp1']:.10g}\n"
        f"🎯 TP2: {result['tp2']:.10g}"
    )


# ============================================================
# FINAL REPORT
# ============================================================

def build_final_message(
    markets,
    top_markets,
    results,
):
    confirmed = sorted(
        [
            x for x in results
            if x["signal"] == "CONFIRMED BUY"
        ],
        key=lambda x: x["score"],
        reverse=True,
    )[:TOP_CONFIRMED]

    early = sorted(
        [
            x for x in results
            if x["signal"] == "EARLY ENTRY"
        ],
        key=lambda x: x["score"],
        reverse=True,
    )[:TOP_EARLY]

    watch = sorted(
        [
            x for x in results
            if x["signal"] == "WATCH"
        ],
        key=lambda x: x["score"],
        reverse=True,
    )[:TOP_WATCH]

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
    )

    lines.append(
        "🚀 AUTO TOP 10 + CLEAN EARLY ENTRY"
    )

    lines.append(
        f"📡 TABDEAL API: OK"
    )

    lines.append(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    lines.append(
        f"🎯 DEEP SCAN: TOP {len(top_markets)}"
    )

    lines.append(
        f"🕐 {utc_now()}"
    )

    lines.append("")
    lines.append("🏆 TOP 10")

    for i, item in enumerate(
        top_markets,
        1,
    ):
        lines.append(
            f"{i}. {item['symbol']} | "
            f"5M {item['change5']:+.2f}% | "
            f"15M {item['change15']:+.2f}% | "
            f"1H {item['change60']:+.2f}%"
        )

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("🟢 CONFIRMED BUY")

    if confirmed:
        for i, result in enumerate(
            confirmed,
            1,
        ):
            lines.append("")
            lines.append(
                f"#{i} {format_signal(result)}"
            )
    else:
        lines.append("NONE")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("⚡ EARLY ENTRY")

    if early:
        for i, result in enumerate(
            early,
            1,
        ):
            lines.append("")
            lines.append(
                f"#{i} {format_signal(result)}"
            )
    else:
        lines.append("NONE")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")
    lines.append("🟡 WATCH")

    if watch:
        for i, result in enumerate(
            watch,
            1,
        ):
            lines.append("")
            lines.append(
                f"#{i} {format_signal(result)}"
            )
    else:
        lines.append("NONE")

    total, tp, sl, open_count = paper_stats()

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━")

    lines.append(
        f"📊 PAPER STATS\n"
        f"Trades: {total} | "
        f"TP: {tp} | "
        f"SL: {sl} | "
        f"OPEN: {open_count}"
    )

    lines.append(
        "🔧 REAL ORDERS: DISABLED"
    )

    return "\n".join(lines)


# ============================================================
# MAIN
# ============================================================

def main():

    # --------------------------------------------------------
    # IMMEDIATE TELEGRAM TEST
    # --------------------------------------------------------

    telegram(
        f"🚀 ATI BOT BOOT {VERSION}\n"
        f"📡 TELEGRAM: OK\n"
        f"📊 AUTO TOP 10: ON\n"
        f"⏱ TIMEFRAME: 5m\n"
        f"🕯 CLOSED CANDLE: YES\n"
        f"📊 PAPER TRACKING: ON\n"
        f"🔧 REAL ORDERS: DISABLED\n"
        f"🕐 {utc_now()}"
    )

    try:

        # ----------------------------------------------------
        # GET MARKETS
        # ----------------------------------------------------

        telegram(
            f"📡 ATI {VERSION}\n"
            f"🔎 Getting Tabdeal USDT markets..."
        )

        markets = get_markets()

        if not markets:
            telegram(
                f"❌ ATI {VERSION}\n"
                f"TABDEAL MARKET DATA ERROR\n"
                f"No USDT markets received.\n"
                f"🕐 {utc_now()}"
            )
            return

        telegram(
            f"✅ ATI {VERSION}\n"
            f"📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: {len(markets)}\n"
            f"🔎 Selecting TOP 10..."
        )

        # ----------------------------------------------------
        # TOP 10
        # ----------------------------------------------------

        top_markets = select_top_markets(
            markets
        )

        if not top_markets:
            telegram(
                f"⚠️ ATI {VERSION}\n"
                f"TOP 10 selection failed.\n"
                f"USDT MARKETS: {len(markets)}\n"
                f"🕐 {utc_now()}"
            )
            return

        top_text = "\n".join(
            f"{i}. {item['symbol']} | "
            f"5M {item['change5']:+.2f}%"
            for i, item in enumerate(
                top_markets,
                1,
            )
        )

        telegram(
            f"🎯 TOP 10 SELECTED\n\n"
            f"{top_text}\n\n"
            f"🔍 Deep scan starting..."
        )

        # ----------------------------------------------------
        # DEEP SCAN
        # ----------------------------------------------------

        results = deep_scan(
            top_markets
        )

        telegram(
            f"🔍 SCAN FINISHED\n"
            f"🎯 Markets scanned: {len(top_markets)}\n"
            f"📊 Signals found: {len(results)}\n"
            f"📨 Final report coming..."
        )

        # ----------------------------------------------------
        # PAPER
        # ----------------------------------------------------

        if PAPER_TRACKING:
            paper_add(results)

        # ----------------------------------------------------
        # FINAL
        # ----------------------------------------------------

        final_message = build_final_message(
            markets,
            top_markets,
            results,
        )

        telegram(final_message)

        print(
            f"ATI {VERSION} FINISHED"
        )

    except Exception as e:

        error_message = (
            f"🚨 ATI BOT ERROR {VERSION}\n"
            f"❌ {type(e).__name__}\n"
            f"{str(e)[:1500]}\n"
            f"🕐 {utc_now()}"
        )

        print(error_message)
        telegram(error_message)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
