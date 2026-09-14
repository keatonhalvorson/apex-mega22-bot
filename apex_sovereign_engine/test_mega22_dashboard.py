"""
Comprehensive Test Suite for Mega-22 Institutional Dashboard & Live Streaming Engine
Verifies:
1. Sub-second ticker streaming, price caching, and tick direction calculation.
2. Real-time floating PnL calculation on active positions upon tick arrival.
3. Pause, Resume, and Emergency Close All functionality.
4. Quantitative performance metrics (Sharpe ratio, durations, payoff, expectancy, recovery factor).
5. FastAPI REST endpoints (state, tickers, CSV export, pause/resume, test alert).
6. WebSocket bi-directional streaming, ping/pong latency measurement, and event broadcasts.
"""

import sys
import json
import time
from pathlib import Path
import pytest
import numpy as np

# Ensure engine in path
ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from mega22_constants import MEGA_22, ALL_SYMBOLS, INITIAL_CAPITAL, MAX_SLOTS, SLOT_FRACTION
from mega22_strategy import Position, TradeRecord
from mega22_paper_bot import Mega22PaperBot
from dashboard_server import app
from fastapi.testclient import TestClient

def test_ticker_update_and_direction(tmp_path):
    """Test that on_ticker_update correctly detects tick direction, updates latest_prices and latest_tickers."""
    journal = tmp_path / "test_tick_dir.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    # Initial tick
    bot.on_ticker_update("NEARUSDT", {
        "c": "2.5000", "p": "0.10", "P": "4.16", "h": "2.60", "l": "2.35",
        "v": "100000", "q": "250000", "b": "2.4990", "a": "2.5010"
    })
    assert bot.latest_prices["NEARUSDT"] == 2.5000
    t1 = bot.latest_tickers["NEARUSDT"]
    assert t1["price"] == 2.5000
    assert t1["change_24h"] == 4.16
    assert t1["spread_bps"] > 0
    assert t1["tick_dir"] == "up"  # went from 0.0 to 2.50

    # Uptick
    bot.on_ticker_update("NEARUSDT", {
        "c": "2.5100", "p": "0.11", "P": "4.58", "h": "2.60", "l": "2.35",
        "v": "100500", "q": "251250", "b": "2.5090", "a": "2.5110"
    })
    assert bot.latest_prices["NEARUSDT"] == 2.5100
    assert bot.latest_tickers["NEARUSDT"]["tick_dir"] == "up"

    # Downtick
    bot.on_ticker_update("NEARUSDT", {
        "c": "2.5050", "p": "0.105", "P": "4.37", "h": "2.60", "l": "2.35",
        "v": "101000", "q": "252500", "b": "2.5040", "a": "2.5060"
    })
    assert bot.latest_prices["NEARUSDT"] == 2.5050
    assert bot.latest_tickers["NEARUSDT"]["tick_dir"] == "down"

def test_live_floating_pnl_on_tick(tmp_path):
    """Test that incoming ticks immediately update active position mark price and floating PnL."""
    journal = tmp_path / "test_live_pnl.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    pos = Position(
        sym="JUPUSDT", px=1.0000, notional=300.0, entry_fee=0.12,
        i=10, entry_time="2026-01-01T00:00:00Z", stop=0.022,
        highest_seen=1.0000, lowest_seen=1.0000, current_px=1.0000
    )
    bot.active_positions["JUPUSDT"] = pos

    # Tick +3% higher, with rolling 24h extremes (h=1.050, l=0.950)
    # Crucial: l=0.950 is below stop-loss (0.978), but must NOT trigger false STOP_LOSS because it is 24h rolling low!
    bot.on_ticker_update("JUPUSDT", {
        "c": "1.0300", "p": "0.03", "P": "3.00", "h": "1.050", "l": "0.950",
        "v": "50000", "q": "51500", "b": "1.029", "a": "1.031"
    })
    
    assert "JUPUSDT" in bot.active_positions, "Position must NOT be liquidated by 24h rolling low!"
    assert pos.current_px == 1.0300
    assert pos.highest_seen == 1.0300
    assert pytest.approx(pos.unrealized_pnl, rel=1e-6) == 9.00  # (1.03 - 1.00) * 300
    assert pytest.approx(pos.unrealized_pnl_pct, rel=1e-6) == 3.00

