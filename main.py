import os
import json
import time
import math
import hmac
import hashlib
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# ATI FUTURES V11
# REAL TABDEAL FUTURES API
# 5M KLINES
# ICHIMOKU 9 / 26 / 52
# NO EMA
# ============================================================

BASE_URL = os.getenv(
    "BASE_URL",
    "https://api1.tabdeal.org"
).rstrip("/")

ORDER_USDT = float(
    os.getenv("ORDER_USDT", "2")
)

LEVERAGE = int(
    os.getenv("LEVERAGE", "3")
)

REAL_TRADING = (
    os.getenv(
        "REAL_TRADING",
        "false"
    ).lower() == "true"
)

TP_PCT = float(
    os.getenv("TP_PCT", "0.02")
)

SL_PCT = float(
    os.getenv("SL_PCT", "0.01")
)

SCAN_UNIVERSE = int(
    os.getenv("SCAN_UNIVERSE", "75")
)

MIN_SCORE = int(
    os.getenv("MIN_SCORE", "6")
)

REQUEST_TIMEOUT = int(
    os.getenv("REQUEST_TIMEOUT", "10")
)

MAX_WORKERS = int(
    os.getenv("MAX_WORKERS", "15")
)

RECV_WINDOW = int(
    os.getenv("RECV_WINDOW", "5000")
)

KLINE_LIMIT = int(
    os.getenv("KLINE_LIMIT", "100")
)

STATE_FILE = "ati_futures_state.json"


# ============================================================
# API KEYS
# ============================================================

API_KEY = (
    os.getenv("TABDEAL_API_KEY")
    or os.getenv("TABDIL_API_KEY")
    or os.getenv("TABDEAL_KEY")
    or os.getenv("TABDIL_KEY")
    or ""
)

API_SECRET = (
    os.getenv("TABDEAL_API_SECRET")
    or os.getenv("TABDIL_API_SECRET")
    or os.getenv("TABDEAL_SECRET")
    or os.getenv("TABDIL_SECRET")
    or ""
)


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


# ============================================================
# SESSION
# ============================================================

session = requests.Session()

session.headers.update({
    "User-Agent": "ATI-Futures-V11",
    "Accept": "application/json",
})


# ============================================================
# TELEGRAM
# ============================================================

def telegram(text):

    if not TG_TOKEN or not TG_CHAT_ID:
        return

    try:

        url = (
            "https://api.telegram.org/"
            f"bot{TG_TOKEN}/sendMessage"
        )

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


# ============================================================
# PUBLIC REQUEST
# ============================================================

def public_get(path, params=None):

    url = BASE_URL + path

    r = session.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT,
    )

    if r.status_code >= 400:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:250]}"
        )

    try:

        return r.json()

    except Exception:

        raise RuntimeError(
            f"INVALID JSON: {r.text[:250]}"
        )


# ============================================================
# SIGNED REQUEST
# ============================================================

