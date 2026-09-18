#!/usr/bin/env python3
"""
l2_orderbook_analyzer.py
Parses live Binance Spot Level 2 Order Book snapshots (btcusdt@depth20@100ms)
and computes real-time Order Book Imbalance (OBI), Micro-Price, and Depth Spread.
"""

import os
import glob
import json
import sys
import pandas as pd
import numpy as np

# Ensure apex_sovereign_engine is importable
ENGINE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "apex_sovereign_engine")
if ENGINE_PATH not in sys.path:
    sys.path.insert(0, ENGINE_PATH)

from empirical_microstructure import (
    compute_stoikov_micro_price,
    compute_discrete_ofi,
    compute_multi_level_ofi,
    compute_order_book_imbalance
)

L2_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "l2_live_data")

def analyze_l2_snapshots():
    files = sorted(glob.glob(os.path.join(L2_DATA_DIR, "*.jsonl")))
    if not files:
        print("[ERR] No L2 snapshot JSONL files found in l2_live_data/")
        return

    latest_file = files[-1]
    print(f"[INFO] Analyzing Level 2 Order Book Snapshots from: {os.path.basename(latest_file)}")

    records = []
    with open(latest_file, "r") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    print(f"[INFO] Loaded {len(records):,} live L2 snapshots (100ms intervals).")

    analyzed_rows = []
    prev_rec = None

    for rec in records:
        ts = rec["recv_timestamp"]
        bids = rec["bids"]  # list of [price, qty]
        asks = rec["asks"]  # list of [price, qty]

        if not bids or not asks:
            continue

        best_bid_p, best_bid_q = float(bids[0][0]), float(bids[0][1])
        best_ask_p, best_ask_q = float(asks[0][0]), float(asks[0][1])

        # Top-5 Depth Sums
        top5_bid_qty = sum(float(b[1]) for b in bids[:5])
        top5_ask_qty = sum(float(a[1]) for a in asks[:5])

        # Top-20 Depth Sums
        top20_bid_qty = sum(float(b[1]) for b in bids)
        top20_ask_qty = sum(float(a[1]) for a in asks)

        # 1. Order Book Imbalance (OBI) Top 5 & Top 20
        obi_top5 = compute_order_book_imbalance(top5_bid_qty, top5_ask_qty)
        obi_top20 = compute_order_book_imbalance(top20_bid_qty, top20_ask_qty)

        # 2. Micro-Price (Stoikov) - Strictly bounded between bid and ask
        mid_price = (best_bid_p + best_ask_p) / 2.0
        micro_price = compute_stoikov_micro_price(best_bid_p, best_bid_q, best_ask_p, best_ask_q)

        # 3. Spread (in basis points)
        spread_bps = ((best_ask_p - best_bid_p) / mid_price) * 10000.0 if mid_price > 0 else 0.0

        # 4. Sequential Order Flow Imbalance (OFI)
        if prev_rec is not None and prev_rec["bids"] and prev_rec["asks"]:
            prev_bid_p = float(prev_rec["bids"][0][0])
            prev_bid_q = float(prev_rec["bids"][0][1])
            prev_ask_p = float(prev_rec["asks"][0][0])
            prev_ask_q = float(prev_rec["asks"][0][1])

            ofi = compute_discrete_ofi(
                prev_bid_p, prev_bid_q, best_bid_p, best_bid_q,
                prev_ask_p, prev_ask_q, best_ask_p, best_ask_q
            )
            ofi_top5 = compute_multi_level_ofi(
                prev_rec["bids"], bids, prev_rec["asks"], asks, levels=5
            )
        else:
            ofi = 0.0
            ofi_top5 = 0.0

        prev_rec = rec

        analyzed_rows.append({
            "timestamp": ts,
            "best_bid": best_bid_p,
            "best_ask": best_ask_p,
            "mid_price": mid_price,
            "micro_price": micro_price,
            "spread_bps": spread_bps,
            "obi_top5": obi_top5,
            "obi_top20": obi_top20,
            "ofi": ofi,
            "ofi_top5": ofi_top5,
            "top5_bid_qty": top5_bid_qty,
            "top5_ask_qty": top5_ask_qty
        })

    df_l2 = pd.DataFrame(analyzed_rows)
    
    print("\n" + "="*95)
    print("      LIVE LEVEL 2 ORDER BOOK MICROSTRUCTURE METRICS (SAMPLE)")
    print("="*95)
    print(df_l2[["timestamp", "best_bid", "best_ask", "mid_price", "micro_price", "spread_bps", "obi_top5", "ofi", "ofi_top5"]].head(10).to_string(index=False))
    print("="*95 + "\n")

    summary_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "processed_data", "l2_analyzed_metrics.csv")
    df_l2.to_csv(summary_file, index=False)
    print(f"[OK] Saved Analyzed L2 Metrics to: {summary_file}")
    return df_l2

if __name__ == "__main__":
    analyze_l2_snapshots()
