"""
Automated Verification & Parity Test Suite for Mega-22 Strategy
Verifies 100% mathematical and execution parity between Mega22StrategyEngine
and the historical backtest engine (simulate_engine_rigorous / comprehensive_audit.py).
"""

import sys
import os
from pathlib import Path
import pytest
import numpy as np
import pandas as pd

# Add engine directory to path
ENGINE_DIR = Path(__file__).resolve().parent

if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from mega22_constants import (
    MEGA_22, GOLDEN_11, TITAN_11, APEX_ADDITIONS, APEX_30, ACTIVE_UNIVERSE,
    MACRO_SYMBOL, ALL_SYMBOLS, INITIAL_CAPITAL,
    MAX_SLOTS, SLOT_FRACTION, FEE_RATE, SLIPPAGE_RATE,
    STOP_LOSS_TARGET, TAKE_PROFIT_TARGET, PARABOLIC_LOCK_TIERS,
    COOLDOWN_STOP_LOSS_BARS, CONSECUTIVE_STOPS_TRIGGER, COOLDOWN_GLOBAL_GUARD_BARS
)
from mega22_strategy import Mega22StrategyEngine, Position, TradeRecord
from apex_hybrid_master_engine import ApexSovereignMasterEngine

def test_mega_22_universe_composition():
    """Verify that Mega-22 is precisely Golden-11 ∪ Titan-11 with 22 distinct symbols."""
    assert len(GOLDEN_11) == 11
    assert len(TITAN_11) == 11
    assert len(MEGA_22) == 22
    assert set(MEGA_22) == set(GOLDEN_11).union(set(TITAN_11))
    assert 'BTCUSDT' not in MEGA_22
    assert MACRO_SYMBOL == 'BTCUSDT'

def test_apex_30_universe_composition():
    """Verify that Sovereign Apex-30 properly encompasses Mega-22 and the 8 high-alpha champion altcoins (100% Halal Spot)."""
    assert len(APEX_30) == 30
    assert set(MEGA_22).issubset(set(APEX_30))
    assert len(APEX_ADDITIONS) == 8
    assert len(set(APEX_30)) == 30
    assert 'BTCUSDT' not in APEX_30
    assert ACTIVE_UNIVERSE == APEX_30
    assert ALL_SYMBOLS == [MACRO_SYMBOL] + ACTIVE_UNIVERSE
    assert len(ALL_SYMBOLS) == 31

    # Verify complete exclusion of doubtful / non-halal coins
    doubtful_5 = {'ENAUSDT', 'PENDLEUSDT', 'CRVUSDT', 'JUPUSDT', 'INJUSDT'}
    assert not any(c in APEX_30 for c in doubtful_5), f"Found doubtful coins in APEX_30: {doubtful_5.intersection(set(APEX_30))}"
    assert not any(c in MEGA_22 for c in doubtful_5), f"Found doubtful coins in MEGA_22: {doubtful_5.intersection(set(MEGA_22))}"

    # Verify inclusion of all 25 confirmed Halal baseline coins
    confirmed_25 = [
        'ORDIUSDT', 'ICPUSDT', 'GALAUSDT', 'NEARUSDT', 'TIAUSDT',
        'RENDERUSDT', 'ALGOUSDT', 'XLMUSDT', 'DOGEUSDT', 'TRXUSDT',
        'BONKUSDT', 'POLUSDT', 'HBARUSDT', 'FILUSDT', 'APTUSDT',
        'XRPUSDT', 'ENSUSDT', 'FETUSDT', 'VETUSDT', 'AVAXUSDT',
        'SEIUSDT', 'OPUSDT', 'DOTUSDT', 'ETHUSDT', 'UNIUSDT'
    ]
    for c in confirmed_25:
        assert c in APEX_30, f"Confirmed Halal coin {c} missing from APEX_30!"

    # Verify inclusion of the 5 optimal Halal replacement coins
    replacements_5 = {'ADAUSDT', 'LINKUSDT', 'LTCUSDT', 'ATOMUSDT', 'SOLUSDT'}
    for c in replacements_5:
        assert c in APEX_30, f"Replacement Halal coin {c} missing from APEX_30!"

    assert set(APEX_30) == set(confirmed_25).union(replacements_5)

def test_btc_hawkes_exact_math_parity():
    """Test that Hawkes Self-Exciting Cascade Shield math is identical to the baseline engine."""
    np.random.seed(42)
    n = 300
    prices = 60000.0 * np.cumprod(1.0 + np.random.normal(0, 0.003, n))
    times = pd.date_range('2026-01-01', periods=n, freq='5min')
    df_btc = pd.DataFrame({'open_time': times, 'btc_c': prices})
    
    df_base = ApexSovereignMasterEngine.compute_btc_hawkes(df_btc.copy())
    df_mega = Mega22StrategyEngine.compute_btc_hawkes(df_btc.copy())
    
    np.testing.assert_allclose(
        df_base['btc_hawkes'].values,
        df_mega['btc_hawkes'].values,
        rtol=1e-12,
        atol=1e-12,
        err_msg="BTC Hawkes intensity differs between engines!"
    )

