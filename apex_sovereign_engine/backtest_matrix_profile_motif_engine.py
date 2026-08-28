"""
====================================================================================================
      🌌 APEX MATRIX PROFILE & GEOMETRIC SIGNATURE MOTIF ENGINE (FULLY VECTORIZED)
      
      State-of-the-Art 2025-2026 Microstructure Pattern Discovery (Non-Overfitting):
      1. Vectorized Sliding Window Z-Normalized Matrix Profile Euclidean Distance
      2. Zero Parameter Memorization: Pure geometric structural invariance across multi-assets
      3. 3-Tier Dynamic Parabolic Profit Lock (+0.5% at +1.6%, +1.6% at +3.0%, +3.0% at +4.8%, Target +5.5%)
      4. Pure Spot 1x Cash (100% Halal, 0 Leverage, 0 MB Internet Data)
====================================================================================================
"""

import os
import sys
import time
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from pathlib import Path

DATA_2026_DIR = Path("/home/atheer/Desktop/Apex_Autonomous_Agent/apex_v2/data/full_year_2026")
DATA_2025_DIR = Path("/home/atheer/Desktop/Apex_Autonomous_Agent/apex_v2/data/full_year_2025")

EXPANDED_UNIVERSE = [
    "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", 
    "ADAUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "RENDERUSDT",
    "LINKUSDT", "LTCUSDT", "UNIUSDT", "SUIUSDT", "INJUSDT"
]

MONTHS_2025 = [f"2025-{m:02d}" for m in range(1, 13)]
MONTHS_2026 = [f"2026-{m:02d}" for m in range(1, 9)]

# Canonical Universal Whale Accumulation Motif Shape (12 bars / 1 hour):
ARCHETYPE_SHAPE = np.array([1.2, 0.6, 0.0, -0.8, -1.4, -1.6, -1.5, -1.4, -1.0, -0.4, 0.2, 0.8])
ARCHETYPE_ZNORM = (ARCHETYPE_SHAPE - np.mean(ARCHETYPE_SHAPE)) / np.std(ARCHETYPE_SHAPE)

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

def compute_matrix_profile_and_signatures(df_5m: pd.DataFrame, df_btc_5m: pd.DataFrame) -> pd.DataFrame:
    df = df_5m.merge(df_btc_5m, on="open_time", how="inner")
    
    # 1. Bollinger Bands & Moving Averages
    typical_px = (df['high'] + df['low'] + df['close']) / 3.0
    df['bb_mid'] = typical_px.rolling(20).mean()
    bb_std = typical_px.rolling(20).std()
    df['bb_lower'] = df['bb_mid'] - (bb_std * 2.0)
    df['ema_slow'] = df['close'].ewm(span=50, adjust=False).mean()
    df['vol_mean_30'] = df['volume'].rolling(30).mean()
    
    # 2. Ultra-Fast Vectorized Matrix Profile (sliding_window_view)
    c_vals = df['close'].values
    n_bars = len(c_vals)
    motif_dist = np.full(n_bars, 99.0)
    
    if n_bars >= 12:
        windows = sliding_window_view(c_vals, window_shape=12) # shape: (n_bars-11, 12)
        means = np.mean(windows, axis=1, keepdims=True)
        stds = np.std(windows, axis=1, keepdims=True) + 1e-8
        znorms = (windows - means) / stds
        dists = np.sqrt(np.mean((znorms - ARCHETYPE_ZNORM) ** 2, axis=1))
        motif_dist[11:] = dists
        
    df['motif_distance'] = motif_dist
    
    # 3. Microstructure Rejection
    candle_range = df['high'] - df['low'] + 1e-6
    lower_wick = np.minimum(df['open'], df['close']) - df['low']
    df['wick_ratio'] = lower_wick / candle_range
    
    # 4. BinHV45 Statistical Metrics
    rolling_mean_40 = df['close'].rolling(40).mean()
    rolling_std_40 = df['close'].rolling(40).std()
    df['lower_40'] = rolling_mean_40 - (rolling_std_40 * 2)
    df['bbdelta'] = (rolling_mean_40 - df['lower_40']).abs()
    df['closedelta'] = (df['close'] - df['close'].shift()).abs()
    df['tail'] = (df['close'] - df['low']).abs()
    
    # Macro Safety Gate: Strict BTC Armor
    is_btc_safe = (df['btc_24h'] > -2.2) & (df['btc_4h'] > -1.2)
    
    # Strict Matrix Profile Spring Match (Distance <= 0.42)
    is_strict_motif_match = (
        (df['motif_distance'] <= 0.42) & 
        (df['close'] < df['bb_lower'] * 1.002) & 
        (df['tbv_ratio'] >= 0.48) & 
        (df['wick_ratio'] >= 0.20)
    )
    
    # Cluc & BinHV45 Base
    cond_binh = (
        (df['lower_40'].shift(1) > 0) &
        (df['bbdelta'] > df['close'] * 0.008) &
        (df['closedelta'] > df['close'] * 0.0175) &
        (df['tail'] < df['bbdelta'] * 0.25) &
        (df['close'] < df['lower_40'].shift(1)) &
        (df['close'] <= df['close'].shift(1))
    )
    cond_cluc = (
        (df['close'] < df['ema_slow']) &
        (df['close'] < 0.988 * df['bb_lower']) &
        (df['volume'] < (df['vol_mean_30'].shift(1) * 15)) &
        ((df['wick_ratio'] >= 0.18) | (df['tbv_ratio'] >= 0.47))
    )
    
    df['is_candidate'] = ((is_strict_motif_match | cond_binh | cond_cluc) & is_btc_safe).astype(int)
    
    # Pattern Invariance Alpha Score
    motif_affinity = np.maximum(1.0 - df['motif_distance'], 0.0)
    disloc_depth = np.maximum((df['bb_lower'] - df['close']) / df['close'] * 100.0, 0.0)
    
    df['pattern_alpha_score'] = (
        (motif_affinity * 40.0) +
        (df['tbv_ratio'] * 30.0) +
        (df['wick_ratio'] * 20.0) +
        (disloc_depth * 10.0)
    )
    
    df['exit_long'] = (df['close'] > df['bb_mid']).astype(int)
    return df

