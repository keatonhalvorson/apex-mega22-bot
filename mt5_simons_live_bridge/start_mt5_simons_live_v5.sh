#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  Launch Script: Real-Time Microstructure Dollar Bar Simons Engine v5.0
# ═══════════════════════════════════════════════════════════════════════

echo "╔═══════════════════════════════════════════════════════════════════════╗"
echo "║  Real-Time Microstructure Dollar Bar Simons Engine v5.0               ║"
echo "║  Builds $5,000 Dollar Bars Live from Ticks | Zero-Latency Execution   ║"
echo "╚═══════════════════════════════════════════════════════════════════════╝"

BOTTLE_PREFIX="$HOME/.var/app/com.usebottles.bottles/data/bottles/bottles/MT5"
WINE_BIN="$HOME/.var/app/com.usebottles.bottles/data/bottles/runners/soda-9.0-1/bin/wine64"
PYTHON_EXE='C:\users\steamuser\AppData\Local\Programs\Python\Python311\python.exe'

BRIDGE_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_SCRIPT="$BRIDGE_DIR/mt5_zmq_server_v5.py"
TRADER_SCRIPT="$BRIDGE_DIR/live_dollar_bar_simons_engine.py"

# Copy server script into Bottles C: drive mt5_bridge directory
WINE_SCRIPT_DIR="$BOTTLE_PREFIX/drive_c/mt5_bridge"
mkdir -p "$WINE_SCRIPT_DIR"
cp "$SERVER_SCRIPT" "$WINE_SCRIPT_DIR/mt5_zmq_server_v5.py"

echo "🚀 Starting MT5 ZeroMQ Server v5 inside Wine/Bottles..."
flatpak run --command=bash com.usebottles.bottles -c \
  "export WINEPREFIX='$BOTTLE_PREFIX' && export WINEDEBUG=-all && '$WINE_BIN' '$PYTHON_EXE' 'C:\\mt5_bridge\\mt5_zmq_server_v5.py'" &

SERVER_PID=$!
sleep 2.5

echo "🚀 Starting Live Dollar Bar Simons Engine Execution Brain..."
"$(dirname "$BRIDGE_DIR")/../Predator_env/bin/python3" "$TRADER_SCRIPT"

kill $SERVER_PID 2>/dev/null
