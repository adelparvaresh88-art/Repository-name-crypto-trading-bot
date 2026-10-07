import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN

# ============================================================
# ATI FUTURES - TABDEAL
# Direct REST API
# No tabdeal.future import
# ============================================================

VERSION = "ATI-FUTURES-V1.0"

BASE_URL = "https://api1.tabdeal.org"

API_KEY = (
    os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_API_KEY")
    or ""
).strip()

API_SECRET = (
    os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDEAL_API_SECRET")
    or ""
).strip()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

LIVE_TRADING = os.getenv("LIVE_TRADING", "false").lower() == "true"

SYMBOL = os.getenv("FUTURES_SYMBOL", "BTCUSDT").upper()
LEVERAGE = int(os.getenv("FUTURES_LEVERAGE", "3"))

ORDER_USDT = Decimal(os.getenv("ORDER_QTY", "2"))

TP_PERCENT = Decimal(os.getenv("TP_PERCENT", "2.0"))
SL_PERCENT = Decimal(os.getenv("SL_PERCENT", "1.0"))

TIMEOUT = 20


# ============================================================
# TELEGRAM
# ============================================================

def telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print(message)
        return

    try:
        url = (
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        )

        requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
            },
            timeout=TIMEOUT,
        )
    except Exception as e:
        print("Telegram error:", e)


# ============================================================
# SIGNATURE
# ============================================================

def signed_request(method, path, params=None):
    if params is None:
        params = {}

    params = dict(params)

    # Tabdeal requires timestamp for signed requests.
    params["timestamp"] = int(time.time() * 1000)

    query = urlencode(params)

    signature = hmac.new(
        API_SECRET.encode(),
        query.encode(),
        hashlib.sha256,
    ).hexdigest()

    query += "&signature=" + signature

    url = BASE_URL + path + "?" + query

    headers = {
        "X-MBX-APIKEY": API_KEY
    }

    response = requests.request(
        method,
        url,
        headers=headers,
        timeout=TIMEOUT,
    )

    try:
        data = response.json()
    except Exception:
        data = response.text

    if response.status_code >= 400:
        raise RuntimeError(
            f"HTTP {response.status_code}: {data}"
        )

    return data


def public_request(path, params=None):
    response = requests.get(
        BASE_URL + path,
        params=params or {},
        timeout=TIMEOUT,
    )

    try:
        data = response.json()
    except Exception:
        data = response.text

    if response.status_code >= 400:
        raise RuntimeError(
            f"HTTP {response.status_code}: {data}"
        )

    return data


# ============================================================
# FUTURES PUBLIC API
# ============================================================

def futures_ping():
    return public_request("/fapi/v1/ping")


def futures_time():
    return public_request("/fapi/v1/time")


def exchange_info():
    return public_request(
        "/fapi/v1/exchangeInfo",
        {"symbol": SYMBOL},
    )


def get_klines(interval="5m", limit=100):
    return public_request(
        "/fapi/v1/klines",
        {
            "symbol": SYMBOL,
            "interval": interval,
            "limit": limit,
        },
    )


# ============================================================
# ACCOUNT
# ============================================================

def futures_balance():
    return signed_request(
        "GET",
        "/fapi/v3/balance",
    )


def futures_account():
    return signed_request(
        "GET",
        "/fapi/v3/account",
    )


def get_position():
    return signed_request(
        "GET",
        "/fapi/v3/positionRisk",
        {"symbol": SYMBOL},
    )


# ============================================================
# LEVERAGE
# ============================================================

def change_leverage():
    return signed_request(
        "POST",
        "/fapi/v1/leverage",
        {
            "symbol": SYMBOL,
            "leverage": LEVERAGE,
        },
    )


# ============================================================
# PRICE
# ============================================================

def get_price():
    data = public_request(
        "/fapi/v1/ticker/price",
        {"symbol": SYMBOL},
    )

    return Decimal(str(data["price"]))


# ============================================================
# QUANTITY
# ============================================================

