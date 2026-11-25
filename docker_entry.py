#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Container entry for the paper runtime.

Runs the pipeline once with --paper, then leaves the health server in the
foreground so a models-loaded ping can succeed. MetaTrader5 is not available
in this Linux image. Broker credentials are read from the environment only
when a process asks for them; this entry does not write them to disk.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parent
SECRET_KEYS = {"password", "passwd", "secret", "apikey", "apisecret", "token", "mt5password"}


def _secret_key(name: str) -> bool:
    compact = "".join(ch for ch in str(name).lower() if ch.isalnum())
    return compact in SECRET_KEYS


def _json_has_secret(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False

    def walk(value) -> bool:
        if isinstance(value, dict):
            for key, item in value.items():
                if _secret_key(key) or walk(item):
                    return True
        elif isinstance(value, list):
            return any(walk(item) for item in value)
        return False

    return walk(data)


def _skipped(path: Path) -> bool:
    name = path.name.lower()
    if name.startswith(".env") or name in {".env", "id_rsa"} or name.endswith((".pem", ".key")):
        return True
    if _secret_key(path.stem):
        return True
    if path.suffix.lower() == ".json" and _json_has_secret(path):
        print("stage skipped {0}: credential field present; value not printed".format(path.name), flush=True)
        return True
    return False


def import_stage(stage: Path, app: Path) -> int:
    """Copy staged models and CSV into the container tree. The stage is only read."""
    if not stage.is_dir():
        return 0
    copied = 0
    for folder_name in ("models", "data"):
        source = stage / folder_name
        if not source.is_dir():
            continue
        for path in sorted(source.rglob("*")):
            if not path.is_file() or _skipped(path):
                continue
            before = path.read_bytes()
            target = app / folder_name / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            if path.read_bytes() != before:
                print("stage source changed during copy: {0}".format(path), flush=True)
                return 1
            copied += 1
    rules = stage / "configftmo.json"
    if rules.is_file() and not _skipped(rules):
        before = rules.read_bytes()
        shutil.copyfile(rules, app / "configftmo.json")
        if rules.read_bytes() != before:
            print("stage source changed during copy: configftmo.json", flush=True)
            return 1
        copied += 1
    print("stage import copied {0} files from {1}".format(copied, stage), flush=True)
    return 0


def ensure_rules(app: Path) -> None:
    target = app / "configftmo.json"
    example = app / "configftmo.example.json"
    if target.is_file() or not example.is_file():
        return
    shutil.copyfile(example, target)
    print("paper runtime copied configftmo.example.json to configftmo.json", flush=True)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--live" in argv:
        print(
            "This Linux image cannot attach to MetaTrader5. "
            "Keep the live terminal on Windows and run that host with run_pipeline.bat.",
            flush=True,
        )
        return 2
    stage = Path(os.environ.get("FXJEFE_STAGE_DIR", "/stage"))
    if import_stage(stage, APP) != 0:
        return 1
    ensure_rules(APP)
    paper = subprocess.call([sys.executable, str(APP / "run_pipeline.py"), "--project-dir", str(APP), "--paper"])
    if paper != 0:
        print("paper pipeline exited {0}".format(paper), flush=True)
        return int(paper)
    os.execv(sys.executable, [sys.executable, str(APP / "health_server.py"), "--project-dir", str(APP)])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
