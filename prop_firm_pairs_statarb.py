import os
import json
import time
import urllib.request
import urllib.error
import pandas as pd
import numpy as np
from concurrent.futures import ThreadPoolExecutor, as_completed

def load_env_key():
    env_path = "/home/atheer/Desktop/ApexPredator/download data/.env"
    if not os.path.exists(env_path):
        return None
    with open(env_path, "r") as f:
        for line in f:
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.strip().split("=")[1]
    return None

def run_kalman_filter_beta(log_gold, log_silver):
    n = len(log_gold)
    beta = np.zeros(n)
    P = np.zeros(n)
    beta[0] = 0.85
    P[0] = 1.0
    Vw = 1e-4
    Ve = 1e-3
    for t in range(1, n):
        beta_pred = beta[t-1]
        P_pred = P[t-1] + Vw
        x = log_silver.iloc[t]
        y = log_gold.iloc[t]
        e = y - beta_pred * x
        Q = x * P_pred * x + Ve
        K = P_pred * x / Q
        beta[t] = beta_pred + K * e
        P[t] = (1 - K * x) * P_pred
    return beta

def query_deepseek_pairs_judge(api_key, df_slice, current_bar_idx):
    context_bars = df_slice.iloc[current_bar_idx-4:current_bar_idx+1]
    last_bar = context_bars.iloc[-1]
    
    timestamp = last_bar['timestamp']
    gold_price = float(last_bar['close'])
    silver_price = float(last_bar['mid_silver'])
    spread_z = float(last_bar['spread_zscore'])
    beta = float(last_bar['kalman_beta'])
    
    table_str = context_bars[[
        'timestamp', 'close', 'mid_silver', 'kalman_beta', 'spread_zscore'
    ]].to_string(index=False)
    
    prompt = f"""You are a Lead Quantitative Research Scientist managing a Market-Neutral StatArb Fund (Gold vs Silver).
Data:
{table_str}

Rules:
1. LONG_PAIR (BUY Gold + SHORT Silver): If spread_zscore < -2.0 & reversion momentum confirmed.
2. SHORT_PAIR (SHORT Gold + BUY Silver): If spread_zscore > +2.0 & reversion momentum confirmed.
3. If momentum is decaying or spread is decoupling, output HOLD.

Output strict JSON:
{{
  "decision": "LONG_PAIR" | "SHORT_PAIR" | "HOLD",
  "confidence": <float 0.0 to 1.0>,
  "reasoning": "<concise 1 sentence>"
}}"""

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {api_key}"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.0,
        "max_tokens": 100
    }
    
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST'
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                resp_body = response.read().decode('utf-8')
                resp_json = json.loads(resp_body)
                raw_content = resp_json['choices'][0]['message']['content']
                decision_data = json.loads(raw_content.strip())
                
                decision_data['bar_idx'] = current_bar_idx
                decision_data['timestamp'] = str(timestamp)
                decision_data['gold_price'] = gold_price
                decision_data['silver_price'] = silver_price
                decision_data['spread_z'] = spread_z
                decision_data['beta'] = beta
                return decision_data
        except Exception:
            time.sleep(1.0)
            
    return {
        "bar_idx": current_bar_idx,
        "timestamp": str(timestamp),
        "gold_price": gold_price,
        "silver_price": silver_price,
        "spread_z": spread_z,
        "beta": beta,
        "decision": "HOLD",
        "confidence": 0.0,
        "reasoning": "API failed"
    }

