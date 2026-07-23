import os
import json
import time
import urllib.request
import urllib.error
import pandas as pd
import numpy as np
from catboost import CatBoostRegressor
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

def query_deepseek_medallion_judge(api_key, df_slice, current_bar_idx, ml_pred):
    context_bars = df_slice.iloc[current_bar_idx-4:current_bar_idx+1]
    last_bar = context_bars.iloc[-1]
    
    timestamp = last_bar['timestamp']
    close_p = float(last_bar['close'])
    spread_z = float(last_bar['spread_zscore'])
    r_vol = float(last_bar['realized_vol_5'])
    
    table_str = context_bars[[
        'timestamp', 'close', 'realized_vol_5', 'spread_zscore', 'ret_1'
    ]].to_string(index=False)
    
    prompt = f"""You are Lead Portfolio Manager at Renaissance Technologies (Jim Simons' Medallion Fund).
Data:
{table_str}

Context:
- Current Spread Z-Score: {spread_z:.2f}
- ML Return Forecast (5-bar lead): {ml_pred:.4f}
- Realized Volatility: {r_vol:.5f}

Medallion Rules:
1. BUY: ML Forecast > +0.0008 & Spread Z-score < +0.5 & low volatility regime.
2. SHORT: ML Forecast < -0.0008 & Spread Z-score > -0.5 & low volatility regime.
3. Output HOLD if noise or high-volatility spike.

Output strict JSON:
{{
  "decision": "BUY" | "SHORT" | "HOLD",
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
                decision_data['close'] = close_p
                decision_data['spread_z'] = spread_z
                decision_data['ml_pred'] = ml_pred
                return decision_data
        except Exception:
            time.sleep(1.0)
            
    return {
        "bar_idx": current_bar_idx,
        "timestamp": str(timestamp),
        "close": close_p,
        "spread_z": spread_z,
        "ml_pred": ml_pred,
        "decision": "HOLD",
        "confidence": 0.0,
        "reasoning": "API failed"
    }

def run_jim_simons_medallion_strategy():
    dataset_path = "processed_data/gold_silver_pairs_dataset.csv"
    if not os.path.exists(dataset_path):
        print("❌ Dataset missing.")
        return
        
    df = pd.read_csv(dataset_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    df['ret_1'] = df['close'].pct_change(1)
    df['realized_vol_5'] = df['ret_1'].rolling(5).std().fillna(0.001)
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    df['atr_5'] = ranges.max(axis=1).rolling(5).mean().fillna(2.0)
    
    # Load Pairs ML Model
    model_path = "processed_data/pairs_ml_model.cbm"
    ml_preds_all = np.zeros(len(df))
    if os.path.exists(model_path):
        ml_model = CatBoostRegressor()
        ml_model.load_model(model_path)
        feature_cols = ['close', 'mid_silver', 'rolling_beta', 'spread_val', 'spread_zscore', 'spread_velocity', 'gold_ret_1', 'silver_ret_1']
        ml_preds_all = ml_model.predict(df[feature_cols])
        
    last_time = df['timestamp'].max()
    start_time = last_time - pd.Timedelta(days=30)
    
    df_sliced = df[df['timestamp'] >= start_time - pd.Timedelta(days=5)].copy().reset_index(drop=True)
    start_bar_indices = df_sliced[df_sliced['timestamp'] >= start_time].index.tolist()
    start_idx = start_bar_indices[0]
    
    test_indices = list(range(start_idx, len(df_sliced) - 15, 1))
    
    api_key = load_env_key()
    if not api_key:
        print("❌ DEEPSEEK_API_KEY missing.")
        return
        
    api_indices = []
    for idx in test_indices:
        last_b = df_sliced.iloc[idx]
        sp_z = float(last_b['spread_zscore'])
        ml_p = float(ml_preds_all[idx])
        if abs(ml_p) > 0.0005 or abs(sp_z) >= 1.0:
            api_indices.append((idx, ml_p))
            
    print(f"🏛️ Running Jim Simons' Medallion Fund Strategy over {len(test_indices)} bars | Querying API for {len(api_indices)} setups...")
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(query_deepseek_medallion_judge, api_key, df_sliced, idx, ml_p): idx 
            for idx, ml_p in api_indices
        }
        for future in as_completed(futures):
            results.append(future.result())
            
    results = sorted(results, key=lambda x: x['bar_idx'])
    
    start_balance = 10000.0
    current_balance = start_balance
    base_target_cash_risk = 60.0 # $60 target risk per trade (0.6% of account)
    
    trades_executed = []
    
    all_timestamps = df_sliced.loc[start_idx:, 'timestamp'].reset_index(drop=True)
    equity_history = pd.DataFrame({'timestamp': all_timestamps})
    equity_history['equity'] = current_balance
    equity_history.set_index('timestamp', inplace=True)
    
    df_sliced['date'] = df_sliced['timestamp'].dt.date
    current_day = None
    day_start_balance = start_balance
    daily_circuit_broken = False
    
    i = 0
    while i < len(results):
        res = results[i]
        decision = res['decision']
        confidence = float(res.get('confidence', 0.0))
        bar_idx = res['bar_idx']
        
        bar_date = df_sliced.loc[bar_idx, 'date']
        if bar_date != current_day:
            current_day = bar_date
            day_start_balance = current_balance
            daily_circuit_broken = False
            
        current_daily_dd = (day_start_balance - current_balance) / day_start_balance
        if current_daily_dd >= 0.018: # Hard 1.8% Daily Stop Circuit Breaker!
            daily_circuit_broken = True
            
        if daily_circuit_broken:
            i += 1
            continue
            
        if decision in ['BUY', 'SHORT'] and confidence >= 0.60:
            entry_idx = bar_idx
            entry_time = pd.to_datetime(res['timestamp'])
            entry_price = res['close']
            r_vol = float(df_sliced.loc[entry_idx, 'realized_vol_5'])
            atr = float(df_sliced.loc[entry_idx, 'atr_5'])
            
            vol_scaler = min(1.4, max(0.7, 0.001 / (r_vol + 1e-8)))
            cash_risk = base_target_cash_risk * vol_scaler * confidence
            
            sl_dist = 1.5 * atr
            tp_dist = 2.8 * atr # High RRR
            
            sl_pct = sl_dist / entry_price
            position_usd = cash_risk / (sl_pct + 1e-8)
            units = position_usd / entry_price
            
            if decision == 'BUY':
                tp_price = entry_price + tp_dist
                sl_price = entry_price - sl_dist
            else:
                tp_price = entry_price - tp_dist
                sl_price = entry_price + sl_dist
                
            outcome = None
            exit_price = None
            exit_idx = entry_idx
            
            for f_idx in range(entry_idx + 1, min(entry_idx + 18, len(df_sliced))):
                f_row = df_sliced.iloc[f_idx]
                f_high = f_row['high']
                f_low = f_row['low']
                
                if decision == 'BUY':
                    if f_low <= sl_price:
                        outcome = 'LOSS'
                        exit_price = sl_price
                        exit_idx = f_idx
                        break
                    elif f_high >= tp_price:
                        outcome = 'WIN'
                        exit_price = tp_price
                        exit_idx = f_idx
                        break
                else:
                    if f_high >= sl_price:
                        outcome = 'LOSS'
                        exit_price = sl_price
                        exit_idx = f_idx
                        break
                    elif f_low <= tp_price:
                        outcome = 'WIN'
                        exit_price = tp_price
                        exit_idx = f_idx
                        break
                        
            if outcome is None:
                outcome = 'TIME_EXIT'
                exit_idx = min(entry_idx + 17, len(df_sliced) - 1)
                exit_price = df_sliced.loc[exit_idx, 'close']
                
            exit_time = pd.to_datetime(df_sliced.loc[exit_idx, 'timestamp'])
            
            if decision == 'BUY':
                raw_pnl = units * (exit_price - entry_price)
            else:
                raw_pnl = units * (entry_price - exit_price)
                
            costs = 3.50
            net_pnl = raw_pnl - costs
            
            old_balance = current_balance
            current_balance += net_pnl
            
            for f_idx in range(entry_idx, exit_idx + 1):
                t_bar = pd.to_datetime(df_sliced.loc[f_idx, 'timestamp'])
                t_close = df_sliced.loc[f_idx, 'close']
                if decision == 'BUY':
                    f_pnl = units * (t_close - entry_price)
                else:
                    f_pnl = units * (entry_price - t_close)
                equity_history.loc[t_bar, 'equity'] = old_balance + f_pnl
                
            equity_history.loc[exit_time:, 'equity'] = current_balance
            
            trades_executed.append({
                'entry_time': entry_time.strftime('%Y-%m-%d %H:%M'),
                'exit_time': exit_time.strftime('%Y-%m-%d %H:%M'),
                'type': decision,
                'cash_risk': cash_risk,
                'outcome': outcome,
                'cash_profit': net_pnl,
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
    print("   JIM SIMONS' MEDALLION FUND STRATEGY SUMMARY (June)")
    print("=======================================================")
    print(f" Starting Balance       : ${start_balance:,.2f}")
    print(f" Final Balance          : ${current_balance:,.2f}")
    print(f" Net Profit/Loss ($)    : ${current_balance - start_balance:+,.2f} ({((current_balance - start_balance)/start_balance):+.2%})")
    print(f" Total Trades Executed  : {len(trades_executed)}")
    print(f" Max Daily Drawdown     : {daily_df['daily_dd_from_start'].max():.2%} (Prop Firm Limit: 5.0%)")
    print(f" Max Total Drawdown     : {max_total_dd:.2%} (Prop Firm Limit: 10.0%)")
    
    if trades_executed:
        wins = [t for t in trades_executed if t['cash_profit'] > 0]
        win_rate = len(wins) / len(trades_executed)
        print(f" Win Rate               : {win_rate:.2%}")
        print("\nExecuted Trades Ledger (Sample):")
        for idx, t in enumerate(trades_executed[:10]):
            print(f" #{idx+1}: {t['type']} | Risk: ${t['cash_risk']:.2f} | Outcome: {t['outcome']} | PnL: ${t['cash_profit']:+,.2f}")
    print("=======================================================\n")

if __name__ == '__main__':
    run_jim_simons_medallion_strategy()
