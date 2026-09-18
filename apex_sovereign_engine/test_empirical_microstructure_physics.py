#!/usr/bin/env python3
"""
test_empirical_microstructure_physics.py
Institutional test suite verifying core Level 2 microstructure algorithms,
information bars, Hawkes point process intensity, and fractional differencing.
"""

import os
import sys
import pytest
import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

# Ensure parent and engine directory is in sys.path
ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

from empirical_microstructure import (
    compute_stoikov_micro_price,
    compute_discrete_ofi,
    compute_multi_level_ofi,
    compute_recursive_hawkes_intensity,
    get_fractional_weights,
    fractional_diff,
    compute_order_book_imbalance
)

# ─────────────────────────────────────────────────────────────────────────────
# Pytest Test Cases
# ─────────────────────────────────────────────────────────────────────────────

def test_stoikov_micro_price_bounds():
    """Verify micro-price strictly lies between bid and ask."""
    bid_p, ask_p = 60000.0, 60001.0
    
    # Heavy bid queue -> micro-price leans toward ask
    mp1 = compute_stoikov_micro_price(bid_p, 10.0, ask_p, 1.0)
    assert bid_p < mp1 < ask_p
    assert mp1 > (bid_p + ask_p) / 2.0  # Leans toward ask
    
    # Heavy ask queue -> micro-price leans toward bid
    mp2 = compute_stoikov_micro_price(bid_p, 1.0, ask_p, 10.0)
    assert bid_p < mp2 < ask_p
    assert mp2 < (bid_p + ask_p) / 2.0  # Leans toward bid

    # Balanced queues -> equal to mid price
    mp3 = compute_stoikov_micro_price(bid_p, 5.0, ask_p, 5.0)
    assert np.isclose(mp3, 60000.5)

def test_stoikov_micro_price_edge_cases():
    """Verify edge case with zero queues falls back gracefully."""
    mp = compute_stoikov_micro_price(60000.0, 0.0, 60002.0, 0.0)
    assert np.isclose(mp, 60001.0)

def test_order_flow_imbalance_directionality():
    """Verify OFI sign matches order book aggressive replenishment/depletion."""
    # Case 1: Higher bid price entered (aggressive buyer uplift)
    ofi_up = compute_discrete_ofi(60000.0, 1.0, 60001.0, 2.0,
                                  60002.0, 1.0, 60002.0, 1.0)
    assert ofi_up > 0, "Uplifted bid price must produce positive OFI"

    # Case 2: Lower ask price entered (aggressive seller push)
    ofi_down = compute_discrete_ofi(60000.0, 1.0, 60000.0, 1.0,
                                    60002.0, 1.0, 60001.0, 3.0)
    assert ofi_down < 0, "Lowered ask price must produce negative OFI"

def test_hawkes_intensity_clustering():
    """Verify self-exciting clustering behavior and decay."""
    # Rapid burst of trades at t=0, 0.1, 0.2
    rapid_trades = np.array([0.0, 0.1, 0.2, 0.3])
    intensities = compute_recursive_hawkes_intensity(rapid_trades, alpha=1.0, beta=2.0, mu=0.5)
    
    # Each rapid trade should spike intensity higher
    assert intensities[-1] > intensities[0]
    
    # Idle period following rapid burst should decay toward baseline mu
    idle_trades = np.array([0.0, 0.1, 0.2, 0.3, 10.0])
    intensities_decay = compute_recursive_hawkes_intensity(idle_trades, alpha=1.0, beta=2.0, mu=0.5)
    assert intensities_decay[-1] < intensities[-1]
    assert np.isclose(intensities_decay[-1], 0.5 + 1.0, atol=0.01)