def test_indicator_calculation_parity():
    """Test full indicator calculations across synthetic 5m candles."""
    np.random.seed(123)
    n = 200
    times = pd.date_range('2026-01-01', periods=n, freq='5min')
    
    btc_c = 65000.0 * np.cumprod(1.0 + np.random.normal(0, 0.002, n))
    df_btc = pd.DataFrame({
        'open_time': times,
        'btc_c': btc_c,
        'btc_24h': np.random.normal(1.0, 0.5, n),
        'btc_4h': np.random.normal(0.5, 0.2, n),
    })
    df_btc = Mega22StrategyEngine.compute_btc_hawkes(df_btc)
    
    c = 10.0 * np.cumprod(1.0 + np.random.normal(0, 0.005, n))
    h = c * (1.0 + np.abs(np.random.normal(0, 0.003, n)))
    l = c * (1.0 - np.abs(np.random.normal(0, 0.003, n)))
    o = (h + l) / 2.0
    v = np.random.uniform(10000, 50000, n)
    tb = v * np.random.uniform(0.4, 0.6, n)
    
    ts = np.maximum(v - tb, 1e-6)
    tbv_ratio = tb / np.maximum(v, 1e-6)
    
    df_alt = pd.DataFrame({
        'open_time': times,
        'open': o, 'high': h, 'low': l, 'close': c,
        'volume': v, 'taker_buy': tb, 'taker_sell': ts,
        'taker_buy_base': tb, 'tbv_ratio': tbv_ratio
    })
    
    ind_base = ApexSovereignMasterEngine.calculate_multifractal_fisher_indicators(df_alt.copy(), df_btc.copy())
    ind_mega = Mega22StrategyEngine.calculate_indicators(df_alt.copy(), df_btc.copy())
    
    check_cols = [
        'bb_mid', 'bb_lower', 'ema_slow', 'motif_distance',
        'multifractal_spectrum_width', 'fisher_z', 'ko_z', 'wick_ratio',
        'ofi', 'te_proxy', 'is_candidate', 'explosion_alpha_score', 'exit_long'
    ]
    assert 'is_btc_safe' in ind_mega.columns
    for col in check_cols:
        assert col in ind_mega.columns, f"Missing column {col} in mega engine indicators"
        np.testing.assert_allclose(
            ind_base[col].values,
            ind_mega[col].values,
            rtol=1e-8,
            atol=1e-8,
            err_msg=f"Discrepancy in indicator column {col}"
        )

def test_stop_loss_trigger_and_price():
    """Test initial stop loss (-2.2%) trigger and exact exit price."""
    pos = Position(
        sym='NEARUSDT', px=10.0, notional=320.0, entry_fee=0.128,
        i=100, entry_time='2026-01-01T00:00:00Z', stop=0.022
    )
    # Price dips to -2.3% low
    event, updated_pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=9.80, h=10.05, l=9.77, exit_sig=0, held=5
    )
    assert event is not None
    exit_px, reason = event
    assert reason == 'STOP_LOSS'
    # Exact exit price: px * (1.0 - 0.022) = 10.0 * 0.978 = 9.78
    assert pytest.approx(exit_px, rel=1e-9) == 9.78

def test_take_profit_trigger_and_price():
    """Test Take Profit (+6.5%) trigger and exact exit price."""
    pos = Position(
        sym='ORDIUSDT', px=50.0, notional=320.0, entry_fee=0.128,
        i=100, entry_time='2026-01-01T00:00:00Z', stop=0.022
    )
    # High reaches +6.6%
    event, updated_pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=52.0, h=53.30, l=49.90, exit_sig=0, held=10
    )
    assert event is not None
    exit_px, reason = event
    assert reason == 'TAKE_PROFIT'
    # Exact exit price: px * (1.0 + 0.065) = 50.0 * 1.065 = 53.25
    assert pytest.approx(exit_px, rel=1e-9) == 53.25

def test_parabolic_profit_lock_tiers():
    """Test all 4 tiers of the dynamic parabolic profit lock mechanism."""
    # Tier 1: best_pnl >= 1.6% -> stop = -0.005 (+0.5% locked)
    pos = Position(
        sym='TIAUSDT', px=10.0, notional=320.0, entry_fee=0.128,
        i=100, entry_time='2026-01-01T00:00:00Z', stop=0.022
    )
    event, pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=10.15, h=10.17, l=10.02, exit_sig=0, held=3
    )
    assert event is None
    assert pos.stop == -0.005

    # Tier 2: best_pnl >= 3.0% -> stop = -0.018 (+1.8% locked)
    event, pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=10.28, h=10.31, l=10.14, exit_sig=0, held=6
    )
    assert event is None
    assert pos.stop == -0.018

    # Tier 3: best_pnl >= 4.8% -> stop = -0.035 (+3.5% locked)
    event, pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=10.45, h=10.49, l=10.25, exit_sig=0, held=9
    )
    assert event is None
    assert pos.stop == -0.035

    # Subsequent pullback hitting locked profit stop
    event, pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=9.90, h=10.40, l=9.60, exit_sig=0, held=12
    )
    assert event is not None
    exit_px, reason = event
    assert reason == 'TRAILING_LOCK'
    # Exit price = px * (1.0 + abs(-0.035)) = 10.0 * 1.035 = 10.35 (+3.5%)
    assert pytest.approx(exit_px, rel=1e-9) == 10.35

