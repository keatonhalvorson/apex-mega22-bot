"""
Mega-22 Sovereign Institutional Web Dashboard Server
High-performance FastAPI server with zero-latency WebSocket live streaming.
Serves an ultra-modern Cyberpunk / Glassmorphic dark interface.
"""

import os
import sys
import json
import asyncio
import logging
from pathlib import Path
from typing import Set
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Ensure engine directory in path
CURRENT_DIR = Path(__file__).resolve().parent
if str(CURRENT_DIR) not in sys.path:
    sys.path.insert(0, str(CURRENT_DIR))

from mega22_paper_bot import Mega22PaperBot
from mega22_constants import MEGA_22, INITIAL_CAPITAL

logger = logging.getLogger("Mega22Dashboard")

app = FastAPI(title="APEX Sovereign Mega-22 Dashboard")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global Bot Instance & WebSocket Clients
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

@app.on_event("startup")
async def startup_event():
    """Launch the paper trading bot event loop in the background."""
    logger.info("Starting Mega-22 Sovereign Paper Trading Bot in background task...")
    asyncio.create_task(bot.run())
    # Start periodic 1-second state broadcast loop
    asyncio.create_task(periodic_state_broadcast())

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
            # Receive client ping or commands
            msg_text = await websocket.receive_text()
            try:
                cmd = json.loads(msg_text)
                action = cmd.get("action")
                if action == "reset":
                    bot.reset_portfolio()
                elif action == "close_position":
                    sym = cmd.get("symbol")
                    if sym:
                        bot.manual_close_position(sym)
            except Exception:
                pass
    except WebSocketDisconnect:
        connected_websockets.discard(websocket)
    except Exception:
        connected_websockets.discard(websocket)

@app.get("/api/state")
async def get_state():
    """REST API: current state snapshot."""
    return JSONResponse(content=bot.get_full_state())

@app.get("/api/trades")
async def get_trades():
    """REST API: completed trades list."""
    return JSONResponse(content=[t.to_dict() for t in bot.trade_history])

@app.post("/api/action/reset")
async def reset_account():
    """REST API: reset account capital."""
    bot.reset_portfolio(INITIAL_CAPITAL)
    return JSONResponse(content={"status": "ok", "capital": INITIAL_CAPITAL})