def signed_request(
    method,
    path,
    params=None
):

    if not API_KEY or not API_SECRET:

        raise RuntimeError(
            "API KEY/SECRET missing"
        )

    data = dict(params or {})

    data["timestamp"] = int(
        time.time() * 1000
    )

    data["recvWindow"] = RECV_WINDOW

    # IMPORTANT:
    # Keep insertion order exactly.
    query = "&".join(
        f"{k}={data[k]}"
        for k in data
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

        r = session.get(
            url,
            params=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    elif method.upper() == "POST":

        r = session.post(
            url,
            data=data,
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )

    else:

        raise RuntimeError(
            f"Unsupported HTTP method: {method}"
        )

    if r.status_code >= 400:

        raise RuntimeError(
            f"HTTP {r.status_code}: "
            f"{r.text[:500]}"
        )

    try:

        return r.json()

    except Exception:

        raise RuntimeError(
            f"INVALID JSON: {r.text[:500]}"
        )


# ============================================================
# EXCHANGE INFO
# ============================================================

def get_markets():

    # V11 FIX:
    # Tabdeal uses /r/api/v1/
    # NOT /r/fapi/v1/

    data = public_get(
        "/r/api/v1/exchangeInfo"
    )

    symbols = data.get(
        "symbols",
        []
    )

    if not isinstance(symbols, list):

        raise RuntimeError(
            "exchangeInfo symbols is not a list"
        )

    markets = []

    for s in symbols:

        symbol = str(
            s.get("symbol", "")
        ).upper()

        status = str(
            s.get("status", "")
        ).upper()

        quote = str(
            s.get("quoteAsset", "")
        ).upper()

        contract = str(
            s.get(
                "contractType",
                ""
            )
        ).upper()

        # Futures USDT markets
        if not symbol:
            continue

        if quote != "USDT":
            continue

        if status not in (
            "",
            "TRADING",
            "ACTIVE",
        ):
            continue

        markets.append(s)

    markets.sort(
        key=lambda x:
        x.get("symbol", "")
    )

    return markets[:SCAN_UNIVERSE]


# ============================================================
# KLINES
# ============================================================

def parse_klines(data):

    candles = []

    if not isinstance(data, list):
        return candles

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

    return candles


def fetch_5m_klines(symbol):

    errors = []

    # --------------------------------------------------------
    # METHOD 1
    # Official Tabdeal read API
    # --------------------------------------------------------

    try:

        data = public_get(
            "/r/api/v1/klines",
            {
                "symbol": symbol,
                "interval": "5m",
                "limit": KLINE_LIMIT,
            },
        )

        candles = parse_klines(data)

        if candles:

            return candles, "r/api/v1/klines"

        errors.append(
            "KLINES_EMPTY"
        )

    except Exception as e:

        errors.append(
            str(e)[:180]
        )

    # --------------------------------------------------------
    # METHOD 2
    # Some deployments may expose the
    # endpoint under /api/v1/
    # --------------------------------------------------------

    try:

        data = public_get(
            "/api/v1/klines",
            {
                "symbol": symbol,
                "interval": "5m",
                "limit": KLINE_LIMIT,
            },
        )

        candles = parse_klines(data)

        if candles:

            return candles, "api/v1/klines"

        errors.append(
            "API_KLINES_EMPTY"
        )

    except Exception as e:

        errors.append(
            str(e)[:180]
        )

    raise RuntimeError(
        " | ".join(errors)
    )


# ============================================================
# REMOVE OPEN CANDLE
# ============================================================

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
        c for c in candles
        if c["time"] < current_bucket
    ]


# ============================================================
# STATE
# ============================================================

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
        ) as f:

            return json.load(f)

    except Exception:

        return {}


def save_state(state):

    tmp = STATE_FILE + ".tmp"

    with open(
        tmp,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
        )

    os.replace(
        tmp,
        STATE_FILE,
    )


# ============================================================
# SYMBOL RULES
# ============================================================

def symbol_rules(info):

    quantity_step = 0.0
    min_qty = 0.0
    tick_size = 0.0

    for f in info.get(
        "filters",
        []
    ):

        typ = str(
            f.get(
                "filterType",
                ""
            )
        )

        if typ in (
            "LOT_SIZE",
            "MARKET_LOT_SIZE",
        ):

            try:

                quantity_step = float(
                    f.get(
                        "stepSize",
                        0
                    )
                )

            except Exception:
                pass

            try:

                min_qty = float(
                    f.get(
                        "minQty",
                        0
                    )
                )

            except Exception:
                pass

        elif typ == "PRICE_FILTER":

            try:

                tick_size = float(
                    f.get(
                        "tickSize",
                        0
                    )
                )

            except Exception:
                pass

    return (
        quantity_step,
        min_qty,
        tick_size,
    )


