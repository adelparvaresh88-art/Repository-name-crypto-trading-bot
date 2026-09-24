import os
import time
import hmac
import hashlib
import requests
from urllib.parse import urlencode
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ============================================================
# ATI CRYPTO BOT V34
# SMART UPWARD COIN SCANNER + TABDEAL FAPI
# 5M CLOSED CANDLE
# 3X LEVERAGE PREPARATION
# ============================================================

BASE_URL = "https://api1.tabdeal.org"

TIMEFRAME = "5m"

TRADE_LIMIT = 250
MIN_CANDLES = 40
MAX_WORKERS = 12

MAX_STRONG_BUYS = 3
MAX_EARLY_BUYS = 5

# ============================================================
# REAL TRADING SAFETY
# ============================================================

# IMPORTANT:
# False = scanner / test only
# True  = REAL FUTURES ORDER
ENABLE_REAL_TRADING = False

LEVERAGE = 3

# Margin used per trade
TRADE_MARGIN_USDT = 20.0

# Maximum one open position
MAX_OPEN_POSITIONS = 1

# ============================================================
# STRONG BUY FILTER
# ============================================================

MIN_BREAKOUT_PCT = 0.0015
MIN_BODY_RATIO = 0.55
MIN_CLOSE_POSITION = 0.65
MIN_MOMENTUM_PCT = 0.0015
MIN_VOLUME_RATIO = 1.20

MAX_CHASE_PCT = 0.015

# ============================================================
# EARLY BUY FILTER
# ============================================================

EARLY_DISTANCE = 0.0025
EARLY_MOMENTUM_PCT = 0.0010
EARLY_VOLUME_RATIO = 1.05

# ============================================================
# TECHNICAL SETTINGS
# ============================================================

MOMENTUM_LOOKBACK = 3
VOLUME_LOOKBACK = 10
RESISTANCE_LOOKBACK = 20

ATR_PERIOD = 14

SL_ATR = 1.20
TP1_ATR = 1.50
TP2_ATR = 2.40

REQUEST_TIMEOUT = 15

# ============================================================
# SECRETS
# ============================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

TABDEAL_API_KEY = os.getenv("TABDEAL_API_KEY", "")
TABDEAL_API_SECRET = os.getenv("TABDEAL_API_SECRET", "")


# ============================================================
# HELPERS
# ============================================================

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def fmt_price(value):
    if value is None:
        return "-"

    value = float(value)

    if value >= 1000:
        return f"{value:,.2f}"
    elif value >= 1:
        return f"{value:,.4f}"
    elif value >= 0.01:
        return f"{value:.6f}"
    elif value >= 0.0001:
        return f"{value:.8f}"
    else:
        return f"{value:.12f}"


def fmt_pct(value):
    return f"{value * 100:.2f}%"


def telegram_send(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message
            },
            timeout=REQUEST_TIMEOUT
        )

        if response.ok:
            return True

        print("Telegram error:", response.text)
        return False

    except Exception as e:
        print("Telegram exception:", e)
        return False


# ============================================================
# TABDEAL PUBLIC API
# ============================================================

def public_get(path, params=None):
    url = BASE_URL + path

    response = requests.get(
        url,
        params=params or {},
        timeout=REQUEST_TIMEOUT
    )

    response.raise_for_status()
    return response.json()


def get_exchange_info():
    return public_get("/r/fapi/v1/exchangeInfo")


def get_klines(symbol):
    return public_get(
        "/r/api/v1/klines",
        {
            "symbol": symbol,
            "interval": TIMEFRAME,
            "limit": TRADE_LIMIT
        }
    )


# ============================================================
# SIGNED FAPI
# ============================================================

def signed_request(method, path, params=None):
    if not TABDEAL_API_KEY or not TABDEAL_API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_KEY / TABDEAL_API_SECRET missing"
        )

    params = params.copy() if params else {}

    params["timestamp"] = int(time.time() * 1000)

    query_string = urlencode(params)

    signature = hmac.new(
        TABDEAL_API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": TABDEAL_API_KEY
    }

    url = BASE_URL + path

    if method.upper() == "GET":
        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    elif method.upper() == "POST":
        response = requests.post(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    elif method.upper() == "DELETE":
        response = requests.delete(
            url,
            params=params,
            headers=headers,
            timeout=REQUEST_TIMEOUT
        )

    else:
        raise RuntimeError("Unsupported HTTP method")

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code}: {response.text}"
        )

    return response.json()


# ============================================================
# FUTURES ACCOUNT
# ============================================================

def get_futures_account():
    return signed_request(
        "GET",
        "/r/fapi/v3/account"
    )


