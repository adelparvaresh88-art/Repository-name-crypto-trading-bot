import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from decimal import Decimal, ROUND_DOWN


# =========================================================
# ATI FUTURES REAL BOT
# Direct REST API - NO tabdeal.future
# =========================================================

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


# =========================================================
# TELEGRAM
# =========================================================

def telegram(text):

    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secrets not configured.")
        return

    try:

        url = (
            f"https://api.telegram.org/"
            f"bot{TELEGRAM_TOKEN}/sendMessage"
        )

        r = session.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": text,
            },
            timeout=15,
        )

        print(
            "Telegram:",
            r.status_code
        )

    except Exception as e:

        print(
            "Telegram ERROR:",
            repr(e)
        )


# =========================================================
# PUBLIC REQUEST
# =========================================================

def public_get(path, params=None):

    url = BASE_URL + path

    r = session.get(
        url,
        params=params or {},
        timeout=20,
    )

    print(
        "PUBLIC",
        r.status_code,
        r.url
    )

    if r.status_code >= 400:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:1000]}"
        )

    return r.json()


# =========================================================
# SIGNED REQUEST
# =========================================================

def signed_request(
    method,
    path,
    params=None,
):

    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDIL_API_KEY / TABDIL_API_SECRET "
            "وجود ندارد."
        )

    data = dict(params or {})

    # timestamp
    data["timestamp"] = int(
        time.time() * 1000
    )

    data["recvWindow"] = RECV_WINDOW

    query = urlencode(
        data,
        doseq=True
    )

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
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
            timeout=20,
        )

    elif method == "POST":

        r = session.post(
            url,
            data=data,
            headers=headers,
            timeout=20,
        )

    elif method == "DELETE":

        r = session.delete(
            url,
            params=data,
            headers=headers,
            timeout=20,
        )

    else:

        raise RuntimeError(
            f"Unsupported method: {method}"
        )

    print(
        "SIGNED",
        method,
        r.status_code,
        path
    )

    if r.status_code >= 400:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:1500]}"
        )

    try:
        return r.json()

    except Exception:
        return {
            "raw": r.text
        }


# =========================================================
# FUTURES PING
# =========================================================

def futures_ping():

    return public_get(
        "/fapi/v1/ping"
    )


# =========================================================
# SERVER TIME
# =========================================================

def server_time():

    return public_get(
        "/fapi/v1/time"
    )


# =========================================================
# EXCHANGE INFO
# =========================================================

def exchange_info():

    return public_get(
        "/fapi/v1/exchangeInfo",
        {
            "symbol": SYMBOL
        }
    )


# =========================================================
# KLINES
# =========================================================

def get_klines():

    data = public_get(
        "/fapi/v1/klines",
        {
            "symbol": SYMBOL,
            "interval": INTERVAL,
            "limit": 100,
        }
    )

    if not isinstance(data, list):
        raise RuntimeError(
            "Kline response invalid."
        )

    if len(data) < 30:
        raise RuntimeError(
            "Kline data insufficient."
        )

    candles = []

    for row in data:

        candles.append(
            {
                "time": int(row[0]),
                "open": Decimal(str(row[1])),
                "high": Decimal(str(row[2])),
                "low": Decimal(str(row[3])),
                "close": Decimal(str(row[4])),
                "volume": Decimal(str(row[5])),
            }
        )

    return candles


# =========================================================
# POSITION
# =========================================================

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
        "POSITION:",
        data
    )

    if isinstance(data, list):

        for p in data:

            for key in (
                "positionAmt",
                "quantity",
                "qty",
            ):

                if key in p:

                    try:

                        if Decimal(
                            str(p[key])
                        ) != 0:

                            return True

                    except Exception:
                        pass

    if isinstance(data, dict):

        for key in (
            "positionAmt",
            "quantity",
            "qty",
        ):

            if key in data:

                try:

                    return (
                        Decimal(
                            str(data[key])
                        ) != 0
                    )

                except Exception:
                    pass

    return False


# =========================================================
# LEVERAGE
# =========================================================

def change_leverage():

    result = signed_request(
        "POST",
        "/fapi/v1/leverage",
        {
            "symbol": SYMBOL,
            "leverage": LEVERAGE,
        }
    )

    print(
        "LEVERAGE RESULT:",
        result
    )

    return result


# =========================================================
# SIGNAL
# =========================================================

def signal(candles):

    # آخرین کندل ممکن است هنوز باز باشد.
    # بنابراین آن را حذف می‌کنیم.
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

    # -----------------------------
    # LONG
    # -----------------------------

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

    # -----------------------------
    # SHORT
    # -----------------------------

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