def floor_step(
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


def round_tick(
    value,
    tick
):

    if tick <= 0:
        return value

    decimals = 12

    try:

        decimals = max(
            0,
            int(
                -math.floor(
                    math.log10(tick)
                )
            ) + 2
        )

    except Exception:
        pass

    return round(
        math.floor(
            value / tick
        ) * tick,
        decimals,
    )


# ============================================================
# ICHIMOKU
# ============================================================

def ichimoku(candles):

    # Need enough candles for 52-period cloud
    # plus previous candle.
    if len(candles) < 54:
        return None

    highs = [
        float(c["high"])
        for c in candles
    ]

    lows = [
        float(c["low"])
        for c in candles
    ]

    closes = [
        float(c["close"])
        for c in candles
    ]

    def midpoint(
        period,
        end
    ):

        start = (
            end - period + 1
        )

        if start < 0:
            return None

        hh = max(
            highs[start:end + 1]
        )

        ll = min(
            lows[start:end + 1]
        )

        return (
            hh + ll
        ) / 2.0

    i = len(candles) - 1

    tenkan = midpoint(9, i)
    kijun = midpoint(26, i)
    span_b = midpoint(52, i)

    prev_tenkan = midpoint(
        9,
        i - 1
    )

    prev_kijun = midpoint(
        26,
        i - 1
    )

    prev_span_b = midpoint(
        52,
        i - 1
    )

    if (
        tenkan is None
        or kijun is None
        or span_b is None
        or prev_tenkan is None
        or prev_kijun is None
        or prev_span_b is None
    ):
        return None

    span_a = (
        tenkan + kijun
    ) / 2.0

    prev_span_a = (
        prev_tenkan
        + prev_kijun
    ) / 2.0

    price = closes[i]

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

    # --------------------------------------------------------
    # PRICE / CLOUD
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # TENKAN / KIJUN
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # CLOUD
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # MOMENTUM
    # --------------------------------------------------------

    if closes[i] > closes[i - 1]:

        buy_score += 1

        buy_reasons.append(
            "MOMENTUM_UP"
        )

    elif closes[i] < closes[i - 1]:

        sell_score += 1

        sell_reasons.append(
            "MOMENTUM_DOWN"
        )

    # --------------------------------------------------------
    # KIJUN DIRECTION
    # --------------------------------------------------------

    if kijun > prev_kijun:

        buy_score += 1

        buy_reasons.append(
            "KIJUN_RISING"
        )

    elif kijun < prev_kijun:

        sell_score += 1

        sell_reasons.append(
            "KIJUN_FALLING"
        )

    # --------------------------------------------------------
    # CLOUD DIRECTION
    # --------------------------------------------------------

    if span_a > prev_span_a:

        buy_score += 1

        buy_reasons.append(
            "CLOUD_RISING"
        )

    elif span_a < prev_span_a:

        sell_score += 1

        sell_reasons.append(
            "CLOUD_FALLING"
        )

    # --------------------------------------------------------
    # SIGNAL
    # --------------------------------------------------------

    signal = None
    score = max(
        buy_score,
        sell_score
    )
    reasons = []

    if (
        buy_score >= MIN_SCORE
        and buy_score > sell_score
    ):

        signal = "BUY"
        score = buy_score
        reasons = buy_reasons

    elif (
        sell_score >= MIN_SCORE
        and sell_score > buy_score
    ):

        signal = "SELL"
        score = sell_score
        reasons = sell_reasons

    return {
        "signal": signal,
        "score": score,
        "buy_score": buy_score,
        "sell_score": sell_score,
        "price": price,
        "tenkan": tenkan,
        "kijun": kijun,
        "span_a": span_a,
        "span_b": span_b,
        "cloud_top": cloud_top,
        "cloud_bottom": cloud_bottom,
        "reasons": reasons,
    }


# ============================================================
# SCAN SYMBOL
# ============================================================

def scan_symbol(
    info,
    state
):

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
            fetch_5m_klines(symbol)
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
                "error": (
                    f"ONLY_{count}_CLOSED_CANDLES"
                ),
            }

        result = ichimoku(
            candles
        )

        if not result:

            return {
                "symbol": symbol,
                "ready": False,
                "candles": count,
                "source": source,
                "error": "ICHIMOKU_FAILED",
            }

        result["symbol"] = symbol
        result["ready"] = True
        result["candles"] = count
        result["source"] = source
        result["info"] = info

        return result

    except Exception as e:

        return {
            "symbol": symbol,
            "ready": False,
            "candles": 0,
            "error": str(e)[:300],
        }


# ============================================================
# REAL FUTURES ORDER
# ============================================================

def place_real_trade(
    signal
):

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
            "No valid quantity step"
        )

    quantity = (
        ORDER_USDT
        * LEVERAGE
    ) / price

    quantity = floor_step(
        quantity,
        step
    )

    if quantity <= 0:

        raise RuntimeError(
            "Calculated quantity is zero"
        )

    if (
        min_qty > 0
        and quantity < min_qty
    ):

        raise RuntimeError(
            f"Quantity {quantity} "
            f"< minQty {min_qty}"
        )

    quantity_text = (
        f"{quantity:.12f}"
        .rstrip("0")
        .rstrip(".")
    )

    # --------------------------------------------------------
    # LEVERAGE
    # --------------------------------------------------------

    signed_request(
        "POST",
        "/api/v1/leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE,
        },
    )

    # --------------------------------------------------------
    # MARKET ORDER
    # --------------------------------------------------------

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


