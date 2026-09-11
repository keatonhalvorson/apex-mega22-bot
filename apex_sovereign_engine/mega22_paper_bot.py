"""
Mega-22 Sovereign Real-Time Spot Paper Trading Engine
Connects directly to Binance Spot Public Data (WebSocket + Async REST Fallback).
100% Halal Spot 1x Pure Cash Trading Bot with exact 1:1 parity to the 32-month backtest.
Ultra-lightweight (< 50MB RAM, < 1% CPU).
"""

import os
import sys
import time
import json
import asyncio
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
import aiohttp
import websockets
import numpy as np
import pandas as pd

from mega22_constants import (
    MEGA_22, GOLDEN_11, TITAN_11, MACRO_SYMBOL, ALL_SYMBOLS,
    INITIAL_CAPITAL, MAX_SLOTS, SLOT_FRACTION, FEE_RATE, SLIPPAGE_RATE,
    STOP_LOSS_TARGET, TAKE_PROFIT_TARGET, PARABOLIC_LOCK_TIERS,
    TRAILING_TRIGGER_MIN_PNL, TRAILING_OFFSET, STALL_BARS_THRESHOLD,
    COOLDOWN_STOP_LOSS_BARS, CONSECUTIVE_STOPS_TRIGGER, COOLDOWN_GLOBAL_GUARD_BARS,
    BUFFER_MAX_BARS, BTC_HAWKES_MAX_INTENSITY, BTC_24H_MIN_PCT, BTC_4H_MIN_PCT
)
from mega22_strategy import Mega22StrategyEngine, Position, TradeRecord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Mega22Bot")

JOURNAL_FILE = Path("/home/atheer/Desktop/ApexPredator/download data/apex_sovereign_engine/live_trade_journal.json")
BINANCE_REST_URLS = [
    "https://api.binance.com",
    "https://data-api.binance.vision"
]
BINANCE_WS_URL = "wss://stream.binance.com:9443/stream"