def get_open_positions():
    account = get_futures_account()

    positions = account.get("positions", [])

    active = []

    for p in positions:
        try:
            amount = float(p.get("positionAmt", 0))
        except Exception:
            amount = 0

        if abs(amount) > 0:
            active.append(p)

    return active


def check_futures_account():
    account = get_futures_account()

    can_trade = account.get("canTrade", False)

    assets = account.get("assets", [])

    available = 0.0

    for asset in assets:
        if asset.get("asset") == "USDT":
            try:
                available = float(
                    asset.get("availableBalance", 0)
                )
            except Exception:
                available = 0.0

    return can_trade, available


# ============================================================
# LEVERAGE
# ============================================================

def set_leverage(symbol):
    result = signed_request(
        "POST",
        "/fapi/v1/leverage",
        {
            "symbol": symbol,
            "leverage": LEVERAGE
        }
    )

    return result


# ============================================================
# FUTURES ORDER
# ============================================================

def create_market_buy(symbol, quantity):
    return signed_request(
        "POST",
        "/fapi/v1/order",
        {
            "symbol": symbol,
            "side": "BUY",
            "type": "MARKET",
            "quantity": quantity
        }
    )


# ============================================================
# POSITION
# ============================================================

def get_active_position(symbol):
    result = signed_request(
        "GET",
        "/r/fapi/v1/position",
        {
            "symbol": symbol,
            "isActive": 1,
            "limit": 50
        }
    )

    if not isinstance(result, list):
        return None

    for position in result:

        try:
            amount = float(
                position.get("positionAmt", 0)
            )
        except Exception:
            amount = 0

        if abs(amount) > 0:
            return position

    return None


def set_position_sl_tp(
    position_id,
    symbol,
    sl_price,
    tp_price
):

    return signed_request(
        "POST",
        "/fapi/v1/positionSlTp",
        {
            "positionId": position_id,
            "symbol": symbol,
            "slPrice": str(sl_price),
            "tpPrice": str(tp_price),
            "workingType": "MARK_PRICE"
        }
    )


# ============================================================
# MARKET DATA
# ============================================================

def parse_candles(raw):

    candles = []

    for c in raw:

        try:
            candles.append({
                "open_time": int(c[0]),
                "open": float(c[1]),
                "high": float(c[2]),
                "low": float(c[3]),
                "close": float(c[4]),
                "volume": float(c[5]),
                "close_time": int(c[6])
            })

        except Exception:
            continue

    return candles


def remove_open_candle(candles):

    if len(candles) < 3:
        return candles

    now_ms = int(time.time() * 1000)

    last = candles[-1]

    if last["close_time"] > now_ms:
        return candles[:-1]

    return candles


# ============================================================
# ATR
# ============================================================

def calculate_atr(candles, period=14):

    if len(candles) < period + 1:
        return None

    trs = []

    for i in range(1, len(candles)):

        current = candles[i]
        previous = candles[i - 1]

        tr = max(
            current["high"] - current["low"],
            abs(current["high"] - previous["close"]),
            abs(current["low"] - previous["close"])
        )

        trs.append(tr)

    if len(trs) < period:
        return None

    return sum(trs[-period:]) / period


# ============================================================
# ANALYZE SYMBOL
# ============================================================

