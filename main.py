import os
import time
import hmac
import hashlib
import math
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone


# ============================================================
# ATI FUTURES REAL TRADING
# TABDEAL
# ============================================================

API_BASE = "https://api1.tabdeal.org"

PUBLIC_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V1 = API_BASE + "/r/fapi/v1/"
PRIVATE_V3 = API_BASE + "/r/fapi/v3/"
WRITE_V1 = API_BASE + "/fapi/v1/"

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_API_KEY")
    or ""
)

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDEAL_API_SECRET")
    or ""
)

LIVE_TRADING = (
    os.getenv("LIVE_TRADING", "false").lower()
    == "true"
)

ORDER_USDT = float(
    os.getenv("ORDER_QTY", "2")
)

LEVERAGE = int(
    os.getenv("LEVERAGE", "3")
)

MAX_NEW_TRADES = int(
    os.getenv("MAX_NEW_TRADES", "1")
)

SL_PERCENT = float(
    os.getenv("SL_PERCENT", "1.0")
)

TP_PERCENT = float(
    os.getenv("TP_PERCENT", "2.0")
)

SCAN_LIMIT = int(
    os.getenv("SCAN_LIMIT", "40")
)

TIMEOUT = 20


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-Bot/1.0",
    "Accept": "application/json",
})


# ============================================================
# TELEGRAM
# ============================================================

TG_TOKEN = os.getenv(
    "TELEGRAM_BOT_TOKEN",
    ""
)

TG_CHAT_ID = os.getenv(
    "TELEGRAM_CHAT_ID",
    ""
)


def telegram(message):

    if not TG_TOKEN or not TG_CHAT_ID:
        return

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TG_TOKEN}/sendMessage"
        )

        requests.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": message
            },
            timeout=15
        )

    except Exception:
        pass


def utc_now():

    return datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M:%S UTC"
    )


# ============================================================
# SIGNATURE
# ============================================================

def signed_params(params=None):

    data = dict(params or {})

    data["timestamp"] = int(
        time.time() * 1000
    )

    data.setdefault(
        "recvWindow",
        10000
    )

    query = urlencode(data)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    data["signature"] = signature

    return data


# ============================================================
# PUBLIC
# ============================================================

def public_get(
    endpoint,
    params=None
):

    url = PUBLIC_V1 + endpoint

    response = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT
    )

    if response.status_code != 200:

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:800]}"
        )

    return response.json()


# ============================================================
# PRIVATE GET V3
# ============================================================

def private_get_v3(
    endpoint,
    params=None
):

    data = signed_params(
        params
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = PRIVATE_V3 + endpoint

    response = session.get(
        url,
        params=data,
        headers=headers,
        timeout=TIMEOUT
    )

    if response.status_code != 200:

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


# ============================================================
# PRIVATE GET V1
# ============================================================

def private_get_v1(
    endpoint,
    params=None
):

    data = signed_params(
        params
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = PRIVATE_V1 + endpoint

    response = session.get(
        url,
        params=data,
        headers=headers,
        timeout=TIMEOUT
    )

    if response.status_code != 200:

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


# ============================================================
# PRIVATE POST V1
# ============================================================

def private_post_v1(
    endpoint,
    params=None
):

    data = signed_params(
        params
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = WRITE_V1 + endpoint

    response = session.post(
        url,
        params=data,
        headers=headers,
        timeout=TIMEOUT
    )

    if response.status_code not in (
        200,
        201
    ):

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:1200]}"
        )

    return response.json()


# ============================================================
# PRIVATE DELETE V1
# ============================================================

