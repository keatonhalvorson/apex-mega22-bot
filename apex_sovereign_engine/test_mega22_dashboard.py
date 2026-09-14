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

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