def test_trailing_ratchet_activation_and_trailing():
    """Test asymmetric trailing ratchet activation at BB mid touch with profit >= 0.8%."""
    pos = Position(
        sym='ADAUSDT', px=1.0, notional=320.0, entry_fee=0.128,
        i=50, entry_time='2026-01-01T00:00:00Z', stop=0.022
    )
    # Price reaches +1.0% with exit_sig == 1 (close > bb_mid)
    event, pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=1.010, h=1.012, l=1.002, exit_sig=1, held=8
    )
    assert event is None
    assert pos.trailing_active is True
    assert pos.stop == -0.008

    # Price extends higher to 1.04 (+4%), trailing stop tightens by 1.2% offset: 4% - 1.2% = 2.8%
    event, pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=1.035, h=1.040, l=1.015, exit_sig=0, held=10
    )
    assert event is None
    expected_trail = (1.04 - 1.0) / 1.0 - 0.012  # 0.028
    assert pytest.approx(pos.stop, rel=1e-9) == -expected_trail

def test_stall_exit():
    """Test 60-bar stall exit when stagnant and dipping below -1.0%."""
    pos = Position(
        sym='RENDERUSDT', px=5.0, notional=320.0, entry_fee=0.128,
        i=10, entry_time='2026-01-01T00:00:00Z', stop=0.022
    )
    # Held 60 bars, PnL < +0.1%, worst PnL < -1.0% (e.g. low = 4.94 -> -1.2%)
    event, pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=4.99, h=5.02, l=4.94, exit_sig=0, held=60
    )
    assert event is not None
    exit_px, reason = event
    assert reason == 'STALL_EXIT'
    assert pytest.approx(exit_px, rel=1e-9) == 4.99 * (1.0 - 0.0002)

def simulate_mega22_standalone(symbols_universe, initial_capital=1000.0, max_slots=3, slot_frac=0.32):
    """
    Executes historical replay directly using Mega22StrategyEngine:
    - Mega22StrategyEngine.compute_btc_hawkes
    - Mega22StrategyEngine.calculate_indicators
    - Mega22StrategyEngine.evaluate_position_step
    """
    d_dir = Path('/home/atheer/Desktop/Apex_Autonomous_Agent/apex_v2/data/full_year_2024')
    p_btc = d_dir / 'BTCUSDT_2024-02.pkl'
    df_btc = pd.read_pickle(p_btc)
    df_btc_5m = ApexSovereignMasterEngine.resample_5m(df_btc)[['open_time', 'close']].rename(columns={'close': 'btc_c'})
    df_btc_5m['btc_24h'] = (df_btc_5m['btc_c'] / df_btc_5m['btc_c'].shift(288) - 1.0) * 100.0
    df_btc_5m['btc_4h'] = (df_btc_5m['btc_c'] / df_btc_5m['btc_c'].shift(48) - 1.0) * 100.0
    df_btc_5m = Mega22StrategyEngine.compute_btc_hawkes(df_btc_5m)
    
    coin_dfs = {}
    for sym in symbols_universe:
        p = d_dir / f'{sym}_2024-02.pkl'
        if p.exists():
            df_1m = pd.read_pickle(p)
            df_5m = ApexSovereignMasterEngine.resample_5m(df_1m)
            df_ind = Mega22StrategyEngine.calculate_indicators(df_5m, df_btc_5m)
            coin_dfs[sym] = df_ind
            
    n_bars = min(len(df) for df in coin_dfs.values())
    symbols = list(coin_dfs.keys())
    active_positions: Dict[str, Position] = {}
    inst_cap = initial_capital
    stoploss_guard_until = -1
    consecutive_stops = 0
    cooldowns = {s: -1 for s in symbols}
    trades = []
    
    for i in range(150, n_bars):
        to_close = []
        for sym, pos in list(active_positions.items()):
            df_s = coin_dfs[sym]
            c = df_s['close'].values[i]
            l = df_s['low'].values[i]
            h = df_s['high'].values[i]
            exit_sig = df_s['exit_long'].values[i]
            held = i - pos.i
            
            event, updated_pos = Mega22StrategyEngine.evaluate_position_step(
                pos=pos, c=c, h=h, l=l, exit_sig=exit_sig, held=held, strict_parity=True
            )
            active_positions[sym] = updated_pos
            
            if event is not None:
                exit_px, reason = event
                gross = (exit_px - pos.px) / pos.px * pos.notional
                exit_fee = pos.notional * FEE_RATE
                entry_fee = pos.entry_fee
                net = gross - exit_fee - entry_fee
                inst_cap += (pos.notional + gross - exit_fee)
                
                trades.append({
                    'sym': sym, 'entry_i': pos.i, 'exit_i': i,
                    'entry_px': pos.px, 'exit_px': exit_px,
                    'gross': gross, 'net': net, 'entry_fee': entry_fee, 'exit_fee': exit_fee,
                    'reason': reason, 'cap_after': inst_cap
                })
                to_close.append(sym)
                if 'STOP_LOSS' in reason:
                    consecutive_stops += 1
                    cooldowns[sym] = i + COOLDOWN_STOP_LOSS_BARS
                    if consecutive_stops >= CONSECUTIVE_STOPS_TRIGGER:
                        stoploss_guard_until = i + COOLDOWN_GLOBAL_GUARD_BARS
                else:
                    consecutive_stops = 0
                    
        for sym in to_close:
            del active_positions[sym]
            
        if len(active_positions) < max_slots and i > stoploss_guard_until:
            avail = max_slots - len(active_positions)
            cands = []
            for sym in symbols:
                if sym not in active_positions and i > cooldowns[sym]:
                    if coin_dfs[sym]['is_candidate'].values[i - 1] == 1:
                        score = coin_dfs[sym]['explosion_alpha_score'].values[i - 1]
                        cands.append((sym, score))
            cands.sort(key=lambda x: x[1], reverse=True)
            for sym, _ in cands[:avail]:
                df_s = coin_dfs[sym]
                o = df_s['open'].values[i]
                target_notional = inst_cap * slot_frac
                if inst_cap >= target_notional and target_notional > 50.0:
                    epx = o * (1.0 + SLIPPAGE_RATE)
                    ef = target_notional * FEE_RATE
                    inst_cap -= (target_notional + ef)
                    active_positions[sym] = Position(
                        sym=sym, px=epx, notional=target_notional, entry_fee=ef,
                        i=i, entry_time=str(df_s['open_time'].values[i]), stop=STOP_LOSS_TARGET
                    )
                    
    # Month end close
    for sym, pos in list(active_positions.items()):
        df_s = coin_dfs[sym]
        c = df_s['close'].values[-1]
        gross = (c - pos.px) / pos.px * pos.notional
        exit_fee = pos.notional * FEE_RATE
        entry_fee = pos.entry_fee
        net = gross - exit_fee - entry_fee
        inst_cap += (pos.notional + gross - exit_fee)
        trades.append({
            'sym': sym, 'entry_i': pos.i, 'exit_i': n_bars - 1,
            'entry_px': pos.px, 'exit_px': c, 'gross': gross, 'net': net,
            'entry_fee': entry_fee, 'exit_fee': exit_fee,
            'reason': 'MONTH_END', 'cap_after': inst_cap
        })
        
    df_trades = pd.DataFrame(trades)
    return {
        'trades': len(df_trades),
        'cap': inst_cap,
        'net': inst_cap - initial_capital,
        'df_trades': df_trades
    }

