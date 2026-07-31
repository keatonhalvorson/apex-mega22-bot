#!/usr/bin/env bash
# run_claude_api.sh - Launch Claude Code CLI connected to GLM 5.2 via LiteLLM Proxy
export ANTHROPIC_BASE_URL="http://127.0.0.1:4000"
export ANTHROPIC_API_KEY="sk-8e36745890783d0e97258cbfbf9f346dd1b248935dffcc36"
export CLAUDE_STREAM_IDLE_TIMEOUT=0

echo "================================================="
echo " Launching Claude Code CLI with GLM 5.2 (LiteLLM Proxy)"
echo " Base URL: http://127.0.0.1:4000"
echo " Model:    z-ai/glm-5.2 (Direct Writing Mode)"
echo "================================================="
echo ""

/home/atheer/.local/bin/claude --model claude-3-5-sonnet-20241022 --dangerously-skip-permissions "$@"
