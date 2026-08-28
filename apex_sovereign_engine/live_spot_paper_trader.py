"""
====================================================================================================
      🚀 APEX LIVE MULTI-COIN SCANNER & SPOT PAPER TRADER (CS-WRE LIVE v2.0)
      
      Live Spot Market Simulation with 30-Coin Cross-Sectional Scanner on Binance:
      - Strictly Halal Spot 1x Cash (0 Leverage, 0 Shorting, 0 CFDs)
      - Integrated Cross-Sectional Kyle Elasticity, Transfer Entropy & Matrix Profile Motifs
      - Ultra-lightweight (less than 20 KB per cycle to save 4G data)
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
logger = logging.getLogger("ApexLiveScanner")

BASE_URL = "https://api.binance.com"

# 30+ Diverse Spot Assets on Binance
ACTIVE_UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "DOGEUSDT",
    "ADAUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "RENDERUSDT", "LINKUSDT",
    "LTCUSDT", "UNIUSDT", "SUIUSDT", "INJUSDT", "PEPEUSDT", "SHIBUSDT",
    "FETUSDT", "AAVEUSDT", "TIAUSDT", "SEIUSDT", "ARBUSDT", "OPUSDT",
    "DOTUSDT", "FILUSDT", "STXUSDT", "FTMUSDT", "WLDUSDT", "ENAUSDT"
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

def scan_and_rank_top_universe():
    logger.info(f"📡 Scanning {len(ACTIVE_UNIVERSE)} spot pairs across Binance Market...")
    
    # 1. Fetch BTC Macro Armor
    df_btc_1m = fetch_klines_1m("BTCUSDT", limit=400)
    df_btc_5m = ApexSovereignMasterEngine.resample_5m(df_btc_1m)[["open_time", "close"]].rename(columns={"close": "btc_c"})
    df_btc_5m["btc_24h"] = (df_btc_5m["btc_c"] / df_btc_5m["btc_c"].shift(288) - 1.0) * 100.0
    df_btc_5m["btc_4h"] = (df_btc_5m["btc_c"] / df_btc_5m["btc_c"].shift(48) - 1.0) * 100.0
    
    latest_btc_24h = df_btc_5m["btc_24h"].iloc[-1]
    latest_btc_4h = df_btc_5m["btc_4h"].iloc[-1]
    btc_price = df_btc_5m["btc_c"].iloc[-1]
    
    logger.info(f"🪙 BTC Spot Price: ${btc_price:,.2f} | 24h: {latest_btc_24h:+0.2f}% | 4h: {latest_btc_4h:+0.2f}%")
    
    # 2. Real-Time 24h Ticker Triage (< 15 KB data)
    res = requests.get(f"{BASE_URL}/api/v3/ticker/24hr", timeout=10)
    tickers = {t["symbol"]: t for t in res.json() if t["symbol"] in ACTIVE_UNIVERSE}
    
    pre_filtered = []
    for sym in ACTIVE_UNIVERSE:
        if sym == "BTCUSDT":
            continue
        if sym in tickers:
            t = tickers[sym]
            q_vol = float(t["quoteVolume"])
            cnt = int(t["count"])
            px_chg = float(t["priceChangePercent"])
            if q_vol >= 2_000_000:
                kyle_est = abs(px_chg) / (np.sqrt(q_vol) / 1000.0 + 1e-4)
                pre_filtered.append((sym, kyle_est))
                
    pre_filtered.sort(key=lambda x: x[1], reverse=True)
    top_candidates = [x[0] for x in pre_filtered[:12]] # Deep scan top 12
    
    # 3. Deep Microstructure & Resonance Evaluation
    deep_ranked = []
    for sym in top_candidates:
        try:
            df_1m = fetch_klines_1m(sym, limit=200)
            df_5m = ApexSovereignMasterEngine.resample_5m(df_1m)
            df_ind = ApexSovereignMasterEngine.calculate_cross_sectional_indicators(df_5m, df_btc_5m)
            
            last_row = df_ind.iloc[-1]
            score = last_row["cross_resonance_score"]
            is_cand = last_row["is_candidate"]
            cur_price = last_row["close"]
            motif_dist = last_row["motif_distance"]
            
            deep_ranked.append((sym, cur_price, motif_dist, score, is_cand))
        except Exception as e:
            continue
            
    deep_ranked.sort(key=lambda x: x[3], reverse=True)
    
    logger.info("--- 🎯 CROSS-SECTIONAL WHALE RESONANCE TOP RANKINGS ---")
    for sym, px, dist, score, is_cand in deep_ranked:
        status_str = "🚀 EXPLOSIVE CANDIDATE TRIGGERED" if is_cand == 1 else "SCANNING"
        logger.info(f"  • {sym:12s} | Price: ${px:<10.4f} | Motif: {dist:0.3f} | Resonance Score: {score:0.2f} | Status: {status_str}")

if __name__ == "__main__":
    scan_and_rank_top_universe()
