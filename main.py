import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN

BASE_URL = "https://api1.tabdeal.org"

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_API_KEY")
)

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDEAL_API_SECRET")
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

LIVE_TRADING = os.getenv(
    "LIVE_TRADING", "false"
).lower() == "true"

SYMBOL = os.getenv(
    "FUTURES_SYMBOL", "BTCUSDT"
).upper()

INTERVAL = os.getenv(
    "FUTURES_INTERVAL", "5m"
)

LEVERAGE = int(
    os.getenv("FUTURES_LEVERAGE", "3")
)

ORDER_USDT = Decimal(
    os.getenv("FUTURES_ORDER_USDT", "2")
)

TP_PERCENT = Decimal(
    os.getenv("TP_PERCENT", "2")
)

SL_PERCENT = Decimal(
    os.getenv("SL_PERCENT", "1")
)

RECV_WINDOW = 5000

session = requests.Session()


def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        url = (
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage"
        )

        requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=15
        )

    except Exception as e:
        print("TELEGRAM ERROR:", repr(e))


def public_get(path, params=None):
    url = BASE_URL + path

    r = session.get(
        url,
        params=params or {},
        timeout=20
    )

    print("PUBLIC:", r.status_code, r.url)

    if r.status_code >= 400:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:1000]}"
        )

    return r.json()


def signed_request(method, path, params=None):

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "API KEY OR SECRET NOT FOUND"
        )

    data = dict(params or {})

    data["timestamp"] = int(
        time.time() * 1000
    )

    data["recvWindow"] = RECV_WINDOW

    query = urlencode(
        data,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = BASE_URL + path

    if method == "GET":
        r = session.get(
            url,
            params=data,
            headers=headers,
            timeout=20
        )

    elif method == "POST":
        r = session.post(
            url,
            data=data,
            headers=headers,
            timeout=20
        )

    elif method == "DELETE":
        r = session.delete(
            url,
            params=data,
            headers=headers,
            timeout=20
        )

    else:
        raise RuntimeError(
            "INVALID HTTP METHOD"
        )

    print(
        "SIGNED:",
        method,
        path,
        r.status_code
    )

    if r.status_code >= 400:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:1500]}"
        )

    try:
        return r.json()
    except Exception:
        return {"raw": r.text}


def futures_ping():
    return public_get(
        "/fapi/v1/ping"
    )


def server_time():
    return public_get(
        "/fapi/v1/time"
    )


def exchange_info():
    return public_get(
        "/fapi/v1/exchangeInfo",
        {
            "symbol": SYMBOL
        }
    )


def get_klines():

    data = public_get(
        "/fapi/v1/klines",
        {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "limit": 100
        }
    )

    if not isinstance(data, list):
        raise RuntimeError(
            "INVALID KLINE RESPONSE"
        )

    if len(data) < 30:
        raise RuntimeError(
            "NOT ENOUGH KLINES"
        )

    candles = []

    for row in data:

        candles.append({
            "time": int(row[0]),
            "open": Decimal(str(row[1])),
            "high": Decimal(str(row[2])),
            "low": Decimal(str(row[3])),
            "close": Decimal(str(row[4])),
            "volume": Decimal(str(row[5]))
        })

    return candles


def get_positions():

    return signed_request(
        "GET",
        "/fapi/v1/position",
        {
            "symbol": SYMBOL
        }
    )


def has_open_position():

    data = get_positions()

    print(
        "POSITIONS:",
        data
    )

    if isinstance(data, list):

        for position in data:

            for key in (
                "positionAmt",
                "quantity",
                "qty"
            ):

                if key in position:

                    try:
                        value = Decimal(
                            str(position[key])
                        )

                        if value != 0:
                            return True

                    except Exception:
                        pass

    if isinstance(data, dict):

        for key in (
            "positionAmt",
            "quantity",
            "qty"
        ):

            if key in data:

                try:
                    value = Decimal(
                        str(data[key])
                    )

                    if value != 0:
                        return True

                except Exception:
                    pass

    return False


def change_leverage():

    result = signed_request(
        "POST",
        "/fapi/v1/leverage",
        {
            "symbol": SYMBOL,
            "leverage": LEVERAGE
        }
    )

    print(
        "LEVERAGE:",
        result
    )

    return result


def get_signal(candles):

    closed = candles[:-1]

    if len(closed) < 20:
        return None

    c = closed[-1]
    p = closed[-2]
    p2 = closed[-3]

    recent_high = max(
        x["high"]
        for x in closed[-7:-1]
    )

    recent_low = min(
        x["low"]
        for x in closed[-7:-1]
    )

    long_break = (
        c["close"] > recent_high
    )

    long_candle = (
        c["close"] > c["open"]
    )

    long_structure = (
        c["close"] > p["close"]
        and p["close"] >= p2["close"]
    )

    if (
        long_break
        and long_candle
        and long_structure
    ):
        return "LONG"

    short_break = (
        c["close"] < recent_low
    )

    short_candle = (
        c["close"] < c["open"]
    )

    short_structure = (
        c["close"] < p["close"]
        and p["close"] <= p2["close"]
    )

    if (
        short_break
        and short_candle
        and short_structure
    ):
        return "SHORT"

    return None


def calculate_quantity(price):

    notional = (
        ORDER_USDT *
        Decimal(LEVERAGE)
    )

    quantity = (
        notional / price
    )

    quantity = quantity.quantize(
        Decimal("0.000001"),
        rounding=ROUND_DOWN
    )

    if quantity <= 0:
        raise RuntimeError(
            "QUANTITY IS ZERO"
        )

    return quantity


