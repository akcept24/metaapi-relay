#!/usr/bin/env python3
"""MetaApi relay: forwards signed requests to the MetaApi client API
(backup-new-york region) from this server's network. The MetaApi token lives
only in this process's environment. Callers authenticate with
X-Relay-Key. Request/response bodies are never logged.
"""
import json
import os
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://mt-client-api-v1.backup-new-york.agiliumtrade.ai"
TOKEN = os.environ.get("METAAPI_TOKEN", "")
RELAY_KEY = os.environ.get("RELAY_KEY", "")
PORT = int(os.environ.get("PORT", "8080"))


def forward(method, path, body):
    data = None
    headers = {"auth-token": TOKEN}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
        import uuid

        headers["transaction-id"] = uuid.uuid4().hex
    req = urllib.request.Request(UPSTREAM + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:
        return 502, json.dumps({"relay_error": f"{type(e).__name__}: {e}"})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code, text):
        payload = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, json.dumps({"ok": True, "token_set": bool(TOKEN)}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path != "/call":
            self._send(404, json.dumps({"error": "not found"}))
            return
        if not RELAY_KEY or self.headers.get("X-Relay-Key") != RELAY_KEY:
            self._send(401, json.dumps({"error": "unauthorized"}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            spec = json.loads(self.rfile.read(length) or b"{}")
            method = str(spec["method"]).upper()
            path = str(spec["path"])
            if not path.startswith("/users/current/accounts/"):
                raise ValueError("path not allowed")
            status, text = forward(method, path, spec.get("body"))
            print(f"relay {method} {path} -> {status}", flush=True)
            self._send(200, json.dumps({"status": status, "body": text[:20000]}))
        except Exception as e:
            self._send(400, json.dumps({"error": f"{type(e).__name__}: {e}"}))


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