def analyze_symbol(symbol):

    try:

        raw = get_klines(symbol)

        candles = parse_candles(raw)

        candles = remove_open_candle(candles)

        if len(candles) < MIN_CANDLES:
            return None

        current = candles[-1]

        close = current["close"]
        open_price = current["open"]
        high = current["high"]
        low = current["low"]

        candle_range = high - low

        if candle_range <= 0:
            return None

        body = abs(close - open_price)

        body_ratio = body / candle_range

        close_position = (
            (close - low) / candle_range
        )

        bullish_candle = close > open_price

        # ----------------------------------------------------
        # RESISTANCE
        # ----------------------------------------------------

        previous = candles[
            -(RESISTANCE_LOOKBACK + 1):-1
        ]

        resistance = max(
            c["high"] for c in previous
        )

        support = min(
            c["low"] for c in previous
        )

        breakout_pct = (
            close / resistance
        ) - 1

        distance_to_resistance = (
            resistance - close
        ) / resistance

        # ----------------------------------------------------
        # MOMENTUM
        # ----------------------------------------------------

        momentum_base = candles[
            -(MOMENTUM_LOOKBACK + 1)
        ]["close"]

        momentum_pct = (
            close / momentum_base
        ) - 1

        # ----------------------------------------------------
        # VOLUME
        # ----------------------------------------------------

        volume_history = candles[
            -(VOLUME_LOOKBACK + 1):-1
        ]

        avg_volume = (
            sum(c["volume"] for c in volume_history)
            / len(volume_history)
        )

        if avg_volume <= 0:
            return None

        volume_ratio = (
            current["volume"] / avg_volume
        )

        # ----------------------------------------------------
        # TREND
        # ----------------------------------------------------

        close_3 = candles[-4]["close"]
        close_5 = candles[-6]["close"]

        bullish_trend = (
            close > close_3 > close_5
        )

        # ----------------------------------------------------
        # CHASE FILTER
        # ----------------------------------------------------

        move_from_support = (
            close / support
        ) - 1

        not_overextended = (
            move_from_support <= MAX_CHASE_PCT
        )

        # ----------------------------------------------------
        # STRONG CANDLE
        # ----------------------------------------------------

        strong_candle = (
            bullish_candle
            and body_ratio >= MIN_BODY_RATIO
            and close_position >= MIN_CLOSE_POSITION
        )

        # ----------------------------------------------------
        # STRONG BUY
        # ----------------------------------------------------

        strong_buy = (
            breakout_pct >= MIN_BREAKOUT_PCT
            and strong_candle
            and momentum_pct >= MIN_MOMENTUM_PCT
            and volume_ratio >= MIN_VOLUME_RATIO
            and bullish_trend
            and not_overextended
        )

        # ----------------------------------------------------
        # EARLY BUY
        # ----------------------------------------------------

        early_buy = (
            not strong_buy
            and distance_to_resistance >= 0
            and distance_to_resistance <= EARLY_DISTANCE
            and strong_candle
            and momentum_pct >= EARLY_MOMENTUM_PCT
            and volume_ratio >= EARLY_VOLUME_RATIO
            and bullish_trend
        )

        if not strong_buy and not early_buy:
            return None

        atr = calculate_atr(
            candles,
            ATR_PERIOD
        )

        if atr is None or atr <= 0:
            return None

        sl = close - (
            atr * SL_ATR
        )

        tp1 = close + (
            atr * TP1_ATR
        )

        tp2 = close + (
            atr * TP2_ATR
        )

        return {
            "symbol": symbol,
            "price": close,
            "resistance": resistance,
            "support": support,
            "breakout_pct": breakout_pct,
            "distance_to_resistance": distance_to_resistance,
            "momentum_pct": momentum_pct,
            "volume_ratio": volume_ratio,
            "body_ratio": body_ratio,
            "close_position": close_position,
            "atr": atr,
            "sl": sl,
            "tp1": tp1,
            "tp2": tp2,
            "strong_buy": strong_buy,
            "early_buy": early_buy
        }

    except Exception as e:

        print(
            f"{symbol} analysis error: {e}"
        )

        return None


# ============================================================
# MARKET LIST
# ============================================================

def get_usdt_symbols():

    info = get_exchange_info()

    symbols = []

    for item in info.get("symbols", []):

        symbol = item.get("symbol", "")
        status = item.get("status", "")
        quote = item.get("quoteAsset", "")

        if (
            status == "TRADING"
            and quote == "USDT"
            and symbol.endswith("USDT")
        ):
            symbols.append(symbol)

    return symbols


# ============================================================
# REAL TRADE
# ============================================================

