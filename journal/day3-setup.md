## Day 3 — 2026-02-19

### Numbers
- Starting capital: $100  
- Ending capital: $100
- PnL: $0
- Trades: 0 (0 wins, 0 losses)
- Win rate: 0%
- Best trade: _
- Worst trade: _
- Fees paid: $0.00

### What Happened
- Due to market fluctuations, the bot saw chances for arbitrage, but for the size of the deal in 0.001 ETH - spread in 61 bps, too small. The profit calculated by the bot was `-$0.0965`, when for the transaction to be executed the minimum profit should be `$0.1`, for the profitability of a deal of this size the minimum spread should be 250 bps. Therefore, there were no trades on the ETH/USDC pair.
- Also, when I used the ARB/USDC pair, the spread in the market almost reached the minimum value for the trade, but it did not increase further.
- The bot attempted to generate signals for the ARB/USDC pair, but encountered routing and price fetching errors (`No route found`).
- Implemented a daily summary task scheduled for 18:00 UTC.

### Problems Encountered
- I had to update my IP in the whitelist on Binance.
- Post-trade balance verification crashed because it tried to access a dictionary like an object (`'dict' object has no attribute 'ETH'`).

### Lesson Learned
- Public RPC nodes often break connections (Connection lost 1013), which prevents stable operation.
- Validating dictionary vs object attributes is crucial in Python, especially when handling balance structures across different exchange responses.

### Changes Made
- Switching to Local Sign (local signing of transactions with a private key).
- Added a daily summary task to send a report to Telegram.

### Tomorrow's Plan
- Make it possible to disable and enable the bot via Telegram.