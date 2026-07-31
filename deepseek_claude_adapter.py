#!/usr/bin/env python3
"""
deepseek_claude_adapter.py
Advanced Zero-Dependency Adapter translating Anthropic Messages API & Native Tool Calls (/v1/messages)
from Claude Code CLI directly to Railway GLM 5.2 Gateway (z-ai/glm-5.2).
Features:
- Fail-Safe Code Interceptor: Automatically intercepts plain text HTML/CSS code outputs and converts them into native Write tool calls
- Universal XML & JSON Tool Call Translator
- Guaranteed Tool-Use Stop Reason handling (stop_reason: tool_use)
- System Prompt Tool Enforcement
- Fast Delivery Optimization & Robust Auto-Retry
"""

import json
import re
import time
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

TARGET_API_KEY = "sk-8e36745890783d0e97258cbfbf9f346dd1b248935dffcc36"
TARGET_URL = "https://apiai-production.up.railway.app/v1/chat/completions"
TARGET_MODEL = "z-ai/glm-5.2"

def parse_all_tool_calls_to_anthropic(text):
    content_blocks = []
    
    # 1. Check <tool_call> tags
    if "<tool_call>" in text:
        cleaned_text = re.sub(r'<tool_call>[\s\S]*?</tool_call>', '', text).strip()
        if cleaned_text:
            content_blocks.append({"type": "text", "text": cleaned_text})

        tool_blocks = re.findall(r'<tool_call>([\s\S]*?)</tool_call>', text)
        for idx, block in enumerate(tool_blocks):
            block_str = block.strip()
            
            # JSON inside <tool_call>
            if block_str.startswith("{") and block_str.endswith("}"):
                try:
                    tool_json = json.loads(block_str)
                    func_name = tool_json.get("name") or tool_json.get("function")
                    args = tool_json.get("arguments") or tool_json.get("parameters") or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {"raw": args}
                    content_blocks.append({
                        "type": "tool_use",
                        "id": f"toolu_json_{idx+1}_{int(time.time()*1000)}",
                        "name": func_name,
                        "input": args
                    })
                    continue
                except Exception:
                    pass

            # XML <function=Name>
            func_match = re.search(r'<function=([^>]+)>([\s\S]*?)</function>', block_str)
            if func_match:
                func_name = func_match.group(1).strip()
                params_str = func_match.group(2)
                
                params = {}
                param_matches = re.findall(r'<parameter=([^>]+)>([\s\S]*?)</parameter>', params_str)
                for p_name, p_val in param_matches:
                    params[p_name] = p_val.strip()

                content_blocks.append({
                    "type": "tool_use",
                    "id": f"toolu_xml_{idx+1}_{int(time.time()*1000)}",
                    "name": func_name,
                    "input": params
                })
        return content_blocks

    # 2. Check <|DSML|tool_calls>
    if "<|DSML|tool_calls>" in text:
        parts = re.split(r'<\|DSML\|tool_calls>[\s\S]*?</\|DSML\|tool_calls>', text)
        cleaned_text = "".join(parts).strip()
        if cleaned_text:
            content_blocks.append({"type": "text", "text": cleaned_text})

        invoke_blocks = re.findall(r'<\|DSML\|invoke name="([^"]+)">([\s\S]*?)</\|DSML\|invoke>', text)
        for idx, (tool_name, params_block) in enumerate(invoke_blocks):
            params = {}
            param_matches = re.findall(r'<\|DSML\|parameter name="([^"]+)"[^>]*>([\s\S]*?)</\|DSML\|parameter>', params_block)
            for p_name, p_val in param_matches:
                params[p_name] = p_val.strip()

            content_blocks.append({
                "type": "tool_use",
                "id": f"toolu_dsml_{idx+1}_{int(time.time()*1000)}",
                "name": tool_name,
                "input": params
            })
        return content_blocks

    return [{"type": "text", "text": text}]

class ClaudeAdapterHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        try:
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"object":"list","data":[{"id":"claude-3-5-sonnet-20241022","object":"model"}]}')
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_OPTIONS(self):
        try:
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
            self.send_header('Access-Control-Allow-Headers', '*')
            self.end_headers()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        try:
            anthropic_data = json.loads(body.decode('utf-8'))
        except Exception:
            anthropic_data = {}

        system_prompt = anthropic_data.get("system", "")
        anthropic_msgs = anthropic_data.get("messages", [])
        anthropic_tools = anthropic_data.get("tools", [])

        # Add System Prompt Tool Enforcement Instruction
        enforce_sys = "CRITICAL INSTRUCTION: You are an autonomous software developer. When generating code, HTML, CSS, JS or modifying files, YOU MUST USE THE Write or Edit FUNCTION TOOL CALL DIRECTLY. DO NOT OUTPUT CODE IN PLAIN TEXT OR MARKDOWN IN CHAT."
        
        openai_messages = []
        if system_prompt:
            if isinstance(system_prompt, list):
                sys_str = " ".join([s.get("text", "") for s in system_prompt if isinstance(s, dict)])
            else:
                sys_str = str(system_prompt)
            openai_messages.append({"role": "system", "content": sys_str + "\n" + enforce_sys})
        else:
            openai_messages.append({"role": "system", "content": enforce_sys})

        for msg in anthropic_msgs:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            
            if isinstance(content, list):
                text_parts = []
                for c in content:
                    if isinstance(c, dict):
                        if c.get("type") == "text":
                            text_parts.append(c.get("text", ""))
                        elif c.get("type") == "tool_result":
                            tool_out = c.get("content", "")
                            if isinstance(tool_out, list):
                                tool_out = " ".join([t.get("text", "") for t in tool_out if isinstance(t, dict)])
                            text_parts.append(f"[Tool Result for {c.get('tool_use_id')}]: {tool_out}")
                content_str = "\n".join(text_parts)
            else:
                content_str = str(content)

            openai_messages.append({"role": role, "content": content_str})

        # Convert Tools
        openai_tools = []
        for t in anthropic_tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": t.get("name"),
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {})
                }
            })

        req_max_tokens = min(anthropic_data.get("max_tokens", 4096), 6000)

        target_payload = {
            "model": TARGET_MODEL,
            "messages": openai_messages,
            "max_tokens": req_max_tokens,
            "temperature": anthropic_data.get("temperature", 0.1)
        }

        if openai_tools:
            target_payload["tools"] = openai_tools

        headers = {
            "Authorization": f"Bearer {TARGET_API_KEY}",
            "Content-Type": "application/json"
        }

        resp = None
        for attempt in range(6):
            try:
                resp = requests.post(TARGET_URL, headers=headers, json=target_payload, timeout=90)
                if resp.status_code == 200:
                    break
                elif resp.status_code in [429, 502, 503, 504]:
                    time.sleep(2 + attempt * 2)
                else:
                    time.sleep(2)
            except Exception:
                time.sleep(2)

        try:
            if resp and resp.status_code == 200:
                ds_res = resp.json()
                choice = ds_res["choices"][0]
                message_obj = choice.get("message", {})
                finish_reason = choice.get("finish_reason", "stop")
                reply_text = message_obj.get("content", "") or ""
                
                content_blocks = []
                stop_reason = "end_turn"

                if finish_reason == "length":
                    stop_reason = "max_tokens"

                tool_calls = message_obj.get("tool_calls", [])
                if tool_calls:
                    stop_reason = "tool_use"
                    if reply_text:
                        content_blocks.append({"type": "text", "text": reply_text})
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        try:
                            fn_args = json.loads(fn.get("arguments", "{}"))
                        except Exception:
                            fn_args = {}
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tc.get("id", f"toolu_{int(time.time()*1000)}"),
                            "name": fn.get("name"),
                            "input": fn_args
                        })
                else:
                    content_blocks = parse_all_tool_calls_to_anthropic(reply_text)

                # FAIL-SAFE CODE INTERCEPTOR: If plain text contains HTML/CSS/JS code and no tool call was parsed, convert it automatically to a Write tool call!
                if not any(b.get("type") == "tool_use" for b in content_blocks):
                    if "<!DOCTYPE html>" in reply_text or "<html" in reply_text or "/* =======" in reply_text or "class=" in reply_text:
                        target_file = "/home/atheer/Desktop/Quant_Lab/DevPulse/index.html"
                        content_blocks = [{
                            "type": "tool_use",
                            "id": f"toolu_intercept_{int(time.time()*1000)}",
                            "name": "Write",
                            "input": {
                                "file_path": target_file,
                                "content": reply_text
                            }
                        }]
                        stop_reason = "tool_use"

                if any(b.get("type") == "tool_use" for b in content_blocks):
                    stop_reason = "tool_use"

                anthropic_response = {
                    "id": ds_res.get("id", f"msg_{int(time.time())}"),
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-3-5-sonnet-20241022",
                    "content": content_blocks,
                    "stop_reason": stop_reason,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": ds_res.get("usage", {}).get("prompt_tokens", 0),
                        "output_tokens": ds_res.get("usage", {}).get("completion_tokens", 0)
                    }
                }
                
                try:
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(anthropic_response).encode('utf-8'))
                except (BrokenPipeError, ConnectionResetError):
                    pass
            else:
                try:
                    status = resp.status_code if resp else 500
                    content = resp.content if resp else b'{"error": "API timeout"}'
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(content)
                except (BrokenPipeError, ConnectionResetError):
                    pass

        except Exception as e:
            try:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            except (BrokenPipeError, ConnectionResetError):
                pass

def run(port=4000):
    server_address = ('127.0.0.1', port)
    httpd = HTTPServer(server_address, ClaudeAdapterHandler)
    print(f"GLM 5.2 Claude Adapter (Fail-Safe Code Interceptor Enabled) running on http://127.0.0.1:{port}")
    httpd.serve_forever()

if __name__ == '__main__':
    run()
