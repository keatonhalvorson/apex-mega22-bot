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

def calculate_rsi(prices, period=14):
    deltas = np.diff(prices)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / (down + 1e-8)
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)
    
    for i in range(period, len(prices)):
        delta = deltas[i-1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / (down + 1e-8)
        rsi[i] = 100. - 100. / (1. + rs)
    return rsi

def fetch_decision(api_key, df_slice, current_bar_idx):
    """
    Sends enriched 10-bar context to DeepSeek and requests trade setup.
    """
    context_bars = df_slice.iloc[current_bar_idx-9:current_bar_idx+1]
    
    timestamp = context_bars['timestamp'].iloc[-1]
    close_price = context_bars['close'].iloc[-1]
    spread_entry = context_bars['spread'].iloc[-1]
    atr_val = context_bars['atr_5'].iloc[-1]
    
    data_table = context_bars[[
        'timestamp', 'open', 'high', 'low', 'close', 'volume', 
        'ofi_accum_5', 'quote_imbalance_mean_5', 'z_score', 'rsi_14', 
        'h_ema_20', 'h_rsi_14', 'atr_5'
    ]].to_string(index=False)
    
    prompt = f"""You are a Lead Quantitative Research Scientist and Head of Risk Management at a prop trading firm.
Your goal is to pass a Funded Account Challenge with strict drawdown limits (Max daily drawdown 5%, Max total drawdown 10%, Target 8%).
To do this, you must run a highly rigorous Mean-Reversion strategy using ATR-based Stop Loss (SL) and Take Profit (TP) targets to guarantee a positive expectancy with a Risk-to-Reward Ratio (RRR) between 1.5 and 3.0.

Here is the enriched market data of the last 10 Gold (XAUUSD) Dollar Bars (threshold $5,000), including Hourly macro trend data:

{data_table}

Follow these scientific trading guidelines:
1. Macro Trend Alignment: Check 'h_ema_20' (20-hour EMA) and 'h_rsi_14'. If Gold close price is above 'h_ema_20', the macro trend is BULLISH. Buy signals have higher probability. If price is below 'h_ema_20', the macro trend is BEARISH. Short signals have higher probability.
2. Statistical Extremes: Look at 'z_score' (distance from 20-bar mean in std devs) and 'rsi_14'. A z_score > 1.8 or rsi_14 > 65 indicates an overbought extreme (look to SHORT). A z_score < -1.8 or rsi_14 < 35 indicates an oversold extreme (look to BUY).
3. Order Flow & Exhaustion: Look at 'ofi_accum_5' (cumulative order flow imbalance) and 'quote_imbalance_mean_5'. A strong short trade requires positive OFI exhaustion. A strong buy trade requires negative OFI exhaustion.
4. Risk Management: If you enter a trade (decision is BUY or SHORT), you must specify 'stop_loss_atr' (multiplier of the current atr_5, e.g. 1.5) and 'take_profit_atr' (multiplier of atr_5, e.g. 3.0) such that take_profit_atr / stop_loss_atr >= 1.5.

Provide your output strictly in JSON format with these exact keys:
{{
  "analysis": "Brief quantitative analysis of trend, Z-score, and order flow",
  "decision": "BUY", "SHORT", or "HOLD",
  "confidence": <float between 0.0 and 1.0>,
  "stop_loss_atr": <float, between 1.0 and 3.0>,
  "take_profit_atr": <float, between 1.5 and 6.0>,
  "reasoning": "Detailed justification of trade direction and SL/TP selection"
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
        "decision": "HOLD",
        "confidence": 0.0,
        "stop_loss_atr": 1.5,
        "take_profit_atr": 3.0,
        "analysis": f"API Error: {str(e)}",
        "reasoning": "API failed to respond."
    }

def run_prop_backtest():
    print("⏳ Loading and preparing enriched dataset...")
    # Load dollar bars
    df = pd.read_csv("processed_data/aligned_dataset.csv")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Load hourly bars
    df_h = pd.read_csv("tv_gold_1h_2m.csv")
    df_h['datetime'] = pd.to_datetime(df_h['datetime'])
    df_h = df_h.sort_values('datetime').reset_index(drop=True)
    
    # Compute Hourly indicators
    df_h['ema_20'] = df_h['close'].ewm(span=20, adjust=False).mean()
    df_h['rsi_14'] = calculate_rsi(df_h['close'].values, period=14)
    df_h_sub = df_h[['datetime', 'ema_20', 'rsi_14']].rename(columns={
        'ema_20': 'h_ema_20',
        'rsi_14': 'h_rsi_14'
    })
    
    # Merge
    df = pd.merge_asof(
        df, df_h_sub,
        left_on='timestamp', right_on='datetime',
        direction='backward'
    ).drop(columns=['datetime'])
    
    # Dollar indicators
    df['rolling_mean'] = df['close'].rolling(20).mean()
    df['rolling_std'] = df['close'].rolling(20).std()
    df['z_score'] = (df['close'] - df['rolling_mean']) / (df['rolling_std'] + 1e-8)
    df['rsi_14'] = calculate_rsi(df['close'].values, period=14)
    df['ofi_accum_5'] = df['ofi_dollar'].rolling(5).sum() / (df['volume'].rolling(5).sum() * df['close'] + 1e-8)
    df['quote_imbalance_mean_5'] = df['quote_imbalance'].rolling(5).mean()
    
    # ATR 5
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    df['atr_5'] = ranges.max(axis=1).rolling(5).mean()
    
    df = df.dropna().reset_index(drop=True)
    
    # Filter for last 10 days
    last_time = df['timestamp'].max()
    start_time = last_time - pd.Timedelta(days=10)
    df_10d = df[df['timestamp'] >= start_time - pd.Timedelta(hours=10)].copy().reset_index(drop=True)
    
    start_bar_indices = df_10d[df_10d['timestamp'] >= start_time].index.tolist()
    if not start_bar_indices:
        print("❌ No bars found in last 10 days.")
        return
        
    start_idx = start_bar_indices[0]
    test_indices = list(range(start_idx, len(df_10d) - 15, 3))
    
    api_key = load_env_key()
    if not api_key:
        print("❌ DEEPSEEK_API_KEY missing.")
        return
        
    print(f"📈 Testing funded strategy at {len(test_indices)} points over the last 10 days...")
    
    results = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            executor.submit(fetch_decision, api_key, df_10d, idx): idx 
            for idx in test_indices
        }
        for future in as_completed(futures):
            idx = futures[future]
            try:
                res = future.result()
                results.append(res)
                print(f"   [+] Processed bar {idx} ({res['timestamp']}) -> Decision: {res['decision']}")
            except Exception as e:
                print(f"   [-] Failed bar {idx}: {e}")
                
    results = sorted(results, key=lambda x: x['bar_idx'])
    
    # Simulate execution with dynamic stop loss & take profit
    commission = 0.00002
    trades = []
    
    i = 0
    while i < len(results):
        res = results[i]
        decision = res['decision']
        confidence = res['confidence']
        
        # Hardcoded Guardrail checks
        entry_idx = res['bar_idx']
        volume = df_10d.loc[entry_idx, 'volume']
        close = df_10d.loc[entry_idx, 'close']
        open_price = df_10d.loc[entry_idx, 'open']
        ofi_current = df_10d.loc[entry_idx, 'ofi_dollar'] / (volume * close + 1e-8)
        bar_ret_abs = abs(np.log(close / open_price))
        
        guardrail_passed = True
        reason_blocked = ""
        
        if bar_ret_abs > 0.0030:
            guardrail_passed = False
            reason_blocked = f"Volatility breakout: return is {bar_ret_abs*10000:.1f} bps (> 30 bps)"
            
        if decision in ['BUY', 'SHORT'] and confidence >= 0.70:
            if not guardrail_passed:
                print(f"   [⚠️ GUARDRAIL BLOCKED] Blocked {decision} trade at {res['timestamp']} | {reason_blocked}")
                i += 1
                continue
                
            entry_price = res['close']
            atr = res['atr']
            sl_atr = float(res.get('stop_loss_atr', 1.5))
            tp_atr = float(res.get('take_profit_atr', 3.0))
            
            # Risk-to-reward ratio check
            if sl_atr <= 0 or tp_atr <= 0:
                print(f"   [⚠️ INVALID TRADE] Blocked {decision} at {res['timestamp']} due to invalid SL/TP ratios.")
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
                
            # Search future rows for exit
            outcome = None
            exit_price = None
            exit_idx = entry_idx
            
            for f_idx in range(entry_idx + 1, min(entry_idx + 16, len(df_10d))):
                f_row = df_10d.iloc[f_idx]
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
                else: # SHORT
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
                exit_idx = min(entry_idx + 15, len(df_10d) - 1)
                exit_price = df_10d.loc[exit_idx, 'close']
                
            # Compute returns
            cost = (res['spread'] / entry_price + df_10d.loc[exit_idx, 'spread'] / exit_price) / 2.0 + 2 * commission
            if decision == 'BUY':
                raw_ret = np.log(exit_price / entry_price)
            else:
                raw_ret = np.log(entry_price / exit_price)
            net_ret = raw_ret - cost
            
            trades.append({
                'timestamp': res['timestamp'],
                'type': decision,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'outcome': outcome,
                'sl_atr': sl_atr,
                'tp_atr': tp_atr,
                'net_return': net_ret,
                'reasoning': res['reasoning']
            })
            
            # Fast forward past the exit index
            next_i = i + 1
            while next_i < len(results) and results[next_i]['bar_idx'] <= exit_idx:
                next_i += 1
            i = next_i
        else:
            i += 1
            
    trade_df = pd.DataFrame(trades)
    
    print("\n=======================================================")
    print("      PROP FIRM FUNDED CHALLENGE BACKTEST SUMMARY      ")
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
        
        # Max Drawdown calculation
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
            print(f"\nTrade #{idx+1}: {row['type']} at {row['timestamp']}")
            print(f"   Entry: {row['entry_price']:.3f} | Exit: {row['exit_price']:.3f} | Outcome: {row['outcome']}")
            print(f"   Net Return: {row['net_return']:.2%} | SL ATR: {row['sl_atr']:.1f} | TP ATR: {row['tp_atr']:.1f}")
            print(f"   Reasoning: {row['reasoning']}")
    else:
        print(" No trades triggered during the test period.")
    print("=======================================================\n")

if __name__ == '__main__':
    run_prop_backtest()
