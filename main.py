import os
import time
import hmac
import hashlib
from urllib.parse import urlencode

import requests


# =========================================================
# ATI FUTURES MULTI-COIN
# AUTO SYMBOL DISCOVERY
# NO BTCUSDT FIXED SYMBOL
# DIAGNOSTIC VERSION - NO REAL ORDER
# =========================================================

API_BASE = "https://api1.tabdeal.org"

READ_BASE = f"{API_BASE}/r/fapi/v1/"
WRITE_BASE = f"{API_BASE}/fapi/v1/"

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

RECV_WINDOW = 5000
TIMEOUT = 15

# فعلاً فقط تست و کشف بازار
# هیچ سفارش واقعی ارسال نمی‌شود.
REAL_TRADING = False

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "ATI-Futures-Bot/1.0",
    "Accept": "application/json",
})


# =========================================================
# TELEGRAM
# =========================================================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print(message)
        return

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        SESSION.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message,
            },
            timeout=10,
        )
    except Exception as e:
        print("Telegram error:", e)

    print(message)


# =========================================================
# HELPERS
# =========================================================

def pretty_number(value):
    try:
        return f"{float(value):,.8f}".rstrip("0").rstrip(".")
    except Exception:
        return str(value)


def extract_json(response):
    try:
        return response.json()
    except Exception:
        raise RuntimeError(
            f"HTTP {response.status_code}: {response.text[:1000]}"
        )


# =========================================================
# PUBLIC GET
# =========================================================

def public_get(endpoint, params=None):
    url = READ_BASE + endpoint

    r = SESSION.get(
        url,
        params=params or {},
        timeout=TIMEOUT,
    )

    if r.status_code >= 400:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:1000]}"
        )

    return extract_json(r)


# =========================================================
# SIGNED GET
# =========================================================

def signed_get(endpoint, params=None):
    if not API_KEY or not API_SECRET:
        raise RuntimeError(
            "TABDIL_API_KEY / TABDIL_API_SECRET not found"
        )

    data = dict(params or {})

    data["timestamp"] = int(time.time() * 1000)
    data["recvWindow"] = RECV_WINDOW

    query = urlencode(data)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    data["signature"] = signature

    headers = {
        "X-MBX-APIKEY": API_KEY,
    }

    url = READ_BASE + endpoint

    r = SESSION.get(
        url,
        params=data,
        headers=headers,
        timeout=TIMEOUT,
    )

    if r.status_code >= 400:
        raise RuntimeError(
            f"HTTP {r.status_code}: {r.text[:1000]}"
        )

    return extract_json(r)


# =========================================================
# DISCOVER ALL FUTURES SYMBOLS
# =========================================================

def discover_symbols():

    print("\n" + "=" * 60)
    print("🔎 FUTURES EXCHANGE INFO")
    print("=" * 60)

    data = public_get("exchangeInfo")

    print("RAW TYPE:", type(data).__name__)

    symbols = []

    # -----------------------------------------
    # حالت‌های مختلف پاسخ API
    # -----------------------------------------

    if isinstance(data, list):
        symbols = data

    elif isinstance(data, dict):

        if isinstance(data.get("symbols"), list):
            symbols = data["symbols"]

        elif isinstance(data.get("data"), list):
            symbols = data["data"]

        elif isinstance(data.get("result"), list):
            symbols = data["result"]

        elif isinstance(data.get("data"), dict):

            nested = data["data"]

            if isinstance(nested.get("symbols"), list):
                symbols = nested["symbols"]

        elif isinstance(data.get("result"), dict):

            nested = data["result"]

            if isinstance(nested.get("symbols"), list):
                symbols = nested["symbols"]

    if not symbols:
        print("\n❌ هیچ نماد Futures پیدا نشد.")
        print("RAW RESPONSE:")
        print(data)
        return []

    print(f"\n✅ تعداد رکوردهای Futures: {len(symbols)}")

    result = []

    for item in symbols:

        if isinstance(item, str):
            symbol = item.upper().strip()

        elif isinstance(item, dict):
            symbol = (
                item.get("symbol")
                or item.get("contract")
                or item.get("name")
                or item.get("pair")
                or ""
            )

            symbol = str(symbol).upper().strip()

        else:
            continue

        if symbol:
            result.append(symbol)

    result = sorted(set(result))

    print(f"✅ تعداد نمادهای قابل استخراج: {len(result)}")

    return result


