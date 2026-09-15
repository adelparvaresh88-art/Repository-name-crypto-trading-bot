        f"Price: {current_price}\n"
        f"Signal: {signal}\n"
        f"Mode: PAPER / TEST\n"
        f"Trading: DISABLED"
    )

    print(message)

    send_telegram(message)


if __name__ == "__main__":
    main()