def test_historical_replay_2024_02_parity():
    """
    Direct historical replay parity test on 2024-02 data.
    Runs BOTH comprehensive_audit baseline AND standalone Mega22StrategyEngine simulation,
    verifying 100% exact parity trade-by-trade across all 36 trades and ending capital.
    """
    try:
        from comprehensive_audit import simulate_engine_rigorous
        import comprehensive_audit
    except ImportError:
        pytest.skip("comprehensive_audit not importable")
        
    p_btc = Path('/home/atheer/Desktop/Apex_Autonomous_Agent/apex_v2/data/full_year_2024/BTCUSDT_2024-02.pkl')
    if not p_btc.exists():
        pytest.skip("Historical 2024-02 data not found")
        
    comprehensive_audit.months = [(2024, '2024-02')]
    res_audit = simulate_engine_rigorous(MEGA_22, initial_capital=1000.0, max_slots=3, slot_frac=0.32, name="Audit Replay", correct_fees=True)
    res_mega = simulate_mega22_standalone(MEGA_22, initial_capital=1000.0, max_slots=3, slot_frac=0.32)
    
    assert res_mega['trades'] == res_audit['trades'], f"Trade count mismatch: Mega={res_mega['trades']}, Audit={res_audit['trades']}"
    assert res_mega['trades'] == 36, f"Expected exactly 36 trades in 2024-02, got {res_mega['trades']}"
    assert pytest.approx(res_mega['cap'], rel=1e-8) == res_audit['cap'], "Ending capital differs between engines!"
    assert pytest.approx(res_mega['net'], rel=1e-8) == res_audit['net'], "Net profit differs between engines!"
    
    df_audit = res_audit['df_trades']
    df_mega = res_mega['df_trades']
    
    for idx in range(len(df_audit)):
        t_a = df_audit.iloc[idx]
        t_m = df_mega.iloc[idx]
        assert t_m['sym'] == t_a['sym'], f"Trade {idx} symbol mismatch"
        assert t_m['reason'] == t_a['reason'], f"Trade {idx} exit reason mismatch for {t_m['sym']}"
        assert pytest.approx(t_m['entry_px'], rel=1e-6) == t_a['entry_px'], f"Trade {idx} entry px mismatch"
        assert pytest.approx(t_m['exit_px'], rel=1e-6) == t_a['exit_px'], f"Trade {idx} exit px mismatch"
        assert pytest.approx(t_m['net'], rel=1e-6) == t_a['net'], f"Trade {idx} net PnL mismatch"

