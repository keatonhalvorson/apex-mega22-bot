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

def query_deepseek_simons_judge(api_key, df_slice, current_bar_idx, ml_pred, regime_type):
    context_bars = df_slice.iloc[current_bar_idx-4:current_bar_idx+1]
    last_bar = context_bars.iloc[-1]
    
    timestamp = last_bar['timestamp']
    close_p = float(last_bar['close'])
    spread_z = float(last_bar['z_score'])
    ofi = float(last_bar['ofi_dollar'])
    flow = float(last_bar['signed_flow'])
    macro_res = float(last_bar['macro_residual_z_20'])
    
    table_str = context_bars[[
        'timestamp', 'close', 'signed_flow', 'ofi_dollar', 'z_score', 'macro_residual_z_20'
    ]].to_string(index=False)
    
    prompt = f"""You are a Lead Quantitative Research Scientist at Renaissance Technologies (Jim Simons' Medallion Fund).
Data:
{table_str}

Candidate Setup:
- Regime Triggered: {regime_type}
- ML Lead Forecast: {ml_pred:+.5f}
- Cointegration Spread Z: {spread_z:.2f}
- Order Flow Imbalance (OFI): {ofi:+.1f}

Evaluation Rules:
1. BUY: High order flow accumulation or cointegration spread discount + positive ML forecast.
2. SHORT: High order flow distribution or cointegration spread premium + negative ML forecast.
3. HOLD: Conflicting flow signals or excessive volatility noise.

Output strict JSON:
{{
  "decision": "BUY" | "SHORT" | "HOLD",
  "confidence": <float 0.0 to 1.0>,
  "reasoning": "<concise 1 sentence rationale>"
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
                decision_data['regime_type'] = regime_type
                decision_data['spread_z'] = spread_z
                decision_data['ml_pred'] = ml_pred
                return decision_data
        except Exception:
            time.sleep(1.0)
            
    return {
        "bar_idx": current_bar_idx,
        "timestamp": str(timestamp),
        "close": close_p,
        "regime_type": regime_type,
        "spread_z": spread_z,
        "ml_pred": ml_pred,
        "decision": "HOLD",
        "confidence": 0.0,
        "reasoning": "API failed"
    }

def run_simons_llm_ensemble_engine():
    feature_file = "processed_data/features_and_targets.csv"
    model_file = "processed_data/ml_trend_model.cbm"
    
    if not os.path.exists(feature_file) or not os.path.exists(model_file):
        print("❌ Model or feature file missing.")
        return
        
    df = pd.read_csv(feature_file)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    last_time = df['timestamp'].max()
    start_time = last_time - pd.Timedelta(days=30)
    
    df_sliced = df[df['timestamp'] >= start_time - pd.Timedelta(days=5)].copy().reset_index(drop=True)
    start_bar_indices = df_sliced[df_sliced['timestamp'] >= start_time].index.tolist()
    start_idx = start_bar_indices[0]
    
    test_indices = list(range(start_idx, len(df_sliced) - 20, 1))
    
    ml_model = CatBoostRegressor()
    ml_model.load_model(model_file)
    
    feature_cols = [
        'gold_ret_1', 'gold_ret_3', 'gold_ret_5', 'gold_ret_10',
        'gold_ofi_norm_1', 'gold_ofi_norm_5', 'gold_signed_flow_norm_1', 'gold_signed_flow_norm_5',
        'gold_quote_imbalance_1', 'gold_quote_imbalance_5', 'gold_realized_vol_1', 'gold_realized_vol_5',
        'dxy_ret_1', 'dxy_ret_3', 'dxy_ret_5', 'dxy_vol_5',
        'bond_ret_1', 'bond_ret_3', 'bond_ret_5', 'bond_vol_5',
        'vix_ret_1', 'vix_ret_3', 'vix_ret_5', 'vix_z_score_20',
        'gold_dxy_corr_20', 'gold_bond_corr_20', 'vol_ratio_5_20',
        'z_score', 'rsi_14', 'h_rsi_14', 'gold_ofi_accel_5',
        'quote_imbalance_velocity_5', 'price_impact_coef_5', 'vwap_dev_20',
        'hft_abs_bull', 'hft_abs_bear'
    ]
    
    ml_preds_all = ml_model.predict(df_sliced[feature_cols])
    
    api_key = load_env_key()
    if not api_key:
        print("❌ DEEPSEEK_API_KEY missing.")
        return
        
    # Multi-Regime Signal Generator
    api_candidates = []
    for idx in test_indices:
        bar = df_sliced.iloc[idx]
        ml_p = float(ml_preds_all[idx])
        ofi_val = float(bar['ofi_dollar'])
        flow_val = float(bar['signed_flow'])
        sp_z = float(bar['z_score'])
        vwap_dev = float(bar['vwap_dev_20'])
        elasticity = float(bar['price_impact_coef_5'])
        
        if elasticity > 0.05:
            continue
            
        regime_type = None
        # Regime 1: Order Flow Acceleration
        if abs(ofi_val) > 25.0 or abs(flow_val) > 35.0:
            regime_type = "FLOW_ACCELERATION"
        # Regime 2: Cointegration Spread Discrepancy
        elif abs(sp_z) >= 1.25:
            regime_type = "PAIR_SPREAD_REVERSION"
        # Regime 3: Micro VWAP Deviation Scalp
        elif abs(vwap_dev) > 1.2 or abs(ml_p) > 0.0004:
            regime_type = "VWAP_MICRO_SCALP"
            
        if regime_type is not None:
            api_candidates.append((idx, ml_p, regime_type))
            
    print(f"🏛️ Running Multi-Regime Simons Engine with DeepSeek Meta-Judge over {len(test_indices)} bars...")
    print(f"📊 Filtered out {len(test_indices)-len(api_candidates)} noise bars | Querying DeepSeek API for {len(api_candidates)} candidate setups...")
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(query_deepseek_simons_judge, api_key, df_sliced, idx, ml_p, reg): idx 
            for idx, ml_p, reg in api_candidates
        }
        for future in as_completed(futures):
            results.append(future.result())
            
    results = sorted(results, key=lambda x: x['bar_idx'])
    
    start_balance = 10000.0
    current_balance = start_balance
    commission = 0.00002
    
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
        regime = res.get('regime_type', 'UNKNOWN')
        bar_idx = res['bar_idx']
        
        # Simons' Hard 1.8% Daily Stop Circuit Breaker
        bar_date = df_sliced.loc[bar_idx, 'date']
        if bar_date != current_day:
            current_day = bar_date
            day_start_balance = current_balance
            daily_circuit_broken = False
            
        current_daily_dd = (day_start_balance - current_balance) / day_start_balance
        if current_daily_dd >= 0.018:
            daily_circuit_broken = True
            
        if daily_circuit_broken:
            i += 1
            continue
            
        if decision in ['BUY', 'SHORT'] and confidence >= 0.58:
            entry_idx = bar_idx
            entry_time = pd.to_datetime(res['timestamp'])
            entry_price = float(df_sliced.loc[entry_idx, 'close'])
            r_vol = float(df_sliced.loc[entry_idx, 'realized_vol'])
            
            high_low = df_sliced.loc[entry_idx, 'high'] - df_sliced.loc[entry_idx, 'low']
            high_close = abs(df_sliced.loc[entry_idx, 'high'] - entry_price)
            low_close = abs(df_sliced.loc[entry_idx, 'low'] - entry_price)
            atr = max(high_low, high_close, low_close)
            if atr < 1.0:
                atr = 2.0
                
            # Simons Volatility Sizing
            vol_scaler = min(1.3, max(0.7, 0.00002 / (r_vol + 1e-8)))
            base_risk_pct = 0.010 * confidence * vol_scaler
            
            cash_risk = current_balance * base_risk_pct
            
            sl_dist = 1.2 * atr
            tp_dist = 2.6 * atr # 2.16 RRR
            
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
            
            for f_idx in range(entry_idx + 1, min(entry_idx + 16, len(df_sliced))):
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
                exit_idx = min(entry_idx + 15, len(df_sliced) - 1)
                exit_price = df_sliced.loc[exit_idx, 'close']
                
            exit_time = pd.to_datetime(df_sliced.loc[exit_idx, 'timestamp'])
            
            spread_cost = (df_sliced.loc[entry_idx, 'spread'] / entry_price) * position_usd
            commission_cost = 2 * commission * position_usd
            total_costs = (spread_cost + commission_cost) / 2.0
            
            if decision == 'BUY':
                raw_profit = units * (exit_price - entry_price)
            else:
                raw_profit = units * (entry_price - exit_price)
                
            net_profit_cash = raw_profit - total_costs
            
            old_balance = current_balance
            current_balance += net_profit_cash
            
            for f_idx in range(entry_idx, exit_idx + 1):
                t_bar = pd.to_datetime(df_sliced.loc[f_idx, 'timestamp'])
                t_close = df_sliced.loc[f_idx, 'close']
                if decision == 'BUY':
                    float_profit = units * (t_close - entry_price)
                else:
                    float_profit = units * (entry_price - t_close)
                equity_history.loc[t_bar, 'equity'] = old_balance + float_profit
                
            equity_history.loc[exit_time:, 'equity'] = current_balance
            
            trades_executed.append({
                'entry_time': entry_time.strftime('%Y-%m-%d %H:%M'),
                'exit_time': exit_time.strftime('%Y-%m-%d %H:%M'),
                'type': decision,
                'regime': regime,
                'risk_pct': base_risk_pct,
                'outcome': outcome,
                'cash_profit': net_profit_cash,
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
    print("   MULTI-REGIME SIMONS + DEEPSEEK QUANT SUMMARY (June)")
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
        print(f" Strategy Win Rate      : {win_rate:.2%}")
        print("\nExecuted Trades Ledger (Sample):")
        for idx, t in enumerate(trades_executed[:10]):
            print(f" #{idx+1}: {t['type']} ({t['regime']}) | Outcome: {t['outcome']} | PnL: ${t['cash_profit']:+,.2f}")
    print("=======================================================\n")

if __name__ == '__main__':
    run_simons_llm_ensemble_engine()
