"""
═══════════════════════════════════════════════════════════════════════
  MT5 ZeroMQ Server v5.0 (Ultra-Fast & Multi-Asset Symbol Resolver)
═══════════════════════════════════════════════════════════════════════
  Streams required assets in real-time:
  1. Gold (XAUUSD)
  2. Silver (XAGUSD)
  3. Dollar Index (DXY / USDX / DX)
  4. US 10-Year Bonds (US10Y / USTBOND / TNX)
  5. Volatility Index (VIX / VOLX)
═══════════════════════════════════════════════════════════════════════
"""
import zmq
import msgpack
import time
import signal
import threading
from datetime import datetime, timedelta
import MetaTrader5 as mt5

class MT5ZmqServerV5:
    def __init__(self, pub_port=15555, rep_port=15556):
        self.pub_port = pub_port
        self.rep_port = rep_port
        self.running = False
        
        # REQUIRED MACRO ASSETS & BROKER ALIAS PATTERNS
        self.target_patterns = {
            "GOLD": ["XAUUSD", "GOLD", "XAUUSD.a", "XAUUSDm"],
            "SILVER": ["XAGUSD", "SILVER", "XAGUSD.a"],
            "DXY": ["DXY", "USDX", "DX", "USD_INDEX", "DXY.index", "USDIndex"],
            "USTBOND": ["US10Y", "USTBOND", "TNX", "10Y_BOND", "US10Y.bond", "US10Y_BOND"],
            "VIX": ["VIX", "VOLX", "VIX.index", "VOLATILITY", "VIXindex"]
        }
        self.active_symbols = []
        self.tick_interval = 0.02  # 20ms (50 ticks/sec ultra-fast multi-asset stream)
        self.ctx = zmq.Context()
        self._point_cache = {}
        
        # BIND SOCKETS IMMEDIATELY AT INIT (WITH SO_REUSEADDR GUARD)
        self.pub = self.ctx.socket(zmq.PUB)
        self.pub.setsockopt(zmq.SNDHWM, 5000)
        self.pub.setsockopt(zmq.LINGER, 0)
        try:
            self.pub.setsockopt(zmq.SO_REUSEADDR, 1)
        except Exception:
            pass
        self.pub.bind(f"tcp://127.0.0.1:{self.pub_port}")

        self.rep = self.ctx.socket(zmq.REP)
        self.rep.setsockopt(zmq.RCVTIMEO, 1000)
        self.rep.setsockopt(zmq.LINGER, 0)
        try:
            self.rep.setsockopt(zmq.SO_REUSEADDR, 1)
        except Exception:
            pass
        self.rep.bind(f"tcp://127.0.0.1:{self.rep_port}")
        
        print(f"  📡 [PUB STREAM] Active on tcp://127.0.0.1:{self.pub_port}")
        print(f"  ⚡ [REP ORDERS] Active on tcp://127.0.0.1:{self.rep_port}")

    def start(self):
        print(f"[SERVER v5 Multi-Asset] Initializing MetaTrader 5 Connection...")
        if not mt5.initialize():
            print(f"❌ [ERROR] MT5 Init failed: {mt5.last_error()}")
            return

        info = mt5.account_info()
        if info:
            print(f"  ✅ Connected: Account #{info.login} | Server: {info.server}")
            print(f"  💰 Balance: ${info.balance:,.2f} | Equity: ${info.equity:,.2f}")

        # Fetch all available symbols in broker's MarketWatch
        all_symbols = mt5.symbols_get() or []
        available_sym_names = [s.name for s in all_symbols]

        print(f"\n🔍 [SYMBOL RESOLVER] Searching broker MarketWatch for Required Macro Assets...")
        
        for category, patterns in self.target_patterns.items():
            matched_symbol = None
            for p in patterns:
                if p in available_sym_names or mt5.symbol_select(p, True):
                    matched_symbol = p
                    break
            
            if not matched_symbol:
                # Fuzzy search in available symbol names
                for name in available_sym_names:
                    if any(pat.lower() in name.lower() for pat in patterns):
                        matched_symbol = name
                        break
                        
            if matched_symbol:
                mt5.symbol_select(matched_symbol, True)
                si = mt5.symbol_info(matched_symbol)
                if si:
                    self._point_cache[matched_symbol] = si.point
                    if matched_symbol not in self.active_symbols:
                        self.active_symbols.append(matched_symbol)
                        print(f"  ✅ [RESOLVED ASSET] {category:<8} -> {matched_symbol} (Point: {si.point})")
            else:
                print(f"  ⚠️ [NOT OFFERED BY BROKER] {category} (Broker '{info.server}' does not offer live ticks for {category})")

        if "XAUUSD" not in self.active_symbols:
            mt5.symbol_select("XAUUSD", True)
            self.active_symbols.append("XAUUSD")

        print(f"\n📡 [ACTIVE MULTI-ASSET STREAM]: {self.active_symbols}\n")

        self.running = True

        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        pub_thread = threading.Thread(target=self._tick_publisher, daemon=True)
        pub_thread.start()

        self._order_responder()

    def _shutdown(self, signum=None, frame=None):
        if not self.running:
            return
        print("\n  [SHUTDOWN] Terminating MT5 ZMQ Server v5...")
        self.running = False
        try:
            mt5.shutdown()
        except Exception:
            pass
        try:
            self.pub.close(linger=0)
            self.rep.close(linger=0)
            self.ctx.destroy(linger=0)
        except Exception:
            pass
        print("  [SHUTDOWN] Cleanup complete.")

    def _tick_publisher(self):
        sym_bytes = {s: s.encode() for s in self.active_symbols}
        _packb = msgpack.packb
        _sleep = time.sleep
        
        while self.running:
            try:
                for symbol in self.active_symbols:
                    tick = mt5.symbol_info_tick(symbol)
                    if tick and tick.bid > 0:
                        data = _packb({
                            "s": symbol,
                            "b": tick.bid,
                            "a": tick.ask,
                            "t": tick.time_msc,
                            "v": tick.volume_real,
                        })
                        self.pub.send_multipart([sym_bytes[symbol], data], flags=zmq.NOBLOCK)
                _sleep(self.tick_interval)
            except Exception:
                time.sleep(0.5)

    def _order_responder(self):
        while self.running:
            try:
                try:
                    msg = self.rep.recv()
                except zmq.Again:
                    continue
                    
                req = msgpack.unpackb(msg, raw=False)
                cmd = req.get("cmd", "")

                if cmd == "ping":
                    self.rep.send(msgpack.packb({"ok": True, "ts": int(time.time() * 1000)}))

                elif cmd == "account":
                    acc = mt5.account_info()
                    if acc:
                        self.rep.send(msgpack.packb({
                            "login": acc.login,
                            "balance": acc.balance,
                            "equity": acc.equity,
                            "margin": acc.margin,
                            "margin_free": acc.margin_free,
                            "profit": acc.profit,
                            "server": acc.server,
                        }))
                    else:
                        mt5.initialize()
                        self.rep.send(msgpack.packb({"error": "MT5 Reconnected"}))

                elif cmd == "get_tick":
                    symbol = req.get("symbol", "XAUUSD")
                    tick = mt5.symbol_info_tick(symbol)
                    if tick:
                        self.rep.send(msgpack.packb({
                            "bid": tick.bid, "ask": tick.ask,
                            "time_msc": tick.time_msc,
                            "volume_real": tick.volume_real,
                        }))
                    else:
                        self.rep.send(msgpack.packb({"error": "Tick unavailable"}))

                elif cmd == "order_now":
                    symbol = req.get("symbol", "XAUUSD")
                    volume = float(req.get("volume", 0.01))
                    order_type = int(req.get("type", 0))
                    sl_dist = float(req.get("sl_distance", 0.0))
                    tp_dist = float(req.get("tp_distance", 0.0))
                    magic = int(req.get("magic", 555000))
                    comment = req.get("comment", "Simons_v5")

                    tick = mt5.symbol_info_tick(symbol)
                    if not tick:
                        self.rep.send(msgpack.packb({"error": "No tick for order"}))
                        continue

                    req_price = tick.ask if order_type == 0 else tick.bid
                    if order_type == 0:
                        sl = req_price - sl_dist if sl_dist > 0 else 0.0
                        tp = req_price + tp_dist if tp_dist > 0 else 0.0
                    else:
                        sl = req_price + sl_dist if sl_dist > 0 else 0.0
                        tp = req_price - tp_dist if tp_dist > 0 else 0.0

                    request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "symbol": symbol,
                        "volume": volume,
                        "type": order_type,
                        "price": req_price,
                        "sl": round(sl, 2) if sl else 0.0,
                        "tp": round(tp, 2) if tp else 0.0,
                        "deviation": 20,
                        "magic": magic,
                        "comment": comment,
                        "type_time": mt5.ORDER_TIME_GTC,
                        "type_filling": mt5.ORDER_FILLING_IOC,
                    }

                    t0 = time.perf_counter()
                    result = mt5.order_send(request)
                    exec_ms = (time.perf_counter() - t0) * 1000.0

                    if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                        fill_p = float(result.price) if result.price > 0 else req_price
                        self.rep.send(msgpack.packb({
                            "retcode": result.retcode,
                            "deal": result.deal,
                            "order": result.order,
                            "price": fill_p,
                            "request_price": req_price,
                            "exec_ms": exec_ms,
                            "comment": result.comment
                        }))
                    else:
                        err_msg = str(mt5.last_error()) if not result else f"Retcode: {result.retcode}"
                        self.rep.send(msgpack.packb({"error": err_msg}))

                elif cmd == "positions":
                    positions = mt5.positions_get(symbol=req.get("symbol", "XAUUSD"))
                    pos_list = []
                    if positions:
                        for p in positions:
                            pos_list.append({
                                "ticket": p.ticket,
                                "symbol": p.symbol,
                                "type": p.type,
                                "volume": p.volume,
                                "price_open": p.price_open,
                                "sl": p.sl,
                                "tp": p.tp,
                                "profit": p.profit,
                                "magic": p.magic
                            })
                    self.rep.send(msgpack.packb({"positions": pos_list}))

                elif cmd == "close_all":
                    positions = mt5.positions_get(symbol=req.get("symbol", "XAUUSD"))
                    closed_cnt = 0
                    if positions:
                        for p in positions:
                            tick = mt5.symbol_info_tick(p.symbol)
                            close_price = tick.bid if p.type == 0 else tick.ask
                            c_req = {
                                "action": mt5.TRADE_ACTION_DEAL,
                                "symbol": p.symbol,
                                "volume": p.volume,
                                "type": 1 if p.type == 0 else 0,
                                "position": p.ticket,
                                "price": close_price,
                                "deviation": 20,
                                "magic": p.magic,
                                "comment": "Close_All_V5"
                            }
                            res = mt5.order_send(c_req)
                            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                                closed_cnt += 1
                    self.rep.send(msgpack.packb({"closed": closed_cnt}))

                else:
                    self.rep.send(msgpack.packb({"error": f"Unknown command: {cmd}"}))

            except Exception as e:
                try:
                    self.rep.send(msgpack.packb({"error": str(e)}))
                except Exception:
                    pass

if __name__ == "__main__":
    server = MT5ZmqServerV5()
    server.start()
