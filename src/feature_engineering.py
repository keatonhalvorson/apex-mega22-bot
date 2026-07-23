import os
import pandas as pd
import numpy as np

def calculate_rsi(prices, period=14):
    deltas = np.diff(prices)
    seed = deltas[:period+1]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / (down + 1e-8)
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)
    
    for i in range(period, len(prices)):
        delta = deltas[i-1]
        if delta > 0:
            upval = delta
            downval = 0.
        else:
            upval = 0.
            downval = -delta
        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / (down + 1e-8)
        rsi[i] = 100. - 100. / (1. + rs)
    return rsi

def build_features_and_targets(input_path, output_path, lead_horizon=5):
    """
    Loads aligned dataset and engineers microstructural and cross-asset features.
    Saves the final clean dataset ready for training.
    """
    print(f"⏳ Building features and targets | Horizon: {lead_horizon} bars...")
    
    df = pd.read_csv(input_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Load and merge hourly bars for macro trend data
    df_h = pd.read_csv("tv_gold_1h_2m.csv")
    df_h['datetime'] = pd.to_datetime(df_h['datetime'])
    df_h = df_h.sort_values('datetime').reset_index(drop=True)
    df_h['ema_20'] = df_h['close'].ewm(span=20, adjust=False).mean()
    df_h['rsi_14'] = calculate_rsi(df_h['close'].values, period=14)
    df_h_sub = df_h[['datetime', 'ema_20', 'rsi_14']].rename(columns={
        'ema_20': 'h_ema_20',
        'rsi_14': 'h_rsi_14'
    })
    
    df = pd.merge_asof(
        df, df_h_sub,
        left_on='timestamp', right_on='datetime',
        direction='backward'
    ).drop(columns=['datetime'])
    
    # 1. Gold Returns (Log returns)
    df['gold_ret_1'] = np.log(df['close'] / df['close'].shift(1))
    df['gold_ret_3'] = np.log(df['close'] / df['close'].shift(3))
    df['gold_ret_5'] = np.log(df['close'] / df['close'].shift(5))
    df['gold_ret_10'] = np.log(df['close'] / df['close'].shift(10))
    
    # 2. Normalized Gold Microstructure
    # Normalise OFI dollar value and signed flow by dollar volume
    epsilon = 1e-8
    df['gold_ofi_norm_1'] = df['ofi_dollar'] / (df['dollar_value'] + epsilon)
    df['gold_ofi_norm_5'] = df['ofi_dollar'].rolling(5).sum() / (df['dollar_value'].rolling(5).sum() + epsilon)
    
    df['gold_signed_flow_norm_1'] = df['signed_flow'] / (df['dollar_value'] + epsilon)
    df['gold_signed_flow_norm_5'] = df['signed_flow'].rolling(5).sum() / (df['dollar_value'].rolling(5).sum() + epsilon)
    
    df['gold_quote_imbalance_1'] = df['quote_imbalance']
    df['gold_quote_imbalance_5'] = df['quote_imbalance'].rolling(5).mean()
    
    df['gold_realized_vol_1'] = df['realized_vol']
    df['gold_realized_vol_5'] = df['realized_vol'].rolling(5).mean()
    
    # 3. Macro Cross-Asset Returns
    # DXY Returns and Vol
    df['dxy_ret_1'] = np.log(df['dxy_price'] / df['dxy_price'].shift(1))
    df['dxy_ret_3'] = np.log(df['dxy_price'] / df['dxy_price'].shift(3))
    df['dxy_ret_5'] = np.log(df['dxy_price'] / df['dxy_price'].shift(5))
    df['dxy_vol_5'] = df['dxy_ret_1'].rolling(5).std()
    
    # USTBOND Returns and Vol
    df['bond_ret_1'] = np.log(df['bond_price'] / df['bond_price'].shift(1))
    df['bond_ret_3'] = np.log(df['bond_price'] / df['bond_price'].shift(3))
    df['bond_ret_5'] = np.log(df['bond_price'] / df['bond_price'].shift(5))
    df['bond_vol_5'] = df['bond_ret_1'].rolling(5).std()
    
    # VIX Returns and Z-Score
    df['vix_ret_1'] = np.log(df['vix_price'] / df['vix_price'].shift(1))
    df['vix_ret_3'] = np.log(df['vix_price'] / df['vix_price'].shift(3))
    df['vix_ret_5'] = np.log(df['vix_price'] / df['vix_price'].shift(5))
    df['vix_z_score_20'] = (df['vix_price'] - df['vix_price'].rolling(20).mean()) / (df['vix_price'].rolling(20).std() + 1e-8)
    
    # 4. Advanced Quant Calculations
    # Rolling Correlations
    df['gold_dxy_corr_20'] = df['gold_ret_1'].rolling(20).corr(df['dxy_ret_1'])
    df['gold_bond_corr_20'] = df['gold_ret_1'].rolling(20).corr(df['bond_ret_1'])
    
    # Volatility Ratio
    df['vol_ratio_5_20'] = df['gold_realized_vol_1'] / (df['gold_realized_vol_5'] + 1e-8)
    
    # Local Z-score, RSI, ATR
    df['rolling_mean'] = df['close'].rolling(20).mean()
    df['rolling_std'] = df['close'].rolling(20).std()
    df['z_score'] = (df['close'] - df['rolling_mean']) / (df['rolling_std'] + 1e-8)
    df['rsi_14'] = calculate_rsi(df['close'].values, period=14)
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    df['atr_5'] = ranges.max(axis=1).rolling(5).mean()
    
    # 5. HFT Footprint Features
    # OFI Acceleration
    df['gold_ofi_accel_5'] = df['gold_ofi_norm_1'] - df['gold_ofi_norm_1'].shift(1)
    
    # Quote Imbalance Velocity
    df['quote_imbalance_velocity_5'] = df['gold_quote_imbalance_1'] - df['gold_quote_imbalance_1'].shift(1)
    
    # Price Impact Elasticity Coefficient
    df['price_impact_coef_5'] = df['gold_ret_1'] / (df['gold_ofi_norm_1'] + 1e-8)
    
    # VWAP Deviation
    vwap_20 = (df['close'] * df['volume']).rolling(20).sum() / (df['volume'].rolling(20).sum() + 1e-8)
    df['vwap_dev_20'] = (df['close'] - vwap_20) / (df['rolling_std'] + 1e-8)
    
    # HFT Passive Absorption Features (Absorption of aggressive selling/buying by resting limit orders)
    df['hft_abs_bull'] = np.where((df['gold_signed_flow_norm_1'] < 0) & (df['gold_ofi_norm_1'] > 0), df['gold_ofi_norm_1'] - df['gold_signed_flow_norm_1'], 0.0)
    df['hft_abs_bear'] = np.where((df['gold_signed_flow_norm_1'] > 0) & (df['gold_ofi_norm_1'] < 0), df['gold_signed_flow_norm_1'] - df['gold_ofi_norm_1'], 0.0)
    
    # 6. Target variable: Lead return of Gold over the next lead_horizon bars
    df['target'] = np.log(df['close'].shift(-lead_horizon) / df['close'])
    
    # Clean up NaNs and Infinite values in features
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
        'z_score', 'rsi_14', 'atr_5', 'h_ema_20', 'h_rsi_14',
        'gold_ofi_accel_5', 'quote_imbalance_velocity_5', 'price_impact_coef_5', 'vwap_dev_20',
        'hft_abs_bull', 'hft_abs_bear'
    ]
    
    # Drop rows that have NaN in features (first few rows due to lags/rolling windows)
    # We keep target NaN for now (it will be handled in model training/backtesting)
    df_clean = df.dropna(subset=feature_cols).reset_index(drop=True)
    
    # Replace any infinite values with 0
    for col in feature_cols:
        df_clean[col] = df_clean[col].replace([np.inf, -np.inf], 0.0).fillna(0.0)
        
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    df_clean.to_csv(output_path, index=False)
    print(f"✅ Features constructed! Final dataset saved to {output_path} ({len(df_clean):,} rows, {df_clean.shape[1]} columns)")
    return df_clean, feature_cols

if __name__ == "__main__":
    import sys
    inp = sys.argv[1] if len(sys.argv) > 1 else "processed_data/aligned_dataset.csv"
    out = sys.argv[2] if len(sys.argv) > 2 else "processed_data/features_and_targets.csv"
    build_features_and_targets(inp, out)