def test_bot_pause_resume_and_emergency_close(tmp_path):
    """Test pause prevents new entries, resume allows them, and emergency close liquidates all positions."""
    journal = tmp_path / "test_controls.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    # 1. Pause
    bot.pause_trading()
    assert bot.is_paused is True
    
    # Attempt entry while paused
    bot.available_cash = 1000.0
    bot.latest_indicators["ORDIUSDT"] = {"is_cand": 1, "score": 90.0, "price": 50.0}
    bot._evaluate_portfolio_entries()
    assert "ORDIUSDT" not in bot.active_positions, "Entries must be blocked while bot is paused!"

    # 2. Resume
    bot.resume_trading()
    assert bot.is_paused is False
    bot._evaluate_portfolio_entries()
    assert "ORDIUSDT" in bot.active_positions, "Entries must succeed when bot is resumed!"

    # Add second position
    bot.latest_indicators["NEARUSDT"] = {"is_cand": 1, "score": 85.0, "price": 5.0}
    bot._evaluate_portfolio_entries()
    assert len(bot.active_positions) == 2

    # 3. Emergency Close All
    closed = bot.emergency_close_all()
    assert len(closed) == 2
    assert len(bot.active_positions) == 0
    assert len(bot.trade_history) == 2
    for t in bot.trade_history:
        assert t.reason == "EMERGENCY_CLOSE_ALL"

def test_quantitative_summary_stats(tmp_path):
    """Test calculation of Sharpe ratio, durations, payoff ratio, expectancy, and streaks."""
    journal = tmp_path / "test_quant_stats.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    # Empty stats default
    s0 = bot.get_summary_stats()
    assert s0["total_trades"] == 0
    assert s0["sharpe_ratio"] == 0.0
    assert s0["payoff_ratio"] == 0.0

    # Add synthetic trade history: 3 wins, 1 loss
    t1 = TradeRecord(
        sym="NEARUSDT", entry_time="t1", exit_time="t2", entry_i=10, exit_i=18,
        entry_px=5.0, exit_px=5.325, pnl_pct=6.5, notional=300.0, gross=19.5, net=19.26,
        entry_fee=0.12, exit_fee=0.12, reason="TAKE_PROFIT", bars_held=8, cap_after=1019.26
    )
    t2 = TradeRecord(
        sym="ORDIUSDT", entry_time="t2", exit_time="t3", entry_i=20, exit_i=24,
        entry_px=50.0, exit_px=48.9, pnl_pct=-2.2, notional=300.0, gross=-6.6, net=-6.84,
        entry_fee=0.12, exit_fee=0.12, reason="STOP_LOSS", bars_held=4, cap_after=1012.42
    )
    t3 = TradeRecord(
        sym="JUPUSDT", entry_time="t3", exit_time="t4", entry_i=30, exit_i=42,
        entry_px=1.0, exit_px=1.035, pnl_pct=3.5, notional=300.0, gross=10.5, net=10.26,
        entry_fee=0.12, exit_fee=0.12, reason="TRAILING_LOCK", bars_held=12, cap_after=1022.68
    )
    bot.trade_history.extend([t1, t2, t3])

    stats = bot.get_summary_stats()
    assert stats["total_trades"] == 3
    assert stats["winning_trades"] == 2
    assert stats["losing_trades"] == 1
    assert pytest.approx(stats["win_rate"], rel=1e-2) == 66.7
    assert stats["gross_profit"] == 29.52
    assert stats["gross_loss"] == 6.84
    assert stats["profit_factor"] > 4.0
    assert stats["sharpe_ratio"] > 0.0
    assert stats["avg_trade_duration_bars"] == 8.0  # (8 + 4 + 12) / 3
    assert stats["avg_trade_duration_min"] == 40
    assert stats["max_consecutive_wins"] >= 1
    assert stats["max_consecutive_losses"] >= 1

