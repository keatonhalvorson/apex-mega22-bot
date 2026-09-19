#!/usr/bin/env python3
"""
Comprehensive 32-Month Audit Engine for Mega-22 Sovereign Strategy
Preserved canonical benchmark simulation engine for verification and parity checks.
"""
import sys
import os
import time
from pathlib import Path
import pandas as pd
import numpy as np

ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from apex_hybrid_master_engine import ApexSovereignMasterEngine

data_dirs = {
    2024: Path('/home/atheer/Desktop/Apex_Autonomous_Agent/apex_v2/data/full_year_2024'),
    2025: Path('/home/atheer/Desktop/Apex_Autonomous_Agent/apex_v2/data/full_year_2025'),
    2026: Path('/home/atheer/Desktop/Apex_Autonomous_Agent/apex_v2/data/full_year_2026'),
}

months = []
for y, nm in [(2024, 12), (2025, 12), (2026, 8)]:
    for m in range(1, nm + 1):
        months.append((y, f'{y}-{m:02d}'))

def compute_btc_hawkes(df_btc_5m, alpha=0.6, beta=0.8):
    rets = df_btc_5m['btc_c'].pct_change().fillna(0).values
    neg_shocks = np.maximum(-rets, 0) ** 1.3
    n = len(rets)
    hawkes = np.zeros(n)
    decay = np.exp(-beta)
    h = 0.0
    for i in range(1, n):
        h = h * decay + alpha * neg_shocks[i-1] * 100.0
        hawkes[i] = h
    df_btc_5m['btc_hawkes'] = hawkes
    return df_btc_5m

def compute_hurst_proxy(series, window=144):
    r1 = series.diff()
    r5 = series.diff(5)
    var1 = r1.rolling(window, min_periods=36).var()
    var5 = r5.rolling(window, min_periods=36).var()
    vr = var5 / (5.0 * np.maximum(var1, 1e-8))
    hurst = 0.5 + 0.5 * (np.log(np.maximum(vr, 1e-4)) / np.log(5.0))
    return np.clip(hurst, 0.0, 1.0)

