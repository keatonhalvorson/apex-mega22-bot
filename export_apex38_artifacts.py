#!/usr/bin/env python3
"""
Export APEX-38 Sovereign Champion Artifacts & Update selected_apex_universe.json
"""
import json
import pickle
import numpy as np
import pandas as pd
from pathlib import Path

# Load expanded cache
with open('cached_compact_expanded.pkl', 'rb') as f:
    cached_months = pickle.load(f)

months = sorted(list(cached_months.keys()))

from apex_sovereign_engine.mega22_constants import (
    GOLDEN_11, TITAN_11, MEGA_22, APEX_ADDITIONS,
    APEX_35_EXPANSION, APEX_35, APEX_38_EXPANSION, APEX_38,
    CANDIDATE_MIN_SCORES, SLOT_FRACTION, FEE_RATE, SLIPPAGE_RATE,
    STOP_LOSS_TARGET, TAKE_PROFIT_TARGET
)

def export_artifacts():
    u = APEX_38
    cutoffs = CANDIDATE_MIN_SCORES
    
    all_trades = []
    monthly_stats = []
    cap = 1000.0
    fee = FEE_RATE
    slip = SLIPPAGE_RATE
    sl_target = STOP_LOSS_TARGET
    tp_target = TAKE_PROFIT_TARGET

    for ym in months:
        m_data = cached_months[ym]
        coin_dfs = {s: m_data[s] for s in u if s in m_data}
        if not coin_dfs:
            continue
        n_bars = min(d['n_bars'] for d in coin_dfs.values())
        symbols = list(coin_dfs.keys())
        active_positions = {}
        inst_cap = cap
        m_start_cap = cap
        stoploss_guard_until = -1
        consecutive_stops = 0
        cooldowns = {s: -1 for s in symbols}
        m_trades = []

        for i in range(150, n_bars):
            to_close = []
            for sym, pos in list(active_positions.items()):
                df_s = coin_dfs[sym]
                c = float(df_s['close'][i])
                l = float(df_s['low'][i])
                h = float(df_s['high'][i])
                exit_sig = int(df_s['exit_long'][i])
                held = i - pos['i']

                pnl = (c - pos['px']) / pos['px']
                best_pnl = (h - pos['px']) / pos['px']
                worst_pnl = (l - pos['px']) / pos['px']

                if best_pnl >= 0.016 and pos['stop'] > -0.005:
                    pos['stop'] = -0.005
                if best_pnl >= 0.030 and pos['stop'] > -0.018:
                    pos['stop'] = -0.018
                if best_pnl >= 0.048 and pos['stop'] > -0.035:
                    pos['stop'] = -0.035

                if 'trailing_active' not in pos:
                    pos['trailing_active'] = False
                    pos['highest_since_trail'] = h

                if exit_sig == 1 and pnl >= 0.008:
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

                    gross = (exit_px - pos['px']) / pos['px'] * pos['notional']
                    exit_fee = pos['notional'] * fee
                    net = gross - exit_fee - pos['entry_fee']
                    inst_cap += (pos['notional'] + gross - exit_fee)
                    m_trades.append({
                        'sym': sym, 'month': ym, 'net': net, 'pnl_pct': (exit_px / pos['px'] - 1) * 100.0,
                        'reason': reason, 'entry_px': pos['px'], 'exit_px': exit_px,
                        'notional': pos['notional'], 'held_bars': held, 'cap_after': inst_cap
                    })
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

            # Candidates
            cands = []
            if i > stoploss_guard_until:
                for sym in symbols:
                    if sym not in active_positions and i > cooldowns[sym]:
                        if coin_dfs[sym]['is_candidate'][i - 1] == 1:
                            score = float(coin_dfs[sym]['score'][i - 1])
                            if sym in cutoffs and score < cutoffs[sym]:
                                continue
                            cands.append((sym, score))
                cands.sort(key=lambda x: x[1], reverse=True)

            # Rotation
            if len(active_positions) >= 3 and len(cands) > 0:
                top_cand_sym, top_cand_score = cands[0]
                if top_cand_score >= 5.0:
                    evictable = []
                    for sym, pos in active_positions.items():
                        held = i - pos['i']
                        c = float(coin_dfs[sym]['close'][i])
                        pnl = (c - pos['px']) / pos['px']
                        if held >= 18 and pnl <= 0.003 and pos['stop'] > 0:
                            evictable.append((sym, held, pnl))
                    if evictable:
                        evictable.sort(key=lambda x: -x[1])
                        sym_evict = evictable[0][0]
                        pos = active_positions[sym_evict]
                        c = float(coin_dfs[sym_evict]['close'][i])
                        exit_px = c * (1.0 - slip)
                        gross = (exit_px - pos['px']) / pos['px'] * pos['notional']
                        exit_fee = pos['notional'] * fee
                        net = gross - exit_fee - pos['entry_fee']
                        inst_cap += (pos['notional'] + gross - exit_fee)
                        cooldowns[sym_evict] = i + 18
                        m_trades.append({
                            'sym': sym_evict, 'month': ym, 'net': net, 'pnl_pct': (exit_px / pos['px'] - 1) * 100.0,
                            'reason': 'ROTATION_EVICT', 'entry_px': pos['px'], 'exit_px': exit_px,
                            'notional': pos['notional'], 'held_bars': held, 'cap_after': inst_cap
                        })
                        del active_positions[sym_evict]

            # Entry with equal equity sizing
            if len(active_positions) < 3 and i > stoploss_guard_until:
                avail = 3 - len(active_positions)
                valid_cands = [c for c in cands if c[0] not in active_positions]
                for sym, score in valid_cands[:avail]:
                    df_s = coin_dfs[sym]
                    o = float(df_s['open'][i])
                    total_equity = inst_cap + sum(p['notional'] for p in active_positions.values())
                    target_notional = min(total_equity * SLOT_FRACTION, inst_cap / (1.0 + fee))
                    if inst_cap >= target_notional and target_notional > 50.0:
                        epx = o * (1.0 + slip)
                        ef = target_notional * fee
                        inst_cap -= (target_notional + ef)
                        active_positions[sym] = {
                            'px': epx, 'notional': target_notional, 'i': i, 'stop': sl_target,
                            'entry_fee': ef, 'score': score
                        }

        # End of month
        for sym, pos in list(active_positions.items()):
            c = float(coin_dfs[sym]['close'][-1])
            gross = (c - pos['px']) / pos['px'] * pos['notional']
            exit_fee = pos['notional'] * fee
            net = gross - exit_fee - pos['entry_fee']
            inst_cap += (pos['notional'] + gross - exit_fee)
            m_trades.append({
                'sym': sym, 'month': ym, 'net': net, 'pnl_pct': (c / pos['px'] - 1) * 100.0,
                'reason': 'MONTH_END', 'entry_px': pos['px'], 'exit_px': c,
                'notional': pos['notional'], 'held_bars': n_bars - pos['i'], 'cap_after': inst_cap
            })

        m_start_cap = cap
        cap = inst_cap
        m_pnl = cap - m_start_cap
        monthly_stats.append({
            'month': ym, 'net': m_pnl, 'cap': cap, 'trades': len(m_trades),
            'm_ret': (cap / m_start_cap - 1.0) * 100.0
        })
        all_trades.extend(m_trades)

    df_t = pd.DataFrame(all_trades)
    df_m = pd.DataFrame(monthly_stats)
    cpnl = df_t.groupby('sym')['net'].sum().sort_values(ascending=False).reset_index()

    # Save CSV artifacts
    df_t.to_csv('apex38_champion_trades.csv', index=False)
    df_m.to_csv('apex38_champion_monthly.csv', index=False)
    cpnl.to_csv('apex38_champion_coin_pnl.csv', index=False)

    total_gain = df_t[df_t['net'] > 0]['net'].sum()
    total_loss = abs(df_t[df_t['net'] < 0]['net'].sum())
    pf = (total_gain / total_loss) if total_loss > 0 else float('inf')

    m_rets = df_m['m_ret'].values / 100.0
    sharpe = (np.mean(m_rets) / np.std(m_rets, ddof=1) * np.sqrt(12)) if np.std(m_rets) > 0 else 0.0

    cum_equity = 1000.0 + np.cumsum(df_t['net'].values)
    t_peak = np.maximum.accumulate(cum_equity)
    t_dds = (cum_equity - t_peak) / t_peak * 100.0
    max_trade_dd = float(np.min(t_dds)) if len(t_dds) > 0 else 0.0

    m_caps = df_m['cap'].values
    m_peak = np.maximum.accumulate(m_caps)
    m_dds = (m_caps - m_peak) / m_peak * 100.0
    max_monthly_dd = float(np.min(m_dds)) if len(m_dds) > 0 else 0.0

    winning_coins = int((cpnl['net'] > 0).sum())

    # Build updated JSON
    apex_json = {
        "name": "Apex-38 Institutional Sovereign Champion (100% Halal Spot)",
        "golden_11": GOLDEN_11,
        "titan_11": TITAN_11,
        "mega_22": MEGA_22,
        "apex_additions": APEX_ADDITIONS,
        "apex_35_expansion": APEX_35_EXPANSION,
        "apex_38_expansion": APEX_38_EXPANSION,
        "champion_universe": APEX_38,
        "candidate_min_scores": CANDIDATE_MIN_SCORES,
        "baseline_mega22": {
            "ending_cap": 6787.11,
            "net_profit": 5787.11,
            "roe": 578.71,
            "trades": 811,
            "win_rate": 52.77,
            "profit_factor": 2.04,
            "sharpe_monthly": 3.67,
            "max_trade_dd": -7.12,
            "winning_coins": 19,
            "total_coins": 22
        },
        "champion_metrics": {
            "ending_cap": float(cap),
            "net_profit": float(cap - 1000.0),
            "roe": float((cap - 1000.0) / 10.0),
            "trades": len(df_t),
            "win_rate": float((df_t['net'] > 0).mean() * 100.0),
            "profit_factor": float(pf),
            "sharpe_monthly": float(sharpe),
            "max_trade_dd": max_trade_dd,
            "max_monthly_dd": max_monthly_dd,
            "winning_coins": winning_coins,
            "total_coins": len(cpnl)
        }
    }

    with open('selected_apex_universe.json', 'w') as f:
        json.dump(apex_json, f, indent=2)

    print("Successfully exported apex38_champion_trades.csv, apex38_champion_monthly.csv, apex38_champion_coin_pnl.csv, and selected_apex_universe.json")
    print(f"Ending Cap: ${cap:.2f} | Net ROE: +{(cap-1000.0)/10:.2f}% | Trades: {len(df_t)} | Win Rate: {(df_t['net']>0).mean()*100:.2f}% | Winning Coins: {winning_coins}/38")

if __name__ == '__main__':
    export_artifacts()
