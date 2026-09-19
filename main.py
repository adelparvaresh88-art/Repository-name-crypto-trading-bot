def calculate_signal(candles):

    if len(candles) < 7:
        return "HOLD", None

    current = candles[-1]
    previous = candles[-6:-1]

    previous_high = max(c["high"] for c in previous)
    previous_low = min(c["low"] for c in previous)

    open_price = current["open"]
    close = current["close"]
    high = current["high"]
    low = current["low"]

    candle_range = high - low

    if candle_range <= 0:
        return "HOLD", current

    body = abs(close - open_price)
    body_strength = body / candle_range

    print("CURRENT CLOSE:", close)
    print("5-CANDLE HIGH:", previous_high)
    print("5-CANDLE LOW:", previous_low)
    print("BODY STRENGTH:", round(body_strength, 3))

    # 🟢 BUY
    # کندل صعودی + عبور از سقف قبلی
    if (
        close > open_price
        and close > previous_high
        and body_strength >= 0.30
    ):
        return "BUY", current

    # 🟢 BUY سریع‌تر:
    # اگر کندل صعودی قوی باشد و نزدیک سقف قبلی بسته شود
    if (
        close > open_price
        and body_strength >= 0.60
        and close >= previous_high * 0.998
    ):
        return "BUY", current

    # 🔴 SELL
    # کندل نزولی + شکست کف قبلی
    if (
        close < open_price
        and close < previous_low
        and body_strength >= 0.30
    ):
        return "SELL", current

    # 🔴 SELL سریع‌تر:
    # اگر کندل نزولی قوی باشد و نزدیک کف قبلی بسته شود
    if (
        close < open_price
        and body_strength >= 0.60
        and close <= previous_low * 1.002
    ):
        return "SELL", current

    return "HOLD", current
