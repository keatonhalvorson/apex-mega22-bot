import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge
from sklearn.ensemble import RandomForestRegressor

def train_and_backtest(features_path, output_plot_path, lead_horizon=5):
    """
    Performs walk-forward validation on Ridge Regression and Random Forest models.
    Backtests predictions under realistic transaction cost assumptions.
    Generates performance metrics and plots cumulative returns.
    """
    print("⏳ Loading features and targets...")
    df = pd.read_csv(features_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    # Feature columns (exclude meta columns)
    exclude_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume', 'dollar_value', 
                    'signed_flow', 'ofi_dollar', 'quote_imbalance', 'realized_vol', 'spread', 
                    'num_ticks', 'dxy_price', 'bond_price', 'vix_price', 'target']
    feature_cols = [col for col in df.columns if col not in exclude_cols]
    
    print(f"   Features ({len(feature_cols)}): {feature_cols}")
    
    # Setup Walk-Forward splits
    # We will use a rolling window of 6 months for training, and 1 month for testing
    # Since bars aren't perfectly uniform, we'll split by indexes
    total_len = len(df)
    train_size = int(total_len * 0.5)  # 50% for initial train
    test_step = int(total_len * 0.08)  # ~1 month step
    
    print(f"   Total rows: {total_len:,}")
    print(f"   Initial train size: {train_size:,} bars")
    print(f"   Test step size: {test_step:,} bars")
    
    # Placeholders for out-of-sample predictions
    df['pred_ridge'] = np.nan
    df['pred_rf'] = np.nan
    
    test_indices = []
    
    # Run Walk-Forward Splits
    idx = train_size
    fold = 1
    
    while idx + lead_horizon < total_len:
        start_train = max(0, idx - train_size)
        end_train = idx
        start_test = idx
        end_test = min(total_len - lead_horizon, idx + test_step)
        
        train_slice = df.iloc[start_train:end_train].dropna(subset=['target'])
        test_slice = df.iloc[start_test:end_test]
        
        if len(test_slice) == 0:
            break
            
        print(f"   👉 Fold {fold}: Train [{start_train}:{end_train}], Test [{start_test}:{end_test}]")
        
        X_train = train_slice[feature_cols].values
        y_train = train_slice['target'].values
        X_test = test_slice[feature_cols].values
        
        # Scale features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Model 1: Ridge Regression
        model_ridge = Ridge(alpha=100.0)
        model_ridge.fit(X_train_scaled, y_train)
        preds_ridge = model_ridge.predict(X_test_scaled)
        df.loc[start_test:end_test-1, 'pred_ridge'] = preds_ridge
        
        # Model 2: Random Forest
        model_rf = RandomForestRegressor(n_estimators=100, max_depth=5, random_state=42, n_jobs=-1)
        model_rf.fit(X_train_scaled, y_train)
        preds_rf = model_rf.predict(X_test_scaled)
        df.loc[start_test:end_test-1, 'pred_rf'] = preds_rf
        
        test_indices.extend(list(range(start_test, end_test)))
        idx += test_step
        fold += 1
        
    # Drop rows where we have no predictions (the training period)
    oos_df = df.iloc[test_indices].copy().reset_index(drop=True)
    print(f"   Out-of-sample period generated: {len(oos_df):,} bars")
    
    # Backtest logic with Transaction Costs
    # We define transaction costs per trade as:
    # cost = (spread_entry / close_entry + spread_exit / close_exit) / 2 + commission
    # Let's set commission = 0.00002 (0.2 bps) per side (0.4 bps round trip)
    commission = 0.00002
    
    # Let's run backtests for both models and find their performance
    for model_name, pred_col in [('Ridge', 'pred_ridge'), ('RF', 'pred_rf')]:
        # To avoid over-trading, we trade only when predicted return exceeds a threshold
        # We define threshold as the 80th percentile of absolute predictions to capture high-conviction moves
        abs_preds = oos_df[pred_col].abs().dropna()
        if len(abs_preds) == 0:
            continue
        signal_threshold = np.percentile(abs_preds, 85)
        print(f"   [{model_name}] Optimal signal threshold (85th pct): {signal_threshold:.6f}")
        
        # We simulate positions
        # For simplicity and to avoid multi-position complexity, we check if the model signals:
        # Long: prediction > signal_threshold
        # Short: prediction < -signal_threshold
        # Hold: 5 bars
        # Since target is log(close_{t+5} / close_t), a signal at t gives a gross return of target_t
        # If we enter a trade at t, we exit at t+5
        
        gross_returns = []
        net_returns = []
        timestamps = []
        prices = []
        trade_signals = []
        
        # Track overlapping trades or non-overlapping trades.
        # To make it realistic and simple, we run non-overlapping trades:
        # If we enter a trade at t, we hold for 5 bars and cannot enter another trade until it closes at t+5.
        i = 0
        total_trades = 0
        winning_trades = 0
        
        while i < len(oos_df):
            pred = oos_df.loc[i, pred_col]
            close_price = oos_df.loc[i, 'close']
            spread_entry = oos_df.loc[i, 'spread']
            
            signal = 0
            if pred > signal_threshold:
                signal = 1
            elif pred < -signal_threshold:
                signal = -1
                
            if signal != 0:
                # We have a trade! Hold for lead_horizon bars or end of series
                exit_idx = min(i + lead_horizon, len(oos_df) - 1)
                exit_price = oos_df.loc[exit_idx, 'close']
                spread_exit = oos_df.loc[exit_idx, 'spread']
                
                # Gross return
                raw_ret = np.log(exit_price / close_price) if signal == 1 else np.log(close_price / exit_price)
                
                # Transaction cost
                cost = (spread_entry / close_price + spread_exit / exit_price) / 2.0 + 2 * commission
                net_ret = raw_ret - cost
                
                gross_returns.append(raw_ret)
                net_returns.append(net_ret)
                timestamps.append(oos_df.loc[i, 'timestamp'])
                prices.append(close_price)
                trade_signals.append(signal)
                
                total_trades += 1
                if net_ret > 0:
                    winning_trades += 1
                    
                # Fast forward past this trade
                i = exit_idx
            else:
                i += 1
                
        # Calculate performance metrics
        gross_returns = np.array(gross_returns)
        net_returns = np.array(net_returns)
        
        if total_trades > 0:
            cum_net = np.cumsum(net_returns)
            cum_gross = np.cumsum(gross_returns)
            win_rate = winning_trades / total_trades
            
            # Annualization
            # Average bars per day
            total_days = (oos_df['timestamp'].iloc[-1] - oos_df['timestamp'].iloc[0]).days
            if total_days == 0:
                total_days = 1
            avg_bars_per_day = len(oos_df) / total_days
            # Annualization factor for trades:
            # Let's annualize based on trade frequency
            trades_per_day = total_trades / total_days
            ann_factor = np.sqrt(trades_per_day * 260)
            
            mean_ret = np.mean(net_returns)
            std_ret = np.std(net_returns) if len(net_returns) > 1 else 1.0
            sharpe = (mean_ret / std_ret) * ann_factor if std_ret > 0 else 0.0
            
            # Sortino
            neg_returns = net_returns[net_returns < 0]
            downside_std = np.std(neg_returns) if len(neg_returns) > 1 else 1.0
            sortino = (mean_ret / downside_std) * ann_factor if downside_std > 0 else 0.0
            
            # Max Drawdown
            peaks = np.maximum.accumulate(cum_net)
            drawdowns = cum_net - peaks
            max_dd = np.min(drawdowns) if len(drawdowns) > 0 else 0.0
            
            # Profit Factor
            gross_profits = np.sum(net_returns[net_returns > 0])
            gross_losses = np.abs(np.sum(net_returns[net_returns < 0]))
            profit_factor = gross_profits / gross_losses if gross_losses > 0 else np.inf
            
            print(f"\n📈 --- {model_name} Backtest Results ---")
            print(f"   Total Trades      : {total_trades}")
            print(f"   Win Rate          : {win_rate:.2%}")
            print(f"   Cumulative Net Ret: {cum_net[-1]:.2%}")
            print(f"   Annualized Sharpe : {sharpe:.2f}")
            print(f"   Annualized Sortino: {sortino:.2f}")
            print(f"   Maximum Drawdown  : {max_dd:.2%}")
            print(f"   Profit Factor     : {profit_factor:.2f}")
            
            # Store results on oos_df for plotting
            # We want to map trade returns back to a chronological series
            # Create a trade return column
            trade_ret_series = np.zeros(len(oos_df))
            current_trade_idx = 0
            i = 0
            while i < len(oos_df):
                if current_trade_idx < len(timestamps) and oos_df.loc[i, 'timestamp'] == timestamps[current_trade_idx]:
                    exit_idx = min(i + lead_horizon, len(oos_df) - 1)
                    # Distribute net return evenly across holding bars (or put it all at exit)
                    trade_ret_series[exit_idx] = net_returns[current_trade_idx]
                    current_trade_idx += 1
                    i = exit_idx
                else:
                    i += 1
            oos_df[f'{model_name}_trade_net_ret'] = trade_ret_series
        else:
            print(f"   ❌ {model_name} did not generate any trades.")
            oos_df[f'{model_name}_trade_net_ret'] = 0.0
            
    # Calculate Gold Benchmark (Buy and Hold Gold)
    oos_df['gold_bh_ret'] = np.log(oos_df['close'] / oos_df['close'].iloc[0])
    
    # Cumulative net returns of strategies
    oos_df['Ridge_cum'] = oos_df['Ridge_trade_net_ret'].cumsum()
    oos_df['RF_cum'] = oos_df['RF_trade_net_ret'].cumsum()
    
    # Save OOS dataset for record
    oos_df.to_csv("processed_data/oos_predictions_and_returns.csv", index=False)
    print("   ✓ Saved out-of-sample predictions to processed_data/oos_predictions_and_returns.csv")
    
    # Plotting
    plt.figure(figsize=(12, 8))
    
    # Subplot 1: Cumulative Returns
    plt.subplot(2, 1, 1)
    plt.plot(oos_df['timestamp'], oos_df['gold_bh_ret'] * 100, label='Gold Buy & Hold (Benchmark)', color='gold', alpha=0.8, linewidth=1.5)
    plt.plot(oos_df['timestamp'], oos_df['Ridge_cum'] * 100, label='Ridge Microstructure+Macro Net Return', color='royalblue', linewidth=2.0)
    plt.plot(oos_df['timestamp'], oos_df['RF_cum'] * 100, label='RandomForest Microstructure+Macro Net Return', color='crimson', linewidth=2.0)
    plt.title('Out-of-Sample Performance Comparison (Net of Transaction Costs)', fontsize=14, fontweight='bold')
    plt.ylabel('Cumulative Return (%)', fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(fontsize=10)
    
    # Subplot 2: Drawdowns
    plt.subplot(2, 1, 2)
    # Ridge Drawdown
    ridge_peaks = np.maximum.accumulate(oos_df['Ridge_cum'])
    ridge_dd = (oos_df['Ridge_cum'] - ridge_peaks) * 100
    # RF Drawdown
    rf_peaks = np.maximum.accumulate(oos_df['RF_cum'])
    rf_dd = (oos_df['RF_cum'] - rf_peaks) * 100
    
    plt.fill_between(oos_df['timestamp'], ridge_dd, 0, label='Ridge Drawdown', color='royalblue', alpha=0.3)
    plt.fill_between(oos_df['timestamp'], rf_dd, 0, label='Random Forest Drawdown', color='crimson', alpha=0.3)
    plt.ylabel('Drawdown (%)', fontsize=12)
    plt.xlabel('Date', fontsize=12)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.legend(fontsize=10)
    
    plt.tight_layout()
    plt.savefig(output_plot_path, dpi=300)
    plt.close()
    print(f"✅ Performance plot saved to {output_plot_path}")
    
    return oos_df

if __name__ == "__main__":
    import sys
    feats = sys.argv[1] if len(sys.argv) > 1 else "processed_data/features_and_targets.csv"
    plot = sys.argv[2] if len(sys.argv) > 2 else "processed_data/backtest_results.png"
    train_and_backtest(feats, plot)
