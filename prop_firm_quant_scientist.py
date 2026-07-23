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

def fetch_decision(api_key, df_slice, current_bar_idx):
    """
    Sends enriched quant-scientist context to DeepSeek and requests dynamic regime detection and trade setup.
    """
    context_bars = df_slice.iloc[current_bar_idx-9:current_bar_idx+1]
    
    timestamp = context_bars['timestamp'].iloc[-1]
    close_price = context_bars['close'].iloc[-1]
    spread_entry = context_bars['spread'].iloc[-1]
    atr_val = context_bars['atr_5'].iloc[-1]
    
    data_table = context_bars[[
        'timestamp', 'open', 'high', 'low', 'close', 'volume', 
        'z_score', 'rsi_14', 'h_ema_20', 'h_rsi_14', 'atr_5',
        'gold_dxy_corr_20', 'gold_bond_corr_20', 'vol_ratio_5_20', 
        'vix_z_score_20', 'dxy_vol_5', 'bond_vol_5'
    ]].to_string(index=False)
    
    prompt = f"""You are a Lead Quantitative Research Scientist and Head of Risk Management at a prop trading firm.
Your goal is to pass a Funded Account Challenge with strict drawdown limits (Max daily drawdown 5%, Max total drawdown 10%, Target 8%).
You must dynamically analyze the cross-asset indicators and statistical features to detect the dominant market regime (MEAN_REVERSION vs. TREND_FOLLOWING) and execute the appropriate trade setup.

Here is the enriched quant-scientist dataset of the last 10 Gold (XAUUSD) Dollar Bars, including rolling macro correlations, volatilities, and VIX features:

{data_table}

Follow these scientific trading guidelines:
1. Regime Detection:
   - Identify MEAN_REVERSION: Volatility ratio ('vol_ratio_5_20') is low/stable (< 1.1), price is ranging within Z-score boundaries (-1.3 to 1.3), and macro correlation ('gold_dxy_corr_20') is neutral or weakening.
   - Identify TREND_FOLLOWING: Volatility ratio ('vol_ratio_5_20') is expanding (> 1.2), price is breaking out above/below h_ema_20, and macro correlation ('gold_dxy_corr_20') is highly negative (< -0.5, showing USD-driven flight to safety).
2. Execution Rules:
   - If MEAN_REVERSION: Fade statistical extremes. BUY oversold pullbacks (z_score < -0.8) or SHORT overbought rallies (z_score > 0.8).
   - If TREND_FOLLOWING: Join the breakout. BUY bullish momentum (close > h_ema_20 with positive OFI and vol expansion) or SHORT bearish momentum (close < h_ema_20 with negative OFI and vol expansion).
3. Cross-Asset Confirmed setups:
   - When VIX Z-score ('vix_z_score_20') is elevated (> 1.2), it signals systemic fear, increasing the probability of safe-haven Gold BUY setups.
   - When Gold has a strong positive correlation with Bonds ('gold_bond_corr_20' > 0.5), it means Gold is moving closely with UST Bond prices (inversely with yields). Yield-drop BUY setups have high conviction.
4. Risk Management: If you enter a trade, specify 'stop_loss_atr' and 'take_profit_atr' (multipliers of atr_5, e.g. 1.5 and 3.0) such that take_profit_atr / stop_loss_atr >= 1.5.

Provide your output strictly in JSON format with these exact keys:
{{
  "detected_regime": "MEAN_REVERSION" or "TREND_FOLLOWING",
  "analysis": "Brief analysis of volatility ratio, cross-asset correlations, and VIX stress",
  "decision": "BUY", "SHORT", or "HOLD",
  "confidence": <float between 0.0 and 1.0>,
  "stop_loss_atr": <float, between 1.0 and 3.0>,
  "take_profit_atr": <float, between 1.5 and 6.0>,
  "reasoning": "Detailed justification of regime detection, trade decision, and SL/TP selection"
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
                return decision_data
        except Exception as e:
            time.sleep(1.0 * (attempt + 1))
            
    return {
        "bar_idx": current_bar_idx,
        "timestamp": str(timestamp),
        "close": float(close_price),
        "spread": float(spread_entry),
        "atr": float(atr_val),
        "detected_regime": "MEAN_REVERSION",
        "decision": "HOLD",
        "confidence": 0.0,
        "stop_loss_atr": 1.5,
        "take_profit_atr": 3.0,
        "analysis": f"API Error: {str(e)}",
        "reasoning": "API failed to respond."
    }

def run_scientist_backtest(period_name="LAST_MONTH"):
    print(f"\n⏳ Loading features_and_targets.csv for {period_name}...")
    df = pd.read_csv("processed_data/features_and_targets.csv")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Slicing time period
    last_time = df['timestamp'].max()
    if period_name == "LAST_MONTH":
        start_time = last_time - pd.Timedelta(days=30)
        df_sliced = df[df['timestamp'] >= start_time - pd.Timedelta(hours=10)].copy().reset_index(drop=True)
    else: # PREVIOUS_MONTH
        end_time = last_time - pd.Timedelta(days=30)
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
        
    print(f"📈 Running Quant-Scientist Strategy at {len(test_indices)} points...")
    
    results = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            executor.submit(fetch_decision, api_key, df_sliced, idx): idx 
            for idx in test_indices
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                res = future.result()
                results.append(res)
                print(f"   [+] Processed bar {idx} ({res['timestamp']}) -> Regime: {res.get('detected_regime', 'UNKNOWN')} | Decision: {res['decision']}")
            except Exception as e:
                print(f"   [-] Failed bar {idx}: {e}")
                
    results = sorted(results, key=lambda x: x['bar_idx'])
    
    # Simulate execution
    commission = 0.00002
    trades = []
    
    i = 0
    while i < len(results):
        res = results[i]
        decision = res['decision']
        confidence = res['confidence']
        regime = res.get('detected_regime', 'MEAN_REVERSION')
        
        # Indicators at entry
        entry_idx = res['bar_idx']
        close = df_sliced.loc[entry_idx, 'close']
        open_price = df_sliced.loc[entry_idx, 'open']
        h_ema = df_sliced.loc[entry_idx, 'h_ema_20']
        z_score = df_sliced.loc[entry_idx, 'z_score']
        rsi = df_sliced.loc[entry_idx, 'rsi_14']
        bar_ret_abs = abs(np.log(close / open_price))
        
        guardrail_passed = True
        reason_blocked = ""
        
        # 1. Strict Trend Guardrail (All trades must align with hourly EMA)
        is_trend_aligned = False
        if decision == 'BUY' and close > h_ema:
            is_trend_aligned = True
        elif decision == 'SHORT' and close < h_ema:
            is_trend_aligned = True
            
        if not is_trend_aligned:
            guardrail_passed = False
            reason_blocked = f"Counter-trend trade blocked (price {close:.2f} wrong side of EMA {h_ema:.2f})"
        
        # 2. Advanced regime-specific overextension guardrails
        elif regime == 'TREND_FOLLOWING':
            # Block buying the absolute top of breakouts
            if decision == 'BUY' and (rsi > 62 or z_score > 1.5):
                guardrail_passed = False
                reason_blocked = f"Trend BUY blocked due to overextension (RSI={rsi:.1f}, Z={z_score:.2f})"
            # Block shorting the absolute bottom of breakdowns
            elif decision == 'SHORT' and (rsi < 38 or z_score < -1.5):
                guardrail_passed = False
                reason_blocked = f"Trend SHORT blocked due to overextension (RSI={rsi:.1f}, Z={z_score:.2f})"
                
        elif regime == 'MEAN_REVERSION':
            # Volatility breakout block for Mean Reversion
            if bar_ret_abs > 0.0030:
                guardrail_passed = False
                reason_blocked = f"Mean Reversion breakout block (bar return {bar_ret_abs*10000:.1f} bps > 30 bps)"
            # Require a solid statistical pullback to enter Mean Reversion
            elif decision == 'BUY' and z_score > -0.8:
                guardrail_passed = False
                reason_blocked = f"Mean Reversion BUY blocked: pullback not deep enough (Z={z_score:.2f} > -0.8)"
            elif decision == 'SHORT' and z_score < 0.8:
                guardrail_passed = False
                reason_blocked = f"Mean Reversion SHORT blocked: rally not high enough (Z={z_score:.2f} < 0.8)"
            
        if decision in ['BUY', 'SHORT'] and confidence >= 0.70:
            if not guardrail_passed:
                print(f"   [⚠️ GUARDRAIL BLOCKED] Blocked {decision} trade at {res['timestamp']} | {reason_blocked}")
                i += 1
                continue
                
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
    print(f"      QUANT-SCIENTIST BACKTEST SUMMARY: {period_name}")
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
    else:
        print(" No trades triggered during the test period.")
    print("=======================================================\n")

if __name__ == '__main__':
    run_scientist_backtest("LAST_MONTH")
    run_scientist_backtest("PREVIOUS_MONTH")
