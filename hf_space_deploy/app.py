import sys
import os
import uvicorn
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENGINE_DIR = BASE_DIR / "apex_sovereign_engine"
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from dashboard_server import app

if __name__ == "__main__":
    print("🚀 Launching APEX Sovereign Mega-22 Terminal on Hugging Face Spaces (Port 7860)...")
    uvicorn.run(app, host="0.0.0.0", port=7860, log_level="info")
