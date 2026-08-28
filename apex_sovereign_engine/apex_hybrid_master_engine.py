"""
====================================================================================================
      🌌 APEX CROSS-SECTIONAL WHALE RESONANCE & MOTIF ENGINE (CS-WRE v2.0)
      
      State-of-the-Art Cross-Sectional Microstructure Asset Selection & Pattern Discovery:
      1. Dynamic Cross-Sectional Scanner across 27+ Diverse Cryptocurrencies
      2. Kyle Microstructure Elasticity Tension (Lambda)
      3. Cross-Sectional Order Flow Imbalance (OFI) Asymmetry
      4. Directional Lead-Lag Transfer Entropy (BTC -> Altcoin)
      5. Vectorized Z-Normalized Matrix Profile Euclidean Distance Matching
      6. 3-Tier Dynamic Parabolic Profit Lock (+0.5% at +1.6%, +1.6% at +3.0%, +3.0% at +4.8%, Target +5.5%)
      7. Pure Spot 1x Cash (100% Halal, 0 Leverage, 0 MB Internet Data)
====================================================================================================
"""

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view
from typing import Dict, Any, List, Tuple

ARCHETYPE_SHAPE = np.array([1.2, 0.6, 0.0, -0.8, -1.4, -1.6, -1.5, -1.4, -1.0, -0.4, 0.2, 0.8])
ARCHETYPE_ZNORM = (ARCHETYPE_SHAPE - np.mean(ARCHETYPE_SHAPE)) / np.std(ARCHETYPE_SHAPE)