def execute_real_trade(signal):

    symbol = signal["symbol"]
    price = signal["price"]

    print(
        f"REAL TRADE REQUEST: {symbol}"
    )

    if not TABDEAL_API_KEY or not TABDEAL_API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_KEY or TABDEAL_API_SECRET missing"
        )

    # --------------------------------------------------------
    # CHECK ACCOUNT
    # --------------------------------------------------------

    can_trade, available = (
        check_futures_account()
    )

    if not can_trade:
        raise RuntimeError(
            "Futures account cannot trade."
        )

    if available < TRADE_MARGIN_USDT:
        raise RuntimeError(
            f"Insufficient futures USDT. "
            f"Available={available:.2f}, "
            f"Required={TRADE_MARGIN_USDT:.2f}"
        )

    # --------------------------------------------------------
    # CHECK EXISTING POSITIONS
    # --------------------------------------------------------

    open_positions = get_open_positions()

    if len(open_positions) >= MAX_OPEN_POSITIONS:
        raise RuntimeError(
            "Existing open position detected. "
            "New trade blocked."
        )

    # --------------------------------------------------------
    # SET 3X
    # --------------------------------------------------------

    leverage_result = set_leverage(symbol)

    print(
        "Leverage result:",
        leverage_result
    )

    # --------------------------------------------------------
    # POSITION SIZE
    # --------------------------------------------------------

    notional = (
        TRADE_MARGIN_USDT
        * LEVERAGE
    )

    quantity = (
        notional / price
    )

    # --------------------------------------------------------
    # GET FUTURES MARKET PRECISION
    # --------------------------------------------------------

    info = get_exchange_info()

    quantity_precision = 6

    for item in info.get("symbols", []):

        if item.get("symbol") == symbol:

            try:
                quantity_precision = int(
                    item.get(
                        "quantityPrecision",
                        6
                    )
                )
            except Exception:
                quantity_precision = 6

            break

    quantity = round(
        quantity,
        quantity_precision
    )

    if quantity <= 0:
        raise RuntimeError(
            "Calculated quantity is zero."
        )

    # --------------------------------------------------------
    # MARKET BUY
    # --------------------------------------------------------

    order = create_market_buy(
        symbol,
        quantity
    )

    print(
        "ORDER RESPONSE:",
        order
    )

    order_id = order.get("orderId")

    if not order_id:
        raise RuntimeError(
            f"Order was not accepted: {order}"
        )

    # --------------------------------------------------------
    # WAIT FOR POSITION
    # --------------------------------------------------------

    position = None

    for _ in range(10):

        time.sleep(1)

        position = get_active_position(
            symbol
        )

        if position:
            break

    if not position:
        raise RuntimeError(
            "Order sent but active position "
            "could not be found."
        )

    position_id = position.get("id")

    if not position_id:
        raise RuntimeError(
            f"Position ID missing: {position}"
        )

    entry_price = float(
        position.get(
            "entryPrice",
            price
        )
    )

    # --------------------------------------------------------
    # SL / TP
    # --------------------------------------------------------

    sl = signal["sl"]
    tp2 = signal["tp2"]

    sltp_result = set_position_sl_tp(
        position_id,
        symbol,
        sl,
        tp2
    )

    print(
        "SL/TP RESPONSE:",
        sltp_result
    )

    return {
        "order": order,
        "position": position,
        "entry": entry_price,
        "sl": sl,
        "tp": tp2
    }


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("ATI CRYPTO BOT V34")
    print("SMART UPWARD SCANNER + FAPI")
    print("=" * 60)

    # --------------------------------------------------------
    # CHECK TELEGRAM
    # --------------------------------------------------------

    telegram_ok = bool(
        TELEGRAM_BOT_TOKEN
        and TELEGRAM_CHAT_ID
    )

    # --------------------------------------------------------
    # MARKET LIST
    # --------------------------------------------------------

    try:

        symbols = get_usdt_symbols()

    except Exception as e:

        message = (
            "⚡ ATI CRYPTO BOT V34\n\n"
            "❌ TABDEAL API ERROR\n\n"
            f"{e}"
        )

        telegram_send(message)

        print(message)

        return

    print(
        f"USDT markets: {len(symbols)}"
    )

    # --------------------------------------------------------
    # SCAN
    # --------------------------------------------------------

    results = []

    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS
    ) as executor:

        futures = {
            executor.submit(
                analyze_symbol,
                symbol
            ): symbol
            for symbol in symbols
        }

        for future in as_completed(futures):

            try:

                result = future.result()

                if result:
                    results.append(result)

            except Exception as e:

                symbol = futures[future]

                print(
                    f"{symbol}: {e}"
                )

    strong = [
        x for x in results
        if x["strong_buy"]
    ]

    early = [
        x for x in results
        if x["early_buy"]
    ]

    strong.sort(
        key=lambda x: (
            x["breakout_pct"]
            + x["momentum_pct"]
            + (x["volume_ratio"] / 10)
        ),
        reverse=True
    )

    early.sort(
        key=lambda x: (
            x["momentum_pct"]
            + (x["volume_ratio"] / 10)
        ),
        reverse=True
    )

    strong = strong[:MAX_STRONG_BUYS]
    early = early[:MAX_EARLY_BUYS]

    # --------------------------------------------------------
    # MESSAGE
    # --------------------------------------------------------

    lines = []

    lines.append(
        "⚡ ATI CRYPTO BOT V34"
    )

    lines.append(
        "🚀 SMART UPWARD COIN SCANNER"
    )

    lines.append(
        "⏱ Timeframe: 5m"
    )

    lines.append(
        "✅ CLOSED CANDLE"
    )

    lines.append(
        "💥 BREAKOUT + MOMENTUM + VOLUME"
    )

    lines.append(
        "🧠 FAPI 3X READY"
    )

    lines.append("")

    lines.append(
        "📡 TABDEAL API: OK"
    )

    lines.append(
        f"📊 USDT MARKETS: {len(symbols)}"
    )

    lines.append(
        f"🔎 SCANNED: {len(symbols)}"
    )

    lines.append(
        f"🕐 Scan: {now_utc()}"
    )

    lines.append("")

    # --------------------------------------------------------
    # STRONG BUY
    # --------------------------------------------------------

    if strong:

        lines.append(
            f"🟢 STRONG BUY: {len(strong)}"
        )

        lines.append("")

        for i, item in enumerate(
            strong,
            1
        ):

            lines.append(
                f"🟢 #{i} {item['symbol']}"
            )

            lines.append(
                f"💰 Entry: {fmt_price(item['price'])}"
            )

            lines.append(
                f"🚀 Breakout: "
                f"{fmt_pct(item['breakout_pct'])}"
            )

            lines.append(
                f"📈 Momentum: "
                f"{fmt_pct(item['momentum_pct'])}"
            )

            lines.append(
                f"📊 Volume: "
                f"{item['volume_ratio']:.2f}x"
            )

            lines.append(
                f"🛑 SL: {fmt_price(item['sl'])}"
            )

            lines.append(
                f"🎯 TP1: {fmt_price(item['tp1'])}"
            )

            lines.append(
                f"🎯 TP2: {fmt_price(item['tp2'])}"
            )

            lines.append("")

    else:

        lines.append(
            "🟢 STRONG BUY: NONE"
        )

        lines.append("")

    # --------------------------------------------------------
    # EARLY
    # --------------------------------------------------------

    if early:

        lines.append(
            f"🟡 EARLY BUY / WATCH: {len(early)}"
        )

        lines.append("")

        for i, item in enumerate(
            early,
            1
        ):

            lines.append(
                f"🟡 #{i} {item['symbol']}"
            )

            lines.append(
                f"💰 Price: {fmt_price(item['price'])}"
            )

            lines.append(
                f"📏 To Resistance: "
                f"{fmt_pct(item['distance_to_resistance'])}"
            )

            lines.append(
                f"📈 Momentum: "
                f"{fmt_pct(item['momentum_pct'])}"
            )

            lines.append(
                f"📊 Volume: "
                f"{item['volume_ratio']:.2f}x"
            )

            lines.append("")

    else:

        lines.append(
            "🟡 EARLY BUY / WATCH: NONE"
        )

        lines.append("")

    # --------------------------------------------------------
    # REAL TRADING
    # --------------------------------------------------------

    if not ENABLE_REAL_TRADING:

        lines.append(
            "⚪ REAL TRADING: OFF"
        )

        lines.append(
            "🧪 MODE: PAPER / TEST"
        )

    else:

        lines.append(
            "🔴 REAL TRADING: ON"
        )

        lines.append(
            "⚠️ FUTURES LEVERAGE: 3X"
        )

        lines.append(
            f"💵 MARGIN / TRADE: "
            f"{TRADE_MARGIN_USDT:.2f} USDT"
        )

    lines.append("")

    lines.append(
        "📡 TELEGRAM: "
        + ("OK" if telegram_ok else "ERROR")
    )

    message = "\n".join(lines)

    print(message)

    # --------------------------------------------------------
    # REAL TRADE ONLY FROM STRONG BUY
    # --------------------------------------------------------

    if ENABLE_REAL_TRADING and strong:

        signal = strong[0]

        try:

            trade = execute_real_trade(
                signal
            )

            entry = trade["entry"]
            sl = trade["sl"]
            tp = trade["tp"]

            trade_message = (
                "\n\n"
                "🔴 REAL FUTURES TRADE OPENED\n\n"
                f"🟢 {signal['symbol']}\n"
                f"⚙️ Leverage: {LEVERAGE}X\n"
                f"💵 Margin: "
                f"{TRADE_MARGIN_USDT:.2f} USDT\n"
                f"📊 Notional: "
                f"{TRADE_MARGIN_USDT * LEVERAGE:.2f} USDT\n"
                f"💰 Entry: {fmt_price(entry)}\n"
                f"🛑 SL: {fmt_price(sl)}\n"
                f"🎯 TP: {fmt_price(tp)}\n"
                "\n"
                "⚠️ REAL MONEY POSITION"
            )

            message += trade_message

        except Exception as e:

            message += (
                "\n\n"
                "🛡 TRADE BLOCKED\n"
                f"❌ {e}"
            )

    telegram_send(message)


if __name__ == "__main__":
    main()
