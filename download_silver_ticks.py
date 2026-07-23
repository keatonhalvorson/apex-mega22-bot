import os
import sys
import time
import lzma
import struct
import urllib.request
import urllib.error
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- Settings ---
SYMBOL = "XAGUSD"
PRICE_DIVISOR = 1000.0  # Silver divisor is 1000 (3 decimal places e.g. 28.525)
MAX_WORKERS = 12        # Number of concurrent threads for downloading active hours
OUTPUT_FILE = "xagusd_ticks_1y.csv"

def download_hour_bytes(year, month_zero, day, hour, retries=4, backoff=2.0):
    url = f"https://datafeed.dukascopy.com/datafeed/{SYMBOL}/{year}/{month_zero:02d}/{day:02d}/{hour:02d}h_ticks.bi5"
    
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=15) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code == 503:
                time.sleep(5 * (attempt + 1))
            if attempt == retries - 1:
                return None
        except Exception as e:
            if attempt == retries - 1:
                return None
        time.sleep(backoff ** attempt)
    return None

def parse_bi5_to_df(compressed_bytes, year, month_zero, day, hour):
    if not compressed_bytes:
        return None
    
    try:
        decompressed = lzma.decompress(compressed_bytes)
    except Exception as e:
        return None
        
    n_records = len(decompressed) // 20
    if n_records == 0:
        return None
        
    dt_dtype = np.dtype('>i4')
    int_dtype = np.dtype('>i4')
    float_dtype = np.dtype('>f4')
    
    record_dtype = np.dtype([
        ('time_ms', dt_dtype),
        ('ask', int_dtype),
        ('bid', int_dtype),
        ('ask_vol', float_dtype),
        ('bid_vol', float_dtype)
    ])
    
    data = np.frombuffer(decompressed, dtype=record_dtype)
    
    base_dt = np.datetime64(f"{year}-{month_zero+1:02d}-{day:02d}T{hour:02d}:00:00.000")
    timestamps = base_dt + data['time_ms'].astype('timedelta64[ms]')
    
    asks = data['ask'] / PRICE_DIVISOR
    bids = data['bid'] / PRICE_DIVISOR
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'ask': asks,
        'bid': bids,
        'ask_vol': data['ask_vol'],
        'bid_vol': data['bid_vol']
    })
    
    return df

def fetch_single_hour(args):
    year, month_zero, day, hour = args
    compressed_bytes = download_hour_bytes(year, month_zero, day, hour)
    if compressed_bytes is None:
        return None
    return parse_bi5_to_df(compressed_bytes, year, month_zero, day, hour)

def download_day_ticks(current_date):
    year = current_date.year
    month_zero = current_date.month - 1
    day = current_date.day
    
    hours_tasks = [(year, month_zero, day, hour) for hour in range(24)]
    
    dfs = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(fetch_single_hour, task): task for task in hours_tasks}
        for future in as_completed(futures):
            df = future.result()
            if df is not None and not df.empty:
                dfs.append(df)
                
    if not dfs:
        return None
        
    day_df = pd.concat(dfs, ignore_index=True)
    day_df = day_df.sort_values('timestamp').reset_index(drop=True)
    return day_df

def run_download(start_date_str="2025-07-04", end_date_str="2026-07-04", dry_run=False):
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    
    total_days = (end_date - start_date).days + 1
    days_list = [start_date + timedelta(days=i) for i in range(total_days)]
    
    if dry_run:
        print("⚡ RUNNING IN DRY-RUN MODE (1 Day only) ⚡")
        days_list = days_list[:1]
    else:
        if os.path.exists(OUTPUT_FILE):
            print(f"Removing existing file: {OUTPUT_FILE}")
            os.remove(OUTPUT_FILE)
        
    print("╔══════════════════════════════════════════════════════╗")
    print("║   DUKASCOPY SILVER (XAGUSD) TICK DOWNLOADER          ║")
    print(f"║   Period: {days_list[0]} → {days_list[-1]}           ║")
    print(f"║   Output: {OUTPUT_FILE:<42s} ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    
    t_start = datetime.now()
    total_ticks = 0
    is_first_write = True
    
    for idx, current_date in enumerate(days_list, 1):
        date_start_time = datetime.now()
        
        if current_date.weekday() == 5:
            continue
            
        day_df = download_day_ticks(current_date)
        
        if day_df is not None and not day_df.empty:
            ticks_count = len(day_df)
            total_ticks += ticks_count
            day_df.to_csv(OUTPUT_FILE, mode='a', header=is_first_write, index=False)
            is_first_write = False
        else:
            ticks_count = 0
            
        elapsed_day = (datetime.now() - date_start_time).total_seconds()
        progress = (idx / len(days_list)) * 100
        
        print(f"[{progress:6.2f}%] processed {current_date} | Ticks: {ticks_count:,d} | Time: {elapsed_day:.2f}s | Cumulative Ticks: {total_ticks:,d}")
            
    total_elapsed = datetime.now() - t_start
    print(f"\n✓ Process complete!")
    print(f"Total Ticks Downloaded: {total_ticks:,d}")
    print(f"Total execution time  : {total_elapsed}")
    print(f"Output saved to: {os.path.abspath(OUTPUT_FILE)}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Dukascopy Silver Tick Downloader")
    parser.add_argument("--dry-run", action="store_true", help="Run a test download for 1 day only")
    args = parser.parse_args()
    
    run_download("2025-07-04", "2026-07-04", dry_run=args.dry_run)
