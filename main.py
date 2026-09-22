import os
import time
from decimal import Decimal, InvalidOperation

import requests

# =========================
# ATI BOT - TABDEAL FUTURES
# SAFE BALANCE CHECK
# =========================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TABDEAL_API_KEY = os.getenv("TABDEAL_API_KEY")
TABDEAL_API_SECRET = os.getenv("TABDEAL_API_SECRET")

SYMBOL = "BTCUSDT"
MIN_USDT_REQUIRED = Decimal("2")


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print(message)
        return

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=15
        )
    except Exception as e:
        print("Telegram error:", e)


def get_futures_balance():
    """
    خواندن موجودی Futures از SDK رسمی تب‌دیل.
    اگر موجودی قابل تأیید نباشد، None برمی‌گرداند.
    """

    if not TABDEAL_API_KEY or not TABDEAL_API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_KEY or TABDEAL_API_SECRET is missing"
        )

    try:
        from tabdeal.future import Future

        client = Future(
            TABDEAL_API_KEY,
            TABDEAL_API_SECRET
        )

        # تلاش برای دریافت اطلاعات حساب Futures
        #
        # نام متد ممکن است بر اساس نسخه SDK متفاوت باشد.
        # بنابراین عمداً در صورت نبودن متد، معامله متوقف می‌شود.
        possible_methods = [
            "account",
            "account_info",
            "balance",
            "futures_account",
            "futures_account_balance",
        ]

        response = None

        for method_name in possible_methods:
            method = getattr(client, method_name, None)

            if callable(method):
                try:
                    response = method()
                    if response is not None:
                        break
                except Exception:
                    continue

        if response is None:
            raise RuntimeError(
                "Futures balance method was not available"
            )

        print("RAW FUTURES BALANCE RESPONSE:")
        print(response)

        return extract_usdt_balance(response)

    except Exception as e:
        print("Futures balance error:", repr(e))
        raise


def extract_usdt_balance(data):
    """
    تلاش امن برای پیدا کردن USDT از پاسخ API.
    هیچ مقدار حدسی استفاده نمی‌شود.
    """

    if data is None:
        return None

    # حالت مستقیم
    if isinstance(data, dict):

        # نمونه‌های رایج:
        for key in [
            "USDT",
            "usdt",
            "availableUSDT",
            "available_usdt",
            "availableBalance",
            "available_balance",
            "balance",
            "free",
        ]:
            if key in data:
                value = data[key]

                if isinstance(value, dict):
                    nested = extract_usdt_balance(value)
                    if nested is not None:
                        return nested

                try:
                    return Decimal(str(value))
                except (InvalidOperation, TypeError):
                    pass

        # جستجوی بازگشتی داخل پاسخ
        for value in data.values():
            result = extract_usdt_balance(value)

            if result is not None:
                return result

    # اگر پاسخ لیست باشد
    elif isinstance(data, list):

        for item in data:
            if isinstance(item, dict):

                asset = str(
                    item.get(
                        "asset",
                        item.get(
                            "currency",
                            item.get(
                                "coin",
                                ""
                            )
                        )
                    )
                ).upper()

                if asset == "USDT":
                    for key in [
                        "available",
                        "availableBalance",
                        "available_balance",
                        "free",
                        "balance",
                        "walletBalance",
                        "wallet_balance",
                    ]:
                        if key in item:
                            try:
                                return Decimal(str(item[key]))
                            except (InvalidOperation, TypeError):
                                pass

                result = extract_usdt_balance(item)

                if result is not None:
                    return result

    return None


def check_usdt_balance():
    """
    بررسی موجودی قبل از هر معامله.
    """

    try:
        balance = get_futures_balance()

        if balance is None:
            message = (
                "🛡 ATI SAFETY\n\n"
                "Trade skipped.\n"
                "USDT Futures balance could not be verified."
            )

            send_telegram(message)
            return False, None

        balance = Decimal(balance)

        print(f"USDT Futures balance: {balance}")

        if balance < MIN_USDT_REQUIRED:

            message = (
                "🛡 ATI SAFETY\n\n"
                "Trade skipped.\n\n"
                f"💵 Futures USDT: {balance:.8f}\n"
                f"⚠️ Required: {MIN_USDT_REQUIRED:.2f} USDT"
            )

            send_telegram(message)

            return False, balance

        message = (
            "✅ ATI BALANCE CHECK\n\n"
            f"💵 Futures USDT: {balance:.8f}\n"
            f"✅ Required: {MIN_USDT_REQUIRED:.2f} USDT\n\n"
            "🟢 Balance sufficient.\n"
            "Trade execution may continue."
        )

        send_telegram(message)

        return True, balance

    except Exception as e:

        print("BALANCE CHECK ERROR:", repr(e))

        message = (
            "🛡 ATI SAFETY\n\n"
            "Trade skipped.\n\n"
            "❌ Futures USDT balance could not be verified.\n"
            "No order was sent."
        )

        send_telegram(message)

        return False, None


def main():

    print("=" * 50)
    print("ATI BOT - FUTURES BALANCE CHECK")
    print("=" * 50)

    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets missing.")

    if not TABDEAL_API_KEY:
        print("TABDEAL_API_KEY missing.")

    if not TABDEAL_API_SECRET:
        print("TABDEAL_API_SECRET missing.")

    # ---------------------------------
    # مهم:
    # قبل از معامله واقعی موجودی چک می‌شود.
    # ---------------------------------

    allowed, balance = check_usdt_balance()

    if not allowed:

        print("TRADE BLOCKED")
        print("No real order will be sent.")

        return

    print()
    print("BALANCE OK")
    print(f"Available Futures USDT: {balance}")
    print()
    print("Trade execution can continue.")
    print()
    print("IMPORTANT:")
    print("Signal/order logic is intentionally not executed")
    print("until the Futures balance endpoint is confirmed.")


if __name__ == "__main__":
    main()
