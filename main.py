import os
import time
from datetime import datetime, timezone

import requests

VERSION = "V36.1"
BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"
CANDLE_LIMIT = 60
MAX_MARKETS = 1000
TOP_RESULTS = 5

REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.03

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"
ORDER_QTY = os.getenv("ORDER_QTY", "0.001")

TABDEAL_API_KEY = os.getenv("TABDEAL_API_KEY", "").strip()
TABDEAL_API_SECRET = os.getenv("TABDEAL_API_SECRET", "").strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-CRYPTO-BOT-V36.1",
    "Accept": "application/json",
})


def send_telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram settings missing")
        return False

    url = (
        "https://api.telegram.org/bot"
        + TELEGRAM_BOT_TOKEN
        + "/sendMessage"
    )

    try:

        r = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=REQUEST_TIMEOUT,
        )

        if r.ok:
            print("TELEGRAM: OK")
            return True

        print("TELEGRAM ERROR:", r.text[:300])
        return False

    except Exception as e:

        print("TELEGRAM ERROR:", str(e))
        return False


def tabdeal_get(path, params=None):

    url = BASE_URL + path

    r = session.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    if r.status_code != 200:

        raise RuntimeError(
            "HTTP "
            + str(r.status_code)
            + " "
            + r.text[:300]
        )

    return r.json()


def unwrap(data):

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in [
            "data",
            "result",
            "items",
            "symbols",
            "markets",
            "rows",
        ]:

            value = data.get(key)

            if isinstance(value, list):
                return value

        return data

    return []


def get_markets():

    for path in [
        "/r/api/v1/exchangeInfo",
        "/api/v1/exchangeInfo",
    ]:

        try:

            data = tabdeal_get(path)
            raw = unwrap(data)

            if isinstance(raw, dict):

                raw = (
                    raw.get("symbols")
                    or raw.get("markets")
                    or raw.get("data")
                    or []
                )

            markets = []

            if not isinstance(raw, list):
                continue

            for item in raw:

                if isinstance(item, str):

                    symbol = item.upper()

                    if symbol.endswith("USDT"):
                        markets.append(symbol)

                    continue

                if not isinstance(item, dict):
                    continue

                symbol = (
                    item.get("symbol")
                    or item.get("market")
                    or item.get("pair")
                )

                if not symbol:
                    continue

                symbol = str(symbol).upper()

                if symbol.endswith("USDT"):
                    markets.append(symbol)

            markets = sorted(set(markets))

            if markets:
                return markets[:MAX_MARKETS]

        except Exception:
            continue

    raise RuntimeError("Could not get USDT markets")


def parse_candles(data):

    raw = unwrap(data)

    if isinstance(raw, dict):

        raw = (
            raw.get("klines")
            or raw.get("candles")
            or raw.get("data")
            or []
        )

    if not isinstance(raw, list):
        return []

    candles = []

    for item in raw:

        try:

            if isinstance(item, list):

                if len(item) < 5:
                    continue

                t = item[0]
                o = item[1]
                h = item[2]
                l = item[3]
                c = item[4]
                v = item[5] if len(item) > 5 else 0

            elif isinstance(item, dict):

                t = (
                    item.get("openTime")
                    or item.get("open_time")
                    or item.get("timestamp")
                    or item.get("time")
                    or 0
                )

                o = item.get("open") or item.get("o")
                h = item.get("high") or item.get("h")
                l = item.get("low") or item.get("l")
                c = item.get("close") or item.get("c")
                v = item.get("volume") or item.get("v") or 0

            else:
                continue

            candles.append({
                "time": float(t),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "volume": float(v),
            })

        except Exception:
            continue

    candles.sort(key=lambda x: x["time"])

    return candles


def get_candles(symbol):

    attempts = [
        (
            "/r/api/v1/klines",
            {
                "symbol": symbol,
                "interval": TIMEFRAME,
                "limit": CANDLE_LIMIT,
            },
        ),
        (
            "/api/v1/klines",
            {
                "symbol": symbol,
                "interval": TIMEFRAME,
                "limit": CANDLE_LIMIT,
            },
        ),
        (
            "/r/api/v1/candles",
            {
                "symbol": symbol,
                "timeframe": TIMEFRAME,
                "limit": CANDLE_LIMIT,
            },
        ),
    ]

    for path, params in attempts:

        try:

            data = tabdeal_get(
                path,
                params,
            )

            candles = parse_candles(data)

            if len(candles) >= 20:
                return candles[-CANDLE_LIMIT:]

        except Exception:
            pass

    return []


