
    # 4. Breakout
    recent_high = max(highs[-11:-1])
    recent_low = min(lows[-11:-1])

    if current > recent_high:
        buy_score += 1
    elif current < recent_low:
        sell_score += 1

    # 5. Move strength
    move_percent = abs((current - previous) / previous) * 100

    if move_percent >= MIN_MOVE_PERCENT:
        if current > previous:
            buy_score += 1
        elif current < previous:
            sell_score += 1

    if buy_score >= MIN_SCORE and buy_score > sell_score:
        signal = "BUY"
    elif sell_score >= MIN_SCORE and sell_score > buy_score:
        signal = "SELL"
    else:
        signal = "HOLD"

    return (
        signal,
        current,
        buy_score,
        sell_score,
        move_percent
    )


def main():
    print("================================")
    print("      ⚡ ATI CRYPTO BOT V12")
    print("================================")

    print("📡 Getting BTC 5m candles...")

    candles = get_data()

    print("✅ Candle data received")
    print("📊 Candles:", len(candles))

    signal, current, buy_score, sell_score, move_percent = calculate_signal(
        candles
    )

    print("================================")
    print("₿ BTC:", round(current, 2))
    print("📊 BUY SCORE:", buy_score, "/5")
    print("📉 SELL SCORE:", sell_score, "/5")
    print("📈 MOVE:", round(move_percent, 3), "%")
    print("🚦 SIGNAL:", signal)
    print("================================")

    if signal == "HOLD":
        print("⚪ No strong signal. Telegram message not sent.")
        return

    if signal == "BUY":
        stop_loss = current * (1 - SL_PERCENT / 100)
        take_profit = current * (1 + TP_PERCENT / 100)

    else:
        stop_loss = current * (1 + SL_PERCENT / 100)
        take_profit = current * (1 - TP_PERCENT / 100)

    message = (
        "⚡ ATI CRYPTO BOT V12\n\n"
        "₿ BTC: $" + f"{current:,.2f}" + "\n"
        "⏱ Timeframe: 5m\n"
        "✅ CLOSED CANDLE CONFIRMED\n\n"
        + ("🟢 SIGNAL: BUY\n" if signal == "BUY"
           else "🔴 SIGNAL: SELL\n")
        + f"📈 BUY SCORE: {buy_score}/5\n"
        + f"📉 SELL SCORE: {sell_score}/5\n"
        + f"📊 MOVE: {move_percent:.3f}%\n\n"
        + f"💰 Entry: ${current:,.2f}\n"
        + f"🛑 SL: ${stop_loss:,.2f}\n"
        + f"🎯 TP: ${take_profit:,.2f}\n\n"
        + "🧪 MODE: PAPER / TEST\n"
        + "🚫 REAL TRADING: DISABLED"
    )

    print("📨 Sending Telegram message...")

    result = send_telegram(message)

    print("✅ Telegram response received")
    print(result)
    print("✅ SIGNAL SENT SUCCESSFULLY")


if __name__ == "__main__":
    try:
        main()

    except Exception as error:
        print("================================")
        print("❌ ATI BOT ERROR")
        print("================================")
        print(str(error))
        print("================================")
        traceback.print_exc()
        print("================================")
        raise
