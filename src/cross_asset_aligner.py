import os
import pandas as pd
import numpy as np

def downsample_ticks(input_path, output_path, chunksize=1000000):
    """
    Downsamples tick data to 30-second intervals to keep RAM usage minimal.
    Uses chunked processing to prevent OOM errors.
    """
    print(f"   Downsampling {os.path.basename(input_path)} to 30s mid prices...")
    
    reader = pd.read_csv(input_path, chunksize=chunksize, usecols=['timestamp', 'ask', 'bid'], low_memory=False)
    resampled_chunks = []
    
    for chunk in reader:
        # Convert types safely
        for col in ['ask', 'bid']:
            chunk[col] = pd.to_numeric(chunk[col], errors='coerce')
        chunk = chunk.dropna(subset=['ask', 'bid']).reset_index(drop=True)
        if chunk.empty:
            continue
            
        chunk['timestamp'] = pd.to_datetime(chunk['timestamp'])
        chunk['mid'] = (chunk['ask'] + chunk['bid']) / 2.0
        chunk['time_30s'] = chunk['timestamp'].dt.floor('30s')
        
        # Take the last mid price in each 30s period within this chunk
        resampled_chunk = chunk.groupby('time_30s')[['mid']].last()
        resampled_chunks.append(resampled_chunk)
        
    if not resampled_chunks:
        raise ValueError(f"No valid data parsed from {input_path}")
        
    # Combine resampled chunks and group again to merge boundary intervals
    df_combined = pd.concat(resampled_chunks)
    df_final = df_combined.groupby(df_combined.index).last().sort_index()
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df_final.to_csv(output_path)
    print(f"   ✓ Downsampled {os.path.basename(input_path)} -> {output_path} ({len(df_final):,} rows)")

def align_datasets(gold_bars_path, dxy_ticks_path, bond_ticks_path, vix_ticks_path, output_path, temp_dir="temp_resampled"):
    """
    Aligns DXY, USTBOND, and VIX to Gold Dollar Bars using pd.merge_asof.
    """
    print("⏳ Aligning cross-asset ticks to Gold Dollar Bars...")
    
    # 1. Downsample auxiliary assets
    os.makedirs(temp_dir, exist_ok=True)
    
    dxy_resampled_path = os.path.join(temp_dir, "dxy_30s.csv")
    bond_resampled_path = os.path.join(temp_dir, "bond_30s.csv")
    vix_resampled_path = os.path.join(temp_dir, "vix_30s.csv")
    
    downsample_ticks(dxy_ticks_path, dxy_resampled_path)
    downsample_ticks(bond_ticks_path, bond_resampled_path)
    downsample_ticks(vix_ticks_path, vix_resampled_path)
    
    # 2. Load Gold Dollar Bars
    print("   Loading Gold Dollar Bars...")
    gold_df = pd.read_csv(gold_bars_path)
    gold_df['timestamp'] = pd.to_datetime(gold_df['timestamp'])
    # Sort just in case
    gold_df = gold_df.sort_values('timestamp').reset_index(drop=True)
    
    # 3. Load resampled auxiliary assets
    print("   Loading resampled datasets...")
    dxy_df = pd.read_csv(dxy_resampled_path, parse_dates=['time_30s']).sort_values('time_30s')
    bond_df = pd.read_csv(bond_resampled_path, parse_dates=['time_30s']).sort_values('time_30s')
    vix_df = pd.read_csv(vix_resampled_path, parse_dates=['time_30s']).sort_values('time_30s')
    
    # 4. Perform pd.merge_asof to align DXY, USTBOND, and VIX prices
    print("   Performing as-of merges...")
    
    # Merge DXY
    merged = pd.merge_asof(
        gold_df,
        dxy_df,
        left_on='timestamp',
        right_on='time_30s',
        direction='backward'
    ).rename(columns={'mid': 'dxy_price'}).drop(columns=['time_30s'])
    
    # Forward fill DXY just in case there are nan gaps
    merged['dxy_price'] = merged['dxy_price'].ffill().bfill()
    
    # Merge USTBOND
    merged = pd.merge_asof(
        merged,
        bond_df,
        left_on='timestamp',
        right_on='time_30s',
        direction='backward'
    ).rename(columns={'mid': 'bond_price'}).drop(columns=['time_30s'])
    
    # Forward fill USTBOND
    merged['bond_price'] = merged['bond_price'].ffill().bfill()
    
    # Merge VIX
    merged = pd.merge_asof(
        merged,
        vix_df,
        left_on='timestamp',
        right_on='time_30s',
        direction='backward'
    ).rename(columns={'mid': 'vix_price'}).drop(columns=['time_30s'])
    
    # Forward fill VIX
    merged['vix_price'] = merged['vix_price'].ffill().bfill()
    
    # 5. Save output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    merged.to_csv(output_path, index=False)
    print(f"✅ Alignment complete! Dataset saved to {output_path} ({len(merged):,} rows)")
    
    # Clean up temporary resampled files
    try:
        os.remove(dxy_resampled_path)
        os.remove(bond_resampled_path)
        os.remove(vix_resampled_path)
        os.rmdir(temp_dir)
        print("   Cleaned up temporary resampled files.")
    except Exception as e:
        print(f"   [Warning] Could not clean up temporary files: {e}")
        
    return merged

if __name__ == "__main__":
    import sys
    gold_p = sys.argv[1] if len(sys.argv) > 1 else "processed_data/gold_dollar_bars.csv"
    dxy_p = sys.argv[2] if len(sys.argv) > 2 else "dxy_ticks_1y.csv"
    bond_p = sys.argv[3] if len(sys.argv) > 3 else "ustbond_ticks_1y.csv"
    vix_p = sys.argv[4] if len(sys.argv) > 4 else "vix_ticks_1y.csv"
    out_p = sys.argv[5] if len(sys.argv) > 5 else "processed_data/aligned_dataset.csv"
    
    align_datasets(gold_p, dxy_p, bond_p, vix_p, out_p)
