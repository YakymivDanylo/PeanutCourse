from dataclasses import dataclass
from typing import Optional
import time
import logging
from core.wallet import WalletManager
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

    SWAP_EXACT_TOKENS_FOR_TOKENS = function_signature_to_4byte_selector(
        "swapExactTokensForTokens(uint256,uint256,address[],address,uint256)"
    )

    ERC20_APPROVE = function_signature_to_4byte_selector("approve(address,uint256)")
    ERC20_ALLOWANCE = function_signature_to_4byte_selector("allowance(address,address)")
    ERC20_BALANCE_OF = function_signature_to_4byte_selector("balanceOf(address)")
    WETH_DEPOSIT = function_signature_to_4byte_selector("deposit()")

    def __init__(self, fork_url: str, wallet: Optional[WalletManager] = None):
        self.w3 = Web3(Web3.HTTPProvider(fork_url))
        self.wallet = wallet
        if not self.w3.is_connected():
            logger.warning(f"Forksimulation failed to connect to {fork_url}")

    def _impersonate(self, address: Address):
        """Unlock account on Anvil"""
        if self.wallet and address.checksum == self.wallet.address:
            return
        try:
            self.w3.provider.make_request(
                "anvil_impersonateAccount", [address.checksum]
            )
        except Exception:
            pass

    def _stop_impersonating(self, address: Address):
        if self.wallet and address.checksum == self.wallet.address:
            return
        try:
            self.w3.provider.make_request(
                "anvil_stopImpersonatingAccount", [address.checksum]
            )
        except Exception:
            pass

    def _get_allowance(self, token: Address, owner: Address, spender: Address) -> int:
        """Read allowance via eth_call"""
        data = self.ERC20_ALLOWANCE + encode(
            ["address", "address"], [owner.checksum, spender.checksum]
        )
        tx = {"to": token.checksum, "data": data}
        try:
            res = self.w3.eth.call(tx)
            return int.from_bytes(res, "big") if res else 0
        except Exception:
            return 0

    def _get_balance(self, token: Address, owner: Address) -> int:
        """Read balance via eth_call"""
        data = self.ERC20_BALANCE_OF + encode(["address"], [owner.checksum])
        tx = {"to": token.checksum, "data": data}
        try:
            res = self.w3.eth.call(tx)
            return int.from_bytes(res, "big") if res else 0
        except Exception:
            return 0

    def _send_signed(self, tx_params: dict):
        """Sign and send a transaction using the local wallet."""
        if not self.wallet:
            raise ValueError("No wallet available for signing")

        tx_params.pop("from", None)

        if "nonce" not in tx_params:
            tx_params["nonce"] = self.w3.eth.get_transaction_count(self.wallet.address)

        if "chainId" not in tx_params:
            tx_params["chainId"] = self.w3.eth.chain_id

        if "gasPrice" not in tx_params:
            try:
                base_gas_price = self.w3.eth.gas_price
                tx_params["gasPrice"] = int(base_gas_price * 1.35)
            except Exception:
                pass

        try:
            signed_tx = self.wallet.sign_transaction(tx_params)
        except Exception as e:
            logger.error(f"Signing error: {e}. Params: {tx_params}")
            raise e

        try:
            if hasattr(signed_tx, "rawTransaction"):
                raw_tx = signed_tx.rawTransaction
            else:
                raw_tx = signed_tx[0]

            raw_tx_hex = raw_tx.hex() if hasattr(raw_tx, "hex") else raw_tx

            tx_hash = self.w3.eth.send_raw_transaction(raw_tx_hex)

            logger.info(f"Sent signed tx: {tx_hash.hex()}")
            return self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
        except Exception as e:
            logger.error(
                f"Send Raw Tx failed: {e} "
                f"| SignedTx Type: {type(signed_tx)} | Dir: {dir(signed_tx)}"
            )
            raise e

    def _set_balance_ether(self, address: Address, amount_eth: float = 10.0):
        """Give an account eth for gas"""
        wei = int(amount_eth * 10**18)
        self.w3.provider.make_request("anvil_setBalance", [address.checksum, hex(wei)])

    def _approve(self, token: Address, spender: Address, sender: Address):
        """Approve token. Uses signing if sender is our wallet."""
        if self.wallet and sender.checksum == self.wallet.address:
            current_allowance = self._get_allowance(token, sender, spender)
            if current_allowance >= 2**255:
                return

            logger.info(f"Approving {token.checksum} for router (Local Sign)...")
            max_amount = 2**256 - 1
            data = self.ERC20_APPROVE + encode(
                ["address", "uint256"], [spender.checksum, max_amount]
            )

            tx = {
                "to": token.checksum,
                "data": data,
                "gas": 200000,
            }
            try:
                self._send_signed(tx)
            except Exception as e:
                logger.error(f"Signed Approve failed: {e}")
            return

        try:
            max_amount = 2**256 - 1
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

            self.w3.eth.send_transaction(tx_max)
        except Exception as e:
            logger.error(f"Fork Approve failed: {e}")

    def _wrap_eth(self, amount: int, sender: Address):
        """Deposit ETH. Uses signing if sender is our wallet."""
        if self.wallet and sender.checksum == self.wallet.address:
            try:
                weth_bal = self._get_balance(self.WETH_ADDRESS, sender)
                if weth_bal >= amount:
                    return

                needed = amount - weth_bal
                if needed <= 0:
                    return

                logger.info(f"Wrapping {needed / 1e18:.4f} ETH (Local Sign)...")

                tx = {
                    "to": self.WETH_ADDRESS.checksum,
                    "data": self.WETH_DEPOSIT,
                    "gas": 200000,
                    "value": int(needed * 1.01),
                }
                self._send_signed(tx)
                logger.info("✅ Wrap successful")
            except Exception as e:
                logger.error(f"Signed Wrap failed: {e}")
            return

        try:
            tx = {
                "from": sender.checksum,
                "to": self.WETH_ADDRESS.checksum,
                "data": self.WETH_DEPOSIT,
                "gas": 100000,
                "gasPrice": self.w3.eth.gas_price,
                "value": amount * 10,
            }
            self.w3.eth.send_transaction(tx)
        except Exception as e:
            logger.error(f"Fork Wrap failed: {e}")

    def simulate_swap(
        self, router: Address, swap_params: dict, sender: Address
    ) -> SimulationResult:
        """Simulate a swap. Uses eth_call for safety on real nets."""
        self._impersonate(sender)

        gas_price = int(self.w3.eth.gas_price * 1.2)

        tx: TxParams = {
            "from": sender.checksum,
            "to": router.checksum,
            "data": swap_params.get("data", b""),
            "value": swap_params.get("value", 0),
            "gas": 500_000,
            "gasPrice": gas_price,
        }

        try:
            try:
                gas_estimate = self.w3.eth.estimate_gas(tx)
                tx["gas"] = int(gas_estimate * 1.2)
            except Exception as e:
                return SimulationResult(False, 0, 0, f"Estimate failed: {e}", [])

            if self.wallet and sender.checksum == self.wallet.address:
                receipt_status = 1
                gas_used = gas_estimate
                logs = []
            else:
                tx_hash = self.w3.eth.send_transaction(tx)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash)
                receipt_status = receipt["status"]
                gas_used = receipt["gasUsed"]
                logs = receipt["logs"]

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
                success=receipt_status == 1,
                amount_out=amount_out_sim,
                gas_used=gas_used,
                error=None,
                logs=logs,
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

        if self.wallet and sim_sender.checksum == self.wallet.address:
            try:
                balance = self._get_balance(token_in, sim_sender)

                if balance < amount_in:
                    decimals = (
                        6
                        if token_in.checksum
                        in [
                            "0xFF970A61A04b1cA14834A43f5dE4533eBDDB5CC8",
                            "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                        ]
                        else 18
                    )

                    human_bal = balance / (10**decimals)
                    human_req = amount_in / (10**decimals)

                    msg = (
                        f"Skipped: Insufficient balance of"
                        f" {token_in.checksum}. Have: {human_bal:.4f}, "
                        f"Need: {human_req:.4f}"
                    )

                    return SimulationResult(
                        success=False, amount_out=0, gas_used=0, error=msg, logs=[]
                    )
            except Exception as e:
                logger.warning(f"Balance check failed: {e}")

        try:
            self._impersonate(sim_sender)

            if not (self.wallet and sim_sender.checksum == self.wallet.address):
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
