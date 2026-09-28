import os
import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


# ============================================================
# ATI CRYPTO BOT V39.7.0
# AUTO TOP 10 + TELEGRAM RANKING HEARTBEAT
# CLEAN EARLY ENTRY + CONFIRMED BREAKOUT
# ============================================================

VERSION = "V39.7.0"

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

MAX_MARKETS = 1000
TOP_N = 10

REQUEST_TIMEOUT = 15

RANK_WORKERS = 20
SCAN_WORKERS = 5

PROGRESS_STEP = 50

LIVE_TRADING = False
PAPER_TRACKING = True


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


def telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("TELEGRAM CONFIG ERROR")
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

        response = requests.post(
            url,
            json=payload,
            timeout=15,
        )

        if response.ok:
            print("TELEGRAM OK")
            return True

        print(
            "TELEGRAM ERROR:",
            response.status_code,
            response.text[:300],
        )

        return False

    except Exception as e:

        print(
            "TELEGRAM EXCEPTION:",
            str(e),
        )

        return False


# ============================================================
# TIME
# ============================================================

def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# TABDEAL API
# ============================================================

def api_get(path, params=None):

    url = BASE_URL + path

    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


# ============================================================
# GET MARKETS
# ============================================================

def get_markets():

    data = api_get(
        "/r/api/v1/exchangeInfo"
    )

    raw_markets = []

    if isinstance(data, dict):

        if isinstance(
            data.get("symbols"),
            list
        ):
            raw_markets = data["symbols"]

        elif isinstance(
            data.get("data"),
            list
        ):
            raw_markets = data["data"]

    elif isinstance(data, list):

        raw_markets = data

    markets = []

    for item in raw_markets:

        if not isinstance(item, dict):
            continue

        symbol = (
            item.get("symbol")
            or item.get("s")
            or item.get("market")
            or ""
        )

        symbol = str(symbol).upper()

        if not symbol.endswith("USDT"):
            continue

        if symbol not in markets:
            markets.append(symbol)

    return markets[:MAX_MARKETS]


# ============================================================
# GET TRADES
# ============================================================

def get_trades(symbol):

    data = api_get(
        "/r/api/v1/trades",
        {
            "symbol": symbol,
            "limit": 1000,
        },
    )

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "data",
            "trades",
            "result",
        ):

            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


# ============================================================
# TRADE PRICE
# ============================================================

def trade_price(item):

    if not isinstance(item, dict):
        return None

    value = (
        item.get("price")
        or item.get("p")
        or item.get("tradePrice")
    )

    try:

        return float(value)

    except Exception:

        return None


# ============================================================
# PRICE SERIES
# ============================================================

def price_series(trades):

    prices = []

    for item in trades:

        price = trade_price(item)

        if price is not None and price > 0:
            prices.append(price)

    return prices


# ============================================================
# QUICK RANK
# ============================================================

def quick_rank_symbol(symbol):

    try:

        trades = get_trades(symbol)

        prices = price_series(trades)

        if len(prices) < 20:
            return None

        current = prices[-1]

        p5 = prices[-6]
        p15 = prices[-16]
        p60 = prices[-61] if len(prices) >= 61 else None

        if p60 is None:
            return None

        move5 = (
            (current - p5)
            / p5
            * 100
        )

        move15 = (
            (current - p15)
            / p15
            * 100
        )

        move60 = (
            (current - p60)
            / p60
            * 100
        )

        score = 0

        if move5 > 0:
            score += min(
                move5 * 2.0,
                20
            )

        if move15 > 0:
            score += min(
                move15 * 1.2,
                20
            )

        if move60 > 0:
            score += min(
                move60 * 0.4,
                20
            )

        if move5 > 12:
            score -= 8

        elif move5 > 8:
            score -= 4

        if move5 > 0 and move15 > 0:
            score += 5

        if move15 > 0 and move60 > 0:
            score += 5

        return {
            "symbol": symbol,
            "price": current,
            "move5": move5,
            "move15": move15,
            "move60": move60,
            "score": score,
        }

    except Exception as e:

        print(
            f"RANK ERROR {symbol}: {e}"
        )

        return None


# ============================================================
# SELECT TOP 10
# ============================================================

