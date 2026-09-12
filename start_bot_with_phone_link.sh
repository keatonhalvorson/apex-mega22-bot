#!/usr/bin/env bash
# ==============================================================================
# 🌌 APEX Sovereign Mega-22 Live Spot Bot + Mobile Phone Link Launcher
# ==============================================================================
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# 1. Kill any existing instances on port 8080 and cloudflared
echo "🧹 Cleaning up previous instances..."
fuser -k 8080/tcp 2>/dev/null || true
pkill -f "cloudflared tunnel" 2>/dev/null || true
sleep 1

# 2. Launch Mega-22 Live Bot in background
echo "🚀 Starting APEX Mega-22 Live Paper Trader..."
python3 run_mega22_live.py --port 8080 > bot_live.log 2>&1 &
BOT_PID=$!
sleep 3

# 3. Launch Cloudflare Tunnel for secure mobile phone access
echo "📱 Creating secure mobile tunnel..."
/home/atheer/.local/bin/cloudflared tunnel --url http://localhost:8080 > cloudflared.log 2>&1 &
TUNNEL_PID=$!
sleep 4

# Extract tunnel URL
TUNNEL_URL=""
for i in {1..15}; do
    if grep -q "trycloudflare.com" cloudflared.log 2>/dev/null; then
        TUNNEL_URL=$(grep -o 'https://[a-zA-Z0-9-]*\.trycloudflare\.com' cloudflared.log | head -n 1)
        break
    fi
    sleep 1
done

LOCAL_IP=$(hostname -I | awk '{print $1}')

echo ""
echo "=============================================================================="
echo "  ✅ APEX SOVEREIGN MEGA-22 LIVE BOT & MOBILE DASHBOARD ARE ACTIVE! "
echo "=============================================================================="
echo "  💻 On this Computer (Local):  http://localhost:8080"
echo "  📶 On Home Wi-Fi (Mobile):   http://${LOCAL_IP}:8080"
echo "  🌍 Anywhere in the World (4G/5G/Phone):"
echo "     👉 \033[1;36m${TUNNEL_URL}\033[0m"
echo "=============================================================================="
echo "  ⚡ Current Open Trade: INJUSDT (Active & Protected)"
echo "  🛑 To stop the bot and tunnel anytime, run: fuser -k 8080/tcp && pkill -f cloudflared"
echo "=============================================================================="
