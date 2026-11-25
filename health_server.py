#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ZMQ REP health server plus the same document over HTTP JSON.

This checkout's golden server is HTTP. There is no existing ZMQ socket, so
this server uses the REQ/REP pattern MT5 expert advisors use with mql-zmq:
one short command in, one JSON reply out.

Commands: PING, STATUS, MODELS.
HTTP: GET /status (full document) and GET /health (PING, including models).
Bind stays on 127.0.0.1 unless FXJEFE_HEALTH_BIND or health_bind says otherwise.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

from health_state import empty_state, load_state, status_path, write_state
from path_resolver import ProjectRootError, add_mode_arguments, load_config, resolve_project_root

log = logging.getLogger("fxjefe.health")


def bind_host(cfg: Optional[dict] = None) -> str:
    env = os.environ.get("FXJEFE_HEALTH_BIND", "").strip()
    if env:
        return env
    return str((cfg or {}).get("health_bind") or "127.0.0.1")


def reply_document(root: Path, cfg: dict, command: str) -> dict:
    state = load_state(root, cfg)
    command = (command or "STATUS").strip().upper()
    models = state.get("models") if isinstance(state.get("models"), list) else []
    if command == "PING":
        return {
            "status": "running",
            "pong": True,
            "models": models,
            "feature_hash": state.get("feature_hash"),
            "feature_count": state.get("feature_count"),
            "mt5": state.get("mt5"),
            "updated": state.get("updated"),
        }
    if command == "MODELS":
        return {"status": "running", "models": models, "updated": state.get("updated")}
    if command in ("STATUS", "HEALTH"):
        state["status"] = "running"
        return state
    return {"status": "running", "error": "unknown_command", "command": command}


class HealthServer(object):
    def __init__(self, root: Path, cfg: Optional[dict] = None, zmq_port: int = 5555, http_port: int = 8081, host: str = "127.0.0.1") -> None:
        self.root = Path(root)
        self.cfg = cfg or {}
        self.zmq_port = int(zmq_port)
        self.http_port = int(http_port)
        self.host = host or "127.0.0.1"
        self._stop = threading.Event()
        self._http = None
        self.bound_zmq = ""
        self.bound_http = 0

    def serve(self) -> int:
        import zmq

        context = zmq.Context()
        socket = context.socket(zmq.REP)
        socket.setsockopt(zmq.LINGER, 0)
        endpoint = "tcp://{0}:{1}".format(self.host, self.zmq_port) if self.zmq_port else "tcp://{0}:*".format(self.host)
        try:
            socket.bind(endpoint)
        except zmq.ZMQError as exc:
            log.error("ZMQ health bind failed on %s (%s)", endpoint, exc)
            context.term()
            return 1
        bound = socket.getsockopt(zmq.LAST_ENDPOINT)
        if isinstance(bound, bytes):
            bound = bound.decode("utf-8")
        self.bound_zmq = str(bound)
        self._start_http()
        log.info("health server zmq=%s http=%s:%s status=%s", self.bound_zmq, self.host, self.bound_http, status_path(self.root, self.cfg))
        print("health server zmq={0} http={1}:{2}".format(self.bound_zmq, self.host, self.bound_http), flush=True)
        poller = zmq.Poller()
        poller.register(socket, zmq.POLLIN)
        try:
            while not self._stop.is_set():
                events = dict(poller.poll(200))
                if socket not in events:
                    continue
                try:
                    raw = socket.recv_string()
                except zmq.ZMQError:
                    break
                socket.send_string(json.dumps(reply_document(self.root, self.cfg, raw)))
        finally:
            self._stop_http()
            socket.close(0)
            context.term()
        return 0

    def stop(self) -> None:
        self._stop.set()

    def _start_http(self) -> None:
        root = self.root
        cfg = self.cfg

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = self.path.split("?", 1)[0]
                if path not in ("/status", "/health", "/"):
                    self._send(404, {"status": "not_found"})
                    return
                command = "PING" if path == "/health" else "STATUS"
                self._send(200, reply_document(root, cfg, command))

            def _send(self, code: int, payload: dict) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt: str, *args: Any) -> None:
                return

        server = ThreadingHTTPServer((self.host, int(self.http_port or 0)), Handler)
        self._http = server
        self.bound_http = int(server.server_address[1])
        thread = threading.Thread(target=server.serve_forever, name="fxjefe-health-http", daemon=True)
        thread.start()

    def _stop_http(self) -> None:
        server = self._http
        if server is not None:
            server.shutdown()
            server.server_close()


def start_subprocess(root: Path) -> Optional[subprocess.Popen]:
    code = Path(__file__).resolve().parent / "health_server.py"
    cmd = [sys.executable, str(code), "--project-dir", str(root)]
    try:
        return subprocess.Popen(cmd)
    except OSError as exc:
        log.info("health server did not start (%s)", exc.__class__.__name__)
        return None


def run(ctx: dict) -> int:
    root = Path(ctx["project_root"])
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    state = load_state(root, cfg)
    state["status"] = "running"
    write_state(root, cfg, state)
    log.info("health status file %s", status_path(root, cfg))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FXJEFE ZMQ health server")
    parser.add_argument("--project-dir", default=None)
    add_mode_arguments(parser)
    parser.add_argument("--zmq-port", type=int, default=0)
    parser.add_argument("--http-port", type=int, default=0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        root = resolve_project_root(args.project_dir, require_exists=True)
    except ProjectRootError as exc:
        print("[FATAL] {0}".format(exc), file=sys.stderr)
        return 2
    try:
        cfg = load_config(root)
    except (OSError, ValueError):
        cfg = {}
    zmq_port = args.zmq_port or int(cfg.get("zmq_health_port") or 5555)
    http_port = args.http_port or int(cfg.get("health_http_port") or 8081)
    if not status_path(root, cfg).is_file():
        write_state(root, cfg, empty_state())
    return HealthServer(root, cfg, zmq_port, http_port, bind_host(cfg)).serve()


if __name__ == "__main__":
    raise SystemExit(main())
