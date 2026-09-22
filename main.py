import os
from decimal import Decimal

import requests

# =========================
# ATI BOT - BALANCE TEST
# =========================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TABDEAL_API_KEY = os.getenv("TABDEAL_API_KEY")
TABDEAL_API_SECRET = os.getenv("TABDEAL_API_SECRET")

MIN_USDT_REQUIRED = Decimal("2")


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        print("Telegram secrets missing")
        print(message)
        return False

    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=15
        )

        print("Telegram status:", response.status_code)
        print("Telegram response:", response.text)

        return response.ok

    except Exception as e:
        print("Telegram error:", repr(e))
        return False


def get_futures_balance():

    if not TABDEAL_API_KEY:
        raise RuntimeError("TABDEAL_API_KEY is missing")

    if not TABDEAL_API_SECRET:
        raise RuntimeError("TABDEAL_API_SECRET is missing")

    try:
        from tabdeal.future import Future

        client = Future(
            TABDEAL_API_KEY,
            TABDEAL_API_SECRET
        )

        # Official Futures balance method
        balances = client.balance()

        print("RAW FUTURES BALANCE:")
        print(balances)

        if not isinstance(balances, list):
            raise RuntimeError(
                f"Unexpected balance response: {balances}"
            )

        for item in balances:

            if not isinstance(item, dict):
                continue

            asset = str(
                item.get("asset", "")
            ).upper()

            if asset != "USDT":
                continue

            value = item.get(
                "availableBalance",
                item.get(
                    "balance",
                    "0"
                )
            )

            return Decimal(str(value))

        raise RuntimeError(
            "USDT was not found in Futures balance"
        )

    except Exception as e:
        raise RuntimeError(
            f"Futures balance API error: {e}"
        )


def main():

    print("=" * 50)
    print("ATI FUTURES BALANCE TEST")
    print("=" * 50)

    # -------------------------
    # Check credentials
    # -------------------------

    if not BOT_TOKEN:
        print("ERROR: TELEGRAM_BOT_TOKEN missing")
        return

    if not CHAT_ID:
        print("ERROR: TELEGRAM_CHAT_ID missing")
        return

    if not TABDEAL_API_KEY:
        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Trade skipped.\n"
            "❌ TABDEAL_API_KEY is missing."
        )
        return

    if not TABDEAL_API_SECRET:
        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Trade skipped.\n"
            "❌ TABDEAL_API_SECRET is missing."
        )
        return

    # -------------------------
    # Read Futures balance
    # -------------------------

    try:

        balance = get_futures_balance()

        print(
            f"USDT Futures balance: {balance}"
        )

    except Exception as e:

        print("BALANCE ERROR:", repr(e))

        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Trade skipped.\n\n"
            "❌ Futures USDT balance could not be verified.\n"
            "No order was sent.\n\n"
            f"Error: {e}"
        )

        return

    # -------------------------
    # Balance result
    # -------------------------

    if balance < MIN_USDT_REQUIRED:

        send_telegram(
            "🛡 ATI SAFETY\n\n"
            "Trade skipped.\n\n"
            f"💵 Futures USDT: {balance:.8f}\n"
            f"⚠️ Required: {MIN_USDT_REQUIRED:.2f} USDT\n\n"
            "❌ Insufficient balance."
        )

        print("TRADE BLOCKED")
        return

    # -------------------------
    # SUCCESS
    # -------------------------

    send_telegram(
        "✅ ATI BALANCE CHECK\n\n"
        "₿ BTC/USDT Futures\n"
        f"💵 USDT Balance: {balance:.8f}\n"
        f"✅ Minimum Required: {MIN_USDT_REQUIRED:.2f} USDT\n\n"
        "🟢 BALANCE OK\n"
        "✅ Futures account verified.\n\n"
        "🛡 TEST MODE\n"
        "No real order was sent."
    )

    print("BALANCE OK")
    print("NO REAL ORDER SENT")


if __name__ == "__main__":
    main()
