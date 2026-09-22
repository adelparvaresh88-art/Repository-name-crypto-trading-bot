def get_futures_balance():
    """
    Read real USDT balance from Tabdeal Futures.
    """

    if not TABDEAL_API_KEY or not TABDEAL_API_SECRET:
        raise RuntimeError(
            "TABDEAL_API_KEY or TABDEAL_API_SECRET is missing"
        )

    from tabdeal.future import Future

    client = Future(
        TABDEAL_API_KEY,
        TABDEAL_API_SECRET
    )

    balances = client.balance()

    print("RAW FUTURES BALANCE:")
    print(balances)

    if not isinstance(balances, list):
        raise RuntimeError(
            "Unexpected Futures balance response"
        )

    for item in balances:

        if not isinstance(item, dict):
            continue

        asset = str(
            item.get("asset", "")
        ).upper()

        if asset != "USDT":
            continue

        # Futures available balance
        value = item.get(
            "availableBalance",
            item.get(
                "available",
                item.get(
                    "balance",
                    "0"
                )
            )
        )

        from decimal import Decimal

        usdt_balance = Decimal(str(value))

        print(
            f"USDT Futures available balance: "
            f"{usdt_balance}"
        )

        return usdt_balance

    raise RuntimeError(
        "USDT balance was not found in Futures account"
    )
