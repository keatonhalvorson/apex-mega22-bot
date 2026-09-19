import pickle
import json
import numpy as np
import pandas as pd
from pathlib import Path

with open('cached_compact_expanded.pkl', 'rb') as f:
    cached_months = pickle.load(f)

months = sorted(list(cached_months.keys()))

CONFIRMED_25 = [
    'ORDIUSDT', 'ICPUSDT', 'GALAUSDT', 'NEARUSDT', 'TIAUSDT',
    'RENDERUSDT', 'ALGOUSDT', 'XLMUSDT', 'DOGEUSDT', 'TRXUSDT',
    'BONKUSDT', 'POLUSDT', 'HBARUSDT', 'FILUSDT', 'APTUSDT',
    'XRPUSDT', 'ENSUSDT', 'FETUSDT', 'VETUSDT', 'AVAXUSDT',
    'SEIUSDT', 'OPUSDT', 'DOTUSDT', 'ETHUSDT', 'UNIUSDT'
]
REPLACEMENTS_5 = ['ADAUSDT', 'LINKUSDT', 'LTCUSDT', 'ATOMUSDT', 'SOLUSDT']
APEX_35_EXPANSION = ['CKBUSDT', 'ROSEUSDT', 'JASMYUSDT', 'PYTHUSDT', 'ANKRUSDT']
APEX_35 = CONFIRMED_25 + REPLACEMENTS_5 + APEX_35_EXPANSION

