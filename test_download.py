import urllib.request
import lzma
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

def test_numpy_parser():
    # URL for July 3, 2026, 10:00 UTC
    url = "https://datafeed.dukascopy.com/datafeed/XAUUSD/2026/06/03/10h_ticks.bi5"
    print(f"Downloading from {url}...")
    
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            compressed_data = response.read()
        print(f"Downloaded {len(compressed_data)} bytes.")
        
        # Decompress LZMA
        decompressed_data = lzma.decompress(compressed_data)
        print(f"Decompressed to {len(decompressed_data)} bytes.")
        
        # NumPy Structured Array Parser
        dtype = np.dtype([
            ('time_ms', '>u4'),
            ('ask', '>u4'),
            ('bid', '>u4'),
            ('ask_vol', '>f4'),
            ('bid_vol', '>f4')
        ])
        
        t0 = datetime.now()
        data = np.frombuffer(decompressed_data, dtype=dtype)
        
        # Convert prices and round volumes
        ask_price = data['ask'] / 1000.0
        bid_price = data['bid'] / 1000.0
        ask_vol = np.round(data['ask_vol'], 5)
        bid_vol = np.round(data['bid_vol'], 5)
        
        # Calculate timestamps
        base_dt = np.datetime64("2026-07-03T10:00:00.000")
        timestamps = base_dt + data['time_ms'].astype('timedelta64[ms]')
        
        # Create DataFrame
        df = pd.DataFrame({
            'timestamp': timestamps,
            'ask': ask_price,
            'bid': bid_price,
            'ask_vol': ask_vol,
            'bid_vol': bid_vol
        })
        
        # Convert timestamp to string format (3 decimals)
        df['timestamp'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S.%f').str[:-3]
        
        elapsed = (datetime.now() - t0).total_seconds()
        print(f"Parsed {len(df):,} records in {elapsed:.4f} seconds!")
        
        print("\nFirst 5 rows:")
        print(df.head())
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_numpy_parser()
