import os
import sys
import time
import hmac
import hashlib
from urllib.parse import urlencode

import requests


BASE_URL = "https://api1.tabdeal.org"

API_KEY = (
    os.getenv("TABDEAL_API_KEY", "").strip()
    or os.getenv("TABDIL_API_KEY", "").strip()
)

API_SECRET = (
    os.getenv("TABDEAL_API_SECRET", "").strip()
    or os.getenv("TABDIL_API_SECRET", "").strip()
)

TIMEOUT = 15
RECV_WINDOW = 10000


def signed_get(path, extra_params=None):
    params = dict(extra_params or {})
    params["recvWindow"] = RECV_WINDOW
    params["timestamp"] = int(time.time() * 1000)

    query = urlencode(params)

    signature = hmac.new(
        API_SECRET.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    url = (
        BASE_URL
        + path
        + "?"
        + query
        + "&signature="
        + signature
    )

    response = requests.get(
        url,
        headers={"X-MBX-APIKEY": API_KEY},
        timeout=TIMEOUT,
    )

    try:
        data = response.json()
    except ValueError:
        data = {"message": response.text[:300]}

    if not response.ok:
        raise RuntimeError(
            f"HTTP {response.status_code}: {str(data)[:700]}"
        )

    if isinstance(data, dict) and data.get("code", 0) not in (0, "0"):
        raise RuntimeError(str(data)[:700])

    return data


def main():
    print("ATI FUTURES V23 API CHECK")
    print("=" * 40)

    if not API_KEY or not API_SECRET:
        print("ERROR: Futures API credentials are missing.")
        print(
            "Required secrets: TABDEAL_API_KEY and "
            "TABDEAL_API_SECRET"
        )
        sys.exit(1)

    print("API credentials: Present")
    print("Real orders: DISABLED")
    print("Order endpoint: NOT CALLED")
    print()

    # 1. Check Futures account.
    try:
        account = signed_get("/r/fapi/v3/account")

        if not isinstance(account, dict):
            raise RuntimeError("Unexpected account response format.")

        print("ACCOUNT: OK")
        print("Can trade:", account.get("canTrade", "unknown"))

        assets = account.get("assets", [])
        usdt = next(
            (
                item for item in assets
                if isinstance(item, dict)
                and item.get("asset") == "USDT"
            ),
            None,
        )

        if usdt:
            print(
                "USDT wallet balance:",
                usdt.get("walletBalance", "unknown"),
            )
            print(
                "USDT available balance:",
                usdt.get("availableBalance", "unknown"),
            )
        else:
            print("USDT balance: Not found in account response")

        positions = account.get("positions", [])
        open_positions = []

        if isinstance(positions, list):
            for position in positions:
                if not isinstance(position, dict):
                    continue

                try:
                    amount = float(position.get("positionAmt", 0))
                except (TypeError, ValueError):
                    amount = 0

                if amount != 0:
                    open_positions.append(position)

        print("Nonzero positions:", len(open_positions))

        for position in open_positions[:10]:
            print(
                "POSITION:",
                position.get("symbol"),
                "amount=",
                position.get("positionAmt"),
                "entry=",
                position.get("entryPrice"),
                "leverage=",
                position.get("leverage"),
            )

    except Exception as exc:
        print("ACCOUNT CHECK FAILED:", str(exc)[:800])
        sys.exit(1)

    print()

    # 2. Check Futures USDT balance endpoint.
    try:
        balances = signed_get("/r/fapi/v3/balance")

        if not isinstance(balances, list):
            raise RuntimeError("Unexpected balance response format.")

        usdt = next(
            (
                item for item in balances
                if isinstance(item, dict)
                and item.get("asset") == "USDT"
            ),
            None,
        )

        print("BALANCE ENDPOINT: OK")

        if usdt:
            print(
                "USDT available:",
                usdt.get("availableBalance", "unknown"),
            )
            print(
                "USDT wallet:",
                usdt.get("walletBalance", "unknown"),
            )
        else:
            print("USDT entry was not returned.")

    except Exception as exc:
        print("BALANCE CHECK FAILED:", str(exc)[:800])
        sys.exit(1)

    print()

    # 3. Read current BTCUSDT leverage. Do not change it.
    try:
        leverage = signed_get(
            "/r/fapi/v1/leverage",
            {"symbol": "BTCUSDT"},
        )

        if not isinstance(leverage, dict):
            raise RuntimeError("Unexpected leverage response format.")

        print("LEVERAGE ENDPOINT: OK")
        print("Symbol:", leverage.get("symbol", "BTCUSDT"))
        print("Current leverage:", leverage.get("leverage", "unknown"))

    except Exception as exc:
        print("LEVERAGE CHECK FAILED:", str(exc)[:800])
        sys.exit(1)

    print()
    print("=" * 40)
    print("API CHECK COMPLETED")
    print("No order was submitted.")
    print("No leverage setting was changed.")
    print("No funds were transferred.")


if __name__ == "__main__":
    main()
