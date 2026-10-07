import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN
from datetime import datetime, timezone

# =========================================================
# ATI FUTURES REAL TRADING
# =========================================================

VERSION = "ATI-FUTURES-REAL-V4"

API_BASE = "https://api1.tabdeal.org"

PUBLIC_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V3 = API_BASE + "/r/fapi/v3/"
WRITE_V1 = API_BASE + "/fapi/v1/"

# =========================================================
# SAFE ENV READERS
# =========================================================

def get_str_env(name, default=""):
    value = os.getenv(name, "")
    return value.strip() if value and value.strip() else default


def get_int_env(name, default):
    value = os.getenv(name, "")
    try:
        value = value.strip()
        return int(value) if value else default
    except (ValueError, TypeError):
        return default


def get_float_env(name, default):
    value = os.getenv(name, "")
    try:
        value = value.strip()
        return float(value) if value else default
    except (ValueError, TypeError):
        return default


def get_bool_env(name, default=False):
    value = os.getenv(name, "")
    if not value:
        return default

    return value.strip().lower() in (
        "true",
        "1",
        "yes",
        "on",
    )


# =========================================================
# SETTINGS
# =========================================================

API_KEY = get_str_env(
    "TABDIL_API_KEY",
    get_str_env("TABDEAL_API_KEY")
)

API_SECRET = get_str_env(
    "TABDIL_API_SECRET",
    get_str_env("TABDEAL_API_SECRET")
)

TELEGRAM_BOT_TOKEN = get_str_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = get_str_env("TELEGRAM_CHAT_ID")

LIVE_TRADING = get_bool_env("LIVE_TRADING", False)

ORDER_USDT = get_float_env("ORDER_QTY", 2.0)

# اگر LEVERAGE خالی باشد = 3
LEVERAGE = get_int_env("LEVERAGE", 3)

MAX_NEW_TRADES = get_int_env("MAX_NEW_TRADES", 1)

SL_PERCENT = get_float_env("SL_PERCENT", 1.0)
TP_PERCENT = get_float_env("TP_PERCENT", 2.0)

SCAN_LIMIT = get_int_env("SCAN_LIMIT", 40)

REQUEST_TIMEOUT = 20

# =========================================================
# HTTP SESSION
# =========================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/4.0"
})


# =========================================================
# TELEGRAM
# =========================================================

def telegram(message):

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    try:
        url = (
            f"https://api.telegram.org/bot"
            f"{TELEGRAM_BOT_TOKEN}/sendMessage"
        )

        requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=10,
        )

    except Exception:
        pass


# =========================================================
# TIME
# =========================================================

def now_utc():

    return datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M:%S UTC")


# =========================================================
# SIGNATURE
# =========================================================

def signed_params(params):

    params = dict(params)

    params["timestamp"] = int(time.time() * 1000)

    params.setdefault(
        "recvWindow",
        5000
    )

    query = urlencode(params)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    return params


# =========================================================
# PUBLIC REQUEST
# =========================================================

def public_get(url, params=None):

    r = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT
    )

    if r.status_code != 200:
        raise Exception(
            f"HTTP {r.status_code}: {r.text[:500]}"
        )

    return r.json()


# =========================================================
# PRIVATE REQUEST
# =========================================================

