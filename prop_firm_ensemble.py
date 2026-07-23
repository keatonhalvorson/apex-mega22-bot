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

def fetch_decision(api_key, df_slice, current_bar_idx, ml_model):
    """
    Predicts future return using CatBoost, compiles prompt with ML + HFT features, and queries DeepSeek.
    """
    context_bars = df_slice.iloc[current_bar_idx-9:current_bar_idx+1]
    
    timestamp = context_bars['timestamp'].iloc[-1]
    close_price = context_bars['close'].iloc[-1]
    spread_entry = context_bars['spread'].iloc[-1]
    atr_val = context_bars['atr_5'].iloc[-1]
    
    # 1. CatBoost Inference
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
        'hft_abs_bull', 'hft_abs_bear'
    ]
    
    current_features = context_bars[feature_cols].copy()
    ml_preds = ml_model.predict(current_features)
    
    # Add ML predictions to the context bars
    context_bars_with_ml = context_bars.copy()
    context_bars_with_ml['ml_pred_return'] = ml_preds
    
    data_table = context_bars_with_ml[[
        'timestamp', 'open', 'high', 'low', 'close', 'volume', 
        'z_score', 'rsi_14', 'h_ema_20', 'atr_5',
        'gold_ofi_norm_1', 'gold_ofi_norm_5', 'hft_abs_bull', 'hft_abs_bear', 
        'vwap_dev_20', 'vol_ratio_5_20', 'gold_dxy_corr_20', 'dxy_ret_3', 'bond_ret_3',
        'ml_pred_return'
    ]].to_string(index=False)
    
    prompt = f"""You are a Lead Quantitative Research Scientist and Head of HFT Strategy at an elite prop trading firm.
Your sole mission is to pass a Funded Account Challenge by maximizing expected return while strictly keeping drawdown below limits (Max daily drawdown 5%, Max total drawdown 10%, Target 8%).
Unlike standard retail systems, there are NO code-level filters blocking your trades. You are fully responsible for risk management, trend prediction, and capital preservation.

Here is the enriched market microstructure dataset of the last 10 Gold (XAUUSD) Dollar Bars, showing rolling correlations, HFT absorption, and CatBoost ML model forecasts:

{data_table}

Analyze the data with scientific rigor, focusing on predicting the trend direction and detecting institutional HFT footprints:
1. CatBoost Machine Learning Forecast:
   - 'ml_pred_return' represents the expected log-return over the next 5 bars predicted by our CatBoost model trained on historical data.
   - A positive value (e.g., > 0.0003) indicates a strong bullish trend prediction; a negative value (e.g., < -0.0003) indicates a strong bearish trend prediction.
   - Use this ML prediction as your primary trend-prediction anchor, but verify it using HFT order book signs before execution.
2. HFT Secrets & Absorption Patterns:
   - HFT Passive Absorption: 
     * 'hft_abs_bull' > 0.25 indicates that aggressive sellers are hitting the bids, but passive HFT market makers are absorbing them by adding limit buy orders, and the price is refusing to drop. This is a high-probability reversal/bounce indicator (exhaustion bottom).
     * 'hft_abs_bear' > 0.25 indicates that aggressive buyers are hitting the asks, but passive HFT sellers are absorbing them, and the price is refusing to rise. This is a high-probability bearish reversal/sell indicator (exhaustion top).
   - Trend Prediction: Use DXY return ('dxy_ret_3') and Bond return ('bond_ret_3') as leading indicators (inverse to Gold yield and USD price) to anticipate Gold trend breakouts.
3. CRITICAL SAFETY RULES (MUST BE STRICTLY ENFORCED, NO EXCEPTIONS ALLOWED):
   - Macro Trend Alignment (Allows Pullback Dip Buying & ML breakouts):
     * Bullish Trend (close > h_ema_20): You can enter a BUY trade. You are also allowed to BUY a pullback if close is below h_ema_20 PROVIDED that either 'z_score' < -0.8 OR 'hft_abs_bull' > 0.25 OR 'ml_pred_return' > 0.0003. No SHORT trades allowed.
     * Bearish Trend (close < h_ema_20): You can enter a SHORT trade. You are also allowed to SHORT a rally if close is above h_ema_20 PROVIDED that either 'z_score' > 0.8 OR 'hft_abs_bear' > 0.25 OR 'ml_pred_return' < -0.0003. No BUY trades allowed.
   - Overextension Block (TREND_FOLLOWING): You MUST NOT buy if 'rsi_14' > 65 or 'z_score' > 1.8. You MUST NOT short if 'rsi_14' < 35 or 'z_score' < -1.8.
   - Volatility Squeeze Block (TREND_FOLLOWING): You MUST NOT enter a trend-following trade unless 'vol_ratio_5_20' > 1.02 OR absolute 'ml_pred_return' > 0.0004 OR 'hft_abs_bull' > 0.20 OR 'hft_abs_bear' > 0.20.
   - Pullback Entry Filter (MEAN_REVERSION): You MUST NOT enter a mean-reversion BUY trade unless 'z_score' < -0.8 and 'rsi_14' < 45. You MUST NOT enter a mean-reversion SHORT trade unless 'z_score' > 0.8 and 'rsi_14' > 55.
   - Absolute Compliance Check: Before formatting your final JSON response, check if the proposed 'decision' violates ANY of the rules above. If a rule is violated (even borderline), you MUST output "decision": "HOLD" and "confidence": 0.0. No justifications or excuses are allowed.
4. Risk Management: If you decide to trade (BUY or SHORT), specify 'stop_loss_atr' and 'take_profit_atr' (multipliers of atr_5, e.g. 1.5 and 3.0) such that take_profit_atr / stop_loss_atr >= 1.5.

Provide your output strictly in JSON format with these exact keys:
{{
  "reasoning": "Step-by-step verification of each of the 4 safety rules. Analyze trend, overextension, volatility ratio, and pullback. State explicitly if any rule is violated.",
  "detected_regime": "MEAN_REVERSION" or "TREND_FOLLOWING",
  "analysis": "Brief scientific analysis of HFT footprints, correlation, and toxicity",
  "decision": "BUY", "SHORT", or "HOLD",
  "confidence": <float between 0.0 and 1.0>,
  "stop_loss_atr": <float, between 1.0 and 3.0>,
  "take_profit_atr": <float, between 1.5 and 6.0>
}}
Do NOT include any text outside the JSON object."""

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {api_key}"
    }
    data = {
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "temperature": 0.0
    }
    
    last_error = "Unknown API error"
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
                decision_data['close'] = float(close_price)
                decision_data['spread'] = float(spread_entry)
                decision_data['atr'] = float(atr_val)
                decision_data['ml_pred_return'] = float(ml_preds[-1])
                return decision_data
        except Exception as e:
            last_error = str(e)
            time.sleep(1.0 * (attempt + 1))
            
    return {
        "bar_idx": current_bar_idx,
        "timestamp": str(timestamp),
        "close": float(close_price),
        "spread": float(spread_entry),
        "atr": float(atr_val),
        "ml_pred_return": 0.0,
        "detected_regime": "MEAN_REVERSION",
        "decision": "HOLD",
        "confidence": 0.0,
        "stop_loss_atr": 1.5,
        "take_profit_atr": 3.0,
        "analysis": f"API Error: {last_error}",
        "reasoning": "API failed to respond."
    }

