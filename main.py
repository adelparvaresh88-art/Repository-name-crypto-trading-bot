print("BUY SCORE:", buy_score, "/5")
print("SELL SCORE:", sell_score, "/5")

message = None

if buy_score >= MIN_SCORE:

    stop_loss = current * (1 - SL_PERCENT / 100)
    take_profit = current * (1 + TP_PERCENT / 100)

    message = (
        "🟢 STRONG BUY - PAPER\n\n"
        f"💰 Entry: ${current:,.2f}\n"
        f"🛑 Stop Loss: ${stop_loss:,.2f}\n"
        f"🎯 Take Profit: ${take_profit:,.2f}\n\n"
        f"🟢 BUY SCORE: {buy_score}/5\n"
        f"🔴 SELL SCORE: {sell_score}/5\n\n"
        f"3-Candle: {change3:.3f}%\n"
        f"5-Candle: {change5:.3f}%\n"
        f"10-Candle: {change10:.3f}%\n\n"
        "🧪 PAPER TRADING\n"
        "🚫 REAL TRADING: OFF\n\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

elif sell_score >= MIN_SCORE:

    stop_loss = current * (1 + SL_PERCENT / 100)
    take_profit = current * (1 - TP_PERCENT / 100)

    message = (
        "🔴 STRONG SELL - PAPER\n\n"
        f"💰 Entry: ${current:,.2f}\n"
        f"🛑 Stop Loss: ${stop_loss:,.2f}\n"
        f"🎯 Take Profit: ${take_profit:,.2f}\n\n"
        f"🟢 BUY SCORE: {buy_score}/5\n"
        f"🔴 SELL SCORE: {sell_score}/5\n\n"
        f"3-Candle: {change3:.3f}%\n"
        f"5-Candle: {change5:.3f}%\n"
        f"10-Candle: {change10:.3f}%\n\n"
        "🧪 PAPER TRADING\n"
        "🚫 REAL TRADING: OFF\n\n"
        f"⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

if message:
    send_telegram(message)
    print("PAPER SIGNAL SENT")
else:
    print("HOLD - NOTHING SENT")

print("================================")
print("FINISHED")
print("================================")
