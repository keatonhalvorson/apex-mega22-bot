import os
import sys
import gc
import numpy as np
import pandas as pd

def build_gold_silver_pairs_dataset():
    gold_file = "xauusd_ticks_1y.csv"
    silver_file = "xagusd_ticks_1y.csv"
    output_file = "processed_data/gold_silver_pairs_dataset.csv"
    
    if not os.path.exists(gold_file) or not os.path.exists(silver_file):
        print("❌ Gold or Silver tick CSV file missing.")
        return
        
    print("⏳ Building Synchronized Gold/Silver Pairs Dataset...")
    
    # -------------------------------------------------------------
    # 1. BUILD MASTER GOLD DOLLAR BARS ($5,000 Threshold)
    # Generates ~10,900 Master Dollar Bars for 1 year
    # -------------------------------------------------------------
    print("   1. Processing Gold ticks (Threshold = 5,000.0)...")
    dollar_threshold = 5000.0
    
    gold_bars_list = []
    cum_dollar_vol = 0.0
    
    for chunk in pd.read_csv(
        gold_file,
        usecols=['timestamp', 'ask', 'bid', 'ask_vol', 'bid_vol'],
        dtype={'ask': 'float32', 'bid': 'float32', 'ask_vol': 'float32', 'bid_vol': 'float32'},
        chunksize=2000000
    ):
        chunk['mid'] = ((chunk['ask'] + chunk['bid']) * 0.5).astype('float32')
        chunk['spread'] = (chunk['ask'] - chunk['bid']).astype('float32')
        chunk['dollar_vol'] = (chunk['mid'] * (chunk['ask_vol'] + chunk['bid_vol'])).astype('float64')
        
        chunk['cum_vol'] = cum_dollar_vol + chunk['dollar_vol'].cumsum()
        cum_dollar_vol = chunk['cum_vol'].iloc[-1]
        
        chunk['bar_group'] = (chunk['cum_vol'] // dollar_threshold).astype('int32')
        
        aggregated = chunk.groupby('bar_group').agg(
            timestamp=('timestamp', 'last'),
            open=('mid', 'first'),
            high=('mid', 'max'),
            low=('mid', 'min'),
            close=('mid', 'last'),
            volume=('dollar_vol', 'sum'),
            spread=('spread', 'mean')
        ).reset_index()
        
        gold_bars_list.append(aggregated)
        del chunk
        gc.collect()
        
    all_gold_bars = pd.concat(gold_bars_list, ignore_index=True)
    del gold_bars_list
    gc.collect()
    
    gold_bars = all_gold_bars.groupby('bar_group').agg(
        timestamp=('timestamp', 'last'),
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
        volume=('volume', 'sum'),
        spread=('spread', 'mean')
    ).reset_index(drop=True)
    
    gold_bars['timestamp'] = pd.to_datetime(gold_bars['timestamp'])
    gold_bars = gold_bars.sort_values('timestamp').reset_index(drop=True)
    del all_gold_bars
    gc.collect()
    
    print(f"   Generated {len(gold_bars):,d} Master Gold Dollar Bars.")
    
    # -------------------------------------------------------------
    # 2. LOAD SILVER TICKS & DIRECT MERGE ASOF
    # -------------------------------------------------------------
    print("   2. Loading Silver ticks & synchronizing timestamps...")
    silver_ticks = pd.read_csv(
        silver_file,
        usecols=['timestamp', 'ask', 'bid'],
        dtype={'ask': 'float32', 'bid': 'float32'}
    )
    silver_ticks['timestamp'] = pd.to_datetime(silver_ticks['timestamp'])
    silver_ticks['mid_silver'] = ((silver_ticks['ask'] + silver_ticks['bid']) * 0.5).astype('float32')
    silver_ticks['spread_silver'] = (silver_ticks['ask'] - silver_ticks['bid']).astype('float32')
    silver_ticks = silver_ticks[['timestamp', 'mid_silver', 'spread_silver']].sort_values('timestamp').reset_index(drop=True)
    
    print("   3. Merging Silver with Master Gold Dollar Bars (pd.merge_asof)...")
    pairs_df = pd.merge_asof(
        gold_bars,
        silver_ticks,
        on='timestamp',
        direction='backward'
    )
    
    del silver_ticks, gold_bars
    gc.collect()
    
    pairs_df['mid_silver'] = pairs_df['mid_silver'].ffill().bfill()
    pairs_df['spread_silver'] = pairs_df['spread_silver'].ffill().bfill()
    
    # -------------------------------------------------------------
    # 3. COMPUTE COINTEGRATION SPREAD & Z-SCORES
    # -------------------------------------------------------------
    print("   4. Computing Dynamic Rolling Cointegration Vector & Spread Z-Scores...")
    pairs_df['log_gold'] = np.log(pairs_df['close'])
    pairs_df['log_silver'] = np.log(pairs_df['mid_silver'])
    
    window = 30
    cov = pairs_df['log_gold'].rolling(window).cov(pairs_df['log_silver'])
    var_silver = pairs_df['log_silver'].rolling(window).var()
    pairs_df['rolling_beta'] = (cov / (var_silver + 1e-8)).fillna(0.85)
    
    # Dynamic Cointegrated Spread = log(Gold) - Beta * log(Silver)
    pairs_df['spread_val'] = pairs_df['log_gold'] - (pairs_df['rolling_beta'] * pairs_df['log_silver'])
    
    # Spread Rolling Z-Score
    spread_mean = pairs_df['spread_val'].rolling(window).mean()
    spread_std = pairs_df['spread_val'].rolling(window).std()
    pairs_df['spread_zscore'] = (pairs_df['spread_val'] - spread_mean) / (spread_std + 1e-8)
    
    # Velocity of Spread Z-Score
    pairs_df['spread_velocity'] = pairs_df['spread_zscore'] - pairs_df['spread_zscore'].shift(1)
    
    # Returns
    pairs_df['gold_ret_1'] = pairs_df['close'].pct_change(1)
    pairs_df['silver_ret_1'] = pairs_df['mid_silver'].pct_change(1)
    
    # Target variable: Lead Spread Return over next 5 bars
    pairs_df['target_spread_lead5'] = pairs_df['spread_zscore'].shift(-5) - pairs_df['spread_zscore']
    
    pairs_df = pairs_df.dropna().reset_index(drop=True)
    
    os.makedirs("processed_data", exist_ok=True)
    pairs_df.to_csv(output_file, index=False)
    print(f"✅ Synchronized Gold/Silver Pairs Dataset built! Saved to {output_file} ({len(pairs_df):,d} rows)")

if __name__ == '__main__':
    build_gold_silver_pairs_dataset()