# ============================================================
# MAIN
# ============================================================

def main():

    started = time.time()

    print(
        "💓 ATI FUTURES V11"
    )

    print(
        "⚡ TABDEAL REAL FUTURES"
    )

    print(
        "📊 5M KLINES"
    )

    print(
        "☁️ ICHIMOKU 9 / 26 / 52"
    )

    print(
        f"💵 ORDER: {ORDER_USDT} USDT"
    )

    print(
        f"⚡ LEVERAGE: {LEVERAGE}x"
    )

    print(
        f"🔒 REAL: {REAL_TRADING}"
    )

    state = load_state()

    # --------------------------------------------------------
    # MARKETS
    # --------------------------------------------------------

    try:

        markets = get_markets()

    except Exception as e:

        msg = (
            "❌ ATI FUTURES V11 ERROR\n\n"
            "MARKET DISCOVERY FAILED\n\n"
            f"{e}"
        )

        print(msg)
        telegram(msg)

        return

    print(
        f"📊 Markets: {len(markets)}"
    )

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        jobs = {
            executor.submit(
                scan_symbol,
                info,
                state
            ): info
            for info in markets
        }

        for future in as_completed(
            jobs
        ):

            info = jobs[future]

            try:

                result = (
                    future.result()
                )

                if result:
                    results.append(
                        result
                    )

            except Exception as e:

                results.append({
                    "symbol": info.get(
                        "symbol",
                        "UNKNOWN"
                    ),
                    "ready": False,
                    "candles": 0,
                    "error": str(e)[:300],
                })

    save_state(state)

    # --------------------------------------------------------
    # STATISTICS
    # --------------------------------------------------------

    ready = [
        r for r in results
        if r.get("ready")
    ]

    signals = [
        r for r in ready
        if r.get("signal")
    ]

    errors = [
        r for r in results
        if r.get("error")
    ]

    max_candles = max(
        [
            r.get(
                "candles",
                0
            )
            for r in results
        ] or [0]
    )

    elapsed = (
        time.time()
        - started
    )

    print(
        f"📈 Ready: {len(ready)}"
    )

    print(
        f"🔥 Signals: {len(signals)}"
    )

    print(
        f"❌ Errors: {len(errors)}"
    )

    print(
        f"📚 Max candles: {max_candles}"
    )

    print(
        f"⏱️ Scan: {elapsed:.2f}s"
    )

    # --------------------------------------------------------
    # ERROR SAMPLE
    # --------------------------------------------------------

    error_lines = []

    for r in errors[:5]:

        error_lines.append(
            f"❌ {r.get('symbol')}: "
            f"{r.get('error', 'UNKNOWN')}"
        )

    error_text = ""

    if error_lines:

        error_text = (
            "\n\n".join(
                error_lines
            )
        )

    # --------------------------------------------------------
    # NO SIGNAL
    # --------------------------------------------------------

    if not signals:

        msg = (
            "💓 ATI FUTURES V11\n\n"
            "☁️ NO SIGNAL THIS CYCLE\n\n"
            f"📊 Markets: {len(markets)}\n"
            f"📈 Ready: {len(ready)}\n"
            f"📚 Max candles: {max_candles}\n"
            f"❌ Errors: {len(errors)}\n"
            f"⏱️ Scan: {elapsed:.2f}s\n\n"
            f"💵 ORDER: {ORDER_USDT} USDT\n"
            f"⚡ LEVERAGE: {LEVERAGE}x\n"
            f"🔒 REAL: {REAL_TRADING}"
        )

        if error_text:

            msg += (
                "\n\n"
                "🔎 ERROR SAMPLE:\n"
                + error_text
            )

        print(msg)
        telegram(msg)

        return

    # --------------------------------------------------------
    # BEST SIGNAL
    # --------------------------------------------------------

    signals.sort(
        key=lambda x:
        x.get(
            "score",
            0
        ),
        reverse=True
    )

    best = signals[0]

    msg = (
        "🔥 ATI FUTURES V11 SIGNAL\n\n"
        f"🪙 {best['symbol']}\n"
        f"📌 {best['signal']}\n"
        f"⭐ SCORE: {best['score']}\n"
        f"💰 PRICE: {best['price']}\n\n"
        f"☁️ Tenkan: {best['tenkan']}\n"
        f"☁️ Kijun: {best['kijun']}\n"
        f"☁️ Span A: {best['span_a']}\n"
        f"☁️ Span B: {best['span_b']}\n\n"
        f"🧠 {' / '.join(best['reasons'])}\n\n"
        f"📚 Candles: {best['candles']}\n"
        f"💵 ORDER: {ORDER_USDT} USDT\n"
        f"⚡ LEVERAGE: {LEVERAGE}x\n"
        f"🔒 REAL: {REAL_TRADING}"
    )

    print(msg)
    telegram(msg)

    # --------------------------------------------------------
    # TEST MODE
    # --------------------------------------------------------

    if not REAL_TRADING:

        print(
            "🧪 TEST MODE - "
            "NO REAL ORDER"
        )

        return

    # --------------------------------------------------------
    # REAL ORDER
    # --------------------------------------------------------

    try:

        order = place_real_trade(
            best
        )

        order_msg = (
            "🚨 ATI REAL FUTURES ORDER\n\n"
            f"🪙 {best['symbol']}\n"
            f"📌 {best['signal']}\n"
            f"⭐ SCORE: {best['score']}\n"
            f"💰 PRICE: {best['price']}\n"
            f"⚡ LEVERAGE: {LEVERAGE}x\n"
            f"💵 ORDER: {ORDER_USDT} USDT\n\n"
            f"🆔 ORDER ID: "
            f"{order.get('orderId', 'N/A')}"
        )

        print(order_msg)
        telegram(order_msg)

    except Exception as e:

        error_msg = (
            "❌ REAL FUTURES ORDER ERROR\n\n"
            f"🪙 {best['symbol']}\n"
            f"📌 {best['signal']}\n\n"
            f"{e}"
        )

        print(error_msg)
        telegram(error_msg)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    main()

