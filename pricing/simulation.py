from dataclasses import dataclass
from typing import Optional
import time

from eth_abi import encode
from eth_utils import function_signature_to_4byte_selector
from web3 import Web3
from web3.types import TxParams
from core.types import Address
from pricing.amm import UniswapV2Pair
from pricing.routing import Route


@dataclass
class SimulationResult:
    success: bool
    amount_out: int
    gas_used: int
    error: Optional[str]
    logs: list  # Decoded events


class ForkSimulator:
    """
    Simulates transactions on a local fork.
    """

    ROUTER_ADDRESS = Address("0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D")

    SWAP_EXACT_TOKENS_FOR_TOKENS = function_signature_to_4byte_selector(
        "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)"
    )

    def __init__(self, fork_url: str):
        """
        fork_url: Local Anvil/Hardhat fork RPC
        """
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

    def simulate_swap(
        self, router: Address, swap_params: dict, sender: Address
    ) -> SimulationResult:
        """
        Simulate a swap and return detailed results.
        """
        self._impersonate(sender)
        self._set_balance_ether(sender)

        tx: TxParams = {
            "from": sender.checksum,
            "to": router.checksum,
            "data": swap_params.get("data", b""),
            "value": swap_params.get("value", 0),
            "gas": 500_000,  # Default high gas
            "gasPrice": self.w3.eth.gas_price,
        }

        try:
            gas_estimate = self.w3.eth.estimate_gas(tx)
            tx["gas"] = int(gas_estimate * 1.2)

            # As its local fork than we can send transaction
            # without signing it if impersonated
            tx_hash = self.w3.eth.send_transaction(tx)

            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)

            raw_return = self.w3.eth.call(tx)

            # Try decode amounts[] if standard swap
            try:
                if raw_return.startswith(b"x0"):
                    raw_return = raw_return[2:]
                # last uint256 in the array is usually amountOut

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
        """
        Simulate a multi-hop route.
        """
        path_addresses = [t.checksum for t in route.path]
        deadline = int(time.time()) + 3600

        # We set amountOutMin to 0 to ensure it doesn't revert
        # due to slippage during sim
        encoded_args = encode(
            ["uint256", "uint256", "address[]", "address", "uint256"],
            [amount_in, 0, path_addresses, sender.checksum, deadline],
        )

        data = self.SWAP_EXACT_TOKENS_FOR_TOKENS + encoded_args

        swap_params = {
            "data": data,
            "value": 0,
        }

        return self.simulate_swap(
            router=self.ROUTER_ADDRESS, swap_params=swap_params, sender=sender
        )

    def compare_simulation_vs_calculation(
        self,
        pair: UniswapV2Pair,
        amount_in: int,
        token_in: Address,
        sender_override: Optional[Address] = None,
    ) -> dict:
        """
        Compare our AMM math vs actual fork simulation.
        Useful for validation.
        """
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
