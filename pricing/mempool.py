import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Optional, Any

import websockets
from eth_abi import decode
import json
from web3 import Web3, HTTPProvider

from core.types import Address

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("Mempool")


@dataclass
class ParsedSwap:
    """Parsed swap transaction from mempool."""

    tx_hash: str
    router: str
    dex: str
    method: str
    token_in: Optional[Address]
    token_out: Optional[Address]
    amount_in: int
    min_amount_out: int
    deadline: int
    sender: Address
    gas_price: int
    value: int

    @property
    def slippage_tolerance(self) -> Decimal:
        """Calculate implied slippage tolerance."""
        return Decimal(0)


class MempoolMonitor:
    """
    Monitors pending transactions for swap activity.
    """

    SWAP_SELECTORS = {
        "0x38ed1739": (
            "UniswapV2",
            "swapExactTokensForTokens",
            ["uint256", "uint256", "address[]", "address", "uint256"],
        ),
        "0x8803dbee": (
            "UniswapV2",
            "swapTokensForExactTokens",
            ["uint256", "uint256", "address[]", "address", "uint256"],
        ),
        "0x7ff36ab5": (
            "UniswapV2",
            "swapExactETHForTokens",
            ["uint256", "address[]", "address", "uint256"],
        ),
        "0x4a25d94a": (
            "UniswapV2",
            "swapTokensForExactETH",
            ["uint256", "uint256", "address[]", "address", "uint256"],
        ),
        "0x18cbafe5": (
            "UniswapV2",
            "swapExactTokensForETH",
            ["uint256", "uint256", "address[]", "address", "uint256"],
        ),
        "0xfb3bdb41": (
            "UniswapV2",
            "swapETHForExactTokens",
            ["uint256", "address[]", "address", "uint256"],
        ),
    }

    def __init__(
        self, ws_url: str, http_rpc_url: str, callback: Callable[[ParsedSwap], None]
    ):
        """
        callback receives ParsedSwap objects for each detected swap.
        """
        self.ws_url = ws_url  # for subscription
        self.http_rpc = Web3(
            HTTPProvider(http_rpc_url)
        )  # for getting details of the transaction
        self.callback = callback
        self._running = False

    async def start(self):
        """Start monitoring pending transactions."""
        self._running = True
        logger.info(f"Connecting to Mempool: {self.ws_url}")

        while self._running:
            try:
                async with websockets.connect(self.ws_url, max_size=None) as ws:
                    # Subscribe
                    sub_request = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "eth_subscribe",
                        "params": ["newPendingTransactions"],
                    }
                    await ws.send(json.dumps(sub_request))
                    resp = await ws.recv()
                    logger.info(f"Subscription response: {resp}")

                    async for message in ws:
                        if not self._running:
                            break

                        try:
                            data = json.loads(message)

                            if "params" in data and "result" in data["params"]:
                                tx_hash = data["params"]["result"]
                                asyncio.create_task(self._process_tx(tx_hash))
                        except Exception as e:
                            logger.error(f"Error parsing WS message: {e}")

            except (websockets.ConnectionClosed, OSError) as e:
                logger.error(f"Connection lost: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                await asyncio.sleep(5)

    async def _process_tx(self, tx_hash: str):
        """Fetch full tx data and try to parse it"""
        try:
            tx = await asyncio.to_thread(self._fetch_tx_safe, tx_hash)

            if not tx:
                return

            parsed = self.parse_transaction(tx)
            if parsed:
                if asyncio.iscoroutinefunction(self.callback):
                    await self.callback(parsed)
                else:
                    self.callback(parsed)

        except Exception as e:
            logger.error(f"Failed to process tx {tx_hash}: {e}")

    def _fetch_tx_safe(self, tx_hash: str):
        """Helper to fetch tx data"""
        try:
            return self.http_rpc.eth.get_transaction(tx_hash)
        except Exception:
            return None

    def decode_swap_params(self, selector: str, data: bytes) -> dict[str, Any]:
        """
        Decode swap parameters from calldata bytes.
        Returns a dictionary of parameters.
        """
        if selector not in self.SWAP_SELECTORS:
            raise ValueError(f"Unknown selector: {selector}")

        dex, method, types = self.SWAP_SELECTORS[selector]

        try:
            decoded = decode(types, data)
        except Exception as e:
            raise ValueError(f"Decoding failed: {e}")

        params = {}

        if method == "swapExactTokensForTokens":
            params = {
                "amountIn": decoded[0],
                "amountOutMin": decoded[1],
                "path": decoded[2],
                "to": decoded[3],
                "deadline": decoded[4],
            }
        elif method == "swapExactETHForTokens":
            params = {
                "amountOutMin": decoded[0],
                "path": decoded[1],
                "to": decoded[2],
                "deadline": decoded[3],
            }
        elif method == "swapExactTokensForETH":
            params = {
                "amountIn": decoded[0],
                "amountOutMin": decoded[1],
                "path": decoded[2],
                "to": decoded[3],
                "deadline": decoded[4],
            }
        elif method == "swapETHForExactTokens":
            params = {
                "amountOut": decoded[0],
                "path": decoded[1],
                "to": decoded[2],
                "deadline": decoded[3],
            }
        elif method == "swapTokensForExactETH":
            params = {
                "amountOut": decoded[0],
                "amountInMax": decoded[1],
                "path": decoded[2],
                "to": decoded[3],
                "deadline": decoded[4],
            }
        elif method == "swapTokensForExactTokens":
            params = {
                "amountOut": decoded[0],
                "amountInMax": decoded[1],
                "path": decoded[2],
                "to": decoded[3],
                "deadline": decoded[4],
            }

        return params

    def parse_transaction(self, tx: Any) -> Optional[ParsedSwap]:
        """Parse Web3 Transaction object."""
        input_data = tx.get("input", "0x")
        if hasattr(input_data, "hex"):
            input_data = input_data.hex()

        if not input_data.startswith("0x"):
            input_data = "0x" + input_data

        if len(input_data) < 10:
            return None

        selector = input_data[:10]
        if selector not in self.SWAP_SELECTORS:
            return None

        dex_name, method_name, _ = self.SWAP_SELECTORS[selector]

        try:
            data_bytes = bytes.fromhex(input_data[10:])
            params = self.decode_swap_params(selector, data_bytes)

            token_in, token_out = None, None
            if "path" in params and len(params["path"]) >= 2:
                token_in = Address(params["path"][0])
                token_out = Address(params["path"][-1])

            amount_in = params.get("amountIn", 0)
            min_amount_out = params.get("amountOutMin", 0)

            if method_name in ["swapExactETHForTokens", "swapETHForExactTokens"]:
                amount_in = tx.get("value", 0)

            if "amountInMax" in params:
                amount_in = params["amountInMax"]

            deadline = params.get("deadline", 0)

            sender = tx.get("from")
            gas_price = tx.get("gasPrice", 0)
            value = tx.get("value", 0)

            tx_hash = tx.get("hash")
            if hasattr(tx_hash, "hex"):
                tx_hash = tx_hash.hex()

            return ParsedSwap(
                tx_hash=tx_hash,
                router=tx.get("to"),
                dex=dex_name,
                method=method_name,
                token_in=token_in,
                token_out=token_out,
                amount_in=amount_in,
                min_amount_out=min_amount_out,
                deadline=deadline,
                sender=Address(sender),
                gas_price=gas_price,
                value=value,
            )

        except Exception as e:
            logger.warning(f"Decoding failed for {tx.get('hash', '')}: {e}")
            return None