def run_simulation_mathematical_solution(period_days=30):
    dataset_path = "processed_data/gold_silver_pairs_dataset.csv"
    if not os.path.exists(dataset_path):
        print("❌ Dataset missing.")
        return
        
    df = pd.read_csv(dataset_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    print(f"⏳ Applying Kalman Filter & Volatility Sizing over {period_days}-Day Out-of-Sample Period...")
    df['kalman_beta'] = run_kalman_filter_beta(df['log_gold'], df['log_silver'])
    
    gold_vol = df['close'].pct_change().rolling(30).std()
    silver_vol = df['mid_silver'].pct_change().rolling(30).std()
    df['vol_ratio'] = gold_vol / (silver_vol + 1e-8)
    
    df['spread_val'] = df['log_gold'] - (df['kalman_beta'] * df['log_silver'])
    spread_mean = df['spread_val'].rolling(30).mean()
    spread_std = df['spread_val'].rolling(30).std()
    df['spread_zscore'] = (df['spread_val'] - spread_mean) / (spread_std + 1e-8)
    
    df = df.dropna().reset_index(drop=True)
    
    last_time = df['timestamp'].max()
    start_time = last_time - pd.Timedelta(days=period_days)
    
    df_sliced = df[df['timestamp'] >= start_time - pd.Timedelta(days=5)].copy().reset_index(drop=True)
    start_bar_indices = df_sliced[df_sliced['timestamp'] >= start_time].index.tolist()
    start_idx = start_bar_indices[0]
    
    test_indices = list(range(start_idx, len(df_sliced) - 20, 2))
    
    api_key = load_env_key()
    if not api_key:
        print("❌ DEEPSEEK_API_KEY missing.")
        return
        
    api_indices = []
    for idx in test_indices:
        last_b = df_sliced.iloc[idx]
        sp_z = float(last_b['spread_zscore'])
        if abs(sp_z) >= 2.0:
            api_indices.append(idx)
            
    print(f"📊 Evaluated {len(test_indices)} bars | Pre-filtered {len(test_indices)-len(api_indices)} dull bars | Querying DeepSeek API for {len(api_indices)} candidates...")
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(query_deepseek_pairs_judge, api_key, df_sliced, idx): idx 
            for idx in api_indices
        }
        for future in as_completed(futures):
            results.append(future.result())
            
    results = sorted(results, key=lambda x: x['bar_idx'])
    
    # -------------------------------------------------------------
    # SIMULATION WITH DEEPSEEK META-JUDGE
    # -------------------------------------------------------------
    start_balance = 10000.0
    current_balance = start_balance
    trades_executed = []
    
    all_timestamps = df_sliced.loc[start_idx:, 'timestamp'].reset_index(drop=True)
    equity_history = pd.DataFrame({'timestamp': all_timestamps})
    equity_history['equity'] = current_balance
    equity_history.set_index('timestamp', inplace=True)
    
    i = 0
    while i < len(results):
        res = results[i]
        decision = res['decision']
        confidence = float(res.get('confidence', 0.0))
        
        if decision in ['LONG_PAIR', 'SHORT_PAIR'] and confidence >= 0.65:
            entry_idx = res['bar_idx']
            entry_time = pd.to_datetime(res['timestamp'])
            entry_gold_p = res['gold_price']
            entry_silver_p = res['silver_price']
            vol_r = float(df_sliced.loc[entry_idx, 'vol_ratio'])
            spread_z = res['spread_z']
            
            # DYNAMIC 1.0% RISK POSITION SIZING
            cash_risk = current_balance * 0.01
            atr_gold = float(df_sliced.loc[entry_idx, 'close']) * 0.005 # ~0.5% ATR
            
            gold_lots = max(0.04, min(0.18, cash_risk / (1.5 * atr_gold * 100.0 + 1e-8)))
            gold_oz = gold_lots * 100.0
            gold_usd_val = gold_oz * entry_gold_p
            
            silver_usd_val = gold_usd_val * vol_r * 0.85
            silver_oz = silver_usd_val / (entry_silver_p + 1e-8)
            silver_lots = silver_oz / 5000.0
            
            outcome = None
            exit_gold_p = entry_gold_p
            exit_silver_p = entry_silver_p
            exit_idx = entry_idx
            
            for f_idx in range(entry_idx + 1, min(entry_idx + 25, len(df_sliced))):
                f_row = df_sliced.iloc[f_idx]
                c_z = f_row['spread_zscore']
                c_g = f_row['close']
                c_s = f_row['mid_silver']
                
                if decision == 'LONG_PAIR':
                    g_pnl = gold_oz * (c_g - entry_gold_p)
                    s_pnl = silver_oz * (entry_silver_p - c_s)
                else:
                    g_pnl = gold_oz * (entry_gold_p - c_g)
                    s_pnl = silver_oz * (c_s - entry_silver_p)
                    
                net_float = (g_pnl + s_pnl) - 4.0
                
                if ((decision == 'LONG_PAIR' and c_z >= -0.2) or (decision == 'SHORT_PAIR' and c_z <= 0.2)) and net_float > 10.0:
                    outcome = 'PROFIT_REVERSION'
                    exit_gold_p = c_g
                    exit_silver_p = c_s
                    exit_idx = f_idx
                    break
                    
                if abs(c_z) >= 3.4 or net_float <= -120.0: # Tight Cap SL
                    outcome = 'STOP_LOSS'
                    exit_gold_p = c_g
                    exit_silver_p = c_s
                    exit_idx = f_idx
                    break
                    
            if outcome is None:
                outcome = 'TIME_EXIT'
                exit_idx = min(entry_idx + 24, len(df_sliced) - 1)
                exit_gold_p = df_sliced.loc[exit_idx, 'close']
                exit_silver_p = df_sliced.loc[exit_idx, 'mid_silver']
                
            exit_time = pd.to_datetime(df_sliced.loc[exit_idx, 'timestamp'])
            
            if decision == 'LONG_PAIR':
                gold_pnl = gold_oz * (exit_gold_p - entry_gold_p)
                silver_pnl = silver_oz * (entry_silver_p - exit_silver_p)
            else:
                gold_pnl = gold_oz * (entry_gold_p - exit_gold_p)
                silver_pnl = silver_oz * (exit_silver_p - entry_silver_p)
                
            total_net_pnl = (gold_pnl + silver_pnl) - 4.0
            
            old_balance = current_balance
            current_balance += total_net_pnl
            
            for f_idx in range(entry_idx, exit_idx + 1):
                t_bar = pd.to_datetime(df_sliced.loc[f_idx, 'timestamp'])
                t_g = df_sliced.loc[f_idx, 'close']
                t_s = df_sliced.loc[f_idx, 'mid_silver']
                if decision == 'LONG_PAIR':
                    f_pnl = (gold_oz * (t_g - entry_gold_p)) + (silver_oz * (entry_silver_p - t_s))
                else:
                    f_pnl = (gold_oz * (entry_gold_p - t_g)) + (silver_oz * (t_s - entry_silver_p))
                equity_history.loc[t_bar, 'equity'] = old_balance + f_pnl
                
            equity_history.loc[exit_time:, 'equity'] = current_balance
            
            trades_executed.append({
                'entry_time': entry_time.strftime('%Y-%m-%d %H:%M'),
                'exit_time': exit_time.strftime('%Y-%m-%d %H:%M'),
                'type': decision,
                'entry_spread_z': spread_z,
                'outcome': outcome,
                'cash_profit': total_net_pnl,
                'balance_after': current_balance,
                'reasoning': res.get('reasoning', '')
            })
            
            next_i = i + 1
            while next_i < len(results) and results[next_i]['bar_idx'] <= exit_idx:
                next_i += 1
            i = next_i
        else:
            i += 1
            
    # Calculate Daily Drawdowns
    equity_history['date'] = equity_history.index.date
    daily_groups = equity_history.groupby('date')
    
    daily_stats = []
    prev_day_close_balance = start_balance
    
    for date, group in daily_groups:
        day_open = prev_day_close_balance
        day_low = group['equity'].min()
        day_close = group['equity'].iloc[-1]
        
        daily_dd_from_start = max(0.0, (day_open - day_low) / day_open)
        daily_stats.append({
            'date': date,
            'day_open': day_open,
            'day_close': day_close,
            'daily_dd_from_start': daily_dd_from_start
        })
        prev_day_close_balance = day_close
        
    daily_df = pd.DataFrame(daily_stats)
    
    equity_history['peak'] = equity_history['equity'].cummax()
    equity_history['drawdown'] = (equity_history['peak'] - equity_history['equity']) / equity_history['peak']
    max_total_dd = equity_history['drawdown'].max()
    
    print("\n=======================================================")
    print(f"   DEEPSEEK + KALMAN PAIR TRADING SUMMARY (Last {period_days} Days)")
    print("=======================================================")
    print(f" Starting Balance       : ${start_balance:,.2f}")
    print(f" Final Balance          : ${current_balance:,.2f}")
    print(f" Net Profit/Loss ($)    : ${current_balance - start_balance:+,.2f} ({((current_balance - start_balance)/start_balance):+.2%})")
    print(f" Total Pair Trades      : {len(trades_executed)}")
    print(f" Max Daily Drawdown     : {daily_df['daily_dd_from_start'].max():.2%} (Prop Firm Limit: 5.0%)")
    print(f" Max Total Drawdown     : {max_total_dd:.2%} (Prop Firm Limit: 10.0%)")
    
    if trades_executed:
        wins = [t for t in trades_executed if t['cash_profit'] > 0]
        win_rate = len(wins) / len(trades_executed)
        print(f" StatArb Win Rate       : {win_rate:.2%}")
        print("\nExecuted Pair Trades Ledger (Sample):")
        for idx, t in enumerate(trades_executed[:10]):
            print(f" #{idx+1}: {t['type']} at {t['entry_time']} | Entry Z: {t['entry_spread_z']:.2f} | Outcome: {t['outcome']} | PnL: ${t['cash_profit']:+,.2f}")
    print("=======================================================\n")

if __name__ == '__main__':
    run_simulation_mathematical_solution(30)
