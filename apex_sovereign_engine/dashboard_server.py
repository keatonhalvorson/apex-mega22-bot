"""
====================================================================================================
      🌌 APEX SOVEREIGN QUANTITATIVE ENGINE — INSTITUTIONAL MEGA-22 COCKPIT
      
      High-performance FastAPI Server with Sub-Second Live WebSocket Streaming.
      Aesthetic: Bloomberg Terminal / Citadel / Jane Street Quantitative Cockpit.
      Architecture: Pure Vanilla JS + Canvas (< 30MB RAM, < 0.2% CPU).
====================================================================================================
"""

import os
import sys
import json
import time
import io
import csv
import asyncio
import logging
from pathlib import Path
from typing import Set, Optional, Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Ensure engine directory in path
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mega22_paper_bot import Mega22PaperBot
from mega22_constants import (
    MEGA_22, GOLDEN_11, TITAN_11, MACRO_SYMBOL, ALL_SYMBOLS,
    INITIAL_CAPITAL, MAX_SLOTS, SLOT_FRACTION, BTC_HAWKES_MAX_INTENSITY
)

from contextlib import asynccontextmanager

logger = logging.getLogger("Mega22Dashboard")

# Global Bot Instance & Connected WebSocket Clients
bot = Mega22PaperBot()
connected_websockets: Set[WebSocket] = set()

async def _safe_send_ws(ws: WebSocket, message: str):
    try:
        await ws.send_text(message)
    except Exception:
        connected_websockets.discard(ws)

def websocket_event_handler(event_type: str, data: dict):
    """Callback from bot to immediately push events to all connected dashboard browsers."""
    if not connected_websockets:
        return
    message = json.dumps({"type": event_type, "data": data})
    for ws in list(connected_websockets):
        asyncio.create_task(_safe_send_ws(ws, message))

bot.add_listener(websocket_event_handler)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Launch the paper trading bot event loop in the background on startup, clean up on shutdown."""
    logger.info("Starting Mega-22 Sovereign Paper Trading Bot in background task...")
    bot_task = asyncio.create_task(bot.run())
    bcast_task = asyncio.create_task(periodic_state_broadcast())
    yield
    bot.is_running = False
    bot_task.cancel()
    bcast_task.cancel()

app = FastAPI(title="APEX Sovereign Mega-22 Quantitative Terminal", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def periodic_state_broadcast():
    """Pushes fresh state snapshot to all open browser tabs every 1 second."""
    while True:
        try:
            await asyncio.sleep(1.0)
            if connected_websockets:
                state = bot.get_full_state()
                msg = json.dumps({"type": "state_snapshot", "data": state})
                tasks = [_safe_send_ws(ws, msg) for ws in list(connected_websockets)]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.debug(f"Broadcast error: {e}")

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time bi-directional streaming WebSocket for the dashboard."""
    await websocket.accept()
    connected_websockets.add(websocket)
    try:
        # Immediately send current state on connect
        state = bot.get_full_state()
        await websocket.send_text(json.dumps({"type": "state_snapshot", "data": state}))
        while True:
            msg_text = await websocket.receive_text()
            try:
                cmd = json.loads(msg_text)
                action = cmd.get("action")
                if action == "ping":
                    # Instantaneous Pong for client latency measurement
                    pong = json.dumps({
                        "type": "pong",
                        "client_t": cmd.get("t", 0),
                        "server_t": int(time.time() * 1000)
                    })
                    await websocket.send_text(pong)
                elif action == "pause":
                    bot.pause_trading()
                elif action == "resume":
                    bot.resume_trading()
                elif action == "emergency_close":
                    bot.emergency_close_all()
                elif action == "reset":
                    bot.reset_portfolio()
                elif action == "close_position":
                    sym = cmd.get("symbol")
                    if sym:
                        bot.manual_close_position(sym.upper())
                elif action == "test_alert":
                    bot._broadcast("alert", {
                        "title": "QUANT TERMINAL TEST",
                        "message": "APEX Sovereign sound & alert latency diagnostic verified.",
                        "level": "INFO"
                    })
            except Exception:
                pass
    except WebSocketDisconnect:
        connected_websockets.discard(websocket)
    except Exception:
        connected_websockets.discard(websocket)

@app.get("/api/health")
@app.head("/api/health")
async def api_health():
    return {"status": "ok", "bot_running": bot.is_running}

@app.get("/api/state")
async def get_state():
    """REST API: current state snapshot."""
    return JSONResponse(content=bot.get_full_state())

@app.get("/api/trades")
async def get_trades():
    """REST API: completed trades list."""
    return JSONResponse(content=[t.to_dict() for t in bot.trade_history])

@app.get("/api/tickers")
async def get_tickers():
    """REST API: real-time 24h ticker cache for all pairs."""
    return JSONResponse(content=bot.latest_tickers)

@app.get("/api/hawkes")
async def get_hawkes():
    """REST API: BTC Hawkes cascade shield and historical volatility trajectory."""
    return JSONResponse(content={
        "hawkes": bot.btc_hawkes,
        "history": list(bot.btc_hawkes_history),
        "threshold": BTC_HAWKES_MAX_INTENSITY,
        "is_safe": bot.is_btc_safe,
        "btc_24h": bot.btc_24h,
        "btc_4h": bot.btc_4h,
        "btc_price": bot.latest_prices.get(MACRO_SYMBOL, 0.0)
    })

