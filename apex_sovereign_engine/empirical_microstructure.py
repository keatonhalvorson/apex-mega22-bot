#!/usr/bin/env python3
"""
empirical_microstructure.py
Institutional quantitative module for Level 2 market microstructure,
order flow imbalance (OFI), Stoikov micro-price, recursive Hawkes point processes,
and fractional differencing for high-frequency cryptocurrency spot trading.
"""

import numpy as np
import pandas as pd
from typing import List, Tuple, Union, Optional


def compute_stoikov_micro_price(
    best_bid_p: float,
    best_bid_q: float,
    best_ask_p: float,
    best_ask_q: float
) -> float:
    """
    Computes Stoikov volume-weighted micro-price (Stoikov 2018):
    P_micro = P_bid * (Q_ask / (Q_bid + Q_ask)) + P_ask * (Q_bid / (Q_bid + Q_ask))
    
    Guarantees strict no-arbitrage bounds:
    min(P_bid, P_ask) <= P_micro <= max(P_bid, P_ask)
    """
    best_bid_p = float(best_bid_p)
    best_bid_q = max(0.0, float(best_bid_q))
    best_ask_p = float(best_ask_p)
    best_ask_q = max(0.0, float(best_ask_q))

    total_q = best_bid_q + best_ask_q
    if total_q <= 0.0 or not np.isfinite(total_q):
        return (best_bid_p + best_ask_p) / 2.0

    # Convex combination of bid and ask
    mp = (best_bid_p * best_ask_q + best_ask_p * best_bid_q) / total_q

    # Strict clamping against numerical floating-point inaccuracies
    lower_bound = min(best_bid_p, best_ask_p)
    upper_bound = max(best_bid_p, best_ask_p)
    return float(np.clip(mp, lower_bound, upper_bound))


def compute_discrete_ofi(
    prev_bid_p: float,
    prev_bid_q: float,
    curr_bid_p: float,
    curr_bid_q: float,
    prev_ask_p: float,
    prev_ask_q: float,
    curr_ask_p: float,
    curr_ask_q: float
) -> float:
    """
    Computes single-level discrete Order Flow Imbalance (Cont, Kukanov & Stoikov 2014):
    OFI_t = Delta_Bid_t - Delta_Ask_t
    """
    # Bid contribution
    if curr_bid_p > prev_bid_p:
        delta_bid = curr_bid_q
    elif curr_bid_p == prev_bid_p:
        delta_bid = curr_bid_q - prev_bid_q
    else:
        delta_bid = -prev_bid_q

    # Ask contribution
    if curr_ask_p < prev_ask_p:
        delta_ask = curr_ask_q
    elif curr_ask_p == prev_ask_p:
        delta_ask = curr_ask_q - prev_ask_q
    else:
        delta_ask = -prev_ask_q

    return float(delta_bid - delta_ask)


def compute_multi_level_ofi(
    prev_bids: List[List[Union[float, str]]],
    curr_bids: List[List[Union[float, str]]],
    prev_asks: List[List[Union[float, str]]],
    curr_asks: List[List[Union[float, str]]],
    levels: int = 5,
    decay_factor: float = 0.5
) -> float:
    """
    Computes multi-level depth-weighted Order Flow Imbalance across top L levels.
    Weights decay geometrically or harmonically with book depth.
    """
    total_ofi = 0.0
    weight_sum = 0.0

    max_levels = min(levels, len(prev_bids), len(curr_bids), len(prev_asks), len(curr_asks))
    if max_levels == 0:
        return 0.0

    for i in range(max_levels):
        w = np.exp(-decay_factor * i)
        weight_sum += w

        p_bp, p_bq = float(prev_bids[i][0]), float(prev_bids[i][1])
        c_bp, c_bq = float(curr_bids[i][0]), float(curr_bids[i][1])
        p_ap, p_aq = float(prev_asks[i][0]), float(prev_asks[i][1])
        c_ap, c_aq = float(curr_asks[i][0]), float(curr_asks[i][1])

        ofi_level = compute_discrete_ofi(p_bp, p_bq, c_bp, c_bq, p_ap, p_aq, c_ap, c_aq)
        total_ofi += w * ofi_level

    return float(total_ofi / (weight_sum + 1e-8))


def compute_recursive_hawkes_intensity(
    trade_timestamps: Union[np.ndarray, List[float]],
    alpha: float = 0.5,
    beta: float = 1.0,
    mu: float = 0.1
) -> np.ndarray:
    """
    Computes recursive exponential Hawkes self-exciting point process intensity:
    lambda(t_i) = mu + (lambda(t_{i-1}) - mu) * exp(-beta * delta_t) + alpha
    """
    ts = np.asarray(trade_timestamps, dtype=float)
    n = len(ts)
    if n == 0:
        return np.array([])

    intensities = np.zeros(n, dtype=float)
    intensities[0] = mu + alpha

    for i in range(1, n):
        dt = ts[i] - ts[i-1]
        if dt < 0:
            raise ValueError("Timestamps must be monotonically non-decreasing.")
        intensities[i] = mu + (intensities[i-1] - mu) * np.exp(-beta * dt) + alpha

    return intensities


def get_fractional_weights(d: float, size: int = 100) -> np.ndarray:
    """
    Generates binomial expansion weights for fractional differencing (1 - B)^d:
    w_0 = 1,  w_k = -w_{k-1} * (d - k + 1) / k
    """
    weights = [1.0]
    for k in range(1, size):
        w = -weights[-1] / k * (d - k + 1)
        weights.append(w)
    return np.array(weights, dtype=float)


def fractional_diff(
    series: Union[np.ndarray, pd.Series],
    d: float,
    threshold: float = 1e-4,
    max_memory: int = 100
) -> np.ndarray:
    """
    Applies fixed-window fractional differentiation to preserve long memory
    while establishing stationarity.
    """
    arr = np.asarray(series, dtype=float)
    weights = get_fractional_weights(d, size=min(len(arr), max_memory))
    weights = weights[np.abs(weights) >= threshold]
    if len(weights) == 0:
        return np.array([])
    return np.convolve(arr, weights, mode="valid")


def compute_order_book_imbalance(bid_qty: float, ask_qty: float) -> float:
    """Computes normalized static Order Book Imbalance (OBI) in [-1.0, 1.0]."""
    total_q = float(bid_qty) + float(ask_qty)
    if total_q <= 0.0:
        return 0.0
    return float((bid_qty - ask_qty) / total_q)