def get_quantity_step():
    data = exchange_info()

    symbols = data.get("symbols", [])

    if not symbols:
        return Decimal("0.001")

    item = symbols[0]

    for f in item.get("filters", []):
        if f.get("filterType") in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):
            step = f.get("stepSize")
            if step:
                return Decimal(str(step))

    return Decimal("0.001")


def calculate_quantity(price):
    if price <= 0:
        raise RuntimeError("Invalid price")

    quantity = ORDER_USDT / price

    step = get_quantity_step()

    quantity = (
        quantity / step
    ).to_integral_value(
        rounding=ROUND_DOWN
    ) * step

    return quantity


# ============================================================
# ORDER
# ============================================================

def market_order(side, quantity, reduce_only=False):
    params = {
        "symbol": SYMBOL,
        "side": side,
        "type": "MARKET",
        "quantity": str(quantity),
    }

    if reduce_only:
        params["reduceOnly"] = "true"

    return signed_request(
        "POST",
        "/fapi/v1/order",
        params,
    )


# ============================================================
# POSITION SL / TP
# ============================================================

def set_position_sl_tp(
    position_id,
    sl_price=None,
    tp_price=None,
):
    params = {
        "positionId": position_id,
        "symbol": SYMBOL,
    }

    if sl_price is not None:
        params["slPrice"] = str(sl_price)

    if tp_price is not None:
        params["tpPrice"] = str(tp_price)

    return signed_request(
        "POST",
        "/fapi/v1/positionSlTp",
        params,
    )


# ============================================================
# SIGNAL
# ============================================================

def make_signal():
    candles = get_klines("5m", 60)

    if not candles or len(candles) < 10:
        return None

    # Last candle may still be open.
    closed = candles[:-1]

    previous = closed[-2]
    current = closed[-1]

    prev_open = Decimal(str(previous[1]))
    prev_high = Decimal(str(previous[2]))
    prev_low = Decimal(str(previous[3]))
    prev_close = Decimal(str(previous[4]))

    cur_open = Decimal(str(current[1]))
    cur_high = Decimal(str(current[2]))
    cur_low = Decimal(str(current[3]))
    cur_close = Decimal(str(current[4]))

    # Simple price-action confirmation:
    # bullish breakout of previous candle high
    if cur_close > prev_high and cur_close > cur_open:
        return "BUY"

    # bearish breakout of previous candle low
    if cur_close < prev_low and cur_close < cur_open:
        return "SELL"

    return None


# ============================================================
# POSITION CHECK
# ============================================================

def active_position():
    try:
        data = get_position()

        if isinstance(data, dict):
            data = [data]

        for p in data:
            if p.get("symbol") != SYMBOL:
                continue

            qty = Decimal(
                str(
                    p.get(
                        "positionAmt",
                        p.get("quantity", "0"),
                    )
                )
            )

            if qty != 0:
                return p

        return None

    except Exception as e:
        print("Position check error:", e)
        return None


# ============================================================
# STARTUP
# ============================================================

def startup():

    print("=" * 60)
    print(VERSION)
    print("TABDEAL FUTURES")
    print("=" * 60)

    telegram(
        f"💓 ATI FUTURES ALIVE\n"
        f"⚡ {VERSION}\n"
        f"📡 TABDEAL FUTURES\n"
        f"📊 {SYMBOL}\n"
        f"⚙️ LEVERAGE: {LEVERAGE}x\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"🎯 TP: +{TP_PERCENT}%\n"
        f"🛑 SL: -{SL_PERCENT}%\n"
        f"🔒 LIVE: {LIVE_TRADING}"
    )

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDIL_API_KEY / TABDIL_API_SECRET missing"
        )

    futures_ping()

    print("✅ FUTURES PING OK")

    server_time = futures_time()

    print("🕐 SERVER:", server_time)

    # Authentication test
    balance = futures_balance()

    print("✅ AUTH SUCCESS")

    usdt_balance = None

    if isinstance(balance, list):
        for asset in balance:
            if asset.get("asset") == "USDT":
                usdt_balance = asset.get(
                    "availableBalance",
                    asset.get("balance"),
                )
                break

    print("💰 USDT:", usdt_balance)

    try:
        lev = change_leverage()
        print("⚙️ LEVERAGE SET:", lev)
    except Exception as e:
        print("⚠️ LEVERAGE:", e)


