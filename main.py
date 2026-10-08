import os
import json
import time
import hmac
import hashlib
import math
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


BASE_URL = os.getenv(
    "BASE_URL",
    "https://api1.tabdeal.org"
).rstrip("/")

ORDER_USDT = float(os.getenv("ORDER_USDT", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))
REAL_TRADING = os.getenv("REAL_TRADING", "false").lower() == "true"

TP_PCT = float(os.getenv("TP_PCT", "0.02"))
SL_PCT = float(os.getenv("SL_PCT", "0.01"))

SCAN_UNIVERSE = int(os.getenv("SCAN_UNIVERSE", "75"))
MIN_SCORE = int(os.getenv("MIN_SCORE", "6"))

REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "10"))
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "15"))
KLINE_LIMIT = int(os.getenv("KLINE_LIMIT", "100"))
RECV_WINDOW = int(os.getenv("RECV_WINDOW", "5000"))

STATE_FILE = "ati_futures_state.json"

API_KEY = (
    os.getenv("TABDEAL_API_KEY")
    or os.getenv("TABDIL_API_KEY")
    or ""
)

API_SECRET = (
    os.getenv("TABDEAL_API_SECRET")
    or os.getenv("TABDIL_API_SECRET")
    or ""
)

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-V11-FIXED",
    "Accept": "application/json",
})


def telegram(text):
    if not TG_TOKEN or not TG_CHAT_ID:
        return

    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"

        requests.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": text,
            },
            timeout=10,
        )
    except Exception:
        pass


def public_get(path, params=None):
    url = BASE_URL + path

    response = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code >= 400:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:400]}"
        )

    try:
        return response.json()
    except Exception:
        raise RuntimeError(
            f"INVALID JSON: {response.text[:400]}"
        )