# =========================================================
# FIND BEST TRADABLE SYMBOLS
# =========================================================

def find_candidates(symbols):

    print("\n" + "=" * 60)
    print("📊 FUTURES SYMBOLS")
    print("=" * 60)

    # حذف مواردی که احتمالاً قابل معامله نیستند
    blocked_words = [
        "INDEX",
        "MARK",
        "TEST",
        "NULL",
    ]

    candidates = []

    for symbol in symbols:

        if any(word in symbol for word in blocked_words):
            continue

        candidates.append(symbol)

    print(f"✅ قابل بررسی: {len(candidates)}")

    # نمایش حداکثر 100 نماد
    for i, symbol in enumerate(candidates[:100], 1):
        print(f"{i:03d}  {symbol}")

    if len(candidates) > 100:
        print(
            f"... و {len(candidates) - 100} نماد دیگر"
        )

    return candidates


# =========================================================
# VERIFY SYMBOL
# =========================================================

def verify_symbol(symbol):

    print("\n" + "=" * 60)
    print(f"🔍 VERIFY: {symbol}")
    print("=" * 60)

    try:

        data = public_get(
            "depth",
            {
                "symbol": symbol,
                "limit": 5,
            },
        )

        print("✅ SYMBOL VALID")

        if isinstance(data, dict):

            bids = data.get("bids", [])
            asks = data.get("asks", [])

            print("BIDS:", len(bids))
            print("ASKS:", len(asks))

            if bids:
                print("BEST BID:", bids[0])

            if asks:
                print("BEST ASK:", asks[0])

        return True

    except Exception as e:

        print(f"❌ INVALID SYMBOL: {symbol}")
        print("ERROR:", e)

        return False


# =========================================================
# FIND USDT / USD FUTURES
# =========================================================

def find_quote_symbols(symbols):

    preferred = []

    for symbol in symbols:

        s = symbol.upper()

        if (
            s.endswith("USDT")
            or s.endswith("USDC")
            or s.endswith("USD")
        ):
            preferred.append(s)

    return sorted(set(preferred))


# =========================================================
# ACCOUNT TEST
# =========================================================

def account_test():

    print("\n" + "=" * 60)
    print("🔐 FUTURES ACCOUNT")
    print("=" * 60)

    data = signed_get("account")

    if isinstance(data, dict):

        print("✅ AUTH SUCCESS")

        print(
            "canTrade:",
            data.get("canTrade")
        )

        print(
            "canWithdraw:",
            data.get("canWithdraw")
        )

        print(
            "canDeposit:",
            data.get("canDeposit")
        )

        assets = data.get("assets", [])

        if isinstance(assets, list):

            print("\n💰 BALANCES:")

            shown = 0

            for asset in assets:

                if not isinstance(asset, dict):
                    continue

                name = asset.get("asset", "")

                wallet = (
                    asset.get("walletBalance")
                    or asset.get("balance")
                    or "0"
                )

                available = (
                    asset.get("availableBalance")
                    or asset.get("available")
                    or "0"
                )

                try:
                    available_float = float(available)
                except Exception:
                    available_float = 0

                if available_float != 0 or name in [
                    "USDT",
                    "USDC",
                ]:

                    print(
                        f"{name}: "
                        f"wallet={wallet} "
                        f"available={available}"
                    )

                    shown += 1

            if shown == 0:
                print("موجودی قابل نمایش پیدا نشد.")


# =========================================================
# POSITION TEST
# =========================================================

