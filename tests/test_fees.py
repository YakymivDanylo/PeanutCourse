from strategy.fees import FeeStructure


def test_fee_structure_defaults():
    fees = FeeStructure()
    assert fees.cex_taker_bps == 10.0
    assert fees.dex_swap_bps == 30.0
    assert fees.gas_cost_usd == 5.0


def test_total_fee_bps_calculation():
    fees = FeeStructure(cex_taker_bps=10, dex_swap_bps=30, gas_cost_usd=5.0)

    trade_value = 10_000.0
    expected_bps = 10.0 + 30.0 + (5.0 / trade_value * 10_000)

    assert fees.total_fee_bps(trade_value) == expected_bps
    assert fees.total_fee_bps(trade_value) == 45.0


def test_breakeven_spread():
    fees = FeeStructure(gas_cost_usd=10.0)
    trade_value = 1000.0

    assert fees.breakeven_spread_bps(trade_value) == 140.0


def test_net_profit_usd():
    fees = FeeStructure(cex_taker_bps=10, dex_swap_bps=30, gas_cost_usd=5.0)
    trade_value = 5000.0

    spread_bps = 100.0

    expected_net = 50.0 - 25.0

    calculated_net = fees.net_profit_usd(spread_bps, trade_value)
    assert calculated_net == expected_net


def test_zero_trade_value():
    fees = FeeStructure()
    assert fees.total_fee_bps(0) == 0.0