def test_apex_30_historical_replay_2024_02_parity():
    """
    Direct historical replay parity test for Apex-30 Sovereign Champion universe on 2024-02 data.
    Validates exact parity with backtest audit: exactly 44 trades and $1,202.73 ending capital.
    """
    p_btc = Path('/home/atheer/Desktop/Apex_Autonomous_Agent/apex_v2/data/full_year_2024/BTCUSDT_2024-02.pkl')
    if not p_btc.exists():
        pytest.skip("Historical 2024-02 data not found")
        
    res_apex = simulate_mega22_standalone(APEX_30, initial_capital=1000.0, max_slots=3, slot_frac=0.32)
    assert res_apex['trades'] == 44, f"Expected exactly 44 trades in 2024-02 for Apex-30, got {res_apex['trades']}"
    assert pytest.approx(res_apex['cap'], rel=1e-5) == 1202.72648, "Ending capital differs for Apex-30 2024-02 replay!"
    assert pytest.approx(res_apex['net'], rel=1e-5) == 202.72648, "Net profit differs for Apex-30 2024-02 replay!"

def test_cooldown_mechanics(tmp_path):
    """Verify coin-specific and global consecutive stop loss cooldown mechanics using Mega22PaperBot."""
    from mega22_paper_bot import Mega22PaperBot
    journal = tmp_path / "test_cooldown.json"
    bot = Mega22PaperBot(journal_path=journal)
    bot.bar_index = 100
    
    # 1. Single Stop Loss on ORDIUSDT at bar 100
    pos_ordi = Position(
        sym='ORDIUSDT', px=50.0, notional=320.0, entry_fee=0.128,
        i=95, entry_time='2026-01-01T00:00:00Z', stop=0.022
    )
    bot.active_positions['ORDIUSDT'] = pos_ordi
    bot._execute_position_close('ORDIUSDT', exit_px=48.90, reason='STOP_LOSS')
    
    assert bot.cooldowns['ORDIUSDT'] == 100 + COOLDOWN_STOP_LOSS_BARS  # 124
    assert bot.consecutive_stops == 1
    assert bot.stoploss_guard_until == -1
    
    # 2. Second Stop Loss on SOLUSDT at bar 105 -> triggers global guard
    bot.bar_index = 105
    pos_sol = Position(
        sym='SOLUSDT', px=100.0, notional=200.0, entry_fee=0.08,
        i=101, entry_time='2026-01-01T00:00:00Z', stop=0.022
    )
    bot.active_positions['SOLUSDT'] = pos_sol
    bot._execute_position_close('SOLUSDT', exit_px=97.8, reason='STOP_LOSS')
    
    assert bot.cooldowns['SOLUSDT'] == 105 + COOLDOWN_STOP_LOSS_BARS  # 129
    assert bot.consecutive_stops == 2
    assert bot.stoploss_guard_until == 105 + COOLDOWN_GLOBAL_GUARD_BARS  # 153
    
    # 3. Entries are blocked during global guard
    bot.bar_index = 110
    bot.latest_indicators['NEARUSDT'] = {'is_cand': 1, 'score': 95.0, 'price': 5.0}
    bot._evaluate_portfolio_entries()
    assert 'NEARUSDT' not in bot.active_positions, "Entry should be blocked while global guard is active!"
    
    # 4. Profitable trade at bar 160 resets consecutive stops
    bot.bar_index = 160
    pos_near = Position(
        sym='NEARUSDT', px=5.0, notional=200.0, entry_fee=0.08,
        i=155, entry_time='2026-01-01T00:00:00Z', stop=0.022
    )
    bot.active_positions['NEARUSDT'] = pos_near
    bot._execute_position_close('NEARUSDT', exit_px=5.325, reason='TAKE_PROFIT')
    assert bot.consecutive_stops == 0

def test_accounting_fee_math(tmp_path):
    """Verify spot 1x cash accounting, fee deduction, and capital conservation through Mega22PaperBot."""
    from mega22_paper_bot import Mega22PaperBot
    journal = tmp_path / "test_accounting.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    initial_cap = 1000.0
    bot.available_cash = initial_cap
    assert bot.get_total_equity() == initial_cap
    
    # Entry into ORDIUSDT
    raw_px = 50.0
    bot.latest_indicators['ORDIUSDT'] = {'is_cand': 1, 'score': 80.0, 'price': raw_px}
    bot._evaluate_portfolio_entries()
    
    assert 'ORDIUSDT' in bot.active_positions
    pos = bot.active_positions['ORDIUSDT']
    expected_notional = initial_cap * SLOT_FRACTION  # 320.0
    expected_entry_fee = expected_notional * FEE_RATE  # 0.128
    assert pytest.approx(pos.notional, rel=1e-9) == expected_notional
    assert pytest.approx(pos.entry_fee, rel=1e-9) == expected_entry_fee
    assert pytest.approx(bot.available_cash, rel=1e-9) == initial_cap - (expected_notional + expected_entry_fee)
    
    # Exit at +6.5% take profit
    exit_px = pos.px * (1.0 + TAKE_PROFIT_TARGET)
    bot._execute_position_close('ORDIUSDT', exit_px=exit_px, reason='TAKE_PROFIT')
    
    gross = (exit_px - pos.px) / pos.px * expected_notional  # 20.80
    exit_fee = expected_notional * FEE_RATE  # 0.128
    net = gross - exit_fee - expected_entry_fee  # 20.544
    
    assert pytest.approx(bot.available_cash, rel=1e-9) == initial_cap + net
    assert pytest.approx(bot.available_cash, rel=1e-9) == 1020.544
    assert pytest.approx(bot.get_total_equity(), rel=1e-9) == 1020.544
    assert len(bot.trade_history) == 1
    assert pytest.approx(bot.trade_history[0].net, rel=1e-9) == 20.544

