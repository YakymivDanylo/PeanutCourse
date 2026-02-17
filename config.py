import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    PRODUCTION = os.getenv("PRODUCTION", "false").lower() == "true"

    DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

    if PRODUCTION:
        CHAIN_ID = 42161
        RPC_URL = os.getenv("ARBITRUM_RPC_URL", "https://arb1.arbitrum.io/rpc")

        CHAIN_WS_URL = os.getenv(
            "ARBITRUM_WS_URL", "wss://arbitrum-one-rpc.publicnode.com"
        )

        WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
        USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        ROUTER = "0x4752ba5dbc23f44d87826276bf6fd6b1c372ad24"
        POOL_ADDRESS = ""

        BINANCE_BASE_URL = "https://api.binance.com"
        BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

        CEX_FEE_BPS = 10.0
        DEX_FEE_BPS = 30.0
        GAS_COST_USD = 0.10

    else:
        CHAIN_ID = 31337
        RPC_URL = os.getenv("RPC_URL", "http://127.0.0.1:8545")

        CHAIN_WS_URL = os.getenv("WS_URL", "ws://127.0.0.1:8545")

        WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
        USDC = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
        ROUTER = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
        POOL_ADDRESS = "0x0d4a11d5EEaaC28EC3F61d100daF4d40471f1852"

        BINANCE_BASE_URL = "https://testnet.binance.vision"
        BINANCE_WS_URL = "wss://testnet.binance.vision/ws"

        CEX_FEE_BPS = 0.0
        DEX_FEE_BPS = 30.0
        GAS_COST_USD = 0.0