def run_institutional_engine():
    universe = APEX_35
    initial_capital = 1000.0
    max_slots = 3
    slot_frac = 0.32
    enable_rotation = True
    rot_cand_threshold = 15.0
    rot_held_bars = 18
    rot_max_pnl = 0.002
    rot_min_pnl = -0.015
    score_edge = 5.0
    stall_bars = 60
    tp_target = 0.065
    sl_target = 0.022
    fee = 0.0004
    slip = 0.0002

    cap = initial_capital
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

                # Parabolic profit locking
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
                is_stalled = (held >= stall_bars) and (pnl < 0.001) and (worst_pnl < -0.010)

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
                        'notional': pos['notional'], 'held': held, 'cap_after': inst_cap
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

            # Candidate collection
            cands = []
            if i > stoploss_guard_until:
                for sym in symbols:
                    if sym not in active_positions and i > cooldowns[sym]:
                        if coin_dfs[sym]['is_candidate'][i - 1] == 1:
                            score = float(coin_dfs[sym]['score'][i - 1])
                            cands.append((sym, score))
                cands.sort(key=lambda x: x[1], reverse=True)

            # Opportunity-Aware Eviction
            if enable_rotation and len(active_positions) >= max_slots and len(cands) > 0:
                top_cand_sym, top_cand_score = cands[0]
                if top_cand_score >= rot_cand_threshold:
                    evictable = []
                    for sym, pos in active_positions.items():
                        held = i - pos['i']
                        df_s = coin_dfs[sym]
                        c = float(df_s['close'][i])
                        pnl = (c - pos['px']) / pos['px']
                        pos_score = pos.get('score', 0.0)
                        if held >= rot_held_bars and rot_min_pnl <= pnl <= rot_max_pnl and pos['stop'] > 0:
                            if (top_cand_score - pos_score) >= score_edge:
                                evictable.append((sym, held, pnl, pos_score))
                    if evictable:
                        evictable.sort(key=lambda x: -x[1])
                        sym_evict = evictable[0][0]
                        pos = active_positions[sym_evict]
                        df_s = coin_dfs[sym_evict]
                        c = float(df_s['close'][i])
                        exit_px = c * (1.0 - slip)
                        gross = (exit_px - pos['px']) / pos['px'] * pos['notional']
                        exit_fee = pos['notional'] * fee
                        net = gross - exit_fee - pos['entry_fee']
                        inst_cap += (pos['notional'] + gross - exit_fee)
                        m_trades.append({
                            'sym': sym_evict, 'month': ym, 'net': net, 'pnl_pct': (exit_px / pos['px'] - 1) * 100.0,
                            'reason': 'ROTATION_EVICT', 'entry_px': pos['px'], 'exit_px': exit_px,
                            'notional': pos['notional'], 'held': held, 'cap_after': inst_cap
                        })
                        del active_positions[sym_evict]

            # Slot entry with Equal-Equity Sizing
            if len(active_positions) < max_slots and i > stoploss_guard_until:
                avail = max_slots - len(active_positions)
                valid_cands = [c for c in cands if c[0] not in active_positions]
                for sym, score in valid_cands[:avail]:
                    df_s = coin_dfs[sym]
                    o = float(df_s['open'][i])

                    total_equity = inst_cap + sum(p['notional'] for p in active_positions.values())
                    target_notional = min(total_equity * slot_frac, inst_cap / (1.0 + fee))

                    if inst_cap >= target_notional and target_notional > 50.0:
                        epx = o * (1.0 + slip)
                        ef = target_notional * fee
                        inst_cap -= (target_notional + ef)
                        active_positions[sym] = {
                            'px': epx, 'notional': target_notional, 'i': i, 'stop': sl_target,
                            'entry_fee': ef, 'score': score
                        }

        # Month end close
        for sym, pos in list(active_positions.items()):
            df_s = coin_dfs[sym]
            c = float(df_s['close'][-1])
            gross = (c - pos['px']) / pos['px'] * pos['notional']
            exit_fee = pos['notional'] * fee
            net = gross - exit_fee - pos['entry_fee']
            inst_cap += (pos['notional'] + gross - exit_fee)
            m_trades.append({
                'sym': sym, 'month': ym, 'net': net, 'pnl_pct': (c / pos['px'] - 1) * 100.0,
                'reason': 'MONTH_END', 'entry_px': pos['px'], 'exit_px': c,
                'notional': pos['notional'], 'held': n_bars - pos['i'], 'cap_after': inst_cap
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

    coin_pnl = df_trades.groupby('sym')['net'].sum().reset_index()
    coin_pnl.columns = ['sym', 'net_pnl']
    coin_pnl['trades'] = df_trades.groupby('sym')['net'].count().values
    coin_pnl['win_rate'] = df_trades.groupby('sym').apply(lambda x: (x['net'] > 0).mean() * 100.0).values
    coin_pnl = coin_pnl.sort_values('net_pnl', ascending=False)

    winning_coins = int((coin_pnl['net_pnl'] > 0).sum())
    total_coins = int(len(coin_pnl))

    print(f"\nINSTITUTIONAL APEX-35 CHAMPION METRICS:")
    print(f"Starting Capital: ${initial_capital:.2f}")
    print(f"Ending Capital:   ${cap:.2f}")
    print(f"Net Profit:       ${net_profit:.2f} (+{roe:.2f}% ROE)")
    print(f"Total Trades:     {n_trades}")
    print(f"Win Rate:         {win_rate:.2f}%")
    print(f"Profit Factor:    {pf:.2f}")
    print(f"Sharpe (Monthly): {sharpe_monthly:.2f}")
    print(f"Max Trade DD:     {max_trade_dd:.2f}%")
    print(f"Max Monthly DD:   {max_monthly_dd:.2f}%")
    print(f"Winning Coins:    {winning_coins}/{total_coins} (100% Halal Spot)")

    # Save detailed CSV files
    df_trades.to_csv('new_halal_apex35_trades.csv', index=False)
    df_m.to_csv('new_halal_apex35_monthly.csv', index=False)
    coin_pnl.to_csv('new_halal_apex35_coin_pnl.csv', index=False)
    print("Saved trades, monthly, and coin PnL CSVs.")

    # Update selected_apex_universe.json
    metrics = {
        "name": "Apex-35 Institutional Sovereign (100% Halal Spot)",
        "golden_11": CONFIRMED_25[:11],
        "titan_11": CONFIRMED_25[11:22],
        "mega_22": CONFIRMED_25[:22],
        "apex_additions": CONFIRMED_25[22:] + REPLACEMENTS_5,
        "apex_35_expansion": APEX_35_EXPANSION,
        "champion_universe": APEX_35,
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
            "net_profit": float(net_profit),
            "roe": float(roe),
            "trades": int(n_trades),
            "win_rate": float(win_rate),
            "profit_factor": float(pf),
            "sharpe_monthly": float(sharpe_monthly),
            "max_trade_dd": float(max_trade_dd),
            "max_monthly_dd": float(max_monthly_dd),
            "winning_coins": int(winning_coins),
            "total_coins": int(total_coins)
        }
    }
    with open('selected_apex_universe.json', 'w') as f:
        json.dump(metrics, f, indent=2)
    print("Updated selected_apex_universe.json successfully.")

if __name__ == '__main__':
    run_institutional_engine()
