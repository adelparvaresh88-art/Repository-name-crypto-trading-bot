import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone

# ============================================================
# ATI FUTURES REAL TRADING
# TABDEAL FUTURES
# ============================================================

API_BASE = "https://api1.tabdeal.org"

# درست:
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

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

ORDER_USDT = float(os.getenv("ORDER_QTY", "2"))
LEVERAGE = int(os.getenv("LEVERAGE", "3"))

# برای امنیت، حداکثر تعداد معاملات در هر اجرای ربات
MAX_NEW_TRADES = int(os.getenv("MAX_NEW_TRADES", "1"))

# حد ضرر / سود
SL_PERCENT = 1.0
TP_PERCENT = 2.0

TIMEOUT = 15

session = requests.Session()

# ============================================================
# TELEGRAM
# ============================================================

TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")


def telegram(msg):
    if not TG_TOKEN or not TG_CHAT_ID:
        return

    try:
        url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
        requests.post(
            url,
            json={
                "chat_id": TG_CHAT_ID,
                "text": msg
            },
            timeout=15
        )
    except Exception:
        pass


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ============================================================
# SIGNATURE
# ============================================================

def sign_params(params):
    params = dict(params or {})

    params["timestamp"] = int(time.time() * 1000)
    params.setdefault("recvWindow", 10000)

    query = urlencode(params)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    return params


# ============================================================
# PUBLIC V1
# ============================================================

def public_get(endpoint, params=None):
    url = PUBLIC_V1 + endpoint

    r = session.get(
        url,
        params=params or {},
        timeout=TIMEOUT
    )

    if r.status_code != 200:
        raise Exception(
            f"HTTP {r.status_code}: {r.text[:500]}"
        )

    return r.json()


# ============================================================
# PRIVATE V3
# ============================================================

def private_get_v3(endpoint, params=None):
    if not API_KEY or not API_SECRET:
        raise Exception("API KEY/SECRET missing")

    params = sign_params(params)

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = PRIVATE_V3 + endpoint

    r = session.get(
        url,
        params=params,
        headers=headers,
        timeout=TIMEOUT
    )

    if r.status_code != 200:
        raise Exception(
            f"HTTP {r.status_code}: {r.text[:700]}"
        )

    return r.json()


# ============================================================
# PRIVATE V1
# ============================================================

def private_get_v1(endpoint, params=None):
    if not API_KEY or not API_SECRET:
        raise Exception("API KEY/SECRET missing")

    params = sign_params(params)

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = PRIVATE_V1 + endpoint

    r = session.get(
        url,
        params=params,
        headers=headers,
        timeout=TIMEOUT
    )

    if r.status_code != 200:
        raise Exception(
            f"HTTP {r.status_code}: {r.text[:700]}"
        )

    return r.json()


# ============================================================
# REAL WRITE POST
# ============================================================

def private_post_v1(endpoint, params=None):
    if not API_KEY or not API_SECRET:
        raise Exception("API KEY/SECRET missing")

    params = sign_params(params)

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    url = WRITE_V1 + endpoint

    r = session.post(
        url,
        params=params,
        headers=headers,
        timeout=TIMEOUT
    )

    if r.status_code not in (200, 201):
        raise Exception(
            f"ORDER HTTP {r.status_code}: {r.text[:1000]}"
        )

    return r.json()


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_exchange_info():

    # مهم:
    # /r/fapi/v1/exchangeInfo
    data = public_get("exchangeInfo")

    if isinstance(data, dict):
        symbols = data.get("symbols")

        if isinstance(symbols, list):
            return symbols

        if isinstance(data.get("data"), list):
            return data["data"]

        if isinstance(data.get("result"), list):
            return data["result"]

    if isinstance(data, list):
        return data

    raise Exception(
        "exchangeInfo format not recognized"
    )


# ============================================================
# SYMBOL FILTER
# ============================================================