def test_fastapi_rest_endpoints():
    """Verify all FastAPI REST routes return 200 and expected schema."""
    client = TestClient(app)
    
    # GET /
    res = client.get("/")
    assert res.status_code == 200
    assert "APEX SOVEREIGN QUANTITATIVE ENGINE" in res.text
    assert "hawkesGaugeCanvas" in res.text

    # GET /api/state
    res = client.get("/api/state")
    assert res.status_code == 200
    d = res.json()
    assert "equity" in d
    assert "leaderboard" in d
    assert "tickers" in d
    assert "is_paused" in d

    # GET /api/tickers
    res = client.get("/api/tickers")
    assert res.status_code == 200
    tickers_dict = res.json()
    assert len(tickers_dict) >= 22
    assert any(t.get("group") == "GOLDEN_11" for t in tickers_dict.values())
    assert any(t.get("group") == "TITAN_11" for t in tickers_dict.values())

    # GET /api/hawkes
    res_hawkes = client.get("/api/hawkes")
    assert res_hawkes.status_code == 200
    h_data = res_hawkes.json()
    assert "hawkes" in h_data
    assert "history" in h_data
    assert "threshold" in h_data
    assert h_data["threshold"] == 0.035
    assert "is_safe" in h_data

    # POST /api/action/pause & resume
    res = client.post("/api/action/pause")
    assert res.status_code == 200
    assert res.json()["is_paused"] is True

    res = client.post("/api/action/resume")
    assert res.status_code == 200
    assert res.json()["is_paused"] is False

    # POST /api/action/test_alert
    res = client.post("/api/action/test_alert")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    # GET /api/trades/export.csv
    res = client.get("/api/trades/export.csv")
    assert res.status_code == 200
    assert "Trade_ID,Symbol" in res.text
    assert res.headers["content-type"].startswith("text/csv")

def test_websocket_live_streaming():
    """Verify WebSocket bi-directional streaming, state push, and ping/pong latency."""
    client = TestClient(app)
    with client.websocket_connect("/ws/live") as ws:
        # Initial snapshot
        msg = ws.receive_json()
        assert msg["type"] == "state_snapshot"
        assert "equity" in msg["data"]

        # Ping / Pong
        t_send = int(time.time() * 1000)
        ws.send_json({"action": "ping", "t": t_send})
        pong = ws.receive_json()
        assert pong["type"] == "pong"
        assert pong["client_t"] == t_send
        assert "server_t" in pong

        # Test alert command
        ws.send_json({"action": "test_alert"})
        # Event should be broadcasted to client
        alert_msg = ws.receive_json()
        assert alert_msg["type"] == "alert"
        assert alert_msg["data"]["title"] == "QUANT TERMINAL TEST"

def test_position_bars_held_and_duration_calculation(tmp_path):
    """Test that active positions calculate and report held_bars, bars_held, and duration_min accurately."""
    journal = tmp_path / "test_bars.json"
    bot = Mega22PaperBot(journal_path=journal)
    bot.bar_index = 50
    
    pos = Position(
        sym="TIAUSDT", px=0.35, notional=320.0, entry_fee=0.128,
        i=20, entry_time="2026-09-13T22:10:00Z"
    )
    bot.active_positions["TIAUSDT"] = pos
    
    # 1. to_dict with current_bar_index
    pos_d = pos.to_dict(current_bar_index=bot.bar_index)
    assert pos_d["held_bars"] == 30  # 50 - 20
    assert pos_d["bars_held"] == 30
    assert pos_d["duration_min"] == 150  # 30 * 5 min
    
    # 2. In get_full_state
    state = bot.get_full_state()
    assert len(state["active_positions"]) == 1
    pos_state = state["active_positions"][0]
    assert pos_state["held_bars"] == 30
    assert pos_state["bars_held"] == 30
    assert pos_state["duration_min"] == 150

def test_state_and_tick_consistency(tmp_path):
    """Test that state snapshot and subsecond tick broadcasts have identical, consistent Net PnL and ROE values."""
    journal = tmp_path / "test_consistency.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    # Add a closed trade: +$20 profit
    t1 = TradeRecord(
        sym="INJUSDT", entry_time="t1", exit_time="t2", entry_i=5, exit_i=20,
        entry_px=5.0, exit_px=5.325, pnl_pct=6.5, notional=320.0, gross=20.8, net=20.54,
        entry_fee=0.13, exit_fee=0.13, reason="TAKE_PROFIT", bars_held=15, cap_after=1020.54
    )
    bot.trade_history.append(t1)
    bot.available_cash = 1020.54
    
    # Add open position with +$10 floating profit
    pos = Position(
        sym="TIAUSDT", px=0.35, notional=320.0, entry_fee=0.13,
        i=25, entry_time="2026-09-13T22:10:00Z", current_px=0.3609375, unrealized_pnl=10.0
    )
    bot.active_positions["TIAUSDT"] = pos
    
    # Capture broadcasts
    events = []
    bot.add_listener(lambda ev, data: events.append((ev, data)))
    
    # Trigger tick update
    bot.on_ticker_update("TIAUSDT", {
        "c": "0.3609375", "p": "0.01", "P": "3.12", "h": "0.37", "l": "0.34",
        "v": "1000", "q": "360", "b": "0.36", "a": "0.361"
    })
    
    tick_data = [d for ev, d in events if ev == "tick"][-1]
    state_data = bot.get_full_state()
    
    # Critical parity check: tick and snapshot MUST report identical total_pnl and net_profit
    assert pytest.approx(tick_data["total_pnl"], rel=1e-2) == state_data["total_pnl"]
    assert pytest.approx(tick_data["net_profit"], rel=1e-2) == state_data["net_profit"]
    assert pytest.approx(tick_data["total_roe_pct"], rel=1e-2) == state_data["total_roe_pct"]
    assert pytest.approx(tick_data["roe_pct"], rel=1e-2) == state_data["roe_pct"]
    assert state_data["capital"] == state_data["equity"]
    assert tick_data["capital"] == tick_data["equity"]
    # Total PnL should be ~$30.41 (realized $20.54 + unrealized gross $10.0 - est exit fee $0.13)
    assert tick_data["total_pnl"] > 30.0
    assert state_data["total_pnl"] > 30.0

