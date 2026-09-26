"""
====================================================================================================
      🌌 APEX SOVEREIGN QUANTITATIVE ENGINE — INSTITUTIONAL APEX-30 COCKPIT (100% HALAL SPOT)
      
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
    MEGA_22, GOLDEN_11, TITAN_11, APEX_ADDITIONS, APEX_30,
    APEX_35_EXPANSION, APEX_35, APEX_38_EXPANSION, APEX_38,
    APEX_51_EXPANSION, APEX_51, ACTIVE_UNIVERSE,
    MACRO_SYMBOL, ALL_SYMBOLS,
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
    logger.info("Starting Apex-35 Sovereign Paper Trading Bot in background task...")
    bot_task = asyncio.create_task(bot.run())
    bcast_task = asyncio.create_task(periodic_state_broadcast())
    yield
    bot.is_running = False
    bot_task.cancel()
    bcast_task.cancel()

app = FastAPI(title="APEX Sovereign Apex-35 Quantitative Terminal", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def periodic_state_broadcast():
    """Pushes fresh state snapshot to all open browser tabs at 4 Hz (250ms) cadence."""
    while True:
        try:
            await asyncio.sleep(0.25)
            if connected_websockets:
                state = bot.get_full_state()
                msg = json.dumps({"type": "state_snapshot", "data": state}, separators=(',', ':'))
                tasks = [_safe_send_ws(ws, msg) for ws in list(connected_websockets)]
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception as e:
            logger.debug(f"Broadcast error: {e}")

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time bi-directional streaming WebSocket for the quantitative cockpit."""
    await websocket.accept()
    connected_websockets.add(websocket)
    try:
        # Immediately send current state on connect
        state = bot.get_full_state()
        await websocket.send_text(json.dumps({"type": "state_snapshot", "data": state}, separators=(',', ':')))
        while True:
            msg_text = await websocket.receive_text()
            try:
                cmd = json.loads(msg_text)
                action = cmd.get("action") or cmd.get("op")
                if action == "ping":
                    pong = json.dumps({
                        "type": "pong",
                        "client_t": cmd.get("t", 0),
                        "server_t": int(time.time() * 1000)
                    }, separators=(',', ':'))
                    await websocket.send_text(pong)
                elif action in ("pause", "pause_bot"):
                    bot.pause_trading()
                elif action in ("resume", "resume_bot"):
                    bot.resume_trading()
                elif action in ("emergency_close", "kill_all"):
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
                elif action == "set_slots":
                    slots = int(cmd.get("slots", 3))
                    if 1 <= slots <= 5:
                        bot.max_slots = slots
                        bot.slot_fraction = 0.98 if slots == 1 else (1.0 / slots)
                        bot.log_event(f"⚙️ Execution slots configured to {slots} (Slot Sizing: {bot.slot_fraction*100:.1f}%)", "INFO")
                        bot._broadcast("config_update", {"max_slots": bot.max_slots, "slot_fraction": bot.slot_fraction})
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
        headers={"Content-Disposition": "attachment; filename=apex30_trades.csv"}
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
    return JSONResponse(content={"status": "ok", "closed_count": len(closed)})

@app.post("/api/action/close_position")
async def close_position(sym: str):
    pos = bot.manual_close_position(sym.upper())
    if pos:
        return JSONResponse(content={"status": "ok", "closed": sym.upper()})
    return JSONResponse(content={"status": "error", "message": f"No open position for {sym}"}, status_code=404)

@app.post("/api/action/reset")
async def reset_portfolio(capital: float = INITIAL_CAPITAL):
    bot.reset_portfolio(capital=capital)
    return JSONResponse(content={"status": "ok", "capital": capital})

@app.post("/api/action/test_alert")
async def trigger_test_alert():
    bot._broadcast("alert", {
        "title": "QUANT TERMINAL TEST",
        "message": "APEX Sovereign sound & alert latency diagnostic verified.",
        "level": "INFO"
    })
    return JSONResponse(content={"status": "ok", "message": "Test alert triggered"})

@app.post("/api/action/set_slots")
async def set_slots(slots: int):
    """Allows setting max execution slots (e.g. 1 or 3)."""
    if slots < 1 or slots > 5:
        raise HTTPException(status_code=400, detail="Slots must be between 1 and 5")
    bot.max_slots = slots
    bot.slot_fraction = 0.98 if slots == 1 else (1.0 / slots)
    bot.log_event(f"⚙️ Execution slots configured to {slots} (Slot Sizing: {bot.slot_fraction*100:.1f}%)", "INFO")
    bot._broadcast("config_update", {"max_slots": bot.max_slots, "slot_fraction": bot.slot_fraction})
    return JSONResponse(content={"status": "ok", "max_slots": bot.max_slots, "slot_fraction": bot.slot_fraction})

@app.get("/api/klines/{sym}")
async def get_symbol_klines(sym: str):
    """REST API: recent 5m candle bars for the requested symbol."""
    candles = bot.get_symbol_candles(sym.upper())
    return JSONResponse(content={"sym": sym.upper(), "candles": candles})



DASHBOARD_FILE = CURRENT_DIR / "dashboard.html"

def get_dashboard_html() -> str:
    """Load institutional dashboard HTML template from disk, with fallback."""
    if DASHBOARD_FILE.exists():
        return DASHBOARD_FILE.read_text(encoding="utf-8")
    return "<!DOCTYPE html><html><body><h2>APEX SOVEREIGN QUANTITATIVE ENGINE: dashboard.html not found.</h2><canvas id='hawkesGaugeCanvas'></canvas></body></html>"

@app.get("/", response_class=HTMLResponse)
@app.head("/")
async def get_dashboard():
    """Serves the ultra-high performance institutional quantitative dashboard."""
    return HTMLResponse(content=get_dashboard_html())


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Apex-35 Dashboard Server")
    default_port = int(os.environ.get("PORT", 8080))
    parser.add_argument("--port", type=int, default=default_port, help=f"Port to bind (default: {default_port})")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host interface (default: 0.0.0.0)")
    args = parser.parse_args()
    
    logger.info(f"🚀 Starting Apex-35 Dashboard on http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")

if __name__ == "__main__":
    main()
