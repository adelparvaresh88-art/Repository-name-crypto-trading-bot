        stop_loss = price * (1 - SL_PERCENT / 100)
        take_profit = price * (1 + TP_PERCENT / 100)

        message = (
            "🟢 BUY SIGNAL\n\n"
            f"₿ BTC: ${price:,.2f}\n"
            f"⏱ Timeframe: {INTERVAL}\n\n"
            f"🎯 Entry: ${price:,.2f}\n"
            f"🛑 Stop Loss: ${stop_loss:,.2f}\n"
            f"💰 Take Profit: ${take_profit:,.2f}\n\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING: DISABLED"
        )

        send_telegram(message)

    elif signal == "SELL":

        stop_loss = price * (1 + SL_PERCENT / 100)
        take_profit = price * (1 - TP_PERCENT / 100)

        message = (
            "🔴 SELL SIGNAL\n\n"
            f"₿ BTC: ${price:,.2f}\n"
            f"⏱ Timeframe: {INTERVAL}\n\n"
            f"🎯 Entry: ${price:,.2f}\n"
            f"🛑 Stop Loss: ${stop_loss:,.2f}\n"
            f"💰 Take Profit: ${take_profit:,.2f}\n\n"
            "📊 MODE: PAPER / TEST\n"
            "🚫 REAL TRADING: DISABLED"
        )

        send_telegram(message)

    else:

        print("HOLD - no Telegram signal sent")

except Exception as e:

    print("BOT ERROR:", e)

    send_telegram(
        "⚠️ ATI BOT ERROR\n\n"
        f"{e}\n\n"
        "📊 MODE: PAPER / TEST"
    )


print("FINISHED")