def private_delete_v1(
    endpoint,
    params=None
):

    data = signed_params(
        params
    )

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = WRITE_V1 + endpoint

    response = session.delete(
        url,
        params=data,
        headers=headers,
        timeout=TIMEOUT
    )

    if response.status_code != 200:

        raise Exception(
            f"HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    return response.json()


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    data = public_get(
        "exchangeInfo"
    )

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        if isinstance(
            data.get("symbols"),
            list
        ):
            return data["symbols"]

        if isinstance(
            data.get("data"),
            list
        ):
            return data["data"]

        if isinstance(
            data.get("result"),
            list
        ):
            return data["result"]

    raise Exception(
        "Invalid Futures exchangeInfo format"
    )


# ============================================================
# FUTURES SYMBOLS
# ============================================================

def get_futures_symbols():

    data = get_exchange_info()

    result = []

    for item in data:

        if not isinstance(
            item,
            dict
        ):
            continue

        symbol = str(
            item.get(
                "symbol",
                ""
            )
        ).upper()

        if not symbol:
            continue

        status = str(
            item.get(
                "status",
                ""
            )
        ).upper()

        if status and status not in (
            "TRADING",
            "ENABLED",
            "OPEN"
        ):
            continue

        quote = str(
            item.get(
                "quoteAsset",
                ""
            )
        ).upper()

        if quote:

            if quote not in (
                "USDT",
                "USDC",
                "USD"
            ):
                continue

        else:

            if not (
                symbol.endswith("USDT")
                or symbol.endswith("USDC")
                or symbol.endswith("USD")
            ):
                continue

        result.append(item)

    return result


# ============================================================
# PRICE
# ============================================================

def get_price(symbol):

    data = public_get(
        "ticker/price",
        {
            "symbol": symbol
        }
    )

    if isinstance(data, dict):

        for key in (
            "price",
            "lastPrice",
            "last",
            "close"
        ):

            if data.get(key) is not None:

                return float(
                    data[key]
                )

    raise Exception(
        f"Price not found: {symbol}"
    )


# ============================================================
# DEPTH
# ============================================================

def get_depth(symbol):

    return public_get(
        "depth",
        {
            "symbol": symbol,
            "limit": 20
        }
    )


# ============================================================
# ACCOUNT
# ============================================================

def get_account():

    return private_get_v3(
        "account"
    )


# ============================================================
# BALANCE
# ============================================================

def get_balance_response():

    return private_get_v3(
        "balance"
    )


def extract_usdt_balance(data):

    values = []

    def scan(obj):

        if isinstance(
            obj,
            dict
        ):

            asset = str(
                obj.get(
                    "asset",
                    ""
                )
            ).upper()

            if asset == "USDT":

                for key in (
                    "availableBalance",
                    "available",
                    "free",
                    "walletBalance",
                    "balance",
                    "crossWalletBalance",
                    "marginAvailable"
                ):

                    value = obj.get(
                        key
                    )

                    if value is not None:

                        try:

                            values.append(
                                float(value)
                            )

                        except Exception:
                            pass

            for value in obj.values():
                scan(value)

        elif isinstance(
            obj,
            list
        ):

            for value in obj:
                scan(value)

    scan(data)

    if not values:
        return 0.0

    # available/free values are preferable
    positive = [
        x for x in values
        if x > 0
    ]

    if positive:
        return max(
            positive
        )

    return max(
        values
    )


def get_usdt_balance():

    # اول balance رسمی Futures
    try:

        data = get_balance_response()

        amount = extract_usdt_balance(
            data
        )

        if amount > 0:
            return amount

    except Exception as e:

        print(
            "⚠️ BALANCE ENDPOINT:",
            e
        )

    # سپس account
    try:

        data = get_account()

        amount = extract_usdt_balance(
            data
        )

        if amount > 0:
            return amount

    except Exception as e:

        print(
            "⚠️ ACCOUNT BALANCE:",
            e
        )

    return 0.0


# ============================================================
# POSITION RISK
# ============================================================

def get_position_risk():

    return private_get_v3(
        "positionRisk"
    )


def get_open_positions():

    data = get_position_risk()

    if isinstance(
        data,
        list
    ):

        positions = data

    elif isinstance(
        data,
        dict
    ):

        positions = (
            data.get("positions")
            or data.get("data")
            or data.get("result")
            or []
        )

    else:

        positions = []

    result = []

    for position in positions:

        if not isinstance(
            position,
            dict
        ):
            continue

        try:

            amount = float(
                position.get(
                    "positionAmt",
                    position.get(
                        "amount",
                        0
                    )
                )
            )

            if abs(amount) > 0:
                result.append(
                    position
                )

        except Exception:
            continue

    return result


# ============================================================
# LEVERAGE
# ============================================================

def change_leverage(symbol):

    return private_post_v1(
        "leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE
        }
    )


