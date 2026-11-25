#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Query the FXJEFE ZMQ health server.

    python health_client.py --project-dir PROJECT PING
    python health_client.py --project-dir PROJECT STATUS
    python health_client.py --project-dir PROJECT MODELS
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from path_resolver import ProjectRootError, load_config, resolve_project_root


def query(endpoint: str, command: str, timeout_ms: int = 2000) -> Optional[dict]:
    import zmq

    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.setsockopt(zmq.LINGER, 0)
    socket.setsockopt(zmq.RCVTIMEO, int(timeout_ms))
    socket.setsockopt(zmq.SNDTIMEO, int(timeout_ms))
    try:
        socket.connect(endpoint)
        socket.send_string(command)
        raw = socket.recv_string()
    except Exception:
        return None
    finally:
        socket.close(0)
        context.term()
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def endpoint_for(root: Path, cfg: Optional[dict] = None, port: int = 0) -> str:
    cfg = cfg or {}
    chosen = int(port or cfg.get("zmq_health_port") or 5555)
    return "tcp://127.0.0.1:{0}".format(chosen)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Query the FXJEFE health server")
    parser.add_argument("command", nargs="?", default="STATUS", help="PING, STATUS, or MODELS")
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--timeout-ms", type=int, default=2000)
    args = parser.parse_args(argv)
    try:
        root = resolve_project_root(args.project_dir, require_exists=True)
    except ProjectRootError as exc:
        print("[FATAL] {0}".format(exc), file=sys.stderr)
        return 2
    try:
        cfg = load_config(root)
    except (OSError, ValueError):
        cfg = {}
    endpoint = endpoint_for(root, cfg, args.port)
    body = query(endpoint, args.command.strip().upper(), args.timeout_ms)
    if body is None:
        print(json.dumps({"ok": False, "endpoint": endpoint, "error": "no reply"}))
        return 1
    print(json.dumps(body, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
