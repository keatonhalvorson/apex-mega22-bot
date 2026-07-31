#!/usr/bin/env parser
"""
llm_tick_backtester.py
Optimized LLM Microstructure Trend Strategy powered by Official DeepSeek API (deepseek-chat).
Streams $1M Dollar Bars with Order Flow metrics, high confidence filtering (>=0.75), and +0.75% TP / -0.30% SL targets.
"""

import os
import sys
import json
import time
import re
import requests
import pandas as pd
import numpy as np
from tqdm import tqdm

# Official DeepSeek API Configuration
API_BASE_URL = "https://api.deepseek.com/v1/chat/completions"
API_KEY = "sk-e839fe71024f4a0ab9c91d5422dfcdb4"
MODEL_NAME = "deepseek-chat"

# Optimized Trading Constants
INITIAL_CAPITAL = 10_000.0   # $10,000 Starting Account
FEE_RATE = 0.00075           # 0.075% Binance Spot Fee
CONFIDENCE_THRESHOLD = 0.75  # High-confidence filter (75%)
DEFAULT_TP_PCT = 0.0075      # +0.75% Take Profit target
DEFAULT_SL_PCT = 0.0030      # -0.30% Stop Loss limit
MAX_HOLD_BARS = 15           # Holding window in dollar bars

# Data Paths
WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_PATH = os.path.join(WORKSPACE_DIR, "processed_data", "btcusdt_dollar_bars_intent.parquet")
OUTPUT_TRADES_CSV = os.path.join(WORKSPACE_DIR, "processed_data", "llm_deepseek_strategy_trades.csv")

def call_llm_optimized_strategy(current_state, history_summary, position_info):
    """
    Sends microstructure dollar bar state to DeepSeek API with high R:R instructions.
    """
    system_prompt = (
        "CRITICAL INSTRUCTION: You are an elite quantitative trend trader for BTCUSD.\n"
        "Your objective is to identify HIGH-PROBABILITY institutional micro-trends that yield at least +0.75% price movement.\n"
        "Only issue a BUY or SELL signal if confidence is >= 0.75 and order flow (CVD, OFI, Volume Surge) strongly confirms direction.\n"
        "Otherwise, output HOLD.\n"
        "Do NOT write any introduction, markdown formatting, explanations, or text outside of JSON.\n"
        "Start your response immediately with the symbol `{` and end with `}`.\n\n"
        "Required JSON format:\n"
        "{\n"
        '  "action": "BUY",\n'
        '  "confidence": 0.80,\n'
        '  "stop_loss_pct": 0.0030,\n'
        '  "take_profit_pct": 0.0075,\n'
        '  "reasoning": "Strong CVD expansion and high OFI indicating institutional momentum."\n'
        "}"
    )

    user_prompt = f"""
Current Market Microstructure State ($1M Dollar Bar):
- Timestamp: {current_state.get('end_time')}
- Price: ${current_state.get('close'):,.2f}
- Volume Delta (Buy - Sell): {current_state.get('volume_delta'):,.2f}
- Cumulative Volume Delta (CVD): {current_state.get('cvd'):,.2f}
- Order Flow Imbalance (OFI): {current_state.get('order_flow_imbalance'):.4f}
- Absorption Metric: {current_state.get('absorption_metric'):.4f}
- Microstructure Momentum: {current_state.get('microstructure_momentum'):.4f}
- Volatility (20-bar): {current_state.get('volatility_20'):.6f}
- Volume Surge Metric: {current_state.get('volume_surge_20'):.2f}

Recent History Summary (Last 5 Dollar Bars):
{history_summary}

Current Account & Position:
- Account Capital: ${position_info['capital']:,.2f}
- Position Active: {position_info['has_position']} (Side: {position_info.get('side', 'N/A')})
- Position Entry Price: ${position_info['entry_price']:,.2f} if active else N/A
- Bars Held: {position_info['bars_held']} bars

Evaluate order flow dynamics and output your JSON trade decision ("BUY", "SELL", or "HOLD").
"""

    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 300
    }

    start_time = time.time()
    try:
        resp = requests.post(API_BASE_URL, headers=headers, json=payload, timeout=20)
        latency = time.time() - start_time
        
        if resp.status_code == 200:
            res_json = resp.json()
            usage = res_json.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
            
            content = res_json["choices"][0]["message"]["content"].strip()
            
            match = re.search(r'(\{[\s\S]*?"action"[\s\S]*?\})', content)
            if match:
                decision = json.loads(match.group(1))
                decision["latency"] = latency
                decision["tokens"] = total_tokens
                return decision
            else:
                return {"action": "HOLD", "confidence": 0.0, "reasoning": "JSON Regex mismatch", "latency": latency, "tokens": total_tokens}
        else:
            return {"action": "HOLD", "confidence": 0.0, "reasoning": f"API Error HTTP {resp.status_code}", "latency": latency, "tokens": 0}

    except Exception as e:
        latency = time.time() - start_time
        return {"action": "HOLD", "confidence": 0.0, "reasoning": f"Exception: {str(e)}", "latency": latency, "tokens": 0}