def select_top_markets(markets):

    total = len(markets)

    telegram(
        "🔄 ATI V39.7.0\n"
        "📊 RANKING TOP 10 STARTED\n"
        f"🔎 Markets: {total}\n"
        "⏳ Please wait..."
    )

    results = []

    completed = 0
    last_progress = 0

    with ThreadPoolExecutor(
        max_workers=RANK_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                quick_rank_symbol,
                symbol,
            ): symbol
            for symbol in markets
        }

        for future in as_completed(
            futures
        ):

            completed += 1

            try:

                result = future.result()

                if result is not None:
                    results.append(result)

            except Exception as e:

                print(
                    "FUTURE ERROR:",
                    str(e),
                )

            if (
                completed - last_progress
                >= PROGRESS_STEP
                or completed == total
            ):

                last_progress = completed

                percent = (
                    completed
                    / total
                    * 100
                )

                telegram(
                    "🔄 ATI V39.7.0\n"
                    "📊 RANKING TOP 10\n"
                    f"⏳ Progress: "
                    f"{completed}/{total}\n"
                    f"📈 {percent:.0f}% completed\n"
                    f"✅ Valid: "
                    f"{len(results)}"
                )

    results.sort(
        key=lambda x: x["score"],
        reverse=True,
    )

    top = results[:TOP_N]

    telegram(
        "🎯 ATI V39.7.0\n"
        "✅ RANKING FINISHED\n"
        f"📊 Markets: {total}\n"
        f"🏆 TOP {len(top)} SELECTED"
    )

    return top


# ============================================================
# DEEP SCAN
# ============================================================

def deep_scan(item):

    symbol = item["symbol"]

    try:

        trades = get_trades(symbol)

        prices = price_series(trades)

        if len(prices) < 30:

            return {
                "symbol": symbol,
                "signal": "NONE",
                "score": 0,
            }

        current = prices[-1]

        p1 = prices[-2]
        p3 = prices[-4]
        p6 = prices[-7]
        p12 = prices[-13]
        p24 = prices[-25]

        move5 = (
            (current - p6)
            / p6
            * 100
        )

        move15 = (
            (current - p12)
            / p12
            * 100
        )

        move30 = (
            (current - p24)
            / p24
            * 100
        )

        score = 0

        reasons = []

        if current > p1:

            score += 1
            reasons.append(
                "5m rising"
            )

        if current > p3:

            score += 1
            reasons.append(
                "higher price"
            )

        if move5 > 0.25:

            score += 1
            reasons.append(
                "5m momentum"
            )

        if move5 > 0.60:

            score += 1
            reasons.append(
                "strong momentum"
            )

        if move15 > 0:

            score += 1
            reasons.append(
                "15m positive"
            )

        if move30 > 0:

            score += 1
            reasons.append(
                "30m positive"
            )

        if move15 > 0.50:

            score += 1
            reasons.append(
                "15m expansion"
            )

        early_entry = False

        if (
            move5 > 0.10
            and move5 < 2.50
            and move15 > 0.30
            and move30 > 0
        ):

            early_entry = True

            score += 2

            reasons.append(
                "early entry"
            )

        recent_high = max(
            prices[-13:-1]
        )

        breakout = (
            current > recent_high
        )

        if breakout:

            score += 3

            reasons.append(
                "breakout"
            )

        if move5 > 7:

            score -= 4

            reasons.append(
                "5m chase"
            )

        elif move5 > 5:

            score -= 2

            reasons.append(
                "high 5m move"
            )

        signal = "NONE"

        if (
            score >= 9
            and breakout
        ):

            signal = "CONFIRMED BUY"

        elif (
            score >= 7
            and early_entry
        ):

            signal = "EARLY ENTRY"

        elif score >= 5:

            signal = "WATCH"

        sl = current * 0.995
        tp1 = current * 1.008
        tp2 = current * 1.015

        return {
            "symbol": symbol,
            "price": current,
            "move5": move5,
            "move15": move15,
            "move30": move30,
            "score": score,
            "signal": signal,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "reasons": reasons,
        }

    except Exception as e:

        print(
            f"DEEP ERROR {symbol}: {e}"
        )

        return {
            "symbol": symbol,
            "signal": "NONE",
            "score": 0,
        }


# ============================================================
# FORMAT RESULT
# ============================================================