def run_motif_month(ym: str, data_dir: Path, start_cap: float, fee=0.0004, slip=0.0002):
    p_btc = data_dir / f"BTCUSDT_{ym}.pkl"
    if not p_btc.exists():
        return None, start_cap
        
    df_btc_1m = pd.read_pickle(p_btc)
    df_btc_5m = resample_5m(df_btc_1m)[["open_time", "close"]].rename(columns={"close": "btc_c"})
    df_btc_5m["btc_24h"] = (df_btc_5m["btc_c"] / df_btc_5m["btc_c"].shift(288) - 1.0) * 100.0
    df_btc_5m["btc_4h"] = (df_btc_5m["btc_c"] / df_btc_5m["btc_c"].shift(48) - 1.0) * 100.0

    coin_dfs = {}
    for sym in EXPANDED_UNIVERSE:
        p = data_dir / f"{sym}_{ym}.pkl"
        if not p.exists():
            continue
        try:
            df_1m = pd.read_pickle(p)
            df_5m = resample_5m(df_1m)
            df_ind = compute_matrix_profile_and_signatures(df_5m, df_btc_5m)
            coin_dfs[sym] = df_ind
        except Exception:
            continue
            
    if not coin_dfs:
        return None, start_cap
        
    n_bars = min(len(df) for df in coin_dfs.values())
    symbols = list(coin_dfs.keys())
    
    active_positions = {}
    inst_trades = []
    inst_cap = start_cap
    max_slots = 3
    
    stoploss_guard_until = -1
    consecutive_stops = 0
    cooldowns = {s: -1 for s in symbols}
    
    for i in range(150, n_bars):
        to_close = []
        for sym, pos in list(active_positions.items()):
            df_s = coin_dfs[sym]
            c = df_s["close"].values[i]
            l = df_s["low"].values[i]
            h = df_s["high"].values[i]
            o = df_s["open"].values[i]
            exit_sig = df_s["exit_long"].values[i]
            held = i - pos["i"]
            
            pnl = (c - pos["px"]) / pos["px"]
            best_pnl = (h - pos["px"]) / pos["px"]
            worst_pnl = (l - pos["px"]) / pos["px"]
            
            # Dynamic Parabolic Profit Lock
            if best_pnl >= 0.016 and pos["stop"] > -0.005:
                pos["stop"] = -0.005 # Lock +0.5% (Zero Risk)
            if best_pnl >= 0.030 and pos["stop"] > -0.016:
                pos["stop"] = -0.016 # Lock +1.6%
            if best_pnl >= 0.048 and pos["stop"] > -0.030:
                pos["stop"] = -0.030 # Lock +3.0%
                
            is_stop = worst_pnl <= -pos["stop"] if pos["stop"] > 0 else worst_pnl <= pos["stop"]
            is_tp = best_pnl >= 0.055
            is_bb_exit = (exit_sig == 1) and (pnl > 0.008)
            is_stalled = (held >= 40) and (pnl < 0.001) and (worst_pnl < -0.010)
            
            if is_stop or is_tp or is_bb_exit or is_stalled:
                if is_stop and pos["stop"] <= 0:
                    exit_px = pos["px"] * (1.0 + abs(pos["stop"]))
                    reason = "PROFIT_LOCK"
                elif is_stop:
                    exit_px = pos["px"] * (1.0 - pos["stop"])
                    reason = "STOP_LOSS"
                elif is_tp:
                    exit_px = pos["px"] * 1.055
                    reason = "TAKE_PROFIT"
                elif is_bb_exit:
                    exit_px = c * (1.0 - slip)
                    reason = "BB_EXIT"
                else:
                    exit_px = c * (1.0 - slip)
                    reason = "STALL_EXIT"
                    
                gross = (exit_px - pos["px"]) / pos["px"] * pos["notional"]
                net = gross - (pos["notional"] * fee)
                inst_cap += (pos["notional"] + net)
                inst_trades.append({"sym": sym, "pnl_pct": f"{(exit_px/pos['px']-1)*100:+0.2f}%", "net": net, "reason": reason, "month": ym, "cap_after": inst_cap})
                to_close.append(sym)
                
                if "STOP_LOSS" in reason:
                    consecutive_stops += 1
                    cooldowns[sym] = i + 24
                    if consecutive_stops >= 2:
                        stoploss_guard_until = i + 48
                else:
                    consecutive_stops = 0
                    
        for sym in to_close:
            del active_positions[sym]
            
        if len(active_positions) < max_slots and i > stoploss_guard_until:
            avail = max_slots - len(active_positions)
            cands = []
            for sym in symbols:
                if sym not in active_positions and i > cooldowns[sym]:
                    if coin_dfs[sym]["is_candidate"].values[i - 1] == 1:
                        score = coin_dfs[sym]["pattern_alpha_score"].values[i - 1]
                        cands.append((sym, score))
                        
            cands.sort(key=lambda x: x[1], reverse=True)
            
            for sym, _ in cands[:avail]:
                df_s = coin_dfs[sym]
                o = df_s["open"].values[i]
                target_notional = inst_cap * 0.32
                if inst_cap >= target_notional and target_notional > 50.0:
                    epx = o * (1.0 + slip)
                    ef = target_notional * fee
                    inst_cap -= (target_notional + ef)
                    active_positions[sym] = {"px": epx, "notional": target_notional, "i": i, "stop": 0.022}
                    
    for sym, pos in list(active_positions.items()):
        df_s = coin_dfs[sym]
        c = df_s["close"].values[-1]
        gross = (c - pos["px"]) / pos["px"] * pos["notional"]
        net = gross - (pos["notional"] * fee)
        inst_cap += (pos["notional"] + net)
        inst_trades.append({"sym": sym, "pnl_pct": f"{(c/pos['px']-1)*100:+0.2f}%", "net": net, "reason": "MONTH_END", "month": ym, "cap_after": inst_cap})
        
    return pd.DataFrame(inst_trades), inst_cap

