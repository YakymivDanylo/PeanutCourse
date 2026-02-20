### 1. Configuration & Setup

- Chain: Arbitrum One (L2)

- DEX: Uniswap V2

- CEX: Binance

- Pair: ETH/USDC, ARB/USDC

- Risk Parameters:Used max_trade_usd=25.0 and max_daily_loss=20.0 according to safety.py security requirements. This allows you to preserve 80% of your capital even in the event of a critical failure.

2. Trading Results

- Total trades: 0  
 
- Total PnL: $0.00
 
- Starting capital: $100.00 / Ending capital: $100.00
 
- Best trade: None.
 
- Fees paid: None.

3. Risk Management in Practice

- Manual Kill Switch: It worked perfectly. Several times the bot stopped instantly after detecting a trigger file.

- Circuit Breaker: There were no critical conditions for its activation.

4. What I Learned

- Surprise: Moving from mocks to the real network revealed the complexity of nonce and gas management (EIP-1559) on L2.

- With $1000 I would be more likely to get an arbitrage opportunity because trades of $2-5 are almost impossible to find an arbitrage opportunity

- Confidence: Most confident in the signal search logic; least confident in the stability of public RPC nodes, which frequently dropped connections (Connection lost 1013).

5. Technical Challenges

-   Gas Accuracy: Arbitrum gas pricing differs from Mainnet due to L1/L2 fee components.

- Latency: CEX prices update much faster than DEX, which creates the risk of signal "slippage".
