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

def query_deepseek_institutional_judge(api_key, df_slice, current_bar_idx, ml_pred):
    context_bars = df_slice.iloc[current_bar_idx-4:current_bar_idx+1]
    last_bar = context_bars.iloc[-1]
    
    timestamp = last_bar['timestamp']
    close_p = float(last_bar['close'])
    spread = float(last_bar['spread'])
    realized_vol = float(last_bar['realized_vol'])
    signed_flow = float(last_bar['signed_flow'])
    macro_res = float(last_bar['macro_residual_z_20'])
    
    high_low = context_bars['high'] - context_bars['low']
    high_close = np.abs(context_bars['high'] - context_bars['close'].shift(1))
    low_close = np.abs(context_bars['low'] - context_bars['close'].shift(1))
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    atr = float(ranges.max(axis=1).iloc[-1])
    
    table_str = context_bars[[
        'timestamp', 'close', 'signed_flow', 'ofi_dollar', 'quote_imbalance', 'realized_vol', 'macro_residual_z_20'
    ]].to_string(index=False)
    
    prompt = f"""You are a Lead Quantitative Trader at Renaissance Technologies managing an Institutional Gold Fund.
Dataset of last 5 Gold Dollar Bars:
{table_str}

Context:
- Current Price: ${close_p:.2f} | Current ATR: ${atr:.2f}
- CatBoost ML Model Lead Return Forecast: {ml_pred:+.5f}
- Macro Cointegration Residual (epsilon_t): {macro_res:+.2f}
- Signed Flow: {signed_flow:+.2f}

Institutional Execution Modes:
- Mode 1: MACRO_TREND (Target 3.0 ATR, SL 1.5 ATR). Use when Macro Residual Vector (epsilon_t) and Order Flow agree.
- Mode 2: FAST_SCALP (Target 1.2 ATR, SL 0.8 ATR). Use when high order flow imbalance exists in short window.

Output strict JSON:
{{
  "decision": "BUY" | "SHORT" | "HOLD",
  "trade_mode": "MACRO_TREND" | "FAST_SCALP",
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
        "max_tokens": 120
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
                decision_data['spread'] = spread
                decision_data['atr'] = atr
                decision_data['ml_pred'] = ml_pred
                return decision_data
        except Exception:
            time.sleep(1.0)
            
    return {
        "bar_idx": current_bar_idx,
        "timestamp": str(timestamp),
        "close": close_p,
        "spread": spread,
        "atr": atr,
        "ml_pred": ml_pred,
        "decision": "HOLD",
        "trade_mode": "MACRO_TREND",
        "confidence": 0.0,
        "reasoning": "API failed"
    }

def run_simulation(period_name="LAST_MONTH"):
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
    
    test_indices = list(range(start_idx, len(df_sliced) - 20, 2))
    
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
        
    # Local Pre-filtering
    api_indices = []
    for idx in test_indices:
        last_b = df_sliced.iloc[idx]
        ml_p = float(ml_preds_all[idx])
        ofi_val = float(last_b['ofi_dollar'])
        flow_val = float(last_b['signed_flow'])
        macro_res = float(last_b['macro_residual_z_20'])
        elasticity = float(last_b['price_impact_coef_5'])
        
        # Microstructure Elasticity Guard: Reject thin liquidity traps
        if elasticity > 0.05:
            continue
            
        if abs(ml_p) > 0.0003 or abs(ofi_val) > 50.0 or abs(flow_val) > 100.0 or abs(macro_res) > 1.2:
            api_indices.append((idx, ml_p))
            
    print(f"📈 Running Institutional Quant Strategy (with Simons Medallion Circuit Breaker) over {len(test_indices)} bars...")
    print(f"📊 Filtered out {len(test_indices)-len(api_indices)} noise bars | Querying DeepSeek API for {len(api_indices)} candidate setups...")
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(query_deepseek_institutional_judge, api_key, df_sliced, idx, ml_p): idx 
            for idx, ml_p in api_indices
        }
        for future in as_completed(futures):
            results.append(future.result())
            
    results = sorted(results, key=lambda x: x['bar_idx'])
    
    # -------------------------------------------------------------
    # SIMONS MEDALLION RISK & BACKTEST ENGINE
    # -------------------------------------------------------------
    start_balance = 10000.0
    current_balance = start_balance
    commission = 0.00002
    
    trades_executed = []
    recent_pnl_pcts = []
    
    all_timestamps = df_sliced.loc[start_idx:, 'timestamp'].reset_index(drop=True)
    equity_history = pd.DataFrame({'timestamp': all_timestamps})
    equity_history['equity'] = current_balance
    equity_history.set_index('timestamp', inplace=True)
    
    current_day = None
    day_start_balance = start_balance
    daily_circuit_broken = False
    
    i = 0
    while i < len(results):
        res = results[i]
        decision = res['decision']
        confidence = float(res['confidence'])
        trade_mode = res.get('trade_mode', 'MACRO_TREND')
        bar_idx = res['bar_idx']
        
        # ---------------------------------------------------------
        # JIM SIMONS' HARD 1.8% DAILY STOP CIRCUIT BREAKER
        # ---------------------------------------------------------
        bar_date = pd.to_datetime(res['timestamp']).date()
        if bar_date != current_day:
            current_day = bar_date
            day_start_balance = current_balance
            daily_circuit_broken = False
            
        current_daily_dd = (day_start_balance - current_balance) / day_start_balance
        if current_daily_dd >= 0.018: # 1.8% Hard Daily Stop Cutoff!
            daily_circuit_broken = True
            
        if daily_circuit_broken:
            i += 1
            continue
            
        if decision in ['BUY', 'SHORT'] and confidence >= 0.65:
            entry_idx = bar_idx
            entry_time = pd.to_datetime(res['timestamp'])
            entry_price = res['close']
            atr = res['atr']
            
            if trade_mode == "FAST_SCALP":
                sl_atr = float(res.get('stop_loss_atr', 0.8))
                tp_atr = float(res.get('take_profit_atr', 1.2))
            else:
                sl_atr = float(res.get('stop_loss_atr', 1.5))
                tp_atr = float(res.get('take_profit_atr', 3.0))
                
            # Fractional Kelly Sizing with 0.95% Base Target
            p_win = max(0.51, min(0.90, confidence))
            b_payoff = tp_atr / (sl_atr + 1e-8)
            kelly_f = (p_win * b_payoff - (1.0 - p_win)) / b_payoff
            half_kelly_pct = max(0.003, min(0.0095, 0.22 * kelly_f))
            
            sl_dist = sl_atr * atr
            tp_dist = tp_atr * atr
            
            sl_pct_of_price = sl_dist / entry_price
            cash_risk = current_balance * half_kelly_pct
            position_size_usd = cash_risk / (sl_pct_of_price + 1e-8)
            units = position_size_usd / entry_price
            
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
            
            spread_cost = (res['spread'] / entry_price) * position_size_usd
            commission_cost = 2 * commission * position_size_usd
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
                'mode': trade_mode,
                'risk_pct': half_kelly_pct,
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
    print("   JIM SIMONS' MEDALLION INSTITUTIONAL QUANT SUMMARY: LAST_MONTH")
    print("=======================================================")
    print(f" Starting Balance       : ${start_balance:,.2f}")
    print(f" Final Balance          : ${current_balance:,.2f}")
    print(f" Net Profit/Loss ($)    : ${current_balance - start_balance:+,.2f} ({((current_balance - start_balance)/start_balance):+.2%})")
    print(f" Total Trades Executed  : {len(trades_executed)}")
    print(f" Max Daily Drawdown     : {daily_df['daily_dd_from_start'].max():.2%} (Prop Firm Limit: 5.0%)")
    print(f" Max Total Drawdown     : {max_total_dd:.2%} (Prop Firm Limit: 10.0%)")
    
    if trades_executed:
        wins = [t for t in trades_executed if t['outcome'] == 'WIN']
        win_rate = len(wins) / len(trades_executed)
        print(f" Strategy Win Rate      : {win_rate:.2%}")
        print("\nExecuted Trades Ledger (Sample):")
        for idx, t in enumerate(trades_executed[:10]):
            print(f" #{idx+1}: {t['type']} ({t['mode']}) | Risk: {t['risk_pct']:.2%} | Outcome: {t['outcome']} | PnL: ${t['cash_profit']:+,.2f}")
    print("=======================================================\n")

if __name__ == '__main__':
    run_simulation("LAST_MONTH")
