#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Minimal golden HTTP server: /health and /predict.

onnxruntime is optional. .pkl models use joblib when that package is present.
This process does not send orders.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    import onnxruntime  # noqa: F401
    HAS_ONNX = True
except Exception:
    onnxruntime = None
    HAS_ONNX = False

try:
    import joblib  # noqa: F401
    HAS_JOBLIB = True
except Exception:
    joblib = None
    HAS_JOBLIB = False


def make_handler(predict_path: str):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._send(200, {"status": "running", "onnxruntime": HAS_ONNX, "joblib": HAS_JOBLIB})
                return
            self._send(404, {"status": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            if path != predict_path:
                self._send(404, {"status": "not_found"})
                return
            try:
                json.loads(raw.decode("utf-8") or "{}")
            except ValueError:
                self._send(400, {"signal": "hold", "confidence": 0.0})
                return
            self._send(200, {"signal": "hold", "confidence": 0.0, "sentiment": "neutral"})

        def log_message(self, fmt: str, *args) -> None:
            return

    return Handler


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FXJEFE golden HTTP server")
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args(argv)
    port = args.port
    predict_path = "/predict"
    if args.project_dir:
        import os
        import sys
        from pathlib import Path
        root = Path(args.project_dir)
        if str(root) not in sys.path:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
        os.environ["FXJEFE_PROJECT_DIR"] = str(root)
        from path_resolver import load_config
        cfg = load_config(root)
        if not port:
            try:
                port = int(cfg.get("api_port") or 8080)
            except (TypeError, ValueError):
                port = 8080
        url = str(cfg.get("ai_server_url") or "")
        if url.rstrip("/").endswith("/predict"):
            predict_path = "/predict"
    if not port:
        port = 8080
    server = ThreadingHTTPServer((args.host, port), make_handler(predict_path))
    print("golden server listening on {0}:{1}".format(args.host, port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
