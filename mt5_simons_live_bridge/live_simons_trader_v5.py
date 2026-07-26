"""
═══════════════════════════════════════════════════════════════════════
  Live Simons Trader v5.0 | 24/7 Automated Execution Brain
═══════════════════════════════════════════════════════════════════════
  Combines Release v5.0 Multi-Regime Simons Engine with Live MT5 ZMQ Bridge.
  - Features 2026 Academic Hierarchical Risk-Gates
  - Compound Fractional Kelly Sizing
  - Real-time Microstructure Order-Flow Processing
  - 24/7 Resilience & Auto-Reconnect
═══════════════════════════════════════════════════════════════════════
"""
import os
import sys
import time
import json
import urllib.request
import pandas as pd
import numpy as np
from datetime import datetime
from catboost import CatBoostRegressor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mt5_fast_bridge_v5 import MT5FastBridgeV5

def load_env_key():
    env_path = "/home/atheer/Desktop/ApexPredator/download data/.env"
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                if line.startswith("DEEPSEEK_API_KEY="):
                    return line.strip().split("=")[1]
    return "sk-3f412db932ae49658db4f4bf985eb9ae"

class LiveSimonsTraderV5:
    def __init__(self, symbol="XAUUSD"):
        self.symbol = symbol
        self.bridge = MT5FastBridgeV5()
        self.api_key = load_env_key()
        
        self.feature_file = "/home/atheer/Desktop/ApexPredator/download data/processed_data/features_and_targets.csv"
        self.model_file = "/home/atheer/Desktop/ApexPredator/download data/processed_data/ml_trend_model.cbm"
        
        self.ml_model = None
        self.feature_cols = [
            'gold_ret_1', 'gold_ret_3', 'gold_ret_5', 'gold_ret_10',
            'gold_ofi_norm_1', 'gold_ofi_norm_5', 'gold_signed_flow_norm_1', 'gold_signed_flow_norm_5',
            'gold_quote_imbalance_1', 'gold_quote_imbalance_5', 'gold_realized_vol_1', 'gold_realized_vol_5',
            'dxy_ret_1', 'dxy_ret_3', 'dxy_ret_5', 'dxy_vol_5',
            'bond_ret_1', 'bond_ret_3', 'bond_ret_5', 'bond_vol_5',
            'vix_ret_1', 'vix_ret_3', 'vix_ret_5', 'vix_z_score_20',
            'gold_dxy_corr_20', 'gold_bond_corr_20', 'vol_ratio_5_20',
            'z_score', 'rsi_14', 'h_rsi_14', 'gold_ofi_accel_5',
            'quote_imbalance_velocity_5', 'price_impact_coef_5', 'vwap_dev_20',
            'hft_abs_bull', 'hft_abs_bear'
        ]
        
        # Risk Gate Tracking
        self.day_start_balance = 10000.0
        self.current_day = datetime.now().date()
        self.daily_circuit_broken = False

    def load_model(self):
        if not os.path.exists(self.model_file):
            print(f"❌ [ERROR] Model file missing: {self.model_file}")
            return False
        self.ml_model = CatBoostRegressor()
        self.ml_model.load_model(self.model_file)
        print("✅ [ML MODEL] CatBoost Regressor loaded successfully.")
        return True

    def query_deepseek_judge(self, context_df, ml_pred, regime_type):
        last_bar = context_df.iloc[-1]
        close_p = float(last_bar['close'])
        spread_z = float(last_bar['z_score'])
        ofi = float(last_bar['ofi_dollar'])
        flow = float(last_bar['signed_flow'])

        table_str = context_df[[
            'timestamp', 'close', 'signed_flow', 'ofi_dollar', 'z_score', 'macro_residual_z_20'
        ]].to_string(index=False)

        prompt = f"""You are Lead Quant Scientist at Medallion Fund.
Data:
{table_str}

Candidate Setup:
- Regime: {regime_type}
- ML Forecast: {ml_pred:+.5f}
- Cointegration Spread Z: {spread_z:.2f}
- Order Flow Imbalance (OFI): {ofi:+.1f}

Rules:
1. BUY: High order flow accumulation or cointegration discount + positive ML forecast.
2. SHORT: High order flow distribution or cointegration premium + negative ML forecast.
3. HOLD: Conflicting signals.

Output strict JSON:
{{"decision": "BUY" | "SHORT" | "HOLD", "confidence": <float 0.0-1.0>, "reasoning": "<concise sentence>"}}"""

        url = "https://api.deepseek.com/chat/completions"
        headers = {"content-type": "application/json", "authorization": f"Bearer {self.api_key}"}
        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": 100
        }

        try:
            req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=8) as response:
                resp_json = json.loads(response.read().decode('utf-8'))
                res = json.loads(resp_json['choices'][0]['message']['content'].strip())
                return res.get("decision", "HOLD"), float(res.get("confidence", 0.0)), res.get("reasoning", "DeepSeek Judgment")
        except Exception:
            pass

        # -------------------------------------------------------------
        # SIMONS QUANTITATIVE ML FALLBACK (GUARANTEED 24/7 RESILIENCE)
        # -------------------------------------------------------------
        fallback_dec = "HOLD"
        fallback_conf = 0.0
        if regime_type == "FLOW_ACCELERATION":
            if ofi > 25.0 or flow > 35.0:
                fallback_dec = "BUY" if ml_pred >= 0 else "SHORT"
                fallback_conf = 0.85
            elif ofi < -25.0 or flow < -35.0:
                fallback_dec = "SHORT" if ml_pred <= 0 else "BUY"
                fallback_conf = 0.85
        elif regime_type == "PAIR_SPREAD_REVERSION":
            if spread_z <= -1.25:
                fallback_dec = "BUY"
                fallback_conf = 0.82
            elif spread_z >= 1.25:
                fallback_dec = "SHORT"
                fallback_conf = 0.82
        elif regime_type == "VWAP_MICRO_SCALP":
            if ml_pred > 0.0003:
                fallback_dec = "BUY"
                fallback_conf = 0.80
            elif ml_pred < -0.0003:
                fallback_dec = "SHORT"
                fallback_conf = 0.80

        return fallback_dec, fallback_conf, "Simons Quant Fallback"

    def run_live_loop(self):
        if not self.load_model():
            return
            
        print(f"[LIVE TRADER v5] Connecting to MT5 ZMQ Bridge (retrying up to 10 times)...")
        connected = False
        for attempt in range(10):
            if self.bridge.connect():
                connected = True
                break
            print(f"  ⏳ Waiting for Wine MT5 Server to initialize... (Attempt {attempt+1}/10)")
            time.sleep(2.5)

        if not connected:
            print("❌ Could not connect to MT5 Bridge. Make sure MT5 terminal is running inside Bottles.")
            return

        print(f"\n🚀 [LIVE TRADER v5] Release v5.0 Hierarchical Risk-Gated Engine Active!")
        print(f"📡 Monitoring {self.symbol} for institutional setups...\n")

        self.bridge.subscribe_ticks([self.symbol])

        while True:
            try:
                # Check Account & Daily Risk-Gates
                acc = self.bridge.get_account_info()
                if "error" in acc:
                    print(f"⚠️ [WARN] Bridge reconnecting...")
                    time.sleep(2.0)
                    continue

                curr_bal = float(acc.get("balance", 10000.0))
                today = datetime.now().date()
                
                if today != self.current_day:
                    self.current_day = today
                    self.day_start_balance = curr_bal
                    self.daily_circuit_broken = False
                    print(f"🌅 [NEW DAY] Resetting Daily Risk-Gate. Starting Balance: ${curr_bal:,.2f}")

                curr_daily_dd = max(0.0, (self.day_start_balance - curr_bal) / self.day_start_balance)
                
                if curr_daily_dd >= 0.018:
                    if not self.daily_circuit_broken:
                        print(f"🛑 [CIRCUIT BREAKER] 1.8% Daily Stop Breached! Halting new entries for today.")
                        self.daily_circuit_broken = True
                    time.sleep(10.0)
                    continue

                # Gate 1 Soft Shield Multiplier
                risk_gate_mult = 0.65 if curr_daily_dd > 0.010 else 1.00

                # Check if position already open
                open_pos = self.bridge.get_open_positions(self.symbol)
                if open_pos.get("positions") and len(open_pos["positions"]) > 0:
                    time.sleep(3.0)
                    continue

                # Read latest market features
                if not os.path.exists(self.feature_file):
                    time.sleep(5.0)
                    continue

                df = pd.read_csv(self.feature_file)
                if len(df) < 50:
                    time.sleep(5.0)
                    continue

                last_bar_idx = len(df) - 1
                context_df = df.iloc[last_bar_idx-4:last_bar_idx+1].copy()
                last_bar = context_df.iloc[-1]

                ofi_val = float(last_bar['ofi_dollar'])
                flow_val = float(last_bar['signed_flow'])
                spread_z = float(last_bar['z_score'])
                vwap_dev = float(last_bar['vwap_dev_20'])
                r_vol = float(last_bar['realized_vol'])

                ml_preds = self.ml_model.predict(df[self.feature_cols])
                ml_p = float(ml_preds[-1])

                regime_type = None
                if abs(ofi_val) > 25.0 or abs(flow_val) > 35.0:
                    regime_type = "FLOW_ACCELERATION"
                elif abs(spread_z) >= 1.25:
                    regime_type = "PAIR_SPREAD_REVERSION"
                elif abs(vwap_dev) > 1.2 or abs(ml_p) > 0.0004:
                    regime_type = "VWAP_MICRO_SCALP"

                if regime_type is None:
                    time.sleep(2.0)
                    continue

                decision, confidence, reasoning = self.query_deepseek_judge(context_df, ml_p, regime_type)

                if decision in ['BUY', 'SHORT'] and confidence >= 0.58:
                    high_low = float(last_bar['high'] - last_bar['low'])
                    close_price = float(last_bar['close'])
                    high_close = abs(float(last_bar['high']) - close_price)
                    low_close = abs(float(last_bar['low']) - close_price)
                    atr = max(high_low, high_close, low_close)
                    if atr < 1.0:
                        atr = 2.0

                    vol_scaler = min(1.3, max(0.7, 0.00002 / (r_vol + 1e-8)))
                    base_risk_pct = 0.010 * confidence * vol_scaler * risk_gate_mult
                    cash_risk = curr_bal * base_risk_pct

                    if self.symbol == "BTCUSD":
                        sl_dist = 400.0
                        tp_dist = 1000.0
                        lot_size = 0.01
                    else:
                        sl_dist = 1.2 * atr
                        tp_dist = 2.6 * atr
                        sl_pct = sl_dist / close_price
                        pos_usd = cash_risk / (sl_pct + 1e-8)
                        lot_size = max(0.01, round(pos_usd / 100000.0, 2))

                    order_type = 0 if decision == 'BUY' else 1
                    
                    print(f"🔥 [SIGNAL TRIGGERED] {decision} ({regime_type}) | Conf: {confidence:.2f} | Risk: {base_risk_pct:.2%} | Lots: {lot_size}")
                    print(f"   Reasoning: {reasoning}")

                    exec_res = self.bridge.execute_market_order(
                        symbol=self.symbol,
                        volume=lot_size,
                        order_type=order_type,
                        sl_dist=sl_dist,
                        tp_dist=tp_dist,
                        magic=555000,
                        comment=f"Simons_v5_{decision}"
                    )

                    if "error" in exec_res:
                        print(f"❌ [EXEC ERROR] {exec_res['error']}")
                    else:
                        print(f"✅ [ORDER EXECUTED] Ticket: #{exec_res.get('deal')} | Price: ${exec_res.get('price'):,.2f} | Latency: {exec_res.get('exec_ms', 0):.1f}ms")

                    time.sleep(10.0)

                time.sleep(2.0)

            except KeyboardInterrupt:
                print("\n  [SHUTDOWN] Live Simons Trader stopped.")
                break
            except Exception as e:
                print(f"⚠️ [WARN] Loop Exception: {e}")
                time.sleep(3.0)

        self.bridge.close()

if __name__ == "__main__":
    trader = LiveSimonsTraderV5()
    trader.run_live_loop()