@app.get("/api/trades/export.csv")
async def export_trades_csv():
    """REST API: export all trade records as downloadable CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Trade_ID", "Symbol", "Entry_Time", "Exit_Time", "Entry_Price", "Exit_Price",
        "PnL_Percent", "Notional_USD", "Gross_PnL_USD", "Net_PnL_USD",
        "Entry_Fee_USD", "Exit_Fee_USD", "Exit_Reason", "Bars_Held", "Duration_Minutes", "Capital_After"
    ])
    for idx, t in enumerate(bot.trade_history):
        writer.writerow([
            idx + 1,
            t.sym,
            t.entry_time,
            t.exit_time,
            f"{t.entry_px:.4f}",
            f"{t.exit_px:.4f}",
            f"{t.pnl_pct:.2f}%",
            f"{t.notional:.2f}",
            f"{t.gross:.2f}",
            f"{t.net:.2f}",
            f"{t.entry_fee:.4f}",
            f"{t.exit_fee:.4f}",
            t.reason,
            t.bars_held,
            t.bars_held * 5,
            f"{t.cap_after:.2f}"
        ])
    csv_content = output.getvalue()
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=mega22_trades.csv"}
    )

@app.post("/api/action/pause")
async def pause_bot():
    bot.pause_trading()
    return JSONResponse(content={"status": "ok", "is_paused": True})

@app.post("/api/action/resume")
async def resume_bot():
    bot.resume_trading()
    return JSONResponse(content={"status": "ok", "is_paused": False})

@app.post("/api/action/emergency_close")
async def emergency_close():
    closed = bot.emergency_close_all()
    return JSONResponse(content={"status": "ok", "closed": closed})

@app.post("/api/action/reset")
async def reset_account():
    bot.reset_portfolio(INITIAL_CAPITAL)
    return JSONResponse(content={"status": "ok", "capital": INITIAL_CAPITAL})

@app.post("/api/action/close/{symbol}")
async def close_position(symbol: str):
    success = bot.manual_close_position(symbol.upper())
    if not success:
        raise HTTPException(status_code=404, detail="Position not found")
    return JSONResponse(content={"status": "closed", "symbol": symbol.upper()})

@app.post("/api/action/test_alert")
async def test_alert():
    bot.log_event("🔔 Sound & Visual Alert Diagnostic Test triggered by operator.", "INFO")
    bot._broadcast("alert", {
        "title": "QUANT TERMINAL TEST",
        "message": "APEX Sovereign sound & alert latency diagnostic verified.",
        "level": "INFO"
    })
    return JSONResponse(content={"status": "ok"})


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>APEX Sovereign Engine | Mega-22 Institutional Terminal</title>
    <style>
        :root {
            --bg: #06080d;
            --bg-elevated: #0b101b;
            --card-bg: rgba(13, 19, 33, 0.88);
            --card-border: rgba(255, 255, 255, 0.08);
            --card-hover-border: rgba(0, 240, 144, 0.35);
            
            --accent-green: #00f090;
            --accent-green-glow: rgba(0, 240, 144, 0.28);
            --accent-red: #ff3366;
            --accent-red-glow: rgba(255, 51, 102, 0.28);
            --accent-cyan: #00d4ff;
            --accent-cyan-glow: rgba(0, 212, 255, 0.25);
            --accent-amber: #fbbf24;
            --accent-purple: #8b5cf6;
            
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --text-sub: #64748b;
            
            --font-mono: 'JetBrains Mono', 'Fira Code', 'Roboto Mono', Consolas, monospace;
            --font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Tajawal', 'Inter', sans-serif;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg);
            background-image: 
                radial-gradient(circle at 12% 12%, rgba(0, 240, 144, 0.035) 0%, transparent 45%),
                radial-gradient(circle at 88% 88%, rgba(0, 212, 255, 0.035) 0%, transparent 45%);
            color: var(--text-main);
            font-family: var(--font-ui);
            min-height: 100vh;
            padding: 14px 18px;
            overflow-x: hidden;
            font-variant-numeric: tabular-nums;
        }

        /* Hardware acceleration */
        .heatmap-card, .pos-card-hero, .kpi-card, .panel, .chart-box {
            transform: translateZ(0);
            will-change: transform;
        }

        /* Top Header Bar */
        .terminal-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 12px 20px;
            margin-bottom: 12px;
            backdrop-filter: blur(16px);
            box-shadow: 0 4px 24px rgba(0, 0, 0, 0.5);
            gap: 16px;
            flex-wrap: wrap;
        }

        .header-brand {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .brand-badge {
            background: linear-gradient(135deg, #00f090 0%, #00d4ff 100%);
            width: 40px;
            height: 40px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            font-weight: 900;
            color: #06080d;
            box-shadow: 0 0 16px var(--accent-green-glow);
        }

        .brand-text h1 {
            font-size: 1.18rem;
            font-weight: 800;
            letter-spacing: 0.5px;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .brand-text h1 span.tag {
            font-size: 0.65rem;
            background: rgba(0, 212, 255, 0.15);
            color: var(--accent-cyan);
            border: 1px solid rgba(0, 212, 255, 0.35);
            padding: 2px 7px;
            border-radius: 4px;
            font-family: var(--font-mono);
        }

        .brand-text p {
            font-size: 0.73rem;
            color: var(--text-muted);
            margin-top: 2px;
            font-family: var(--font-mono);
        }

        .header-center-status {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }

        .status-badge {
            display: flex;
            align-items: center;
            gap: 6px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--card-border);
            padding: 4px 11px;
            border-radius: 20px;
            font-size: 0.73rem;
            font-weight: 600;
            font-family: var(--font-mono);
            color: var(--text-muted);
            transition: all 0.2s;
        }

        .pulse-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            background: var(--accent-green);
            animation: pulseGlow 1.6s infinite;
        }

        @keyframes pulseGlow {
            0% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(0, 240, 144, 0.7); }
            70% { transform: scale(1.15); box-shadow: 0 0 0 7px rgba(0, 240, 144, 0); }
            100% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(0, 240, 144, 0); }
        }

        .pulse-danger {
            background: var(--accent-red) !important;
            animation: pulseRedGlow 1.2s infinite !important;
        }
        @keyframes pulseRedGlow {
            0% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(255, 51, 102, 0.7); }
            70% { transform: scale(1.15); box-shadow: 0 0 0 7px rgba(255, 51, 102, 0); }
            100% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(255, 51, 102, 0); }
        }

        /* Header Quick Actions */
        .header-actions {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .btn-action {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--card-border);
            color: var(--text-main);
            padding: 5px 12px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 0.74rem;
            font-weight: 600;
            font-family: var(--font-mono);
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 5px;
        }
        .btn-action:hover {
            background: rgba(255, 255, 255, 0.08);
            border-color: rgba(255, 255, 255, 0.2);
            transform: translateY(-1px);
        }

        .btn-pause {
            background: rgba(251, 191, 36, 0.12);
            border-color: rgba(251, 191, 36, 0.35);
            color: #fbbf24;
        }
        .btn-pause:hover {
            background: rgba(251, 191, 36, 0.25);
            box-shadow: 0 0 10px rgba(251, 191, 36, 0.25);
        }

        .btn-emergency {
            background: rgba(255, 51, 102, 0.12);
            border-color: rgba(255, 51, 102, 0.35);
            color: #ff3366;
        }
        .btn-emergency:hover {
            background: rgba(255, 51, 102, 0.28);
            box-shadow: 0 0 10px var(--accent-red-glow);
        }

        .btn-csv {
            background: rgba(0, 212, 255, 0.12);
            border-color: rgba(0, 212, 255, 0.35);
            color: var(--accent-cyan);
        }
        .btn-csv:hover {
            background: rgba(0, 212, 255, 0.25);
            box-shadow: 0 0 10px var(--accent-cyan-glow);
        }

        /* Top 6 KPI Metric Cards Strip */
        .kpi-strip {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 10px;
            margin-bottom: 12px;
        }

        .kpi-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 12px 14px;
            backdrop-filter: blur(12px);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
            overflow: hidden;
            transition: all 0.2s;
        }
        .kpi-card:hover {
            border-color: rgba(255, 255, 255, 0.18);
            transform: translateY(-1px);
        }

        .kpi-card::before {
            content: '';
            position: absolute;
            top: 0;
            right: 0;
            width: 100%;
            height: 2px;
            background: linear-gradient(90deg, var(--accent-green), transparent);
            opacity: 0.8;
        }
        .kpi-card.cyan::before { background: linear-gradient(90deg, var(--accent-cyan), transparent); }
        .kpi-card.amber::before { background: linear-gradient(90deg, var(--accent-amber), transparent); }
        .kpi-card.red::before { background: linear-gradient(90deg, var(--accent-red), transparent); }
        .kpi-card.purple::before { background: linear-gradient(90deg, var(--accent-purple), transparent); }

        .kpi-title {
            font-size: 0.7rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .kpi-val {
            font-size: 1.45rem;
            font-weight: 800;
            font-family: var(--font-mono);
            color: #fff;
            margin: 4px 0;
        }

        .kpi-sub {
            font-size: 0.69rem;
            color: var(--text-muted);
            font-family: var(--font-mono);
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .text-green { color: var(--accent-green) !important; }
        .text-red { color: var(--accent-red) !important; }
        .text-cyan { color: var(--accent-cyan) !important; }
        .text-amber { color: var(--accent-amber) !important; }

        /* Navigation Tab Bar */
        .terminal-nav {
            display: flex;
            gap: 6px;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 10px;
            padding: 6px;
            margin-bottom: 12px;
            overflow-x: auto;
        }
        .terminal-nav::-webkit-scrollbar { height: 3px; }
        .terminal-nav::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.1); border-radius: 3px; }

        .tab-btn {
            background: transparent;
            border: 1px solid transparent;
            color: var(--text-muted);
            padding: 7px 14px;
            border-radius: 7px;
            font-size: 0.78rem;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
            white-space: nowrap;
            display: flex;
            align-items: center;
            gap: 7px;
            font-family: var(--font-ui);
        }
        .tab-btn:hover {
            color: #fff;
            background: rgba(255, 255, 255, 0.04);
        }
        .tab-btn.active {
            background: rgba(0, 240, 144, 0.12);
            border-color: rgba(0, 240, 144, 0.3);
            color: var(--accent-green);
        }

        /* Tab Content Panes */
        .tab-content {
            display: none;
            animation: fadeIn 0.22s ease-in-out;
        }
        .tab-content.active {
            display: block;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(3px); }
            to { opacity: 1; transform: translateY(0); }
        }

        .panel {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 16px;
            backdrop-filter: blur(14px);
            margin-bottom: 12px;
        }

        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 10px;
            margin-bottom: 12px;
        }

        .panel-title {
            font-size: 0.92rem;
            font-weight: 700;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* Sub-Second Live Tick Animation */
        @keyframes flashUp {
            0% { color: #00f090; text-shadow: 0 0 8px rgba(0, 240, 144, 0.6); }
            100% { color: inherit; text-shadow: none; }
        }
        @keyframes flashDown {
            0% { color: #ff3366; text-shadow: 0 0 8px rgba(255, 51, 102, 0.6); }
            100% { color: inherit; text-shadow: none; }
        }
        .tick-up { animation: flashUp 0.75s ease-out; }
        .tick-down { animation: flashDown 0.75s ease-out; }

        /* Filter Pills Strip */
        .filter-strip {
            display: flex;
            gap: 6px;
            align-items: center;
            flex-wrap: wrap;
        }
        .filter-pill {
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--card-border);
            color: var(--text-muted);
            padding: 4px 10px;
            border-radius: 6px;
            font-size: 0.72rem;
            cursor: pointer;
            font-family: var(--font-mono);
            transition: all 0.2s;
        }
        .filter-pill:hover {
            color: #fff;
            background: rgba(255, 255, 255, 0.07);
        }
        .filter-pill.active {
            background: rgba(0, 212, 255, 0.15);
            border-color: rgba(0, 212, 255, 0.4);
            color: var(--accent-cyan);
            font-weight: 700;
        }

        /* TAB 1: Cockpit Layout */
        .cockpit-grid {
            display: grid;
            grid-template-columns: 1.6fr 0.8fr;
            gap: 12px;
        }
        @media (max-width: 1150px) {
            .cockpit-grid { grid-template-columns: 1fr; }
        }

        .heatmap-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(135px, 1fr));
            gap: 8px;
        }

        .heatmap-card {
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 8px;
            padding: 10px 11px;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            gap: 4px;
            cursor: pointer;
            transition: all 0.2s;
            position: relative;
            overflow: hidden;
        }
        .heatmap-card:hover {
            border-color: rgba(0, 240, 144, 0.4);
            transform: scale(1.02);
            background: rgba(255, 255, 255, 0.04);
        }

        .hm-sym {
            font-size: 0.84rem;
            font-weight: 800;
            font-family: var(--font-mono);
            color: #fff;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .badge-grp {
            font-size: 0.58rem;
            padding: 1px 4px;
            border-radius: 3px;
            font-family: var(--font-mono);
        }
        .badge-grp.G-11 { background: rgba(0, 212, 255, 0.18); color: var(--accent-cyan); border: 1px solid rgba(0, 212, 255, 0.3); }
        .badge-grp.T-11 { background: rgba(251, 191, 36, 0.18); color: var(--accent-amber); border: 1px solid rgba(251, 191, 36, 0.3); }

        .hm-price {
            font-size: 0.94rem;
            font-weight: 800;
            font-family: var(--font-mono);
            color: #f1f5f9;
            padding: 1px 3px;
            border-radius: 4px;
            display: inline-block;
        }

        .hm-chg-pill {
            font-size: 0.66rem;
            font-weight: 700;
            font-family: var(--font-mono);
            padding: 1px 5px;
            border-radius: 4px;
            display: inline-block;
        }
        .hm-chg-pill.pos { background: rgba(0, 240, 144, 0.18); color: var(--accent-green); }
        .hm-chg-pill.neg { background: rgba(255, 51, 102, 0.18); color: var(--accent-red); }

        .hm-l2-depth {
            font-size: 0.62rem;
            color: var(--text-sub);
            font-family: var(--font-mono);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .hm-meta {
            font-size: 0.62rem;
            color: var(--text-sub);
            font-family: var(--font-mono);
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-top: 1px solid rgba(255, 255, 255, 0.04);
            padding-top: 4px;
            margin-top: 2px;
        }

        /* Top 3 Opportunities Radar */
        .radar-list {
            display: flex;
            flex-direction: column;
            gap: 8px;
            margin-top: 10px;
        }

        .radar-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid rgba(255, 255, 255, 0.06);
            border-radius: 8px;
            padding: 9px 12px;
            font-family: var(--font-mono);
            transition: all 0.2s;
        }
        .radar-item:hover {
            border-color: rgba(0, 212, 255, 0.3);
            background: rgba(255, 255, 255, 0.04);
        }

        /* TAB 2: Active Positions */
        .positions-matrix-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(340px, 1fr));
            gap: 12px;
        }

        .pos-card-hero {
            background: rgba(16, 24, 40, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-right: 4px solid var(--accent-green);
            border-radius: 10px;
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 10px;
            box-shadow: 0 4px 18px rgba(0, 0, 0, 0.4);
        }

        .pos-head {
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .pos-sym-title {
            font-size: 1.25rem;
            font-weight: 800;
            font-family: var(--font-mono);
            color: #fff;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .pos-pnl-headline {
            text-align: left;
            font-family: var(--font-mono);
        }
        .pos-pnl-usd {
            font-size: 1.35rem;
            font-weight: 800;
        }
        .pos-pnl-pct {
            font-size: 0.8rem;
            font-weight: 700;
        }

        .pos-details-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 6px;
            font-size: 0.74rem;
            font-family: var(--font-mono);
            color: var(--text-muted);
            background: rgba(0, 0, 0, 0.25);
            padding: 8px 10px;
            border-radius: 6px;
        }

        /* Dynamic SL/TP Progress Bar */
        .pos-progress-wrap {
            width: 100%;
            margin-top: 4px;
        }
        .pos-progress-labels {
            display: flex;
            justify-content: space-between;
            font-size: 0.65rem;
            color: var(--text-muted);
            font-family: var(--font-mono);
            margin-bottom: 3px;
        }
        .pos-progress-track {
            position: relative;
            width: 100%;
            height: 8px;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 4px;
            overflow: hidden;
        }
        .pos-progress-fill {
            position: absolute;
            top: 0;
            bottom: 0;
            border-radius: 4px;
            transition: all 0.2s;
        }
        .pos-progress-fill.green { background: linear-gradient(90deg, #059669, #00f090); }
        .pos-progress-fill.red { background: linear-gradient(90deg, #ff3366, #dc2626); }
        .pos-zero-line {
            position: absolute;
            top: 0;
            bottom: 0;
            left: 25.3%; /* -2.2% SL to +6.5% TP */
            width: 2px;
            background: rgba(255, 255, 255, 0.5);
            z-index: 2;
        }

        /* TAB 3: Equity & Analytics */
        .analytics-grid {
            display: grid;
            grid-template-columns: 1.45fr 0.95fr;
            gap: 12px;
        }
        @media (max-width: 1100px) {
            .analytics-grid { grid-template-columns: 1fr; }
        }

        .chart-box {
            height: 260px;
            position: relative;
            width: 100%;
        }
        #equityCanvas {
            width: 100%;
            height: 100%;
            display: block;
        }

        .risk-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.74rem;
            font-family: var(--font-mono);
        }
        .risk-table td {
            padding: 6px 8px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        }
        .risk-table td.label { color: var(--text-muted); }
        .risk-table td.val { text-align: left; font-weight: 700; color: #fff; }

        /* TAB 4: Dedicated Hawkes Volatility Radar */
        .hawkes-top-grid {
            display: grid;
            grid-template-columns: 1fr 1.6fr;
            gap: 12px;
            margin-bottom: 12px;
        }
        @media (max-width: 1100px) {
            .hawkes-top-grid { grid-template-columns: 1fr; }
        }

        .gauge-container {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            position: relative;
            padding: 10px 0;
        }
        #hawkesGaugeCanvas {
            width: 100%;
            max-width: 320px;
            height: 150px;
            display: block;
        }
        .hawkes-status-box {
            text-align: center;
            margin-top: 6px;
            font-family: var(--font-mono);
        }

        #hawkesHistoryCanvas {
            width: 100%;
            height: 190px;
            display: block;
        }

        /* TAB 5 & 6: Quant Tables */
        .table-responsive {
            max-height: 520px;
            overflow-y: auto;
            border: 1px solid var(--card-border);
            border-radius: 8px;
        }
        .table-responsive::-webkit-scrollbar { width: 4px; height: 4px; }
        .table-responsive::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.15); border-radius: 4px; }

        table.quant-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.74rem;
            text-align: right;
        }
        table.quant-table th {
            color: var(--text-muted);
            font-weight: 600;
            padding: 9px 10px;
            border-bottom: 1px solid var(--card-border);
            position: sticky;
            top: 0;
            background: #0d1321;
            z-index: 2;
            font-family: var(--font-ui);
        }
        table.quant-table td {
            padding: 8px 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03);
            font-family: var(--font-mono);
            color: #e2e8f0;
        }
        table.quant-table tr:hover td {
            background: rgba(255, 255, 255, 0.025);
        }

        .badge-status {
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.65rem;
            font-weight: 700;
            display: inline-block;
        }
        .badge-status.TRIGGERED { background: rgba(0, 240, 144, 0.18); color: var(--accent-green); }
        .badge-status.SCANNING { background: rgba(148, 163, 184, 0.15); color: #94a3b8; }
        .badge-status.COOLDOWN { background: rgba(251, 191, 36, 0.18); color: var(--accent-amber); }
        .badge-status.POSITION_OPEN { background: rgba(0, 212, 255, 0.18); color: var(--accent-cyan); }

        .table-controls {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
            gap: 10px;
            flex-wrap: wrap;
        }
        .input-search {
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--card-border);
            color: #fff;
            padding: 5px 10px;
            border-radius: 6px;
            font-size: 0.74rem;
            font-family: var(--font-mono);
            outline: none;
            width: 200px;
        }
        .input-search:focus {
            border-color: var(--accent-cyan);
        }

        /* TAB 7: Console Feed */
        .console-feed {
            background: #040609;
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 12px;
            font-family: var(--font-mono);
            font-size: 0.72rem;
            height: 480px;
            overflow-y: auto;
            color: #94a3b8;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .console-feed::-webkit-scrollbar { width: 4px; }
        .console-feed::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.15); border-radius: 4px; }

        .log-entry { display: flex; gap: 8px; line-height: 1.4; }
        .log-t { color: #64748b; }
        .log-lvl-INFO { color: #38bdf8; }
        .log-lvl-WARNING { color: #fbbf24; }
        .log-lvl-ERROR { color: #f87171; }
        .log-lvl-TRADE { color: #00f090; font-weight: 700; }
        .log-txt { color: #e2e8f0; }

        /* Notification Banner Modal */
        #alert-banner {
            position: fixed;
            bottom: 20px;
            left: 20px;
            background: #0e1526;
            border: 1px solid var(--accent-green);
            color: #fff;
            padding: 12px 18px;
            border-radius: 8px;
            box-shadow: 0 8px 30px rgba(0, 0, 0, 0.6);
            z-index: 9999;
            display: none;
            font-family: var(--font-mono);
            font-size: 0.8rem;
            max-width: 380px;
            animation: slideIn 0.3s ease-out;
        }
        /* 📱 Mobile Phone & Tablet Optimization (Screens <= 768px) */
        @media (max-width: 768px) {
            header {
                flex-direction: column;
                align-items: stretch;
                gap: 10px;
                padding: 10px 12px;
            }
            .header-controls {
                flex-wrap: wrap;
                justify-content: space-between;
            }
            .kpi-row {
                grid-template-columns: repeat(2, 1fr) !important;
                gap: 8px;
            }
            .nav-tabs {
                overflow-x: auto;
                white-space: nowrap;
                padding-bottom: 4px;
                -webkit-overflow-scrolling: touch;
            }
            .nav-tab {
                padding: 7px 12px;
                font-size: 0.75rem;
                flex-shrink: 0;
            }
            .cockpit-grid {
                grid-template-columns: 1fr !important;
            }
            .table-container {
                overflow-x: auto;
                -webkit-overflow-scrolling: touch;
            }
            .heatmap-grid {
                grid-template-columns: repeat(2, 1fr);
            }
            .analytics-grid {
                grid-template-columns: 1fr !important;
            }
            #alert-banner {
                left: 10px;
                right: 10px;
                bottom: 10px;
                max-width: none;
            }
        }
    </style>
</head>
<body>

    <!-- Notification Toast Banner -->
    <div id="alert-banner">
        <div id="alert-banner-title" style="font-weight: 800; color: var(--accent-green); margin-bottom: 2px;">⚡ QUANT ALERT</div>
        <div id="alert-banner-msg">Apex Sovereign Engine Notification</div>
    </div>

    <!-- Top Institutional Header -->
    <header class="terminal-header">
        <div class="header-brand">
            <div class="brand-badge">⚡</div>
            <div class="brand-text">
                <h1>
                    APEX SOVEREIGN QUANTITATIVE ENGINE
                    <span class="tag">MEGA-22 SPOT</span>
                </h1>
                <p>Golden-11 ∪ Titan-11 (22 Pairs) | 100% Halal Cash 1x | Binance Sub-Second L2 Order Flow</p>
            </div>
        </div>

        <div class="header-center-status">
            <div class="status-badge" id="badge-ws">
                <span class="pulse-dot" id="ws-pulse"></span>
                <span id="ws-text">جاري الاتصال بـ Binance...</span>
            </div>
            <div class="status-badge" id="badge-ping" title="WebSocket Round-Trip Latency">
                <span>⚡</span>
                <span id="ping-text">-- ms</span>
            </div>
            <div class="status-badge" id="badge-hawkes" title="BTC Hawkes Cascade Shock Shield">
                <span id="hawkes-icon">🛡️</span>
                <span id="hawkes-text">هوكس: --</span>
            </div>
            <div class="status-badge" id="badge-bot-mode">
                <span id="bot-mode-icon">🟢</span>
                <span id="bot-mode-text">نشط (ACTIVE)</span>
            </div>
            <div class="status-badge" id="badge-audio" style="cursor: pointer;" onclick="toggleAudio()" title="نظام التنبيهات الصوتية الحسابية">
                <span id="audio-icon">🔊</span>
                <span id="audio-text">صوت: مفعل</span>
            </div>
        </div>

        <div class="header-actions">
            <button class="btn-action btn-pause" id="btn-toggle-pause" onclick="togglePauseBot()">⏸️ إيقاف مؤقت</button>
            <button class="btn-action btn-emergency" onclick="emergencyCloseAll()">🚨 إغلاق كل الصفقات</button>
            <button class="btn-action" onclick="resetPortfolio()">🔄 تصفير المحفظة</button>
            <button class="btn-action" onclick="testSoundAlert()">🔔 اختبار التنبيه</button>
            <button class="btn-action btn-csv" onclick="downloadTradesCSV()">📥 تصدير CSV</button>
        </div>
    </header>

    <!-- Top KPI Metrics Strip (6 Institutional Metric Cards) -->
    <section class="kpi-strip">
        <div class="kpi-card cyan">
            <div class="kpi-title">
                <span>💎 إجمالي الرصيد (Equity)</span>
                <span>MTM</span>
            </div>
            <div class="kpi-val" id="val-equity">$1,000.00</div>
            <div class="kpi-sub" id="val-roe">العائد الصافي: +0.00% ROE</div>
        </div>

        <div class="kpi-card green">
            <div class="kpi-title">
                <span>💵 السيولة النقدية (Cash)</span>
                <span id="val-slots">0 / 3 خانات</span>
            </div>
            <div class="kpi-val" id="val-cash">$1,000.00</div>
            <div class="kpi-sub" id="val-slot-sub">حصة الخانة: 32% من النقد</div>
        </div>

        <div class="kpi-card">
            <div class="kpi-title">
                <span>📈 الأرباح الصافية (Net PnL)</span>
                <span>Sharpe</span>
            </div>
            <div class="kpi-val" id="val-net-profit">+$0.00</div>
            <div class="kpi-sub" id="val-sharpe">معامل شارب: 0.00 | المحقق: +$0.00</div>
        </div>

        <div class="kpi-card amber">
            <div class="kpi-title">
                <span>🎯 نسبة الفوز (Win Rate)</span>
                <span>PF</span>
            </div>
            <div class="kpi-val" id="val-win-rate">0.0%</div>
            <div class="kpi-sub" id="val-pf">معامل الربح: 0.00 | 0 رابحة / 0 خاسرة</div>
        </div>

        <div class="kpi-card red">
            <div class="kpi-title">
                <span>📉 أقصى تراجع (Max DD)</span>
                <span>المدة</span>
            </div>
            <div class="kpi-val" id="val-max-dd">0.0%</div>
            <div class="kpi-sub" id="val-duration">متوسط المدة: -- دقيقة</div>
        </div>

        <div class="kpi-card purple">
            <div class="kpi-title">
                <span>🛡️ سعر درع البيتكوين (BTC)</span>
                <span id="btc-gate-badge">آمن 🟢</span>
            </div>
            <div class="kpi-val" id="val-btc-price">$0.00</div>
            <div class="kpi-sub" id="val-btc-sub">هوكس: 0.0000 | 24h: +0.0%</div>
        </div>
    </section>

    <!-- Navigation Tabs Strip -->
    <nav class="terminal-nav">
        <button class="tab-btn active" data-tab="tab-cockpit" onclick="switchTab('tab-cockpit')">🌐 مقصورة الرادار والخريطة الحرارية (Cockpit & Heatmap)</button>
        <button class="tab-btn" data-tab="tab-positions" onclick="switchTab('tab-positions')">🚀 مصفوفة الصفقات النشطة (Active Execution Matrix)</button>
        <button class="tab-btn" data-tab="tab-analytics" onclick="switchTab('tab-analytics')">📊 تحليلات الرصيد وإدارة المخاطر (Equity & Risk Analytics)</button>
        <button class="tab-btn" data-tab="tab-hawkes" onclick="switchTab('tab-hawkes')">🛡️ رادار تقلبات هوكس ومقياس الشدة (Hawkes Volatility Radar)</button>
        <button class="tab-btn" data-tab="tab-matrix" onclick="switchTab('tab-matrix')">🔬 مصفوفة الألفا للـ 22 عملة (Cross-Sectional Alpha)</button>
        <button class="tab-btn" data-tab="tab-ledger" onclick="switchTab('tab-ledger')">📜 سجل الصفقات المغلقة (Execution Ledger)</button>
        <button class="tab-btn" data-tab="tab-console" onclick="switchTab('tab-console')">🖥️ سجل الأحداث الحي (Quantitative Console)</button>
    </nav>

    <!-- TAB 1: Cockpit & Heatmap -->
    <div class="tab-content active" id="tab-cockpit">
        <div class="cockpit-grid">
            <!-- Left: 22-Coin Real-Time Market Heatmap -->
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>🔥 الخريطة الحرارية اللحظية للـ 22 عملة (Sub-Second Market Heatmap)</span>
                    </div>
                    <div class="filter-strip">
                        <span class="filter-pill active" onclick="setHeatmapFilter('all', this)">الكل (22)</span>
                        <span class="filter-pill" onclick="setHeatmapFilter('GOLDEN_11', this)">⚡ Golden-11</span>
                        <span class="filter-pill" onclick="setHeatmapFilter('TITAN_11', this)">🏛️ Titan-11</span>
                        <span class="filter-pill" onclick="setHeatmapFilter('pos', this)">🟢 صفقات نشطة</span>
                        <span class="filter-pill" onclick="setHeatmapFilter('triggered', this)">🚀 إشارات انفجار</span>
                    </div>
                </div>
                <div class="heatmap-grid" id="heatmap-container">
                    <!-- Dynamic 22 coin tiles rendered by JS -->
                </div>
            </div>

            <!-- Right: Mini Shield Monitor & Whale Alpha Radar -->
            <div style="display: flex; flex-direction: column; gap: 12px;">
                <div class="panel">
                    <div class="panel-header">
                        <div class="panel-title">
                            <span>🛡️ درع شلالات هوكس (BTC Hawkes Shield)</span>
                        </div>
                        <span style="font-size: 0.68rem; font-family: var(--font-mono); color: var(--text-muted);">عتبة الخطر: 0.035</span>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 8px; font-family: var(--font-mono); font-size: 0.74rem;">
                        <div style="display: flex; justify-content: space-between; padding: 6px 8px; background: rgba(255,255,255,0.02); border-radius: 6px;">
                            <span style="color: var(--text-muted);">شدة الصدمات اللحظية:</span>
                            <span id="mini-hawkes-val" style="font-weight: 800;" class="text-green">0.0000</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; padding: 6px 8px; background: rgba(255,255,255,0.02); border-radius: 6px;">
                            <span style="color: var(--text-muted);">حالة البوابة الاحترازية:</span>
                            <span id="mini-hawkes-gate" style="font-weight: 800;" class="text-green">مفتوحة (النطاق آمن) 🟢</span>
                        </div>
                        <div style="display: flex; justify-content: space-between; padding: 6px 8px; background: rgba(255,255,255,0.02); border-radius: 6px;">
                            <span style="color: var(--text-muted);">اتجاه البيتكوين (24h / 4h):</span>
                            <span id="mini-btc-trend" style="color: #fff;">+0.0% / +0.0%</span>
                        </div>
                        <button class="btn-action" style="justify-content: center; margin-top: 4px;" onclick="switchTab('tab-hawkes')">
                            📊 فتح رادار هوكس المتقدم ومخطط المسار الزمني
                        </button>
                    </div>
                </div>

                <div class="panel" style="flex: 1;">
                    <div class="panel-header">
                        <div class="panel-title">
                            <span>🎯 قمة فرص الألفا الحسابية (Top Alpha Radar)</span>
                        </div>
                        <span style="font-size: 0.68rem; color: var(--text-muted);">فيشر + وايكوف</span>
                    </div>
                    <div class="radar-list" id="top-radar-list">
                        <!-- Top 3 coins rendered by JS -->
                    </div>
                </div>
            </div>
        </div>
    </div>

    <!-- TAB 2: Active Positions & Execution Matrix -->
    <div class="tab-content" id="tab-positions">
        <div class="panel">
            <div class="panel-header">
                <div class="panel-title">
                    <span>🚀 الصفقات المفتوحة قيد التنفيذ (Active Institutional Positions)</span>
                </div>
                <div style="display: flex; gap: 12px; align-items: center; font-size: 0.72rem; font-family: var(--font-mono);">
                    <span id="pos-matrix-count">0 / 3 خانات مستخدمة</span>
                    <button class="btn-action btn-emergency" onclick="emergencyCloseAll()">🚨 تصفية الكل بأمر سوق</button>
                </div>
            </div>
            <div class="positions-matrix-grid" id="positions-matrix-container">
                <!-- Position cards rendered by JS -->
            </div>
        </div>
    </div>

    <!-- TAB 3: Equity & Risk Analytics -->
    <div class="tab-content" id="tab-analytics">
        <div class="analytics-grid">
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>📈 منحنى نمو الرصيد الفعلي (Mark-to-Market Equity Curve)</span>
                    </div>
                    <div style="display: flex; gap: 10px; font-size: 0.7rem; font-family: var(--font-mono);">
                        <span style="color: var(--accent-green);">● الرصيد اللحظي</span>
                        <span style="color: #64748b;">--- الأساس $1,000</span>
                    </div>
                </div>
                <div class="chart-box">
                    <canvas id="equityCanvas"></canvas>
                </div>
            </div>

            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>📊 مصفوفة المخاطر والأداء الكمي (Institutional Risk Matrix)</span>
                    </div>
                </div>
                <div style="display: flex; gap: 14px; align-items: center; margin-bottom: 12px;">
                    <canvas id="winLossCanvas" width="150" height="150" style="display: block;"></canvas>
                    <div style="flex: 1;">
                        <table class="risk-table">
                            <tr><td class="label">معامل شارب السنوي (Sharpe):</td><td class="val text-cyan" id="m-sharpe">0.00</td></tr>
                            <tr><td class="label">معامل الربحية (Profit Factor):</td><td class="val text-green" id="m-pf">0.00</td></tr>
                            <tr><td class="label">معامل الاسترداد (Recovery Factor):</td><td class="val" id="m-rec">0.00</td></tr>
                            <tr><td class="label">إجمالي الأرباح المحققة:</td><td class="val text-green" id="m-gross-win">+$0.00</td></tr>
                            <tr><td class="label">إجمالي الخسائر المحققة:</td><td class="val text-red" id="m-gross-loss">-$0.00</td></tr>
                        </table>
                    </div>
                </div>
                <table class="risk-table">
                    <tr><td class="label">معدل الربح / الخسارة (Payoff Ratio):</td><td class="val" id="m-payoff">0.00</td></tr>
                    <tr><td class="label">متوسط الربح المتوقع (Expectancy):</td><td class="val text-green" id="m-exp">+$0.00 (+0.0%)</td></tr>
                    <tr><td class="label">أقصى تراجع محقق (Max Drawdown):</td><td class="val text-red" id="m-dd">0.0%</td></tr>
                    <tr><td class="label">متوسط مدة بقاء الصفقة:</td><td class="val" id="m-duration">0 شمعة (0 دقيقة)</td></tr>
                    <tr><td class="label">أطول سلسلة متتالية (فوز / خسارة):</td><td class="val" id="m-streaks">0W / 0L</td></tr>
                </table>
            </div>
        </div>
    </div>

    <!-- TAB 4: Dedicated Hawkes Volatility Radar & Intensity Gauge -->
    <div class="tab-content" id="tab-hawkes">
        <div class="hawkes-top-grid">
            <!-- Left: Large Arc Gauge -->
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>🛡️ مقياس شدة قفزات هوكس اللحظي (Hawkes Jump-Diffusion Gauge)</span>
                    </div>
                    <span style="font-size: 0.68rem; font-family: var(--font-mono); color: #ff3366;">عتبة الخطر: 0.035</span>
                </div>
                <div class="gauge-container">
                    <canvas id="hawkesGaugeCanvas"></canvas>
                    <div class="hawkes-status-box">
                        <div style="font-size: 1.25rem; font-weight: 800;" id="hawkes-gauge-val">0.0000</div>
                        <div style="font-size: 0.74rem; color: var(--text-muted); margin-top: 2px;" id="hawkes-gauge-desc">الشدة الذاتية لشلالات السيولة في النطاق الآمن</div>
                    </div>
                </div>
            </div>

            <!-- Right: Rolling 60-Bar Hawkes Trajectory Line Chart -->
            <div class="panel">
                <div class="panel-header">
                    <div class="panel-title">
                        <span>📉 مسار شدة هوكس عبر آخر 60 شمعة (Hawkes Cascade Trajectory History)</span>
                    </div>
                    <div style="display: flex; gap: 10px; font-size: 0.7rem; font-family: var(--font-mono);">
                        <span style="color: var(--accent-green);">● منحنى الشدة</span>
                        <span style="color: #ff3366;">--- عتبة الصدمة 0.035</span>
                    </div>
                </div>
                <div style="height: 190px; position: relative;">
                    <canvas id="hawkesHistoryCanvas"></canvas>
                </div>
            </div>
        </div>

        <!-- Bottom: Cross-Sectional Shock Sensitivity Matrix -->
        <div class="panel">
            <div class="panel-header">
                <div class="panel-title">
                    <span>🔬 مصفوفة حساسية الـ 22 عملة لشلالات البيتكوين (Cross-Sectional Shock Transmission)</span>
                </div>
                <span style="font-size: 0.7rem; color: var(--text-muted); font-family: var(--font-mono);">Transfer Entropy + Kyle Impact + OFI</span>
            </div>
            <div class="table-responsive">
                <table class="quant-table">
                    <thead>
                        <tr>
                            <th>العملة (Symbol)</th>
                            <th>المجموعة</th>
                            <th>انتقال المعلومات من BTC (TE Proxy)</th>
                            <th>مرونة صدمة كايل (Kyle Z)</th>
                            <th>عدم توازن الأوامر (OFI)</th>
                            <th>قوة الألفا اللحظية</th>
                            <th>حالة درع هوكس</th>
                        </tr>
                    </thead>
                    <tbody id="hawkes-matrix-tbody">
                        <tr><td colspan="7" style="text-align: center; color: var(--text-muted); padding: 20px;">جاري تحميل مصفوفة الحساسية الكمية...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- TAB 5: Mega-22 Cross-Sectional Alpha Matrix -->
    <div class="tab-content" id="tab-matrix">
        <div class="panel">
            <div class="panel-header">
                <div class="panel-title">
                    <span>🔬 مصفوفة الألفا للـ 22 عملة (Cross-Sectional Alpha & Level-2 Radar)</span>
                </div>
                <div class="table-controls">
                    <input type="text" class="input-search" id="matrix-search" placeholder="بحث بالعملة (مثال: NEAR, JUP)..." oninput="filterAlphaMatrix()">
                    <select class="input-search" id="matrix-sort" onchange="sortAlphaMatrix()" style="width: 160px;">
                        <option value="score">ترتيب: قوة الألفا ↓</option>
                        <option value="change">ترتيب: تغير 24h ↓</option>
                        <option value="price">ترتيب: السعر ↓</option>
                        <option value="volume">ترتيب: السيولة 24h ↓</option>
                        <option value="spread">ترتيب: أقل فارق سعري ↑</option>
                    </select>
                </div>
            </div>
            <div class="table-responsive">
                <table class="quant-table">
                    <thead>
                        <tr>
                            <th>العملة (Symbol)</th>
                            <th>المجموعة</th>
                            <th>السعر المباشر ($)</th>
                            <th>تغير 24h (%)</th>
                            <th>أعلى / أدنى 24h</th>
                            <th>الفارق اللحظي (Spread)</th>
                            <th>قوة الألفا (Alpha Score)</th>
                            <th>مسافة وايكوف (Motif Dist)</th>
                            <th>مصفوفة فيشر (Fisher Z)</th>
                            <th>مرونة كايل (Kyle Z)</th>
                            <th>عدم توازن الأوامر (OFI)</th>
                            <th>حجم السيولة (24h Vol)</th>
                            <th>الحالة التشغيلية</th>
                        </tr>
                    </thead>
                    <tbody id="matrix-tbody">
                        <tr><td colspan="13" style="text-align: center; color: var(--text-muted); padding: 20px;">جاري تحميل مصفوفة الألفا الحسابية...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- TAB 6: Execution Ledger (Trade History) -->
    <div class="tab-content" id="tab-ledger">
        <div class="panel">
            <div class="panel-header">
                <div class="panel-title">
                    <span>📜 سجل التنفيذ التاريخي للصفقات (Closed Trades Execution Ledger)</span>
                </div>
                <div class="table-controls">
                    <input type="text" class="input-search" id="ledger-search" placeholder="فلترة بالعملة أو سبب الخروج..." oninput="filterTradeLedger()">
                    <select class="input-search" id="ledger-filter" onchange="filterTradeLedger()" style="width: 150px;">
                        <option value="all">كل الصفقات</option>
                        <option value="win">الصفقات الرابحة 🟢</option>
                        <option value="loss">الصفقات الخاسرة 🛑</option>
                        <option value="TP">أهداف كاملة (TP)</option>
                        <option value="SL">وقف خسارة (SL)</option>
                        <option value="TRAILING">حصد القمم (Trail)</option>
                    </select>
                    <button class="btn-action btn-csv" onclick="downloadTradesCSV()">📥 تصدير سجل الصفقات (CSV)</button>
                </div>
            </div>
            <div class="table-responsive">
                <table class="quant-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>العملة</th>
                            <th>توقيت الدخول</th>
                            <th>توقيت الخروج</th>
                            <th>سعر الدخول ($)</th>
                            <th>سعر الخروج ($)</th>
                            <th>العائد الصافي (%)</th>
                            <th>الربح الصافي ($)</th>
                            <th>سبب الخروج</th>
                            <th>المدة (شموع)</th>
                            <th>الرصيد بعدها ($)</th>
                        </tr>
                    </thead>
                    <tbody id="ledger-tbody">
                        <tr><td colspan="11" style="text-align: center; color: var(--text-muted); padding: 20px;">لا توجد صفقات مغلقة بعد في هذه الجلسة.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <!-- TAB 7: Live Quantitative Console -->
    <div class="tab-content" id="tab-console">
        <div class="panel">
            <div class="panel-header">
                <div class="panel-title">
                    <span>🖥️ سجل القرارات اللحظية لمحرك التداول (Autonomous Decision Console)</span>
                </div>
                <div style="display: flex; gap: 10px; align-items: center;">
                    <label style="font-size: 0.72rem; color: var(--text-muted); display: flex; align-items: center; gap: 4px; cursor: pointer;">
                        <input type="checkbox" id="autoscroll-chk" checked> تمرير تلقائي
                    </label>
                    <button class="btn-action" onclick="clearConsole()">مسح الشاشة</button>
                </div>
            </div>
            <div class="console-feed" id="console-logs">
                <!-- Log entries inserted here -->
            </div>
        </div>
    </div>

    <script>
        /* =========================================================================
           APEX SOVEREIGN QUANTITATIVE ENGINE — REAL-TIME DASHBOARD CORE
           High-performance Vanilla JS with requestAnimationFrame batching (<0.2% CPU).
           ========================================================================= */

        let ws = null;
        let lastState = null;
        let tickers = {};
        let equityHistory = [];
        let hawkesHistory = [];
        let pingInterval = null;
        let lastPingSent = 0;
        let soundEnabled = localStorage.getItem('apex_sound') !== 'false';
        let isPausedState = false;
        let heatmapFilterMode = 'all';

        // High-frequency tick batching via requestAnimationFrame
        const pendingTicks = {};
        let isRafScheduled = false;

        // Audio System via Web Audio API (Anti-pop gain envelope)
        let audioCtx = null;
        function initAudio() {
            if (!audioCtx) {
                const AudioContext = window.AudioContext || window.webkitAudioContext;
                if (AudioContext) audioCtx = new AudioContext();
            }
            if (audioCtx && audioCtx.state === 'suspended') {
                audioCtx.resume();
            }
        }

        function playTone(freq, type, duration, delay = 0) {
            if (!soundEnabled) return;
            try {
                initAudio();
                if (!audioCtx) return;
                const osc = audioCtx.createOscillator();
                const gain = audioCtx.createGain();
                osc.type = type || 'sine';
                
                const startTime = audioCtx.currentTime + delay;
                // Anti-pop envelope: starts at 0.0001
                gain.gain.setValueAtTime(0.0001, audioCtx.currentTime);
                gain.gain.setValueAtTime(0.08, startTime);
                gain.gain.exponentialRampToValueAtTime(0.0001, startTime + duration);
                
                osc.frequency.setValueAtTime(freq, startTime);
                osc.connect(gain);
                gain.connect(audioCtx.destination);
                osc.start(startTime);
                osc.stop(startTime + duration);
            } catch (e) {}
        }

        function playEntrySound() {
            playTone(523.25, 'triangle', 0.15, 0.0);   // C5
            playTone(659.25, 'triangle', 0.25, 0.12);  // E5
        }
        function playTakeProfitSound() {
            playTone(587.33, 'triangle', 0.12, 0.0);   // D5
            playTone(783.99, 'triangle', 0.15, 0.10);  // G5
            playTone(1046.50, 'sine', 0.40, 0.22);     // C6
        }
        function playStopLossSound() {
            playTone(329.63, 'sawtooth', 0.18, 0.0);  // E4
            playTone(261.63, 'sawtooth', 0.25, 0.14); // C4
        }
        function playAlertSound() {
            playTone(880.0, 'sine', 0.12, 0.0);       // A5
            playTone(880.0, 'sine', 0.20, 0.14);
        }

        function toggleAudio() {
            soundEnabled = !soundEnabled;
            localStorage.setItem('apex_sound', soundEnabled ? 'true' : 'false');
            updateAudioBadge();
            if (soundEnabled) playAlertSound();
        }

        function updateAudioBadge() {
            const icon = document.getElementById('audio-icon');
            const txt = document.getElementById('audio-text');
            if (soundEnabled) {
                icon.innerText = '🔊';
                txt.innerText = 'صوت: مفعل';
                txt.parentElement.style.borderColor = 'rgba(0, 240, 144, 0.3)';
            } else {
                icon.innerText = '🔇';
                txt.innerText = 'صوت: مكتوم';
                txt.parentElement.style.borderColor = 'rgba(255, 51, 102, 0.3)';
            }
        }

        function showNotification(title, message, isGreen = true) {
            const banner = document.getElementById('alert-banner');
            const titleEl = document.getElementById('alert-banner-title');
            const msgEl = document.getElementById('alert-banner-msg');
            titleEl.innerText = title;
            titleEl.style.color = isGreen ? 'var(--accent-green)' : 'var(--accent-red)';
            banner.style.borderColor = isGreen ? 'var(--accent-green)' : 'var(--accent-red)';
            msgEl.innerText = message;
            banner.style.display = 'block';
            setTimeout(() => { banner.style.display = 'none'; }, 4500);
        }

        // WebSocket Connection & Auto-Reconnect
        const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/live';

        function connectWS() {
            ws = new WebSocket(wsUrl);
            ws.onopen = () => {
                document.getElementById('ws-pulse').className = 'pulse-dot';
                document.getElementById('ws-text').innerText = 'بث لحظي مباشر (Binance Spot L2)';
                document.getElementById('badge-ws').style.borderColor = 'rgba(0, 240, 144, 0.3)';
                if (pingInterval) clearInterval(pingInterval);
                pingInterval = setInterval(sendPing, 3000);
                sendPing();
            };

            ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    if (msg.type === 'state_snapshot') {
                        renderDashboard(msg.data);
                    } else if (msg.type === 'tick') {
                        queueSubsecondTick(msg.data);
                    } else if (msg.type === 'pong') {
                        const now = Date.now();
                        const rtt = now - msg.client_t;
                        document.getElementById('ping-text').innerText = `${rtt} ms`;
                    } else if (msg.type === 'log') {
                        appendConsoleLog(msg.data);
                    } else if (msg.type === 'position_opened') {
                        playEntrySound();
                        showNotification('🚀 دخول صفقة جديدة', `تم فتح شراء SPOT في ${msg.data.sym} بسعر $${formatPx(msg.data.px)}`, true);
                    } else if (msg.type === 'trade_closed') {
                        const isWin = msg.data.net > 0;
                        if (isWin) playTakeProfitSound(); else playStopLossSound();
                        showNotification(isWin ? '🎯 إغلاق رابح (+)' : '🛑 وقف خسارة (-)', `${msg.data.sym}: ${msg.data.pnl_pct > 0 ? '+' : ''}${msg.data.pnl_pct.toFixed(2)}% ($${msg.data.net.toFixed(2)}) عبر ${msg.data.reason}`, isWin);
                    } else if (msg.type === 'alert') {
                        playAlertSound();
                        showNotification(msg.data.title, msg.data.message, msg.data.level !== 'ERROR');
                    } else if (msg.type === 'status_change') {
                        isPausedState = msg.data.is_paused;
                        updatePauseButtonUI();
                    } else if (msg.type === 'reset') {
                        equityHistory = [{t: 'البداية', equity: msg.data.capital || 1000.0}];
                        drawEquityChart();
                        showNotification('🔄 تصفير المحفظة', 'تمت إعادة ضبط رصيد المحفظة إلى $1,000.00', true);
                    }
                } catch (e) {
                    console.error('WS message error:', e);
                }
            };

            ws.onclose = () => {
                document.getElementById('ws-pulse').className = 'pulse-dot pulse-danger';
                document.getElementById('ws-text').innerText = 'انقطع الاتصال، جاري الإعادة...';
                document.getElementById('badge-ws').style.borderColor = 'rgba(255, 51, 102, 0.4)';
                if (pingInterval) clearInterval(pingInterval);
                setTimeout(connectWS, 2000);
            };
        }

        function sendPing() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                lastPingSent = Date.now();
                ws.send(JSON.stringify({action: 'ping', t: lastPingSent}));
            }
        }

        // Sub-second Live Tick Batching via requestAnimationFrame
        function setElText(id, text) {
            const el = document.getElementById(id);
            if (el && el.innerText !== text) el.innerText = text;
            return el;
        }

        function setElClass(el, cls) {
            if (el && el.className !== cls) el.className = cls;
        }

        let lastServerTimeMs = 0;
        let lastServerTimeReceivedAt = 0;

        function parseEntryTimeMs(timeStr) {
            if (!timeStr) return null;
            try {
                const cleanStr = String(timeStr).replace(/(\.\d{3})\d+/, '$1').replace(/\+00:00$/, 'Z');
                let t = new Date(cleanStr).getTime();
                if (!isNaN(t)) return t;
                t = new Date(timeStr).getTime();
                if (!isNaN(t)) return t;
                const m = String(timeStr).match(/^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?/);
                if (m) {
                    const ms = m[7] ? parseInt(m[7].substring(0, 3).padEnd(3, '0'), 10) : 0;
                    return Date.UTC(parseInt(m[1],10), parseInt(m[2],10)-1, parseInt(m[3],10), parseInt(m[4],10), parseInt(m[5],10), parseInt(m[6],10), ms);
                }
            } catch (e) {}
            return null;
        }

        function calcPositionDuration(p) {
            let bars = (p.held_bars !== undefined && p.held_bars !== null && Number(p.held_bars) > 0) ? Number(p.held_bars) : (
                (p.bars_held !== undefined && p.bars_held !== null && Number(p.bars_held) > 0) ? Number(p.bars_held) : 0
            );
            let durationMin = (p.duration_min !== undefined && p.duration_min !== null && Number(p.duration_min) > 0) ? Number(p.duration_min) : (bars * 5);

            if (p.entry_time) {
                const entryMs = parseEntryTimeMs(p.entry_time);
                if (entryMs !== null) {
                    const nowMs = lastServerTimeMs ? (lastServerTimeMs + (Date.now() - lastServerTimeReceivedAt)) : Date.now();
                    const diffMs = Math.max(0, nowMs - entryMs);
                    const elapsedMins = Math.floor(diffMs / 60000);
                    if (elapsedMins > durationMin) {
                        durationMin = elapsedMins;
                    }
                    if (elapsedMins > 0) {
                        bars = Math.max(bars, Math.floor(elapsedMins / 5));
                    }
                }
            }
            if (bars === 0 && p.i !== undefined && lastState && lastState.bar_index && lastState.bar_index > p.i) {
                bars = lastState.bar_index - p.i;
                if (bars > 0 && durationMin < bars * 5) {
                    durationMin = bars * 5;
                }
            }
            if (bars === 0 && durationMin > 0) {
                bars = Math.floor(durationMin / 5);
            }
            if (durationMin === 0 && bars > 0) {
                durationMin = bars * 5;
            }

            let durText = '';
            let displayStr = '';
            if (durationMin <= 0 && bars === 0) {
                durText = '<1د';
                displayStr = '0 شمعة (<1د)';
            } else {
                const durH = Math.floor(durationMin / 60);
                const durM = durationMin % 60;
                durText = durH > 0 ? `${durH}س ${durM}د` : `${durationMin}د`;
                displayStr = `${bars} شمعة (${durText})`;
            }
            return { bars, durationMin, durText, displayStr };
        }

        function queueSubsecondTick(tick) {
            pendingTicks[tick.sym] = tick;
            if (!isRafScheduled) {
                isRafScheduled = true;
                requestAnimationFrame(flushPendingTicks);
            }
        }

        function flushPendingTicks() {
            isRafScheduled = false;
            let lastEquity = null;
            let lastNet = null;
            let lastRoe = null;
            let lastSharpe = null;
            let lastRealized = null;

            for (const sym in pendingTicks) {
                const tick = pendingTicks[sym];
                tickers[sym] = tick;

                if (tick.server_time_ms) {
                    lastServerTimeMs = tick.server_time_ms;
                    lastServerTimeReceivedAt = Date.now();
                }

                // 1. Update Heatmap Card (DOM batch)
                const hmPrice = document.getElementById('hm-px-' + sym);
                if (hmPrice) {
                    const pxStr = '$' + formatPx(tick.price);
                    if (hmPrice.innerText !== pxStr) {
                        hmPrice.innerText = pxStr;
                        if (tick.prev_price && tick.price > tick.prev_price) {
                            hmPrice.classList.remove('tick-down');
                            hmPrice.classList.add('tick-up');
                        } else if (tick.prev_price && tick.price < tick.prev_price) {
                            hmPrice.classList.remove('tick-up');
                            hmPrice.classList.add('tick-down');
                        }
                    }
                }
                const hmChg = document.getElementById('hm-chg-' + sym);
                if (hmChg) {
                    const chgStr = (tick.change_24h >= 0 ? '+' : '') + tick.change_24h.toFixed(2) + '%';
                    const chgCls = 'hm-chg-pill ' + (tick.change_24h >= 0 ? 'pos' : 'neg');
                    if (hmChg.innerText !== chgStr) hmChg.innerText = chgStr;
                    setElClass(hmChg, chgCls);
                }
                const hmSpread = document.getElementById('hm-spread-' + sym);
                if (hmSpread && tick.spread_bps !== undefined) {
                    const spStr = tick.spread_bps.toFixed(1) + ' bps';
                    if (hmSpread.innerText !== spStr) hmSpread.innerText = spStr;
                }

                // 2. Update Alpha Matrix Row Price & Spread
                const matPrice = document.getElementById('mat-px-' + sym);
                if (matPrice) {
                    const pxStr = '$' + formatPx(tick.price);
                    if (matPrice.innerText !== pxStr) {
                        matPrice.innerText = pxStr;
                        if (tick.prev_price && tick.price > tick.prev_price) {
                            matPrice.classList.remove('tick-down');
                            matPrice.classList.add('tick-up');
                        } else if (tick.prev_price && tick.price < tick.prev_price) {
                            matPrice.classList.remove('tick-up');
                            matPrice.classList.add('tick-down');
                        }
                    }
                }
                const matChg = document.getElementById('mat-chg-' + sym);
                if (matChg) {
                    const chgStr = (tick.change_24h >= 0 ? '+' : '') + tick.change_24h.toFixed(2) + '%';
                    const chgCls = tick.change_24h >= 0 ? 'text-green' : 'text-red';
                    if (matChg.innerText !== chgStr) matChg.innerText = chgStr;
                    setElClass(matChg, chgCls);
                }
                const matSpread = document.getElementById('mat-spread-' + sym);
                if (matSpread && tick.spread_bps !== undefined) {
                    const spStr = tick.spread_bps.toFixed(1) + ' bps';
                    if (matSpread.innerText !== spStr) matSpread.innerText = spStr;
                }

                // 3. Update Active Position Card if open
                if (tick.pos) {
                    updatePositionCardLive(tick.pos);
                }

                if (tick.equity !== undefined) lastEquity = tick.equity;
                if (tick.total_pnl !== undefined) lastNet = tick.total_pnl;
                else if (tick.net_profit !== undefined) lastNet = tick.net_profit;
                if (tick.total_roe_pct !== undefined) lastRoe = tick.total_roe_pct;
                else if (tick.roe_pct !== undefined) lastRoe = tick.roe_pct;
                if (tick.sharpe_ratio !== undefined && tick.sharpe_ratio !== null) lastSharpe = tick.sharpe_ratio;
                if (tick.realized_pnl !== undefined && tick.realized_pnl !== null) lastRealized = tick.realized_pnl;

                delete pendingTicks[sym];
            }

            // Update top KPI cards if changed
            if (lastEquity !== null) {
                setElText('val-equity', '$' + lastEquity.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}));
            }
            if (lastNet !== null) {
                const netEl = document.getElementById('val-net-profit');
                if (netEl) {
                    const netStr = (lastNet >= 0 ? '+$' : '-$') + Math.abs(lastNet).toFixed(2);
                    const netCls = 'kpi-val ' + (lastNet >= 0 ? 'text-green' : 'text-red');
                    if (netEl.innerText !== netStr) netEl.innerText = netStr;
                    setElClass(netEl, netCls);
                }
            }
            if (lastRoe !== null) {
                const roeEl = document.getElementById('val-roe');
                if (roeEl) {
                    const roeStr = `العائد الصافي: ${lastRoe >= 0 ? '+' : ''}${lastRoe.toFixed(2)}% ROE`;
                    const roeCls = 'kpi-sub ' + (lastRoe >= 0 ? 'text-green' : 'text-red');
                    if (roeEl.innerText !== roeStr) roeEl.innerText = roeStr;
                    setElClass(roeEl, roeCls);
                }
            }
            if (lastSharpe !== null && lastRealized !== null) {
                setElText('val-sharpe', `معامل شارب: ${lastSharpe.toFixed(2)} | المحقق: ${lastRealized >= 0 ? '+' : ''}$${lastRealized.toFixed(2)}`);
            }
        }

        function formatPx(px) {
            if (!px) return '0.00';
            if (px < 0.01) return px.toFixed(6);
            if (px < 1.0) return px.toFixed(4);
            if (px < 100.0) return px.toFixed(3);
            return px.toFixed(2);
        }

        // Render Full State Snapshot
        function renderDashboard(s) {
            lastState = s;
            isPausedState = s.is_paused || false;
            updatePauseButtonUI();

            if (s.server_time_ms) {
                lastServerTimeMs = s.server_time_ms;
                lastServerTimeReceivedAt = Date.now();
            }

            // 1. KPI Cards
            const eqVal = (s.equity !== undefined && s.equity !== null) ? s.equity : (s.capital || 1000.0);
            setElText('val-equity', '$' + eqVal.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}));
            const cashVal = (s.available_cash !== undefined && s.available_cash !== null) ? s.available_cash : 1000.0;
            setElText('val-cash', '$' + cashVal.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}));
            setElText('val-slots', `${s.used_slots || 0} / ${s.max_slots || 3} خانات`);
            
            const netVal = s.total_pnl !== undefined ? s.total_pnl : (s.net_profit !== undefined ? s.net_profit : 0.0);
            const netEl = document.getElementById('val-net-profit');
            if (netEl) {
                const netStr = (netVal >= 0 ? '+$' : '-$') + Math.abs(netVal).toFixed(2);
                const netCls = 'kpi-val ' + (netVal >= 0 ? 'text-green' : 'text-red');
                if (netEl.innerText !== netStr) netEl.innerText = netStr;
                setElClass(netEl, netCls);
            }

            const roeVal = s.total_roe_pct !== undefined ? s.total_roe_pct : (s.roe_pct !== undefined ? s.roe_pct : 0.0);
            const roeEl = document.getElementById('val-roe');
            if (roeEl) {
                const roeStr = `العائد الصافي: ${roeVal >= 0 ? '+' : ''}${roeVal.toFixed(2)}% ROE`;
                const roeCls = 'kpi-sub ' + (roeVal >= 0 ? 'text-green' : 'text-red');
                if (roeEl.innerText !== roeStr) roeEl.innerText = roeStr;
                setElClass(roeEl, roeCls);
            }

            const sharpeVal = (s.sharpe_ratio !== undefined && s.sharpe_ratio !== null) ? s.sharpe_ratio : ((s.stats && s.stats.sharpe_ratio !== undefined) ? s.stats.sharpe_ratio : 0.0);
            const realizedVal = (s.realized_pnl !== undefined && s.realized_pnl !== null) ? s.realized_pnl : ((s.stats && s.stats.net_profit !== undefined) ? s.stats.net_profit : 0.0);
            setElText('val-sharpe', `معامل شارب: ${sharpeVal.toFixed(2)} | المحقق: ${realizedVal >= 0 ? '+' : ''}$${realizedVal.toFixed(2)}`);

            setElText('val-win-rate', (s.win_rate !== undefined ? s.win_rate.toFixed(1) : '0.0') + '%');
            setElText('val-pf', `معامل الربح: ${(s.profit_factor !== undefined ? s.profit_factor.toFixed(2) : '0.00')} | ${s.winning_trades || 0} رابحة / ${s.losing_trades || 0} خاسرة`);

            setElText('val-max-dd', ((s.max_drawdown_pct || 0)).toFixed(1) + '%');
            const avgMins = s.avg_trade_duration_min || (s.stats ? s.stats.avg_trade_duration_min : 0) || 0;
            setElText('val-duration', `متوسط المدة: ${avgMins} دقيقة | ${s.total_trades || 0} صفقات`);

            if (s.btc_price !== undefined) {
                setElText('val-btc-price', '$' + s.btc_price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}));
            }
            if (s.btc_hawkes !== undefined) {
                setElText('val-btc-sub', `هوكس: ${s.btc_hawkes.toFixed(4)} | 24h: ${s.btc_24h > 0 ? '+' : ''}${(s.btc_24h || 0).toFixed(1)}%`);
            }
            
            const btcBadge = document.getElementById('btc-gate-badge');
            if (btcBadge) {
                const btcText = s.is_btc_safe ? 'آمن 🟢' : 'درع هوكس نشط 🛑';
                const btcCls = s.is_btc_safe ? 'text-green' : 'text-red';
                if (btcBadge.innerText !== btcText) btcBadge.innerText = btcText;
                setElClass(btcBadge, btcCls);
            }

            // Hawkes Badges
            const hBadgeText = document.getElementById('hawkes-text');
            if (hBadgeText && s.btc_hawkes !== undefined) {
                const hText = `هوكس: ${s.btc_hawkes.toFixed(4)} (${s.is_btc_safe ? 'آمن' : 'صدمة!'})`;
                if (hBadgeText.innerText !== hText) hBadgeText.innerText = hText;
            }
            const badgeH = document.getElementById('badge-hawkes');
            if (badgeH) {
                const borderColor = s.is_btc_safe ? 'rgba(0, 240, 144, 0.3)' : 'rgba(255, 51, 102, 0.4)';
                if (badgeH.style.borderColor !== borderColor) badgeH.style.borderColor = borderColor;
            }

            // Mini monitor in Tab 1
            const miniHVal = document.getElementById('mini-hawkes-val');
            if (miniHVal && s.btc_hawkes !== undefined) {
                const valStr = s.btc_hawkes.toFixed(4);
                const valCls = s.is_btc_safe ? 'text-green' : 'text-red';
                if (miniHVal.innerText !== valStr) miniHVal.innerText = valStr;
                setElClass(miniHVal, valCls);
            }
            const miniHGate = document.getElementById('mini-hawkes-gate');
            if (miniHGate) {
                const gateText = s.is_btc_safe ? 'مفتوحة (النطاق آمن) 🟢' : 'مغلقة (درع الصدمات مفعل) 🛑';
                const gateCls = s.is_btc_safe ? 'text-green' : 'text-red';
                if (miniHGate.innerText !== gateText) miniHGate.innerText = gateText;
                setElClass(miniHGate, gateCls);
            }
            const miniTrend = document.getElementById('mini-btc-trend');
            if (miniTrend) {
                const trendStr = `${(s.btc_24h || 0) > 0 ? '+' : ''}${(s.btc_24h || 0).toFixed(1)}% / ${(s.btc_4h || 0) > 0 ? '+' : ''}${(s.btc_4h || 0).toFixed(1)}%`;
                if (miniTrend.innerText !== trendStr) miniTrend.innerText = trendStr;
            }

            // Bot Mode Badge
            const botModeTxt = document.getElementById('bot-mode-text');
            const botModeIcon = document.getElementById('bot-mode-icon');
            const badgeMode = document.getElementById('badge-bot-mode');
            if (s.is_paused) {
                if (botModeTxt && botModeTxt.innerText !== 'متوقف مؤقتاً (PAUSED)') botModeTxt.innerText = 'متوقف مؤقتاً (PAUSED)';
                if (botModeIcon && botModeIcon.innerText !== '⏸️') botModeIcon.innerText = '⏸️';
                if (badgeMode) badgeMode.style.borderColor = 'rgba(251, 191, 36, 0.4)';
            } else {
                if (botModeTxt && botModeTxt.innerText !== 'نشط (ACTIVE)') botModeTxt.innerText = 'نشط (ACTIVE)';
                if (botModeIcon && botModeIcon.innerText !== '🟢') botModeIcon.innerText = '🟢';
                if (badgeMode) badgeMode.style.borderColor = 'rgba(0, 240, 144, 0.3)';
            }

            // 2. Render Heatmap (Tab 1)
            renderHeatmap(s.leaderboard);

            // 3. Render Top Opportunities (Tab 1)
            renderTopRadar(s.leaderboard);

            // 4. Render Active Positions (Tab 2)
            renderActivePositions(s.active_positions);

            // 5. Render Equity Chart & Risk Analytics (Tab 3)
            updateEquityHistory(s);
            renderRiskAnalytics(s);

            // 6. Render Dedicated Hawkes Radar & Trajectory (Tab 4)
            if (s.btc_hawkes_history) {
                hawkesHistory = s.btc_hawkes_history;
            }
            const hawkesTab = document.getElementById('tab-hawkes');
            if (hawkesTab && hawkesTab.classList.contains('active')) {
                drawHawkesGauge(s.btc_hawkes);
                drawHawkesTrajectory();
                renderHawkesSensitivityTable(s.leaderboard);
            }

            // 7. Render Alpha Matrix (Tab 5)
            renderAlphaMatrixTable(s.leaderboard);

            // 8. Render Trade History Ledger (Tab 6)
            renderTradeLedger(s.recent_trades || []);
        }

        // 22-Coin Heatmap Renderer with Cluster Filtering
        function setHeatmapFilter(filter, el) {
            heatmapFilterMode = filter;
            document.querySelectorAll('.filter-pill').forEach(p => p.classList.remove('active'));
            if (el) el.classList.add('active');
            if (lastState) renderHeatmap(lastState.leaderboard);
        }

        function renderHeatmapCardHtml(item) {
            const isPos = item.change_24h >= 0;
            const chgSign = isPos ? '+' : '';
            const grpClass = item.group === 'GOLDEN_11' ? 'G-11' : 'T-11';
            const grpLabel = item.group === 'GOLDEN_11' ? 'G-11' : 'T-11';
            const volM = ((item.vol_quote || 0) / 1000000.0).toFixed(1);
            const statusLabel = item.status === 'POSITION_OPEN' ? '🟢 صفقة' : (item.status === 'TRIGGERED' ? '🚀 انفجار' : item.status);

            return `
            <div class="heatmap-card" id="hm-card-${item.sym}" onclick="selectMatrixCoin('${item.sym}')">
                <div class="hm-sym">
                    <span>${item.sym.replace('USDT', '')}</span>
                    <div style="display:flex;gap:4px;align-items:center;">
                        <span class="badge-grp ${grpClass}">${grpLabel}</span>
                        <span class="hm-chg-pill ${isPos ? 'pos' : 'neg'}" id="hm-chg-${item.sym}">${chgSign}${(item.change_24h || 0).toFixed(2)}%</span>
                    </div>
                </div>
                <div class="hm-price" id="hm-px-${item.sym}">$${formatPx(item.price)}</div>
                <div class="hm-l2-depth">
                    <span>فارق: <b id="hm-spread-${item.sym}">${(item.spread_bps || 0).toFixed(1)} bps</b></span>
                    <span>حجم: $${volM}M</span>
                </div>
                <div class="hm-meta" id="hm-meta-${item.sym}">
                    <span>Alpha: <b>${item.score.toFixed(1)}</b></span>
                    <span class="badge-status ${item.status}">${statusLabel}</span>
                </div>
            </div>`;
        }

        function updateHeatmapCard(item) {
            const isPos = item.change_24h >= 0;
            const chgSign = isPos ? '+' : '';
            const pxEl = document.getElementById('hm-px-' + item.sym);
            if (pxEl) {
                const pxStr = '$' + formatPx(item.price);
                if (pxEl.innerText !== pxStr) pxEl.innerText = pxStr;
            }
            const chgEl = document.getElementById('hm-chg-' + item.sym);
            if (chgEl) {
                const chgStr = `${chgSign}${(item.change_24h || 0).toFixed(2)}%`;
                const chgCls = 'hm-chg-pill ' + (isPos ? 'pos' : 'neg');
                if (chgEl.innerText !== chgStr) chgEl.innerText = chgStr;
                setElClass(chgEl, chgCls);
            }
            const spreadEl = document.getElementById('hm-spread-' + item.sym);
            if (spreadEl && item.spread_bps !== undefined) {
                const spStr = (item.spread_bps || 0).toFixed(1) + ' bps';
                if (spreadEl.innerText !== spStr) spreadEl.innerText = spStr;
            }
            const metaEl = document.getElementById('hm-meta-' + item.sym);
            if (metaEl) {
                const statusLabel = item.status === 'POSITION_OPEN' ? '🟢 صفقة' : (item.status === 'TRIGGERED' ? '🚀 انفجار' : item.status);
                const metaHtml = `<span>Alpha: <b>${item.score.toFixed(1)}</b></span><span class="badge-status ${item.status}">${statusLabel}</span>`;
                if (metaEl.innerHTML !== metaHtml) metaEl.innerHTML = metaHtml;
            }
        }

        function renderHeatmap(leaderboard) {
            const container = document.getElementById('heatmap-container');
            if (!container) return;

            let filtered = (leaderboard || []).slice();
            if (heatmapFilterMode === 'GOLDEN_11') {
                filtered = filtered.filter(x => x.group === 'GOLDEN_11');
            } else if (heatmapFilterMode === 'TITAN_11') {
                filtered = filtered.filter(x => x.group === 'TITAN_11');
            } else if (heatmapFilterMode === 'pos') {
                filtered = filtered.filter(x => x.status === 'POSITION_OPEN');
            } else if (heatmapFilterMode === 'triggered') {
                filtered = filtered.filter(x => x.is_candidate === 1 || x.status === 'TRIGGERED');
            }

            const activeSyms = new Set(filtered.map(x => x.sym));
            // Remove cards no longer in filter
            Array.from(container.children).forEach(child => {
                const sym = child.id.replace('hm-card-', '');
                if (!activeSyms.has(sym)) child.remove();
            });

            // Update in place and maintain DOM order without destruction
            filtered.forEach(item => {
                let card = document.getElementById('hm-card-' + item.sym);
                if (!card) {
                    const temp = document.createElement('div');
                    temp.innerHTML = renderHeatmapCardHtml(item).trim();
                    if (temp.firstElementChild) {
                        container.appendChild(temp.firstElementChild);
                    }
                } else {
                    updateHeatmapCard(item);
                    container.appendChild(card); // Reorder existing DOM element smoothly
                }
            });
        }

        // Top 3 Opportunities Radar
        function renderTopRadar(leaderboard) {
            const list = document.getElementById('top-radar-list');
            if (!list) return;
            const cands = (leaderboard || []).filter(x => x.status !== 'POSITION_OPEN').slice(0, 3);
            if (cands.length === 0) {
                const emptyHtml = '<div style="color:var(--text-muted);font-size:0.75rem;text-align:center;padding:10px;">المحرك يفحص الـ 22 عملة...</div>';
                if (list.innerHTML !== emptyHtml) list.innerHTML = emptyHtml;
                return;
            }
            if (list.querySelector('.radar-item') === null) {
                list.innerHTML = '';
            }
            cands.forEach((c, i) => {
                let item = document.getElementById('radar-item-' + i);
                if (!item) {
                    item = document.createElement('div');
                    item.id = 'radar-item-' + i;
                    item.className = 'radar-item';
                    item.style.cursor = 'pointer';
                    list.appendChild(item);
                }
                item.onclick = () => selectMatrixCoin(c.sym);
                const scoreColor = c.score > 20 ? 'var(--accent-green)' : 'var(--accent-cyan)';
                const newHtml = `
                    <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-weight:800;color:var(--accent-cyan);">#${i+1}</span>
                        <span style="font-weight:800;color:#fff;">${c.sym}</span>
                        <span class="badge-status ${c.status}">${c.status}</span>
                    </div>
                    <div style="display:flex;gap:12px;align-items:center;">
                        <span style="color:var(--text-muted);">$${formatPx(c.price)}</span>
                        <span style="font-weight:800;color:${scoreColor};">Alpha: ${c.score.toFixed(1)}</span>
                    </div>
                `;
                if (item.innerHTML !== newHtml) item.innerHTML = newHtml;
            });
            while (list.children.length > cands.length) {
                list.lastElementChild.remove();
            }
        }

        // Active Positions Card Matrix (Tab 2)
        function renderPositionCardHtml(p) {
            const isPos = (p.unrealized_pnl || 0) >= 0;
            const pnlColor = isPos ? 'text-green' : 'text-red';
            const pnlSign = isPos ? '+' : '';
            const stopText = p.stop > 0 ? `وقف خسارة: -${(p.stop * 100).toFixed(1)}%` : `ربح مقفول: +${(Math.abs(p.stop) * 100).toFixed(1)}% 🔒`;
            const dur = calcPositionDuration(p);

            // Progress -2.2% SL to +6.5% TP
            const pnlProgress = Math.max(0, Math.min(100, (((p.unrealized_pnl_pct || 0) + 2.2) / 8.7) * 100));
            const fillLeft = (p.unrealized_pnl_pct || 0) >= 0 ? '25.3%' : `${pnlProgress}%`;
            const fillWidth = (p.unrealized_pnl_pct || 0) >= 0 ? `${pnlProgress - 25.3}%` : `${25.3 - pnlProgress}%`;
            const barClass = (p.unrealized_pnl_pct || 0) >= 0 ? 'green' : 'red';

            return `
            <div class="pos-card-hero" id="pos-card-${p.sym}">
                <div class="pos-head">
                    <div class="pos-sym-title">
                        <span>${p.sym}</span>
                        <span class="badge-status POSITION_OPEN">SPOT 1X CASH</span>
                        <span id="pos-trail-badge-${p.sym}">${p.trailing_active ? '<span class="badge-status TRIGGERED">حاصد القمم 🏹</span>' : ''}</span>
                    </div>
                    <div class="pos-pnl-headline">
                        <div class="pos-pnl-usd ${pnlColor}" id="pos-pnl-val-${p.sym}">${pnlSign}$${(p.unrealized_pnl || 0).toFixed(2)}</div>
                        <div class="pos-pnl-pct ${pnlColor}" id="pos-pnl-pct-${p.sym}">${pnlSign}${(p.unrealized_pnl_pct || 0).toFixed(2)}%</div>
                    </div>
                </div>

                <div class="pos-details-grid">
                    <div>سعر الدخول: <b>$${formatPx(p.px)}</b></div>
                    <div>السعر المباشر: <b id="pos-curr-px-${p.sym}">$${formatPx(p.current_px)}</b></div>
                    <div>حجم المركز: <b>$${(p.notional || 0).toFixed(2)}</b></div>
                    <div>أعلى سعر وصله: <b id="pos-high-${p.sym}">$${formatPx(p.highest_seen || p.current_px)}</b></div>
                    <div>الحماية: <b id="pos-stop-${p.sym}" style="color:${p.stop < 0 ? 'var(--accent-green)' : 'var(--accent-red)'};">${stopText}</b></div>
                    <div>المدة الحالية: <b id="pos-dur-${p.sym}">${dur.displayStr}</b></div>
                </div>

                <div class="pos-progress-wrap">
                    <div class="pos-progress-labels">
                        <span style="color:var(--accent-red);">-2.2% SL</span>
                        <span style="color:#94a3b8;">0.0% تعادل</span>
                        <span style="color:var(--accent-green);">+6.5% TP</span>
                    </div>
                    <div class="pos-progress-track">
                        <div class="pos-zero-line"></div>
                        <div class="pos-progress-fill ${barClass}" id="pos-prog-fill-${p.sym}" style="left:${fillLeft}; width:${fillWidth};"></div>
                    </div>
                </div>

                <div style="display:flex; justify-content:space-between; align-items:center; border-top:1px solid rgba(255,255,255,0.06); padding-top:8px; margin-top:4px;">
                    <span style="font-size:0.7rem; color:var(--text-sub);">توقيت الدخول: ${(p.entry_time || '').substring(11, 19)} UTC</span>
                    <button class="btn-action btn-emergency" onclick="closePosition('${p.sym}')">إغلاق يدوي للمركز</button>
                </div>
            </div>`;
        }

        function updatePositionCard(p) {
            if (!p || !p.sym) return false;
            const card = document.getElementById('pos-card-' + p.sym);
            if (!card) return false;

            const isPos = (p.unrealized_pnl || 0) >= 0;
            const sign = isPos ? '+' : '';
            const col = isPos ? 'text-green' : 'text-red';

            const pnlVal = document.getElementById('pos-pnl-val-' + p.sym);
            if (pnlVal) {
                const valStr = `${sign}$${(p.unrealized_pnl || 0).toFixed(2)}`;
                const valCls = 'pos-pnl-usd ' + col;
                if (pnlVal.innerText !== valStr) pnlVal.innerText = valStr;
                setElClass(pnlVal, valCls);
            }

            const pnlPct = document.getElementById('pos-pnl-pct-' + p.sym);
            if (pnlPct) {
                const pctStr = `${sign}${(p.unrealized_pnl_pct || 0).toFixed(2)}%`;
                const pctCls = 'pos-pnl-pct ' + col;
                if (pnlPct.innerText !== pctStr) pnlPct.innerText = pctStr;
                setElClass(pnlPct, pctCls);
            }

            const currPx = document.getElementById('pos-curr-px-' + p.sym);
            if (currPx) {
                const pxStr = '$' + formatPx(p.current_px);
                if (currPx.innerText !== pxStr) currPx.innerText = pxStr;
            }

            const highEl = document.getElementById('pos-high-' + p.sym);
            if (highEl && p.highest_seen !== undefined) {
                const highStr = '$' + formatPx(p.highest_seen);
                if (highEl.innerText !== highStr) highEl.innerText = highStr;
            }

            const stopEl = document.getElementById('pos-stop-' + p.sym);
            if (stopEl && p.stop !== undefined) {
                const stopText = p.stop > 0 ? `وقف خسارة: -${(p.stop * 100).toFixed(1)}%` : `ربح مقفول: +${(Math.abs(p.stop) * 100).toFixed(1)}% 🔒`;
                const stopColor = p.stop < 0 ? 'var(--accent-green)' : 'var(--accent-red)';
                if (stopEl.innerText !== stopText) stopEl.innerText = stopText;
                if (stopEl.style.color !== stopColor) stopEl.style.color = stopColor;
            }

            const trailBadge = document.getElementById('pos-trail-badge-' + p.sym);
            if (trailBadge) {
                const badgeHtml = p.trailing_active ? '<span class="badge-status TRIGGERED">حاصد القمم 🏹</span>' : '';
                if (trailBadge.innerHTML !== badgeHtml) trailBadge.innerHTML = badgeHtml;
            }

            const durEl = document.getElementById('pos-dur-' + p.sym);
            if (durEl) {
                const dur = calcPositionDuration(p);
                if (durEl.innerText !== dur.displayStr) durEl.innerText = dur.displayStr;
            }

            const fill = document.getElementById('pos-prog-fill-' + p.sym);
            if (fill) {
                const pnlProgress = Math.max(0, Math.min(100, (((p.unrealized_pnl_pct || 0) + 2.2) / 8.7) * 100));
                const fillLeft = (p.unrealized_pnl_pct || 0) >= 0 ? '25.3%' : `${pnlProgress}%`;
                const fillWidth = (p.unrealized_pnl_pct || 0) >= 0 ? `${pnlProgress - 25.3}%` : `${25.3 - pnlProgress}%`;
                const fillCls = 'pos-progress-fill ' + (isPos ? 'green' : 'red');
                if (fill.style.left !== fillLeft) fill.style.left = fillLeft;
                if (fill.style.width !== fillWidth) fill.style.width = fillWidth;
                setElClass(fill, fillCls);
            }
            return true;
        }

        function renderActivePositions(positions) {
            const container = document.getElementById('positions-matrix-container');
            const badgeCount = document.getElementById('pos-matrix-count');
            const posList = positions || [];
            if (badgeCount) {
                const badgeText = `${posList.length} / 3 خانات مستخدمة`;
                if (badgeCount.innerText !== badgeText) badgeCount.innerText = badgeText;
            }
            if (!container) return;

            if (posList.length === 0) {
                if (!container.querySelector('.pos-empty-placeholder')) {
                    container.innerHTML = `
                    <div class="pos-empty-placeholder" style="grid-column: 1/-1; text-align: center; padding: 40px 20px; color: var(--text-muted); border: 1px dashed rgba(255,255,255,0.08); border-radius: 10px; background: rgba(255,255,255,0.01);">
                        <div style="font-size: 1.8rem; margin-bottom: 8px;">🔍</div>
                        <div style="font-size: 0.95rem; font-weight: 700; color: #fff;">لا توجد صفقات مفتوحة حالياً</div>
                        <div style="font-size: 0.75rem; color: #64748b; margin-top: 4px;">المحرك يفحص الـ 22 عملة بانتظار استيفاء شروط وايكوف وفيشر مع التحقق من درع هوكس.</div>
                    </div>`;
                }
                return;
            }

            // Remove empty placeholder if transitioning from 0 to >0 positions
            const emptyEl = container.querySelector('.pos-empty-placeholder');
            if (emptyEl) emptyEl.remove();

            const activeSyms = new Set(posList.map(p => p.sym));
            // Remove cards for closed positions
            container.querySelectorAll('.pos-card-hero').forEach(card => {
                const cardSym = card.id.replace('pos-card-', '');
                if (!activeSyms.has(cardSym)) card.remove();
            });

            // Update existing cards in place without DOM recreation, or append new cards
            posList.forEach(p => {
                const existing = document.getElementById('pos-card-' + p.sym);
                if (existing) {
                    updatePositionCard(p);
                } else {
                    const temp = document.createElement('div');
                    temp.innerHTML = renderPositionCardHtml(p).trim();
                    if (temp.firstElementChild) {
                        container.appendChild(temp.firstElementChild);
                    }
                }
            });
        }

        function updatePositionCardLive(p) {
            updatePositionCard(p);
        }

        // Equity Curve Drawing (Tab 3)
        function updateEquityHistory(s) {
            if (equityHistory.length === 0) {
                equityHistory.push({t: 'البداية', equity: 1000.0});
                if (s.recent_trades && s.recent_trades.length > 0) {
                    s.recent_trades.forEach((t, i) => {
                        equityHistory.push({t: `${i+1}`, equity: t.cap_after || 1000.0});
                    });
                }
                equityHistory.push({t: 'الآن', equity: s.equity});
            } else {
                const knownTrades = Math.max(0, equityHistory.length - 2);
                if (s.recent_trades && s.recent_trades.length > knownTrades) {
                    const lastTrade = s.recent_trades[s.recent_trades.length - 1];
                    const livePt = equityHistory.pop();
                    equityHistory.push({t: `${s.total_trades}`, equity: lastTrade.cap_after || s.equity});
                    equityHistory.push(livePt);
                    if (equityHistory.length > 120) equityHistory.shift();
                }
                const lastIdx = equityHistory.length - 1;
                equityHistory[lastIdx] = {t: new Date().toLocaleTimeString('en-GB'), equity: s.equity};
            }
            const tab = document.getElementById('tab-analytics');
            if (tab && tab.classList.contains('active')) {
                drawEquityChart();
            }
        }

        function drawEquityChart() {
            const canvas = document.getElementById('equityCanvas');
            if (!canvas || !canvas.parentElement) return;
            const ctx = canvas.getContext('2d');
            const w = canvas.width = canvas.parentElement.clientWidth;
            const h = canvas.height = canvas.parentElement.clientHeight || 260;

            ctx.clearRect(0, 0, w, h);
            const padL = 65, padR = 25, padT = 20, padB = 25;
            const plotW = w - padL - padR;
            const plotH = h - padT - padB;

            if (equityHistory.length === 0) equityHistory.push({t: 'البداية', equity: 1000.0});
            const values = equityHistory.map(d => d.equity);
            let minVal = Math.min(...values, 990.0);
            let maxVal = Math.max(...values, 1015.0);
            const range = (maxVal - minVal) || 10.0;
            minVal = Math.floor(minVal - range * 0.08);
            maxVal = Math.ceil(maxVal + range * 0.08);

            const getY = (val) => padT + plotH - ((val - minVal) / (maxVal - minVal)) * plotH;
            const getX = (idx) => padL + (equityHistory.length > 1 ? (idx / (equityHistory.length - 1)) * plotW : plotW / 2);

            // Grid lines
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
            ctx.fillStyle = '#64748b';
            ctx.font = '10px JetBrains Mono, monospace';
            for (let i = 0; i <= 4; i++) {
                const val = minVal + (i / 4) * (maxVal - minVal);
                const y = getY(val);
                ctx.beginPath();
                ctx.moveTo(padL, y);
                ctx.lineTo(w - padR, y);
                ctx.stroke();
                ctx.fillText('$' + val.toFixed(0), 12, y + 3);
            }

            // $1000 Baseline
            const base1000Y = getY(1000.0);
            if (base1000Y >= padT && base1000Y <= padT + plotH) {
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
                ctx.setLineDash([4, 4]);
                ctx.beginPath();
                ctx.moveTo(padL, base1000Y);
                ctx.lineTo(w - padR, base1000Y);
                ctx.stroke();
                ctx.setLineDash([]);
            }

            if (equityHistory.length < 2) return;
            const lastEq = values[values.length - 1];
            const isUp = lastEq >= 1000.0;
            const strokeCol = isUp ? '#00f090' : '#ff3366';

            // Area Gradient
            const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
            grad.addColorStop(0, isUp ? 'rgba(0, 240, 144, 0.28)' : 'rgba(255, 51, 102, 0.28)');
            grad.addColorStop(1, 'rgba(0, 0, 0, 0.0)');

            ctx.beginPath();
            ctx.moveTo(getX(0), getY(values[0]));
            for (let i = 1; i < equityHistory.length; i++) {
                ctx.lineTo(getX(i), getY(values[i]));
            }
            ctx.lineTo(getX(equityHistory.length - 1), padT + plotH);
            ctx.lineTo(getX(0), padT + plotH);
            ctx.closePath();
            ctx.fillStyle = grad;
            ctx.fill();

            // Line
            ctx.shadowColor = strokeCol;
            ctx.shadowBlur = 8;
            ctx.strokeStyle = strokeCol;
            ctx.lineWidth = 2.4;
            ctx.beginPath();
            ctx.moveTo(getX(0), getY(values[0]));
            for (let i = 1; i < equityHistory.length; i++) {
                ctx.lineTo(getX(i), getY(values[i]));
            }
            ctx.stroke();
            ctx.shadowBlur = 0;

            // Last point
            const lx = getX(equityHistory.length - 1);
            const ly = getY(lastEq);
            ctx.fillStyle = strokeCol;
            ctx.beginPath();
            ctx.arc(lx, ly, 4.5, 0, Math.PI * 2);
            ctx.fill();
        }

        // Win/Loss Doughnut (Tab 3)
        function renderRiskAnalytics(s) {
            const stats = s.stats || s;
            document.getElementById('m-sharpe').innerText = (stats.sharpe_ratio || 0.0).toFixed(2);
            document.getElementById('m-pf').innerText = (stats.profit_factor || 0.0).toFixed(2);
            document.getElementById('m-rec').innerText = (stats.recovery_factor || 0.0).toFixed(2);
            document.getElementById('m-gross-win').innerText = '+$' + (stats.gross_profit || 0.0).toFixed(2);
            document.getElementById('m-gross-loss').innerText = '-$' + Math.abs(stats.gross_loss || 0.0).toFixed(2);
            const expUsd = stats.expectancy_usd || 0.0;
            const expPct = stats.expectancy_pct || 0.0;
            document.getElementById('m-exp').innerText = `${expUsd >= 0 ? '+' : '-'}$${Math.abs(expUsd).toFixed(2)} (${expPct >= 0 ? '+' : ''}${expPct.toFixed(2)}%)`;
            document.getElementById('m-dd').innerText = (stats.max_drawdown_pct || 0.0).toFixed(2) + '%';
            document.getElementById('m-duration').innerText = `${stats.avg_trade_duration_bars || 0} شمعة (${stats.avg_trade_duration_min || 0} دقيقة)`;
            document.getElementById('m-streaks').innerText = `${stats.max_consecutive_wins || 0}W متتالية / ${stats.max_consecutive_losses || 0}L متتالية`;

            drawWinLossDoughnut(stats.win_rate || 0.0, stats.winning_trades || 0, stats.losing_trades || 0);
        }

        function drawWinLossDoughnut(winRate, wins, losses) {
            const canvas = document.getElementById('winLossCanvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const w = canvas.width = 150;
            const h = canvas.height = 150;
            ctx.clearRect(0, 0, w, h);
            const cx = w / 2;
            const cy = h / 2;
            const r = 55;
            const total = wins + losses;

            ctx.beginPath();
            ctx.arc(cx, cy, r, 0, Math.PI * 2);
            ctx.lineWidth = 14;
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
            ctx.stroke();

            if (total === 0) {
                ctx.font = '700 15px JetBrains Mono, monospace';
                ctx.fillStyle = '#64748b';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText('0.0%', cx, cy);
                return;
            }

            const winAngle = (wins / total) * Math.PI * 2;
            ctx.beginPath();
            ctx.arc(cx, cy, r, -Math.PI / 2, -Math.PI / 2 + winAngle, false);
            ctx.lineWidth = 14;
            ctx.strokeStyle = '#00f090';
            ctx.stroke();

            if (losses > 0) {
                ctx.beginPath();
                ctx.arc(cx, cy, r, -Math.PI / 2 + winAngle, -Math.PI / 2 + Math.PI * 2, false);
                ctx.lineWidth = 14;
                ctx.strokeStyle = '#ff3366';
                ctx.stroke();
            }

            ctx.font = '800 17px JetBrains Mono, monospace';
            ctx.fillStyle = '#fff';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(winRate.toFixed(1) + '%', cx, cy - 6);

            ctx.font = '10px JetBrains Mono, monospace';
            ctx.fillStyle = '#94a3b8';
            ctx.fillText(`${wins}W / ${losses}L`, cx, cy + 12);
        }

        // TAB 4: Dedicated Hawkes Arc Gauge & Rolling Trajectory
        function drawHawkesGauge(intensity) {
            const canvas = document.getElementById('hawkesGaugeCanvas');
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            const w = canvas.width = canvas.parentElement.clientWidth || 300;
            const h = canvas.height = 150;

            ctx.clearRect(0, 0, w, h);
            const cx = w / 2;
            const cy = h - 22;
            const r = Math.min(cx - 24, h - 34);

            // Background Arc
            ctx.beginPath();
            ctx.arc(cx, cy, r, Math.PI, 0, false);
            ctx.lineWidth = 16;
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
            ctx.stroke();

            // Safe Zone Arc (0 to 0.035) -> 50%
            ctx.beginPath();
            ctx.arc(cx, cy, r, Math.PI, Math.PI + Math.PI * 0.5, false);
            ctx.lineWidth = 16;
            ctx.strokeStyle = 'rgba(0, 240, 144, 0.25)';
            ctx.stroke();

            // Danger Zone Arc (0.035 to 0.070)
            ctx.beginPath();
            ctx.arc(cx, cy, r, Math.PI + Math.PI * 0.5, 0, false);
            ctx.lineWidth = 16;
            ctx.strokeStyle = 'rgba(255, 51, 102, 0.35)';
            ctx.stroke();

            // 0.035 Cutoff Marker
            const thAngle = Math.PI + Math.PI * 0.5;
            const tx1 = cx + (r - 14) * Math.cos(thAngle);
            const ty1 = cy + (r - 14) * Math.sin(thAngle);
            const tx2 = cx + (r + 14) * Math.cos(thAngle);
            const ty2 = cy + (r + 14) * Math.sin(thAngle);
            ctx.beginPath();
            ctx.moveTo(tx1, ty1);
            ctx.lineTo(tx2, ty2);
            ctx.lineWidth = 3;
            ctx.strokeStyle = '#ff3366';
            ctx.stroke();

            // Active Intensity Arc
            const maxRange = 0.070;
            const valClamped = Math.max(0.0, Math.min(maxRange, intensity));
            const angle = Math.PI + (valClamped / maxRange) * Math.PI;
            const isDanger = intensity > 0.035;
            const needleColor = isDanger ? '#ff3366' : '#00f090';

            ctx.beginPath();
            ctx.arc(cx, cy, r, Math.PI, angle, false);
            ctx.lineWidth = 16;
            ctx.strokeStyle = needleColor;
            ctx.stroke();

            // Needle Line
            const nx = cx + (r - 8) * Math.cos(angle);
            const ny = cy + (r - 8) * Math.sin(angle);
            ctx.beginPath();
            ctx.moveTo(cx, cy);
            ctx.lineTo(nx, ny);
            ctx.lineWidth = 3.5;
            ctx.strokeStyle = '#fff';
            ctx.stroke();

            // Hub
            ctx.beginPath();
            ctx.arc(cx, cy, 7, 0, Math.PI * 2);
            ctx.fillStyle = needleColor;
            ctx.fill();

            // Labels
            ctx.font = '10px JetBrains Mono, monospace';
            ctx.fillStyle = '#ff3366';
            ctx.textAlign = 'center';
            ctx.fillText('0.035 عتبة الخطر', cx, cy - r - 10);

            const gVal = document.getElementById('hawkes-gauge-val');
            const gDesc = document.getElementById('hawkes-gauge-desc');
            if (gVal && gDesc) {
                gVal.innerText = intensity.toFixed(4);
                gVal.className = isDanger ? 'text-red' : 'text-green';
                gDesc.innerText = isDanger ? '🛑 شلالات هبوط حادة نشطة! درع الحماية يمنع صفقات الألت كوينز' : '🟢 الشدة الذاتية في النطاق الآمن — محرك الاقتناص مفعل بالكامل';
            }
        }

        // Rolling 60-Bar Hawkes Trajectory Line Chart
        function drawHawkesTrajectory() {
            const canvas = document.getElementById('hawkesHistoryCanvas');
            if (!canvas || !canvas.parentElement) return;
            const ctx = canvas.getContext('2d');
            const w = canvas.width = canvas.parentElement.clientWidth;
            const h = canvas.height = 190;

            ctx.clearRect(0, 0, w, h);
            const padL = 55, padR = 25, padT = 20, padB = 25;
            const plotW = w - padL - padR;
            const plotH = h - padT - padB;

            const pts = (hawkesHistory && hawkesHistory.length > 0) ? hawkesHistory : [{time: 'الآن', intensity: (lastState ? lastState.btc_hawkes : 0.0)}];
            const maxVal = Math.max(0.060, ...pts.map(p => p.intensity));
            const minVal = 0.0;

            const getY = (val) => padT + plotH - (val / maxVal) * plotH;
            const getX = (idx) => padL + (pts.length > 1 ? (idx / (pts.length - 1)) * plotW : plotW / 2);

            // Shaded Danger Zone (>= 0.035)
            const dangerY = getY(0.035);
            if (dangerY >= padT) {
                ctx.fillStyle = 'rgba(255, 51, 102, 0.08)';
                ctx.fillRect(padL, padT, plotW, dangerY - padT);
            }

            // Grid Lines
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
            ctx.fillStyle = '#64748b';
            ctx.font = '10px JetBrains Mono, monospace';
            for (let v = 0.0; v <= maxVal; v += 0.02) {
                const y = getY(v);
                ctx.beginPath();
                ctx.moveTo(padL, y);
                ctx.lineTo(w - padR, y);
                ctx.stroke();
                ctx.fillText(v.toFixed(3), 12, y + 3);
            }

            // 0.035 Threshold Dashed Line
            ctx.strokeStyle = '#ff3366';
            ctx.setLineDash([5, 5]);
            ctx.lineWidth = 1.8;
            ctx.beginPath();
            ctx.moveTo(padL, dangerY);
            ctx.lineTo(w - padR, dangerY);
            ctx.stroke();
            ctx.setLineDash([]);
            ctx.fillStyle = '#ff3366';
            ctx.fillText('0.035 عتبة الخطر', w - padR - 85, dangerY - 6);

            if (pts.length < 2) return;

            // Gradient fill under curve
            const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
            grad.addColorStop(0, 'rgba(0, 240, 144, 0.3)');
            grad.addColorStop(1, 'rgba(0, 0, 0, 0.0)');

            ctx.beginPath();
            ctx.moveTo(getX(0), getY(pts[0].intensity));
            for (let i = 1; i < pts.length; i++) {
                ctx.lineTo(getX(i), getY(pts[i].intensity));
            }
            ctx.lineTo(getX(pts.length - 1), padT + plotH);
            ctx.lineTo(getX(0), padT + plotH);
            ctx.closePath();
            ctx.fillStyle = grad;
            ctx.fill();

            // Line
            ctx.strokeStyle = '#00f090';
            ctx.lineWidth = 2.2;
            ctx.beginPath();
            ctx.moveTo(getX(0), getY(pts[0].intensity));
            for (let i = 1; i < pts.length; i++) {
                ctx.lineTo(getX(i), getY(pts[i].intensity));
            }
            ctx.stroke();

            // End point
            const lastPt = pts[pts.length - 1];
            const ex = getX(pts.length - 1);
            const ey = getY(lastPt.intensity);
            ctx.fillStyle = lastPt.intensity > 0.035 ? '#ff3366' : '#00f090';
            ctx.beginPath();
            ctx.arc(ex, ey, 4.5, 0, Math.PI * 2);
            ctx.fill();
        }

        // Cross-Sectional Shock Sensitivity Table
        function renderHawkesSensitivityTable(leaderboard) {
            const tab = document.getElementById('tab-hawkes');
            if (!tab || !tab.classList.contains('active')) return;
            const tbody = document.getElementById('hawkes-matrix-tbody');
            if (!tbody) return;
            const items = leaderboard || [];
            if (items.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--text-muted);padding:20px;">جاري استلام البيانات...</td></tr>';
                return;
            }
            tbody.innerHTML = items.map(c => {
                const grpClass = c.group === 'GOLDEN_11' ? 'G-11' : 'T-11';
                const isSafe = (lastState && lastState.is_btc_safe);
                const shieldStatus = c.status === 'POSITION_OPEN' ? '🟢 مركز مفتوح' : (isSafe ? 'مفتوح للدخول 🟢' : 'محمي بدرع هوكس 🛑');
                return `
                <tr>
                    <td style="font-weight:800;color:#fff;">${c.sym}</td>
                    <td><span class="badge-grp ${grpClass}">${grpClass}</span></td>
                    <td style="color:${c.fisher_z > 1.2 ? 'var(--accent-green)' : 'var(--text-muted)'};">${(c.fisher_z || 0).toFixed(2)}</td>
                    <td>${(c.ko_z || 0).toFixed(2)}</td>
                    <td>${(c.ofi || 0).toFixed(2)}</td>
                    <td style="font-weight:800;color:${c.score > 20 ? 'var(--accent-green)' : 'var(--accent-cyan)'};">${c.score.toFixed(1)}</td>
                    <td><span class="badge-status ${isSafe ? 'TRIGGERED' : 'COOLDOWN'}">${shieldStatus}</span></td>
                </tr>`;
            }).join('');
        }

        // TAB 5: Alpha Matrix Table
        let matrixData = [];
        function renderAlphaMatrixTable(leaderboard) {
            matrixData = leaderboard || [];
            const tab = document.getElementById('tab-matrix');
            if (tab && tab.classList.contains('active')) {
                applyMatrixFilterAndSort();
            }
        }

        function applyMatrixFilterAndSort() {
            const query = (document.getElementById('matrix-search')?.value || '').toUpperCase();
            const sortMode = document.getElementById('matrix-sort')?.value || 'score';
            
            let filtered = matrixData.filter(x => x.sym.includes(query));
            if (sortMode === 'score') filtered.sort((a, b) => b.score - a.score);
            else if (sortMode === 'change') filtered.sort((a, b) => (b.change_24h || 0) - (a.change_24h || 0));
            else if (sortMode === 'price') filtered.sort((a, b) => b.price - a.price);
            else if (sortMode === 'volume') filtered.sort((a, b) => (b.vol_quote || 0) - (a.vol_quote || 0));
            else if (sortMode === 'spread') filtered.sort((a, b) => (a.spread_bps || 0) - (b.spread_bps || 0));

            const tbody = document.getElementById('matrix-tbody');
            if (!tbody) return;
            if (filtered.length === 0) {
                tbody.innerHTML = '<tr><td colspan="13" style="text-align:center;color:var(--text-muted);padding:20px;">لا توجد عملات مطابقة للبحث.</td></tr>';
                return;
            }

            tbody.innerHTML = filtered.map(item => {
                const isPos = (item.change_24h || 0) >= 0;
                const sign = isPos ? '+' : '';
                const volM = ((item.vol_quote || 0) / 1000000.0).toFixed(1);
                const grpClass = item.group === 'GOLDEN_11' ? 'G-11' : 'T-11';

                return `
                <tr>
                    <td style="font-weight:800;color:#fff;">${item.sym}</td>
                    <td><span class="badge-grp ${grpClass}">${grpClass}</span></td>
                    <td id="mat-px-${item.sym}">$${formatPx(item.price)}</td>
                    <td class="${isPos ? 'text-green' : 'text-red'}" id="mat-chg-${item.sym}" style="font-weight:700;">${sign}${(item.change_24h || 0).toFixed(2)}%</td>
                    <td style="color:var(--text-muted);font-size:0.7rem;">$${formatPx(item.high_24h || item.price)} / $${formatPx(item.low_24h || item.price)}</td>
                    <td id="mat-spread-${item.sym}">${(item.spread_bps || 0).toFixed(1)} bps</td>
                    <td style="font-weight:800;color:${item.score > 20 ? 'var(--accent-green)' : (item.score > 0 ? 'var(--accent-cyan)' : 'var(--text-muted)')};">${item.score.toFixed(1)}</td>
                    <td>${(item.motif_dist || 99.0).toFixed(3)}</td>
                    <td style="color:${item.fisher_z > 1.5 ? 'var(--accent-green)' : (item.fisher_z < -1.0 ? 'var(--accent-red)' : 'var(--text-muted)')};">${item.fisher_z > 0 ? '+' : ''}${(item.fisher_z || 0).toFixed(2)}</td>
                    <td>${(item.ko_z || 0).toFixed(2)}</td>
                    <td>${(item.ofi || 0).toFixed(2)}</td>
                    <td style="color:var(--text-muted);">$${volM}M</td>
                    <td><span class="badge-status ${item.status}">${item.status === 'POSITION_OPEN' ? '🟢 صفقة' : item.status}</span></td>
                </tr>`;
            }).join('');
        }

        function filterAlphaMatrix() { applyMatrixFilterAndSort(); }
        function sortAlphaMatrix() { applyMatrixFilterAndSort(); }
        function selectMatrixCoin(sym) {
            switchTab('tab-matrix');
            const s = document.getElementById('matrix-search');
            if (s) { s.value = sym; filterAlphaMatrix(); }
        }

        // TAB 6: Trade Ledger Table
        let ledgerData = [];
        let lastLedgerHash = '';
        function renderTradeLedger(trades) {
            ledgerData = trades || [];
            const tab = document.getElementById('tab-ledger');
            if (!tab || !tab.classList.contains('active')) return;
            const currentHash = trades.length + ':' + (trades.length > 0 ? (trades[trades.length-1].exit_time || '') : '');
            if (currentHash !== lastLedgerHash) {
                lastLedgerHash = currentHash;
                applyLedgerFilter();
            }
        }

        function applyLedgerFilter() {
            const query = (document.getElementById('ledger-search')?.value || '').toUpperCase();
            const filterMode = document.getElementById('ledger-filter')?.value || 'all';

            let filtered = ledgerData.slice().reverse().filter(t => {
                const matchQ = t.sym.toUpperCase().includes(query) || (t.reason || '').toUpperCase().includes(query);
                if (!matchQ) return false;
                if (filterMode === 'win') return t.net > 0;
                if (filterMode === 'loss') return t.net <= 0;
                if (filterMode === 'TP') return t.reason === 'TAKE_PROFIT';
                if (filterMode === 'SL') return t.reason === 'STOP_LOSS';
                if (filterMode === 'TRAILING') return t.reason === 'TRAILING_LOCK';
                return true;
            });

            const tbody = document.getElementById('ledger-tbody');
            if (!tbody) return;
            if (filtered.length === 0) {
                tbody.innerHTML = '<tr><td colspan="11" style="text-align:center;color:var(--text-muted);padding:20px;">لا توجد صفقات مغلقة مطابقة.</td></tr>';
                return;
            }

            tbody.innerHTML = filtered.map((t, idx) => {
                const isWin = t.net >= 0;
                const sign = isWin ? '+' : '';
                const col = isWin ? 'text-green' : 'text-red';
                let reasonAr = t.reason;
                if (t.reason === 'TAKE_PROFIT') reasonAr = 'هدف كامل (+6.5%) 🎯';
                else if (t.reason === 'TRAILING_LOCK') reasonAr = 'حصد أرباح القمة 🔒';
                else if (t.reason === 'STOP_LOSS') reasonAr = 'وقف خسارة (-2.2%) 🛑';
                else if (t.reason === 'STALL_EXIT') reasonAr = 'خروج ركود ⏳';
                else if (t.reason === 'EMERGENCY_OVERRIDE' || t.reason === 'EMERGENCY_CLOSE_ALL') reasonAr = 'إغلاق طوارئ يدوي 🚨';

                return `
                <tr>
                    <td style="color:var(--text-sub);">${filtered.length - idx}</td>
                    <td style="font-weight:800;color:#fff;">${t.sym}</td>
                    <td style="color:var(--text-muted);font-size:0.68rem;">${(t.entry_time || '').substring(5, 19).replace('T', ' ')}</td>
                    <td style="color:var(--text-muted);font-size:0.68rem;">${(t.exit_time || '').substring(5, 19).replace('T', ' ')}</td>
                    <td>$${formatPx(t.entry_px)}</td>
                    <td>$${formatPx(t.exit_px)}</td>
                    <td class="${col}" style="font-weight:800;">${sign}${t.pnl_pct.toFixed(2)}%</td>
                    <td class="${col}" style="font-weight:800;">${sign}$${t.net.toFixed(2)}</td>
                    <td>${reasonAr}</td>
                    <td>${t.bars_held} (${t.bars_held * 5} د)</td>
                    <td>$${(t.cap_after !== undefined && t.cap_after !== null ? t.cap_after : 1000).toFixed(2)}</td>
                </tr>`;
            }).join('');
        }

        function filterTradeLedger() { applyLedgerFilter(); }

        // TAB 7: Console Logs
        function appendConsoleLog(log) {
            const feed = document.getElementById('console-logs');
            if (!feed) return;
            const div = document.createElement('div');
            div.className = 'log-entry';
            const lvl = log.level || 'INFO';
            div.innerHTML = `
                <span class="log-t">${log.timestamp}</span>
                <span class="log-lvl-${lvl}">[${lvl}]</span>
                <span class="log-txt">${log.message}</span>
            `;
            feed.appendChild(div);
            if (feed.children.length > 300) feed.removeChild(feed.firstChild);

            const chk = document.getElementById('autoscroll-chk');
            if (chk && chk.checked) feed.scrollTop = feed.scrollHeight;
        }

        function clearConsole() {
            const feed = document.getElementById('console-logs');
            if (feed) feed.innerHTML = '';
        }

        // Tab Switching
        function switchTab(tabId) {
            document.querySelectorAll('.tab-btn').forEach(b => {
                b.classList.toggle('active', b.getAttribute('data-tab') === tabId);
            });
            document.querySelectorAll('.tab-content').forEach(p => {
                p.classList.toggle('active', p.id === tabId);
            });
            if (tabId === 'tab-matrix') {
                applyMatrixFilterAndSort();
            } else if (tabId === 'tab-analytics') {
                setTimeout(drawEquityChart, 60);
            } else if (tabId === 'tab-hawkes') {
                setTimeout(() => {
                    if (lastState) {
                        drawHawkesGauge(lastState.btc_hawkes);
                        renderHawkesSensitivityTable(lastState.leaderboard);
                    }
                    drawHawkesTrajectory();
                }, 60);
            } else if (tabId === 'tab-ledger') {
                lastLedgerHash = '';
                applyLedgerFilter();
            }
        }

        // Quick Actions Commands with REST Fallback
        async function togglePauseBot() {
            const action = isPausedState ? 'resume' : 'pause';
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({action: action}));
            } else {
                try {
                    await fetch(`/api/action/${action}`, {method: 'POST'});
                } catch (e) { console.error(e); }
            }
        }

        function updatePauseButtonUI() {
            const btn = document.getElementById('btn-toggle-pause');
            if (!btn) return;
            if (isPausedState) {
                btn.innerHTML = '▶️ استئناف التداول';
                btn.style.background = 'rgba(0, 240, 144, 0.15)';
                btn.style.borderColor = 'rgba(0, 240, 144, 0.35)';
                btn.style.color = 'var(--accent-green)';
            } else {
                btn.innerHTML = '⏸️ إيقاف مؤقت';
                btn.style.background = 'rgba(251, 191, 36, 0.12)';
                btn.style.borderColor = 'rgba(251, 191, 36, 0.3)';
                btn.style.color = '#fbbf24';
            }
        }

        async function emergencyCloseAll() {
            if (confirm('🚨 تحذير: هل أنت متأكد من تصفية وإغلاق كافة الصفقات المفتوحة فوراً بأمر سوق؟')) {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({action: 'emergency_close'}));
                } else {
                    try {
                        await fetch('/api/action/emergency_close', {method: 'POST'});
                    } catch (e) { console.error(e); }
                }
            }
        }

        async function closePosition(sym) {
            if (confirm(`هل أنت متأكد من إغلاق مركز ${sym} يدوياً بسعر السوق اللحظي؟`)) {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({action: 'close_position', symbol: sym}));
                } else {
                    try {
                        await fetch(`/api/action/close/${sym}`, {method: 'POST'});
                    } catch (e) { console.error(e); }
                }
            }
        }

        async function resetPortfolio() {
            if (confirm('هل أنت متأكد من تصفير رصيد المحفظة بالكامل إلى $1,000.00؟')) {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({action: 'reset'}));
                } else {
                    try {
                        await fetch('/api/action/reset', {method: 'POST'});
                    } catch (e) { console.error(e); }
                }
            }
        }

        async function testSoundAlert() {
            playAlertSound();
            showNotification('🔔 اختبار النظام الصوتي الحسابي', 'تم التحقق من صوت التنبيه اللحظي بنجاح عبر Web Audio API.', true);
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({action: 'test_alert'}));
            } else {
                try {
                    await fetch('/api/action/test_alert', {method: 'POST'});
                } catch (e) { console.error(e); }
            }
        }

        function downloadTradesCSV() {
            const a = document.createElement('a');
            a.href = '/api/trades/export.csv';
            a.download = 'mega22_trades.csv';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        }

        window.addEventListener('resize', () => {
            drawEquityChart();
            if (lastState) drawHawkesGauge(lastState.btc_hawkes);
            drawHawkesTrajectory();
        });

        window.onload = () => {
            updateAudioBadge();
            connectWS();
        };
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
@app.head("/")
async def get_dashboard():
    """Serves the ultra-high performance institutional quantitative dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Mega-22 Dashboard Server")
    default_port = int(os.environ.get("PORT", 8080))
    parser.add_argument("--port", type=int, default=default_port, help=f"Port to bind (default: {default_port})")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    args = parser.parse_args()
    
    logger.info(f"🚀 Starting Mega-22 Dashboard on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

if __name__ == "__main__":
    main()