# ============================================================
# MAIN
# ============================================================

def main():

    startup()

    position = active_position()

    if position:
        telegram(
            f"📌 ATI FUTURES POSITION\n"
            f"Symbol: {SYMBOL}\n"
            f"Position: {position}"
        )

        print("Existing position detected.")
        return

    signal = make_signal()

    price = get_price()

    print("💵 PRICE:", price)
    print("📊 SIGNAL:", signal)

    if not signal:
        telegram(
            f"📊 ATI FUTURES SCAN\n"
            f"{SYMBOL}: NO SIGNAL\n"
            f"💵 Price: {price}"
        )
        return

    quantity = calculate_quantity(price)

    if quantity <= 0:
        raise RuntimeError(
            f"Calculated quantity invalid: {quantity}"
        )

    telegram(
        f"🚨 FUTURES SIGNAL\n"
        f"📊 {SYMBOL}\n"
        f"➡️ {signal}\n"
        f"💵 Entry: {price}\n"
        f"📦 Qty: {quantity}\n"
        f"⚙️ Leverage: {LEVERAGE}x\n"
        f"🔒 LIVE: {LIVE_TRADING}"
    )

    # Safety:
    # First run does NOT place a real order unless
    # LIVE_TRADING=true.
    if not LIVE_TRADING:
        print("🔒 LIVE_TRADING=false")
        print("🚫 REAL ORDER NOT SENT")

        telegram(
            "🔒 TEST MODE\n"
            "🚫 سفارش واقعی ارسال نشد."
        )

        return

    side = "BUY" if signal == "BUY" else "SELL"

    order = market_order(
        side,
        quantity,
        reduce_only=False,
    )

    print("✅ ORDER:", order)

    telegram(
        f"✅ FUTURES ORDER SENT\n"
        f"📊 {SYMBOL}\n"
        f"➡️ {side}\n"
        f"💵 Price: {price}\n"
        f"📦 Qty: {quantity}"
    )

    # Give exchange time to create position.
    time.sleep(2)

    pos = active_position()

    if not pos:
        telegram(
            "⚠️ سفارش ارسال شد اما پوزیشن هنوز "
            "از API قابل مشاهده نیست."
        )
        return

    position_id = pos.get("positionId")

    if position_id is None:
        telegram(
            "⚠️ positionId پیدا نشد؛ "
            "SL/TP تنظیم نشد."
        )
        return

    if signal == "BUY":
        sl = price * (
            Decimal("1")
            - SL_PERCENT / Decimal("100")
        )

        tp = price * (
            Decimal("1")
            + TP_PERCENT / Decimal("100")
        )

    else:
        sl = price * (
            Decimal("1")
            + SL_PERCENT / Decimal("100")
        )

        tp = price * (
            Decimal("1")
            - TP_PERCENT / Decimal("100")
        )

    try:
        result = set_position_sl_tp(
            position_id,
            sl_price=sl,
            tp_price=tp,
        )

        print("✅ SL/TP:", result)

        telegram(
            f"🛡️ SL/TP SET\n"
            f"🛑 SL: {sl}\n"
            f"🎯 TP: {tp}"
        )

    except Exception as e:
        print("SL/TP ERROR:", e)

        telegram(
            f"🚨 SL/TP ERROR\n"
            f"{e}"
        )


if __name__ == "__main__":
    try:
        main()

    except Exception as e:

        print("❌ ATI FUTURES ERROR")
        print(e)

        telegram(
            f"❌ ATI FUTURES ERROR\n\n"
            f"{e}"
        )

        raise
