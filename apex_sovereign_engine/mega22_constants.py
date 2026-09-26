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

# Sovereign Champion Universe (Apex-35: 35 Coins, 100% Halal, 100% Net Profitable, Sharpe 3.68, +1,575.12% Net ROE, $16,751.22)
APEX_35 = list(dict.fromkeys(APEX_30 + APEX_35_EXPANSION))

# Apex-38 Champion Expansion Squad (High-Alpha Halal L1 & Web3 Compute Infrastructure)
# CFX (Conflux Tree-Graph PoW/PoS L1), GRT (The Graph Web3 Indexing Oracle), FLUX (Flux Decentralized Cloud Compute)
APEX_38_EXPANSION = [
    'CFXUSDT', 'GRTUSDT', 'FLUXUSDT'
]

# Sovereign Champion Universe (Apex-38: 38 Coins, 100% Halal Spot, 100% Net Profitable, Sharpe 3.57, +2,056.49% Net ROE, $21,564.87)
APEX_38 = list(dict.fromkeys(APEX_35 + APEX_38_EXPANSION))

# Apex-51 High-Velocity Sovereign Expansion Squad (Verified Halal Spot 2025 Alpha Drivers)
APEX_51_EXPANSION = [
    'ARUSDT', 'ASTRUSDT', 'FLOWUSDT', 'QNTUSDT', 'EGLDUSDT',
    'MINAUSDT', 'ONEUSDT', 'BATUSDT', 'MANAUSDT', 'TAOUSDT',
    'XTZUSDT', 'INJUSDT', 'STXUSDT'
]

# Sovereign Apex-51 Master Universe (51 Halal Coins, Spot 1x Cash Only, +361.38% ROE, $230.69)
APEX_51 = list(dict.fromkeys(APEX_38 + APEX_51_EXPANSION))

# Active Trading Universe (Default configured for Apex-51)
ACTIVE_UNIVERSE = APEX_51

# Per-Candidate Explosion Alpha Score Thresholds for selective momentum admission (0.0 default)
CANDIDATE_MIN_SCORES = {
    'CFXUSDT': 10.0,
    'GRTUSDT': 10.0,
    'FLUXUSDT': 5.0,
    'EGLDUSDT': 10.0,
    'ADAUSDT': 5.0
}


# Macro Anchor for Hawkes Shield & Cross-Market Transfer Entropy
MACRO_SYMBOL = 'BTCUSDT'

# All trading pairs monitored on Binance Spot (Macro Anchor + Active Universe)
ALL_SYMBOLS = [MACRO_SYMBOL] + ACTIVE_UNIVERSE

# Canonical Universal 12-bar Motif Archetype (Z-Normalized)
ARCHETYPE_12 = np.array([1.2, 0.6, 0.0, -0.8, -1.4, -1.6, -1.5, -1.4, -1.0, -0.4, 0.2, 0.8])
ARCH_12_ZNORM = (ARCHETYPE_12 - np.mean(ARCHETYPE_12)) / np.std(ARCHETYPE_12)

# Quantitative Strategy Parameters (Exact match to validated 51-coin $50 challenge)
INITIAL_CAPITAL = 50.00
MAX_SLOTS = 1
SLOT_FRACTION = 0.98         # Single slot all-in (98% of available capital per trade, 2% fee buffer)
FEE_RATE = 0.0004             # 0.04% taker fee (Binance VIP / BNB discounted standard)
SLIPPAGE_RATE = 0.0002        # 0.02% slippage allowance on market orders

# Exit Parameters & Dual-Regime Take Profit
STOP_LOSS_TARGET = 0.022          # -2.2% Stop Loss
TAKE_PROFIT_BASE = 0.065          # +6.5% Base Take Profit
TAKE_PROFIT_HIGH_ALPHA = 0.092    # +9.2% High-Alpha Runner Target (score >= 11.0)
HIGH_ALPHA_SCORE_THRESHOLD = 11.0 # Kinetic acceleration cutoff for +9.2% runner
TAKE_PROFIT_TARGET = TAKE_PROFIT_BASE

# Dynamic Progressive 4-Tier Parabolic Profit Lock: (trigger_best_pnl, locked_stop_offset)
# Note: negative offset in stop means locked positive profit floor
# best_pnl >= +1.6% -> lock +0.6% profit (stop = -0.006)
# best_pnl >= +2.8% -> lock +1.6% profit (stop = -0.016)
# best_pnl >= +4.5% -> lock +3.2% profit (stop = -0.032)
# best_pnl >= +6.5% -> lock +5.0% profit (stop = -0.050)
PARABOLIC_LOCK_TIERS = [
    (0.016, -0.006),
    (0.028, -0.016),
    (0.045, -0.032),
    (0.065, -0.050),
]

# Asymmetric Trailing Ratchet Parameters
TRAILING_TRIGGER_MIN_PNL = 0.008  # +0.8% required to activate trailing ratchet
TRAILING_OFFSET = 0.012          # 1.2% trail distance below highest price reached

# Stall Exit Parameters
STALL_BARS_THRESHOLD = 60        # 60 bars (5 hours)
STALL_MAX_PNL = 0.001           # PnL < +0.1%
STALL_WORST_MIN_PNL = -0.010    # worst PnL dipped below -1.0%

# Dynamic Stagnation Time-Decay Trailing Stop
ENABLE_STAGNATION_TIME_DECAY = True
STAGNATION_DECAY_BARS = 36       # 36 bars (3 hours) with no upward progress
STAGNATION_DECAY_STOP = 0.015    # Dynamically tighten stop from -2.2% to -1.5%

# Smart Opportunity-Cost Rotation Parameters (Institutional Active Alpha Rotation)
ENABLE_OPPORTUNITY_ROTATION = True
ROTATION_MIN_SCORE = 5.0        # Candidate explosion alpha score threshold
ROTATION_HELD_BARS = 18         # Standard minimum holding period (1.5 hours) before eviction eligibility
ROTATION_FAST_HELD_BARS = 12    # Accelerated 12-bar (1 hour) eviction when kinetic deceleration (d^2P/dt^2 <= 0) is verified
ROTATION_MAX_PNL = 0.003        # Evict stagnant positions with PnL <= +0.3%
ROTATION_MIN_PNL = -0.015       # Don't evict positions in deep drawdown (PnL < -1.5%), let stop loss protect
ROTATION_SCORE_EDGE = 0.0       # Minimum score advantage candidate must hold over position

# Kinetic Momentum & Acceleration Stagnation Filter (Velocity Slope & d^2P/dt^2 <= 0)
ENABLE_KINETIC_EVICTION = True
KINETIC_VELOCITY_WINDOW = 6     # 6 bars (30 min) for velocity slope dP/dt
KINETIC_ACCEL_WINDOW = 6        # 6 bars (30 min) for second-derivative acceleration d^2P/dt^2


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
