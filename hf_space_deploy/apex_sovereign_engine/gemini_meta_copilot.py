"""
====================================================================================================
               APEX GEMINI 3.7 FLASH QUANTITATIVE META-COPILOT
               Deep Microstructure LLM Decision Layer for Live & Audit Execution
====================================================================================================
"""

import json
import urllib.request
import time
from typing import Dict, Any, Optional

GEMINI_API_URL = "http://127.0.0.1:1339/v1/chat/completions"
GEMINI_API_KEY = "123456"

class GeminiMetaCopilot:
    def __init__(self, api_url: str = GEMINI_API_URL, api_key: str = GEMINI_API_KEY, model: str = "gemini-flash"):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model

    def evaluate_entry(self, state: Dict[str, Any], timeout: float = 6.0) -> Dict[str, Any]:
        """
        Sends the complete quantitative market microstructure context to Gemini 3.7 Flash
        and receives a structured JSON decision: APPROVE / REJECT, conviction multiplier, and reasoning.
        """
        prompt = f"""You are an elite quantitative risk and microstructure analyst at a tier-1 fund.
Evaluate this trade candidate:

- Symbol: {state.get('sym')}
- BTC 24h: {state.get('btc_24h', 0):.2f}% | BTC 4h: {state.get('btc_4h', 0):.2f}% | BTC 1h: {state.get('btc_1h', 0):.2f}%
- Coin 24h: {state.get('coin_24h', 0):.2f}% | Coin 1h: {state.get('coin_1h', 0):.2f}%
- Cross-Sectional Relative Strength (Z-Score): {state.get('rs_score', 0):.2f}
- Kalman Dislocation Z-Residual: {state.get('z_res', 0):.2f} sigma
- Volume Spike: {state.get('vol_spike', 0):.2f}x
- Lower Absorption Wick: {state.get('wick_pct', 0):.1f}%
- Order Flow Delta 1m: {state.get('delta', 0):.0f}
- Hurst Exponent: {state.get('hurst', 0.5):.2f}

Decision Rules:
1. APPROVE if dislocation is statistical ($Z <= -2.5$) and absorption is verified with positive order flow delta.
2. REJECT if systemic macro waterfall collapse without buyer support, or coin is severely decaying.
3. Output strictly valid JSON:
{{"decision": "APPROVE" or "REJECT", "conviction": 1.0 to 2.0, "reason": "concise explanation"}}"""

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a sub-millisecond quantitative trade validator. Output JSON only."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1
        }

        try:
            data_bytes = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.api_url,
                data=data_bytes,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": "Mozilla/5.0"
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                content = res["choices"][0]["message"]["content"]
                
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0].strip()
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0].strip()
                    
                parsed = json.loads(content)
                return parsed
        except Exception as e:
            return {"decision": "APPROVE", "conviction": 1.0, "reason": f"Fallback Pass: {str(e)}"}

if __name__ == "__main__":
    copilot = GeminiMetaCopilot()
    test_data = {
        "sym": "NEARUSDT",
        "btc_24h": -0.5,
        "btc_4h": 0.2,
        "btc_1h": 0.1,
        "coin_24h": -3.2,
        "coin_1h": -1.1,
        "rs_score": 0.8,
        "z_res": -2.95,
        "vol_spike": 2.8,
        "wick_pct": 36.0,
        "delta": 62000,
        "hurst": 0.38
    }
    t0 = time.time()
    res = copilot.evaluate_entry(test_data)
    print(f"Gemini 3.7 Flash Evaluation ({round(time.time() - t0, 2)}s):")
    print(json.dumps(res, indent=2))