"main.yml" کامل

:::writing{variant="document" id="74106" title="ATI FUTURES V11 — main.yml"}

name: ATI Futures Bot

on:
  workflow_dispatch:
  schedule:
    - cron: "*/5 * * * *"

jobs:
  run-bot:
    runs-on: ubuntu-latest

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

      - name: Run ATI Futures V11
        env:
          BASE_URL: https://api1.tabdeal.org

          ORDER_USDT: "2"
          LEVERAGE: "3"

          # فعلاً خاموش نگه می‌داریم
          REAL_TRADING: "false"

          TP_PCT: "0.02"
          SL_PCT: "0.01"

          SCAN_UNIVERSE: "75"
          MIN_SCORE: "6"

          REQUEST_TIMEOUT: "10"
          MAX_WORKERS: "15"
          KLINE_LIMIT: "100"
          RECV_WINDOW: "5000"

          TABDEAL_API_KEY: ${{ secrets.TABDEAL_API_KEY }}
          TABDEAL_API_SECRET: ${{ secrets.TABDEAL_API_SECRET }}

          TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}
          TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}

        run: |
          python main.py

این نسخه را فعلاً با "REAL_TRADING: "false"" اجرا کن.
یعنی حتی اگر سیگنال پیدا کند، هیچ معامله واقعی باز نمی‌کند.

نکته مهم V11 این است که دیگر خطای دیتا را قایم نمی‌کند. اگر endpoint اشتباه باشد، تلگرام نمونه خطا را نشان می‌دهد. همچنین از API رسمی Tabdeal استفاده می‌کنیم؛ مستندات رسمی/SDK خود Tabdeal وجود Futures API را تأیید می‌کنند.

بعد از اجرا، فقط پیام تلگرام V11 را برای من بفرست. اگر مثلاً "Ready: 75" شد، می‌رویم سراغ بهینه‌سازی سیگنال Ichimoku؛ اگر خطا شد، از روی ERROR SAMPLE دقیقاً همان endpoint را اصلاح می‌کنیم.