class Mega22PaperBot:
    """
    Production-Grade Real-Time Spot Paper Trading Bot.
    Runs asynchronously, maintaining fixed-size ring buffers in memory.
    """
    def __init__(self, journal_path: Path = JOURNAL_FILE):
        self.journal_path = journal_path
        self.capital: float = INITIAL_CAPITAL
        self.available_cash: float = INITIAL_CAPITAL
        self.active_positions: Dict[str, Position] = {}
        self.trade_history: List[TradeRecord] = []
        
        # Risk & Cooldown State
        self.bar_index: int = 0
        self.cooldowns: Dict[str, int] = {s: -1 for s in MEGA_22}
        self.consecutive_stops: int = 0
        self.stoploss_guard_until: int = -1
        
        # In-memory Candle Ring Buffers (maxlen 300)
        self.candle_buffers: Dict[str, deque] = {s: deque(maxlen=BUFFER_MAX_BARS) for s in ALL_SYMBOLS}
        self.latest_prices: Dict[str, float] = {s: 0.0 for s in ALL_SYMBOLS}
        self.latest_indicators: Dict[str, Dict[str, Any]] = {}
        
        # Macro BTC State
        self.btc_hawkes: float = 0.0
        self.btc_24h: float = 0.0
        self.btc_4h: float = 0.0
        self.is_btc_safe: bool = True
        
        # Event Notification Callbacks
        self.listeners: List[Callable[[str, Dict[str, Any]], None]] = []
        self.event_logs: deque = deque(maxlen=200)
        
        # Bot State
        self.is_running: bool = False
        self.last_ws_message_time: float = time.time()
        
        # Multi-Stream Synchronization State
        self._closed_candles_in_interval: Dict[pd.Timestamp, set] = {}
        self._pending_debounce_tasks: Dict[pd.Timestamp, asyncio.Task] = {}
        self._processed_intervals: set = set()

        # Load persistent state
        self._load_journal()

    def add_listener(self, callback: Callable[[str, Dict[str, Any]], None]):
        """Register a callback for real-time WebSocket dashboard broadcast."""
        self.listeners.append(callback)

    def _broadcast(self, event_type: str, data: Dict[str, Any]):
        """Broadcast state updates to all registered dashboard listeners."""
        for cb in self.listeners:
            try:
                cb(event_type, data)
            except Exception as e:
                logger.error(f"Error notifying listener: {e}")

    def log_event(self, message: str, level: str = "INFO"):
        """Record an event in the ring log buffer and broadcast."""
        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S"),
            "level": level,
            "message": message
        }
        self.event_logs.append(entry)
        if level == "INFO":
            logger.info(message)
        elif level == "WARNING":
            logger.warning(message)
        elif level == "ERROR":
            logger.error(message)
        self._broadcast("log", entry)

    def _load_journal(self):
        """Loads persistent portfolio balance and trade records from disk."""
        if not self.journal_path.exists():
            self._save_journal()
            return
        try:
            with open(self.journal_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.capital = float(data.get("capital", INITIAL_CAPITAL))
            self.available_cash = float(data.get("available_cash", self.capital))
            self.bar_index = int(data.get("bar_index", 0))
            self.consecutive_stops = int(data.get("consecutive_stops", 0))
            self.stoploss_guard_until = int(data.get("stoploss_guard_until", -1))
            self.cooldowns = data.get("cooldowns", {s: -1 for s in MEGA_22})
            
            raw_pos = data.get("active_positions", {})
            self.active_positions = {}
            for sym, pos_d in raw_pos.items():
                self.active_positions[sym] = Position.from_dict(pos_d)
                
            raw_hist = data.get("history", [])
            self.trade_history = [TradeRecord(**t) for t in raw_hist]
            self.log_event(f"Loaded journal: Cash=${self.available_cash:.2f}, {len(self.active_positions)} open positions, {len(self.trade_history)} closed trades (Bar Index: {self.bar_index}).")
        except Exception as e:
            logger.error(f"Error loading journal: {e}. Starting fresh.")
            self._save_journal()

    def _save_journal(self):
        """Atomically saves portfolio state to disk."""
        try:
            state = {
                "last_update": datetime.now(timezone.utc).isoformat(),
                "capital": round(self.get_total_equity(), 2),
                "available_cash": round(self.available_cash, 2),
                "bar_index": self.bar_index,
                "consecutive_stops": self.consecutive_stops,
                "stoploss_guard_until": self.stoploss_guard_until,
                "cooldowns": self.cooldowns,
                "active_positions": {s: p.to_dict() for s, p in self.active_positions.items()},
                "history": [t.to_dict() for t in self.trade_history],
                "stats": self.get_summary_stats()
            }
            tmp_path = self.journal_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
            tmp_path.replace(self.journal_path)
        except Exception as e:
            logger.error(f"Failed to save journal: {e}")

    def get_total_equity(self) -> float:
        """Total portfolio equity = cash + sum(notional + unrealized gross - est exit fee)."""
        equity = self.available_cash
        for sym, pos in self.active_positions.items():
            unrealized_gross = (pos.current_px - pos.px) / pos.px * pos.notional if pos.current_px > 0 else 0.0
            est_exit_fee = pos.notional * FEE_RATE
            equity += (pos.notional + unrealized_gross - est_exit_fee)
        return equity

    def get_summary_stats(self) -> Dict[str, Any]:
        """Computes comprehensive quantitative performance metrics."""
        total_trades = len(self.trade_history)
        if total_trades == 0:
            return {
                "total_trades": 0,
                "win_rate": 0.0,
                "net_profit": 0.0,
                "roe_pct": 0.0,
                "profit_factor": 0.0,
                "winning_trades": 0,
                "losing_trades": 0,
                "max_drawdown_pct": 0.0,
                "avg_trade_net": 0.0,
                "best_trade_pnl": 0.0,
                "worst_trade_pnl": 0.0,
                "last_trade": None
            }
        
        wins = [t for t in self.trade_history if t.net > 0]
        losses = [t for t in self.trade_history if t.net <= 0]
        gross_wins = sum(t.net for t in wins)
        gross_losses = abs(sum(t.net for t in losses))
        pf = (gross_wins / gross_losses) if gross_losses > 0 else 99.0
        
        tot_net = sum(t.net for t in self.trade_history)
        roe = (tot_net / INITIAL_CAPITAL) * 100.0
        win_rate = (len(wins) / total_trades) * 100.0
        avg_trade = tot_net / total_trades
        best_pnl = max(t.pnl_pct for t in self.trade_history)
        worst_pnl = min(t.pnl_pct for t in self.trade_history)

        # Trade-level closed-equity drawdown
        cum_equity = [INITIAL_CAPITAL]
        eq = INITIAL_CAPITAL
        for t in self.trade_history:
            eq += t.net
            cum_equity.append(eq)
        peaks = np.maximum.accumulate(cum_equity)
        dds = (np.array(cum_equity) - peaks) / peaks * 100.0
        max_dd = abs(float(np.min(dds))) if len(dds) > 0 else 0.0

        last_t = self.trade_history[-1].to_dict() if self.trade_history else None

        return {
            "total_trades": total_trades,
            "win_rate": round(win_rate, 1),
            "net_profit": round(tot_net, 2),
            "roe_pct": round(roe, 2),
            "profit_factor": round(pf, 2),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "max_drawdown_pct": round(max_dd, 2),
            "avg_trade_net": round(avg_trade, 2),
            "best_trade_pnl": round(best_pnl, 2),
            "worst_trade_pnl": round(worst_pnl, 2),
            "last_trade": last_t
        }

    async def bootstrap_historical_klines(self):
        """
        Concurrently fetches initial 300 5m bars for all 23 pairs via async REST in ~1s.
        Ensures rolling indicators have full warm-up immediately upon launch.
        """
        self.log_event("📡 Initializing High-Speed Market Bootstrap (300 bars per pair)...")
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            tasks = []
            for sym in ALL_SYMBOLS:
                tasks.append(self._fetch_symbol_klines(session, sym))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            successful = 0
            for sym, res in zip(ALL_SYMBOLS, results):
                if isinstance(res, list) and len(res) > 0:
                    self.candle_buffers[sym].extend(res)
                    self.latest_prices[sym] = res[-1]['close']
                    successful += 1
                else:
                    self.log_event(f"Warning: Failed initial bootstrap for {sym}: {res}", "WARNING")
                    
            self.log_event(f"✅ Market Bootstrap Completed: {successful}/{len(ALL_SYMBOLS)} pairs primed with live history.")
            self.update_all_indicators()

    async def _fetch_symbol_klines(self, session: aiohttp.ClientSession, symbol: str) -> List[Dict[str, Any]]:
        """Fetch 5m klines from Binance REST."""
        for base in BINANCE_REST_URLS:
            url = f"{base}/api/v3/klines"
            params = {"symbol": symbol, "interval": "5m", "limit": BUFFER_MAX_BARS}
            try:
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        raw = await resp.json()
                        bars = []
                        for b in raw:
                            vol = float(b[5])
                            tb = float(b[9])
                            ts = max(vol - tb, 1e-6)
                            bars.append({
                                'open_time': pd.to_datetime(b[0], unit='ms'),
                                'open': float(b[1]),
                                'high': float(b[2]),
                                'low': float(b[3]),
                                'close': float(b[4]),
                                'volume': vol,
                                'taker_buy': tb,
                                'taker_sell': ts,
                                'tbv_ratio': tb / max(vol, 1e-6)
                            })
                        return bars
            except Exception:
                continue
        return []

    def _df_from_buffer(self, sym: str) -> Optional[pd.DataFrame]:
        """Convert deque buffer to DataFrame."""
        buf = self.candle_buffers[sym]
        if len(buf) < 30:
            return None
        df = pd.DataFrame(list(buf))
        return df

    def update_all_indicators(self):
        """
        Runs mathematical indicator calculations on recent 5m candle buffers.
        Updates BTC Hawkes shield and altcoin explosion alpha scores.
        """
        df_btc = self._df_from_buffer(MACRO_SYMBOL)
        if df_btc is None or len(df_btc) < 50:
            return
            
        df_btc_5m = df_btc[['open_time', 'close']].rename(columns={'close': 'btc_c'})
        df_btc_5m['btc_24h'] = (df_btc_5m['btc_c'] / df_btc_5m['btc_c'].shift(288) - 1.0) * 100.0
        df_btc_5m['btc_4h'] = (df_btc_5m['btc_c'] / df_btc_5m['btc_c'].shift(48) - 1.0) * 100.0
        df_btc_5m = Mega22StrategyEngine.compute_btc_hawkes(df_btc_5m)
        
        last_btc = df_btc_5m.iloc[-1]
        self.btc_hawkes = float(last_btc['btc_hawkes'])
        self.btc_24h = float(last_btc['btc_24h']) if not pd.isna(last_btc['btc_24h']) else 0.0
        self.btc_4h = float(last_btc['btc_4h']) if not pd.isna(last_btc['btc_4h']) else 0.0
        self.is_btc_safe = (self.btc_24h > BTC_24H_MIN_PCT) and (self.btc_4h > BTC_4H_MIN_PCT) and (self.btc_hawkes <= BTC_HAWKES_MAX_INTENSITY)
        
        for sym in MEGA_22:
            df_alt = self._df_from_buffer(sym)
            if df_alt is None:
                continue
            try:
                df_ind = Mega22StrategyEngine.calculate_indicators(df_alt, df_btc_5m)
                if len(df_ind) == 0:
                    continue
                row = df_ind.iloc[-1]
                self.latest_indicators[sym] = {
                    'sym': sym,
                    'price': float(row['close']),
                    'motif_dist': float(row['motif_distance']),
                    'fisher_z': float(row['fisher_z']),
                    'ko_z': float(row['ko_z']),
                    'ofi': float(row['ofi']),
                    'score': float(row['explosion_alpha_score']),
                    'is_cand': int(row['is_candidate']),
                    'exit_long': int(row['exit_long']),
                    'bb_mid': float(row['bb_mid']),
                    'bb_lower': float(row['bb_lower'])
                }
            except Exception as e:
                logger.debug(f"Indicator calculation skipped for {sym}: {e}")

    def on_tick_update(self, symbol: str, current_px: float, high_px: float, low_px: float):
        """
        Processes real-time intra-bar price ticks from WebSocket.
        Immediately verifies dynamic stop loss, parabolic locks, and take profit.
        """
        self.latest_prices[symbol] = current_px
        
        if symbol in self.active_positions:
            pos = self.active_positions[symbol]
            event, updated_pos = Mega22StrategyEngine.evaluate_position_step(
                pos=pos,
                c=current_px,
                h=high_px,
                l=low_px,
                exit_sig=0,
                held=self.bar_index - pos.i
            )
            self.active_positions[symbol] = updated_pos
            
            if event is not None:
                exit_px, reason = event
                self._execute_position_close(symbol, exit_px, reason)

    async def on_candle_closed(self, symbol: str, bar_data: Dict[str, Any]):
        """
        Called when a 5-minute candle closes for a symbol.
        1. Appends bar to ring buffer.
        2. Evaluates exit triggers immediately for active positions.
        3. Synchronizes across all 23 symbols before evaluating new entries.
        """
        self.candle_buffers[symbol].append(bar_data)
        self.latest_prices[symbol] = bar_data['close']
        
        # Check active position exit on closed candle
        if symbol in self.active_positions:
            df_s = self._df_from_buffer(symbol)
            if df_s is not None and len(df_s) >= 5:
                typical_px = (df_s['high'] + df_s['low'] + df_s['close']) / 3.0
                bb_mid = typical_px.rolling(20, min_periods=5).mean().iloc[-1]
                exit_sig = int(bar_data['close'] > bb_mid)
            else:
                exit_sig = 0
                
            pos = self.active_positions[symbol]
            event, updated_pos = Mega22StrategyEngine.evaluate_position_step(
                pos=pos,
                c=bar_data['close'],
                h=bar_data['high'],
                l=bar_data['low'],
                exit_sig=exit_sig,
                held=self.bar_index - pos.i
            )
            self.active_positions[symbol] = updated_pos
            if event is not None:
                exit_px, reason = event
                self._execute_position_close(symbol, exit_px, reason)

        # Multi-Stream Synchronization by interval timestamp
        interval_t = bar_data['open_time']
        if interval_t not in self._closed_candles_in_interval:
            self._closed_candles_in_interval[interval_t] = set()
        self._closed_candles_in_interval[interval_t].add(symbol)
        
        # Check if all pairs have reported closed klines for this interval
        if len(self._closed_candles_in_interval[interval_t]) >= len(ALL_SYMBOLS):
            if interval_t in self._pending_debounce_tasks:
                task = self._pending_debounce_tasks.pop(interval_t)
                task.cancel()
            self._process_interval_close(interval_t)
        else:
            # Schedule debounce fallback: 1.5s if MACRO_SYMBOL, else 3.0s fallback
            if interval_t not in self._pending_debounce_tasks and interval_t not in self._processed_intervals:
                delay = 1.5 if symbol == MACRO_SYMBOL else 3.0
                task = asyncio.create_task(self._debounce_interval_close(interval_t, delay=delay))
                self._pending_debounce_tasks[interval_t] = task

    async def _debounce_interval_close(self, interval_t: pd.Timestamp, delay: float):
        try:
            await asyncio.sleep(delay)
            self._pending_debounce_tasks.pop(interval_t, None)
            self._process_interval_close(interval_t)
        except asyncio.CancelledError:
            pass

    def _process_interval_close(self, interval_t: pd.Timestamp):
        """Processes interval close: updates all indicators, executes new entries, increments bar index."""
        if interval_t in self._processed_intervals:
            return
        self._processed_intervals.add(interval_t)
        if len(self._processed_intervals) > 100:
            self._processed_intervals.pop()
            
        self._closed_candles_in_interval.pop(interval_t, None)
        
        self.bar_index += 1
        self.update_all_indicators()
        self._evaluate_portfolio_entries()
        self._save_journal()
        self._broadcast("bar_close", {
            "bar_index": self.bar_index,
            "interval": str(interval_t),
            "btc_hawkes": round(self.btc_hawkes, 4),
            "is_btc_safe": self.is_btc_safe
        })

    def _execute_position_close(self, symbol: str, exit_px: float, reason: str):
        """Executes position closure, updates cash balance, records trade."""
        if symbol not in self.active_positions:
            return
            
        pos = self.active_positions.pop(symbol)
        gross = (exit_px - pos.px) / pos.px * pos.notional
        exit_fee = pos.notional * FEE_RATE
        entry_fee = pos.entry_fee
        net = gross - exit_fee - entry_fee
        pnl_pct = (exit_px / pos.px - 1.0) * 100.0
        
        # Cash update: refund notional + gross - exit_fee
        self.available_cash += (pos.notional + gross - exit_fee)
        
        # Cooldown management
        if 'STOP_LOSS' in reason:
            self.consecutive_stops += 1
            self.cooldowns[symbol] = self.bar_index + COOLDOWN_STOP_LOSS_BARS
            if self.consecutive_stops >= CONSECUTIVE_STOPS_TRIGGER:
                self.stoploss_guard_until = self.bar_index + COOLDOWN_GLOBAL_GUARD_BARS
                self.log_event(f"🛡️ Risk Circuit Tripped: 2 consecutive stops! Global pause until bar {self.stoploss_guard_until}.", "WARNING")
        else:
            self.consecutive_stops = 0
            
        trade = TradeRecord(
            sym=symbol,
            entry_time=pos.entry_time,
            exit_time=datetime.now(timezone.utc).isoformat(),
            entry_i=pos.i,
            exit_i=self.bar_index,
            entry_px=pos.px,
            exit_px=exit_px,
            pnl_pct=pnl_pct,
            notional=pos.notional,
            gross=gross,
            net=net,
            entry_fee=entry_fee,
            exit_fee=exit_fee,
            reason=reason,
            bars_held=self.bar_index - pos.i,
            cap_after=self.get_total_equity()
        )
        self.trade_history.append(trade)
        
        emoji = "🎯" if net > 0 else "🛑"
        self.log_event(f"{emoji} CLOSED {symbol} via {reason} | PnL: {pnl_pct:+.2f}% (${net:+.2f}) | Cash: ${self.available_cash:.2f}")
        
        self._save_journal()
        self._broadcast("trade_closed", trade.to_dict())

    def _evaluate_portfolio_entries(self):
        """
        Evaluates top-ranked candidates across all 22 coins and executes entries.
        Matches exact logic of simulate_engine_rigorous lines 187-208.
        """
        if len(self.active_positions) >= MAX_SLOTS:
            return
        if self.bar_index <= self.stoploss_guard_until:
            return
            
        avail_slots = MAX_SLOTS - len(self.active_positions)
        cands = []
        for sym in MEGA_22:
            if sym in self.active_positions:
                continue
            if self.bar_index <= self.cooldowns.get(sym, -1):
                continue
            ind = self.latest_indicators.get(sym)
            if ind and ind['is_cand'] == 1:
                cands.append((sym, ind['score'], ind['price']))
                
        # Rank by Explosion Alpha Score descending
        cands.sort(key=lambda x: x[1], reverse=True)
        
        for sym, score, raw_px in cands[:avail_slots]:
            target_notional = self.available_cash * SLOT_FRACTION
            if self.available_cash >= target_notional and target_notional > 50.0:
                epx = raw_px * (1.0 + SLIPPAGE_RATE)
                ef = target_notional * FEE_RATE
                self.available_cash -= (target_notional + ef)
                
                pos = Position(
                    sym=sym,
                    px=epx,
                    notional=target_notional,
                    entry_fee=ef,
                    i=self.bar_index,
                    entry_time=datetime.now(timezone.utc).isoformat(),
                    stop=STOP_LOSS_TARGET,
                    highest_seen=epx,
                    lowest_seen=epx,
                    current_px=epx
                )
                self.active_positions[sym] = pos
                self.log_event(f"🚀 ENTERED {sym} @ ${epx:.4f} | Size: ${target_notional:.2f} | Alpha Score: {score:.2f} | Remaining Cash: ${self.available_cash:.2f}")
                self._save_journal()
                self._broadcast("position_opened", pos.to_dict())

    def manual_close_position(self, symbol: str) -> bool:
        """Emergency manual close of an active position from the dashboard."""
        if symbol in self.active_positions:
            curr_px = self.latest_prices.get(symbol, self.active_positions[symbol].px)
            exit_px = curr_px * (1.0 - SLIPPAGE_RATE)
            self._execute_position_close(symbol, exit_px, "MANUAL_OVERRIDE")
            return True
        return False

    def reset_portfolio(self, capital: float = INITIAL_CAPITAL):
        """Reset paper trading state to initial capital."""
        self.capital = capital
        self.available_cash = capital
        self.bar_index = 0
        self.active_positions.clear()
        self.trade_history.clear()
        self.consecutive_stops = 0
        self.stoploss_guard_until = -1
        self.cooldowns = {s: -1 for s in MEGA_22}
        self._closed_candles_in_interval.clear()
        self._processed_intervals.clear()
        for task in self._pending_debounce_tasks.values():
            task.cancel()
        self._pending_debounce_tasks.clear()
        self.log_event(f"🔄 Portfolio Reset: Capital initialized to ${capital:.2f}")
        self._save_journal()
        self._broadcast("reset", {"capital": capital})

    async def run(self):
        """
        Main async event loop: connects to Binance WebSocket and processes real-time klines.
        Includes auto-reconnect and watchdog timer.
        """
        self.is_running = True
        await self.bootstrap_historical_klines()
        
        streams = "/".join([f"{s.lower()}@kline_5m" for s in ALL_SYMBOLS])
        ws_url = f"{BINANCE_WS_URL}?streams={streams}"
        
        while self.is_running:
            try:
                # Reconnection after gap detection (> 60s since last msg): re-sync klines
                if time.time() - self.last_ws_message_time > 60:
                    self.log_event("🔄 Re-syncing 300 bars per pair via REST after stream interruption...")
                    await self.bootstrap_historical_klines()

                self.log_event(f"🔌 Connecting to Binance Stream ({len(ALL_SYMBOLS)} pairs)...")
                async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                    self.log_event("🟢 Live WebSocket Connected. Receiving Real-Time Market Ticks.")
                    while self.is_running:
                        msg = await ws.recv()
                        self.last_ws_message_time = time.time()
                        data = json.loads(msg)
                        k = data.get('data', {}).get('k', {})
                        if not k:
                            continue
                            
                        sym = k['s']
                        c = float(k['c'])
                        h = float(k['h'])
                        l = float(k['l'])
                        is_closed = k['x']
                        
                        # Process real-time tick
                        self.on_tick_update(sym, c, h, l)
                        
                        # Process closed candle
                        if is_closed:
                            vol = float(k['v'])
                            tb = float(k['V'])
                            ts = max(vol - tb, 1e-6)
                            bar = {
                                'open_time': pd.to_datetime(k['t'], unit='ms'),
                                'open': float(k['o']),
                                'high': h,
                                'low': l,
                                'close': c,
                                'volume': vol,
                                'taker_buy': tb,
                                'taker_sell': ts,
                                'tbv_ratio': tb / max(vol, 1e-6)
                            }
                            await self.on_candle_closed(sym, bar)
                            
            except Exception as e:
                self.log_event(f"WebSocket warning: {e}. Reconnecting in 3s...", "WARNING")
                await asyncio.sleep(3)

    def get_full_state(self) -> Dict[str, Any]:
        """Provides full snapshot of the bot for the dashboard."""
        equity = self.get_total_equity()
        stats = self.get_summary_stats()
        
        # Build scanner leaderboard
        leaderboard = []
        for sym in MEGA_22:
            ind = self.latest_indicators.get(sym, {})
            px = self.latest_prices.get(sym, 0.0)
            in_cooldown = self.bar_index <= self.cooldowns.get(sym, -1)
            status = "POSITION_OPEN" if sym in self.active_positions else (
                "COOLDOWN" if in_cooldown else (
                    "TRIGGERED" if ind.get('is_cand', 0) == 1 else "SCANNING"
                )
            )
            leaderboard.append({
                "sym": sym,
                "price": px,
                "motif_dist": ind.get('motif_dist', 99.0),
                "fisher_z": ind.get('fisher_z', 0.0),
                "ko_z": ind.get('ko_z', 0.0),
                "ofi": ind.get('ofi', 0.0),
                "score": ind.get('score', 0.0),
                "is_candidate": ind.get('is_cand', 0),
                "status": status
            })
            
        leaderboard.sort(key=lambda x: x['score'], reverse=True)
        
        unrealized = sum(p.unrealized_pnl for p in self.active_positions.values())
        total_pnl = equity - INITIAL_CAPITAL
        total_roe = (total_pnl / INITIAL_CAPITAL) * 100.0
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "bar_index": self.bar_index,
            "equity": round(equity, 2),
            "available_cash": round(self.available_cash, 2),
            "unrealized_pnl": round(unrealized, 2),
            "total_pnl": round(total_pnl, 2),
            "total_roe_pct": round(total_roe, 2),
            "net_profit": stats['net_profit'],
            "roe_pct": stats['roe_pct'],
            "win_rate": stats['win_rate'],
            "profit_factor": stats['profit_factor'],
            "total_trades": stats['total_trades'],
            "winning_trades": stats['winning_trades'],
            "losing_trades": stats['losing_trades'],
            "max_drawdown_pct": stats['max_drawdown_pct'],
            "avg_trade_net": stats['avg_trade_net'],
            "best_trade_pnl": stats['best_trade_pnl'],
            "worst_trade_pnl": stats['worst_trade_pnl'],
            "last_trade": stats['last_trade'],
            "max_slots": MAX_SLOTS,
            "used_slots": len(self.active_positions),
            "btc_hawkes": round(self.btc_hawkes, 4),
            "btc_24h": round(self.btc_24h, 2),
            "btc_4h": round(self.btc_4h, 2),
            "btc_price": self.latest_prices.get(MACRO_SYMBOL, 0.0),
            "is_btc_safe": self.is_btc_safe,
            "global_guard_active": self.bar_index <= self.stoploss_guard_until,
            "active_positions": [p.to_dict() for p in self.active_positions.values()],
            "recent_trades": [t.to_dict() for t in self.trade_history[-20:]],
            "leaderboard": leaderboard,
            "logs": list(self.event_logs)
        }
