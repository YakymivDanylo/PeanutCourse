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

        ARB = "0x912CE59144191C1204E64559FE8253a0e49E6548"
        WETH = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
        USDC = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        ROUTER = "0xc873fEcbd354f5A56E00E710B90EF4201db2448d"
        POOL_ADDRESS = "0x011f31D20C8778c8Beb1093b73E3A5690Ee6271b"

        BINANCE_BASE_URL = "https://api.binance.com"
        BINANCE_WS_URL = "wss://stream.binance.com:9443/ws"

        CEX_FEE_BPS = 10.0
        DEX_FEE_BPS = 30.0
        GAS_COST_USD = 0.10

        MIN_NOTIONAL = 5.0
        ARB_LOT_SIZE_STEP = 0.1
        ARB_PRICE_TICK = 0.0001

    else:
        CHAIN_ID = 31337
        RPC_URL = os.getenv("RPC_URL", "http://127.0.0.1:8545")

        CHAIN_WS_URL = os.getenv("WS_URL", "ws://127.0.0.1:8545")

        ARB = "0x912CE59144191C1204E64559FE8253a0e49E6548"
        WETH = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
        USDC = "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8"
        ROUTER = "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
        POOL_ADDRESS = "0x905dfCD5649217c42684f23958568e533C711Aa3"

        BINANCE_BASE_URL = "https://testnet.binance.vision"
        BINANCE_WS_URL = "wss://testnet.binance.vision/ws"

        CEX_FEE_BPS = 0.0
        DEX_FEE_BPS = 30.0
        GAS_COST_USD = 0.0

        MIN_NOTIONAL = 5.0
        ARB_LOT_SIZE_STEP = 0.1
        ARB_PRICE_TICK = 0.0001

    def get_token_address(self, symbol: str) -> str:
        """Returns the token address based on the symbol (ARB, USDC)."""
        symbol = symbol.upper()
        if symbol == "ARB":
            return self.ARB
        if symbol == "USDC":
            return self.USDC

        raise ValueError(f"Address for token {symbol} is not defined in config")

    def get_token_decimals(self, symbol: str) -> int:
        """
        Returns the number of decimal places.
        On Arbitrum/Mainnet USDC has 6 decimal places, WETH has 18.
        """
        symbol = symbol.upper()
        if symbol in ["USDC", "USDT"]:
            return 6
        return 18