def run_optimized_llm_backtest(max_steps=50, step_stride=1):
    """
    Runs the LLM backtest using Official DeepSeek API.
    """
    if not os.path.exists(DATA_PATH):
        print(f"Error: Data file not found at {DATA_PATH}")
        sys.exit(1)

    print(f"Loading $1M Dollar Bars from {DATA_PATH}...")
    df = pd.read_parquet(DATA_PATH)
    df = df.dropna(subset=['absorption_metric', 'cvd', 'order_flow_imbalance']).reset_index(drop=True)

    sample_df = df.iloc[-max_steps * step_stride:].reset_index(drop=True) if max_steps else df

    capital = INITIAL_CAPITAL
    position = None
    trades = []
    
    total_tokens_consumed = 0
    total_api_calls = 0
    
    print("\n" + "="*80)
    print(f"STARTING DEEPSEEK OFFICIAL API BACKTEST ({len(sample_df)//step_stride} steps)")
    print(f"Model: {MODEL_NAME} | Endpoint: {API_BASE_URL}")
    print("="*80 + "\n")

    pbar = tqdm(range(5, len(sample_df), step_stride), desc="DeepSeek Backtest", unit="step")

    for i in pbar:
        curr_row = sample_df.iloc[i].to_dict()
        curr_price = float(curr_row["close"])
        curr_high = float(curr_row["high"])
        curr_low = float(curr_row["low"])
        timestamp = str(curr_row["end_time"])

        hist_rows = sample_df.iloc[max(0, i-5):i]
        hist_summary = ""
        for idx, h_row in hist_rows.iterrows():
            hist_summary += f"  - Time: {h_row['end_time']} | Close: ${h_row['close']:,.2f} | VolDelta: {h_row['volume_delta']:,.1f} | OFI: {h_row['order_flow_imbalance']:.3f}\n"

        pos_info = {
            "capital": capital,
            "has_position": position is not None,
            "side": position["side"] if position else "N/A",
            "entry_price": position["entry_price"] if position else 0.0,
            "bars_held": (i - position["entry_bar"]) if position else 0
        }

        # Check Position Exits (TP / SL / Time Exit)
        if position is not None:
            entry_price = position["entry_price"]
            entry_bar = position["entry_bar"]
            qty = position["size"]
            pos_side = position["side"]
            tp_pct = position.get("tp_pct", DEFAULT_TP_PCT)
            sl_pct = position.get("sl_pct", DEFAULT_SL_PCT)
            
            bars_held = i - entry_bar
            exit_price = None
            exit_reason = None

            if pos_side == "BUY":
                tp_price = entry_price * (1 + tp_pct)
                sl_price = entry_price * (1 - sl_pct)
                if curr_high >= tp_price:
                    exit_price = tp_price
                    exit_reason = f"Take Profit (+{tp_pct*100:.2f}%)"
                elif curr_low <= sl_price:
                    exit_price = sl_price
                    exit_reason = f"Stop Loss (-{sl_pct*100:.2f}%)"
                elif bars_held >= MAX_HOLD_BARS:
                    exit_price = curr_price
                    exit_reason = f"Time Exit ({MAX_HOLD_BARS} Bars)"
            elif pos_side == "SELL":
                tp_price = entry_price * (1 - tp_pct)
                sl_price = entry_price * (1 + sl_pct)
                if curr_low <= tp_price:
                    exit_price = tp_price
                    exit_reason = f"Take Profit (+{tp_pct*100:.2f}%)"
                elif curr_high >= sl_price:
                    exit_price = sl_price
                    exit_reason = f"Stop Loss (-{sl_pct*100:.2f}%)"
                elif bars_held >= MAX_HOLD_BARS:
                    exit_price = curr_price
                    exit_reason = f"Time Exit ({MAX_HOLD_BARS} Bars)"

            if exit_price is not None:
                if pos_side == "BUY":
                    exit_notional = qty * exit_price
                    exit_fee = exit_notional * FEE_RATE
                    net_pnl = (exit_notional - exit_fee) - (position["entry_notional"] + position["entry_fee"])
                else:
                    exit_notional = qty * exit_price
                    exit_fee = exit_notional * FEE_RATE
                    net_pnl = (position["entry_notional"] - position["entry_fee"]) - (exit_notional + exit_fee)

                pct_return = net_pnl / position["entry_notional"]
                capital += net_pnl
                
                trades.append({
                    "side": pos_side,
                    "entry_time": position["entry_time"],
                    "exit_time": timestamp,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "net_pnl": net_pnl,
                    "pct_return": pct_return,
                    "exit_reason": exit_reason,
                    "capital": capital,
                    "llm_reasoning": position["llm_reasoning"]
                })

                position = None

        # Call DeepSeek API Strategy if no position
        decision = {"action": "HOLD", "tokens": 0, "latency": 0.0, "reasoning": "Holding"}
        if position is None:
            decision = call_llm_optimized_strategy(curr_row, hist_summary, pos_info)
            total_tokens_consumed += decision.get("tokens", 0)
            total_api_calls += 1

            action = decision.get("action", "HOLD").upper()
            confidence = float(decision.get("confidence", 0.0))

            if action in ["BUY", "SELL"] and confidence >= CONFIDENCE_THRESHOLD:
                entry_price = curr_price
                entry_notional = capital * 0.98
                entry_fee = entry_notional * FEE_RATE
                qty = (entry_notional - entry_fee) / entry_price

                position = {
                    "side": action,
                    "entry_time": timestamp,
                    "entry_price": entry_price,
                    "entry_bar": i,
                    "size": qty,
                    "entry_notional": entry_notional,
                    "entry_fee": entry_fee,
                    "tp_pct": float(decision.get("take_profit_pct", DEFAULT_TP_PCT)),
                    "sl_pct": float(decision.get("stop_loss_pct", DEFAULT_SL_PCT)),
                    "llm_reasoning": decision.get("reasoning", "")
                }

        # Update Progress Bar
        net_ret = (capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
        total_trades = len(trades)
        win_count = sum(1 for t in trades if t["net_pnl"] > 0)
        win_rate = (win_count / total_trades * 100) if total_trades > 0 else 0.0

        pbar.set_postfix({
            "Price": f"${curr_price:,.2f}",
            "Signal": decision.get("action", "HOLD"),
            "PnL": f"{net_ret:+.2f}%",
            "Trades": total_trades,
            "WinRate": f"{win_rate:.0f}%",
            "Tokens": f"{total_tokens_consumed:,}"
        })

    # Summary
    print("\n" + "="*80)
    print("DEEPSEEK OFFICIAL API BACKTEST SUMMARY")
    print("="*80)
    print(f"Initial Capital:         ${INITIAL_CAPITAL:,.2f}")
    print(f"Final Capital:           ${capital:,.2f}")
    print(f"Total Net PnL:           ${capital - INITIAL_CAPITAL:+,.2f} ({(capital - INITIAL_CAPITAL)/INITIAL_CAPITAL * 100:+.2f}%)")
    print(f"Total Executed Trades:   {len(trades)}")
    
    if len(trades) > 0:
        trades_df = pd.DataFrame(trades)
        trades_df.to_csv(OUTPUT_TRADES_CSV, index=False)
        print(f"Trades Saved To:         {OUTPUT_TRADES_CSV}")
        
        wins = trades_df[trades_df["net_pnl"] > 0]
        losses = trades_df[trades_df["net_pnl"] <= 0]
        print(f"Winning Trades:          {len(wins)} ({len(wins)/len(trades)*100:.1f}%)")
        print(f"Losing Trades:           {len(losses)} ({len(losses)/len(trades)*100:.1f}%)")
        print(f"Avg PnL per Trade:       ${trades_df['net_pnl'].mean():+,.2f}")

    print(f"Total API Calls Made:    {total_api_calls:,}")
    print(f"Total Tokens Consumed:   {total_tokens_consumed:,} tokens")
    print("="*80 + "\n")

if __name__ == "__main__":
    max_s = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run_optimized_llm_backtest(max_steps=max_s)