def private_get(url, params=None):

    if not API_KEY or not API_SECRET:
        raise Exception("API KEY/SECRET missing")

    params = signed_params(
        params or {}
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    r = session.get(
        url,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT
    )

    if r.status_code != 200:
        raise Exception(
            f"HTTP {r.status_code}: {r.text[:500]}"
        )

    return r.json()


# =========================================================
# PRIVATE POST
# =========================================================

def private_post(url, params=None):

    if not API_KEY or not API_SECRET:
        raise Exception("API KEY/SECRET missing")

    params = signed_params(
        params or {}
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    r = session.post(
        url,
        params=params,
        headers=headers,
        timeout=REQUEST_TIMEOUT
    )

    if r.status_code not in (200, 201):
        raise Exception(
            f"HTTP {r.status_code}: {r.text[:1000]}"
        )

    return r.json()


# =========================================================
# ACCOUNT
# =========================================================

def get_account():

    return private_get(
        PRIVATE_V3 + "account"
    )


# =========================================================
# BALANCE
# =========================================================

def get_balance():

    return private_get(
        PRIVATE_V3 + "balance"
    )


def extract_usdt(obj):

    values = []

    def walk(x):

        if isinstance(x, dict):

            asset = str(
                x.get("asset", "")
            ).upper()

            if asset == "USDT":

                for key in (
                    "availableBalance",
                    "available",
                    "free",
                    "walletBalance",
                    "balance",
                    "crossWalletBalance",
                ):

                    value = x.get(key)

                    try:
                        if value is not None:
                            values.append(
                                float(value)
                            )
                    except:
                        pass

            for value in x.values():
                walk(value)

        elif isinstance(x, list):

            for item in x:
                walk(item)

    walk(obj)

    positive = [
        x for x in values
        if x >= 0
    ]

    return max(positive) if positive else 0.0


def get_usdt_balance():

    candidates = []

    try:
        data = get_balance()
        candidates.append(
            extract_usdt(data)
        )
    except Exception:
        pass

    try:
        data = get_account()
        candidates.append(
            extract_usdt(data)
        )
    except Exception:
        pass

    return max(candidates) if candidates else 0.0


# =========================================================
# EXCHANGE INFO
# =========================================================

def get_exchange_info():

    return public_get(
        PUBLIC_V1 + "exchangeInfo"
    )


# =========================================================
# SYMBOLS
# =========================================================

def get_symbols():

    data = get_exchange_info()

    result = []

    for s in data.get(
        "symbols",
        []
    ):

        symbol = s.get(
            "symbol",
            ""
        )

        status = str(
            s.get("status", "")
        ).upper()

        quote = str(
            s.get("quoteAsset", "")
        ).upper()

        if not symbol:
            continue

        if quote not in (
            "USDT",
            "USDC",
            "USD",
        ):
            continue

        if status not in (
            "TRADING",
            "ENABLED",
            "OPEN",
        ):
            continue

        result.append(s)

    return result


# =========================================================
# PRICE
# =========================================================

def get_price(symbol):

    data = public_get(
        PUBLIC_V1 + "ticker/price",
        {
            "symbol": symbol
        }
    )

    return float(
        data["price"]
    )


# =========================================================
# ORDER BOOK
# =========================================================

def get_depth(symbol):

    return public_get(
        PUBLIC_V1 + "depth",
        {
            "symbol": symbol,
            "limit": 20
        }
    )


def pressure(symbol):

    try:

        data = get_depth(symbol)

        bids = data.get(
            "bids",
            []
        )

        asks = data.get(
            "asks",
            []
        )

        bid_volume = sum(
            float(x[1])
            for x in bids[:20]
        )

        ask_volume = sum(
            float(x[1])
            for x in asks[:20]
        )

        total = (
            bid_volume +
            ask_volume
        )

        if total <= 0:
            return 50.0

        return (
            bid_volume /
            total
        ) * 100

    except Exception:

        return 50.0


# =========================================================
# POSITION RISK
# =========================================================

def get_positions():

    return private_get(
        PRIVATE_V3 + "positionRisk"
    )


def get_open_positions():

    try:

        data = get_positions()

        result = []

        if isinstance(data, list):

            for p in data:

                try:
                    qty = abs(
                        float(
                            p.get(
                                "positionAmt",
                                0
                            )
                        )
                    )
                except:
                    qty = 0

                if qty > 0:
                    result.append(p)

        return result

    except Exception as e:

        print(
            "POSITION ERROR:",
            e
        )

        return []


# =========================================================
# LEVERAGE
# =========================================================

def change_leverage(symbol):

    return private_post(
        WRITE_V1 + "leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE
        }
    )


# =========================================================
# SYMBOL RULES
# =========================================================

def symbol_rules(symbol_info):

    step = 0.0
    min_qty = 0.0
    min_notional = 0.0
    tick = 0.0

    for f in symbol_info.get(
        "filters",
        []
    ):

        typ = f.get(
            "filterType"
        )

        if typ == "LOT_SIZE":

            step = float(
                f.get(
                    "stepSize",
                    0
                )
            )

            min_qty = float(
                f.get(
                    "minQty",
                    0
                )
            )

        elif typ in (
            "MIN_NOTIONAL",
            "NOTIONAL"
        ):

            min_notional = float(
                f.get(
                    "notional",
                    f.get(
                        "minNotional",
                        0
                    )
                )
            )

        elif typ == "PRICE_FILTER":

            tick = float(
                f.get(
                    "tickSize",
                    0
                )
            )

    return (
        step,
        min_qty,
        min_notional,
        tick
    )


# =========================================================
# QUANTITY
# =========================================================

def make_quantity(
    price,
    symbol_info
):

    step, min_qty, min_notional, tick = (
        symbol_rules(symbol_info)
    )

    if price <= 0:
        return 0.0

    qty = ORDER_USDT / price

    if step > 0:

        q = Decimal(
            str(qty)
        )

        s = Decimal(
            str(step)
        )

        qty = float(
            (q // s) * s
        )

    if qty < min_qty:
        qty = min_qty

    if (
        min_notional > 0
        and qty * price < min_notional
    ):

        qty = (
            min_notional /
            price
        )

        if step > 0:

            q = Decimal(
                str(qty)
            )

            s = Decimal(
                str(step)
            )

            qty = float(
                (q // s + 1) * s
            )

    return qty


# =========================================================
# MARKET ORDER
# =========================================================

def market_order(
    symbol,
    side,
    quantity
):

    return private_post(
        WRITE_V1 + "order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity,
        }
    )


# =========================================================
# FIND POSITION
# =========================================================

def find_position(symbol):

    for _ in range(10):

        try:

            positions = get_positions()

            if isinstance(
                positions,
                list
            ):

                for p in positions:

                    if p.get(
                        "symbol"
                    ) != symbol:
                        continue

                    try:

                        qty = float(
                            p.get(
                                "positionAmt",
                                0
                            )
                        )

                    except:
                        qty = 0

                    if abs(qty) > 0:
                        return p

        except:
            pass

        time.sleep(1)

    return None


# =========================================================
# SL / TP
# =========================================================

def set_position_sl_tp(
    position
):

    try:

        symbol = position.get(
            "symbol"
        )

        position_id = position.get(
            "positionId"
        )

        entry = float(
            position.get(
                "entryPrice",
                0
            )
        )

        qty = float(
            position.get(
                "positionAmt",
                0
            )
        )

        if entry <= 0:
            return None

        if qty > 0:

            sl = entry * (
                1 -
                SL_PERCENT / 100
            )

            tp = entry * (
                1 +
                TP_PERCENT / 100
            )

        else:

            sl = entry * (
                1 +
                SL_PERCENT / 100
            )

            tp = entry * (
                1 -
                TP_PERCENT / 100
            )

        params = {
            "positionId": position_id,
            "symbol": symbol,
            "slPrice": sl,
            "tpPrice": tp,
            "workingType": "MARK_PRICE",
        }

        return private_post(
            WRITE_V1 + "positionSlTp",
            params
        )

    except Exception as e:

        print(
            "SL/TP ERROR:",
            e
        )

        return None


# =========================================================
# MAIN
# =========================================================

def main():

    print()
    print("ATI Crypto Bot")
    print("💓 ATI FUTURES")
    print("⚡ REAL TRADING ENGINE")
    print("📡 TABDEAL FUTURES")
    print(
        f"⚙️ LEVERAGE: {LEVERAGE}x"
    )
    print(
        f"💵 ORDER: {ORDER_USDT} USDT"
    )
    print(
        f"🟢 LIVE: {LIVE_TRADING}"
    )
    print(
        f"🕐 {now_utc()}"
    )
    print()

    telegram(
        f"💓 ATI FUTURES\n"
        f"⚡ {VERSION}\n"
        f"📡 TABDEAL FUTURES\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"🟢 LIVE: {LIVE_TRADING}\n"
        f"🕐 {now_utc()}"
    )

    # -----------------------------------------------------
    # API CHECK
    # -----------------------------------------------------

    if not API_KEY or not API_SECRET:

        print(
            "❌ API KEY/SECRET missing"
        )

        telegram(
            "❌ ATI FUTURES ERROR\n"
            "API KEY/SECRET missing"
        )

        return

    try:

        account = get_account()

        print(
            "✅ FUTURES AUTH SUCCESS"
        )

        print(
            "🔓 canTrade=",
            account.get(
                "canTrade"
            )
        )

    except Exception as e:

        print(
            "❌ FUTURES AUTH ERROR"
        )

        print(e)

        telegram(
            "❌ ATI FUTURES AUTH ERROR\n\n"
            + str(e)[:1000]
        )

        return

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    balance = get_usdt_balance()

    print(
        f"💰 USDT: {balance}"
    )

    # -----------------------------------------------------
    # OPEN POSITIONS
    # -----------------------------------------------------

    positions = get_open_positions()

    print(
        f"📌 OPEN POSITIONS: {len(positions)}"
    )

    if positions:

        for p in positions:

            print(
                "•",
                p.get("symbol"),
                p.get("positionAmt"),
                p.get("entryPrice")
            )

        print(
            "⛔ MAX NEW TRADES REACHED"
        )

        return

    # -----------------------------------------------------
    # EXCHANGE INFO
    # -----------------------------------------------------

    try:

        symbols = get_symbols()

        print(
            f"📊 Markets: {len(symbols)}"
        )

    except Exception as e:

        print(
            "❌ EXCHANGE INFO ERROR"
        )

        print(e)

        telegram(
            "❌ ATI FUTURES EXCHANGE INFO ERROR\n\n"
            + str(e)[:1000]
        )

        return

    # -----------------------------------------------------
    # SCAN
    # -----------------------------------------------------

    candidates = []

    for info in symbols[:SCAN_LIMIT]:

        symbol = info.get(
            "symbol"
        )

        try:

            p = pressure(
                symbol
            )

            if p >= 65:

                candidates.append(
                    (
                        p,
                        symbol,
                        "BUY"
                    )
                )

            elif p <= 35:

                candidates.append(
                    (
                        100 - p,
                        symbol,
                        "SELL"
                    )
                )

        except:

            continue

    if not candidates:

        print(
            "❌ سیگنال قوی پیدا نشد."
        )

        telegram(
            f"📊 ATI FUTURES\n"
            f"Markets: {len(symbols)}\n"
            f"❌ سیگنال قوی پیدا نشد.\n"
            f"💰 USDT: {balance}\n"
            f"🟢 LIVE: {LIVE_TRADING}\n"
            f"🕐 {now_utc()}"
        )

        return

    candidates.sort(
        reverse=True
    )

    score, symbol, side = candidates[0]

    print()
    print(
        "🚨 SIGNAL FOUND"
    )

    print(
        "🪙 SYMBOL:",
        symbol
    )

    print(
        "📈 SIDE:",
        side
    )

    print(
        f"🔥 PRESSURE: {score:.2f}%"
    )

    # -----------------------------------------------------
    # PRICE
    # -----------------------------------------------------

    try:

        price = get_price(
            symbol
        )

        quantity = make_quantity(
            price,
            next(
                x for x in symbols
                if x.get("symbol") == symbol
            )
        )

    except Exception as e:

        print(
            "❌ QUANTITY ERROR:",
            e
        )

        return

    print(
        f"💵 PRICE: {price}"
    )

    print(
        f"📦 QTY: {quantity}"
    )

    # -----------------------------------------------------
    # LIVE OFF
    # -----------------------------------------------------

    if not LIVE_TRADING:

        print()
        print(
            "🔴 LIVE_TRADING=False"
        )

        print(
            "⚠️ سفارش واقعی ارسال نشد."
        )

        telegram(
            f"⚠️ ATI FUTURES SIGNAL\n"
            f"🪙 {symbol}\n"
            f"📈 {side}\n"
            f"🔥 Pressure: {score:.2f}%\n"
            f"💵 Price: {price}\n"
            f"🔴 LIVE: False\n"
            f"🚫 REAL ORDER NOT SENT"
        )

        return

    # -----------------------------------------------------
    # REAL TRADING
    # -----------------------------------------------------

    if balance < 0.5:

        print(
            "❌ USDT balance too low."
        )

        telegram(
            f"❌ ATI FUTURES\n"
            f"USDT balance too low: {balance}"
        )

        return

    try:

        print(
            f"⚙️ Setting leverage {LEVERAGE}x..."
        )

        lev = change_leverage(
            symbol
        )

        print(
            "✅ LEVERAGE OK"
        )

    except Exception as e:

        print(
            "❌ LEVERAGE ERROR:",
            e
        )

        telegram(
            f"❌ LEVERAGE ERROR\n"
            f"{symbol}\n\n"
            f"{str(e)[:1000]}"
        )

        return

    # -----------------------------------------------------
    # ORDER
    # -----------------------------------------------------

    try:

        print()
        print(
            "🚨 SENDING REAL ORDER..."
        )

        result = market_order(
            symbol,
            side,
            quantity
        )

        print(
            "✅ REAL ORDER SUCCESS"
        )

        print(
            result
        )

        telegram(
            f"🚨 REAL FUTURES TRADE OPENED\n\n"
            f"🪙 {symbol}\n"
            f"📈 SIDE: {side}\n"
            f"💵 PRICE: {price}\n"
            f"📦 QTY: {quantity}\n"
            f"⚙️ LEVERAGE: {LEVERAGE}x\n"
            f"🆔 ORDER: {result.get('orderId')}\n"
            f"🕐 {now_utc()}"
        )

    except Exception as e:

        print()
        print(
            "❌ REAL ORDER ERROR"
        )

        print(e)

        telegram(
            f"❌ REAL FUTURES ORDER ERROR\n\n"
            f"🪙 {symbol}\n"
            f"📈 {side}\n"
            f"{str(e)[:1500]}"
        )

        return

    # -----------------------------------------------------
    # POSITION + SL/TP
    # -----------------------------------------------------

    position = find_position(
        symbol
    )

    if not position:

        print(
            "⚠️ Position not found after order."
        )

        telegram(
            f"⚠️ ORDER ACCEPTED BUT POSITION NOT FOUND\n"
            f"🪙 {symbol}"
        )

        return

    print()
    print(
        "✅ POSITION OPEN"
    )

    print(
        "🪙",
        symbol
    )

    print(
        "📍 ENTRY:",
        position.get(
            "entryPrice"
        )
    )

    # -----------------------------------------------------
    # SL / TP
    # -----------------------------------------------------

    sltp = set_position_sl_tp(
        position
    )

    if sltp:

        print(
            "🛡️ SL/TP SET SUCCESS"
        )

        telegram(
            f"🛡️ SL/TP SET\n"
            f"🪙 {symbol}\n"
            f"🛑 SL: {SL_PERCENT}%\n"
            f"🎯 TP: {TP_PERCENT}%"
        )

    else:

        print(
            "⚠️ SL/TP could not be confirmed."
        )

        telegram(
            f"⚠️ POSITION OPENED\n"
            f"🪙 {symbol}\n"
            f"⚠️ SL/TP confirmation failed."
        )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        print()
        print(
            "❌ ATI FATAL ERROR"
        )

        print(e)

        telegram(
            "❌ ATI FUTURES FATAL ERROR\n\n"
            + str(e)[:1500]
        )
