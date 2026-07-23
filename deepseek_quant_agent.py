import os
import json
import urllib.request
import urllib.error
import pandas as pd
import numpy as np

def load_env_key():
    env_path = "/home/atheer/Desktop/ApexPredator/download data/.env"
    if not os.path.exists(env_path):
        return None
    with open(env_path, "r") as f:
        for line in f:
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.strip().split("=")[1]
    return None

def ask_deepseek_quant():
    print("⏳ Loading the latest market data...")
    # Load aligned dataset
    df = pd.read_csv("processed_data/aligned_dataset.csv")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Get last 10 bars (most recent state of the market)
    last_10 = df.tail(10).copy()
    
    # Format the data table as text for the prompt
    data_table = last_10[[
        'timestamp', 'open', 'high', 'low', 'close', 'volume', 
        'ofi_dollar', 'quote_imbalance', 'realized_vol', 'spread', 
        'dxy_price', 'bond_price', 'vix_price'
    ]].to_string(index=False)
    
    # Load API Key from local .env
    api_key = load_env_key()
    if not api_key:
        print("❌ Error: DEEPSEEK_API_KEY not found in '.env' file.")
        return
        
    prompt = f"""You are an elite quantitative trading intelligence running a Mean-Reversion / Market-Making strategy on Gold (XAUUSD).
At this short-term horizon (5-bar holding period, ~1.5 hours), Gold prices are highly mean-reverting. Chasing momentum (e.g. buying when price and OFI are rising) will result in losses due to overbought pullbacks.

Your task is to analyze the following raw market data of the last 10 Gold (XAUUSD) Dollar Bars (compiled at a $5,000 threshold), synchronized with DXY, USTBOND, and VIX:

{data_table}

Follow these strict Market-Making guidelines:
1. Strict Trend Alignment: You are ONLY allowed to BUY if the price is above the 20-hour EMA ('close > h_ema_20'). You are ONLY allowed to SHORT if the price is below the 20-hour EMA ('close < h_ema_20'). Counter-trend trading is strictly FORBIDDEN.
2. Identify Oversold Dips (BUY opportunity): Look for instances where Gold is oversold (z_score < -1.2, rsi_14 < 42) AND we are above the 20-hour EMA. Anticipate a mean-reversion bounce.
3. Identify Overbought Spikes (SHORT opportunity): Look for instances where Gold is overbought (z_score > 1.2, rsi_14 > 58) AND we are below the 20-hour EMA. Anticipate a downward mean-reversion.
4. Transaction Costs: The round-trip cost is ~2 bps. Only signal BUY or SHORT if you have high confidence (> 0.75) of a clear mean-reversion bounce exceeding 15 bps. Otherwise, output HOLD.

Provide your output strictly in JSON format with these exact keys:
{{
  "analysis": "A brief summary of your microstructure and cross-asset analysis focusing on overbought/oversold extremes",
  "decision": "BUY", "SHORT", or "HOLD",
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "Detailed justification of your mean-reversion decision"
}}
Do NOT include any text outside the JSON object."""

    # Set up DeepSeek API call using standard urllib
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {api_key}"
    }
    
    data = {
        "model": "deepseek-chat",
        "messages": [
            {
                "role": "user",
                "content": prompt
            }
        ],
        "response_format": {
            "type": "json_object"
        }
    }
    
    print("🧠 Sending raw data to DeepSeek-V3 for quantitative decision...")
    req = urllib.request.Request(
        url, 
        data=json.dumps(data).encode('utf-8'), 
        headers=headers, 
        method='POST'
    )
    
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            resp_body = response.read().decode('utf-8')
            resp_json = json.loads(resp_body)
            raw_content = resp_json['choices'][0]['message']['content']
            
            decision_data = json.loads(raw_content.strip())
            
            # Code-level Guardrail Filter (Scientific Risk Overlay)
            decision = decision_data['decision']
            volume = last_10['volume'].iloc[-1]
            close = last_10['close'].iloc[-1]
            open_price = last_10['open'].iloc[-1]
            h_ema = last_10['h_ema_20'].iloc[-1]
            
            # Calculate bar absolute return
            bar_ret_abs = abs(np.log(close / open_price))
            
            guardrail_override = False
            override_msg = ""
            
            # 1. Breakout Volatility Filter (> 30 bps)
            if bar_ret_abs > 0.0030:
                decision = 'HOLD'
                guardrail_override = True
                override_msg = f"Override {decision_data['decision']} to HOLD. Extreme breakout volatility: bar return is {bar_ret_abs*10000:.1f} bps (> 30 bps), which is dangerous for mean reversion."
            # 2. Strict Trend Alignment Guardrail (No counter-trend trading)
            elif decision == 'BUY' and close < h_ema:
                decision = 'HOLD'
                guardrail_override = True
                override_msg = f"Override BUY to HOLD. Trend Alignment: BUY is forbidden below hourly EMA (price {close:.2f} < EMA {h_ema:.2f})."
            elif decision == 'SHORT' and close > h_ema:
                decision = 'HOLD'
                guardrail_override = True
                override_msg = f"Override SHORT to HOLD. Trend Alignment: SHORT is forbidden above hourly EMA (price {close:.2f} > EMA {h_ema:.2f})."
                
            print("\n=======================================================")
            print("        DEEPSEEK QUANT TRADING AGENT DECISION          ")
            print("=======================================================")
            print(f" Timestamp  : {last_10['timestamp'].iloc[-1]}")
            print(f" Gold Price : {last_10['close'].iloc[-1]} USD")
            if guardrail_override:
                print(f" Decision   : {decision} (Overridden from {decision_data['decision']}) ⚠️")
                print(f" Guardrail  : {override_msg}")
            else:
                print(f" Decision   : {decision}")
            print(f" Confidence : {decision_data['confidence']:.2f}")
            print("\n[Analysis]:")
            print(decision_data['analysis'])
            print("\n[Reasoning]:")
            print(decision_data['reasoning'])
            print("=======================================================\n")
            
    except urllib.error.HTTPError as e:
        print(f"❌ API Error {e.code}: {e.read().decode('utf-8')}")
    except Exception as e:
        print(f"❌ Error parsing response: {e}")

if __name__ == '__main__':
    ask_deepseek_quant()