def test_unrealized_equity_and_state(tmp_path):
    """Verify real-time mark-to-market equity and state accounting with open positions."""
    from mega22_paper_bot import Mega22PaperBot
    journal = tmp_path / "test_unrealized.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    pos1 = Position(sym='ORDIUSDT', px=10.0, notional=300.0, entry_fee=0.12, i=10, entry_time='2026-01-01', current_px=10.50, unrealized_pnl=15.0)
    pos2 = Position(sym='TIAUSDT', px=20.0, notional=300.0, entry_fee=0.12, i=12, entry_time='2026-01-01', current_px=19.60, unrealized_pnl=-6.0)
    bot.available_cash = 400.0 - 0.24
    bot.active_positions['ORDIUSDT'] = pos1
    bot.active_positions['TIAUSDT'] = pos2
    
    eq = bot.get_total_equity()
    assert pytest.approx(eq, rel=1e-6) == 1008.52
    
    state = bot.get_full_state()
    assert state['equity'] == 1008.52
    assert state['unrealized_pnl'] == 9.0
    assert state['total_pnl'] == 8.52

@pytest.mark.asyncio
async def test_multi_stream_debounce_sync(tmp_path):
    """Verify that multi-stream candle processing cancels debounce when all 23 arrive."""
    from mega22_paper_bot import Mega22PaperBot
    from mega22_constants import ALL_SYMBOLS
    journal = tmp_path / "test_sync.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    t0 = pd.Timestamp('2026-01-01 12:00:00')
    dummy_bar = {
        'open_time': t0, 'open': 10.0, 'high': 10.5, 'low': 9.8, 'close': 10.2,
        'volume': 1000.0, 'taker_buy': 550.0, 'taker_sell': 450.0, 'tbv_ratio': 0.55
    }
    
    # Send first 22 pairs
    for sym in ALL_SYMBOLS[:-1]:
        await bot.on_candle_closed(sym, dummy_bar)
        
    assert t0 in bot._closed_candles_in_interval
    assert len(bot._closed_candles_in_interval[t0]) == len(ALL_SYMBOLS) - 1
    assert t0 in bot._pending_debounce_tasks
    
    # Send 23rd pair (triggers immediate processing and cancels debounce)
    last_sym = ALL_SYMBOLS[-1]
    initial_bar_index = bot.bar_index
    await bot.on_candle_closed(last_sym, dummy_bar)
    
    assert bot.bar_index == initial_bar_index + 1
    assert t0 in bot._processed_intervals
    assert t0 not in bot._pending_debounce_tasks

def test_journal_round_trip_persistence(tmp_path):
    """Verify that portfolio state, bar index, cooldowns and circuit breakers persist across reloads."""
    from mega22_paper_bot import Mega22PaperBot
    journal = tmp_path / "test_journal.json"
    
    bot1 = Mega22PaperBot(journal_path=journal)
    bot1.bar_index = 88
    bot1.available_cash = 750.25
    bot1.consecutive_stops = 2
    bot1.stoploss_guard_until = 136
    bot1.cooldowns['NEARUSDT'] = 112
    pos = Position(
        sym='NEARUSDT', px=5.50, notional=240.0, entry_fee=0.096,
        i=85, entry_time='2026-01-01T00:00:00Z', stop=0.022
    )
    bot1.active_positions['NEARUSDT'] = pos
    bot1._save_journal()
    
    # Reload in bot2
    bot2 = Mega22PaperBot(journal_path=journal)
    assert bot2.bar_index == 88
    assert pytest.approx(bot2.available_cash, rel=1e-6) == 750.25
    assert bot2.consecutive_stops == 2
    assert bot2.stoploss_guard_until == 136
    assert bot2.cooldowns['NEARUSDT'] == 112
    assert 'NEARUSDT' in bot2.active_positions
    p2 = bot2.active_positions['NEARUSDT']
    assert p2.px == 5.50
    assert p2.i == 85