def pct(a, b):

    if not a:
        return 0.0

    return ((b - a) / a) * 100.0


def analyze(symbol):

    candles = get_candles(symbol)

    if len(candles) < 20:
        return None

    closed = candles[:-1]

    if len(closed) < 20:
        return None

    last = closed[-1]

    price = last["close"]

    move5 = pct(
        closed[-2]["close"],
        price,
    )

    move15 = pct(
        closed[-4]["close"],
        price,
    )

    move1h = pct(
        closed[-13]["close"],
        price,
    )

    hour_data = closed[-13:-1]

    if hour_data:
        hour_high = max(
            x["high"]
            for x in hour_data
        )
    else:
        hour_high = last["high"]

    breakout = price > hour_high

    volumes = [
        x["volume"]
        for x in closed[-6:-1]
        if x["volume"] > 0
    ]

    if volumes:

        avg_volume = (
            sum(volumes)
            / len(volumes)
        )

    else:

        avg_volume = 0

    if avg_volume > 0:

        volume_ratio = (
            last["volume"]
            / avg_volume
        )

    else:

        volume_ratio = 0

    bullish = (
        last["close"]
        > last["open"]
    )

    candle_range = (
        last["high"]
        - last["low"]
    )

    if candle_range > 0:

        close_position = (
            last["close"]
            - last["low"]
        ) / candle_range

    else:

        close_position = 0.5

    score = 0

    if move5 > 0.30:
        score += 1

    if move15 > 0.50:
        score += 1

    if move1h > 1.00:
        score += 2

    if bullish:
        score += 1

    if close_position >= 0.65:
        score += 1

    if volume_ratio >= 1.15:
        score += 1

    if breakout:
        score += 2

    buy_setup = (
        score >= 6
        and move5 > 0
        and move15 > 0
        and move1h > 0
        and bullish
    )

    momentum = (
        max(move5, 0)
        + max(move15, 0) * 0.70
        + max(move1h, 0) * 0.40
        + max(volume_ratio - 1, 0) * 0.50
    )

    if (
        move5 > 0
        and move15 > 0
        and move1h > 0
    ):

        direction = "UP"

    elif move15 > 0 and move1h > 0:

        direction = "RECOVERING"

    elif (
        move5 > 0
        or move15 > 0
        or move1h > 0
    ):

        direction = "MIXED"

    else:

        direction = "DOWN"

    return {
        "symbol": symbol,
        "price": price,
        "move5": move5,
        "move15": move15,
        "move1h": move1h,
        "volume": volume_ratio,
        "score": score,
        "momentum": momentum,
        "breakout": breakout,
        "buy": buy_setup,
        "direction": direction,
        "sl": price * 0.995,
        "tp": price * 1.010,
    }


def price_text(value):

    if value >= 1000:
        return f"{value:,.2f}"

    if value >= 1:
        return f"{value:.4f}"

    if value >= 0.01:
        return f"{value:.6f}"

    return f"{value:.10f}"


def percent_text(value):

    return f"{value:+.2f}%"


