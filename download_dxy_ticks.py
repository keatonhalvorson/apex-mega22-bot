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
SYMBOL = "DOLLARIDXUSD"
PRICE_DIVISOR = 1000.0  # DXY divisor is 1000 (3 decimal places)
MAX_WORKERS = 12        # Number of concurrent threads for downloading active hours
OUTPUT_FILE = "dxy_ticks_1y.csv"

def download_hour_bytes(year, month_zero, day, hour, retries=4, backoff=2.0):
    """
    Download raw compressed .bi5 bytes for a specific hour.
    Returns bytes if successful, None if 404 (weekend/market closed) or failed.
    """
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
                # Rate limited: Cool down
                time.sleep(5 * (attempt + 1))
            if attempt == retries - 1:
                print(f"\n[Error] Failed HTTP {e.code} for URL: {url}")
                return None
        except Exception as e:
            if attempt == retries - 1:
                print(f"\n[Error] Connection error for URL: {url} -> {e}")
                return None
        time.sleep(backoff ** attempt)
    return None

def parse_bi5_to_df(compressed_bytes, year, month_zero, day, hour):
    """
    Vectorized parse of .bi5 tick records using NumPy and Pandas.
    Returns a DataFrame with columns: ['timestamp', 'ask', 'bid', 'ask_vol', 'bid_vol']
    """
    if not compressed_bytes:
        return None
    
    try:
        decompressed = lzma.decompress(compressed_bytes)
    except Exception as e:
        print(f"\n[Error] LZMA decompression failed for {year}-{month_zero+1:02d}-{day:02d} {hour:02d}:00: {e}")
        return None
        
    dtype = np.dtype([
        ('time_ms', '>u4'),
        ('ask', '>u4'),
        ('bid', '>u4'),
        ('ask_vol', '>f4'),
        ('bid_vol', '>f4')
    ])
    
    data = np.frombuffer(decompressed, dtype=dtype)
    if len(data) == 0:
        return None
        
    ask_price = data['ask'] / PRICE_DIVISOR
    bid_price = data['bid'] / PRICE_DIVISOR
    ask_vol = np.round(data['ask_vol'], 5)
    bid_vol = np.round(data['bid_vol'], 5)
    
    # Vectorized timestamp computation
    base_dt = np.datetime64(f"{year}-{month_zero+1:02d}-{day:02d}T{hour:02d}:00:00.000")
    timestamps = base_dt + data['time_ms'].astype('timedelta64[ms]')
    
    df = pd.DataFrame({
        'timestamp': timestamps,
        'ask': ask_price,
        'bid': bid_price,
        'ask_vol': ask_vol,
        'bid_vol': bid_vol
    })
    
    # Format timestamp to string with 3 decimal places
    df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S.%f').str[:-3]
    return df

def get_active_hours_for_date(date_obj):
    """
    Returns the list of active hours for a given date in UTC.
    Market is open Sunday 22:00 UTC to Friday 22:00 UTC.
    """
    weekday = date_obj.weekday()  # 0: Monday, ..., 6: Sunday
    
    if weekday == 5:  # Saturday: completely closed
        return []
    elif weekday == 6:  # Sunday: opens at 22:00
        return [22, 23]
    elif weekday == 4:  # Friday: closes at 22:00 (hours 22, 23 are closed)
        return list(range(22))
    else:  # Monday to Thursday: open all day
        return list(range(24))

def process_day(date_obj):
    """
    Downloads and parses active hours of a single day in parallel.
    Returns a single sorted DataFrame of ticks for that day.
    """
    active_hours = get_active_hours_for_date(date_obj)
    if not active_hours:
        return None
        
    year = date_obj.year
    month_zero = date_obj.month - 1
    day = date_obj.day
    
    dfs = []
    
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(active_hours))) as executor:
        futures = {}
        for hour in active_hours:
            futures[executor.submit(download_hour_bytes, year, month_zero, day, hour)] = hour
            
        for future in as_completed(futures):
            hour = futures[future]
            try:
                data = future.result()
                if data:
                    df = parse_bi5_to_df(data, year, month_zero, day, hour)
                    if df is not None and not df.empty:
                        dfs.append(df)
            except Exception as e:
                print(f"\n[Error] Thread execution error for hour {hour}: {e}")
                
    if not dfs:
        return None
        
    # Concatenate and sort
    day_df = pd.concat(dfs, ignore_index=True)
    day_df.sort_values(by='timestamp', inplace=True)
    return day_df

def run_download(start_date_str, end_date_str, dry_run=False):
    start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
    
    # Calculate days list
    total_days = (end_date - start_date).days + 1
    days_list = [start_date + timedelta(days=i) for i in range(total_days)]
    
    if dry_run:
        print("⚡ RUNNING IN DRY-RUN MODE (1 Day only) ⚡")
        days_list = days_list[:1]
    else:
        # Clear existing file to avoid duplicate header/data
        if os.path.exists(OUTPUT_FILE):
            print(f"Removing existing file: {OUTPUT_FILE}")
            os.remove(OUTPUT_FILE)
        
    print("╔══════════════════════════════════════════════════════╗")
    print("║   DUCASCOPY US DOLLAR INDEX (DXY) TICK DOWNLOADER    ║")
    print(f"║   Period: {days_list[0]} → {days_list[-1]}           ║")
    print(f"║   Output: {OUTPUT_FILE:<42s} ║")
    print("╚══════════════════════════════════════════════════════╝\n")
    
    t_start = datetime.now()
    total_ticks = 0
    is_first_write = True
    
    for idx, current_date in enumerate(days_list, 1):
        date_start_time = datetime.now()
        
        # Check if Saturday (skip completely without thread overhead)
        if current_date.weekday() == 5:
            elapsed_day = (datetime.now() - date_start_time).total_seconds()
            progress = (idx / len(days_list)) * 100
            print(f"[{progress:6.2f}%] processed {current_date} | Ticks: 0 (Weekend Skip) | Time: {elapsed_day:.2f}s | Cumulative Ticks: {total_ticks:,d}")
            continue
            
        day_df = process_day(current_date)
        
        if day_df is not None and not day_df.empty:
            ticks_count = len(day_df)
            total_ticks += ticks_count
            
            # Write immediately to disk
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
    parser = argparse.ArgumentParser(description="Dukascopy DXY Tick Downloader")
    parser.add_argument("--dry-run", action="store_true", help="Run a test download for 1 day only")
    args = parser.parse_args()
    
    # Download for the exact same year
    run_download("2025-07-04", "2026-07-04", dry_run=args.dry_run)