def test_capital_accumulation_and_compounding(tmp_path):
    """Test that multiple trade closes correctly compound and preserve cumulative capital."""
    journal = tmp_path / "test_compound.json"
    bot = Mega22PaperBot(journal_path=journal)
    
    # Initial state
    assert bot.capital == 1000.0
    assert bot.available_cash == 1000.0
    
    # 1. Trade 1: +$20 profit
    pos1 = Position(sym="INJUSDT", px=5.0, notional=320.0, entry_fee=0.128, i=5, entry_time="t1")
    bot.available_cash -= (320.0 + 0.128)
    bot.active_positions["INJUSDT"] = pos1
    bot._execute_position_close("INJUSDT", exit_px=5.325, reason="TAKE_PROFIT")
    
    assert pytest.approx(bot.available_cash, rel=1e-2) == 1020.54
    assert pytest.approx(bot.capital, rel=1e-2) == 1020.54
    assert bot.trade_history[0].cap_after == 1020.54
    
    # 2. Trade 2: -$7 loss
    pos2 = Position(sym="FILUSDT", px=1.0, notional=326.57, entry_fee=0.13, i=10, entry_time="t2")
    bot.available_cash -= (326.57 + 0.13)
    bot.active_positions["FILUSDT"] = pos2
    bot._execute_position_close("FILUSDT", exit_px=0.978, reason="STOP_LOSS")
    
    assert pytest.approx(bot.available_cash, rel=1e-2) == 1013.10
    assert pytest.approx(bot.capital, rel=1e-2) == 1013.10
    assert bot.trade_history[1].cap_after == 1013.10
    
    # 3. Reload from saved journal and verify persistence
    bot2 = Mega22PaperBot(journal_path=journal)
    assert pytest.approx(bot2.available_cash, rel=1e-2) == 1013.10
    assert pytest.approx(bot2.capital, rel=1e-2) == 1013.10
    assert len(bot2.trade_history) == 2
    assert bot2.trade_history[1].cap_after == 1013.10

def test_journal_resilience_to_unknown_fields(tmp_path):
    """Test that Position and TradeRecord ignore unknown fields when deserialized from JSON."""
    d_pos = {
        "sym": "TIAUSDT", "px": 0.35, "notional": 320.0, "entry_fee": 0.128,
        "i": 10, "entry_time": "t1", "unknown_extra_metric": 999.9, "legacy_field": "test"
    }
    p = Position.from_dict(d_pos)
    assert p.sym == "TIAUSDT"
    assert p.px == 0.35
    assert not hasattr(p, "unknown_extra_metric")
    
    d_trade = {
        "sym": "INJUSDT", "entry_time": "t1", "exit_time": "t2", "entry_i": 5, "exit_i": 20,
        "entry_px": 5.0, "exit_px": 5.325, "pnl_pct": 6.5, "notional": 320.0, "gross": 20.8,
        "net": 20.54, "entry_fee": 0.13, "exit_fee": 0.13, "reason": "TAKE_PROFIT",
        "bars_held": 15, "cap_after": 1020.54, "extra_experimental_flag": True
    }
    t = TradeRecord.from_dict(d_trade)
    assert t.sym == "INJUSDT"
    assert t.net == 20.54
    assert not hasattr(t, "extra_experimental_flag")

