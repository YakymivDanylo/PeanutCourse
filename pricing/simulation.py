from dataclasses import dataclass
from typing import Optional
import time
import logging

from eth_abi import encode
from eth_utils import function_signature_to_4byte_selector
from web3 import Web3
from web3.types import TxParams
from core.types import Address
from pricing.amm import UniswapV2Pair
from pricing.routing import Route

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    success: bool
    amount_out: int
    gas_used: int
    error: Optional[str]
    logs: list


class ForkSimulator:
    """
    Simulates transactions on a local fork.
    """

    ROUTER_ADDRESS = Address("0x1b02dA8Cb0d097eB8D57A175b88c7D8b47997506")
    WETH_ADDRESS = Address("0x82aF49447D8a07e3bd95BD0d56f35241523fBab1")
    USDT_ADDRESS = Address("0xdAC17F958D2ee523a2206206994597C13D831ec7")
    USDC_ADDRESS = Address("0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8")

    WHALES = {
        "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8": Address(
            "0x47c031236e197323a311907186930732dd4c659e"
        ),
        "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1": Address(
            "0xba12222222228d8ba445958a75a0704d566bf2c8"
        ),
    }

    SWAP_EXACT_TOKENS_FOR_TOKENS = function_signature_to_4byte_selector(
        "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)"
    )

    ERC20_APPROVE = function_signature_to_4byte_selector("approve(address,uint256)")
    WETH_DEPOSIT = function_signature_to_4byte_selector("deposit()")

    def __init__(self, fork_url: str):
        self.w3 = Web3(Web3.HTTPProvider(fork_url))
        if not self.w3.is_connected():
            raise ConnectionError("RPC connection failed")

    def _impersonate(self, address: Address):
        """Unlock account on Anvil"""
        self.w3.provider.make_request("anvil_impersonateAccount", [address.checksum])

    def _stop_impersonating(self, address: Address):
        self.w3.provider.make_request(
            "anvil_stopImpersonatingAccount", [address.checksum]
        )

    def _set_balance_ether(self, address: Address, amount_eth: float = 10.0):
        """Give an account eth for gas"""
        wei = int(amount_eth * 10**18)
        self.w3.provider.make_request("anvil_setBalance", [address.checksum, hex(wei)])

    def _approve(self, token: Address, spender: Address, sender: Address):
        """
        Force approve token for spender. Handles USDT reset-to-zero quirk.
        """
        max_amount = 2**256 - 1

        data_zero = self.ERC20_APPROVE + encode(
            ["address", "uint256"], [spender.checksum, 0]
        )
        tx_zero = {
            "from": sender.checksum,
            "to": token.checksum,
            "data": data_zero,
            "gas": 60000,
            "gasPrice": self.w3.eth.gas_price,
            "value": 0,
        }

        try:
            self.w3.eth.send_transaction(tx_zero)
        except Exception:
            pass

        data_max = self.ERC20_APPROVE + encode(
            ["address", "uint256"], [spender.checksum, max_amount]
        )
        tx_max = {
            "from": sender.checksum,
            "to": token.checksum,
            "data": data_max,
            "gas": 100000,
            "gasPrice": self.w3.eth.gas_price,
            "value": 0,
        }

        try:
            tx_hash = self.w3.eth.send_transaction(tx_max)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            if receipt.status != 1:
                logger.warning(f"Approve transaction reverted for {token.checksum}")
        except Exception as e:
            logger.error(f"Approve failed: {e}")

    def _wrap_eth(self, amount: int, sender: Address):
        """Deposit ETH to get WETH."""
        safe_amount = amount * 10
        tx: TxParams = {
            "from": sender.checksum,
            "to": self.WETH_ADDRESS.checksum,
            "data": self.WETH_DEPOSIT,
            "gas": 100000,
            "gasPrice": self.w3.eth.gas_price,
            "value": safe_amount,
        }
        try:
            tx_hash = self.w3.eth.send_transaction(tx)
            self.w3.eth.wait_for_transaction_receipt(tx_hash)
        except Exception as e:
            logger.error(f"Wrap ETH failed: {e}")

    def simulate_swap(
        self, router: Address, swap_params: dict, sender: Address
    ) -> SimulationResult:
        """Simulate a swap and return detailed results."""
        self._impersonate(sender)

        tx: TxParams = {
            "from": sender.checksum,
            "to": router.checksum,
            "data": swap_params.get("data", b""),
            "value": swap_params.get("value", 0),
            "gas": 500_000,
            "gasPrice": self.w3.eth.gas_price,
        }

        try:
            gas_estimate = self.w3.eth.estimate_gas(tx)
            tx["gas"] = int(gas_estimate * 1.2)

            tx_hash = self.w3.eth.send_transaction(tx)
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
            raw_return = self.w3.eth.call(tx)

            try:
                if raw_return.startswith(b"x0"):
                    raw_return = raw_return[2:]
                amount_out_sim = 0
                if len(raw_return) >= 32:
                    amount_out_sim = int.from_bytes(raw_return[-32:], byteorder="big")
            except Exception:
                amount_out_sim = 0

            return SimulationResult(
                success=receipt["status"] == 1,
                amount_out=amount_out_sim,
                gas_used=receipt["gasUsed"],
                error=None,
                logs=receipt["logs"],
            )
        except Exception as e:
            return SimulationResult(
                success=False,
                amount_out=0,
                gas_used=0,
                error=str(e),
                logs=[],
            )
        finally:
            self._stop_impersonating(sender)

    def simulate_route(
        self, route: Route, amount_in: int, sender: Address
    ) -> SimulationResult:
        """Simulate a multi-hop route."""
        path_addresses = [t.checksum for t in route.path]
        deadline = int(time.time()) + 3600
        token_in = route.path[0]

        sim_sender = sender

        if token_in.checksum in self.WHALES:
            sim_sender = self.WHALES[token_in.checksum]

        try:
            self._impersonate(sim_sender)
            self._set_balance_ether(sim_sender, 10.0)

            if token_in.checksum == self.WETH_ADDRESS.checksum:
                self._wrap_eth(amount_in, sim_sender)

            self._approve(token_in, self.ROUTER_ADDRESS, sim_sender)

        except Exception as e:
            logger.error(f"Simulation setup failed: {e}")
            self._stop_impersonating(sim_sender)
            return SimulationResult(False, 0, 0, f"Setup Error: {e}", [])

        encoded_args = encode(
            ["uint256", "uint256", "address[]", "address", "uint256"],
            [amount_in, 0, path_addresses, sim_sender.checksum, deadline],
        )

        data = self.SWAP_EXACT_TOKENS_FOR_TOKENS + encoded_args
        swap_params = {"data": data, "value": 0}

        return self.simulate_swap(
            router=self.ROUTER_ADDRESS, swap_params=swap_params, sender=sim_sender
        )

    def compare_simulation_vs_calculation(
        self,
        pair: UniswapV2Pair,
        amount_in: int,
        token_in: Address,
        sender_override: Optional[Address] = None,
    ) -> dict:
        calculated_out = pair.get_amount_out(amount_in, token_in)
        token_out = pair.token1 if token_in == pair.token0 else pair.token0
        route = Route([pair], [token_in, token_out])

        sender = (
            sender_override
            if sender_override
            else Address("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")
        )

        sim_result = self.simulate_route(route, amount_in, sender)

        return {
            "calculated": calculated_out,
            "simulated": sim_result.amount_out,
            "difference": abs(calculated_out - sim_result.amount_out),
            "match": calculated_out == sim_result.amount_out,
            "gas": sim_result.gas_used,
            "error": sim_result.error,
        }
