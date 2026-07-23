import os
import pandas as pd
import numpy as np

def assign_bar_ids_python(dollar_values, threshold, start_bar_id, start_cum):
    """
    Assigns bar IDs based on the accumulate-and-reset method.
    Uses a simple loop which is fast in Python for 2M rows.
    """
    n = len(dollar_values)
    bar_ids = np.empty(n, dtype=np.int64)
    cum = start_cum
    curr_id = start_bar_id
    
    for i in range(n):
        val = dollar_values[i]
        if not np.isfinite(val) or val < 0.0:
            val = 0.0
        cum += val
        bar_ids[i] = curr_id
        if cum >= threshold:
            curr_id += 1
            cum = 0.0
            
    return bar_ids, curr_id, cum

def generate_gold_dollar_bars(input_path, output_path, threshold=5000.0, chunksize=2000000):
    """
    Generates Dollar Bars from Gold tick data in a streaming fashion.
    Keeps memory usage extremely low.
    """
    print(f"⏳ Generating Gold Dollar Bars | Threshold: {threshold:.1f} | Chunksize: {chunksize:,}")
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    if os.path.exists(output_path):
        os.remove(output_path)
        
    # State tracking across chunks
    carryover_row = None
    carryover_tick_direction = 0.0
    carryover_bar_id = 0
    carryover_cum_dollar = 0.0
    
    # We will accumulate data for the open/incomplete bar at the end of each chunk
    incomplete_bar_df = None
    is_first_write = True
    total_bars_generated = 0
    
    required_cols = ['timestamp', 'ask', 'bid', 'ask_vol', 'bid_vol']
    
    reader = pd.read_csv(input_path, chunksize=chunksize, low_memory=False)
    
    for chunk_idx, chunk in enumerate(reader):
        print(f"📦 Processing chunk {chunk_idx + 1} ...")
        
        # Verify columns
        for col in required_cols:
            if col not in chunk.columns:
                raise ValueError(f"Missing column '{col}' in input file.")
                
        # Clean inputs: convert to float
        for col in ['ask', 'bid', 'ask_vol', 'bid_vol']:
            chunk[col] = pd.to_numeric(chunk[col], errors='coerce')
            
        chunk = chunk.dropna(subset=['ask', 'bid', 'ask_vol', 'bid_vol']).reset_index(drop=True)
        if chunk.empty:
            continue
            
        prepended = carryover_row is not None
        if prepended:
            helper_df = pd.DataFrame([carryover_row])
            work = pd.concat([helper_df, chunk], ignore_index=True)
        else:
            work = chunk.copy()
            
        # Compute mid price
        work['mid'] = (work['ask'] + work['bid']) / 2.0
        
        # Tick rule with continuity
        price_diff = work['mid'].diff()
        raw_direction = np.sign(price_diff).replace(0, np.nan)
        if prepended:
            raw_direction.iloc[0] = carryover_tick_direction
            
        tick_direction = raw_direction.ffill().fillna(0.0)
        work['tick_direction'] = tick_direction.values
        
        # Inferred trades
        work['inferred_price'] = np.where(
            work['tick_direction'] > 0, work['ask'],
            np.where(work['tick_direction'] < 0, work['bid'], work['mid'])
        )
        work['inferred_volume'] = np.where(
            work['tick_direction'] > 0, work['ask_vol'],
            np.where(work['tick_direction'] < 0, work['bid_vol'], 0.0)
        )
        work['trade_dollar_value'] = work['inferred_price'] * work['inferred_volume']
        work['signed_flow'] = work['trade_dollar_value'] * work['tick_direction']
        
        # Quote Imbalance
        book_vol = work['ask_vol'] + work['bid_vol']
        work['quote_imbalance'] = np.where(
            book_vol > 0, (work['bid_vol'] - work['ask_vol']) / book_vol, 0.0
        )
        
        # Order Flow Imbalance (OFI)
        # Using vectorised L1 OFI
        prev_bid = work['bid'].shift(1)
        prev_ask = work['ask'].shift(1)
        prev_bid_vol = work['bid_vol'].shift(1)
        prev_ask_vol = work['ask_vol'].shift(1)
        
        bid_ofi = np.where(
            work['bid'] > prev_bid, work['bid_vol'],
            np.where(work['bid'] == prev_bid, work['bid_vol'] - prev_bid_vol, -prev_bid_vol)
        )
        ask_ofi = np.where(
            work['ask'] < prev_ask, work['ask_vol'],
            np.where(work['ask'] == prev_ask, work['ask_vol'] - prev_ask_vol, -prev_ask_vol)
        )
        work['ofi_units'] = pd.Series(bid_ofi - ask_ofi, index=work.index).fillna(0.0).values
        work['ofi_dollar'] = work['ofi_units'] * work['mid']
        
        # Remove helper row before bar assignment
        if prepended:
            work = work.iloc[1:].reset_index(drop=True)
            if work.empty:
                continue
                
        # Update carryover tick direction for next chunk
        nonzero_directions = work.loc[work['tick_direction'] != 0, 'tick_direction']
        if len(nonzero_directions) > 0:
            carryover_tick_direction = float(nonzero_directions.iloc[-1])
            
        # Update carryover row for next chunk
        carryover_row = work.iloc[-1][required_cols].copy()
        
        # Combine with previous incomplete bar rows if any
        if incomplete_bar_df is not None and not incomplete_bar_df.empty:
            work = pd.concat([incomplete_bar_df, work], ignore_index=True)
            incomplete_bar_df = None
            
        # Assign bar IDs
        dollar_vals = work['trade_dollar_value'].fillna(0.0).clip(lower=0.0).values
        bar_ids, next_bar_id, carryover_cum_dollar = assign_bar_ids_python(
            dollar_vals, threshold, carryover_bar_id, carryover_cum_dollar
        )
        work['bar_id'] = bar_ids
        
        # Identify open bar
        open_bar_mask = work['bar_id'] == next_bar_id
        if open_bar_mask.any():
            incomplete_bar_df = work.loc[open_bar_mask].copy()
            work = work.loc[~open_bar_mask].reset_index(drop=True)
            
        carryover_bar_id = next_bar_id
        
        if work.empty:
            continue
            
        # We need tick-to-tick log returns within each bar to compute realized volatility
        # We calculate log return within bar: log_ret = ln(mid / mid_prev)
        work['tick_log_ret'] = np.log(work['mid'] / work['mid'].shift(1)).fillna(0.0)
        
        # Aggregation
        bars = work.groupby('bar_id', sort=True).agg(
            timestamp=('timestamp', 'last'),
            open=('inferred_price', 'first'),
            high=('inferred_price', 'max'),
            low=('inferred_price', 'min'),
            close=('inferred_price', 'last'),
            volume=('inferred_volume', 'sum'),
            dollar_value=('trade_dollar_value', 'sum'),
            signed_flow=('signed_flow', 'sum'),
            ofi_dollar=('ofi_dollar', 'sum'),
            quote_imbalance=('quote_imbalance', 'mean'),
            realized_vol=('tick_log_ret', lambda x: np.std(x) if len(x) > 1 else 0.0),
            spread=('ask', lambda x: (x - work.loc[x.index, 'bid']).mean()),
            num_ticks=('timestamp', 'count')
        ).reset_index(drop=True)
        
        # Write to output CSV
        if is_first_write:
            bars.to_csv(output_path, index=False, mode='w')
            is_first_write = False
        else:
            bars.to_csv(output_path, index=False, mode='a', header=False)
            
        total_bars_generated += len(bars)
        print(f"   Generated {len(bars)} bars. Total so far: {total_bars_generated}")
        
    # Write final incomplete bar if any
    if incomplete_bar_df is not None and not incomplete_bar_df.empty:
        tail = incomplete_bar_df.copy()
        tail['tick_log_ret'] = np.log(tail['mid'] / tail['mid'].shift(1)).fillna(0.0)
        
        final_bar = pd.DataFrame([{
            'timestamp': tail['timestamp'].iloc[-1],
            'open': tail['inferred_price'].iloc[0],
            'high': tail['inferred_price'].max(),
            'low': tail['inferred_price'].min(),
            'close': tail['inferred_price'].iloc[-1],
            'volume': tail['inferred_volume'].sum(),
            'dollar_value': tail['trade_dollar_value'].sum(),
            'signed_flow': tail['signed_flow'].sum(),
            'ofi_dollar': tail['ofi_dollar'].sum(),
            'quote_imbalance': tail['quote_imbalance'].mean(),
            'realized_vol': np.std(tail['tick_log_ret']) if len(tail) > 1 else 0.0,
            'spread': (tail['ask'] - tail['bid']).mean(),
            'num_ticks': len(tail)
        }])
        
        if is_first_write:
            final_bar.to_csv(output_path, index=False, mode='w')
            is_first_write = False
        else:
            final_bar.to_csv(output_path, index=False, mode='a', header=False)
        total_bars_generated += 1
        
    print(f"✅ Completed Gold Dollar Bars generation. Total bars: {total_bars_generated}")
    return total_bars_generated

if __name__ == "__main__":
    import sys
    inp = sys.argv[1] if len(sys.argv) > 1 else "xauusd_ticks_1y.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "processed_data/gold_dollar_bars.csv"
    generate_gold_dollar_bars(inp, out)