def test_trade_record_missing_fields_defaults():
    """Test that TradeRecord gracefully defaults bars_held and cap_after when omitted."""
    d = {
        "sym": "BONKUSDT", "entry_time": "t1", "exit_time": "t2", "entry_i": 1, "exit_i": 2,
        "entry_px": 0.00001, "exit_px": 0.000012, "pnl_pct": 20.0, "notional": 300.0,
        "gross": 60.0, "net": 59.5, "entry_fee": 0.25, "exit_fee": 0.25, "reason": "TAKE_PROFIT"
    }
    t = TradeRecord.from_dict(d)
    assert t.bars_held == 0
    assert t.cap_after == 1000.0

def test_tick_payload_includes_sharpe():
    """Test that tick broadcast includes sharpe_ratio matching state snapshot."""
    bot = Mega22PaperBot()
    t1 = TradeRecord(
        sym="INJUSDT", entry_time="t1", exit_time="t2", entry_i=5, exit_i=20,
        entry_px=5.0, exit_px=5.325, pnl_pct=6.5, notional=320.0, gross=20.8, net=20.54,
        entry_fee=0.13, exit_fee=0.13, reason="TAKE_PROFIT", bars_held=15, cap_after=1020.54
    )
    bot.trade_history.append(t1)
    events = []
    bot.add_listener(lambda ev, data: events.append((ev, data)))
    bot.on_ticker_update("TIAUSDT", {
        "c": "0.35", "p": "0.0", "P": "0.0", "h": "0.36", "l": "0.34",
        "v": "100", "q": "35", "b": "0.35", "a": "0.351"
    })
    tick = [d for ev, d in events if ev == "tick"][-1]
    state = bot.get_full_state()
    assert "sharpe_ratio" in tick
    assert tick["sharpe_ratio"] == state["sharpe_ratio"]

def test_position_to_dict_entry_time_fallback():
    """Test that Position.to_dict computes elapsed bars and duration_min from entry_time when held_bars is 0."""
    from datetime import datetime, timezone, timedelta
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    pos = Position(
        sym="TIAUSDT", px=0.35, notional=320.0, entry_fee=0.13,
        i=0, entry_time=past_time
    )
    # When called without current_bar_index and held_bars=0, should calculate from timestamp
    d = pos.to_dict()
    assert d["held_bars"] >= 8
    assert d["bars_held"] >= 8
    assert d["duration_min"] >= 40

def test_position_to_dict_never_resets_when_current_bar_index_behind():
    """Verify that Position.to_dict never wipes held_bars or duration_min to 0 when current_bar_index <= pos.i."""
    from datetime import datetime, timezone, timedelta
    past_time = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
    pos = Position(
        sym="TIAUSDT", px=0.35, notional=320.0, entry_fee=0.13,
        i=309, entry_time=past_time, held_bars=263
    )
    # 1. Called with current_bar_index=0 (e.g. server restart)
    d1 = pos.to_dict(current_bar_index=0)
    assert d1["held_bars"] >= 263
    assert d1["bars_held"] >= 263
    assert d1["duration_min"] >= 1315
    assert pos.held_bars >= 263

    # 2. Called with current_bar_index=309 (current_bar_index == pos.i)
    d2 = pos.to_dict(current_bar_index=309)
    assert d2["held_bars"] >= 263
    assert d2["duration_min"] >= 1315

def test_tick_payload_includes_server_time_ms():
    """Verify that tick payload contains server_time_ms for client clock sync."""
    bot = Mega22PaperBot()
    events = []
    bot.add_listener(lambda ev, d: events.append((ev, d)))
    bot.on_ticker_update("TIAUSDT", {
        "c": "0.3600", "p": "0.01", "P": "2.85", "h": "0.37", "l": "0.34",
        "v": "100500", "q": "251250", "b": "0.3599", "a": "0.3601"
    })
    ticks = [d for ev, d in events if ev == "tick"]
    assert len(ticks) > 0
    assert "server_time_ms" in ticks[-1]
    assert ticks[-1]["server_time_ms"] > 0

def test_dashboard_html_contains_nonflickering_heatmap_and_radar():
    """Verify that dashboard_server HTML includes in-place heatmap and radar updating."""
    from dashboard_server import DASHBOARD_HTML
    assert "renderHeatmapCardHtml" in DASHBOARD_HTML
    assert "updateHeatmapCard" in DASHBOARD_HTML
    assert "radar-item-" in DASHBOARD_HTML
    assert "Date.UTC" in DASHBOARD_HTML

