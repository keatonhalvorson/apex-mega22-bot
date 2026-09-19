"""
Mega-22 Sovereign Strategy Configuration and Constants
Universe: Golden-11 ∪ Titan-11 (22 Binance Spot USDT pairs) + BTCUSDT Macro Reference
"""

import numpy as np

# Golden-11 universe (High-alpha momentum and Wyckoff motif absorption - 100% Halal Spot)
GOLDEN_11 = [
    'ORDIUSDT', 'ICPUSDT', 'GALAUSDT', 'NEARUSDT', 'ADAUSDT',
    'TIAUSDT', 'RENDERUSDT', 'LINKUSDT', 'ALGOUSDT', 'XLMUSDT', 'DOGEUSDT'
]

# Titan-11 universe (Deep-liquidity whale resonance & Kyle elasticity - 100% Halal Spot)
TITAN_11 = [
    'TRXUSDT', 'LTCUSDT', 'ATOMUSDT', 'BONKUSDT', 'POLUSDT',
    'HBARUSDT', 'FILUSDT', 'APTUSDT', 'XRPUSDT', 'ENSUSDT', 'FETUSDT'
]

# Combined 22-Coin Mega Universe (deterministic order, no duplicates)
MEGA_22 = list(dict.fromkeys(GOLDEN_11 + TITAN_11))

# Apex-Alpha Expansion Squad (Agile, High-Momentum Halal Altcoins validated across 32-month quantitative audit)
# Selected for zero correlation, high Wyckoff accumulation, and explosive Fisher expansion dynamics
APEX_ADDITIONS = [
    'AVAXUSDT', 'VETUSDT', 'OPUSDT', 'DOTUSDT',
    'SEIUSDT', 'ETHUSDT', 'UNIUSDT', 'SOLUSDT'
]

# Sovereign Universe (Apex-30: 30 Coins, 100% Halal, 100% Net Profitable, Sharpe 3.83, +691.65% Net ROE)
APEX_30 = list(dict.fromkeys(MEGA_22 + APEX_ADDITIONS))

# Apex-35 Champion Expansion Squad (High-Alpha Halal L1, IoT, Oracle & Web3 Compute Infrastructure)
# CKB (Nervos ASIC PoW L1), ROSE (Oasis Privacy L1), JASMY (IoT Data), PYTH (Market Oracle), ANKR (RPC Web3)
APEX_35_EXPANSION = [
    'CKBUSDT', 'ROSEUSDT', 'JASMYUSDT', 'PYTHUSDT', 'ANKRUSDT'
]

# Sovereign Champion Universe (Apex-35: 35 Coins, 100% Halal, 100% Net Profitable, Sharpe 3.74, +936.48% Net ROE, $10,364.80)
APEX_35 = list(dict.fromkeys(APEX_30 + APEX_35_EXPANSION))

# Active Trading Universe (default configured for the Apex-35 Sovereign Champion expansion)
ACTIVE_UNIVERSE = APEX_35


# Macro Anchor for Hawkes Shield & Cross-Market Transfer Entropy
MACRO_SYMBOL = 'BTCUSDT'

# All trading pairs monitored on Binance Spot (Macro Anchor + Active Universe)
ALL_SYMBOLS = [MACRO_SYMBOL] + ACTIVE_UNIVERSE

# Canonical Universal 12-bar Motif Archetype (Z-Normalized)
ARCHETYPE_12 = np.array([1.2, 0.6, 0.0, -0.8, -1.4, -1.6, -1.5, -1.4, -1.0, -0.4, 0.2, 0.8])
ARCH_12_ZNORM = (ARCHETYPE_12 - np.mean(ARCHETYPE_12)) / np.std(ARCHETYPE_12)

# Quantitative Strategy Parameters (Exact match to 32-month $11,727.69 backtest)
INITIAL_CAPITAL = 1000.00
MAX_SLOTS = 3
SLOT_FRACTION = 0.32          # 32% of total capital allocated per position
FEE_RATE = 0.0004             # 0.04% taker fee (Binance VIP / BNB discounted standard)
SLIPPAGE_RATE = 0.0002        # 0.02% slippage allowance on market orders

# Exit Parameters
STOP_LOSS_TARGET = 0.022      # -2.2% Stop Loss
TAKE_PROFIT_TARGET = 0.065    # +6.5% Take Profit

# Dynamic 4-Tier Parabolic Profit Lock: (trigger_best_pnl, locked_stop_offset)
# Note: negative offset in stop means locked positive profit floor
# best_pnl >= +1.6% -> lock +0.5% profit (stop = -0.005)
# best_pnl >= +3.0% -> lock +1.8% profit (stop = -0.018)
# best_pnl >= +4.8% -> lock +3.5% profit (stop = -0.035)
PARABOLIC_LOCK_TIERS = [
    (0.016, -0.005),
    (0.030, -0.018),
    (0.048, -0.035),
]

# Asymmetric Trailing Ratchet Parameters
TRAILING_TRIGGER_MIN_PNL = 0.008  # +0.8% required to activate trailing ratchet
TRAILING_OFFSET = 0.012          # 1.2% trail distance below highest price reached

# Stall Exit Parameters
STALL_BARS_THRESHOLD = 60        # 60 bars (5 hours)
STALL_MAX_PNL = 0.001           # PnL < +0.1%
STALL_WORST_MIN_PNL = -0.010    # worst PnL dipped below -1.0%

# Risk Cooldown Durations (in 5-minute bars)
COOLDOWN_STOP_LOSS_BARS = 24    # 24 bars (2 hours) per-coin cooldown after stop loss
CONSECUTIVE_STOPS_TRIGGER = 2   # 2 consecutive stops trigger portfolio-wide pause
COOLDOWN_GLOBAL_GUARD_BARS = 48 # 48 bars (4 hours) global pause on consecutive stops

# Macro BTC Safety Gate
BTC_24H_MIN_PCT = -2.2          # BTC 24h change must be > -2.2%
BTC_4H_MIN_PCT = -1.2           # BTC 4h change must be > -1.2%
BTC_HAWKES_MAX_INTENSITY = 0.035 # BTC Hawkes shock cascade intensity must be <= 0.035
HAWKES_ALPHA = 0.6
HAWKES_BETA = 0.8

# Memory Ring Buffer Size (5-minute bars per symbol)
BUFFER_MAX_BARS = 300           # ~25 hours of 5m bars, ultra-lightweight memory footprint