def main():

    print("ATI CRYPTO BOT " + VERSION)
    print("UPWARD COIN SCANNER")

    try:

        markets = get_markets()

    except Exception as e:

        message = (
            "ATI CRYPTO BOT "
            + VERSION
            + "\n\n"
            + "TABDEAL API ERROR\n\n"
            + str(e)
        )

        print(message)
        send_telegram(message)
        return

    print(
        "TABDEAL API: OK"
    )

    print(
        "USDT MARKETS:",
        len(markets)
    )

    scan_time = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    results = []

    errors = 0

    for symbol in markets:

        try:

            result = analyze(symbol)

            if result:
                results.append(result)

        except Exception as e:

            errors += 1

            print(
                symbol,
                "ERROR",
                str(e)
            )

        time.sleep(
            SLEEP_BETWEEN_MARKETS
        )

    if not results:

        message = (
            "⚡ ATI CRYPTO BOT "
            + VERSION
            + "\n\n"
            + "🚀 UPWARD COIN SCANNER\n\n"
            + "⏱ Timeframe: 5m\n"
            + "✅ CLOSED CANDLE\n"
            + "📊 5M + 15M + 1H MOMENTUM\n\n"
            + "📡 TABDEAL API: OK\n"
            + "📊 USDT MARKETS: "
            + str(len(markets))
            + "\n\n"
            + "🕐 Scan:\n"
            + scan_time
            + "\n\n"
            + "❌ NO CANDLE DATA FOUND\n"
            + "🚫 NO TRADE"
        )

        print(message)
        send_telegram(message)
        return

    results.sort(
        key=lambda x: (
            x["momentum"],
            x["move1h"],
            x["move15"],
            x["move5"],
        ),
        reverse=True,
    )

    top = results[:TOP_RESULTS]

    buy_setups = [
        x
        for x in results
        if x["buy"]
    ]

    lines = []

    lines.append(
        "⚡ ATI CRYPTO BOT "
        + VERSION
    )

    lines.append("")
    lines.append(
        "🚀 UPWARD COIN SCANNER"
    )

    lines.append("")
    lines.append(
        "⏱ Timeframe: 5m"
    )

    lines.append(
        "✅ CLOSED CANDLE"
    )

    lines.append(
        "📊 5M + 15M + 1H MOMENTUM"
    )

    lines.append("")
    lines.append(
        "📡 TABDEAL API: OK"
    )

    lines.append(
        "📊 USDT MARKETS: "
        + str(len(markets))
    )

    lines.append("")
    lines.append("🕐 Scan:")
    lines.append(scan_time)

    lines.append("")
    lines.append(
        "🔥 TOP 5 UPWARD COINS"
    )

    lines.append("")

    for i, item in enumerate(
        top,
        1
    ):

        lines.append(
            "#"
            + str(i)
            + " "
            + item["symbol"]
        )

        lines.append(
            "💰 Price: "
            + price_text(
                item["price"]
            )
        )

        lines.append(
            "5M: "
            + percent_text(
                item["move5"]
            )
        )

        lines.append(
            "15M: "
            + percent_text(
                item["move15"]
            )
        )

        lines.append(
            "1H: "
            + percent_text(
                item["move1h"]
            )
        )

        lines.append(
            "📦 Volume: "
            + f"{item['volume']:.2f}"
            + "x"
        )

        lines.append(
            "⭐ Score: "
            + str(item["score"])
            + "/9"
        )

        lines.append(
            "🚀 Momentum: "
            + f"{item['momentum']:.2f}"
        )

        if item["breakout"]:

            lines.append(
                "💥 BREAKOUT: YES"
            )

        else:

            lines.append(
                "💥 BREAKOUT: NO"
            )

        if item["buy"]:

            lines.append(
                "🟢 BUY SETUP"
            )

            lines.append(
                "🛑 SL: "
                + price_text(
                    item["sl"]
                )
            )

            lines.append(
                "🎯 TP: "
                + price_text(
                    item["tp"]
                )
            )

        elif item["direction"] == "UP":

            lines.append(
                "🟢 UPWARD MOMENTUM"
            )

        elif item["direction"] == "RECOVERING":

            lines.append(
                "🟡 RECOVERING"
            )

        elif item["direction"] == "MIXED":

            lines.append(
                "🟠 MIXED MOMENTUM"
            )

        else:

            lines.append(
                "⚪ WEAK / DOWN"
            )

        lines.append("")

    lines.append(
        "📊 Scanned: "
        + str(len(markets))
    )

    lines.append(
        "📈 Valid: "
        + str(len(results))
    )

    if errors > 0:

        lines.append(
            "⚠️ Errors: "
            + str(errors)
        )

    lines.append("")

    if buy_setups:

        lines.append(
            "🟢 BUY SETUPS: "
            + str(len(buy_setups))
        )

        lines.append(
            "🎯 BEST: "
            + buy_setups[0]["symbol"]
        )

    else:

        lines.append(
            "⚪ NO STRONG BUY SETUP"
        )

        lines.append(
            "🚫 NO TRADE"
        )

    if LIVE_TRADING:

        lines.append(
            "🔴 REAL TRADING: ENABLED"
        )

    else:

        lines.append(
            "🟢 REAL TRADING: DISABLED"
        )

    message = "\n".join(lines)

    print(message)

    send_telegram(message)

    print(
        "ORDER EXECUTION: DISABLED"
    )


if __name__ == "__main__":
    main()
