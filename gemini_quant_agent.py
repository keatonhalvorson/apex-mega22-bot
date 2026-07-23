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
            if line.startswith("GEMINI_API_KEY="):
                return line.strip().split("=")[1]
    return None

def ask_gemini_quant():
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
        print("❌ Error: GEMINI_API_KEY not found in '.env' file. Please run the secure setup command first.")
        return
        
    prompt = f"""You are an elite quantitative trading model running inside a high-frequency fund.
Your task is to analyze the following raw market data of the last 10 Gold (XAUUSD) Dollar Bars (compiled at a $5,000 threshold), synchronized with DXY, USTBOND, and VIX:

{data_table}

Analyze:
1. Microstructure: OFI (Order Flow Imbalance) trends, quote imbalance (bid vs ask depth), and realized volatility.
2. Cross-Asset Dynamics: Relative movements of DXY (Dollar Index - dollar strength is typically bearish for Gold), USTBOND (US Treasury Bond prices - rising bond prices reflect lower yields which is typically bullish for Gold), and VIX (Fear index).
3. Transaction Costs: The bid-ask spread relative to the price.

Determine the optimal action (BUY, SHORT, or HOLD) for a short-term holding period of 5 bars. Because transaction costs are high (average ~2 bps per trade), only choose BUY or SHORT if you have high confidence (> 0.75) that the predicted move will exceed the cost. Otherwise, output HOLD.

Provide your output strictly in JSON format with these exact keys:
{{
  "analysis": "A brief summary of your technical, order flow, and cross-asset analysis",
  "decision": "BUY", "SHORT", or "HOLD",
  "confidence": <float between 0.0 and 1.0>,
  "reasoning": "Detailed justification of your decision"
}}
Do NOT include any markdown formatting, backticks, or text before/after the JSON."""

    # Set up Gemini API call using standard urllib
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    headers = {
        "content-type": "application/json"
    }
    
    data = {
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {
                    "analysis": {"type": "STRING"},
                    "decision": {"type": "STRING", "enum": ["BUY", "SHORT", "HOLD"]},
                    "confidence": {"type": "NUMBER"},
                    "reasoning": {"type": "STRING"}
                },
                "required": ["analysis", "decision", "confidence", "reasoning"]
            }
        }
    }
    
    print("🧠 Sending raw data to Gemini 2.5 for quantitative decision...")
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
            raw_content = resp_json['candidates'][0]['content']['parts'][0]['text']
            
            decision_data = json.loads(raw_content.strip())
            
            print("\n=======================================================")
            print("         GEMINI QUANT TRADING AGENT DECISION           ")
            print("=======================================================")
            print(f" Timestamp  : {last_10['timestamp'].iloc[-1]}")
            print(f" Gold Price : {last_10['close'].iloc[-1]} USD")
            print(f" Decision   : {decision_data['decision']}")
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
    ask_gemini_quant()
