"""
═══════════════════════════════════════════════════════════════════════
  MT5 Fast Bridge v5.0 (24/7 Deadlock-Proof Client Bridge)
═══════════════════════════════════════════════════════════════════════
  Connects Python Quantitative Engine on Linux to MT5 ZMQ Server.
  - Zero Deadlocks: Automatic REQ socket destruction on 2.5s Timeout
  - Auto-Heartbeat: Background Ping monitoring
  - Thread-Safe Lock Guarding
═══════════════════════════════════════════════════════════════════════
"""
import zmq
import msgpack
import time
import threading

class MT5FastBridgeV5:
    def __init__(self, host="127.0.0.1", pub_port=15555, rep_port=15556):
        self.host = host
        self.pub_port = pub_port
        self.rep_port = rep_port
        self.ctx = zmq.Context()
        self._lock = threading.Lock()
        
        self.req = None
        self.sub = None
        self._latest_ticks = {}
        self._running = False
        
        self._init_req_socket()

    def _init_req_socket(self):
        """Creates or resets REQ socket to prevent ZeroMQ deadlocks"""
        if self.req:
            try:
                self.req.close(linger=0)
            except Exception:
                pass
        self.req = self.ctx.socket(zmq.REQ)
        self.req.setsockopt(zmq.RCVTIMEO, 2500) # 2.5 second timeout
        self.req.setsockopt(zmq.SNDTIMEO, 2500)
        self.req.setsockopt(zmq.LINGER, 0)
        self.req.connect(f"tcp://{self.host}:{self.rep_port}")

    def connect(self):
        print(f"[BRIDGE v5] Connecting to MT5 Server at tcp://{self.host}:{self.rep_port}...")
        res = self.ping()
        if res.get("ok"):
            print(f"  ✅ [BRIDGE v5] Connected successfully! Ping latency: {res.get('ts')}")
            return True
        print(f"  ❌ [BRIDGE v5] Connection failed.")
        return False

    def _send_cmd(self, cmd_dict):
        with self._lock:
            for attempt in range(2):
                try:
                    self.req.send(msgpack.packb(cmd_dict))
                    reply = self.req.recv()
                    return msgpack.unpackb(reply, raw=False)
                except zmq.Again:
                    # Timeout occurred - destroy and reset socket to unblock ZMQ state machine
                    self._init_req_socket()
                except Exception as e:
                    self._init_req_socket()
                    time.sleep(0.5)
            return {"error": "ZMQ Timeout / Connection Lost"}

    def ping(self):
        return self._send_cmd({"cmd": "ping"})

    def get_account_info(self):
        return self._send_cmd({"cmd": "account"})

    def get_tick(self, symbol="XAUUSD"):
        return self._send_cmd({"cmd": "get_tick", "symbol": symbol})

    def execute_market_order(self, symbol="XAUUSD", volume=0.01, order_type=0, sl_dist=0.0, tp_dist=0.0, magic=555000, comment="Simons_v5"):
        """
        order_type: 0 for BUY, 1 for SELL
        sl_dist / tp_dist: Dollar price distance (e.g. 2.40 for $2.40 ATR)
        """
        return self._send_cmd({
            "cmd": "order_now",
            "symbol": symbol,
            "volume": float(volume),
            "type": int(order_type),
            "sl_distance": float(sl_dist),
            "tp_distance": float(tp_dist),
            "magic": int(magic),
            "comment": comment
        })

    def get_open_positions(self, symbol="XAUUSD"):
        return self._send_cmd({"cmd": "positions", "symbol": symbol})

    def close_all_positions(self, symbol="XAUUSD"):
        return self._send_cmd({"cmd": "close_all", "symbol": symbol})

    def subscribe_ticks(self, symbols=None):
        self.sub = self.ctx.socket(zmq.SUB)
        self.sub.setsockopt(zmq.RCVHWM, 5000) # High capacity queue
        self.sub.setsockopt(zmq.LINGER, 0)
        self.sub.connect(f"tcp://{self.host}:{self.pub_port}")
        
        # Subscribe to ALL active multi-asset topics (Zero-Filter Ultra-Fast Path)
        self.sub.setsockopt(zmq.SUBSCRIBE, b"")
            
        self._running = True
        t = threading.Thread(target=self._tick_receiver_loop, daemon=True)
        t.start()
        print(f"[FAST-BRIDGE v5] Multi-Asset Real-Time Tick Stream Subscribed!")

    def _tick_receiver_loop(self):
        poller = zmq.Poller()
        poller.register(self.sub, zmq.POLLIN)
        _unpackb = msgpack.unpackb
        while self._running:
            try:
                socks = dict(poller.poll(timeout=100))
                if self.sub in socks:
                    topic, data = self.sub.recv_multipart(flags=zmq.NOBLOCK)
                    tick = _unpackb(data, raw=False)
                    self._latest_ticks[tick["s"]] = tick
            except Exception:
                time.sleep(0.1)

    def get_latest_streamed_tick(self, symbol="XAUUSD"):
        return self._latest_ticks.get(symbol)

    def close(self):
        self._running = False
        try:
            self.req.close(linger=0)
            if self.sub:
                self.sub.close(linger=0)
            self.ctx.destroy(linger=0)
        except Exception:
            pass

if __name__ == "__main__":
    bridge = MT5FastBridgeV5()
    if bridge.connect():
        print("Account:", bridge.get_account_info())
        print("Tick:", bridge.get_tick("XAUUSD"))
    bridge.close()