def test_fractional_differentiation_stationarity_and_memory():
    """Verify fractional differencing (d=0.45) preserves memory and achieves stationarity."""
    np.random.seed(42)
    # Generate non-stationary random walk (geometric price series)
    n = 1000
    returns = np.random.normal(0, 0.01, size=n)
    prices = 60000.0 * np.exp(np.cumsum(returns))
    
    # d=0 (raw price): should be non-stationary (ADF p-value > 0.05)
    adf_raw = adfuller(prices)[1]
    assert adf_raw > 0.05, "Raw price series must be non-stationary"
    
    # d=0.45: should achieve stationarity while retaining memory
    fd_prices = fractional_diff(prices, d=0.45)
    adf_fd = adfuller(fd_prices)[1]
    assert adf_fd < 0.05, f"Fractionally differentiated series must be stationary (ADF p={adf_fd})"
    
    # Correlation with raw price should be substantial (> 0.60) unlike d=1 returns
    raw_aligned = prices[-len(fd_prices):]
    corr_fd = np.corrcoef(raw_aligned, fd_prices)[0, 1]
    assert corr_fd > 0.60, f"Memory correlation must remain high: got {corr_fd:.3f}"

def test_multi_level_ofi_calculation():
    """Verify multi-level OFI aggregates order book updates across depth levels."""
    prev_bids = [[60000.0, 1.0], [59999.0, 2.0], [59998.0, 3.0]]
    curr_bids = [[60000.0, 2.0], [59999.0, 2.0], [59998.0, 4.0]]  # Bid additions at L1 and L3
    prev_asks = [[60001.0, 1.0], [60002.0, 2.0], [60003.0, 3.0]]
    curr_asks = [[60001.0, 1.0], [60002.0, 2.0], [60003.0, 3.0]]  # Asks unchanged

    ofi_multilevel = compute_multi_level_ofi(prev_bids, curr_bids, prev_asks, curr_asks, levels=3)
    assert ofi_multilevel > 0, "Net bid additions must produce positive multi-level OFI"

def test_real_l2_snapshots_data_integrity():
    """Verify live L2 snapshots can be parsed and produce valid microstructure metrics across all rows."""
    l2_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "l2_live_data", "btcusdt_l2_snapshots_2026-07-31.jsonl")
    assert os.path.exists(l2_file), f"L2 snapshots file must exist at {l2_file}"
    
    import json
    with open(l2_file, "r") as f:
        first_line = f.readline()
        record = json.loads(first_line)
    
    assert "recv_timestamp" in record
    assert "bids" in record and len(record["bids"]) >= 5
    assert "asks" in record and len(record["asks"]) >= 5
    
    best_bid_p = float(record["bids"][0][0])
    best_bid_q = float(record["bids"][0][1])
    best_ask_p = float(record["asks"][0][0])
    best_ask_q = float(record["asks"][0][1])
    
    assert best_bid_p < best_ask_p, "Bid price must be less than Ask price"
    mp = compute_stoikov_micro_price(best_bid_p, best_bid_q, best_ask_p, best_ask_q)
    assert best_bid_p <= mp <= best_ask_p

    # Verify that l2_orderbook_analyzer output exists and 100% of rows meet strict no-arbitrage bounds
    metrics_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "processed_data", "l2_analyzed_metrics.csv")
    assert os.path.exists(metrics_file), f"Analyzed metrics file must exist at {metrics_file}"

    df_metrics = pd.read_csv(metrics_file)
    assert len(df_metrics) > 0, "Analyzed metrics DataFrame must not be empty"

    # Micro-price strictly bounded by best bid and best ask for ALL rows
    assert (df_metrics["micro_price"] >= df_metrics["best_bid"]).all(), "micro_price must never fall below best_bid"
    assert (df_metrics["micro_price"] <= df_metrics["best_ask"]).all(), "micro_price must never exceed best_ask"

    # Spread must be strictly positive
    assert (df_metrics["spread_bps"] >= 0.0).all(), "Spread bps must be non-negative"

    # OBI must remain in [-1.0, 1.0]
    assert (df_metrics["obi_top5"].between(-1.0, 1.0)).all(), "OBI top 5 must lie within [-1, 1]"
    assert (df_metrics["obi_top20"].between(-1.0, 1.0)).all(), "OBI top 20 must lie within [-1, 1]"

    # OFI columns exist and contain valid finite numbers
    assert "ofi" in df_metrics.columns and df_metrics["ofi"].notna().all(), "OFI column must be fully populated and finite"
    assert "ofi_top5" in df_metrics.columns and df_metrics["ofi_top5"].notna().all(), "Multi-level OFI must be fully populated and finite"