def format_result(item):

    return (
        f"🪙 {item['symbol']}\n"
        f"⭐ SCORE: {item.get('score', 0)}\n"
        f"💰 PRICE: "
        f"{item.get('price', 0):.8f}\n"
        f"📈 5M: "
        f"{item.get('move5', 0):+.2f}%\n"
        f"📊 15M: "
        f"{item.get('move15', 0):+.2f}%\n"
        f"📊 30M: "
        f"{item.get('move30', 0):+.2f}%\n"
        f"🛑 SL: "
        f"{item.get('sl', 0):.8f}\n"
        f"🎯 TP1: "
        f"{item.get('tp1', 0):.8f}\n"
        f"🎯 TP2: "
        f"{item.get('tp2', 0):.8f}\n"
        f"📌 {item.get('signal', 'NONE')}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    telegram(
        "🚀 ATI BOT BOOT V39.7.0\n"
        "📡 TELEGRAM: OK\n"
        "📊 AUTO TOP 10: ON\n"
        "⏱ TIMEFRAME: 5m\n"
        "🕯 CLOSED CANDLE: YES\n"
        "📊 PAPER TRACKING: ON\n"
        "🔧 REAL ORDERS: DISABLED\n"
        f"🕐 {utc_now()}"
    )

    try:

        telegram(
            "📡 ATI V39.7.0\n"
            "🔎 Getting Tabdeal USDT markets..."
        )

        markets = get_markets()

        if not markets:

            telegram(
                "❌ ATI V39.7.0\n"
                "TABDEAL MARKET DATA ERROR\n"
                "No USDT markets found."
            )

            return

        telegram(
            "✅ ATI V39.7.0\n"
            "📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: "
            f"{len(markets)}\n"
            "🔎 Selecting TOP 10..."
        )

        top = select_top_markets(
            markets
        )

        if not top:

            telegram(
                "⚠️ ATI V39.7.0\n"
                "❌ TOP 10 SELECTION FAILED"
            )

            return

        top_text = "🏆 TOP 10\n\n"

        for i, item in enumerate(
            top,
            start=1,
        ):

            top_text += (
                f"{i}. "
                f"{item['symbol']} | "
                f"5M "
                f"{item['move5']:+.2f}% | "
                f"15M "
                f"{item['move15']:+.2f}% | "
                f"1H "
                f"{item['move60']:+.2f}%\n"
            )

        telegram(
            "⚡ ATI V39.7.0\n"
            "🎯 TOP 10 SELECTED\n\n"
            + top_text
        )

        telegram(
            "🔬 ATI V39.7.0\n"
            "🔎 DEEP SCAN STARTING\n"
            f"🎯 Markets: {len(top)}\n"
            "⏱ TIMEFRAME: 5m\n"
            "🕯 CLOSED CANDLE: YES"
        )

        results = []

        with ThreadPoolExecutor(
            max_workers=SCAN_WORKERS
        ) as executor:

            futures = [
                executor.submit(
                    deep_scan,
                    item,
                )
                for item in top
            ]

            for future in as_completed(
                futures
            ):

                try:

                    result = future.result()

                    if result:
                        results.append(result)

                except Exception as e:

                    print(
                        "SCAN ERROR:",
                        str(e),
                    )

        results.sort(
            key=lambda x: x.get(
                "score",
                0
            ),
            reverse=True,
        )

        confirmed = [
            x for x in results
            if x.get("signal")
            == "CONFIRMED BUY"
        ]

        early = [
            x for x in results
            if x.get("signal")
            == "EARLY ENTRY"
        ]

        watch = [
            x for x in results
            if x.get("signal")
            == "WATCH"
        ]

        final = (
            "⚡ ATI CRYPTO BOT V39.7.0\n"
            "🚀 AUTO TOP 10 + "
            "CLEAN EARLY ENTRY\n"
            "📡 TABDEAL API: OK\n"
            f"📊 USDT MARKETS: "
            f"{len(markets)}\n"
            f"🎯 DEEP SCAN: TOP "
            f"{len(top)}\n"
            f"🕐 {utc_now()}\n\n"
        )

        final += (
            "━━━━━━━━━━━━━━━━━━\n"
            "🟢 CONFIRMED BUY\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        if confirmed:

            for i, item in enumerate(
                confirmed[:3],
                start=1,
            ):

                final += (
                    f"\n#{i}\n"
                    + format_result(item)
                    + "\n"
                )

        else:

            final += "NONE\n"

        final += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "⚡ EARLY ENTRY\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        if early:

            for i, item in enumerate(
                early[:3],
                start=1,
            ):

                final += (
                    f"\n#{i}\n"
                    + format_result(item)
                    + "\n"
                )

        else:

            final += "NONE\n"

        final += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "🟡 WATCH\n"
            "━━━━━━━━━━━━━━━━━━\n"
        )

        if watch:

            for i, item in enumerate(
                watch[:3],
                start=1,
            ):

                final += (
                    f"\n#{i}\n"
                    + format_result(item)
                    + "\n"
                )

        else:

            final += "NONE\n"

        final += (
            "\n━━━━━━━━━━━━━━━━━━\n"
            "📊 PAPER STATS\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Trades: 0 | TP: 0 | "
            "SL: 0 | OPEN: 0\n"
            "🔧 REAL ORDERS: DISABLED"
        )

        telegram(final)

        print(final)

    except Exception as e:

        error_text = (
            "🚨 ATI BOT ERROR V39.7.0\n"
            f"❌ {str(e)}\n"
            f"🕐 {utc_now()}"
        )

        print(error_text)

        telegram(error_text)


# ============================================================
# START
# ============================================================

if __name__ == "__main__":
    main()
