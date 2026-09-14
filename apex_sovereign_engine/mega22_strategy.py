"""
Mega-22 Sovereign Strategy Core Logic
Implements exact 1:1 mathematical parity with the 32-Month $11,727.69 backtest engine.
100% Halal Spot 1x Cash - Zero CFDs, Zero Leverage, Zero Shorting.
"""

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

from mega22_constants import (
    ARCHETYPE_12, ARCH_12_ZNORM, INITIAL_CAPITAL, MAX_SLOTS, SLOT_FRACTION,
    FEE_RATE, SLIPPAGE_RATE, STOP_LOSS_TARGET, TAKE_PROFIT_TARGET,
    PARABOLIC_LOCK_TIERS, TRAILING_TRIGGER_MIN_PNL, TRAILING_OFFSET,
    STALL_BARS_THRESHOLD, STALL_MAX_PNL, STALL_WORST_MIN_PNL,
    COOLDOWN_STOP_LOSS_BARS, CONSECUTIVE_STOPS_TRIGGER, COOLDOWN_GLOBAL_GUARD_BARS,
    BTC_24H_MIN_PCT, BTC_4H_MIN_PCT, BTC_HAWKES_MAX_INTENSITY,
    HAWKES_ALPHA, HAWKES_BETA, MEGA_22, MACRO_SYMBOL
)