def run_ensemble_backtest(period_name="LAST_MONTH"):
    print(f"\n⏳ Loading features_and_targets.csv for {period_name}...")
    df = pd.read_csv("processed_data/features_and_targets.csv")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Slicing time period
    last_time = df['timestamp'].max()
    if period_name == "LAST_MONTH":
        start_time = last_time - pd.Timedelta(days=30)
        df_sliced = df[df['timestamp'] >= start_time - pd.Timedelta(hours=10)].copy().reset_index(drop=True)
    elif period_name == "PREVIOUS_MONTH":
        end_time = last_time - pd.Timedelta(days=30)
        start_time = end_time - pd.Timedelta(days=30)
        df_sliced = df[(df['timestamp'] >= start_time - pd.Timedelta(hours=10)) & (df['timestamp'] <= end_time)].copy().reset_index(drop=True)
    elif period_name == "APRIL":
        end_time = last_time - pd.Timedelta(days=60)
        start_time = end_time - pd.Timedelta(days=30)
        df_sliced = df[(df['timestamp'] >= start_time - pd.Timedelta(hours=10)) & (df['timestamp'] <= end_time)].copy().reset_index(drop=True)
        
    start_bar_indices = df_sliced[df_sliced['timestamp'] >= start_time].index.tolist()
    if not start_bar_indices:
        print("❌ No bars found in the sliced period.")
        return
        
    start_idx = start_bar_indices[0]
    test_indices = list(range(start_idx, len(df_sliced) - 15, 4))
    
    api_key = load_env_key()
    if not api_key:
        print("❌ DEEPSEEK_API_KEY missing.")
        return
        
    # Load CatBoost Model
    ml_model = CatBoostRegressor()
    ml_model.load_model("processed_data/ml_trend_model.cbm")
    
    print(f"📈 Running Hybrid Ensemble Strategy (CatBoost + LLM) at {len(test_indices)} points...")
    
    results = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            executor.submit(fetch_decision, api_key, df_sliced, idx, ml_model): idx 
            for idx in test_indices
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                res = future.result()
                results.append(res)
                print(f"   [+] Processed bar {idx} ({res['timestamp']}) -> ML Pred: {res.get('ml_pred_return', 0.0)*10000:.1f} bps | Regime: {res.get('detected_regime', 'UNKNOWN')} | Decision: {res['decision']}")
            except Exception as e:
                print(f"   [-] Failed bar {idx}: {e}")
                
    results = sorted(results, key=lambda x: x['bar_idx'])
    
    # Simulate execution (NO Python Filters)
    commission = 0.00002
    trades = []
    
    i = 0
    while i < len(results):
        res = results[i]
        decision = res['decision']
        confidence = res['confidence']
        regime = res.get('detected_regime', 'MEAN_REVERSION')
        
        # Only execute if model confidence is >= 0.70
        if decision in ['BUY', 'SHORT'] and confidence >= 0.70:
            entry_idx = res['bar_idx']
            entry_price = res['close']
            atr = res['atr']
            sl_atr = float(res.get('stop_loss_atr', 1.5))
            tp_atr = float(res.get('take_profit_atr', 3.0))
            
            if sl_atr <= 0 or tp_atr <= 0:
                i += 1
                continue
                
            sl_dist = sl_atr * atr
            tp_dist = tp_atr * atr
            
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
                    if f_low <= sl_price and f_high >= tp_price:
                        outcome = 'LOSS (Dual Hit)'
                        exit_price = sl_price
                        exit_idx = f_idx
                        break
                    elif f_low <= sl_price:
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
                    if f_high >= sl_price and f_low <= tp_price:
                        outcome = 'LOSS (Dual Hit)'
                        exit_price = sl_price
                        exit_idx = f_idx
                        break
                    elif f_high >= sl_price:
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
                
            cost = (res['spread'] / entry_price + df_sliced.loc[exit_idx, 'spread'] / exit_price) / 2.0 + 2 * commission
            if decision == 'BUY':
                raw_ret = np.log(exit_price / entry_price)
            else:
                raw_ret = np.log(entry_price / exit_price)
            net_ret = raw_ret - cost
            
            trades.append({
                'timestamp': res['timestamp'],
                'type': decision,
                'regime': regime,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'outcome': outcome,
                'sl_atr': sl_atr,
                'tp_atr': tp_atr,
                'net_return': net_ret,
                'reasoning': res['reasoning']
            })
            
            next_i = i + 1
            while next_i < len(results) and results[next_i]['bar_idx'] <= exit_idx:
                next_i += 1
            i = next_i
        else:
            i += 1
            
    trade_df = pd.DataFrame(trades)
    
    print("\n=======================================================")
    print(f"      HYBRID ENSEMBLE BACKTEST SUMMARY: {period_name}")
    print("=======================================================")
    if not trade_df.empty:
        total_trades = len(trade_df)
        wins = trade_df[trade_df['outcome'] == 'WIN']
        losses = trade_df[trade_df['outcome'].str.contains('LOSS')]
        time_exits = trade_df[trade_df['outcome'] == 'TIME_EXIT']
        
        print(f" Total Trades Triggered : {total_trades}")
        print(f" Wins                   : {len(wins)} ({(len(wins)/total_trades):.2%})")
        print(f" Losses                 : {len(losses)} ({(len(losses)/total_trades):.2%})")
        print(f" Time Exits             : {len(time_exits)} ({(len(time_exits)/total_trades):.2%})")
        print(f" Cumulative Net Return  : {trade_df['net_return'].sum():.2%}")
        
        # Breakdown by regime
        print("\nRegime Performance Breakdown:")
        for reg_name in ['MEAN_REVERSION', 'TREND_FOLLOWING']:
            reg_trades = trade_df[trade_df['regime'] == reg_name]
            if not reg_trades.empty:
                reg_wins = reg_trades[reg_trades['outcome'] == 'WIN']
                print(f"   * {reg_name}: {len(reg_trades)} trades | Net Return: {reg_trades['net_return'].sum():.2%} | Win Rate: {len(reg_wins)/len(reg_trades):.2%}")
            else:
                print(f"   * {reg_name}: 0 trades executed")
        
        trade_df['cum_return'] = trade_df['net_return'].cumsum()
        cum_ret = trade_df['cum_return'].values
        max_dd = 0.0
        peak = 0.0
        for val in cum_ret:
            if val > peak:
                peak = val
            dd = peak - val
            if dd > max_dd:
                max_dd = dd
        print(f" Maximum Drawdown       : {max_dd:.2%}")
        
        print("\nDetail of Executed Trades:")
        for idx, row in trade_df.iterrows():
            print(f"\nTrade #{idx+1}: {row['type']} ({row['regime']}) at {row['timestamp']}")
            print(f"   Entry: {row['entry_price']:.3f} | Exit: {row['exit_price']:.3f} | Outcome: {row['outcome']}")
            print(f"   Net Return: {row['net_return']:.2%} | SL ATR: {row['sl_atr']:.1f} | TP ATR: {row['tp_atr']:.1f}")
            print(f"   Reasoning: {row['reasoning']}")
    else:
        print(" No trades triggered during the test period.")
    print("=======================================================\n")

if __name__ == '__main__':
    run_ensemble_backtest("APRIL")