# =========================================================
# QUANTITY
# =========================================================

def get_quantity(price):

    # ORDER_USDT = margin
    # leverage = notional multiplier

    notional = (
        ORDER_USDT *
        Decimal(LEVERAGE)
    )

    quantity = (
        notional / price
    )

    # محافظه‌کارانه 6 رقم اعشار
    quantity = quantity.quantize(
        Decimal("0.000001"),
        rounding=ROUND_DOWN,
    )

    if quantity <= 0:
        raise RuntimeError(
            "Calculated quantity is zero."
        )

    return quantity


# =========================================================
# MARKET ORDER
# =========================================================

def market_order(side, quantity):

    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": SYMBOL,
            "side": side,
            "type": "MARKET",
            "quantity": str(quantity),
        }
    )


# =========================================================
# SL / TP
# =========================================================

def set_sl_tp():

    positions = get_positions()

    print(
        "POSITION AFTER ENTRY:",
        positions
    )

    if not isinstance(
        positions,
        list
    ):
        print(
            "Could not parse positions."
        )
        return

    for p in positions:

        try:

            position_id = int(
                p.get(
                    "positionId"
                )
            )

        except Exception:

            continue

        try:

            qty = Decimal(
                str(
                    p.get(
                        "positionAmt",
                        p.get(
                            "quantity",
                            "0"
                        )
                    )
                )
            )

        except Exception:

            qty = Decimal("0")

        if qty == 0:
            continue

        entry = Decimal(
            str(
                p.get(
                    "entryPrice",
                    p.get(
                        "avgPrice",
                        "0"
                    )
                )
            )
        )

        if entry <= 0:
            continue

        is_short = qty < 0

        if is_short:

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

        # برای BTC
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
                "tpPrice": str(tp),
            }
        )

        print(
            "SL/TP RESULT:",
            result
        )

        telegram(
            "🛡 ATI FUTURES SL/TP\n\n"
            f"SYMBOL: {SYMBOL}\n"
            f"ENTRY: {entry}\n"
            f"TP: {tp}\n"
            f"SL: {sl}"
        )


# =========================================================
# MAIN
# =========================================================

