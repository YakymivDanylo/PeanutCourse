# tests/test_scorer.py
import pytest
import time
from unittest.mock import Mock
from strategy.scorer import SignalScorer
from strategy.signal import Signal


@pytest.fixture
def scorer():
    return SignalScorer()


@pytest.fixture
def mock_signal():
    """Creates a mock Signal object with default valid values."""
    sig = Mock(spec=Signal)
    sig.pair = "ETH/USDC"
    sig.spread_bps = 50
    sig.timestamp = time.time()
    sig.expiry = sig.timestamp + 60
    sig.score = 50
    sig.age_seconds.return_value = 0
    return sig


def test_score_high_spread(scorer, mock_signal):
    """100 bps spread scores high."""
    # Setup
    mock_signal.spread_bps = 100
    inventory_state = []

    score = scorer.score(mock_signal, inventory_state)

    # With 100 bps:
    # Spread Score = 100 (Weight 0.4) -> 40
    # Liquidity = 80 (Weight 0.2) -> 16
    # Inventory = 60 (Weight 0.2) -> 12
    # History = 50 (Weight 0.2) -> 10
    # Total expected ~ 78
    assert score >= 78.0


def test_score_inventory_penalty(scorer, mock_signal):
    """RED skew gives penalty."""
    mock_signal.pair = "BTC/USDT"

    # Define two states: one with RED skew, one without
    bad_inventory = [{"token": "BTC", "status": "RED"}]
    good_inventory = [{"token": "BTC", "status": "GREEN"}]

    score_bad = scorer.score(mock_signal, bad_inventory)
    score_good = scorer.score(mock_signal, good_inventory)

    # Penalty for RED is 20 vs 60 for normal.
    # Weighted difference: (60 - 20) * 0.2 = 8 points
    assert score_bad < score_good
    assert score_good - score_bad == 8.0


def test_decay_over_time(scorer, mock_signal):
    """Older signals have lower score."""
    mock_signal.score = 100
    mock_signal.timestamp = 1000
    mock_signal.expiry = 2000

    # Case 1: Fresh signal (0 seconds old)
    mock_signal.age_seconds.return_value = 0
    score_fresh = scorer.apply_decay(mock_signal)

    # Case 2: Aged signal (500 seconds old, 50% of TTL)
    mock_signal.age_seconds.return_value = 500
    score_aged = scorer.apply_decay(mock_signal)

    assert score_fresh == 100
    assert score_aged < score_fresh
    assert score_aged == 75.0
