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

def fetch_decision(api_key, df_slice, current_bar_idx, last_idx, lead_horizon=5):
    """
    Sends the 10-bar context to DeepSeek and returns the decision.
    """
    # Use the 10 bars ending at current_bar_idx
    context_bars = df_slice.iloc[current_bar_idx-9:current_bar_idx+1]
    
    timestamp = context_bars['timestamp'].iloc[-1]
    close_price = context_bars['close'].iloc[-1]
    spread_entry = context_bars['spread'].iloc[-1]
    
    data_table = context_bars[[
        'timestamp', 'open', 'high', 'low', 'close', 'volume', 
        'ofi_dollar', 'quote_imbalance', 'realized_vol', 'spread', 
        'dxy_price', 'bond_price', 'vix_price'
    ]].to_string(index=False)
    
    prompt = f"""You are an elite quantitative trading intelligence running a Mean-Reversion / Market-Making strategy on Gold (XAUUSD).
At this short-term horizon (5-bar holding period, ~1.5 hours), Gold prices are highly mean-reverting. Chasing momentum (e.g. buying when price and OFI are rising) will result in losses due to overbought pullbacks.

Your task is to analyze the following raw market data of the last 10 Gold (XAUUSD) Dollar Bars (compiled at a $5,000 threshold), synchronized with DXY, USTBOND, and VIX:

{data_table}

Follow these strict Market-Making guidelines:
1. Identify Oversold Dips (BUY opportunity): Look for instances where DXY price spikes up (dollar strengthens) AND Gold has a negative order flow spike (ofi_dollar is strongly negative, quote_imbalance < -0.05). This represents a temporary liquidity dip where Gold is oversold. Anticipate a mean-reversion bounce.
2. Identify Overbought Spikes (SHORT opportunity): Look for instances where DXY price drops (dollar weakens) AND Gold has a positive order flow spike (ofi_dollar is strongly positive, quote_imbalance > 0.05). This represents a temporary liquidity spike where Gold is overbought. Anticipate a downward mean-reversion.
3. Chasing Momentum is FORBIDDEN: Do not buy if Gold has been rising steadily with positive OFI unless DXY has crashed. Do not short if Gold has been falling steadily with negative OFI.
4. Transaction Costs: The round-trip cost is ~2 bps. Only signal BUY or SHORT if you have high confidence (> 0.75) of a clear mean-reversion bounce exceeding 15 bps. Otherwise, output HOLD.

Provide your output strictly in JSON format with these exact keys:
{{
  "analysis": "A brief summary of your microstructure and cross-asset analysis focusing on overbought/oversold extremes",
  "decision": "BUY", "SHORT", or "HOLD",
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "Detailed justification of your mean-reversion decision"
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
        "response_format": {"type": "json_object"}
    }
    
    # Try calling the API
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
                
                # Add index information to track
                decision_data['bar_idx'] = current_bar_idx
                decision_data['timestamp'] = str(timestamp)
                decision_data['close'] = float(close_price)
                decision_data['spread'] = float(spread_entry)
                return decision_data
        except Exception as e:
            time.sleep(1.0 * (attempt + 1))
            
    # Fallback to HOLD on failure
    return {
        "bar_idx": current_bar_idx,
        "timestamp": str(timestamp),
        "close": float(close_price),
        "spread": float(spread_entry),
        "decision": "HOLD",
        "confidence": 0.0,
        "analysis": f"API Error: {str(e)}",
        "reasoning": "API failed to respond."
    }

def run_deepseek_backtest():
    print("⏳ Loading dataset and setting up DeepSeek backtest...")
    df = pd.read_csv("processed_data/aligned_dataset.csv")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Slice for the last 3 days
    last_time = df['timestamp'].max()
    start_time = last_time - pd.Timedelta(days=3)
    df_3d = df[df['timestamp'] >= start_time - pd.Timedelta(hours=10)].copy().reset_index(drop=True)
    
    # Find the starting index that has at least 10 historical rows within the 3d range
    # Let's say we start where timestamp >= start_time
    start_bar_indices = df_3d[df_3d['timestamp'] >= start_time].index.tolist()
    if not start_bar_indices:
        print("❌ No bars found in the last 3 days.")
        return
        
    start_idx = start_bar_indices[0]
    # We will test at every 3rd bar to avoid overlapping trades and speed up API calls (20-30 total calls is plenty and fast!)
    test_indices = list(range(start_idx, len(df_3d) - 5, 3))
    
    api_key = load_env_key()
    if not api_key:
        print("❌ Error: DEEPSEEK_API_KEY not found.")
        return
        
    print(f"📈 Testing DeepSeek decisions at {len(test_indices)} points over the last 3 days...")
    
    results = []
    # Run in parallel using a ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {
            executor.submit(fetch_decision, api_key, df_3d, idx, len(df_3d)): idx 
            for idx in test_indices
        }
        
        for future in as_completed(futures):
            idx = futures[future]
            try:
                res = future.result()
                results.append(res)
                print(f"   [+] Processed bar index {idx} ({res['timestamp']}) -> Decision: {res['decision']}")
            except Exception as e:
                print(f"   [-] Failed to process bar {idx}: {e}")
                
    # Sort results chronologically
    results = sorted(results, key=lambda x: x['bar_idx'])
    
    # Simulate trades
    commission = 0.00002
    lead_horizon = 5
    trades = []
    
    # Track trades chronologically without overlaps
    i = 0
    while i < len(results):
        res = results[i]
        decision = res['decision']
        confidence = res['confidence']
        
        # Only trade on high confidence signals
        entry_idx = res['bar_idx']
        volume = df_3d.loc[entry_idx, 'volume']
        close = df_3d.loc[entry_idx, 'close']
        ofi_current = df_3d.loc[entry_idx, 'ofi_dollar'] / (volume * close + 1e-8)
        
        guardrail_passed = True
        if decision == 'SHORT' and ofi_current < 0.02:
            guardrail_passed = False
            reason_blocked = f"Price rise with negative OFI ({ofi_current:.4f}) indicates Liquidity Pulling breakout"
        elif decision == 'BUY' and ofi_current > -0.02:
            guardrail_passed = False
            reason_blocked = f"Price drop with positive OFI ({ofi_current:.4f}) indicates seller dominance pulling bids"
            
        if decision in ['BUY', 'SHORT'] and confidence >= 0.70:
            if not guardrail_passed:
                print(f"   [⚠️ GUARDRAIL BLOCKED] Blocked {decision} trade at {res['timestamp']} | Reason: {reason_blocked}")
                i += 1
                continue
                
            exit_idx = min(entry_idx + lead_horizon, len(df_3d) - 1)
            
            entry_price = res['close']
            exit_price = df_3d.loc[exit_idx, 'close']
            
            spread_entry = res['spread']
            spread_exit = df_3d.loc[exit_idx, 'spread']
            
            raw_ret = np.log(exit_price / entry_price) if decision == 'BUY' else np.log(entry_price / exit_price)
            cost = (spread_entry / entry_price + spread_exit / exit_price) / 2.0 + 2 * commission
            net_ret = raw_ret - cost
            
            trades.append({
                'timestamp': res['timestamp'],
                'type': decision,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'confidence': confidence,
                'net_return': net_ret,
                'reasoning': res['reasoning']
            })
            
            # Fast-forward our results pointer past the exit bar index
            # Find the next index in results that is after exit_idx
            next_i = i + 1
            while next_i < len(results) and results[next_i]['bar_idx'] <= exit_idx:
                next_i += 1
            i = next_i
        else:
            i += 1
            
    trade_df = pd.DataFrame(trades)
    
    print("\n=======================================================")
    print("       DEEPSEEK AGENT 3-DAY BACKTEST SUMMARY           ")
    print("=======================================================")
    if not trade_df.empty:
        print(f" Total Trades Triggered : {len(trade_df)}")
        print(f" Win Rate               : {(trade_df['net_return'] > 0).mean():.2%}")
        print(f" Cumulative Net Return  : {trade_df['net_return'].sum():.2%}")
        print("\nDetail of Executed Trades:")
        for idx, row in trade_df.iterrows():
            print(f"\nTrade #{idx+1}: {row['type']} at {row['timestamp']}")
            print(f"   Entry: {row['entry_price']:.3f} | Exit: {row['exit_price']:.3f}")
            print(f"   Net Return: {row['net_return']:.2%} | Confidence: {row['confidence']:.2f}")
            print(f"   Reasoning: {row['reasoning']}")
    else:
        print(" No trades met the confidence threshold (>0.70) during this period.")
    print("=======================================================\n")

if __name__ == '__main__':
    run_deepseek_backtest()