def test_multi_bar_trailing_ratchet_peak_preservation():
    """Verify that highest_since_trail preserves the peak price across bars when trailing is inactive."""
    pos = Position(
        sym='NEARUSDT', px=10.0, notional=320.0, entry_fee=0.128,
        i=50, entry_time='2026-01-01T00:00:00Z', stop=0.022
    )
    # Bar 1: Price reaches high 10.50 (best_pnl +5%), locks parabolic tier 3 (-0.035), exit_sig=0
    event, pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=10.40, h=10.50, l=10.36, exit_sig=0, held=1
    )
    assert event is None
    assert pos.trailing_active is False
    assert pos.highest_since_trail == 10.50
    assert pos.stop == -0.035
    
    # Bar 2: Price consolidates (high 10.45 < 10.50, staying above 10.35 lock), exit_sig=0
    # Crucial test: highest_since_trail must NOT be overwritten by 10.45!
    event, pos = Mega22StrategyEngine.evaluate_position_step(
        pos, c=10.38, h=10.45, l=10.36, exit_sig=0, held=2
    )
    assert event is None
    assert pos.trailing_active is False
    assert pos.highest_since_trail == 10.50

def test_realtime_tick_trailing_lock_exit(tmp_path):
    """
    Critical verification: When a trade reaches profit (+5%) and stop is raised/locked
    (e.g. pos.stop = -0.029245 / +2.92%), on_tick_update MUST close the position immediately
    when price pulls back to the locked stop level (0.362573), preventing a -$3 loss.
    """
    from mega22_paper_bot import Mega22PaperBot
    journal = tmp_path / "test_tick_lock.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    pos = Position(
        sym='TIAUSDT',
        px=0.35227044,
        notional=324.19,
        entry_fee=0.13,
        i=309,
        entry_time='2026-09-13T22:10:03Z',
        stop=-0.02924547,
        trailing_active=True,
        highest_since_trail=0.3668,
        highest_seen=0.3687,
        lowest_seen=0.3482,
        current_px=0.3641
    )
    bot.active_positions['TIAUSDT'] = pos
    expected_stop_px = pos.px * (1.0 - pos.stop)  # ~0.362573 (+2.92%)
    
    # Tick above stop (0.3630) -> position must remain OPEN
    bot.on_tick_update('TIAUSDT', current_px=0.3630, high_px=0.3630, low_px=0.3630)
    assert 'TIAUSDT' in bot.active_positions
    
    # Pullback tick hits locked stop level (0.3625 <= 0.362573) -> MUST CLOSE IMMEDIATELY
    bot.on_tick_update('TIAUSDT', current_px=0.3625, high_px=0.3625, low_px=0.3625)
    assert 'TIAUSDT' not in bot.active_positions, "Position must be closed at locked profit stop!"
    assert len(bot.trade_history) == 1
    trade = bot.trade_history[0]
    assert trade.reason == 'TRAILING_LOCK'
    assert pytest.approx(trade.exit_px, rel=1e-6) == expected_stop_px
    assert trade.net > 0, "Trailing lock must close with positive net profit!"

@pytest.mark.asyncio
async def test_closed_candle_trailing_lock_exit(tmp_path):
    """Verify that on_candle_closed enforces trailing lock floor if tick was missed."""
    from mega22_paper_bot import Mega22PaperBot
    journal = tmp_path / "test_candle_lock.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    pos = Position(
        sym='TIAUSDT',
        px=0.35227044,
        notional=324.19,
        entry_fee=0.13,
        i=309,
        entry_time='2026-09-13T22:10:03Z',
        stop=-0.02924547,
        trailing_active=True,
        highest_since_trail=0.3668,
        highest_seen=0.3687,
        lowest_seen=0.3482,
        current_px=0.3641
    )
    bot.active_positions['TIAUSDT'] = pos
    expected_stop_px = pos.px * (1.0 - pos.stop)
    
    # Candle closes below locked stop floor (e.g. close=0.3620)
    bar = {
        'open_time': pd.to_datetime('2026-09-14 21:05:00'),
        'open': 0.3635,
        'high': 0.3638,
        'low': 0.3615,
        'close': 0.3620,
        'volume': 1000.0,
        'taker_buy': 500.0,
        'taker_sell': 500.0,
        'tbv_ratio': 0.5
    }
    await bot.on_candle_closed('TIAUSDT', bar)
    assert 'TIAUSDT' not in bot.active_positions
    assert len(bot.trade_history) == 1
    assert bot.trade_history[0].reason == 'TRAILING_LOCK'
    assert pytest.approx(bot.trade_history[0].exit_px, rel=1e-6) == expected_stop_px