def main():

    print("=" * 60)
    print("ATI FUTURES DIRECT REST")
    print("=" * 60)

    telegram(
        "💓 ATI FUTURES ALIVE\n\n"
        f"SYMBOL: {SYMBOL}\n"
        f"INTERVAL: {INTERVAL}\n"
        f"LEVERAGE: {LEVERAGE}X\n"
        f"ORDER MARGIN: {ORDER_USDT} USDT\n"
        f"TP: +{TP_PERCENT}%\n"
        f"SL: -{SL_PERCENT}%\n"
        f"LIVE: {LIVE_TRADING}"
    )

    # -----------------------------------------------------
    # CONNECTIVITY
    # -----------------------------------------------------

    print(
        "PING:",
        futures_ping()
    )

    print(
        "SERVER TIME:",
        server_time()
    )

    # -----------------------------------------------------
    # EXCHANGE INFO
    # -----------------------------------------------------

    info = exchange_info()

    print(
        "EXCHANGE INFO:",
        info
    )

    # -----------------------------------------------------
    # API AUTH TEST
    # -----------------------------------------------------

    positions = get_positions()

    print(
        "AUTH SUCCESS"
    )

    print(
        "POSITIONS:",
        positions
    )

    # -----------------------------------------------------
    # EXISTING POSITION
    # -----------------------------------------------------

    if has_open_position():

        print(
            "OPEN POSITION EXISTS."
        )

        telegram(
            "⏸ ATI FUTURES\n\n"
            f"{SYMBOL}\n"
            "پوزیشن باز وجود دارد.\n"
            "ورود جدید انجام نشد."
        )

        return

    # -----------------------------------------------------
    # LEVERAGE
    # -----------------------------------------------------

    if LIVE_TRADING:

        change_leverage()

    # -----------------------------------------------------
    # MARKET DATA
    # -----------------------------------------------------

    candles = get_klines()

    price = candles[-2]["close"]

    print(
        "CLOSED PRICE:",
        price
    )

    # -----------------------------------------------------
    # SIGNAL
    # -----------------------------------------------------

    sig = signal(candles)

    print(
        "SIGNAL:",
        sig
    )

    if not sig:

        telegram(
            "📊 ATI FUTURES\n\n"
            f"{SYMBOL}\n"
            f"PRICE: {price}\n\n"
            "⏳ سیگنال معتبر وجود ندارد.\n"
            "❌ معامله انجام نشد."
        )

        return

    # -----------------------------------------------------
    # QUANTITY
    # -----------------------------------------------------

    quantity = get_quantity(
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

    # -----------------------------------------------------
    # PAPER MODE
    # -----------------------------------------------------

    if not LIVE_TRADING:

        telegram(
            "🧪 ATI FUTURES PAPER\n\n"
            f"SYMBOL: {SYMBOL}\n"
            f"SIGNAL: {sig}\n"
            f"SIDE: {side}\n"
            f"PRICE: {price}\n"
            f"QTY: {quantity}\n"
            f"LEVERAGE: {LEVERAGE}X\n"
            "🔒 LIVE_TRADING=false\n"
            "❌ سفارش واقعی ارسال نشد."
        )

        return

    # -----------------------------------------------------
    # REAL ORDER
    # -----------------------------------------------------

    telegram(
        "🚨 ATI FUTURES REAL ENTRY\n\n"
        f"SYMBOL: {SYMBOL}\n"
        f"SIDE: {side}\n"
        f"PRICE: {price}\n"
        f"QTY: {quantity}\n"
        f"LEVERAGE: {LEVERAGE}X\n"
        "🔴 سفارش واقعی در حال ارسال..."
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
        "✅ ATI FUTURES REAL ORDER\n\n"
        f"SYMBOL: {SYMBOL}\n"
        f"SIDE: {side}\n"
        f"QTY: {quantity}\n"
        f"LEVERAGE: {LEVERAGE}X\n"
        f"ORDER: {order}"
    )

    # -----------------------------------------------------
    # WAIT FOR POSITION
    # -----------------------------------------------------

    time.sleep(2)

    # -----------------------------------------------------
    # SL / TP
    # -----------------------------------------------------

    set_sl_tp()

    print(
        "ATI FUTURES FINISHED"
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
            "❌ ATI FUTURES ERROR\n\n"
            f"{repr(e)}"
        )

        raise

این نسخه هیچ import از "tabdeal" ندارد و امضای درخواست را مطابق الگویی که در کد رسمی Tabdeal دیده می‌شود انجام می‌دهد.

"main.yml"

این فایل را فقط در:

".github/workflows/main.yml"

قرار بده:

:::writing{variant="document" id="41857" title="ATI Futures — main.yml"}

name: ATI FUTURES REAL

on:
  workflow_dispatch:

  schedule:
    - cron: "*/5 * * * *"

permissions:
  contents: read

concurrency:
  group: ati-futures-real
  cancel-in-progress: false

jobs:

  run-bot:

    runs-on: ubuntu-latest

    timeout-minutes: 4

    steps:

      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install requests

      - name: Run ATI Futures
        env:

          TABDIL_API_KEY: ${{ secrets.TABDIL_API_KEY }}
          TABDIL_API_SECRET: ${{ secrets.TABDIL_API_SECRET }}

          TABDEAL_API_KEY: ${{ secrets.TABDEAL_API_KEY }}
          TABDEAL_API_SECRET: ${{ secrets.TABDEAL_API_SECRET }}

          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}

          LIVE_TRADING: ${{ secrets.LIVE_TRADING }}

          FUTURES_SYMBOL: ${{ secrets.FUTURES_SYMBOL }}
          FUTURES_INTERVAL: ${{ secrets.FUTURES_INTERVAL }}

          FUTURES_LEVERAGE: ${{ secrets.FUTURES_LEVERAGE }}
          FUTURES_ORDER_USDT: ${{ secrets.FUTURES_ORDER_USDT }}

          TP_PERCENT: ${{ secrets.TP_PERCENT }}
          SL_PERCENT: ${{ secrets.SL_PERCENT }}

        run: |
          python main.py

Secrets

این‌ها را در GitHub بگذار:

TABDIL_API_KEY
TABDIL_API_SECRET

TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID

LIVE_TRADING
FUTURES_SYMBOL
FUTURES_INTERVAL
FUTURES_LEVERAGE
FUTURES_ORDER_USDT
TP_PERCENT
SL_PERCENT

برای شروع:

LIVE_TRADING=true
FUTURES_SYMBOL=BTCUSDT
FUTURES_INTERVAL=5m
FUTURES_LEVERAGE=3
FUTURES_ORDER_USDT=2
TP_PERCENT=2
SL_PERCENT=1

نکته: کد رسمی Tabdeal تأیید می‌کند که مسیر Futures با "/fapi/v1/..." است و سفارش واقعی با "POST /fapi/v1/order" انجام می‌شود؛ همچنین endpoint تغییر اهرم و SL/TP هم همین ساختار را دارند.

فعلاً هیچ "pip install tabdeal-python" و هیچ "from tabdeal.future import Future" لازم نیست. این دقیقاً برای رفع خطایی است که الان گرفتی.