def futures_symbols():

    all_symbols = get_exchange_info()

    result = []

    for s in all_symbols:

        if not isinstance(s, dict):
            continue

        symbol = str(s.get("symbol", "")).upper()

        if not symbol:
            continue

        status = str(s.get("status", "")).upper()

        if status and status not in (
            "TRADING",
            "ENABLED",
            "OPEN"
        ):
            continue

        quote = str(
            s.get("quoteAsset")
            or s.get("quote")
            or ""
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

        result.append(s)

    return result


# ============================================================
# PRICE
# ============================================================

def get_price(symbol):

    data = public_get(
        "ticker/price",
        {"symbol": symbol}
    )

    if isinstance(data, dict):

        for key in (
            "price",
            "lastPrice",
            "last",
            "close"
        ):
            if data.get(key) is not None:
                return float(data[key])

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

    # مهم:
    # /r/fapi/v3/account
    return private_get_v3("account")


# ============================================================
# BALANCE
# ============================================================

def get_usdt_balance():

    try:
        data = private_get_v3("balance")

        if isinstance(data, list):

            for item in data:

                asset = str(
                    item.get("asset", "")
                ).upper()

                if asset == "USDT":

                    return float(
                        item.get(
                            "availableBalance",
                            item.get("balance", 0)
                        )
                    )

    except Exception:
        pass

    try:

        account = get_account()

        if isinstance(account, dict):

            balances = account.get(
                "balances",
                []
            )

            for item in balances:

                if str(
                    item.get("asset", "")
                ).upper() == "USDT":

                    return float(
                        item.get(
                            "availableBalance",
                            item.get("free", 0)
                        )
                    )

    except Exception:
        pass

    return 0.0


# ============================================================
# OPEN POSITIONS
# ============================================================

def get_positions():

    # مهم:
    # /r/fapi/v3/positionRisk
    data = private_get_v3(
        "positionRisk"
    )

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "positions",
            "data",
            "result"
        ):

            if isinstance(data.get(key), list):
                return data[key]

    return []


def get_open_positions():

    positions = get_positions()

    result = []

    for p in positions:

        try:
            amt = float(
                p.get(
                    "positionAmt",
                    p.get("amount", 0)
                )
            )

            if abs(amt) > 0:
                result.append(p)

        except Exception:
            pass

    return result


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage(symbol):

    try:

        data = private_post_v1(
            "leverage",
            {
                "symbol": symbol,
                "leverage": LEVERAGE
            }
        )

        return data

    except Exception as e:

        # بعضی نسخه‌های API ممکن است
        # leverage را در endpoint دیگری بپذیرند.
        raise Exception(
            f"LEVERAGE ERROR {symbol}: {e}"
        )


# ============================================================
# PRECISION
# ============================================================

