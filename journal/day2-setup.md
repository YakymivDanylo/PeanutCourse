## Day 2 — 2026-02-18

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
- Successful launch in DRY_RUN and PRODUCTION mode

### Problems Encountered
- Wrap ETH failed: eth_sendTransaction error. Reason: Attempt to send transaction via public RPC without local signature.
- Problems with maxFeePerGas (less than base fee) on Arbitrum.
- Market stability, which did not allow finding an arbitrage opportunity

### Changes Made
- Switching to Local Sign (local signing of transactions with a private key).

### Tomorrow's Plan
- Find another pair that is more volatile and has a higher chance of arbitrage