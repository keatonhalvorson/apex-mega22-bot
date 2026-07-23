import os
import json
import time
import urllib.request
import urllib.error
import pandas as pd
import numpy as np
from catboost import CatBoostRegressor
from concurrent.futures import ThreadPoolExecutor, as_completed

def load_env_key():
    env_path = "/home/atheer/Desktop/ApexPredator/download data/.env"
    if not os.path.exists(env_path):
        return None
    with open(env_path, "r") as f:
        for line in f:
            if line.startswith("DEEPSEEK_API_KEY="):
                return line.strip().split("=")[1]
    return None

def run_ultimate_fast_pass_simulation():
    """
    Ultimate Fast-Pass Engine (v3.0):
    Combines Gold Microstructure HFT + Gold/Silver Pair Spread Booster + Fractional Kelly.
    Target: +25% Monthly Return, 60+ Trades, Max Daily DD < 4.0%.
    """
    dataset_path = "processed_data/gold_silver_pairs_dataset.csv"
    if not os.path.exists(dataset_path):
        print("❌ Pairs Dataset missing.")
        return
        
    df = pd.read_csv(dataset_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values('timestamp').reset_index(drop=True)
    
    # Calculate ATR and EMA
    df['h_ema_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['rsi_14'] = 50.0 # Standard default
    
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    df['atr_5'] = ranges.max(axis=1).rolling(5).mean().fillna(2.5)
    
    last_time = df['timestamp'].max()
    start_time = last_time - pd.Timedelta(days=30)
    
    df_sliced = df[df['timestamp'] >= start_time - pd.Timedelta(days=5)].copy().reset_index(drop=True)
    start_bar_indices = df_sliced[df_sliced['timestamp'] >= start_time].index.tolist()
    start_idx = start_bar_indices[0]
    
    test_indices = list(range(start_idx, len(df_sliced) - 15, 1))
    
    print(f"🚀 Running Ultimate Fast-Pass Quant Engine v3.0 over {len(test_indices)} bars...")
    
    start_balance = 10000.0
    current_balance = start_balance
    commission = 0.00002
    
    trades_executed = []
    
    all_timestamps = df_sliced.loc[start_idx:, 'timestamp'].reset_index(drop=True)
    equity_history = pd.DataFrame({'timestamp': all_timestamps})
    equity_history['equity'] = current_balance
    equity_history.set_index('timestamp', inplace=True)
    
    i = 0
    while i < len(test_indices):
        idx = test_indices[i]
        bar = df_sliced.iloc[idx]
        
        close_p = float(bar['close'])
        ema_20 = float(bar['h_ema_20'])
        spread_z = float(bar['spread_zscore'])
        gold_ret1 = float(bar['gold_ret_1'])
        atr = float(bar['atr_5'])
        
        # Signal Generation (Gold Microstructure + Pair Spread Confluence)
        is_bullish_trend = close_p > ema_20
        is_bearish_trend = close_p < ema_20
        
        # Pair Spread Booster: Gold underpriced vs Silver (Z < -0.8) -> Strong BUY
        # Pair Spread Booster: Gold overpriced vs Silver (Z > +0.8) -> Strong SHORT
        pair_buy_boost = spread_z < -0.8
        pair_short_boost = spread_z > 0.8
        
        decision = 'HOLD'
        risk_pct = 0.01 # Base 1%
        
        if is_bullish_trend or pair_buy_boost:
            if gold_ret1 > -0.001:
                decision = 'BUY'
                if pair_buy_boost:
                    risk_pct = 0.018 # Boost risk to 1.8% on Pair Confluence!
        elif is_bearish_trend or pair_short_boost:
            if gold_ret1 < 0.001:
                decision = 'SHORT'
                if pair_short_boost:
                    risk_pct = 0.018 # Boost risk to 1.8% on Pair Confluence!
                    
        if decision in ['BUY', 'SHORT']:
            entry_idx = idx
            entry_time = pd.to_datetime(bar['timestamp'])
            entry_price = close_p
            
            sl_dist = 1.5 * atr
            tp_dist = 3.0 * atr # 1:2 RRR
            
            sl_pct_of_price = sl_dist / entry_price
            cash_risk = current_balance * risk_pct
            position_size_usd = cash_risk / (sl_pct_of_price + 1e-8)
            units = position_size_usd / entry_price
            
            if decision == 'BUY':
                tp_price = entry_price + tp_dist
                sl_price = entry_price - sl_dist
            else:
                tp_price = entry_price - tp_dist
                sl_price = entry_price + sl_dist
                
            outcome = None
            exit_price = None
            exit_idx = entry_idx
            
            for f_idx in range(entry_idx + 1, min(entry_idx + 16, len(df_sliced))):
                f_row = df_sliced.iloc[f_idx]
                f_high = f_row['high']
                f_low = f_row['low']
                
                if decision == 'BUY':
                    if f_low <= sl_price:
                        outcome = 'LOSS'
                        exit_price = sl_price
                        exit_idx = f_idx
                        break
                    elif f_high >= tp_price:
                        outcome = 'WIN'
                        exit_price = tp_price
                        exit_idx = f_idx
                        break
                else:
                    if f_high >= sl_price:
                        outcome = 'LOSS'
                        exit_price = sl_price
                        exit_idx = f_idx
                        break
                    elif f_low <= tp_price:
                        outcome = 'WIN'
                        exit_price = tp_price
                        exit_idx = f_idx
                        break
                        
            if outcome is None:
                outcome = 'TIME_EXIT'
                exit_idx = min(entry_idx + 15, len(df_sliced) - 1)
                exit_price = df_sliced.loc[exit_idx, 'close']
                
            exit_time = pd.to_datetime(df_sliced.loc[exit_idx, 'timestamp'])
            
            spread_cost = (bar['spread'] / entry_price) * position_size_usd
            commission_cost = 2 * commission * position_size_usd
            total_costs = (spread_cost + commission_cost) / 2.0
            
            if decision == 'BUY':
                raw_profit = units * (exit_price - entry_price)
            else:
                raw_profit = units * (entry_price - exit_price)
                
            net_profit_cash = raw_profit - total_costs
            
            old_balance = current_balance
            current_balance += net_profit_cash
            
            for f_idx in range(entry_idx, exit_idx + 1):
                t_bar = pd.to_datetime(df_sliced.loc[f_idx, 'timestamp'])
                t_close = df_sliced.loc[f_idx, 'close']
                if decision == 'BUY':
                    float_profit = units * (t_close - entry_price)
                else:
                    float_profit = units * (entry_price - t_close)
                equity_history.loc[t_bar, 'equity'] = old_balance + float_profit
                
            equity_history.loc[exit_time:, 'equity'] = current_balance
            
            trades_executed.append({
                'entry_time': entry_time.strftime('%Y-%m-%d %H:%M'),
                'exit_time': exit_time.strftime('%Y-%m-%d %H:%M'),
                'type': decision,
                'risk_pct': risk_pct,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'outcome': outcome,
                'cash_profit': net_profit_cash,
                'balance_after': current_balance
            })
            
            while i < len(test_indices) and test_indices[i] <= exit_idx:
                i += 1
        else:
            i += 1
            
    # Calculate Daily Drawdowns
    equity_history['date'] = equity_history.index.date
    daily_groups = equity_history.groupby('date')
    
    daily_stats = []
    prev_day_close_balance = start_balance
    
    for date, group in daily_groups:
        day_open = prev_day_close_balance
        day_low = group['equity'].min()
        day_close = group['equity'].iloc[-1]
        
        daily_dd_from_start = max(0.0, (day_open - day_low) / day_open)
        daily_stats.append({
            'date': date,
            'day_open': day_open,
            'day_close': day_close,
            'daily_dd_from_start': daily_dd_from_start
        })
        prev_day_close_balance = day_close
        
    daily_df = pd.DataFrame(daily_stats)
    
    equity_history['peak'] = equity_history['equity'].cummax()
    equity_history['drawdown'] = (equity_history['peak'] - equity_history['equity']) / equity_history['peak']
    max_total_dd = equity_history['drawdown'].max()
    
    print("\n=======================================================")
    print("   ULTIMATE FAST-PASS QUANT ENGINE v3.0 SUMMARY (June)")
    print("=======================================================")
    print(f" Starting Balance       : ${start_balance:,.2f}")
    print(f" Final Balance          : ${current_balance:,.2f}")
    print(f" Net Profit/Loss ($)    : ${current_balance - start_balance:+,.2f} ({((current_balance - start_balance)/start_balance):+.2%})")
    print(f" Total Trades Executed  : {len(trades_executed)}")
    print(f" Max Daily Drawdown     : {daily_df['daily_dd_from_start'].max():.2%} (Prop Firm Limit: 5.0%)")
    print(f" Max Total Drawdown     : {max_total_dd:.2%} (Prop Firm Limit: 10.0%)")
    
    if trades_executed:
        wins = [t for t in trades_executed if t['outcome'] == 'WIN']
        win_rate = len(wins) / len(trades_executed)
        print(f" Win Rate               : {win_rate:.2%}")
        print("\nExecuted Trades Ledger (Sample):")
        for idx, t in enumerate(trades_executed[:10]):
            print(f" #{idx+1}: {t['type']} | Risk: {t['risk_pct']:.1%} | Outcome: {t['outcome']} | PnL: ${t['cash_profit']:+,.2f}")
    print("=======================================================\n")

if __name__ == '__main__':
    run_ultimate_fast_pass_simulation()
