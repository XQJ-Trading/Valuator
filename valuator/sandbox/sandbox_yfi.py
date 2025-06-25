import yfinance as yf

"""
sandbox_yfi.py

Example usage of yfinance to fetch and print company info and recent prices.
"""
import yfinance as yf


def main():
    md_file = open("output.md", "w", encoding="utf-8")
    # List of ticker symbols to fetch
    tickers = ["WDAY"]

    for symbol in tickers:
        ticker = yf.Ticker(symbol)

        # Print header
        md_file.write(f"=== {symbol} ===\n")

        # Print basic info
        info = ticker.info
        md_file.write(f"Name: {info.get('longName', 'N/A')}\n")
        md_file.write(f"Sector: {info.get('sector', 'N/A')}\n")
        md_file.write(f"Industry: {info.get('industry', 'N/A')}\n")
        md_file.write(f"Market Cap: {info.get('marketCap', 'N/A')}\n")
        md_file.write(f"Current Price: {info.get('currentPrice', 'N/A')}\n")

        # Print last 5 days of closing prices
        hist = ticker.history(period="5d")
        md_file.write("Last 5 days closing prices:\n")
        for date, row in hist.iterrows():
            md_file.write(f"  {date.date()}: {row['Close']}\n")
        md_file.write("\n")

        # Print financial statements
        md_file.write("Annual Income Statement:\n")
        md_file.write(ticker.financials.to_markdown(floatfmt=",.0f") + "\n")
        md_file.write("\nBalance Sheet:\n")
        md_file.write(ticker.balance_sheet.to_markdown(floatfmt=",.0f") + "\n")
        md_file.write("\nCashflow Statement:\n")
        md_file.write(ticker.cashflow.to_markdown(floatfmt=",.0f") + "\n")
        md_file.write("\n")
    md_file.close()


if __name__ == "__main__":
    main()
