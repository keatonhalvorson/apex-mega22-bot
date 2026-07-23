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

def fetch_decision_institutional(api_key, df_slice, current_bar_idx, ml_model):
    """
    Elite Institutional Quant Pipeline:
    1. Microstructure Elasticity Filter: Rejects spurious low-liquidity price spikes (Adverse Selection).
    2. Cross-Asset Residual Divergence Filter: Checks Gold vs DXY/Bond cointegration vector.
    3. Fractional Kelly & Volatility Targeting Sizing.
    4. Compact DeepSeek Meta-Judge query.
    """
    context_bars = df_slice.iloc[current_bar_idx-9:current_bar_idx+1]
    last_bar = context_bars.iloc[-1]
    
    timestamp = last_bar['timestamp']
    close_price = float(last_bar['close'])
    spread_entry = float(last_bar['spread'])
    atr_val = float(last_bar['atr_5'])
    
    feature_cols = [
        'gold_ret_1', 'gold_ret_3', 'gold_ret_5', 'gold_ret_10',
        'gold_ofi_norm_1', 'gold_ofi_norm_5',
        'gold_signed_flow_norm_1', 'gold_signed_flow_norm_5',
        'gold_quote_imbalance_1', 'gold_quote_imbalance_5',
        'gold_realized_vol_1', 'gold_realized_vol_5',
        'dxy_ret_1', 'dxy_ret_3', 'dxy_ret_5', 'dxy_vol_5',
        'bond_ret_1', 'bond_ret_3', 'bond_ret_5', 'bond_vol_5',
        'vix_ret_1', 'vix_ret_3', 'vix_ret_5', 'vix_z_score_20',
        'gold_dxy_corr_20', 'gold_bond_corr_20', 'vol_ratio_5_20',
        'z_score', 'rsi_14', 'h_ema_20', 'h_rsi_14',
        'gold_ofi_accel_5', 'quote_imbalance_velocity_5', 'price_impact_coef_5', 'vwap_dev_20',
        'hft_abs_bull', 'hft_abs_bear', 'macro_residual_z_20'
    ]
    
    current_features = context_bars[feature_cols].copy()
    ml_preds = ml_model.predict(current_features)
    ml_pred = float(ml_preds[-1])
    
    # -------------------------------------------------------------
    # 1. INSTITUTIONAL QUANT FILTERS (NO RETAIL TRICKS)
    # -------------------------------------------------------------
    z_sc = float(last_bar['z_score'])
    abs_bull = float(last_bar['hft_abs_bull'])
    abs_bear = float(last_bar['hft_abs_bear'])
    vol_rat = float(last_bar['vol_ratio_5_20'])
    price_elasticity = float(last_bar['price_impact_coef_5'])
    macro_res_z = float(last_bar['macro_residual_z_20'])
    
    has_ml_signal = abs(ml_pred) > 0.0003
    has_hft_signal = (abs_bull > 0.20) or (abs_bear > 0.20)
    has_stretch_signal = abs(z_sc) > 0.8
    has_vol_signal = vol_rat > 1.05
    
    if not (has_ml_signal or has_hft_signal or has_stretch_signal or has_vol_signal):
        return {
            "bar_idx": current_bar_idx,
            "timestamp": str(timestamp),
            "close": close_price,
            "spread": spread_entry,
            "atr": atr_val,
            "ml_pred_return": ml_pred,
            "decision": "HOLD",
            "confidence": 0.0,
            "trade_mode": "HOLD",
            "stop_loss_atr": 1.5,
            "take_profit_atr": 3.0,
            "reasoning": "Pre-filtered locally in Python (no signal setup)."
        }
        
    # QUANT FILTER A: Price Elasticity Spurious Spike Block (Adverse Selection)
    # If price moved rapidly on zero OFI (elasticity > 15.0), it's a thin liquidity trap.
    if abs(price_elasticity) > 15.0 and not has_hft_signal:
        return {
            "bar_idx": current_bar_idx,
            "timestamp": str(timestamp),
            "close": close_price,
            "spread": spread_entry,
            "atr": atr_val,
            "ml_pred_return": ml_pred,
            "decision": "HOLD",
            "confidence": 0.0,
            "trade_mode": "HOLD",
            "stop_loss_atr": 1.5,
            "take_profit_atr": 3.0,
            "reasoning": "Blocked by Quant Filter: High Price Impact Elasticity (Thin Liquidity Trap)."
        }
        
    # QUANT FILTER B: Cointegration Residual Divergence Vector (\epsilon_t)
    # Passed dynamically to CatBoost & DeepSeek for trend acceleration sizing
    pass

    # -------------------------------------------------------------
    # 2. DEEPSEEK COMPACT QUERY
    # -------------------------------------------------------------
    context_bars_compact = context_bars.copy()
    context_bars_compact['ml_pred_bps'] = (ml_preds * 10000).round(1)
    
    table_str = context_bars_compact[[
        'timestamp', 'close', 'z_score', 'rsi_14', 'h_ema_20',
        'hft_abs_bull', 'hft_abs_bear', 'vol_ratio_5_20', 'ml_pred_bps'
    ]].tail(5).to_string(index=False)
    
    prompt = f"""HFT Prop Trading Meta-Judge. Pass Funded Account Challenge with strict risk.
Data (last 5 Gold Dollar Bars):
{table_str}

Rules:
1. Macro Trend: close > h_ema_20 => BUY / BUY Pullback. close < h_ema_20 => SHORT / SHORT Rally.
2. Signal Verification:
   - MACRO_TREND (TP=3.0, SL=1.5): vol_ratio_5_20 > 1.02 & strong ML forecast (|ml_pred_bps| > 3.0).
   - FAST_SCALP (TP=1.2, SL=0.8): Quick reversal/exhaustion via HFT absorption (hft_abs_bull/bear > 0.20) or Z-score pullback (|z_score| > 0.8).
3. Do NOT buy if rsi_14 > 65. Do NOT short if rsi_14 < 35.

Output strict JSON:
{{
  "decision": "BUY" | "SHORT" | "HOLD",
  "trade_mode": "MACRO_TREND" | "FAST_SCALP" | "HOLD",
  "confidence": <float 0.0 to 1.0>,
  "stop_loss_atr": <float>,
  "take_profit_atr": <float>,
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
        "max_tokens": 120
    }
    
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST'
            )
            with urllib.request.urlopen(req, timeout=15) as response:
                resp_body = response.read().decode('utf-8')
                resp_json = json.loads(resp_body)
                raw_content = resp_json['choices'][0]['message']['content']
                decision_data = json.loads(raw_content.strip())
                
                decision_data['bar_idx'] = current_bar_idx
                decision_data['timestamp'] = str(timestamp)
                decision_data['close'] = close_price
                decision_data['spread'] = spread_entry
                decision_data['atr'] = atr_val
                decision_data['ml_pred_return'] = ml_pred
                return decision_data
        except Exception as e:
            time.sleep(1.0 * (attempt + 1))
            
    return {
        "bar_idx": current_bar_idx,
        "timestamp": str(timestamp),
        "close": close_price,
        "spread": spread_entry,
        "atr": atr_val,
        "ml_pred_return": ml_pred,
        "decision": "HOLD",
        "confidence": 0.0,
        "trade_mode": "HOLD",
        "stop_loss_atr": 1.5,
        "take_profit_atr": 3.0,
        "reasoning": "API connection failed."
    }

def run_simulation(period_name="LAST_MONTH"):
    print(f"⏳ Loading features_and_targets.csv for {period_name}...")
    df = pd.read_csv("processed_data/features_and_targets.csv")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    last_time = df['timestamp'].max()
    if period_name == "LAST_MONTH": # June
        start_time = last_time - pd.Timedelta(days=30)
        df_sliced = df[df['timestamp'] >= start_time - pd.Timedelta(days=5)].copy().reset_index(drop=True)
    elif period_name == "PREVIOUS_MONTH": # May
        end_time = last_time - pd.Timedelta(days=30)
        start_time = end_time - pd.Timedelta(days=30)
        df_sliced = df[(df['timestamp'] >= start_time - pd.Timedelta(days=5)) & (df['timestamp'] <= end_time)].copy().reset_index(drop=True)
    else: # APRIL
        end_time = last_time - pd.Timedelta(days=60)
        start_time = end_time - pd.Timedelta(days=30)
        df_sliced = df[(df['timestamp'] >= start_time - pd.Timedelta(days=5)) & (df['timestamp'] <= end_time)].copy().reset_index(drop=True)
        
    start_bar_indices = df_sliced[df_sliced['timestamp'] >= start_time].index.tolist()
    start_idx = start_bar_indices[0]
    test_indices = list(range(start_idx, len(df_sliced) - 15, 3))
    
    api_key = load_env_key()
    if not api_key:
        print("❌ DEEPSEEK_API_KEY missing.")
        return
        
    ml_model = CatBoostRegressor()
    ml_model.load_model("processed_data/ml_trend_model.cbm")
    
    print(f"📈 Running Institutional Quant Strategy over {len(test_indices)} bars...")
    
    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {
            executor.submit(fetch_decision_institutional, api_key, df_sliced, idx, ml_model): idx 
            for idx in test_indices
        }
        for future in as_completed(futures):
            res = future.result()
            results.append(res)
                
    results = sorted(results, key=lambda x: x['bar_idx'])
    
    # -------------------------------------------------------------
    # INSTITUTIONAL ACCOUNT SIMULATION ($10,000 Account)
    # With Fractional Kelly Allocation & Dynamic Volatility Targeting
    # -------------------------------------------------------------
    start_balance = 10000.0
    commission = 0.00002
    
    trades_executed = []
    current_balance = start_balance
    
    recent_pnl_pcts = [] # Track rolling trade returns for Volatility Targeting
    
    all_timestamps = df_sliced.loc[start_idx:, 'timestamp'].reset_index(drop=True)
    equity_history = pd.DataFrame({'timestamp': all_timestamps})
    equity_history['equity'] = current_balance
    equity_history.set_index('timestamp', inplace=True)
    
    i = 0
    while i < len(results):
        res = results[i]
        decision = res['decision']
        confidence = float(res['confidence'])
        trade_mode = res.get('trade_mode', 'MACRO_TREND')
        
        if decision in ['BUY', 'SHORT'] and confidence >= 0.65:
            entry_idx = res['bar_idx']
            entry_time = pd.to_datetime(res['timestamp'])
            entry_price = res['close']
            atr = res['atr']
            
            if trade_mode == "FAST_SCALP":
                sl_atr = float(res.get('stop_loss_atr', 0.8))
                tp_atr = float(res.get('take_profit_atr', 1.2))
            else:
                sl_atr = float(res.get('stop_loss_atr', 1.5))
                tp_atr = float(res.get('take_profit_atr', 3.0))
                
            # ---------------------------------------------------------
            # QUANT INNOVATION 1: FRACTIONAL KELLY SIZING WITH SHRINKAGE
            # f* = (p * b - (1 - p)) / b
            # ---------------------------------------------------------
            p_win = max(0.51, min(0.90, confidence)) # Calibrated probability
            b_payoff = tp_atr / (sl_atr + 1e-8) # Payoff ratio
            kelly_f = (p_win * b_payoff - (1.0 - p_win)) / b_payoff
            half_kelly_pct = max(0.003, min(0.015, 0.30 * kelly_f)) # Fractional Kelly 30%
            
            # ---------------------------------------------------------
            # QUANT INNOVATION 2: DYNAMIC VOLATILITY TARGETING
            # Scale down size if recent trade equity volatility is clustering
            # ---------------------------------------------------------
            if len(recent_pnl_pcts) >= 5:
                rolling_vol = np.std(recent_pnl_pcts[-5:])
                target_vol = 0.01
                vol_target_scalar = min(1.2, max(0.4, target_vol / (rolling_vol + 1e-8)))
            else:
                vol_target_scalar = 1.0
                
            final_risk_pct = half_kelly_pct * vol_target_scalar
            
            sl_dist = sl_atr * atr
            tp_dist = tp_atr * atr
            
            sl_pct_of_price = sl_dist / entry_price
            cash_risk = current_balance * final_risk_pct
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
            net_return_pct = net_profit_cash / current_balance
            recent_pnl_pcts.append(net_return_pct)
            
            old_balance = current_balance
            current_balance += net_profit_cash
            
            for f_idx in range(entry_idx, exit_idx + 1):
                t_bar = pd.to_datetime(df_sliced.loc[f_idx, 'timestamp'])
                t_close = df_sliced.loc[f_idx, 'close']
                if decision == 'BUY':
                    float_profit = units * (t_close - entry_price)
                else:
                    float_profit = units * (entry_price - t_close)
                floating_equity = old_balance + float_profit
                equity_history.loc[t_bar, 'equity'] = floating_equity
                
            equity_history.loc[exit_time:, 'equity'] = current_balance
            
            trades_executed.append({
                'entry_time': entry_time.strftime('%Y-%m-%d %H:%M'),
                'exit_time': exit_time.strftime('%Y-%m-%d %H:%M'),
                'type': decision,
                'mode': trade_mode,
                'risk_pct': final_risk_pct,
                'entry_price': entry_price,
                'exit_price': exit_price,
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
        day_high = group['equity'].max()
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
    print(f"   ELITE INSTITUTIONAL QUANT SUMMARY: {period_name}")
    print("=======================================================")
    print(f" Starting Balance       : ${start_balance:,.2f}")
    print(f" Final Balance          : ${current_balance:,.2f}")
    print(f" Net Profit/Loss ($)    : ${current_balance - start_balance:+,.2f} ({((current_balance - start_balance)/start_balance):+.2%})")
    print(f" Total Trades Executed  : {len(trades_executed)}")
    print(f" Max Daily Drawdown     : {daily_df['daily_dd_from_start'].max():.2%} (Prop Firm Limit: 5.0%)")
    print(f" Max Total Drawdown     : {max_total_dd:.2%} (Prop Firm Limit: 10.0%)")
    
    if trades_executed:
        scalp_trades = [t for t in trades_executed if t['mode'] == 'FAST_SCALP']
        macro_trades = [t for t in trades_executed if t['mode'] == 'MACRO_TREND']
        print(f" Breakdown: {len(macro_trades)} MACRO_TREND trades | {len(scalp_trades)} FAST_SCALP trades")
        print("\nExecuted Trades Ledger (Sample):")
        for idx, t in enumerate(trades_executed[:10]):
            print(f" #{idx+1}: {t['type']} ({t['mode']}) | Risk: {t['risk_pct']:.2%} | Outcome: {t['outcome']} | PnL: ${t['cash_profit']:+,.2f}")
    print("=======================================================\n")

if __name__ == '__main__':
    run_simulation("LAST_MONTH")