def positions_test():

    print("\n" + "=" * 60)
    print("📌 OPEN FUTURES POSITIONS")
    print("=" * 60)

    data = signed_get("positionRisk")

    if isinstance(data, list):

        open_positions = []

        for p in data:

            if not isinstance(p, dict):
                continue

            amount = (
                p.get("positionAmt")
                or p.get("quantity")
                or p.get("qty")
                or "0"
            )

            try:
                amount_float = float(amount)
            except Exception:
                amount_float = 0

            if amount_float != 0:
                open_positions.append(p)

        if not open_positions:
            print("✅ هیچ پوزیشن بازی وجود ندارد.")

        else:

            for p in open_positions:

                print(
                    "\nSYMBOL:",
                    p.get("symbol")
                )

                print(
                    "POSITION:",
                    p.get("positionAmt")
                    or p.get("quantity")
                    or p.get("qty")
                )

                print(
                    "ENTRY:",
                    p.get("entryPrice")
                )

                print(
                    "MARK:",
                    p.get("markPrice")
                )

                print(
                    "UNREALIZED:",
                    p.get("unRealizedProfit")
                )


# =========================================================
# MAIN
# =========================================================

def main():

    telegram(
        "💓 ATI FUTURES\n"
        "⚡ MULTI-COIN AUTO DISCOVERY\n"
        "📡 TABDEAL FUTURES\n"
        "🔒 REAL ORDER: OFF\n"
        "🔎 BTC ثابت نیست"
    )

    print("\nATI FUTURES MULTI-COIN START")

    # -----------------------------------------
    # 1. Discover
    # -----------------------------------------

    try:
        symbols = discover_symbols()

    except Exception as e:

        telegram(
            "❌ FUTURES EXCHANGE INFO ERROR\n\n"
            + str(e)
        )

        return

    if not symbols:

        telegram(
            "❌ هیچ Futures Symbol پیدا نشد."
        )

        return

    # -----------------------------------------
    # 2. All tradable candidates
    # -----------------------------------------

    candidates = find_candidates(symbols)

    # -----------------------------------------
    # 3. USDT / USD market list
    # -----------------------------------------

    quote_symbols = find_quote_symbols(candidates)

    print("\n" + "=" * 60)
    print("💵 USDT / USD FUTURES")
    print("=" * 60)

    print(
        f"تعداد: {len(quote_symbols)}"
    )

    for symbol in quote_symbols[:150]:
        print(symbol)

    if len(quote_symbols) > 150:
        print(
            f"... {len(quote_symbols)-150} مورد دیگر"
        )

    # -----------------------------------------
    # 4. Verify several real symbols
    # -----------------------------------------

    print("\n" + "=" * 60)
    print("🧪 VERIFY REAL FUTURES MARKETS")
    print("=" * 60)

    verified = []

    # اول نمادهای USDT
    test_list = quote_symbols[:20]

    for symbol in test_list:

        if verify_symbol(symbol):
            verified.append(symbol)

    # -----------------------------------------
    # 5. Account
    # -----------------------------------------

    if API_KEY and API_SECRET:

        try:
            account_test()

        except Exception as e:

            print(
                "\n❌ ACCOUNT ERROR:"
            )

            print(e)

        try:
            positions_test()

        except Exception as e:

            print(
                "\n❌ POSITION ERROR:"
            )

            print(e)

    else:

        print(
            "\n⚠️ API KEY/SECRET موجود نیست."
        )

    # -----------------------------------------
    # FINAL
    # -----------------------------------------

    print("\n" + "=" * 60)
    print("✅ ATI FUTURES DISCOVERY FINISHED")
    print("=" * 60)

    print(
        f"📊 TOTAL SYMBOLS: {len(symbols)}"
    )

    print(
        f"💵 USDT/USD SYMBOLS: {len(quote_symbols)}"
    )

    print(
        f"🟢 VERIFIED SYMBOLS: {len(verified)}"
    )

    if verified:

        print("\nنمادهای تأییدشده:")

        for s in verified:
            print("✅", s)

    print(
        "\n🔒 REAL ORDER = OFF"
    )

    telegram(
        "✅ ATI FUTURES SCAN OK\n"
        f"📊 TOTAL: {len(symbols)}\n"
        f"💵 USDT/USD: {len(quote_symbols)}\n"
        f"🟢 VERIFIED: {len(verified)}\n"
        "🔒 REAL ORDER: OFF"
    )


if __name__ == "__main__":
    main()
