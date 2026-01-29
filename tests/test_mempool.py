import pytest
from eth_abi import encode
from pricing.mempool import MempoolMonitor


@pytest.mark.asyncio
async def test_mempool_parsing_logic():
    """Test clear parsing without network."""
    monitor = MempoolMonitor("wss://fake", "https://fake", None)

    # Mock transaction data (swapExactETHForTokens)
    # Selector: 0x7ff36ab5
    # Data: encoded (amountOutMin, path, to, deadline)

    fake_tx = {
        "hash": b"\x00" * 32,
        "to": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
        "from": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        "value": 10**18,
        "gasPrice": 20 * 10**9,
        "input": "0x",
    }

    # Empty input -> None
    assert monitor.parse_transaction(fake_tx) is None

    # Unknown selector -> None
    fake_tx["input"] = "0xa9059cbb" + "00" * 64  # ERC20 Transfer
    assert monitor.parse_transaction(fake_tx) is None

    # Valid selector but garbage data -> None (Exception caught)
    fake_tx["input"] = "0x7ff36ab5" + "1234"
    assert monitor.parse_transaction(fake_tx) is None


@pytest.mark.asyncio
async def test_mempool_parsing_valid_tx():
    """Positive test: test the correctness of the parsed data."""
    monitor = MempoolMonitor("wss://fake", "https://fake", None)

    # WETH -> USDC
    token_in_addr = "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2"
    token_out_addr = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"

    amount_in = 10 * 10**18  # 10 ETH
    amount_out_min = 20000 * 10**6  # 20,000 USDC
    deadline = 1234567890
    path = [token_in_addr, token_out_addr]
    to = "0x1234567890123456789012345678901234567890"

    # Selector: swapExactTokensForTokens: 0x38ed1739
    # Signature: (uint256 amountIn, uint256 amountOutMin,
    # address[] path, address to, uint256 deadline)

    encoded_args = encode(
        ["uint256", "uint256", "address[]", "address", "uint256"],
        [amount_in, amount_out_min, path, to, deadline],
    )

    input_data = "0x38ed1739" + encoded_args.hex()

    fake_tx = {
        "hash": "0x" + "1" * 64,
        "to": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",  # UniV2 Router
        "from": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        "value": 0,
        "gasPrice": 50 * 10**9,  # 50 gwei
        "input": input_data,
    }

    parsed = monitor.parse_transaction(fake_tx)

    assert parsed is not None, "Парсер повернув None для валідної транзакції"

    assert parsed.dex == "UniswapV2"
    assert parsed.method == "swapExactTokensForTokens"

    assert parsed.amount_in == amount_in
    assert parsed.min_amount_out == amount_out_min
    assert parsed.deadline == deadline
    assert parsed.gas_price == 50 * 10**9

    assert parsed.token_in == token_in_addr
    assert parsed.token_out == token_out_addr
    assert parsed.sender == "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"

    print(
        f"\nParsed: {parsed.amount_in} "
        f"{parsed.token_in.value[:6]} -> {parsed.min_amount_out}"
        f" {parsed.token_out.value[:6]}"
    )