# ============================================================
# SYMBOL FILTERS
# ============================================================

def get_symbol_rules(
    symbol_info
):

    qty_step = 0.001
    min_qty = 0.001
    min_notional = 1.0
    price_tick = 0.000001

    filters = symbol_info.get(
        "filters",
        []
    )

    for f in filters:

        if not isinstance(
            f,
            dict
        ):
            continue

        ftype = str(
            f.get(
                "filterType",
                ""
            )
        )

        if ftype in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE"
        ):

            try:

                qty_step = float(
                    f.get(
                        "stepSize",
                        qty_step
                    )
                )

            except Exception:
                pass

            try:

                min_qty = float(
                    f.get(
                        "minQty",
                        min_qty
                    )
                )

            except Exception:
                pass

        elif ftype == "MIN_NOTIONAL":

            try:

                min_notional = float(
                    f.get(
                        "notional",
                        f.get(
                            "minNotional",
                            min_notional
                        )
                    )
                )

            except Exception:
                pass

        elif ftype == "PRICE_FILTER":

            try:

                price_tick = float(
                    f.get(
                        "tickSize",
                        price_tick
                    )
                )

            except Exception:
                pass

    return (
        qty_step,
        min_qty,
        min_notional,
        price_tick
    )


def floor_to_step(
    value,
    step
):

    if step <= 0:
        return value

    return (
        math.floor(
            value / step
        ) * step
    )


def format_number(
    value,
    step
):

    if step <= 0:
        return str(value)

    decimals = max(
        0,
        int(
            round(
                -math.log10(step)
            )
        )
    )

    return f"{value:.{decimals}f}"


# ============================================================
# QUANTITY
# ============================================================

def calculate_quantity(
    price,
    symbol_info
):

    (
        step,
        min_qty,
        min_notional,
        _
    ) = get_symbol_rules(
        symbol_info
    )

    qty = (
        ORDER_USDT /
        price
    )

    qty = floor_to_step(
        qty,
        step
    )

    if (
        qty * price
        < min_notional
    ):

        qty = floor_to_step(
            (
                min_notional
                * 1.10
            ) / price,
            step
        )

    if qty < min_qty:

        qty = min_qty

    return format_number(
        qty,
        step
    )


# ============================================================
# PRICE FORMAT
# ============================================================

def format_price(
    price,
    symbol_info
):

    (
        _,
        _,
        _,
        tick
    ) = get_symbol_rules(
        symbol_info
    )

    value = floor_to_step(
        price,
        tick
    )

    return format_number(
        value,
        tick
    )


# ============================================================
# ORDER
# ============================================================

def market_order(
    symbol,
    side,
    quantity
):

    return private_post_v1(
        "order",
        {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": quantity
        }
    )


# ============================================================
# SL / TP
# ============================================================

def set_position_sl_tp(
    position_id,
    symbol,
    sl_price,
    tp_price
):

    return private_post_v1(
        "positionSlTp",
        {
            "positionId": position_id,
            "symbol": symbol,
            "slPrice": sl_price,
            "tpPrice": tp_price,
            "workingType": "MARK_PRICE"
        }
    )


# ============================================================
# FIND POSITION ID
# ============================================================

def find_position(
    symbol,
    retries=5
):

    for _ in range(
        retries
    ):

        try:

            data = get_position_risk()

            if isinstance(
                data,
                list
            ):

                positions = data

            elif isinstance(
                data,
                dict
            ):

                positions = (
                    data.get(
                        "positions"
                    )
                    or data.get(
                        "data"
                    )
                    or data.get(
                        "result"
                    )
                    or []
                )

            else:

                positions = []

            for p in positions:

                if str(
                    p.get(
                        "symbol",
                        ""
                    )
                ).upper() != symbol:
                    continue

                try:

                    amount = float(
                        p.get(
                            "positionAmt",
                            0
                        )
                    )

                    if abs(amount) > 0:

                        return p

                except Exception:
                    pass

        except Exception:
            pass

        time.sleep(1)

    return None