def signed_request(method, path, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "API KEY/SECRET missing"
        )

    data = dict(params or {})

    data["timestamp"] = int(
        time.time() * 1000
    )

    data["recvWindow"] = RECV_WINDOW

    query = "&".join(
        f"{key}={data[key]}"
        for key in data
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = BASE_URL + path

    if method.upper() == "GET":
        response = session.get(
            url,
            params=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    elif method.upper() == "POST":
        response = session.post(
            url,
            data=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    else:
        raise RuntimeError(
            f"Unsupported HTTP method: {method}"
        )

    if response.status_code >= 400:
        raise RuntimeError(
            f"HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    try:
        return response.json()
    except Exception:
        raise RuntimeError(
            f"INVALID JSON: {response.text[:500]}"
        )


def normalize_market_list(data):
    if isinstance(data, list):
        return data

    if not isinstance(data, dict):
        return []

    candidates = [
        data.get("symbols"),
        data.get("data"),
        data.get("result"),
        data.get("markets"),
        data.get("items"),
    ]

    for candidate in candidates:
        if isinstance(candidate, list):
            return candidate

        if isinstance(candidate, dict):
            nested = candidate.get("symbols")

            if isinstance(nested, list):
                return nested

            nested = candidate.get("data")

            if isinstance(nested, list):
                return nested

    return []


def get_markets():
    paths = [
        "/r/fapi/v1/exchangeInfo",
        "/api/fapi/v1/exchangeInfo",
        "/r/api/v1/exchangeInfo",
        "/api/v1/exchangeInfo",
    ]

    errors = []

    for path in paths:
        try:
            data = public_get(path)

            symbols = normalize_market_list(
                data
            )

            if not symbols:
                errors.append(
                    f"{path}: EMPTY"
                )
                continue

            markets = []

            for item in symbols:

                if not isinstance(item, dict):
                    continue

                symbol = str(
                    item.get("symbol")
                    or item.get("market")
                    or item.get("pair")
                    or item.get("name")
                    or ""
                ).upper().strip()

                if not symbol:
                    continue

                quote = str(
                    item.get("quoteAsset")
                    or item.get("quote")
                    or ""
                ).upper().strip()

                if quote:
                    if quote != "USDT":
                        continue
                else:
                    if not symbol.endswith("USDT"):
                        continue

                status = str(
                    item.get("status")
                    or ""
                ).upper().strip()

                if status:
                    if status not in (
                        "TRADING",
                        "ACTIVE",
                        "ENABLED",
                    ):
                        continue

                markets.append(item)

            if markets:
                return markets[
                    :SCAN_UNIVERSE
                ]

            errors.append(
                f"{path}: "
                f"{len(symbols)} RAW / "
                f"0 VALID"
            )

        except Exception as error:
            errors.append(
                f"{path}: "
                f"{str(error)[:180]}"
            )

    raise RuntimeError(
        " | ".join(errors)
    )


def parse_klines(data):
    if isinstance(data, dict):

        if isinstance(
            data.get("data"),
            list
        ):
            data = data["data"]

        elif isinstance(
            data.get("result"),
            list
        ):
            data = data["result"]

        elif isinstance(
            data.get("klines"),
            list
        ):
            data = data["klines"]

        else:
            data = []

    if not isinstance(data, list):
        return []

    candles = []

    for row in data:

        if not isinstance(row, list):
            continue

        if len(row) < 6:
            continue

        try:
            candles.append({
                "time": int(row[0]),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            })
        except Exception:
            continue

    candles.sort(
        key=lambda x: x["time"]
    )

    return candles


def fetch_5m_klines(symbol):

    paths = [
        "/r/fapi/v1/klines",
        "/api/fapi/v1/klines",
        "/r/api/v1/klines",
        "/api/v1/klines",
    ]

    errors = []

    for path in paths:

        try:
            data = public_get(
                path,
                {
                    "symbol": symbol,
                    "interval": "5m",
                    "limit": KLINE_LIMIT,
                },
            )

            candles = parse_klines(
                data
            )

            if candles:
                return candles, path

            errors.append(
                f"{path}: EMPTY"
            )

        except Exception as error:
            errors.append(
                f"{path}: "
                f"{str(error)[:140]}"
            )

    raise RuntimeError(
        " || ".join(errors)
    )


def closed_candles(candles):

    if not candles:
        return []

    now_ms = int(
        time.time() * 1000
    )

    current_bucket = (
        now_ms // 300000
    ) * 300000

    return [
        candle
        for candle in candles
        if candle["time"]
        < current_bucket
    ]


def load_state():

    if not os.path.exists(
        STATE_FILE
    ):
        return {}

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as file:
            return json.load(file)

    except Exception:
        return {}


def save_state(state):

    temp_file = (
        STATE_FILE + ".tmp"
    )

    with open(
        temp_file,
        "w",
        encoding="utf-8",
    ) as file:

        json.dump(
            state,
            file,
            ensure_ascii=False,
        )

    os.replace(
        temp_file,
        STATE_FILE,
    )


def symbol_rules(info):

    step = 0.0
    min_qty = 0.0
    tick = 0.0

    filters = info.get(
        "filters",
        []
    )

    if not isinstance(
        filters,
        list
    ):
        filters = []

    for item in filters:

        if not isinstance(
            item,
            dict
        ):
            continue

        filter_type = str(
            item.get(
                "filterType",
                ""
            )
        )

        if filter_type in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):

            try:
                step = float(
                    item.get(
                        "stepSize",
                        0
                    )
                )
            except Exception:
                pass

            try:
                min_qty = float(
                    item.get(
                        "minQty",
                        0
                    )
                )
            except Exception:
                pass

        elif filter_type == (
            "PRICE_FILTER"
        ):

            try:
                tick = float(
                    item.get(
                        "tickSize",
                        0
                    )
                )
            except Exception:
                pass

    return (
        step,
        min_qty,
        tick
    )


def floor_step(value, step):

    if step <= 0:
        return value

    return (
        math.floor(
            value / step
        ) * step
    )


def ichimoku(candles):

    if len(candles) < 54:
        return None

    highs = [
        float(
            candle["high"]
        )
        for candle in candles
    ]

    lows = [
        float(
            candle["low"]
        )
        for candle in candles
    ]

    closes = [
        float(
            candle["close"]
        )
        for candle in candles
    ]

    def midpoint(
        period,
        end_index
    ):

        start = (
            end_index
            - period
            + 1
        )

        if start < 0:
            return None

        highest = max(
            highs[
                start:
                end_index + 1
            ]
        )

        lowest = min(
            lows[
                start:
                end_index + 1
            ]
        )

        return (
            highest + lowest
        ) / 2.0

    index = len(candles) - 1

    tenkan = midpoint(
        9,
        index
    )

    kijun = midpoint(
        26,
        index
    )

    span_b = midpoint(
        52,
        index
    )

    previous_tenkan = midpoint(
        9,
        index - 1
    )

    previous_kijun = midpoint(
        26,
        index - 1
    )

    if any(
        value is None
        for value in (
            tenkan,
            kijun,
            span_b,
            previous_tenkan,
            previous_kijun,
        )
    ):
        return None

    span_a = (
        tenkan + kijun
    ) / 2.0

    previous_span_a = (
        previous_tenkan
        + previous_kijun
    ) / 2.0

    price = closes[index]

    cloud_top = max(
        span_a,
        span_b
    )

    cloud_bottom = min(
        span_a,
        span_b
    )

    buy_score = 0
    sell_score = 0

    buy_reasons = []
    sell_reasons = []

    if price > cloud_top:

        buy_score += 2

        buy_reasons.append(
            "PRICE_ABOVE_CLOUD"
        )

    elif price < cloud_bottom:

        sell_score += 2

        sell_reasons.append(
            "PRICE_BELOW_CLOUD"
        )

    if tenkan > kijun:

        buy_score += 2

        buy_reasons.append(
            "TENKAN_GT_KIJUN"
        )

    elif tenkan < kijun:

        sell_score += 2

        sell_reasons.append(
            "TENKAN_LT_KIJUN"
        )

    if span_a > span_b:

        buy_score += 1

        buy_reasons.append(
            "BULLISH_CLOUD"
        )

    elif span_a < span_b:

        sell_score += 1

        sell_reasons.append(
            "BEARISH_CLOUD"
        )

    if closes[index] > closes[index - 1]:

        buy_score += 1

        buy_reasons.append(
            "MOMENTUM_UP"
        )

    elif closes[index] < closes[index - 1]:

        sell_score += 1

        sell_reasons.append(
            "MOMENTUM_DOWN"
        )

    if kijun > previous_kijun:

        buy_score += 1

        buy_reasons.append(
            "KIJUN_RISING"
        )

    elif kijun < previous_kijun:

        sell_score += 1

        sell_reasons.append(
            "KIJUN_FALLING"
        )

    if span_a > previous_span_a:

        buy_score += 1

        buy_reasons.append(
            "CLOUD_RISING"
        )

    elif span_a < previous_span_a:

        sell_score += 1

        sell_reasons.append(
            "CLOUD_FALLING"
        )

    signal = None

    if (
        buy_score >= MIN_SCORE
        and buy_score > sell_score
    ):
        signal = "BUY"

    elif (
        sell_score >= MIN_SCORE
        and sell_score > buy_score
    ):
        signal = "SELL"

    return {
        "signal": signal,
        "score": max(
            buy_score,
            sell_score
        ),
        "buy_score": buy_score,
        "sell_score": sell_score,
        "price": price,
        "tenkan": tenkan,
        "kijun": kijun,
        "span_a": span_a,
        "span_b": span_b,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
        "buy_reasons": buy_reasons,
        "sell_reasons": sell_reasons,
    }


def scan_symbol(info, state):

    symbol = str(
        info.get(
            "symbol",
            ""
        )
    ).upper()

    if not symbol:

        return {
            "symbol": "",
            "ready": False,
            "candles": 0,
            "error": "EMPTY_SYMBOL",
        }

    try:

        candles, source = (
            fetch_5m_klines(
                symbol
            )
        )

        candles = closed_candles(
            candles
        )

        candles = candles[-120:]

        state[symbol] = candles

        count = len(candles)

        if count < 54:

            return {
                "symbol": symbol,
                "ready": False,
                "candles": count,
                "source": source,
                "error":
                    f"ONLY_{count}_CLOSED_CANDLES",
            }

        analysis = ichimoku(
            candles
        )

        if analysis is None:

            return {
                "symbol": symbol,
                "ready": False,
                "candles": count,
                "source": source,
                "error":
                    "ICHIMOKU_FAILED",
            }

        analysis["symbol"] = symbol
        analysis["ready"] = True
        analysis["candles"] = count
        analysis["source"] = source
        analysis["info"] = info

        return analysis

    except Exception as error:

        return {
            "symbol": symbol,
            "ready": False,
            "candles": 0,
            "error": str(error)[:300],
        }


def place_real_trade(signal):

    symbol = signal["symbol"]
    side = signal["signal"]
    price = float(
        signal["price"]
    )

    info = signal["info"]

    (
        step,
        min_qty,
        tick,
    ) = symbol_rules(info)

    if step <= 0:

        raise RuntimeError(
            "NO_VALID_QUANTITY_STEP"
        )

    quantity = (
        ORDER_USDT * LEVERAGE
    ) / price

    quantity = floor_step(
        quantity,
        step
    )

    if quantity <= 0:

        raise RuntimeError(
            "CALCULATED_QUANTITY_ZERO"
        )

    if (
        min_qty > 0
        and quantity < min_qty
    ):

        raise RuntimeError(
            f"QUANTITY {quantity} "
            f"< MIN_QTY {min_qty}"
        )

    quantity_text = (
        f"{quantity:.12f}"
        .rstrip("0")
        .rstrip(".")
    )

    signed_request(
        "POST",
        "/api/v1/leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE,
        },
    )

    order = signed_request(
        "POST",
        "/api/v1/order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity_text,
        },
    )

    return order


def main():

    start_time = time.time()

    print(
        "ATI FUTURES V11 FIXED"
    )

    print(
        "TABDEAL FUTURES"
    )

    print(
        "5M KLINES"
    )

    print(
        "ICHIMOKU 9 / 26 / 52"
    )

    print(
        f"ORDER: {ORDER_USDT} USDT"
    )

    print(
        f"LEVERAGE: {LEVERAGE}x"
    )

    print(
        f"REAL: {REAL_TRADING}"
    )

    state = load_state()

    try:

        markets = get_markets()

    except Exception as error:

        message = (
            "ATI FUTURES V11 ERROR\n\n"
            "MARKET DISCOVERY FAILED\n\n"
            f"{error}"
        )

        print(message)
        telegram(message)

        return

    print(
        f"Markets: {len(markets)}"
    )

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                scan_symbol,
                market,
                state
            ): market
            for market in markets
        }

        for future in as_completed(
            futures
        ):

            try:

                result = (
                    future.result()
                )

                if result:
                    results.append(
                        result
                    )

            except Exception as error:

                market = futures[
                    future
                ]

                results.append({
                    "symbol":
                        market.get(
                            "symbol",
                            "UNKNOWN"
                        ),
                    "ready": False,
                    "candles": 0,
                    "error":
                        str(error)[:300],
                })

    save_state(state)

    ready = [
        result
        for result in results
        if result.get(
            "ready",
            False
        )
    ]

    signals = [
        result
        for result in ready
        if result.get(
            "signal"
        )
    ]

    errors = [
        result
        for result in results
        if result.get(
            "error"
        )
    ]

    max_candles = max(
        [
            result.get(
                "candles",
                0
            )
            for result in results
        ] or [0]
    )

    elapsed = (
        time.time()
        - start_time
    )

    print(
        f"Ready: {len(ready)}"
    )

    print(
        f"Signals: {len(signals)}"
    )

    print(
        f"Errors: {len(errors)}"
    )

    print(
        f"Max candles: {max_candles}"
    )

    print(
        f"Scan: {elapsed:.2f}s"
    )

    error_samples = []

    for result in errors[:5]:

        error_samples.append(
            f"{result.get('symbol')}: "
            f"{result.get('error')}"
        )

    if not signals:

        message = (
            "ATI FUTURES V11 FIXED\n\n"
            "NO SIGNAL THIS CYCLE\n\n"
            f"Markets: {len(markets)}\n"
            f"Ready: {len(ready)}\n"
            f"Max candles: {max_candles}\n"
            f"Errors: {len(errors)}\n"
            f"Scan: {elapsed:.2f}s\n\n"
            f"ORDER: {ORDER_USDT} USDT\n"
            f"LEVERAGE: {LEVERAGE}x\n"
            f"REAL: {REAL_TRADING}"
        )

        if error_samples:

            message += (
                "\n\nERROR SAMPLE:\n"
                + "\n".join(
                    error_samples
                )
            )

        print(message)
        telegram(message)

        return

    signals.sort(
        key=lambda result:
            result.get(
                "score",
                0
            ),
        reverse=True
    )

    best = signals[0]

    reasons = (
        best.get(
            "buy_reasons",
            []
        )
        if best["signal"] == "BUY"
        else
        best.get(
            "sell_reasons",
            []
        )
    )

    message = (
        "ATI FUTURES V11 SIGNAL\n\n"
        f"SYMBOL: {best['symbol']}\n"
        f"SIGNAL: {best['signal']}\n"
        f"SCORE: {best['score']}\n"
        f"PRICE: {best['price']}\n\n"
        f"TENKAN: {best['tenkan']}\n"
        f"KIJUN: {best['kijun']}\n"
        f"SPAN A: {best['span_a']}\n"
        f"SPAN B: {best['span_b']}\n\n"
        f"REASONS: "
        f"{' / '.join(reasons)}\n\n"
        f"CANDLES: {best['candles']}\n"
        f"ORDER: {ORDER_USDT} USDT\n"
        f"LEVERAGE: {LEVERAGE}x\n"
        f"REAL: {REAL_TRADING}"
    )

    print(message)
    telegram(message)

    if not REAL_TRADING:

        print(
            "TEST MODE - NO REAL ORDER"
        )

        return

    try:

        order = place_real_trade(
            best
        )

        order_message = (
            "ATI REAL FUTURES ORDER\n\n"
            f"SYMBOL: {best['symbol']}\n"
            f"SIDE: {best['signal']}\n"
            f"SCORE: {best['score']}\n"
            f"PRICE: {best['price']}\n"
            f"LEVERAGE: {LEVERAGE}x\n"
            f"ORDER: {ORDER_USDT} USDT\n\n"
            f"ORDER ID: "
            f"{order.get('orderId', 'N/A')}"
        )

        print(order_message)
        telegram(order_message)

    except Exception as error:

        error_message = (
            "REAL FUTURES ORDER ERROR\n\n"
            f"SYMBOL: {best['symbol']}\n"
            f"SIDE: {best['signal']}\n\n"
            f"{error}"
        )

        print(error_message)
        telegram(error_message)


if __name__ == "__main__":
    main()
