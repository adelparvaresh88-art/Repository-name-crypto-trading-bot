def calculate_strong_signal(candles):
    """
    ATI CRYPTO BOT - STRONG PRICE ACTION ENGINE
    5M
    No EMA
    No RSI
    No indicators
    """

    if len(candles) < 12:
        return "HOLD", 0, 0

    # آخرین کندل بسته‌شده
    c = candles[-1]

    o = float(c["open"])
    h = float(c["high"])
    l = float(c["low"])
    close = float(c["close"])

    if o <= 0 or h <= 0 or l <= 0 or close <= 0:
        return "HOLD", 0, 0

    candle_range = h - l

    if candle_range <= 0:
        return "HOLD", 0, 0

    body = abs(close - o)

    upper_wick = h - max(o, close)
    lower_wick = min(o, close) - l

    body_ratio = body / candle_range
    upper_ratio = upper_wick / candle_range
    lower_ratio = lower_wick / candle_range

    # ------------------------------------------------
    # 1. جهت کندل
    # ------------------------------------------------

    buy_score = 0
    sell_score = 0

    if close > o:
        buy_score += 1

    if close < o:
        sell_score += 1

    # ------------------------------------------------
    # 2. قدرت کندل
    # ------------------------------------------------

    if body_ratio >= 0.55:
        if close > o:
            buy_score += 1
        else:
            sell_score += 1

    # ------------------------------------------------
    # 3. موقعیت بسته شدن
    # ------------------------------------------------

    close_position = (close - l) / candle_range

    if close_position >= 0.70:
        buy_score += 1

    if close_position <= 0.30:
        sell_score += 1

    # ------------------------------------------------
    # 4. مومنتوم سه کندل
    # ------------------------------------------------

    c1 = candles[-2]
    c2 = candles[-3]

    c1_open = float(c1["open"])
    c1_close = float(c1["close"])

    c2_open = float(c2["open"])
    c2_close = float(c2["close"])

    if close > o and c1_close > c1_open and c2_close > c2_open:
        buy_score += 1

    if close < o and c1_close < c1_open and c2_close < c2_open:
        sell_score += 1

    # ------------------------------------------------
    # 5. شکست سقف / کف اخیر
    # ------------------------------------------------

    recent_high = max(
        float(x["high"])
        for x in candles[-8:-1]
    )

    recent_low = min(
        float(x["low"])
        for x in candles[-8:-1]
    )

    if close > recent_high:
        buy_score += 1

    if close < recent_low:
        sell_score += 1

    # ------------------------------------------------
    # 6. ساختار حرکت
    # ------------------------------------------------

    previous_close = float(candles[-2]["close"])
    previous_previous_close = float(candles[-3]["close"])

    if close > previous_close > previous_previous_close:
        buy_score += 1

    if close < previous_close < previous_previous_close:
        sell_score += 1

    # ------------------------------------------------
    # 7. فیلتر سایه
    # ------------------------------------------------

    # BUY با سایه بالایی شدید ممنوع
    if upper_ratio <= 0.30 and close > o:
        buy_score += 1

    # SELL با سایه پایینی شدید ممنوع
    if lower_ratio <= 0.30 and close < o:
        sell_score += 1

    # ------------------------------------------------
    # 8. جلوگیری از ورود در سقف / کف
    # ------------------------------------------------

    range_high = max(
        float(x["high"])
        for x in candles[-12:-1]
    )

    range_low = min(
        float(x["low"])
        for x in candles[-12:-1]
    )

    total_range = range_high - range_low

    if total_range > 0:

        position = (close - range_low) / total_range

        # نزدیک سقف → BUY ممنوع
        if position < 0.80:
            if close > o:
                buy_score += 1

        # نزدیک کف → SELL ممنوع
        if position > 0.20:
            if close < o:
                sell_score += 1

    # ------------------------------------------------
    # FINAL STRONG FILTER
    # ------------------------------------------------

    # حداکثر امتیاز تقریبی 8
    # فقط سیگنال خیلی قوی

    if buy_score >= 6 and buy_score > sell_score:
        return "BUY", buy_score, sell_score

    if sell_score >= 6 and sell_score > buy_score:
        return "SELL", buy_score, sell_score

    return "HOLD", buy_score, sell_score
