import os
import time
from datetime import datetime, timezone

import requests


VERSION = "V36.2"
BASE_URL = "https://api1.tabdeal.org"

MAX_MARKETS = 1000
TOP_RESULTS = 5
REQUEST_TIMEOUT = 15
SLEEP_BETWEEN_MARKETS = 0.03

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false").strip().lower() == "true"
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

session = requests.Session()


def telegram_send(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    try:
        url = (
            "https://api.telegram.org/bot"
            + TELEGRAM_BOT_TOKEN
            + "/sendMessage"
        )

        response = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=REQUEST_TIMEOUT,
        )

        return response.ok

    except Exception:
        return False


def get_json(path, params=None):
    response = session.get(
        BASE_URL + path,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )

    response.raise_for_status()

    return response.json()


def get_markets():
    last_error = None

    paths = [
        "/r/api/v1/exchangeInfo",
        "/api/v1/exchangeInfo",
    ]

    for path in paths:

        try:
            data = get_json(path)

            if isinstance(data, list):
                items = data

            elif isinstance(data, dict):
                items = (
                    data.get("symbols")
                    or data.get("data")
                    or data.get("result")
                    or []
                )

            else:
                items = []

            markets = []

            for item in items:

                if not isinstance(item, dict):
                    continue

                symbol = str(
                    item.get("symbol")
                    or item.get("tabdealSymbol")
                    or ""
                ).replace("_", "").upper()

                quote = str(
                    item.get("quoteAsset")
                    or item.get("quote")
                    or ""
                ).upper()

                status = str(
                    item.get("status")
                    or "TRADING"
                ).upper()

                if (
                    (symbol.endswith("USDT") or quote == "USDT")
                    and status in ("TRADING", "ACTIVE", "")
                ):
                    markets.append(symbol)

            markets = list(dict.fromkeys(markets))

            if markets:
                return markets[:MAX_MARKETS]

        except Exception as exc:
            last_error = exc

    raise last_error or RuntimeError("No USDT markets found")


def get_trades(symbol):

    last_error = None

    paths = [
        "/r/api/v1/trades",
        "/api/v1/trades",
    ]

    for path in paths:

        try:
            data = get_json(
                path,
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
                    "result",
                    "trades",
                ):

                    value = data.get(key)

                    if isinstance(value, list):
                        return value

        except Exception as exc:
            last_error = exc

    if last_error:
        raise last_error

    return []


def parse_trade(item):

    if not isinstance(item, dict):
        return None

    try:

        price = float(item.get("price"))

        qty = float(
            item.get("qty")
            or item.get("quantity")
            or 0
        )

        timestamp = int(
            item.get("time")
            or item.get("timestamp")
            or item.get("T")
            or 0
        )

    except (TypeError, ValueError):

        return None

    if price <= 0 or timestamp <= 0:
        return None

    if timestamp < 100000000000:
        timestamp *= 1000

    return (
        timestamp,
        price,
        max(qty, 0.0),
    )


def build_5m_candles(trades):

    parsed = []

    for item in trades:

        trade = parse_trade(item)

        if trade is not None:
            parsed.append(trade)

    if not parsed:
        return []

    parsed.sort(
        key=lambda x: x[0]
    )

    buckets = {}

    for timestamp, price, qty in parsed:

        bucket = (
            timestamp // 300000
        ) * 300000

        if bucket not in buckets:

            buckets[bucket] = {
                "time": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 0.0,
            }

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

    candles = [
        buckets[key]
        for key in sorted(buckets)
    ]

    current_bucket = (
        int(time.time() * 1000)
        // 300000
    ) * 300000

    if (
        candles
        and candles[-1]["time"] >= current_bucket
    ):
        candles.pop()

    return candles


def pct(old_value, new_value):

    if old_value == 0:
        return 0.0

    return (
        (new_value - old_value)
        / old_value
        * 100.0
    )


