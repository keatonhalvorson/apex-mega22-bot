import os
import sys
import time
from datetime import datetime

# Insert 'src' directory into the path
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from bar_generator import generate_gold_dollar_bars
from cross_asset_aligner import align_datasets
from feature_engineering import build_features_and_targets
from model_trainer import train_and_backtest

def main():
    print("=================================================================")
    print("   APEX PREDATOR QUANT TRADING ENGINE - RUN STRATEGY            ")
    print("=================================================================")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Cwd : {PROJECT_ROOT}")
    print("=================================================================\n")
    
    t_start = time.time()
    
    # 1. Define paths
    input_gold = "xauusd_ticks_1y.csv"
    input_dxy = "dxy_ticks_1y.csv"
    input_bond = "ustbond_ticks_1y.csv"
    input_vix = "vix_ticks_1y.csv"
    
    output_dir = "processed_data"
    os.makedirs(output_dir, exist_ok=True)
    
    gold_bars_path = os.path.join(output_dir, "gold_dollar_bars.csv")
    aligned_path = os.path.join(output_dir, "aligned_dataset.csv")
    features_path = os.path.join(output_dir, "features_and_targets.csv")
    
    # Output plot path in artifacts directory for automatic display
    artifact_plot_path = "/home/atheer/.gemini/antigravity/brain/ba8bd9c7-0a1e-41d8-aaf3-0aec8b37b595/backtest_results.png"
    
    # Parse arguments
    import argparse
    parser = argparse.ArgumentParser(description="Apex Predator Quant Strategy Runner")
    parser.add_argument("--rebuild", action="store_true", help="Force rebuild dollar bars and alignment")
    args, unknown = parser.parse_known_args()
    
    # Check if tick files exist (only required if we need to build from scratch)
    rebuild_needed = args.rebuild or not os.path.exists(gold_bars_path) or not os.path.exists(aligned_path)
    
    if rebuild_needed:
        for f in [input_gold, input_dxy, input_bond, input_vix]:
            if not os.path.exists(f):
                print(f"❌ Error: Required data file '{f}' not found in the current directory.")
                sys.exit(1)
            
    # 2. Generate Dollar Bars for Gold (XAUUSD)
    if os.path.exists(gold_bars_path) and not args.rebuild:
        print(f"ℹ️ {gold_bars_path} already exists. Skipping Bar Generation.")
    else:
        t0 = time.time()
        num_bars = generate_gold_dollar_bars(
            input_path=input_gold,
            output_path=gold_bars_path,
            threshold=5000.0,
            chunksize=2000000
        )
        print(f"⏱️ Bar Generation Time: {time.time() - t0:.2f} seconds\n")
    
    # 3. Align DXY, USTBOND, and VIX to Gold Dollar Bars
    if os.path.exists(aligned_path) and not args.rebuild:
        print(f"ℹ️ {aligned_path} already exists. Skipping Alignment.")
    else:
        t0 = time.time()
        align_datasets(
            gold_bars_path=gold_bars_path,
            dxy_ticks_path=input_dxy,
            bond_ticks_path=input_bond,
            vix_ticks_path=input_vix,
            output_path=aligned_path
        )
        print(f"⏱️ Alignment Time: {time.time() - t0:.2f} seconds\n")
    
    # 4. Feature Engineering
    t0 = time.time()
    build_features_and_targets(
        input_path=aligned_path,
        output_path=features_path,
        lead_horizon=5
    )
    print(f"⏱️ Feature Engineering Time: {time.time() - t0:.2f} seconds\n")
    
    # 5. Train Walk-Forward Models & Backtest
    t0 = time.time()
    train_and_backtest(
        features_path=features_path,
        output_plot_path=artifact_plot_path,
        lead_horizon=5
    )
    print(f"⏱️ Model Training and Backtesting Time: {time.time() - t0:.2f} seconds\n")
    
    total_time = time.time() - t_start
    print("=================================================================")
    print(f"✅ PIPELINE EXECUTED SUCCESSFULLY IN {total_time:.2f} SECONDS ({total_time/60:.2f} MINUTES)")
    print("=================================================================")

if __name__ == "__main__":
    main()