def market_order(side, quantity):

    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": SYMBOL,
            "side": side,
            "type": "MARKET",
            "quantity": str(quantity)
        }
    )


def set_sl_tp():

    positions = get_positions()

    print(
        "POSITIONS AFTER ENTRY:",
        positions
    )

    if not isinstance(
        positions,
        list
    ):
        return

    for position in positions:

        try:

            position_id = int(
                position.get(
                    "positionId"
                )
            )

        except Exception:

            continue

        try:

            quantity = Decimal(
                str(
                    position.get(
                        "positionAmt",
                        position.get(
                            "quantity",
                            "0"
                        )
                    )
                )
            )

        except Exception:

            quantity = Decimal("0")

        if quantity == 0:
            continue

        try:

            entry = Decimal(
                str(
                    position.get(
                        "entryPrice",
                        position.get(
                            "avgPrice",
                            "0"
                        )
                    )
                )
            )

        except Exception:

            continue

        if entry <= 0:
            continue

        short_position = quantity < 0

        if short_position:

            tp = (
                entry *
                (
                    Decimal("1")
                    -
                    TP_PERCENT /
                    Decimal("100")
                )
            )

            sl = (
                entry *
                (
                    Decimal("1")
                    +
                    SL_PERCENT /
                    Decimal("100")
                )
            )

        else:

            tp = (
                entry *
                (
                    Decimal("1")
                    +
                    TP_PERCENT /
                    Decimal("100")
                )
            )

            sl = (
                entry *
                (
                    Decimal("1")
                    -
                    SL_PERCENT /
                    Decimal("100")
                )
            )

        tp = tp.quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN
        )

        sl = sl.quantize(
            Decimal("0.01"),
            rounding=ROUND_DOWN
        )

        result = signed_request(
            "POST",
            "/fapi/v1/positionSlTp",
            {
                "positionId": position_id,
                "symbol": SYMBOL,
                "slPrice": str(sl),
                "tpPrice": str(tp)
            }
        )

        print(
            "SL TP RESULT:",
            result
        )

        telegram(
            "SL TP SET\n"
            f"SYMBOL: {SYMBOL}\n"
            f"ENTRY: {entry}\n"
            f"TP: {tp}\n"
            f"SL: {sl}"
        )


def main():

    print("=" * 50)
    print("ATI FUTURES DIRECT REST")
    print("=" * 50)

    telegram(
        "ATI FUTURES ALIVE\n"
        f"SYMBOL: {SYMBOL}\n"
        f"INTERVAL: {INTERVAL}\n"
        f"LEVERAGE: {LEVERAGE}X\n"
        f"ORDER: {ORDER_USDT} USDT\n"
        f"TP: {TP_PERCENT}%\n"
        f"SL: {SL_PERCENT}%\n"
        f"LIVE: {LIVE_TRADING}"
    )

    print(
        "PING:",
        futures_ping()
    )

    print(
        "SERVER TIME:",
        server_time()
    )

    print(
        "EXCHANGE INFO:",
        exchange_info()
    )

    get_positions()

    print(
        "AUTH SUCCESS"
    )

    if has_open_position():

        print(
            "OPEN POSITION EXISTS"
        )

        telegram(
            "ATI FUTURES\n"
            f"{SYMBOL}\n"
            "OPEN POSITION EXISTS\n"
            "NO NEW ENTRY"
        )

        return

    if LIVE_TRADING:

        change_leverage()

    candles = get_klines()

    price = candles[-2]["close"]

    print(
        "CLOSED PRICE:",
        price
    )

    sig = get_signal(candles)

    print(
        "SIGNAL:",
        sig
    )

    if not sig:

        telegram(
            "ATI FUTURES\n"
            f"SYMBOL: {SYMBOL}\n"
            f"PRICE: {price}\n"
            "NO VALID SIGNAL\n"
            "NO TRADE"
        )

        return

    quantity = calculate_quantity(
        price
    )

    side = (
        "BUY"
        if sig == "LONG"
        else
        "SELL"
    )

    print(
        "SIGNAL:",
        sig
    )

    print(
        "SIDE:",
        side
    )

    print(
        "QUANTITY:",
        quantity
    )

    if not LIVE_TRADING:

        telegram(
            "ATI FUTURES PAPER\n"
            f"SYMBOL: {SYMBOL}\n"
            f"SIGNAL: {sig}\n"
            f"PRICE: {price}\n"
            f"QTY: {quantity}\n"
            f"LEVERAGE: {LEVERAGE}X\n"
            "LIVE TRADING OFF\n"
            "NO REAL ORDER"
        )

        return

    telegram(
        "ATI FUTURES REAL ENTRY\n"
        f"SYMBOL: {SYMBOL}\n"
        f"SIDE: {side}\n"
        f"PRICE: {price}\n"
        f"QTY: {quantity}\n"
        f"LEVERAGE: {LEVERAGE}X\n"
        "SENDING REAL ORDER"
    )

    order = market_order(
        side,
        quantity
    )

    print(
        "REAL ORDER:",
        order
    )

    telegram(
        "ATI FUTURES REAL ORDER\n"
        f"SYMBOL: {SYMBOL}\n"
        f"SIDE: {side}\n"
        f"QTY: {quantity}\n"
        f"ORDER: {order}"
    )

    time.sleep(2)

    set_sl_tp()

    print(
        "BOT FINISHED"
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        print(
            "ATI FUTURES ERROR:",
            repr(e)
        )

        telegram(
            "ATI FUTURES ERROR\n"
            f"{repr(e)}"
        )

        raise