# ============================================================
# ORDER BOOK SIGNAL
# ============================================================

def get_pressure(
    symbol
):

    data = get_depth(
        symbol
    )

    bids = data.get(
        "bids",
        []
    )

    asks = data.get(
        "asks",
        []
    )

    bid_volume = 0.0
    ask_volume = 0.0

    for row in bids[:10]:

        try:

            bid_volume += (
                float(row[0])
                * float(row[1])
            )

        except Exception:
            pass

    for row in asks[:10]:

        try:

            ask_volume += (
                float(row[0])
                * float(row[1])
            )

        except Exception:
            pass

    total = (
        bid_volume
        + ask_volume
    )

    if total <= 0:
        return None

    pressure = (
        bid_volume /
        total
    ) * 100

    return pressure


# ============================================================
# SIGNAL
# ============================================================

def get_signal(
    symbol
):

    try:

        price = get_price(
            symbol
        )

        pressure = get_pressure(
            symbol
        )

        if pressure is None:
            return None

        # BUY قوی
        if pressure >= 65:

            return {
                "symbol": symbol,
                "side": "BUY",
                "price": price,
                "pressure": pressure
            }

        # SELL قوی
        if pressure <= 35:

            return {
                "symbol": symbol,
                "side": "SELL",
                "price": price,
                "pressure": pressure
            }

    except Exception as e:

        print(
            f"⚠️ SIGNAL {symbol}: {e}"
        )

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 65)
    print("ATI FUTURES")
    print("⚡ REAL TRADING ENGINE")
    print("📡 TABDEAL FUTURES")
    print("=" * 65)

    telegram(
        "💓 ATI FUTURES\n"
        "⚡ REAL TRADING ENGINE\n"
        "📡 TABDEAL FUTURES\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"🔴 LIVE: {LIVE_TRADING}\n"
        f"🕐 {utc_now()}"
    )

    # --------------------------------------------------------
    # API KEYS
    # --------------------------------------------------------

    if not API_KEY or not API_SECRET:

        msg = (
            "❌ ATI FUTURES ERROR\n\n"
            "TABDIL_API_KEY یا "
            "TABDIL_API_SECRET موجود نیست."
        )

        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # AUTH
    # --------------------------------------------------------

    try:

        account = get_account()

        can_trade = account.get(
            "canTrade",
            account.get(
                "can_trade",
                False
            )
        )

        print(
            "✅ FUTURES AUTH SUCCESS"
        )

        print(
            f"🔓 canTrade={can_trade}"
        )

        if not can_trade:

            msg = (
                "❌ Futures account "
                "اجازه معامله ندارد.\n"
                "🔒 canTrade=False"
            )

            print(msg)
            telegram(msg)
            return

    except Exception as e:

        msg = (
            "❌ FUTURES AUTH ERROR\n\n"
            f"{e}"
        )

        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # BALANCE
    # --------------------------------------------------------

    try:

        balance = get_usdt_balance()

        print(
            f"💰 FUTURES USDT: "
            f"{balance:.8f}"
        )

    except Exception as e:

        print(
            f"⚠️ BALANCE ERROR: {e}"
        )

        balance = 0.0

    if balance <= 0:

        msg = (
            "❌ FUTURES USDT = 0\n\n"
            "حساب Futures توسط API "
            "موجودی قابل معامله ندارد."
        )

        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # OPEN POSITIONS
    # --------------------------------------------------------

    try:

        open_positions = (
            get_open_positions()
        )

        print(
            f"📌 OPEN POSITIONS: "
            f"{len(open_positions)}"
        )

        for p in open_positions[:10]:

            print(
                "•",
                p.get("symbol"),
                p.get("positionAmt")
            )

    except Exception as e:

        print(
            f"⚠️ POSITION ERROR: {e}"
        )

        open_positions = []

    # --------------------------------------------------------
    # EXCHANGE INFO
    # --------------------------------------------------------

    try:

        symbols = (
            get_futures_symbols()
        )

        print(
            f"📊 FUTURES MARKETS: "
            f"{len(symbols)}"
        )

    except Exception as e:

        msg = (
            "❌ EXCHANGE INFO ERROR\n\n"
            f"{e}"
        )

        print(msg)
        telegram(msg)
        return

    if not symbols:

        msg = (
            "❌ هیچ بازار Futures "
            "پیدا نشد."
        )

        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    print("\n🔎 SCANNING...\n")

    candidates = []

    for info in symbols[:SCAN_LIMIT]:

        symbol = str(
            info.get(
                "symbol",
                ""
            )
        ).upper()

        if not symbol:
            continue

        # پوزیشن باز را دوباره معامله نکن
        already_open = False

        for p in open_positions:

            psymbol = str(
                p.get(
                    "symbol",
                    ""
                )
            ).upper()

            if psymbol != symbol:
                continue

            try:

                amount = float(
                    p.get(
                        "positionAmt",
                        0
                    )
                )

                if abs(amount) > 0:
                    already_open = True

            except Exception:
                pass

        if already_open:
            continue

        signal = get_signal(
            symbol
        )

        if signal:

            signal["info"] = info

            candidates.append(
                signal
            )

            print(
                f"🎯 {symbol} | "
                f"{signal['side']} | "
                f"Pressure="
                f"{signal['pressure']:.2f}% | "
                f"Price="
                f"{signal['price']}"
            )

        time.sleep(
            0.05
        )

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x:
        abs(
            x["pressure"] - 50
        ),
        reverse=True
    )

    if not candidates:

        msg = (
            "📊 ATI FUTURES\n\n"
            f"Markets: "
            f"{min(len(symbols),SCAN_LIMIT)}\n"
            "❌ سیگنال قوی پیدا نشد.\n"
            f"💰 USDT: {balance:.4f}\n"
            f"🔴 LIVE: {LIVE_TRADING}\n"
            f"🕐 {utc_now()}"
        )

        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # REAL TRADE
    # --------------------------------------------------------

    trades_done = 0

    for signal in candidates:

        if (
            trades_done
            >= MAX_NEW_TRADES
        ):
            break

        symbol = signal[
            "symbol"
        ]

        side = signal[
            "side"
        ]

        entry_price = signal[
            "price"
        ]

        pressure = signal[
            "pressure"
        ]

        info = signal[
            "info"
        ]

        try:

            quantity = (
                calculate_quantity(
                    entry_price,
                    info
                )
            )

            # ------------------------------------------------
            # LEVERAGE
            # ------------------------------------------------

            print(
                f"\n⚙️ Setting "
                f"{LEVERAGE}x "
                f"for {symbol}"
            )

            if LIVE_TRADING:

                leverage_response = (
                    change_leverage(
                        symbol
                    )
                )

                print(
                    "✅ LEVERAGE OK"
                )

                print(
                    leverage_response
                )

            # ------------------------------------------------
            # REAL MARKET ORDER
            # ------------------------------------------------

            print("\n" + "=" * 65)

            print(
                f"🚨 REAL ORDER"
            )

            print(
                f"🪙 {symbol}"
            )

            print(
                f"📈 SIDE: {side}"
            )

            print(
                f"💰 ENTRY: "
                f"{entry_price}"
            )

            print(
                f"📦 QTY: "
                f"{quantity}"
            )

            print(
                f"📊 PRESSURE: "
                f"{pressure:.2f}%"
            )

            print(
                f"⚙️ LEVERAGE: "
                f"{LEVERAGE}x"
            )

            if not LIVE_TRADING:

                print(
                    "🟡 LIVE_TRADING=False"
                )

                print(
                    "🟡 ORDER NOT SENT"
                )

                return

            order = market_order(
                symbol,
                side,
                quantity
            )

            print(
                "✅ MARKET ORDER SENT"
            )

            print(order)

            # ------------------------------------------------
            # FIND REAL POSITION
            # ------------------------------------------------

            position = find_position(
                symbol
            )

            if not position:

                warning = (
                    "🚨 ORDER SENT BUT "
                    "POSITION NOT FOUND\n\n"
                    f"Symbol: {symbol}\n"
                    f"Order: {order}"
                )

                print(warning)
                telegram(warning)
                return

            position_id = position.get(
                "positionId",
                position.get(
                    "id"
                )
            )

            # اگر positionId عددی باشد
            try:

                if position_id is not None:

                    position_id = int(
                        position_id
                    )

            except Exception:
                pass

            # ------------------------------------------------
            # REAL ENTRY PRICE
            # ------------------------------------------------

            real_entry = (
                position.get(
                    "entryPrice"
                )
            )

            try:

                real_entry = float(
                    real_entry
                )

            except Exception:

                real_entry = (
                    entry_price
                )

            # ------------------------------------------------
            # SL / TP
            # ------------------------------------------------

            if side == "BUY":

                sl_raw = (
                    real_entry
                    * (
                        1
                        - SL_PERCENT
                        / 100
                    )
                )

                tp_raw = (
                    real_entry
                    * (
                        1
                        + TP_PERCENT
                        / 100
                    )
                )

            else:

                sl_raw = (
                    real_entry
                    * (
                        1
                        + SL_PERCENT
                        / 100
                    )
                )

                tp_raw = (
                    real_entry
                    * (
                        1
                        - TP_PERCENT
                        / 100
                    )
                )

            sl_price = format_price(
                sl_raw,
                info
            )

            tp_price = format_price(
                tp_raw,
                info
            )

            # ------------------------------------------------
            # REAL SL / TP
            # ------------------------------------------------

            if position_id is not None:

                try:

                    sltp = (
                        set_position_sl_tp(
                            position_id,
                            symbol,
                            sl_price,
                            tp_price
                        )
                    )

                    print(
                        "✅ REAL SL/TP SET"
                    )

                    print(
                        sltp
                    )

                except Exception as e:

                    critical = (
                        "🚨 WARNING\n"
                        "REAL POSITION OPENED "
                        "BUT SL/TP FAILED\n\n"
                        f"Symbol: {symbol}\n"
                        f"Entry: {real_entry}\n"
                        f"SL: {sl_price}\n"
                        f"TP: {tp_price}\n"
                        f"ERROR: {e}"
                    )

                    print(
                        critical
                    )

                    telegram(
                        critical
                    )

                    return

            # ------------------------------------------------
            # SUCCESS
            # ------------------------------------------------

            message = (
                "🚨 ATI FUTURES REAL TRADE\n\n"
                f"🪙 {symbol}\n"
                f"📈 {side}\n"
                f"💰 Entry: {real_entry}\n"
                f"📦 Qty: {quantity}\n"
                f"📊 Pressure: "
                f"{pressure:.2f}%\n"
                f"⚙️ Leverage: "
                f"{LEVERAGE}x\n"
                f"🛑 REAL SL: "
                f"{sl_price}\n"
                f"🎯 REAL TP: "
                f"{tp_price}\n"
                f"💵 Order: "
                f"{ORDER_USDT} USDT\n"
                f"🔴 LIVE: TRUE\n"
                f"🕐 {utc_now()}"
            )

            print(
                message
            )

            telegram(
                message
            )

            trades_done += 1

            break

        except Exception as e:

            error = (
                "❌ REAL TRADE ERROR\n\n"
                f"Symbol: {symbol}\n"
                f"Side: {side}\n"
                f"Error: {e}"
            )

            print(error)
            telegram(error)

    # --------------------------------------------------------
    # FINISH
    # --------------------------------------------------------

    print("\n" + "=" * 65)

    print(
        f"✅ ATI FINISHED"
    )

    print(
        f"REAL TRADES: "
        f"{trades_done}"
    )

    print("=" * 65)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        error = (
            "🚨 ATI FUTURES CRITICAL ERROR\n\n"
            f"{e}"
        )

        print(error)

        telegram(
            error
        )
