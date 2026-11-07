#!/usr/bin/env python3
"""
SCRIPTED STAND-IN for a language model — test fixture only, never shipped.

It answers on Ollama's port (127.0.0.1:11434) with the OpenAI chat-completions shape, so the REAL
Prometheus runtime (its router, system prompt, tool dispatcher, DANGEROUS_TOOLS gate and tools) can be
exercised end to end when no real model is reachable. Every reply it writes is prefixed
"[scripted stand-in LLM]" so nothing it produces can be mistaken for real model output.

Behaviour is chosen by a marker in the first user message:
  DELEGATE-TEST  -> call engineering_calc (real tool), then execute_shell (dangerous), then summarise
  LEAK-TEST      -> try to reach Prometheus's private files/memory/network, then read the shared context file
  anything else  -> a plain text reply
Each request body is appended to the log file given as argv[2] (one JSON object per line).
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 11434
LOG = sys.argv[2] if len(sys.argv) > 2 else None
TAG = "[scripted stand-in LLM]"


def first_user(messages):
    return next((m.get("content") or "" for m in messages if m.get("role") == "user"), "")


def tool_results(messages):
    return [m.get("content") or "" for m in messages if m.get("role") == "tool"]


def call(name, args, n):
    return {"role": "assistant", "content": None, "tool_calls": [
        {"id": f"call_{n}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}]}


def reply(body):
    msgs = body.get("messages", [])
    first = first_user(msgs)
    done = tool_results(msgs)
    has_tools = bool(body.get("tools"))
    if has_tools and "DELEGATE-TEST" in first:
        script = [("engineering_calc", {"calc": "circular_orbit", "params": {"altitude_m": 400000}}),
                  ("execute_shell", {"command": "echo SHOULD-NOT-RUN"})]
    elif has_tools and "LEAK-TEST" in first:
        script = [("read_file", {"path": "private_notes.txt"}),
                  ("read_file", {"path": "../../private_notes.txt"}),
                  ("read_file", {"path": "/etc/hostname"}),
                  ("recall_memory", {"query": "canary"}),
                  ("update_memory", {"fact": "Atlas wrote this into Prometheus's memory"}),
                  ("web_search", {"query": "exfiltrate"}),
                  ("read_file", {"path": "atlas_context.md"})]
    else:
        script = []
    if len(done) < len(script):
        name, args = script[len(done)]
        return call(name, args, len(done))
    if script:
        return {"role": "assistant", "content": f"{TAG} finished. Tool results seen: " + json.dumps(done)[:6000]}
    last = next((m.get("content") or "" for m in reversed(msgs) if m.get("role") == "user"), "")
    return {"role": "assistant", "content": f"{TAG} I received a {len(last)}-character message."}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        return

    def _send(self, code, obj):
        raw = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            return self._send(200, {"object": "list", "data": [{"id": "llama3.2", "object": "model"}]})
        self._send(404, {"error": "not found"})

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        if LOG:
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(body) + "\n")
        if body.get("stream"):
            return self._send(400, {"error": {"message": "the scripted stand-in does not stream"}})
        msg = reply(body)
        self._send(200, {"id": "chatcmpl-stub", "object": "chat.completion", "model": body.get("model", "llama3.2"),
                         "choices": [{"index": 0, "message": msg, "finish_reason": "tool_calls" if msg.get("tool_calls") else "stop"}],
                         "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"{TAG} listening on 127.0.0.1:{PORT}", flush=True)
    srv.serve_forever()