def analyze(symbol):

    trades = get_trades(symbol)

    candles = build_5m_candles(
        trades
    )

    if len(candles) < 2:
        return None

    last = candles[-1]

    candle_count = len(candles)

    old_15m = candles[
        max(0, candle_count - 4)
    ]["close"]

    old_1h = candles[
        max(0, candle_count - 13)
    ]["close"]

    move_5m = pct(
        candles[-2]["close"],
        last["close"],
    )

    move_15m = pct(
        old_15m,
        last["close"],
    )

    move_1h = pct(
        old_1h,
        last["close"],
    )

    previous = candles[-2]

    candle_range = max(
        previous["high"]
        - previous["low"],
        0.0,
    )

    if candle_range > 0:

        close_position = (
            previous["close"]
            - previous["low"]
        ) / candle_range

    else:

        close_position = 0.5

    recent_volumes = [
        candle["volume"]
        for candle in candles[-11:-1]
        if candle["volume"] > 0
    ]

    if recent_volumes:

        average_volume = (
            sum(recent_volumes)
            / len(recent_volumes)
        )

    else:

        average_volume = 0.0

    if average_volume > 0:

        volume_ratio = (
            previous["volume"]
            / average_volume
        )

    else:

        volume_ratio = 1.0

    bullish = (
        previous["close"]
        >= previous["open"]
    )

    score = 0

    if move_5m > 0.20:
        score += 1

    if move_15m > 0.35:
        score += 1

    if move_1h > 0.70:
        score += 2

    if bullish:
        score += 1

    if close_position >= 0.70:
        score += 1

    if volume_ratio >= 1.10:
        score += 1

    positive_count = sum(
        value > 0
        for value in (
            move_5m,
            move_15m,
            move_1h,
        )
    )

    momentum = (
        max(move_5m, 0.0)
        + 0.7 * max(move_15m, 0.0)
        + 0.4 * max(move_1h, 0.0)
        + 0.5 * max(
            volume_ratio - 1.0,
            0.0,
        )
    )

    if positive_count >= 3:

        direction = "UP"

    elif positive_count == 2:

        direction = "MIXED"

    elif positive_count == 1:

        direction = "RECOVERING"

    else:

        direction = "DOWN"

    strong = (
        score >= 5
        and positive_count == 3
        and bullish
        and close_position >= 0.60
    )

    return {
        "symbol": symbol,
        "price": last["close"],
        "move5": move_5m,
        "move15": move_15m,
        "move1h": move_1h,
        "vol": volume_ratio,
        "score": score,
        "momentum": momentum,
        "direction": direction,
        "strong": strong,
        "candles": candle_count,
    }


def format_number(value):

    if value >= 1000:

        return f"{value:,.2f}"

    return (
        f"{value:.10f}"
        .rstrip("0")
        .rstrip(".")
    )


def build_message(
    markets,
    results,
    failures,
):

    now = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    lines = []

    lines.append(
        f"⚡ ATI CRYPTO BOT {VERSION}"
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

    lines.append(
        "🔧 CANDLE SOURCE: "
        "TABDEAL TRADES → 5M CANDLES"
    )

    lines.append("")
    lines.append(
        "📡 TABDEAL API: OK"
    )
    lines.append(
        f"📊 USDT MARKETS: {len(markets)}"
    )

    lines.append("")
    lines.append(
        f"🕐 Scan: {now}"
    )

    lines.append("")

    if failures:

        lines.append(
            f"⚠️ Candle data unavailable: "
            f"{failures} markets"
        )

        lines.append("")

    if not results:

        lines.append(
            "❌ NO USDT MARKET CANDLE DATA FOUND"
        )

        lines.append("")
        lines.append(
            "🚫 NO TRADE"
        )

    else:

        strong_results = [
            item
            for item in results
            if item["strong"]
        ]

        if strong_results:

            lines.append(
                "🔥 STRONG UPWARD SETUPS"
            )

        else:

            lines.append(
                "📈 TOP UPWARD COINS"
            )

        lines.append("")

        for index, item in enumerate(
            results[:TOP_RESULTS],
            start=1,
        ):

            lines.append(
                f"{index}. "
                f"{item['symbol']} | "
                f"{item['direction']}"
            )

            lines.append(
                f"   💰 "
                f"{format_number(item['price'])} | "
                f"Score {item['score']}/7"
            )

            lines.append(
                f"   5m "
                f"{item['move5']:+.2f}% | "
                f"15m "
                f"{item['move15']:+.2f}% | "
                f"1h "
                f"{item['move1h']:+.2f}%"
            )

            lines.append(
                f"   📊 Vol "
                f"{item['vol']:.2f}x | "
                f"Candles "
                f"{item['candles']}"
            )

            lines.append("")

        if strong_results:

            lines.append(
                "🟢 TRADE CANDIDATE: "
                + strong_results[0]["symbol"]
            )

        else:

            lines.append(
                "🟡 NO STRONG SETUP"
            )

    lines.append("")

    lines.append(
        "⚠️ REAL TRADING: "
        + (
            "ENABLED"
            if LIVE_TRADING
            else "DISABLED"
        )
    )

    lines.append(
        "🚫 ORDER EXECUTION: "
        "DISABLED IN V36.2"
    )

    return "\n".join(lines)


def main():

    try:

        markets = get_markets()

        results = []
        failures = 0

        for symbol in markets:

            try:

                item = analyze(symbol)

                if item:

                    results.append(item)

                else:

                    failures += 1

            except Exception:

                failures += 1

            time.sleep(
                SLEEP_BETWEEN_MARKETS
            )

        results.sort(
            key=lambda item: (
                item["momentum"],
                item["move1h"],
                item["move15"],
                item["move5"],
            ),
            reverse=True,
        )

        message = build_message(
            markets,
            results,
            failures,
        )

        print(message)

        telegram_send(message)

    except Exception as exc:

        message = (
            f"⚡ ATI CRYPTO BOT {VERSION}\n\n"
            f"❌ TABDEAL API ERROR\n\n"
            f"{type(exc).__name__}: {exc}"
        )

        print(message)

        telegram_send(message)


if __name__ == "__main__":
    main()