@app.post("/api/action/close/{symbol}")
async def close_position(symbol: str):
    """REST API: manual position closure."""
    success = bot.manual_close_position(symbol.upper())
    if not success:
        raise HTTPException(status_code=404, detail="Position not found")
    return JSONResponse(content={"status": "closed", "symbol": symbol.upper()})

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>APEX Sovereign Engine | Mega-22 Live Spot Paper Trader</title>
    <style>
        :root {
            --bg: #07090e;
            --card-bg: rgba(14, 19, 32, 0.85);
            --card-border: rgba(255, 255, 255, 0.08);
            --accent-green: #10b981;
            --accent-green-glow: rgba(16, 185, 129, 0.25);
            --accent-red: #f43f5e;
            --accent-red-glow: rgba(244, 63, 94, 0.25);
            --accent-cyan: #06b6d4;
            --accent-amber: #f59e0b;
            --accent-purple: #8b5cf6;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --font-mono: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
            --font-ui: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Tajawal', 'Inter', sans-serif;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            background-color: var(--bg);
            background-image: 
                radial-gradient(circle at 15% 15%, rgba(16, 185, 129, 0.04) 0%, transparent 40%),
                radial-gradient(circle at 85% 85%, rgba(6, 182, 212, 0.04) 0%, transparent 40%);
            color: var(--text-main);
            font-family: var(--font-ui);
            min-height: 100vh;
            padding: 16px;
            overflow-x: hidden;
        }

        /* Glassmorphic Container */
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 16px 24px;
            margin-bottom: 16px;
            backdrop-filter: blur(16px);
            box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
        }

        .header-title {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .logo-badge {
            background: linear-gradient(135deg, #10b981 0%, #06b6d4 100%);
            width: 42px;
            height: 42px;
            border-radius: 10px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            font-weight: bold;
            color: #000;
            box-shadow: 0 0 16px var(--accent-green-glow);
        }

        .title-text h1 {
            font-size: 1.3rem;
            font-weight: 700;
            letter-spacing: 0.5px;
            color: #fff;
        }

        .title-text p {
            font-size: 0.8rem;
            color: var(--text-muted);
            margin-top: 2px;
        }

        .header-controls {
            display: flex;
            align-items: center;
            gap: 16px;
        }

        .status-pill {
            display: flex;
            align-items: center;
            gap: 8px;
            background: rgba(16, 185, 129, 0.12);
            border: 1px solid rgba(16, 185, 129, 0.3);
            color: var(--accent-green);
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 0.78rem;
            font-weight: 600;
            font-family: var(--font-mono);
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--accent-green);
            animation: pulse 1.5s infinite;
        }

        @keyframes pulse {
            0% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
            70% { transform: scale(1.1); box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
            100% { transform: scale(0.9); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
        }

        .btn-reset {
            background: rgba(244, 63, 94, 0.15);
            border: 1px solid rgba(244, 63, 94, 0.35);
            color: #ff6b81;
            padding: 6px 14px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.8rem;
            font-weight: 600;
            transition: all 0.2s;
        }
        .btn-reset:hover {
            background: rgba(244, 63, 94, 0.3);
            box-shadow: 0 0 12px var(--accent-red-glow);
        }

        /* KPI Metric Cards Grid */
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
            gap: 14px;
            margin-bottom: 16px;
        }

        .kpi-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 16px;
            backdrop-filter: blur(12px);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            position: relative;
            overflow: hidden;
        }

        .kpi-card::before {
            content: '';
            position: absolute;
            top: 0;
            right: 0;
            width: 100%;
            height: 3px;
            background: linear-gradient(90deg, var(--accent-green), transparent);
            opacity: 0.8;
        }

        .kpi-card.amber::before { background: linear-gradient(90deg, var(--accent-amber), transparent); }
        .kpi-card.cyan::before { background: linear-gradient(90deg, var(--accent-cyan), transparent); }
        .kpi-card.red::before { background: linear-gradient(90deg, var(--accent-red), transparent); }
        .kpi-card.purple::before { background: linear-gradient(90deg, var(--accent-purple), transparent); }

        .kpi-title {
            font-size: 0.75rem;
            color: var(--text-muted);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 6px;
        }

        .kpi-value {
            font-size: 1.55rem;
            font-weight: 800;
            font-family: var(--font-mono);
            color: #fff;
        }

        .kpi-sub {
            font-size: 0.75rem;
            color: var(--text-muted);
            margin-top: 6px;
            display: flex;
            align-items: center;
            gap: 6px;
        }

        .text-green { color: var(--accent-green) !important; }
        .text-red { color: var(--accent-red) !important; }
        .text-amber { color: var(--accent-amber) !important; }
        .text-cyan { color: var(--accent-cyan) !important; }

        /* Chart & Spotlight Section */
        .chart-spotlight-grid {
            display: grid;
            grid-template-columns: 1.35fr 0.65fr;
            gap: 16px;
            margin-bottom: 16px;
        }
        @media (max-width: 1050px) {
            .chart-spotlight-grid { grid-template-columns: 1fr; }
        }

        .chart-canvas-container {
            position: relative;
            width: 100%;
            height: 200px;
            margin-top: 8px;
        }
        #equityCanvas {
            width: 100%;
            height: 100%;
            display: block;
        }

        .spotlight-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 16px;
            backdrop-filter: blur(12px);
            display: flex;
            flex-direction: column;
            justify-content: space-between;
        }

        /* Position PnL Progress Bar */
        .pos-bar-container {
            width: 100%;
            margin-top: 10px;
        }
        .pos-bar-labels {
            display: flex;
            justify-content: space-between;
            font-size: 0.68rem;
            color: var(--text-muted);
            font-family: var(--font-mono);
            margin-bottom: 3px;
        }
        .pos-bar-track {
            position: relative;
            width: 100%;
            height: 6px;
            background: rgba(255, 255, 255, 0.08);
            border-radius: 4px;
            overflow: hidden;
        }
        .pos-bar-fill {
            position: absolute;
            top: 0;
            bottom: 0;
            border-radius: 4px;
            transition: all 0.3s;
        }
        .pos-bar-fill.green { background: linear-gradient(90deg, #059669, #10b981); }
        .pos-bar-fill.red { background: linear-gradient(90deg, #f43f5e, #dc2626); }
        .pos-zero-marker {
            position: absolute;
            top: 0;
            bottom: 0;
            left: 25.3%; /* -2.2% SL to +6.5% TP = 8.7% range; zero is at 2.2/8.7 = 25.3% */
            width: 2px;
            background: rgba(255, 255, 255, 0.4);
            z-index: 2;
        }

        /* Main Workspace: 2 Columns */
        .workspace-grid {
            display: grid;
            grid-template-columns: 1.2fr 0.8fr;
            gap: 16px;
            margin-bottom: 16px;
        }

        @media (max-width: 1100px) {
            .workspace-grid { grid-template-columns: 1fr; }
        }

        .panel-card {
            background: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 16px;
            backdrop-filter: blur(12px);
            display: flex;
            flex-direction: column;
        }

        .panel-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 12px;
            margin-bottom: 14px;
        }

        .panel-title {
            font-size: 0.95rem;
            font-weight: 700;
            color: #fff;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        /* Active Positions Cards */
        .positions-container {
            display: flex;
            flex-direction: column;
            gap: 12px;
            min-height: 180px;
        }

        .empty-state {
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 40px 20px;
            color: var(--text-muted);
            font-size: 0.85rem;
            text-align: center;
            border: 1px dashed rgba(255, 255, 255, 0.1);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.01);
        }

        .position-card {
            background: rgba(20, 27, 45, 0.8);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-right: 4px solid var(--accent-green);
            border-radius: 10px;
            padding: 14px 18px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: all 0.2s;
        }
        .position-card:hover {
            border-color: rgba(255, 255, 255, 0.2);
            box-shadow: 0 4px 16px rgba(0, 0, 0, 0.3);
        }

        .pos-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .pos-sym {
            font-size: 1.1rem;
            font-weight: 800;
            font-family: var(--font-mono);
            color: #fff;
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .pos-badge {
            font-size: 0.65rem;
            background: rgba(16, 185, 129, 0.2);
            color: var(--accent-green);
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 700;
        }

        .pos-prices {
            font-size: 0.78rem;
            color: var(--text-muted);
            font-family: var(--font-mono);
        }

        .pos-metrics {
            display: flex;
            gap: 20px;
            align-items: center;
        }

        .pos-pnl {
            text-align: left;
        }

        .pos-pnl-val {
            font-size: 1.25rem;
            font-weight: 800;
            font-family: var(--font-mono);
        }

        .pos-pnl-pct {
            font-size: 0.8rem;
            font-weight: 600;
            font-family: var(--font-mono);
        }

        .pos-action-btn {
            background: rgba(244, 63, 94, 0.15);
            border: 1px solid rgba(244, 63, 94, 0.3);
            color: var(--accent-red);
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 0.72rem;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.2s;
        }
        .pos-action-btn:hover {
            background: var(--accent-red);
            color: #fff;
        }

        /* Leaderboard & Scanner Table */
        .table-wrap {
            max-height: 290px;
            overflow-y: auto;
        }
        .table-wrap::-webkit-scrollbar { width: 4px; }
        .table-wrap::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.15); border-radius: 4px; }

        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 0.78rem;
            text-align: right;
        }

        th {
            color: var(--text-muted);
            font-weight: 600;
            padding: 8px 10px;
            border-bottom: 1px solid var(--card-border);
            position: sticky;
            top: 0;
            background: #0e1320;
            z-index: 2;
        }

        td {
            padding: 8px 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            font-family: var(--font-mono);
            color: #e5e7eb;
        }

        tr:hover td {
            background: rgba(255, 255, 255, 0.03);
        }

        .badge-status {
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.68rem;
            font-weight: 700;
            display: inline-block;
        }
        .badge-status.TRIGGERED { background: rgba(16, 185, 129, 0.2); color: var(--accent-green); }
        .badge-status.SCANNING { background: rgba(107, 114, 128, 0.2); color: #9ca3af; }
        .badge-status.COOLDOWN { background: rgba(245, 158, 11, 0.2); color: var(--accent-amber); }
        .badge-status.POSITION_OPEN { background: rgba(6, 182, 212, 0.2); color: var(--accent-cyan); }

        /* Bottom Section: History & Logs */
        .bottom-grid {
            display: grid;
            grid-template-columns: 1.2fr 0.8fr;
            gap: 16px;
        }
        @media (max-width: 1100px) {
            .bottom-grid { grid-template-columns: 1fr; }
        }

        /* Terminal Console */
        .terminal-feed {
            background: #05070a;
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 8px;
            padding: 12px;
            font-family: var(--font-mono);
            font-size: 0.72rem;
            height: 250px;
            overflow-y: auto;
            color: #94a3b8;
            display: flex;
            flex-direction: column;
            gap: 4px;
        }
        .terminal-feed::-webkit-scrollbar { width: 4px; }
        .terminal-feed::-webkit-scrollbar-thumb { background: rgba(255, 255, 255, 0.15); border-radius: 4px; }

        .log-entry {
            display: flex;
            gap: 8px;
            line-height: 1.4;
        }
        .log-time { color: #64748b; }
        .log-level-INFO { color: #38bdf8; }
        .log-level-WARNING { color: #fbbf24; }
        .log-level-ERROR { color: #f87171; }
        .log-msg { color: #e2e8f0; }

        .hawkes-badge {
            display: flex;
            align-items: center;
            gap: 6px;
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 700;
        }
        .hawkes-safe { background: rgba(16, 185, 129, 0.15); color: var(--accent-green); }
        .hawkes-danger { background: rgba(244, 63, 94, 0.15); color: var(--accent-red); }
    </style>
</head>
<body>

    <!-- Header -->
    <header class="header">
        <div class="header-title">
            <div class="logo-badge">⚡</div>
            <div class="title-text">
                <h1>APEX Sovereign Engine | Mega-22 Spot Paper Trader</h1>
                <p>Golden-11 ∪ Titan-11 (22 عملة) | 100% Halal Spot 1x Cash | درع هوكس وشلالات الانفجار</p>
            </div>
        </div>
        <div class="header-controls">
            <div class="status-pill" id="conn-status">
                <span class="pulse-dot"></span>
                <span>بث مباشر فوري (Binance Spot)</span>
            </div>
            <button class="btn-reset" onclick="resetAccount()">🔄 تصفير المحفظة</button>
        </div>
    </header>

    <!-- KPI Metric Cards Grid -->
    <section class="kpi-grid">
        <div class="kpi-card cyan">
            <div class="kpi-title">💎 إجمالي رصيد المحفظة (Equity)</div>
            <div class="kpi-value" id="val-equity">$1,000.00</div>
            <div class="kpi-sub">رأس المال المبدئي: $1,000.00</div>
        </div>

        <div class="kpi-card green">
            <div class="kpi-title">💵 السيولة النقدية المتاحة (Cash)</div>
            <div class="kpi-value" id="val-cash">$1,000.00</div>
            <div class="kpi-sub" id="val-slots">الخانات الشاغرة: 3 / 3</div>
        </div>

        <div class="kpi-card">
            <div class="kpi-title">📈 صافي الأرباح المحققة (Net PnL)</div>
            <div class="kpi-value" id="val-net-profit">+$0.00</div>
            <div class="kpi-sub" id="val-roe">العائد الصافي: +0.00% ROE</div>
        </div>

        <div class="kpi-card amber">
            <div class="kpi-title">🎯 نسبة الفوز ومعامل الربح (Win Rate)</div>
            <div class="kpi-value" id="val-win-rate">0.0%</div>
            <div class="kpi-sub" id="val-pf">معامل الربح: 0.00 | 0 رابحة / 0 خاسرة</div>
        </div>

        <div class="kpi-card purple">
            <div class="kpi-title">🛡️ درع شلالات البيتكوين (BTC Hawkes Shield)</div>
            <div class="kpi-value" id="val-btc-price">$0.00</div>
            <div class="kpi-sub" id="val-hawkes-status">
                <span class="hawkes-badge hawkes-safe">آمن 🟢</span>
                <span id="val-hawkes-num">شدة هوكس: 0.0000</span>
            </div>
        </div>

        <div class="kpi-card red">
            <div class="kpi-title">📉 أقصى تراجع ومعدل الصفقات (Max DD)</div>
            <div class="kpi-value" id="val-max-dd">0.0%</div>
            <div class="kpi-sub" id="val-avg-trade">متوسط الربح: $0.00 / صفقة</div>
        </div>
    </section>

    <!-- Real-Time Equity Curve & Last Trade Spotlight -->
    <section class="chart-spotlight-grid">
        <div class="panel-card">
            <div class="panel-header">
                <div class="panel-title">
                    <span>📈 منحنى نمو الرصيد اللحظي (Live Equity Curve)</span>
                </div>
                <div style="display:flex; align-items:center; gap:12px; font-size:0.75rem; font-family:var(--font-mono);">
                    <span style="color:var(--accent-green);">● الرصيد الفعلي</span>
                    <span style="color:#6b7280;">--- خط الأساس $1,000</span>
                </div>
            </div>
            <div class="chart-canvas-container">
                <canvas id="equityCanvas"></canvas>
            </div>
        </div>

        <div class="spotlight-card">
            <div class="panel-header">
                <div class="panel-title">
                    <span>🏆 آخر صفقة مكتملة (Last Trade Spotlight)</span>
                </div>
                <span id="last-trade-time" style="font-size:0.72rem; color:var(--text-muted); font-family:var(--font-mono);">--:--:--</span>
            </div>
            <div id="spotlight-content" style="flex:1; display:flex; flex-direction:column; justify-content:center;">
                <div style="text-align:center; color:var(--text-muted); font-size:0.82rem; padding:20px;">
                    ⏳ في انتظار إغلاق أول صفقة حية...
                </div>
            </div>
        </div>
    </section>

    <!-- Middle Workspace: Positions & Scanner -->
    <main class="workspace-grid">
        <!-- Active Positions Panel -->
        <div class="panel-card">
            <div class="panel-header">
                <div class="panel-title">
                    <span>🚀 الصفقات المفتوحة حالياً (Active Spot Positions)</span>
                </div>
                <span style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);" id="pos-count-badge">0 / 3 خانات مستخدمة</span>
            </div>
            <div class="positions-container" id="positions-list">
                <div class="empty-state">
                    <span>🔍 لا توجد صفقات مفتوحة حالياً.</span>
                    <span style="margin-top: 4px; font-size: 0.75rem; color: #6b7280;">المحرك يفحص الـ 22 عملة بانتظار تشكل نمط وايكوف وانفجار مصفوفة فيشر.</span>
                </div>
            </div>
        </div>

        <!-- Mega-22 Scanner & Alpha Ranking -->
        <div class="panel-card">
            <div class="panel-header">
                <div class="panel-title">
                    <span>📊 رادار مصفوفة الألفا للـ 22 عملة (Whale Explosion Scanner)</span>
                </div>
                <span style="font-size: 0.72rem; color: var(--text-muted);">ترتيب لحظي حسب قوة الإشارة</span>
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>العملة</th>
                            <th>السعر ($)</th>
                            <th>قوة الألفا</th>
                            <th>المسافة</th>
                            <th>انتقال فيشر</th>
                            <th>الحالة</th>
                        </tr>
                    </thead>
                    <tbody id="scanner-tbody">
                        <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">جارٍ استلام بيانات الرادار...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </main>

    <!-- Bottom Section: Trade History & Real-Time Logs -->
    <section class="bottom-grid">
        <!-- Completed Trade Ledger -->
        <div class="panel-card">
            <div class="panel-header">
                <div class="panel-title">
                    <span>📜 سجل الصفقات المنجزة (Closed Trade History)</span>
                </div>
                <span style="font-size: 0.75rem; color: var(--text-muted); font-family: var(--font-mono);" id="hist-count">0 صفقات</span>
            </div>
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr>
                            <th>العملة</th>
                            <th>سعر الدخول</th>
                            <th>سعر الخروج</th>
                            <th>العائد (%)</th>
                            <th>صافي الربح ($)</th>
                            <th>سبب الخروج</th>
                            <th>المدة (شمعة)</th>
                        </tr>
                    </thead>
                    <tbody id="history-tbody">
                        <tr><td colspan="7" style="text-align: center; color: var(--text-muted);">لا توجد صفقات مغلقة بعد.</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Terminal Log Feed -->
        <div class="panel-card">
            <div class="panel-header">
                <div class="panel-title">
                    <span>🖥️ سجل القرارات اللحظية الحية (Live Event Console)</span>
                </div>
                <span style="font-size: 0.72rem; color: var(--text-muted);">بث حي غير متزامن</span>
            </div>
            <div class="terminal-feed" id="terminal-logs">
                <div class="log-entry">
                    <span class="log-time">00:00:00</span>
                    <span class="log-level-INFO">[SYS]</span>
                    <span class="log-msg">جاري الاتصال بمحرك التداول الحسابي المباشر...</span>
                </div>
            </div>
        </div>
    </section>

    <script>
        let ws;
        const wsUrl = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/live';

        function connectWS() {
            ws = new WebSocket(wsUrl);
            ws.onopen = () => {
                document.getElementById('conn-status').innerHTML = '<span class="pulse-dot"></span><span>بث مباشر فوري (Binance Spot)</span>';
                document.getElementById('conn-status').style.borderColor = 'rgba(16, 185, 129, 0.4)';
            };
            ws.onmessage = (event) => {
                const payload = JSON.parse(event.data);
                if (payload.type === 'state_snapshot') {
                    renderDashboard(payload.data);
                } else if (payload.type === 'log') {
                    appendLog(payload.data);
                } else if (payload.type === 'reset') {
                    equityHistory = [{t: 'البداية', equity: payload.data.capital || 1000.0}];
                    drawEquityChart();
                }
            };
            ws.onclose = () => {
                document.getElementById('conn-status').innerHTML = '<span style="color:#f43f5e;">● انقطع الاتصال، جاري إعادة المحاولة...</span>';
                document.getElementById('conn-status').style.borderColor = 'rgba(244, 63, 94, 0.4)';
                setTimeout(connectWS, 2000);
            };
        }

        let equityHistory = [];

        function drawEquityChart() {
            const canvas = document.getElementById('equityCanvas');
            if (!canvas || !canvas.parentElement) return;
            const ctx = canvas.getContext('2d');
            const width = canvas.width = canvas.parentElement.clientWidth;
            const height = canvas.height = canvas.parentElement.clientHeight || 200;
            
            ctx.clearRect(0, 0, width, height);
            
            const padL = 60, padR = 25, padT = 20, padB = 25;
            const plotW = width - padL - padR;
            const plotH = height - padT - padB;
            
            if (equityHistory.length === 0) {
                equityHistory.push({t: 'البداية', equity: 1000.0});
            }
            
            const values = equityHistory.map(d => d.equity);
            let minVal = Math.min(...values, 990.0);
            let maxVal = Math.max(...values, 1010.0);
            const range = (maxVal - minVal) || 10.0;
            minVal = Math.floor(minVal - range * 0.08);
            maxVal = Math.ceil(maxVal + range * 0.08);
            
            const getY = (val) => padT + plotH - ((val - minVal) / (maxVal - minVal)) * plotH;
            const getX = (idx) => padL + (equityHistory.length > 1 ? (idx / (equityHistory.length - 1)) * plotW : plotW / 2);
            
            // Grid lines & labels
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
            ctx.fillStyle = '#9ca3af';
            ctx.font = '10px JetBrains Mono, monospace';
            for (let i = 0; i <= 4; i++) {
                const val = minVal + (i / 4) * (maxVal - minVal);
                const y = getY(val);
                ctx.beginPath();
                ctx.moveTo(padL, y);
                ctx.lineTo(width - padR, y);
                ctx.stroke();
                ctx.fillText('$' + val.toFixed(0), 12, y + 3);
            }
            
            // Starting Capital $1000 Reference Line
            const base1000Y = getY(1000.0);
            if (base1000Y >= padT && base1000Y <= padT + plotH) {
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
                ctx.setLineDash([4, 4]);
                ctx.beginPath();
                ctx.moveTo(padL, base1000Y);
                ctx.lineTo(width - padR, base1000Y);
                ctx.stroke();
                ctx.setLineDash([]);
            }
            
            if (equityHistory.length < 2) return;
            
            const lastEq = values[values.length - 1];
            const isUp = lastEq >= 1000.0;
            const strokeColor = isUp ? '#10b981' : '#f43f5e';
            
            // Area gradient
            const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
            grad.addColorStop(0, isUp ? 'rgba(16, 185, 129, 0.28)' : 'rgba(244, 63, 94, 0.28)');
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
            ctx.shadowColor = strokeColor;
            ctx.shadowBlur = 6;
            ctx.strokeStyle = strokeColor;
            ctx.lineWidth = 2.2;
            ctx.beginPath();
            ctx.moveTo(getX(0), getY(values[0]));
            for (let i = 1; i < equityHistory.length; i++) {
                ctx.lineTo(getX(i), getY(values[i]));
            }
            ctx.stroke();
            ctx.shadowBlur = 0;
            
            // Last point marker
            const lastX = getX(equityHistory.length - 1);
            const lastY = getY(lastEq);
            ctx.fillStyle = strokeColor;
            ctx.beginPath();
            ctx.arc(lastX, lastY, 4, 0, Math.PI * 2);
            ctx.fill();
        }

        window.addEventListener('resize', drawEquityChart);

        function renderDashboard(s) {
            // KPIs
            document.getElementById('val-equity').innerText = '$' + s.equity.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            document.getElementById('val-cash').innerText = '$' + s.available_cash.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            document.getElementById('val-slots').innerText = `الخانات المستخدمة: ${s.used_slots} / ${s.max_slots}`;
            
            const netEl = document.getElementById('val-net-profit');
            netEl.innerText = (s.net_profit >= 0 ? '+$' : '-$') + Math.abs(s.net_profit).toFixed(2);
            netEl.className = 'kpi-value ' + (s.net_profit >= 0 ? 'text-green' : 'text-red');

            const roeEl = document.getElementById('val-roe');
            roeEl.innerText = `العائد الصافي: ${s.roe_pct >= 0 ? '+' : ''}${s.roe_pct.toFixed(2)}% ROE`;
            roeEl.className = 'kpi-sub ' + (s.roe_pct >= 0 ? 'text-green' : 'text-red');

            document.getElementById('val-win-rate').innerText = s.win_rate.toFixed(1) + '%';
            document.getElementById('val-pf').innerText = `معامل الربح: ${s.profit_factor.toFixed(2)} | ${s.winning_trades} رابحة / ${s.losing_trades} خاسرة`;

            document.getElementById('val-max-dd').innerText = (s.max_drawdown_pct || 0).toFixed(1) + '%';
            const avgTradeSign = (s.avg_trade_net || 0) >= 0 ? '+$' : '-$';
            document.getElementById('val-avg-trade').innerText = `متوسط الربح: ${avgTradeSign}${Math.abs(s.avg_trade_net || 0).toFixed(2)} / صفقة`;

            document.getElementById('val-btc-price').innerText = '$' + s.btc_price.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
            const hStatus = document.getElementById('val-hawkes-status');
            if (s.is_btc_safe) {
                hStatus.innerHTML = `<span class="hawkes-badge hawkes-safe">آمن 🟢</span> <span id="val-hawkes-num">هوكس: ${s.btc_hawkes.toFixed(4)} | 24h: ${s.btc_24h > 0 ? '+' : ''}${s.btc_24h.toFixed(1)}%</span>`;
            } else {
                hStatus.innerHTML = `<span class="hawkes-badge hawkes-danger">درع هوكس نشط 🛑</span> <span id="val-hawkes-num">هوكس: ${s.btc_hawkes.toFixed(4)} | 24h: ${s.btc_24h.toFixed(1)}%</span>`;
            }

            // Spotlight Card (Last Trade)
            const sContent = document.getElementById('spotlight-content');
            if (s.last_trade) {
                const lt = s.last_trade;
                const ltColor = lt.net >= 0 ? 'text-green' : 'text-red';
                const ltSign = lt.net >= 0 ? '+' : '';
                let reasonArabic = lt.reason;
                if (lt.reason === 'TAKE_PROFIT') reasonArabic = 'هدف كامل (+6.5%) 🎯';
                else if (lt.reason === 'TRAILING_LOCK') reasonArabic = 'حصد أرباح القمة 🔒';
                else if (lt.reason === 'STOP_LOSS') reasonArabic = 'وقف خسارة (-2.2%) 🛑';
                else if (lt.reason === 'STALL_EXIT') reasonArabic = 'خروج ركود ⏳';
                
                document.getElementById('last-trade-time').innerText = (lt.exit_time || '').substring(11, 19) + ' UTC';
                sContent.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                        <span style="font-size:1.35rem; font-weight:800; font-family:var(--font-mono); color:#fff;">${lt.sym}</span>
                        <span class="badge-status ${lt.net >= 0 ? 'TRIGGERED' : 'COOLDOWN'}">${reasonArabic}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:10px;">
                        <div style="font-size:0.8rem; color:var(--text-muted); font-family:var(--font-mono);">
                            $${lt.entry_px.toFixed(4)} ➔ $${lt.exit_px.toFixed(4)}
                        </div>
                        <div class="${ltColor}" style="font-size:1.3rem; font-weight:800; font-family:var(--font-mono);">
                            ${ltSign}$${lt.net.toFixed(2)} (${ltSign}${lt.pnl_pct.toFixed(2)}%)
                        </div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:0.75rem; color:#6b7280; font-family:var(--font-mono); border-top:1px solid rgba(255,255,255,0.06); padding-top:8px;">
                        <span>المدة: ${lt.bars_held} شمعة (${lt.bars_held * 5} دقيقة)</span>
                        <span>الرصيد بعدها: $${lt.cap_after.toFixed(2)}</span>
                    </div>
                `;
            }

            // Equity Curve Data Update (Preserves trade history & updates live point in-place)
            if (equityHistory.length === 0) {
                equityHistory.push({t: 'البداية', equity: 1000.0});
                if (s.recent_trades && s.recent_trades.length > 0) {
                    s.recent_trades.forEach((t, idx) => {
                        equityHistory.push({t: `${idx+1}`, equity: t.cap_after || 1000.0});
                    });
                }
                equityHistory.push({t: 'الآن', equity: s.equity});
            } else {
                // If a new closed trade has been recorded, add its permanent checkpoint
                const knownTrades = Math.max(0, equityHistory.length - 2);
                if (s.recent_trades && s.recent_trades.length > knownTrades) {
                    const lastTrade = s.recent_trades[s.recent_trades.length - 1];
                    const livePt = equityHistory.pop();
                    equityHistory.push({t: `${s.total_trades}`, equity: lastTrade.cap_after || s.equity});
                    equityHistory.push(livePt);
                    if (equityHistory.length > 100) equityHistory.shift();
                }
                // Update live point in-place
                const lastIdx = equityHistory.length - 1;
                equityHistory[lastIdx] = {t: new Date().toLocaleTimeString('en-GB'), equity: s.equity};
            }
            drawEquityChart();

            // Positions
            const posCont = document.getElementById('positions-list');
            document.getElementById('pos-count-badge').innerText = `${s.active_positions.length} / ${s.max_slots} خانات مستخدمة`;
            if (s.active_positions.length === 0) {
                posCont.innerHTML = `<div class="empty-state">
                    <span>🔍 لا توجد صفقات مفتوحة حالياً.</span>
                    <span style="margin-top: 4px; font-size: 0.75rem; color: #6b7280;">المحرك يفحص الـ 22 عملة بانتظار تشكل نمط وايكوف وانفجار مصفوفة فيشر.</span>
                </div>`;
            } else {
                posCont.innerHTML = s.active_positions.map(p => {
                    const pnlColor = p.unrealized_pnl >= 0 ? 'text-green' : 'text-red';
                    const pnlSign = p.unrealized_pnl >= 0 ? '+' : '';
                    let stopText = p.stop > 0 ? `وقف خسارة: -${(p.stop * 100).toFixed(1)}%` : `ربح مقفول: +${(Math.abs(p.stop) * 100).toFixed(1)}% 🔒`;
                    
                    const pnlProgress = Math.max(0, Math.min(100, ((p.unrealized_pnl_pct + 2.2) / 8.7) * 100));
                    const fillLeft = p.unrealized_pnl_pct >= 0 ? '25.3%' : `${pnlProgress}%`;
                    const fillWidth = p.unrealized_pnl_pct >= 0 ? `${pnlProgress - 25.3}%` : `${25.3 - pnlProgress}%`;
                    const barClass = p.unrealized_pnl_pct >= 0 ? 'green' : 'red';

                    return `
                    <div class="position-card">
                        <div class="pos-info" style="flex:1;">
                            <div class="pos-sym">
                                ${p.sym}
                                <span class="pos-badge">SPOT 1X LONG</span>
                                ${p.trailing_active ? '<span class="pos-badge" style="background:rgba(245,158,11,0.2);color:#f59e0b;">تتبع القمم 🏹</span>' : ''}
                            </div>
                            <div class="pos-prices">
                                الدخول: $${p.px.toFixed(4)} | الحالي: $${p.current_px.toFixed(4)} | الحجم: $${p.notional.toFixed(2)}
                            </div>
                            <div style="font-size:0.72rem;color:#9ca3af;margin-top:2px;">
                                ${stopText} | أعلى سعر: $${p.highest_seen.toFixed(4)}
                            </div>
                            <div class="pos-bar-container">
                                <div class="pos-bar-labels">
                                    <span style="color:var(--accent-red);">-2.2% SL</span>
                                    <span style="color:#9ca3af;">0.0%</span>
                                    <span style="color:var(--accent-green);">+6.5% TP</span>
                                </div>
                                <div class="pos-bar-track">
                                    <div class="pos-zero-marker"></div>
                                    <div class="pos-bar-fill ${barClass}" style="left:${fillLeft}; width:${fillWidth};"></div>
                                </div>
                            </div>
                        </div>
                        <div class="pos-metrics" style="margin-right:20px;">
                            <div class="pos-pnl">
                                <div class="pos-pnl-val ${pnlColor}">${pnlSign}$${p.unrealized_pnl.toFixed(2)}</div>
                                <div class="pos-pnl-pct ${pnlColor}">${pnlSign}${p.unrealized_pnl_pct.toFixed(2)}%</div>
                            </div>
                            <button class="pos-action-btn" onclick="closePosition('${p.sym}')">إغلاق يدوي</button>
                        </div>
                    </div>`;
                }).join('');
            }

            // Scanner Leaderboard
            const tb = document.getElementById('scanner-tbody');
            tb.innerHTML = s.leaderboard.map(item => `
                <tr>
                    <td style="font-weight:700;">${item.sym}</td>
                    <td>$${item.price.toFixed(4)}</td>
                    <td style="font-weight:700;color:${item.score > 20 ? '#10b981' : (item.score > 0 ? '#38bdf8' : '#9ca3af')};">${item.score.toFixed(1)}</td>
                    <td>${item.motif_dist.toFixed(3)}</td>
                    <td style="color:${item.fisher_z > 1.5 ? '#10b981' : (item.fisher_z < -1.0 ? '#f43f5e' : '#9ca3af')};">${item.fisher_z > 0 ? '+' : ''}${item.fisher_z.toFixed(2)}</td>
                    <td><span class="badge-status ${item.status}">${item.status}</span></td>
                </tr>
            `).join('');

            // History
            document.getElementById('hist-count').innerText = `${s.recent_trades.length} صفقات`;
            const htb = document.getElementById('history-tbody');
            if (s.recent_trades.length === 0) {
                htb.innerHTML = `<tr><td colspan="7" style="text-align: center; color: var(--text-muted);">لا توجد صفقات مغلقة بعد.</td></tr>`;
            } else {
                htb.innerHTML = s.recent_trades.slice().reverse().map(t => {
                    const pnlCol = t.net >= 0 ? 'text-green' : 'text-red';
                    const sign = t.net >= 0 ? '+' : '';
                    let reasonArabic = t.reason;
                    if (t.reason === 'TAKE_PROFIT') reasonArabic = 'هدف كامل (+6.5%) 🎯';
                    else if (t.reason === 'TRAILING_LOCK') reasonArabic = 'حصد أرباح القمة 🔒';
                    else if (t.reason === 'STOP_LOSS') reasonArabic = 'وقف خسارة (-2.2%) 🛑';
                    else if (t.reason === 'STALL_EXIT') reasonArabic = 'خروج ركود ⏳';
                    return `
                    <tr>
                        <td style="font-weight:700;">${t.sym}</td>
                        <td>$${t.entry_px.toFixed(4)}</td>
                        <td>$${t.exit_px.toFixed(4)}</td>
                        <td class="${pnlCol}" style="font-weight:700;">${sign}${t.pnl_pct.toFixed(2)}%</td>
                        <td class="${pnlCol}" style="font-weight:700;">${sign}$${t.net.toFixed(2)}</td>
                        <td>${reasonArabic}</td>
                        <td>${t.bars_held}</td>
                    </tr>`;
                }).join('');
            }
        }

        function appendLog(log) {
            const feed = document.getElementById('terminal-logs');
            const div = document.createElement('div');
            div.className = 'log-entry';
            div.innerHTML = `<span class="log-time">${log.timestamp}</span> <span class="log-level-${log.level}">[${log.level}]</span> <span class="log-msg">${log.message}</span>`;
            feed.appendChild(div);
            feed.scrollTop = feed.scrollHeight;
        }

        function closePosition(sym) {
            if (confirm(`هل أنت متأكد من رغبتك في إغلاق صفقة ${sym} يدوياً؟`)) {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({action: 'close_position', symbol: sym}));
                }
            }
        }

        function resetAccount() {
            if (confirm('هل أنت متأكد من تصفير رصيد المحفظة إلى $1,000.00؟')) {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send(JSON.stringify({action: 'reset'}));
                }
            }
        }

        window.onload = connectWS;
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    """Serves the institutional cyberpunk dashboard."""
    return HTMLResponse(content=DASHBOARD_HTML)

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Mega-22 Dashboard Server")
    parser.add_argument("--port", type=int, default=8080, help="Port to bind (default: 8080)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    args = parser.parse_args()
    
    logger.info(f"🚀 Starting Mega-22 Dashboard on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

if __name__ == "__main__":
    main()