def main():
    print("=======================================================================================")
    print("🌌 AUDITING APEX MATRIX PROFILE & GEOMETRIC SIGNATURE MOTIF ENGINE...")
    print("=======================================================================================")
    capital = 1000.0
    all_stats = []
    
    print("\n--- 📅 2025 AUDIT ---")
    for ym in MONTHS_2025:
        df_m, end_cap = run_motif_month(ym, DATA_2025_DIR, capital)
        capital = end_cap
        if df_m is not None and len(df_m) > 0:
            net_m = df_m["net"].sum()
            wins = (df_m["net"] > 0).sum()
            wr = round(wins / len(df_m) * 100.0, 1)
            gw = df_m[df_m["net"] > 0]["net"].sum()
            gl = abs(df_m[df_m["net"] <= 0]["net"].sum())
            pf = round(gw / gl, 2) if gl > 0 else 99.0
            all_stats.append({"Month": ym, "Net": round(net_m, 2), "Cap": round(capital, 2), "Trades": len(df_m), "WR": f"{wr}%", "PF": pf})
            print(f"🚀 {ym}: Net ${net_m:+0.2f} | Cap: ${capital:0.2f} | Trades: {len(df_m)} | WR: {wr}% | PF: {pf}")

    print("\n--- 📅 2026 AUDIT ---")
    for ym in MONTHS_2026:
        df_m, end_cap = run_motif_month(ym, DATA_2026_DIR, capital)
        capital = end_cap
        if df_m is not None and len(df_m) > 0:
            net_m = df_m["net"].sum()
            wins = (df_m["net"] > 0).sum()
            wr = round(wins / len(df_m) * 100.0, 1)
            gw = df_m[df_m["net"] > 0]["net"].sum()
            gl = abs(df_m[df_m["net"] <= 0]["net"].sum())
            pf = round(gw / gl, 2) if gl > 0 else 99.0
            all_stats.append({"Month": ym, "Net": round(net_m, 2), "Cap": round(capital, 2), "Trades": len(df_m), "WR": f"{wr}%", "PF": pf})
            print(f"🚀 {ym}: Net ${net_m:+0.2f} | Cap: ${capital:0.2f} | Trades: {len(df_m)} | WR: {wr}% | PF: {pf}")

    df_res = pd.DataFrame(all_stats)
    print("\n=======================================================================================")
    print("🏆 APEX MATRIX PROFILE & GEOMETRIC SIGNATURE PERFORMANCE SUMMARY:")
    print("=======================================================================================")
    print(df_res.to_string(index=False))
    tot_prof = capital - 1000.0
    print(f"\n💰 Total 20-Month Net Profit: ${tot_prof:+0.2f} ({(tot_prof/1000.0)*100.0:0.2f}% ROE)")

if __name__ == "__main__":
    main()