class ApexSovereignMasterEngine:
    def __init__(self, initial_capital: float = 1000.0, max_slots: int = 3):
        self.capital = initial_capital
        self.max_slots = max_slots
        self.active_positions = {}
        self.fee = 0.0004
        self.slip = 0.0002
        
    @staticmethod
    def resample_5m(df_1m: pd.DataFrame) -> pd.DataFrame:
        df = df_1m.copy()
        if df['open_time'].dtype == np.int64:
            val0 = df['open_time'].iloc[0]
            if val0 > 1e14:
                df['open_time'] = pd.to_datetime(df['open_time'], unit='us')
            else:
                df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
        elif not np.issubdtype(df['open_time'].dtype, np.datetime64):
            df['open_time'] = pd.to_datetime(df['open_time'])
        df = df.set_index('open_time')
        
        agg_dict = {'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'}
        tbv_col = "taker_buy_base" if "taker_buy_base" in df.columns else ("taker_buy_volume" if "taker_buy_volume" in df.columns else None)
        if tbv_col:
            agg_dict[tbv_col] = 'sum'
        df_5m = df.resample('5min').agg(agg_dict).dropna().reset_index()
        if tbv_col:
            df_5m['taker_buy'] = df_5m[tbv_col]
            df_5m['taker_sell'] = np.maximum(df_5m['volume'] - df_5m['taker_buy'], 1e-6)
            df_5m['delta'] = df_5m['taker_buy'] - df_5m['taker_sell']
            df_5m['tbv_ratio'] = df_5m[tbv_col] / np.maximum(df_5m['volume'], 1e-6)
        else:
            df_5m['taker_buy'] = df_5m['volume'] * 0.55
            df_5m['taker_sell'] = df_5m['volume'] * 0.45
            df_5m['delta'] = df_5m['volume'] * 0.1
            df_5m['tbv_ratio'] = 0.55
        return df_5m

    @staticmethod
    def calculate_cross_sectional_indicators(df_5m: pd.DataFrame, df_btc_5m: pd.DataFrame) -> pd.DataFrame:
        df = df_5m.merge(df_btc_5m, on="open_time", how="inner")
        
        # 1. Bollinger Bands & Moving Averages
        typical_px = (df['high'] + df['low'] + df['close']) / 3.0
        df['bb_mid'] = typical_px.rolling(20, min_periods=5).mean()
        bb_std = typical_px.rolling(20, min_periods=5).std().fillna(1e-4)
        df['bb_lower'] = df['bb_mid'] - (bb_std * 2.0)
        df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()
        df['vol_mean_30'] = df['volume'].rolling(30, min_periods=5).mean().fillna(1.0)
        
        # 2. Vectorized Matrix Profile
        c_vals = df['close'].values
        n_bars = len(c_vals)
        motif_dist = np.full(n_bars, 99.0)
        if n_bars >= 12:
            windows = sliding_window_view(c_vals, window_shape=12)
            means = np.mean(windows, axis=1, keepdims=True)
            stds = np.std(windows, axis=1, keepdims=True) + 1e-8
            znorms = (windows - means) / stds
            dists = np.sqrt(np.mean((znorms - ARCHETYPE_ZNORM) ** 2, axis=1))
            motif_dist[11:] = dists
        df['motif_distance'] = motif_dist
        
        # 3. Kyle Elasticity Lambda
        ret_abs = (df['close'].pct_change()).abs().fillna(0)
        vol_sqrt = np.sqrt(df['volume'] + 1e-6)
        candle_range = (df['high'] - df['low']) / (df['close'] + 1e-6) + 1e-6
        df['kyle_lambda'] = ret_abs / (vol_sqrt * candle_range + 1e-8)
        lam_mean = df['kyle_lambda'].rolling(24, min_periods=5).mean().fillna(0)
        lam_std = df['kyle_lambda'].rolling(24, min_periods=5).std().fillna(1.0) + 1e-6
        df['lambda_z'] = (df['kyle_lambda'] - lam_mean) / lam_std
        
        # 4. OFI Asymmetry
        df['ofi'] = (df['taker_buy'] - df['taker_sell']) / (df['volume'] + 1e-6)
        
        # 5. Microstructure Lower Wick Absorption
        lower_wick = np.minimum(df['open'], df['close']) - df['low']
        df['wick_ratio'] = lower_wick / (df['high'] - df['low'] + 1e-6)
        
        # 6. Directional Transfer Entropy Proxy
        btc_ret = df['btc_c'].pct_change().fillna(0)
        alt_ret = df['close'].pct_change().fillna(0)
        alt_std = alt_ret.rolling(24, min_periods=5).std().fillna(1.0) + 1e-6
        btc_std = btc_ret.rolling(24, min_periods=5).std().fillna(1.0) + 1e-6
        df['te_proxy'] = (alt_ret * btc_ret.shift(1)).rolling(24, min_periods=5).mean().fillna(0) / (alt_std * btc_std)
        
        # 7. BinHV45 Metrics
        rolling_mean_40 = df['close'].rolling(40, min_periods=5).mean()
        rolling_std_40 = df['close'].rolling(40, min_periods=5).std().fillna(1e-4)
        df['lower_40'] = rolling_mean_40 - (rolling_std_40 * 2)
        df['bbdelta'] = (rolling_mean_40 - df['lower_40']).abs()
        df['closedelta'] = (df['close'] - df['close'].shift()).abs().fillna(0)
        df['tail'] = (df['close'] - df['low']).abs()
        
        # Macro BTC Safety Gate
        btc_24 = df['btc_24h'].fillna(0)
        btc_4 = df['btc_4h'].fillna(0)
        is_btc_safe = (btc_24 > -2.2) & (btc_4 > -1.2)
        
        is_strict_motif_match = (
            (df['motif_distance'] <= 0.42) & 
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
            (df['close'] < 0.988 * df['bb_lower']) &
            (df['volume'] < (df['vol_mean_30'].shift(1).fillna(999999) * 15)) &
            ((df['wick_ratio'] >= 0.18) | (df['tbv_ratio'] >= 0.47))
        )
        df['is_candidate'] = ((is_strict_motif_match | cond_binh | cond_cluc) & is_btc_safe).astype(int)
        
        # Master Cross-Sectional Resonance Score
        motif_score = np.maximum(1.0 - df['motif_distance'], 0.0) * 30.0
        kyle_score = np.clip(df['lambda_z'].fillna(0) * 10.0, -10.0, 30.0)
        ofi_score = np.clip(df['ofi'].fillna(0) * 30.0, -15.0, 30.0)
        te_score = np.clip(df['te_proxy'].fillna(0) * 10.0, -10.0, 20.0)
        
        df['cross_resonance_score'] = motif_score + kyle_score + ofi_score + te_score
        df['exit_long'] = (df['close'] > df['bb_mid']).astype(int)
        return df
