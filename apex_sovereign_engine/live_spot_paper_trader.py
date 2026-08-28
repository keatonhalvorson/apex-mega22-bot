"""
====================================================================================================
      🚀 APEX SOVEREIGN LIVE SPOT PAPER TRADER (ASW-LIVE v3.0)
      
      Live Spot Market Simulation directly interacting with Binance Public REST API:
      - Strictly Halal Spot 1x Cash (0 Leverage, 0 Shorting, 0 CFDs)
      - Integrated Matrix Profile Geometric Motif Pattern Discovery Engine
      - Real-time Order Book & Taker Flow Evaluation every 5 minutes
      - Parabolic Trailing Profit Lock (+0.5% at +1.6%, +1.6% at +3.0%, +3.0% at +4.8%)
====================================================================================================
"""

import os
import sys
import time
import json
import logging
from datetime import datetime, timezone
import requests
import pandas as pd
import numpy as np
from pathlib import Path

from apex_hybrid_master_engine import ApexSovereignMasterEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("ApexLiveTrader")

BASE_URL = "https://api.binance.com"
SYMBOLS = [
    "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT", 
    "ADAUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "RENDERUSDT",
    "LINKUSDT", "LTCUSDT", "UNIUSDT", "SUIUSDT", "INJUSDT"
]

def fetch_klines_1m(symbol: str, limit: int = 400) -> pd.DataFrame:
    url = f"{BASE_URL}/api/v3/klines"
    params = {"symbol": symbol, "interval": "1m", "limit": limit}
    res = requests.get(url, params=params, timeout=10)
    data = res.json()
    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "count", "taker_buy_base", "taker_buy_quote", "ignore"
    ]
    df = pd.DataFrame(data, columns=cols)
    for c in ["open", "high", "low", "close", "volume", "quote_volume", "taker_buy_base"]:
        df[c] = df[c].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df

def run_live_cycle():
    logger.info("📡 Connecting to Binance Spot live feed for BTC & 15 Top Assets...")
    
    # 1. Fetch BTC
    df_btc_1m = fetch_klines_1m("BTCUSDT", limit=400)
    df_btc_5m = ApexSovereignMasterEngine.resample_5m(df_btc_1m)[["open_time", "close"]].rename(columns={"close": "btc_c"})
    df_btc_5m["btc_24h"] = (df_btc_5m["btc_c"] / df_btc_5m["btc_c"].shift(288) - 1.0) * 100.0
    df_btc_5m["btc_4h"] = (df_btc_5m["btc_c"] / df_btc_5m["btc_c"].shift(48) - 1.0) * 100.0
    
    latest_btc_24h = df_btc_5m["btc_24h"].iloc[-1]
    latest_btc_4h = df_btc_5m["btc_4h"].iloc[-1]
    btc_price = df_btc_5m["btc_c"].iloc[-1]
    
    logger.info(f"🪙 BTC Spot Price: ${btc_price:,.2f} | 24h: {latest_btc_24h:+0.2f}% | 4h: {latest_btc_4h:+0.2f}%")
    
    # 2. Evaluate Matrix Profile Motifs across 15 coins
    candidates = []
    for sym in SYMBOLS:
        try:
            df_1m = fetch_klines_1m(sym, limit=400)
            df_5m = ApexSovereignMasterEngine.resample_5m(df_1m)
            df_ind = ApexSovereignMasterEngine.calculate_matrix_profile_indicators(df_5m, df_btc_5m)
            
            last_row = df_ind.iloc[-1]
            dist = last_row["motif_distance"]
            score = last_row["pattern_alpha_score"]
            is_cand = last_row["is_candidate"]
            cur_price = last_row["close"]
            
            candidates.append((sym, cur_price, dist, score, is_cand))
        except Exception as e:
            logger.warning(f"Error fetching {sym}: {e}")
            
    candidates.sort(key=lambda x: x[3], reverse=True)
    logger.info("--- 📊 REAL-TIME MATRIX PROFILE MOTIF DISCOVERY RANKINGS ---")
    for sym, px, dist, score, is_cand in candidates:
        status_str = "🎯 CANDIDATE TRIGGERED" if is_cand == 1 else "HOLD (Scanning)"
        logger.info(f"  • {sym:10s} | Price: ${px:<10.4f} | Motif Dist: {dist:0.3f} | Alpha Score: {score:0.2f} | Status: {status_str}")

if __name__ == "__main__":
    run_live_cycle()
