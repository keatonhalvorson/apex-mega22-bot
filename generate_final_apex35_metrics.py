import pickle
import json
import pandas as pd
import numpy as np

with open('cached_compact_expanded.pkl', 'rb') as f:
    cached_months = pickle.load(f)

months = sorted(list(cached_months.keys()))

# The confirmed 25 Halal baseline coins
CONFIRMED_25 = [
    'ORDIUSDT', 'ICPUSDT', 'GALAUSDT', 'NEARUSDT', 'TIAUSDT',
    'RENDERUSDT', 'ALGOUSDT', 'XLMUSDT', 'DOGEUSDT', 'TRXUSDT',
    'BONKUSDT', 'POLUSDT', 'HBARUSDT', 'FILUSDT', 'APTUSDT',
    'XRPUSDT', 'ENSUSDT', 'FETUSDT', 'VETUSDT', 'AVAXUSDT',
    'SEIUSDT', 'OPUSDT', 'DOTUSDT', 'ETHUSDT', 'UNIUSDT'
]

# The 5 replacements from APEX_30
REPLACEMENTS_5 = ['ADAUSDT', 'LINKUSDT', 'LTCUSDT', 'ATOMUSDT', 'SOLUSDT']

APEX_30 = CONFIRMED_25 + REPLACEMENTS_5

# The 5 Champion Halal expansion coins for APEX_35
APEX_35_EXPANSION = ['CKBUSDT', 'ROSEUSDT', 'JASMYUSDT', 'PYTHUSDT', 'ANKRUSDT']

APEX_35 = APEX_30 + APEX_35_EXPANSION

def simulate_fast(universe, initial_capital=1000.0, max_slots=3, slot_frac=0.32):
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
                        'reason': reason, 'entry_px': pos['px'], 'exit_px': exit_px, 'notional': pos['notional'],
                        'cap_after': inst_cap
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
                'reason': 'MONTH_END', 'entry_px': pos['px'], 'exit_px': c, 'notional': pos['notional'],
                'cap_after': inst_cap
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

    wins = df_trades[df_trades['net'] > 0]['net'].sum()
    losses = abs(df_trades[df_trades['net'] < 0]['net'].sum())
    pf = wins / losses if losses > 0 else 999.0

    m_rets = df_m['m_ret'].values / 100.0
    sharpe_monthly = float((np.mean(m_rets) / np.std(m_rets, ddof=1) * np.sqrt(12)) if np.std(m_rets) > 0 else 0.0)

    cum_equity = initial_capital + np.cumsum(df_trades['net'].values)
    t_peak = np.maximum.accumulate(cum_equity)
    t_dds = (cum_equity - t_peak) / t_peak * 100.0
    max_trade_dd = float(np.min(t_dds)) if len(t_dds) > 0 else 0.0

    m_caps = [initial_capital] + df_m['cap'].tolist()
    m_peak = np.maximum.accumulate(m_caps)
    m_dds = (np.array(m_caps) - m_peak) / m_peak * 100.0
    max_monthly_dd = float(np.min(m_dds))

    coin_pnl = df_trades.groupby('sym').agg(
        trades=('net', 'count'),
        net_profit=('net', 'sum'),
        win_rate=('net', lambda x: float((x > 0).mean() * 100.0)),
        avg_pnl=('pnl_pct', 'mean')
    ).sort_values('net_profit', ascending=False)

    winning_coins = int((coin_pnl['net_profit'] > 0).sum())
    total_coins = int(len(coin_pnl))

    return {
        'cap': float(cap),
        'net': float(net_profit),
        'roe': float(roe),
        'trades': int(n_trades),
        'win_rate': float(win_rate),
        'profit_factor': float(pf),
        'sharpe_monthly': float(sharpe_monthly),
        'max_trade_dd': float(max_trade_dd),
        'max_monthly_dd': float(max_monthly_dd),
        'winning_coins': winning_coins,
        'total_coins': total_coins,
        'all_win': (winning_coins == len(universe)),
        'coin_pnl': coin_pnl,
        'df_trades': df_trades,
        'df_monthly': df_m
    }

print("Running simulation for APEX_35 Champion Universe...")
res = simulate_fast(APEX_35)

print("\n=================================================================")
print("             APEX-35 SOVEREIGN CHAMPION METRICS                  ")
print("=================================================================")
print(f"Initial Capital   : $1,000.00")
print(f"Ending Capital    : ${res['cap']:.2f}")
print(f"Net Profit        : ${res['net']:.2f}")
print(f"Net ROE           : +{res['roe']:.2f}%")
print(f"Total Trades      : {res['trades']}")
print(f"Win Rate          : {res['win_rate']:.2f}%")
print(f"Profit Factor     : {res['profit_factor']:.2f}")
print(f"Sharpe (Monthly)  : {res['sharpe_monthly']:.2f}")
print(f"Max Trade DD      : {res['max_trade_dd']:.2f}%")
print(f"Max Monthly DD    : {res['max_monthly_dd']:.2f}%")
print(f"Winning Coins     : {res['winning_coins']}/{res['total_coins']} (100.0% Win: {res['all_win']})")
print("=================================================================\n")

print("--- COIN BY COIN PERFORMANCE (RANKED BY NET PROFIT) ---")
print(res['coin_pnl'].to_string())

# Save artifacts
res['df_trades'].to_csv('new_halal_apex35_trades.csv', index=False)
res['df_monthly'].to_csv('new_halal_apex35_monthly.csv', index=False)
res['coin_pnl'].to_csv('new_halal_apex35_coin_pnl.csv')

# Update selected_apex_universe.json
with open('selected_apex_universe.json', 'r') as f:
    u_json = json.load(f)

u_json['name'] = "Apex-35 (Apex-30 + 5 Halal Champions) 100% Halal Spot"
u_json['apex_35_expansion'] = APEX_35_EXPANSION
u_json['apex_35'] = APEX_35
u_json['champion_universe'] = list(res['coin_pnl'].index)
u_json['champion_metrics_apex35'] = {
    'ending_cap': res['cap'],
    'net_profit': res['net'],
    'roe': res['roe'],
    'trades': res['trades'],
    'win_rate': res['win_rate'],
    'profit_factor': res['profit_factor'],
    'sharpe_monthly': res['sharpe_monthly'],
    'max_trade_dd': res['max_trade_dd'],
    'max_monthly_dd': res['max_monthly_dd'],
    'winning_coins': res['winning_coins'],
    'total_coins': res['total_coins']
}

with open('selected_apex_universe.json', 'w') as f:
    json.dump(u_json, f, indent=2)

print("\nArtifacts saved successfully:")
print(" - new_halal_apex35_trades.csv")
print(" - new_halal_apex35_monthly.csv")
print(" - new_halal_apex35_coin_pnl.csv")
print(" - selected_apex_universe.json updated")