def test_tick_low_piercing_trailing_lock_exit(tmp_path):
    """
    Verify that an intra-bar wick dip (low_px <= stop_price) triggers TRAILING_LOCK
    even if current_px has temporarily bounced above stop_price.
    """
    from mega22_paper_bot import Mega22PaperBot
    journal = tmp_path / "test_wick_lock.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    pos = Position(
        sym='TIAUSDT',
        px=0.35227044,
        notional=324.19,
        entry_fee=0.13,
        i=309,
        entry_time='2026-09-13T22:10:03Z',
        stop=-0.02924547,
        trailing_active=True,
        highest_since_trail=0.3668,
        highest_seen=0.3687,
        lowest_seen=0.3482,
        current_px=0.3641
    )
    bot.active_positions['TIAUSDT'] = pos
    expected_stop_px = pos.px * (1.0 - pos.stop)  # ~0.362573
    
    # Tick with current_px=0.3630 (> stop_px), but low_px=0.3620 (<= stop_px)
    bot.on_tick_update('TIAUSDT', current_px=0.3630, high_px=0.3635, low_px=0.3620)
    assert 'TIAUSDT' not in bot.active_positions, "Position must close when low_px pierces stop price!"
    assert len(bot.trade_history) == 1
    assert bot.trade_history[0].reason == 'TRAILING_LOCK'
    assert pytest.approx(bot.trade_history[0].exit_px, rel=1e-6) == expected_stop_px

def test_trailing_stop_raised_to_2_3_pct_drop_below_instant_exit(tmp_path):
    """
    Direct user regression test:
    Position entered at 0.391178. Stop is raised to +2.3% (pos.stop = -0.023, stop_price = 0.400175).
    Price drops below the stop to 0.39962 (+2.16%).
    1. Mega22StrategyEngine.evaluate_position_step MUST return TRAILING_LOCK exit event.
    2. Mega22PaperBot.on_tick_update MUST close the position immediately without manual override.
    """
    from mega22_paper_bot import Mega22PaperBot
    
    pos = Position(
        sym='TIAUSDT',
        px=0.391178,
        notional=329.67,
        entry_fee=0.1319,
        i=1617,
        entry_time='2026-09-18T11:10:03Z',
        stop=-0.023,  # Raised to +2.3% locked profit
        trailing_active=True,
        highest_since_trail=0.40487,
        highest_seen=0.40487,
        lowest_seen=0.3910,
        current_px=0.4020
    )
    expected_stop_px = pos.px * (1.0 - pos.stop)  # ~0.400175

    # 1. Strategy Engine Direct Evaluation test (guarantees engine triggers exit)
    event, _ = Mega22StrategyEngine.evaluate_position_step(
        pos=pos, c=0.39962, h=0.4010, l=0.39962, exit_sig=0, held=31
    )
    assert event is not None, "Mega22StrategyEngine.evaluate_position_step must return exit event when price drops below stop!"
    strat_exit_px, strat_reason = event
    assert strat_reason == 'TRAILING_LOCK'
    assert pytest.approx(strat_exit_px, rel=1e-5) == expected_stop_px

    # 2. Paper bot live tick test (instant execution on tick below stop)
    journal = tmp_path / "test_journal_2_3.json"
    bot = Mega22PaperBot(journal_path=journal)
    bot.active_positions['TIAUSDT'] = pos
    bot.on_tick_update('TIAUSDT', current_px=0.39962, high_px=0.4010, low_px=0.39962)
    assert 'TIAUSDT' not in bot.active_positions, "Position must be closed immediately on tick below stop!"
    assert len(bot.trade_history) == 1
    assert bot.trade_history[0].reason == 'TRAILING_LOCK'
    expected_exit_px = 0.391178 * (1.0 - (-0.02300196841335653))
    assert pytest.approx(bot.trade_history[0].exit_px, rel=1e-5) == expected_exit_px

@pytest.mark.asyncio
async def test_candle_low_piercing_raised_stop_instant_exit(tmp_path):
    """
    Verify that when stop is raised to +2.3%, a candle whose close bounced above stop
    but whose low dipped below stop (e.g. low=0.3988, close=0.4008) triggers exit on candle close.
    """
    from mega22_paper_bot import Mega22PaperBot
    journal = tmp_path / "test_journal_candle_2_3.json"
    bot = Mega22PaperBot(journal_path=journal)
    pos = Position(
        sym='TIAUSDT',
        px=0.391178,
        notional=329.67,
        entry_fee=0.1319,
        i=1617,
        entry_time='2026-09-18T11:10:03Z',
        stop=-0.023,
        trailing_active=True,
        highest_since_trail=0.40487,
        highest_seen=0.40487,
        lowest_seen=0.3910,
        current_px=0.4020
    )
    bot.active_positions['TIAUSDT'] = pos

    bar = {
        'open_time': pd.to_datetime('2026-09-18 13:45:00'),
        'open': 0.4031,
        'high': 0.4031,
        'low': 0.3988,   # < 0.400175 stop price
        'close': 0.4008, # > 0.400175 stop price
        'volume': 1000.0,
        'taker_buy': 500.0,
        'taker_sell': 500.0,
        'tbv_ratio': 0.5
    }
    await bot.on_candle_closed('TIAUSDT', bar)
    assert 'TIAUSDT' not in bot.active_positions, "Position must close when candle low pierces stop price!"
    assert len(bot.trade_history) == 1
    assert bot.trade_history[0].reason == 'TRAILING_LOCK'
    expected_stop_px = 0.391178 * (1.0 - (-0.02300196841335653))
    assert pytest.approx(bot.trade_history[0].exit_px, rel=1e-5) == expected_stop_px

if __name__ == '__main__':
    pytest.main([__file__, '-v'])