def symbol_rules(symbol_info):

    qty_step = 0.001
    min_qty = 0.001
    min_notional = 1.0
    price_tick = 0.000001

    filters = symbol_info.get(
        "filters",
        []
    )

    for f in filters:

        typ = str(
            f.get("filterType", "")
        )

        if typ in (
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

        elif typ == "MIN_NOTIONAL":

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

        elif typ == "PRICE_FILTER":

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


def floor_step(value, step):

    if step <= 0:
        return value

    import math

    return math.floor(
        value / step
    ) * step


# ============================================================
# ORDER QTY
# ============================================================

def calculate_qty(
    price,
    symbol_info
):

    (
        step,
        min_qty,
        min_notional,
        _
    ) = symbol_rules(
        symbol_info
    )

    # ORDER_USDT ارزش معامله است
    qty = ORDER_USDT / price

    qty = floor_step(
        qty,
        step
    )

    # اگر ارزش کمتر از حداقل بود
    if qty * price < min_notional:

        qty = floor_step(
            (min_notional * 1.10) / price,
            step
        )

    if qty < min_qty:
        qty = min_qty

    return qty


# ============================================================
# REAL MARKET ORDER
# ============================================================

def market_order(
    symbol,
    side,
    quantity
):

    params = {
        "symbol": symbol,
        "side": side,
        "type": "MARKET",
        "quantity": quantity
    }

    if not LIVE_TRADING:
        return {
            "dry_run": True,
            "symbol": symbol,
            "side": side,
            "quantity": quantity
        }

    return private_post_v1(
        "order",
        params
    )


# ============================================================
# SIMPLE PRICE ACTION SIGNAL
# ============================================================

def signal_for_symbol(
    symbol,
    price
):

    try:

        depth = get_depth(symbol)

        bids = depth.get(
            "bids",
            []
        )

        asks = depth.get(
            "asks",
            []
        )

        bid_volume = 0.0
        ask_volume = 0.0

        for row in bids[:10]:

            try:
                bid_volume += (
                    float(row[0]) *
                    float(row[1])
                )
            except Exception:
                pass

        for row in asks[:10]:

            try:
                ask_volume += (
                    float(row[0]) *
                    float(row[1])
                )
            except Exception:
                pass

        total = (
            bid_volume +
            ask_volume
        )

        if total <= 0:
            return None

        pressure = (
            bid_volume / total
        ) * 100

        # فقط فشار خیلی قوی خرید
        if pressure >= 65:

            return {
                "side": "BUY",
                "pressure": pressure,
                "price": price
            }

        # فروش فقط در صورت فشار بسیار قوی
        if pressure <= 35:

            return {
                "side": "SELL",
                "pressure": pressure,
                "price": price
            }

    except Exception:
        return None

    return None


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("ATI FUTURES REAL TRADING")
    print("TABDEAL FUTURES")
    print("=" * 60)

    telegram(
        "💓 ATI FUTURES\n"
        "⚡ REAL TRADING ENGINE\n"
        f"📡 TABDEAL FUTURES\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"🔴 LIVE: {LIVE_TRADING}\n"
        f"🕐 {now()}"
    )

    if not API_KEY or not API_SECRET:

        msg = (
            "❌ ATI FUTURES ERROR\n\n"
            "API KEY / SECRET پیدا نشد.\n"
            "Secrets باید TABDIL_API_KEY و "
            "TABDIL_API_SECRET باشند."
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

        print("✅ FUTURES AUTH SUCCESS")
        print(
            f"🔓 canTrade={can_trade}"
        )

        if not can_trade:

            msg = (
                "❌ FUTURES ACCOUNT CANNOT TRADE\n"
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
            f"💰 USDT AVAILABLE: {balance}"
        )

    except Exception as e:

        print(
            f"⚠️ Balance error: {e}"
        )

        balance = 0.0

    if balance <= 0:

        msg = (
            "⚠️ USDT AVAILABLE = 0\n\n"
            "برای Futures باید موجودی قابل "
            "معامله در حساب Futures داشته باشی."
        )

        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # OPEN POSITIONS
    # --------------------------------------------------------

    try:

        open_positions = get_open_positions()

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
            f"⚠️ Position check error: {e}"
        )

        open_positions = []

    # --------------------------------------------------------
    # EXCHANGE INFO
    # --------------------------------------------------------

    try:

        symbols = futures_symbols()

        print(
            f"📊 FUTURES SYMBOLS: "
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
            "❌ هیچ نماد Futures پیدا نشد."
        )

        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    print("\n🔎 SCANNING FUTURES...\n")

    candidates = []

    # تا 40 نماد
    for info in symbols[:40]:

        symbol = str(
            info.get("symbol", "")
        ).upper()

        if not symbol:
            continue

        try:

            price = get_price(
                symbol
            )

            signal = signal_for_symbol(
                symbol,
                price
            )

            if signal:

                signal["symbol"] = symbol
                signal["info"] = info

                candidates.append(
                    signal
                )

                print(
                    f"🎯 {symbol} "
                    f"{signal['side']} "
                    f"pressure="
                    f"{signal['pressure']:.1f}% "
                    f"price={price}"
                )

        except Exception as e:

            print(
                f"⚠️ {symbol}: {e}"
            )

        time.sleep(0.05)

    # --------------------------------------------------------
    # SORT
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x:
        abs(x["pressure"] - 50),
        reverse=True
    )

    if not candidates:

        msg = (
            "📊 ATI FUTURES SCAN\n\n"
            f"نماد بررسی‌شده: {min(len(symbols),40)}\n"
            "❌ سیگنال قوی پیدا نشد.\n"
            f"🔴 LIVE: {LIVE_TRADING}\n"
            f"🕐 {now()}"
        )

        print(msg)
        telegram(msg)
        return

    # --------------------------------------------------------
    # TRADE
    # --------------------------------------------------------

    trades_done = 0

    for signal in candidates:

        if trades_done >= MAX_NEW_TRADES:
            break

        symbol = signal["symbol"]
        side = signal["side"]
        price = signal["price"]
        pressure = signal["pressure"]

        # جلوگیری از معامله روی نمادی که پوزیشن باز دارد
        already_open = False

        for p in open_positions:

            if str(
                p.get("symbol", "")
            ).upper() == symbol:

                try:
                    if abs(
                        float(
                            p.get(
                                "positionAmt",
                                0
                            )
                        )
                    ) > 0:

                        already_open = True

                except Exception:
                    pass

        if already_open:

            print(
                f"⏭️ {symbol}: "
                "position already open"
            )

            continue

        try:

            # leverage
            if LIVE_TRADING:

                set_leverage(
                    symbol
                )

            quantity = calculate_qty(
                price,
                signal["info"]
            )

            # ------------------------------------------------
            # SL / TP
            # ------------------------------------------------

            if side == "BUY":

                sl = price * (
                    1 - SL_PERCENT / 100
                )

                tp = price * (
                    1 + TP_PERCENT / 100
                )

            else:

                sl = price * (
                    1 + SL_PERCENT / 100
                )

                tp = price * (
                    1 - TP_PERCENT / 100
                )

            print("\n" + "=" * 60)

            print(
                f"🎯 SIGNAL: {symbol}"
            )

            print(
                f"📈 SIDE: {side}"
            )

            print(
                f"💰 PRICE: {price}"
            )

            print(
                f"📊 PRESSURE: "
                f"{pressure:.2f}%"
            )

            print(
                f"📦 QTY: {quantity}"
            )

            print(
                f"🛑 SL: {sl}"
            )

            print(
                f"🎯 TP: {tp}"
            )

            print(
                f"🔴 REAL ORDER: "
                f"{LIVE_TRADING}"
            )

            # ------------------------------------------------
            # MARKET ORDER
            # ------------------------------------------------

            order = market_order(
                symbol,
                side,
                quantity
            )

            print(
                "✅ MARKET ORDER RESPONSE:"
            )

            print(order)

            telegram(
                "🚨 ATI FUTURES TRADE\n\n"
                f"🪙 {symbol}\n"
                f"📈 {side}\n"
                f"💰 Entry: {price}\n"
                f"📦 Qty: {quantity}\n"
                f"📊 Pressure: {pressure:.1f}%\n"
                f"🛑 SL: {sl}\n"
                f"🎯 TP: {tp}\n"
                f"⚙️ Leverage: {LEVERAGE}x\n"
                f"🔴 REAL: {LIVE_TRADING}\n"
                f"🕐 {now()}"
            )

            trades_done += 1

            # فعلاً فقط یک معامله
            break

        except Exception as e:

            error = (
                f"❌ TRADE ERROR {symbol}\n\n"
                f"{e}"
            )

            print(error)
            telegram(error)

    # --------------------------------------------------------
    # FINAL
    # --------------------------------------------------------

    print("\n" + "=" * 60)
    print(
        f"✅ ATI FINISHED | "
        f"TRADES={trades_done}"
    )
    print("=" * 60)


if __name__ == "__main__":

    try:
        main()

    except Exception as e:

        error = (
            "🚨 ATI FUTURES CRITICAL ERROR\n\n"
            f"{e}"
        )

        print(error)
        telegram(error)
