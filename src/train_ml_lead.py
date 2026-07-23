import os
import pandas as pd
import numpy as np
from catboost import CatBoostRegressor

def train_ml_model():
    print("⏳ Loading features_and_targets.csv...")
    df = pd.read_csv("processed_data/features_and_targets.csv")
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.dropna(subset=['target']).reset_index(drop=True)
    
    # Define features
    feature_cols = [
        'gold_ret_1', 'gold_ret_3', 'gold_ret_5', 'gold_ret_10',
        'gold_ofi_norm_1', 'gold_ofi_norm_5',
        'gold_signed_flow_norm_1', 'gold_signed_flow_norm_5',
        'gold_quote_imbalance_1', 'gold_quote_imbalance_5',
        'gold_realized_vol_1', 'gold_realized_vol_5',
        'dxy_ret_1', 'dxy_ret_3', 'dxy_ret_5', 'dxy_vol_5',
        'bond_ret_1', 'bond_ret_3', 'bond_ret_5', 'bond_vol_5',
        'vix_ret_1', 'vix_ret_3', 'vix_ret_5', 'vix_z_score_20',
        'gold_dxy_corr_20', 'gold_bond_corr_20', 'vol_ratio_5_20',
        'z_score', 'rsi_14', 'h_rsi_14',
        'gold_ofi_accel_5', 'quote_imbalance_velocity_5', 'price_impact_coef_5', 'vwap_dev_20',
        'hft_abs_bull', 'hft_abs_bear'
    ]
    
    # Split train/test chronologically to avoid lookahead bias
    # Train on first 75%, test on last 25% (which includes our backtest range)
    split_idx = int(len(df) * 0.75)
    
    X = df[feature_cols]
    y = df['target']
    
    X_train, X_test = X.iloc[:split_idx], X.iloc[split_idx:]
    y_train, y_test = y.iloc[:split_idx], y.iloc[split_idx:]
    
    print(f"📈 Training CatBoost Regressor on {len(X_train)} bars...")
    model = CatBoostRegressor(
        iterations=500,
        learning_rate=0.03,
        depth=6,
        eval_metric='RMSE',
        random_seed=42,
        verbose=100
    )
    
    model.fit(
        X_train, y_train,
        eval_set=(X_test, y_test),
        early_stopping_rounds=50,
        verbose=100
    )
    
    os.makedirs("processed_data", exist_ok=True)
    model.save_model("processed_data/ml_trend_model.cbm")
    print("✅ Model trained and saved to processed_data/ml_trend_model.cbm!")
    
if __name__ == '__main__':
    train_ml_model()
