#!/usr/bin/env python3
"""
Evaluate All Universes and Screen for the Optimal Champion Universe
"""
import sys
import time
import pickle
import itertools
import json
from pathlib import Path
import pandas as pd
import numpy as np

cache_file = Path('cached_compact_all49.pkl')
if not cache_file.exists():
    print("Cache file missing!")
    sys.exit(1)

print(f"Loading {cache_file}...")
t0 = time.time()
with open(cache_file, 'rb') as f:
    cached_months = pickle.load(f)
print(f"Loaded in {time.time() - t0:.2f}s")

from apex_sovereign_engine.mega22_constants import MEGA_22, GOLDEN_11, TITAN_11

months = sorted(list(cached_months.keys()))
all_49 = sorted(list(set(s for m in cached_months.values() for s in m.keys())))

def simulate_fast(universe, initial_capital=1000.0, max_slots=3, slot_frac=0.32, return_details=False):
    cap = initial_capital
    fee = 0.0004
    slip = 0.0002
    sl_target = 0.022
    tp_target = 0.065
    all_trades = []
    monthly_stats = []

    for ym in months:
        m_data = cached_months[ym]
        coin_dfs = {s: m_data[s] for s in universe if s in m_data}
        if not coin_dfs:
            continue

        n_bars = min(d['n_bars'] for d in coin_dfs.values())
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
                        'reason': reason
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

            if len(active_positions) < max_slots and i > stoploss_guard_until:
                avail = max_slots - len(active_positions)
                cands = []
                for sym in symbols:
                    if sym not in active_positions and i > cooldowns[sym]:
                        if coin_dfs[sym]['is_candidate'][i - 1] == 1:
                            score = float(coin_dfs[sym]['score'][i - 1])
                            cands.append((sym, score))

                cands.sort(key=lambda x: x[1], reverse=True)
                for sym, _ in cands[:avail]:
                    df_s = coin_dfs[sym]
                    o = float(df_s['open'][i])
                    target_notional = inst_cap * slot_frac
                    if inst_cap >= target_notional and target_notional > 50.0:
                        epx = o * (1.0 + slip)
                        ef = target_notional * fee
                        inst_cap -= (target_notional + ef)
                        active_positions[sym] = {
                            'px': epx, 'notional': target_notional, 'i': i, 'stop': sl_target,
                            'entry_fee': ef
                        }

        # End of month close
        for sym, pos in list(active_positions.items()):
            df_s = coin_dfs[sym]
            c = float(df_s['close'][-1])
            gross = (c - pos['px']) / pos['px'] * pos['notional']
            exit_fee = pos['notional'] * fee
            net = gross - exit_fee - pos['entry_fee']
            inst_cap += (pos['notional'] + gross - exit_fee)
            m_trades.append({
                'sym': sym, 'month': ym, 'net': net, 'pnl_pct': (c / pos['px'] - 1) * 100.0,
                'reason': 'MONTH_END'
            })

        m_start_cap = cap
        cap = inst_cap
        m_pnl = cap - m_start_cap
        monthly_stats.append({
            'month': ym, 'net': m_pnl, 'cap': cap, 'trades': len(m_trades),
            'm_ret': (cap / m_start_cap - 1.0) * 100.0
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

    gw = df_trades[df_trades['net'] > 0]['net'].sum()
    gl = abs(df_trades[df_trades['net'] <= 0]['net'].sum())
    pf = gw / gl if gl > 0 else 99.0

    coin_pnl = df_trades.groupby('sym')['net'].sum()
    winning_coins = int((coin_pnl > 0).sum())
    total_coins = int(len(coin_pnl))
    min_coin_pnl = float(coin_pnl.min()) if len(coin_pnl) > 0 else 0.0

    res = {
        'cap': cap, 'net': net_profit, 'roe': roe, 'trades': n_trades,
        'wr': win_rate, 'pf': pf, 'sharpe_monthly': sharpe_monthly,
        'max_trade_dd': max_trade_dd, 'max_monthly_dd': max_monthly_dd,
        'winning_coins': winning_coins, 'total_coins': total_coins,
        'min_coin_pnl': min_coin_pnl
    }
    if return_details:
        res['df_trades'] = df_trades
        res['df_m'] = df_m
        res['coin_pnl'] = df_trades.groupby('sym').agg(
            trades=('net', 'count'),
            net_profit=('net', 'sum'),
            win_rate=('net', lambda x: (x > 0).mean() * 100.0),
            avg_pnl=('pnl_pct', 'mean')
        ).sort_values('net_profit', ascending=False)
    return res

if __name__ == '__main__':
    # 1. Mega-22 Baseline
    print("=" * 70)
    print("1. MEGA-22 BASELINE QUANTITATIVE AUDIT")
    print("=" * 70)
    r_mega = simulate_fast(MEGA_22, return_details=True)
    print(f"Ending Cap: ${r_mega['cap']:.2f} (+{r_mega['roe']:.1f}%) | Trades: {r_mega['trades']} | WR: {r_mega['wr']:.1f}% | PF: {r_mega['pf']:.2f} | Sharpe: {r_mega['sharpe_monthly']:.2f} | DD: {r_mega['max_trade_dd']:.2f}% | Winning Coins: {r_mega['winning_coins']}/{r_mega['total_coins']}")

    # Clean candidate additions discovered through forward stepwise optimization:
    # Top high-alpha, agile, halal altcoins:
    # PENDLE, DOT, VET, AVAX, OP, SEI, ADA, UNI, PYTH, ETH
    top_clean_pool = ['PENDLEUSDT', 'DOTUSDT', 'VETUSDT', 'AVAXUSDT', 'OPUSDT', 'SEIUSDT', 'ADAUSDT', 'ETHUSDT', 'UNIUSDT', 'PYTHUSDT']

    print("\n" + "=" * 70)
    print("2. SCREENING CANDIDATE APEX EXPANSIONS (100% PROFITABLE COINS)")
    print("=" * 70)
    
    # Test adding remaining candidates to Apex-31:
    base_31 = MEGA_22 + top_clean_pool[:9]
    remaining = [s for s in all_49 if s not in base_31]
    print(f"\n--- Testing marginal impact of adding remaining {len(remaining)} coins to Apex-31 ---")
    rem_results = []
    for s in remaining:
        r_test = simulate_fast(base_31 + [s], return_details=True)
        is_all_win = (r_test['winning_coins'] == r_test['total_coins'])
        s_pnl = r_test['coin_pnl'].loc[s]['net_profit'] if s in r_test['coin_pnl'].index else 0.0
        rem_results.append({
            'sym': s, 'cap': r_test['cap'], 'delta': r_test['cap'] - 16036.12,
            'sym_pnl': s_pnl, 'all_win': is_all_win, 'win_coins': r_test['winning_coins'],
            'trades': r_test['trades'], 'sharpe': r_test['sharpe_monthly'], 'dd': r_test['max_trade_dd']
        })
    df_rem = pd.DataFrame(rem_results).sort_values('delta', ascending=False)
    print(df_rem.to_string())

    candidates_to_test = {
        'Apex-28 (Mega-22 + 6)': MEGA_22 + top_clean_pool[:6],
        'Apex-29 (Mega-22 + 7)': MEGA_22 + top_clean_pool[:7],
        'Apex-30 (Mega-22 + 8)': MEGA_22 + top_clean_pool[:8],
        'Apex-31 (Mega-22 + 9)': MEGA_22 + top_clean_pool[:9],
        'Apex-32 (Mega-22 + 10)': MEGA_22 + top_clean_pool[:10],
    }

    best_name = None
    best_res = None
    best_cap = -1.0

    for name, uni in candidates_to_test.items():
        res = simulate_fast(uni, return_details=True)
        flag = "🌟 100% WIN" if res['winning_coins'] == res['total_coins'] else f"⚠️ {res['winning_coins']}/{res['total_coins']}"
        print(f"{name:25s} -> Cap: ${res['cap']:.2f} (+{res['roe']:.1f}%) | Trades: {res['trades']} (+{res['trades'] - r_mega['trades']}) | WR: {res['wr']:.1f}% | PF: {res['pf']:.2f} | Sharpe: {res['sharpe_monthly']:.2f} | DD: {res['max_trade_dd']:.2f}% [{flag}]")
        if res['winning_coins'] == res['total_coins'] and res['cap'] > best_cap:
            best_cap = res['cap']
            best_name = name
            best_res = res

    print("\n" + "=" * 70)
    print(f"3. CHAMPION UNIVERSE SELECTED: {best_name}")
    print("=" * 70)
    champ = best_res
    print(f"Ending Capital: ${champ['cap']:.2f} (Net Profit: ${champ['net']:.2f}, +{champ['roe']:.2f}%)")
    print(f"Total Trades: {champ['trades']} (+{champ['trades'] - r_mega['trades']} trades, +{(champ['trades']/r_mega['trades']-1)*100:.1f}%)")
    print(f"Win Rate: {champ['wr']:.2f}% (vs Mega-22 {r_mega['wr']:.2f}%)")
    print(f"Profit Factor: {champ['pf']:.2f} (vs Mega-22 {r_mega['pf']:.2f})")
    print(f"Monthly Sharpe: {champ['sharpe_monthly']:.2f} (vs Mega-22 {r_mega['sharpe_monthly']:.2f})")
    print(f"Max Trade Drawdown: {champ['max_trade_dd']:.2f}% (vs Mega-22 {r_mega['max_trade_dd']:.2f}%)")
    print(f"Max Monthly Drawdown: {champ['max_monthly_dd']:.2f}% (vs Mega-22 {r_mega['max_monthly_dd']:.2f}%)")
    print(f"Winning Coins: {champ['winning_coins']}/{champ['total_coins']} (100.0% of coins profitable)")

    # Detailed trade frequency & drought analysis
    total_hours = 32 * 30.416 * 24  # ~23,360 hours
    m22_hours_per_trade = total_hours / r_mega['trades']
    champ_hours_per_trade = total_hours / champ['trades']
    print("\n--- TRADE VELOCITY & DRY-SPELL ELIMINATION ---")
    print(f"Mega-22 Trade Velocity: 1 trade every {m22_hours_per_trade:.1f} hours ({r_mega['trades']/32.0:.1f} trades/month)")
    print(f"Champion Trade Velocity: 1 trade every {champ_hours_per_trade:.1f} hours ({champ['trades']/32.0:.1f} trades/month)")
    print(f"Trade Density Increase: +{(champ['trades']/r_mega['trades']-1)*100:.1f}% higher activity, reducing multi-day idle intervals by ~{(1 - champ_hours_per_trade/m22_hours_per_trade)*100:.1f}%")

    print("\n--- INDIVIDUAL COIN CONTRIBUTION (CHAMPION) ---")
    print(champ['coin_pnl'].to_string())

    # Save institutional audit artifacts
    champ['coin_pnl'].to_csv('apex_champion_coin_pnl.csv')
    champ['df_trades'].to_csv('apex_champion_trades.csv', index=False)
    champ['df_m'].to_csv('apex_champion_monthly.csv', index=False)

    champ_universe = list(champ['coin_pnl'].index)
    added_coins = [s for s in champ_universe if s not in MEGA_22]

    with open('selected_apex_universe.json', 'w') as f:
        json.dump({
            'name': best_name,
            'golden_11': GOLDEN_11,
            'titan_11': TITAN_11,
            'mega_22': MEGA_22,
            'apex_additions': added_coins,
            'champion_universe': champ_universe,
            'baseline_mega22': {
                'ending_cap': r_mega['cap'],
                'net_profit': r_mega['net'],
                'roe': r_mega['roe'],
                'trades': r_mega['trades'],
                'win_rate': r_mega['wr'],
                'profit_factor': r_mega['pf'],
                'sharpe_monthly': r_mega['sharpe_monthly'],
                'max_trade_dd': r_mega['max_trade_dd'],
                'max_monthly_dd': r_mega['max_monthly_dd'],
                'winning_coins': r_mega['winning_coins'],
                'total_coins': r_mega['total_coins']
            },
            'champion_metrics': {
                'ending_cap': champ['cap'],
                'net_profit': champ['net'],
                'roe': champ['roe'],
                'trades': champ['trades'],
                'win_rate': champ['wr'],
                'profit_factor': champ['pf'],
                'sharpe_monthly': champ['sharpe_monthly'],
                'max_trade_dd': champ['max_trade_dd'],
                'max_monthly_dd': champ['max_monthly_dd'],
                'winning_coins': champ['winning_coins'],
                'total_coins': champ['total_coins']
            }
        }, f, indent=2)

    print("\nSuccessfully saved institutional audit artifacts to:")
    print("  - apex_champion_coin_pnl.csv")
    print("  - apex_champion_trades.csv")
    print("  - apex_champion_monthly.csv")
    print("  - selected_apex_universe.json")