def test_tick_broadcasting_throttled_per_symbol(tmp_path):
    """Verify that rapid tick bursts for the same symbol are throttled to 250ms, while maintaining state and independent symbols."""
    journal = tmp_path / "journal.json"
    bot = Mega22PaperBot(journal_path=journal, tick_broadcast_interval=0.25)
    events = []
    bot.add_listener(lambda ev, d: events.append((ev, d)))

    # 1. First tick for NEARUSDT -> should broadcast
    bot.on_ticker_update("NEARUSDT", {
        "c": "2.50", "p": "0.01", "P": "1.0", "h": "2.60", "l": "2.40",
        "v": "100", "q": "250", "b": "2.49", "a": "2.51"
    })
    near_ticks = [d for ev, d in events if ev == "tick" and d["sym"] == "NEARUSDT"]
    assert len(near_ticks) == 1

    # 2. Immediate second tick for NEARUSDT (within <250ms) -> throttled from broadcast
    bot.on_ticker_update("NEARUSDT", {
        "c": "2.55", "p": "0.06", "P": "2.0", "h": "2.60", "l": "2.40",
        "v": "105", "q": "260", "b": "2.54", "a": "2.56"
    })
    near_ticks_2 = [d for ev, d in events if ev == "tick" and d["sym"] == "NEARUSDT"]
    assert len(near_ticks_2) == 1  # Not broadcasted
    # But internal state MUST still be updated!
    assert bot.latest_prices["NEARUSDT"] == 2.55
    assert bot.latest_tickers["NEARUSDT"]["price"] == 2.55

    # 3. Tick for a different symbol (ICPUSDT) -> should broadcast independently
    bot.on_ticker_update("ICPUSDT", {
        "c": "8.50", "p": "0.10", "P": "1.5", "h": "8.60", "l": "8.40",
        "v": "100", "q": "850", "b": "8.49", "a": "8.51"
    })
    icp_ticks = [d for ev, d in events if ev == "tick" and d["sym"] == "ICPUSDT"]
    assert len(icp_ticks) == 1

    # 4. Wait for throttle interval to expire (>= 250ms)
    time.sleep(0.26)
    bot.on_ticker_update("NEARUSDT", {
        "c": "2.60", "p": "0.11", "P": "2.5", "h": "2.65", "l": "2.40",
        "v": "110", "q": "270", "b": "2.59", "a": "2.61"
    })
    near_ticks_3 = [d for ev, d in events if ev == "tick" and d["sym"] == "NEARUSDT"]
    assert len(near_ticks_3) == 2
    assert near_ticks_3[-1]["price"] == 2.60

def test_dashboard_html_no_recursive_ping_storm():
    """Verify that dashboard HTML contains no recursive ping storm in pong handler and checks RTT sanity."""
    from dashboard_server import DASHBOARD_HTML
    import re
    # Extract pong handler block
    pong_match = re.search(r"else if\s*\(msg\.type\s*===\s*'pong'[\s\S]*?\}(?=\s*else if|\s*\}\s*catch)", DASHBOARD_HTML)
    assert pong_match is not None, "Pong handler block must be present"
    pong_block = pong_match.group(0)

    # Must NOT call sendPing() anywhere inside the pong handler
    assert "sendPing()" not in pong_block, "CRITICAL: sendPing() must never be called inside pong handler to prevent ping storms"
    assert "Math.max(1, now - msg.client_t)" in pong_block
    assert "rtt < 5000" in pong_block

def test_dashboard_html_ping_matching_and_watchdog():
    """Verify that dashboard HTML tracks lastPingSentTime, checks matching on pong, and has watchdog."""
    from dashboard_server import DASHBOARD_HTML
    assert "lastPingSentTime" in DASHBOARD_HTML
    assert "msg.client_t === lastPingSentTime" in DASHBOARD_HTML
    assert "lastPongReceived" in DASHBOARD_HTML
    assert "ws.close()" in DASHBOARD_HTML

def test_reset_portfolio_clears_tick_broadcast_cache(tmp_path):
    """Verify that resetting portfolio clears the tick broadcast throttling timestamps."""
    journal = tmp_path / "journal.json"
    bot = Mega22PaperBot(journal_path=journal, tick_broadcast_interval=0.25)
    bot.add_listener(lambda ev, d: None)
    bot.on_ticker_update("TIAUSDT", {
        "c": "0.35", "p": "0.01", "P": "1.0", "h": "0.36", "l": "0.34",
        "v": "1000", "q": "350", "b": "0.349", "a": "0.351"
    })
    assert "TIAUSDT" in bot._last_tick_broadcast
    bot.reset_portfolio()
    assert len(bot._last_tick_broadcast) == 0

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