def simulate_engine_rigorous(symbols_universe, initial_capital=1000.0, max_slots=3, slot_frac=0.32, 
                             name="Simulation", correct_fees=True):
    cap = initial_capital
    fee = 0.0004
    slip = 0.0002
    sl_target = 0.022
    tp_target = 0.065
    all_trades = []
    monthly_stats = []
    
    for y, ym in months:
        d_dir = data_dirs[y]
        p_btc = d_dir / f'BTCUSDT_{ym}.pkl'
        if not p_btc.exists():
            continue
        df_btc = pd.read_pickle(p_btc)
        df_btc_5m = ApexSovereignMasterEngine.resample_5m(df_btc)[['open_time', 'close']].rename(columns={'close': 'btc_c'})
        df_btc_5m['btc_24h'] = (df_btc_5m['btc_c'] / df_btc_5m['btc_c'].shift(288) - 1.0) * 100.0
        df_btc_5m['btc_4h'] = (df_btc_5m['btc_c'] / df_btc_5m['btc_c'].shift(48) - 1.0) * 100.0
        df_btc_5m = compute_btc_hawkes(df_btc_5m)
        
        coin_dfs = {}
        for sym in symbols_universe:
            p = d_dir / f'{sym}_{ym}.pkl'
            if p.exists():
                try:
                    df_1m = pd.read_pickle(p)
                    df_5m = ApexSovereignMasterEngine.resample_5m(df_1m)
                    df_ind = ApexSovereignMasterEngine.calculate_multifractal_fisher_indicators(df_5m, df_btc_5m)
                    df_ind['hurst'] = compute_hurst_proxy(df_ind['close'], window=144)
                    coin_dfs[sym] = df_ind
                except Exception:
                    pass
                    
        if not coin_dfs:
            continue
            
        n_bars = min(len(df) for df in coin_dfs.values())
        symbols = list(coin_dfs.keys())
        active_positions = {}
        inst_cap = cap
        stoploss_guard_until = -1
        consecutive_stops = 0
        cooldowns = {s: -1 for s in symbols}
        
        m_trades = []
        for i in range(150, n_bars):
            to_close = []
            for sym, pos in list(active_positions.items()):
                df_s = coin_dfs[sym]
                c = df_s['close'].values[i]
                l = df_s['low'].values[i]
                h = df_s['high'].values[i]
                exit_sig = df_s['exit_long'].values[i]
                held = i - pos['i']
                
                pnl = (c - pos['px']) / pos['px']
                best_pnl = (h - pos['px']) / pos['px']
                worst_pnl = (l - pos['px']) / pos['px']
                
                # Dynamic Parabolic Profit Lock (4-tier)
                if best_pnl >= 0.016 and pos['stop'] > -0.005:
                    pos['stop'] = -0.005
                if best_pnl >= 0.030 and pos['stop'] > -0.018:
                    pos['stop'] = -0.018
                if best_pnl >= 0.048 and pos['stop'] > -0.035:
                    pos['stop'] = -0.035
                    
                # Trailing Ratchet
                if 'trailing_active' not in pos:
                    pos['trailing_active'] = False
                    pos['highest_since_trail'] = h
                
                if (exit_sig == 1) and (pnl >= 0.008):
                    pos['trailing_active'] = True
                    if pos['stop'] > -0.008:
                        pos['stop'] = -0.008
                        
                if pos['trailing_active']:
                    if h > pos['highest_since_trail']:
                        pos['highest_since_trail'] = h
                    trail_stop_pct = (pos['highest_since_trail'] - pos['px']) / pos['px'] - 0.012
                    if trail_stop_pct > 0.008 and -trail_stop_pct < pos['stop']:
                        pos['stop'] = -trail_stop_pct
                        
                is_stop = worst_pnl <= -pos['stop'] if pos['stop'] > 0 else worst_pnl <= pos['stop']
                is_tp = best_pnl >= tp_target
                is_stalled = (held >= 60) and (pnl < 0.001) and (worst_pnl < -0.010)
                
                if is_stop or is_tp or is_stalled:
                    if is_stop and pos['stop'] <= 0:
                        exit_px = pos['px'] * (1.0 + abs(pos['stop']))
                        reason = 'TRAILING_LOCK'
                    elif is_stop:
                        exit_px = pos['px'] * (1.0 - pos['stop'])
                        reason = 'STOP_LOSS'
                    elif is_tp:
                        exit_px = pos['px'] * (1.0 + tp_target)
                        reason = 'TAKE_PROFIT'
                    else:
                        exit_px = c * (1.0 - slip)
                        reason = 'STALL_EXIT'
                        
                    future_slice = df_s['high'].values[i+1 : min(i+49, len(df_s))]
                    post_mfe = (np.max(future_slice) - exit_px) / exit_px * 100.0 if len(future_slice) > 0 else 0.0
                        
                    gross = (exit_px - pos['px']) / pos['px'] * pos['notional']
                    exit_fee = pos['notional'] * fee
                    entry_fee = pos['entry_fee']
                    
                    if correct_fees:
                        net = gross - exit_fee - entry_fee
                    else:
                        net = gross - exit_fee
                        
                    inst_cap += (pos['notional'] + gross - exit_fee)
                    
                    t_record = {
                        'sym': sym, 'month': ym, 'entry_i': pos['i'], 'exit_i': i,
                        'entry_px': pos['px'], 'exit_px': exit_px,
                        'pnl_pct': (exit_px / pos['px'] - 1) * 100.0,
                        'gross': gross, 'net': net, 'entry_fee': entry_fee, 'exit_fee': exit_fee,
                        'reason': reason, 'post_mfe': post_mfe,
                        'cap_after': inst_cap
                    }
                    m_trades.append(t_record)
                    to_close.append(sym)
                    
                    if 'STOP_LOSS' in reason:
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
                        if coin_dfs[sym]['is_candidate'].values[i - 1] == 1:
                            score = coin_dfs[sym]['explosion_alpha_score'].values[i - 1]
                            cands.append((sym, score))
                            
                cands.sort(key=lambda x: x[1], reverse=True)
                for sym, _ in cands[:avail]:
                    df_s = coin_dfs[sym]
                    o = df_s['open'].values[i]
                    target_notional = inst_cap * slot_frac
                    if inst_cap >= target_notional and target_notional > 50.0:
                        epx = o * (1.0 + slip)
                        ef = target_notional * fee
                        inst_cap -= (target_notional + ef)
                        active_positions[sym] = {
                            'px': epx, 'notional': target_notional, 'i': i, 'stop': sl_target,
                            'entry_fee': ef
                        }
                        
        for sym, pos in list(active_positions.items()):
            df_s = coin_dfs[sym]
            c = df_s['close'].values[-1]
            gross = (c - pos['px']) / pos['px'] * pos['notional']
            exit_fee = pos['notional'] * fee
            entry_fee = pos['entry_fee']
            if correct_fees:
                net = gross - exit_fee - entry_fee
            else:
                net = gross - exit_fee
            inst_cap += (pos['notional'] + gross - exit_fee)
            m_trades.append({
                'sym': sym, 'month': ym, 'entry_i': pos['i'], 'exit_i': n_bars-1,
                'entry_px': pos['px'], 'exit_px': c, 'pnl_pct': (c/pos['px']-1)*100.0,
                'gross': gross, 'net': net, 'entry_fee': entry_fee, 'exit_fee': exit_fee,
                'reason': 'MONTH_END', 'post_mfe': 0.0,
                'cap_after': inst_cap
            })
            
        m_start_cap = cap
        cap = inst_cap
        m_pnl = cap - m_start_cap
        wins = sum(1 for t in m_trades if t['net'] > 0)
        wr = (wins / len(m_trades) * 100.0) if m_trades else 0.0
        monthly_stats.append({
            'month': ym, 'net': m_pnl, 'cap': cap, 'trades': len(m_trades),
            'wins': wins, 'wr': wr, 'm_ret': (cap / m_start_cap - 1.0) * 100.0
        })
        all_trades.extend(m_trades)
        
    df_trades = pd.DataFrame(all_trades)
    df_m = pd.DataFrame(monthly_stats)
    
    n_trades = len(df_trades)
    net_profit = cap - initial_capital
    roe = (net_profit / initial_capital) * 100.0
    win_rate = (df_trades['net'] > 0).mean() * 100.0 if n_trades > 0 else 0.0
    
    m_caps = [initial_capital] + df_m['cap'].tolist()
    m_peak = np.maximum.accumulate(m_caps)
    m_dds = (np.array(m_caps) - m_peak) / m_peak * 100.0
    max_monthly_dd = np.min(m_dds)
    
    cum_equity = initial_capital + np.cumsum(df_trades['net'].values)
    t_peak = np.maximum.accumulate(cum_equity)
    t_dds = (cum_equity - t_peak) / t_peak * 100.0
    max_trade_dd = np.min(t_dds) if len(t_dds) > 0 else 0.0
    
    m_rets = df_m['m_ret'].values / 100.0
    sharpe_monthly = (np.mean(m_rets) / np.std(m_rets, ddof=1) * np.sqrt(12)) if np.std(m_rets) > 0 else 0.0
    
    rets = df_trades['pnl_pct'].values / 100.0
    ann_factor = n_trades / (32.0 / 12.0)
    sharpe_trades = (np.mean(rets) / np.std(rets, ddof=1) * np.sqrt(ann_factor)) if np.std(rets) > 0 else 0.0
    
    pos_months = (df_m['net'] > 0).sum()
    tot_months = len(df_m)
    
    gw = df_trades[df_trades['net'] > 0]['net'].sum()
    gl = abs(df_trades[df_trades['net'] <= 0]['net'].sum())
    pf = gw / gl if gl > 0 else 99.0
    
    coin_pnl = df_trades.groupby('sym').agg(
        trades=('net', 'count'),
        net_profit=('net', 'sum'),
        win_rate=('net', lambda x: (x > 0).mean() * 100.0),
        avg_pnl=('pnl_pct', 'mean'),
        profit_factor=('net', lambda x: x[x > 0].sum() / abs(x[x <= 0].sum()) if abs(x[x <= 0].sum()) > 0 else 99.0)
    ).sort_values('net_profit', ascending=False)
    coin_pnl['pnl_share'] = (coin_pnl['net_profit'] / coin_pnl['net_profit'].sum()) * 100.0
    
    winning_coins = (coin_pnl['net_profit'] > 0).sum()
    total_active_coins = len(coin_pnl)
    
    return {
        'name': name, 'cap': cap, 'net': net_profit, 'roe': roe, 'trades': n_trades,
        'wr': win_rate, 'pf': pf, 'sharpe_monthly': sharpe_monthly, 'sharpe_trades': sharpe_trades,
        'max_trade_dd': max_trade_dd, 'max_monthly_dd': max_monthly_dd,
        'pos_months': pos_months, 'tot_months': tot_months,
        'winning_coins': winning_coins, 'total_coins': total_active_coins,
        'df_trades': df_trades, 'df_m': df_m, 'coin_pnl': coin_pnl
    }