@dataclass
class Position:
    sym: str
    px: float                        # Effective entry price (with slippage)
    notional: float                  # Allocated capital in USD
    entry_fee: float                 # Entry fee paid
    i: int                           # Bar index at entry
    entry_time: str                  # ISO timestamp string
    stop: float = STOP_LOSS_TARGET   # Positive = SL below px, Negative = locked profit above px
    trailing_active: bool = False
    highest_since_trail: float = 0.0
    highest_seen: float = 0.0
    lowest_seen: float = 0.0
    current_px: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    held_bars: int = 0

    def to_dict(self, current_bar_index: Optional[int] = None) -> Dict[str, Any]:
        if current_bar_index is not None:
            bars = max(0, current_bar_index - self.i)
        elif self.held_bars > 0:
            bars = self.held_bars
        else:
            bars = 0
            if self.entry_time:
                try:
                    et = datetime.fromisoformat(self.entry_time.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    diff_m = max(0, int((now - et).total_seconds() / 60))
                    bars = max(0, diff_m // 5)
                except Exception:
                    pass
        self.held_bars = bars
        duration_min = bars * 5
        return {
            'sym': self.sym,
            'px': self.px,
            'notional': self.notional,
            'entry_fee': self.entry_fee,
            'i': self.i,
            'entry_time': self.entry_time,
            'stop': self.stop,
            'trailing_active': self.trailing_active,
            'highest_since_trail': self.highest_since_trail,
            'highest_seen': self.highest_seen,
            'lowest_seen': self.lowest_seen,
            'current_px': self.current_px,
            'unrealized_pnl': self.unrealized_pnl,
            'unrealized_pnl_pct': self.unrealized_pnl_pct,
            'held_bars': bars,
            'bars_held': bars,
            'duration_min': duration_min
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'Position':
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        if 'held_bars' not in filtered and 'bars_held' in d:
            filtered['held_bars'] = int(d['bars_held'])
        return cls(**filtered)

@dataclass
class TradeRecord:
    sym: str
    entry_time: str
    exit_time: str
    entry_i: int
    exit_i: int
    entry_px: float
    exit_px: float
    pnl_pct: float
    notional: float
    gross: float
    net: float
    entry_fee: float
    exit_fee: float
    reason: str
    bars_held: int = 0
    cap_after: float = 1000.0

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'TradeRecord':
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in valid_fields}
        if 'bars_held' not in filtered:
            filtered['bars_held'] = int(d.get('held_bars', 0))
        if 'cap_after' not in filtered:
            filtered['cap_after'] = float(d.get('capital_after', d.get('cap_after', 1000.0)))
        return cls(**filtered)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'sym': self.sym,
            'entry_time': self.entry_time,
            'exit_time': self.exit_time,
            'entry_i': self.entry_i,
            'exit_i': self.exit_i,
            'entry_px': round(self.entry_px, 6),
            'exit_px': round(self.exit_px, 6),
            'pnl_pct': round(self.pnl_pct, 4),
            'notional': round(self.notional, 2),
            'gross': round(self.gross, 4),
            'net': round(self.net, 4),
            'entry_fee': round(self.entry_fee, 4),
            'exit_fee': round(self.exit_fee, 4),
            'reason': self.reason,
            'bars_held': self.bars_held,
            'cap_after': round(self.cap_after, 2)
        }

class Mega22StrategyEngine:
    """
    Exact mathematical implementation of the Mega-22 strategy.
    Supports both batch backtest verification and real-time streaming bar updates.
    """
    
    @staticmethod
    def compute_btc_hawkes(df_btc_5m: pd.DataFrame, alpha: float = HAWKES_ALPHA, beta: float = HAWKES_BETA) -> pd.DataFrame:
        """
        Hawkes Self-Exciting Cascading Shock Intensity for BTC.
        Exact parity with apex_hybrid_master_engine and comprehensive_audit.
        """
        df = df_btc_5m.copy()
        rets = df['btc_c'].pct_change().fillna(0).values
        neg_shocks = np.maximum(-rets, 0) ** 1.3
        n = len(rets)
        hawkes = np.zeros(n)
        decay = np.exp(-beta)
        h = 0.0
        for i in range(1, n):
            h = h * decay + alpha * neg_shocks[i-1] * 100.0
            hawkes[i] = h
        df['btc_hawkes'] = hawkes
        return df

    @staticmethod
    def calculate_indicators(df_5m: pd.DataFrame, df_btc_5m: pd.DataFrame) -> pd.DataFrame:
        """
        Calculates all multifractal, Fisher, Kyle-Obizhaeva, motif, and microstructural indicators.
        Returns combined DataFrame with all signals.
        """
        if 'btc_hawkes' not in df_btc_5m.columns:
            df_btc_5m = Mega22StrategyEngine.compute_btc_hawkes(df_btc_5m)
            
        df = df_5m.merge(df_btc_5m, on="open_time", how="inner")
        if len(df) == 0:
            return df
            
        # 1. Bollinger Bands & Moving Averages
        typical_px = (df['high'] + df['low'] + df['close']) / 3.0
        df['bb_mid'] = typical_px.rolling(20, min_periods=5).mean()
        bb_std = typical_px.rolling(20, min_periods=5).std().fillna(1e-4)
        df['bb_lower'] = df['bb_mid'] - (bb_std * 2.0)
        df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()
        df['vol_mean_30'] = df['volume'].rolling(30, min_periods=5).mean().fillna(1.0)
        
        # 2. Vectorized Matrix Profile Motif Matching
        c_vals = df['close'].values
        n_bars = len(c_vals)
        motif_dist = np.full(n_bars, 99.0)
        if n_bars >= 12:
            windows = sliding_window_view(c_vals, window_shape=12)
            means = np.mean(windows, axis=1, keepdims=True)
            stds = np.std(windows, axis=1, keepdims=True) + 1e-8
            znorms = (windows - means) / stds
            dists = np.sqrt(np.mean((znorms - ARCH_12_ZNORM) ** 2, axis=1))
            motif_dist[11:] = dists
        df['motif_distance'] = motif_dist
        
        # 3. Multifractal Singularity Spectrum Width Proxy
        log_ret = np.log(df['close'] / df['close'].shift(1)).fillna(0)
        rolling_std_6 = log_ret.rolling(6, min_periods=3).std().fillna(1e-4)
        rolling_std_24 = log_ret.rolling(24, min_periods=6).std().fillna(1e-4) + 1e-6
        df['multifractal_spectrum_width'] = (rolling_std_6 / rolling_std_24).clip(0.1, 5.0)
        
        # 4. Fisher Information Metric Phase Transition
        df['fisher_info'] = 1.0 / (rolling_std_6**2 + 1e-6)
        fisher_mean = df['fisher_info'].rolling(48, min_periods=5).mean().fillna(0)
        fisher_std = df['fisher_info'].rolling(48, min_periods=5).std().fillna(1.0) + 1e-6
        df['fisher_z'] = ((df['fisher_info'] - fisher_mean) / fisher_std).clip(-3.0, 5.0)
        
        # 5. Kyle-Obizhaeva Invariant Microstructure Elasticity
        adv_approx = df['volume'].rolling(288, min_periods=10).mean().fillna(1.0) + 1e-6
        vol_impact_term = (df['volume'] / adv_approx) ** (1.0 / 3.0)
        candle_range = (df['high'] - df['low']) / (df['close'] + 1e-6) + 1e-6
        df['kyle_obizhaeva'] = candle_range / (vol_impact_term * (bb_std / df['close']) + 1e-6)
        ko_mean = df['kyle_obizhaeva'].rolling(48, min_periods=5).mean().fillna(0)
        ko_std = df['kyle_obizhaeva'].rolling(48, min_periods=5).std().fillna(1.0) + 1e-6
        df['ko_z'] = ((df['kyle_obizhaeva'] - ko_mean) / ko_std).clip(-3.0, 5.0)
        
        # 6. Microstructure Order Flow & Lower Wick Absorption
        tb_col = 'taker_buy' if 'taker_buy' in df.columns else 'taker_buy_base'
        if tb_col in df.columns:
            taker_buy = df[tb_col]
        else:
            taker_buy = df['volume'] * 0.55
            
        ts_col = 'taker_sell' if 'taker_sell' in df.columns else None
        if ts_col and ts_col in df.columns:
            taker_sell = df[ts_col]
        else:
            taker_sell = np.maximum(df['volume'] - taker_buy, 1e-6)
            
        tbv_ratio = taker_buy / np.maximum(df['volume'], 1e-6)
        lower_wick = np.minimum(df['open'], df['close']) - df['low']
        wick_ratio = lower_wick / (df['high'] - df['low'] + 1e-6)
        ofi = (taker_buy - taker_sell) / (df['volume'] + 1e-6)
        
        df['tbv_ratio'] = tbv_ratio
        df['wick_ratio'] = wick_ratio
        df['ofi'] = ofi
        
        # 7. Directional Transfer Entropy from BTC
        btc_ret = df['btc_c'].pct_change().fillna(0)
        alt_ret = df['close'].pct_change().fillna(0)
        alt_std = alt_ret.rolling(24, min_periods=5).std().fillna(1.0) + 1e-6
        btc_std = btc_ret.rolling(24, min_periods=5).std().fillna(1.0) + 1e-6
        df['te_proxy'] = (alt_ret * btc_ret.shift(1)).rolling(24, min_periods=5).mean().fillna(0) / (alt_std * btc_std)
        
        # 8. BinHV45 Metrics
        rolling_mean_40 = df['close'].rolling(40, min_periods=5).mean()
        rolling_std_40 = df['close'].rolling(40, min_periods=5).std().fillna(1e-4)
        df['lower_40'] = rolling_mean_40 - (rolling_std_40 * 2)
        df['bbdelta'] = (rolling_mean_40 - df['lower_40']).abs()
        df['closedelta'] = (df['close'] - df['close'].shift()).abs().fillna(0)
        df['tail'] = (df['close'] - df['low']).abs()
        
        # Macro BTC Safety Gate with Hawkes Cascade Shield
        btc_24 = df['btc_24h'].fillna(0)
        btc_4 = df['btc_4h'].fillna(0)
        btc_hawkes = df['btc_hawkes'].fillna(0)
        is_btc_safe = (btc_24 > BTC_24H_MIN_PCT) & (btc_4 > BTC_4H_MIN_PCT) & (btc_hawkes <= BTC_HAWKES_MAX_INTENSITY)
        df['is_btc_safe'] = is_btc_safe.astype(int)
        
        # Liquidation Cascade & Falling Knife Pre-Crash Shield
        is_falling_knife = (
            (df['close'] < df['close'].shift(1)) & 
            (df['tbv_ratio'] < 0.28) & 
            (df['wick_ratio'] < 0.18)
        )
        
        is_strict_motif_match = (
            (df['motif_distance'] <= 0.45) & 
            (df['close'] < df['bb_lower'] * 1.002) & 
            (df['tbv_ratio'] >= 0.48) & 
            (df['wick_ratio'] >= 0.20)
        )
        cond_binh = (
            (df['lower_40'].shift(1).fillna(0) > 0) &
            (df['bbdelta'] > df['close'] * 0.008) &
            (df['closedelta'] > df['close'] * 0.0175) &
            (df['tail'] < df['bbdelta'] * 0.25) &
            (df['close'] < df['lower_40'].shift(1).fillna(999999)) &
            (df['close'] <= df['close'].shift(1).fillna(999999))
        )
        cond_cluc = (
            (df['close'] < df['ema_slow']) &
            (df['close'] < 0.992 * df['bb_lower']) &
            (df['volume'] < (df['vol_mean_30'].shift(1).fillna(999999) * 15)) &
            ((df['wick_ratio'] >= 0.18) | (df['tbv_ratio'] >= 0.47))
        )
        
        # Entry candidate signal
        df['is_candidate'] = (
            (is_strict_motif_match | cond_binh | cond_cluc) & 
            ~is_falling_knife & 
            is_btc_safe
        ).astype(int)
        
        # Unified Explosion Rank Alpha Score
        motif_score = np.maximum(1.0 - df['motif_distance'], 0.0) * 25.0
        fisher_score = np.clip(df['fisher_z'].fillna(0) * 10.0, -10.0, 25.0)
        ko_score = np.clip(df['ko_z'].fillna(0) * 10.0, -10.0, 25.0)
        ofi_score = np.clip(df['ofi'].fillna(0) * 25.0, -15.0, 25.0)
        te_score = np.clip(df['te_proxy'].fillna(0) * 10.0, -10.0, 15.0)
        df['explosion_alpha_score'] = motif_score + fisher_score + ko_score + ofi_score + te_score
        
        # Exit long signal (trigger for trailing ratchet activation)
        df['exit_long'] = (df['close'] > df['bb_mid']).astype(int)
        return df

    @staticmethod
    def evaluate_position_step(
        pos: Position,
        c: float,
        h: float,
        l: float,
        exit_sig: int,
        held: int
    ) -> Tuple[Optional[Tuple[float, str]], Position]:
        """
        Evaluates active position exit conditions on bar or intra-bar prices.
        Matches EXACT logic of simulate_engine_rigorous lines 105-147:
        1. Dynamic 4-Tier Parabolic Profit Lock
        2. Asymmetric Trailing Ratchet
        3. Stop loss / Trailing lock / Take profit / Stall exit checking
        Returns: (exit_event, updated_position)
                 where exit_event is None or (exit_price, reason)
        """
        pnl = (c - pos.px) / pos.px
        best_pnl = (h - pos.px) / pos.px
        worst_pnl = (l - pos.px) / pos.px
        
        # Update high / low watermarks
        pos.highest_seen = max(pos.highest_seen, h)
        pos.lowest_seen = min(pos.lowest_seen, l) if pos.lowest_seen > 0 else l
        pos.current_px = c
        pos.unrealized_pnl = pnl * pos.notional
        pos.unrealized_pnl_pct = pnl * 100.0

        # 1. Dynamic Parabolic Profit Lock (4-tier)
        for trig, lock_offset in PARABOLIC_LOCK_TIERS:
            if best_pnl >= trig and pos.stop > lock_offset:
                pos.stop = lock_offset

        # 2. Trailing Ratchet Activation & Update
        if pos.highest_since_trail == 0.0:
            pos.highest_since_trail = h

        if exit_sig == 1 and pnl >= TRAILING_TRIGGER_MIN_PNL:
            pos.trailing_active = True
            if pos.stop > -0.008:
                pos.stop = -0.008

        if pos.trailing_active:
            if h > pos.highest_since_trail:
                pos.highest_since_trail = h
            trail_stop_pct = (pos.highest_since_trail - pos.px) / pos.px - TRAILING_OFFSET
            if trail_stop_pct > 0.008 and -trail_stop_pct < pos.stop:
                pos.stop = -trail_stop_pct

        # 3. Check Exits (exact match to backtest condition)
        is_stop = worst_pnl <= -pos.stop if pos.stop > 0 else worst_pnl <= pos.stop
        is_tp = best_pnl >= TAKE_PROFIT_TARGET
        is_stalled = (held >= STALL_BARS_THRESHOLD) and (pnl < STALL_MAX_PNL) and (worst_pnl < STALL_WORST_MIN_PNL)

        if is_stop or is_tp or is_stalled:
            if is_stop and pos.stop <= 0:
                exit_px = pos.px * (1.0 + abs(pos.stop))
                reason = 'TRAILING_LOCK'
            elif is_stop:
                exit_px = pos.px * (1.0 - pos.stop)
                reason = 'STOP_LOSS'
            elif is_tp:
                exit_px = pos.px * (1.0 + TAKE_PROFIT_TARGET)
                reason = 'TAKE_PROFIT'
            else:
                exit_px = c * (1.0 - SLIPPAGE_RATE)
                reason = 'STALL_EXIT'
            return (exit_px, reason), pos

        return None, pos
