#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FXJEFE secure strap — after first successful production pipeline. Does NOT replace scripts."""
from __future__ import annotations
import json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

def log(m: str) -> None:
    print(f"[FXJEFE-STRAP] {m}", flush=True)

def project_root() -> Path:
    if sys.platform == "win32":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Documents" / "FXJEFE_Project"
    return Path.home() / "Documents" / "FXJEFE_Project"

def main() -> int:
    root = project_root()
    state = root / "state"
    state.mkdir(parents=True, exist_ok=True)
    prod = root / "production"
    prod.mkdir(parents=True, exist_ok=True)
    last = state / "last_production_run.json"
    if not last.is_file():
        log("No last_production_run.json — run pipelinerun_production.py to success first")
        return 1
    try:
        data = json.loads(last.read_text(encoding="utf-8"))
        if not (data.get("final") or {}).get("ok"):
            log("Last production run final.ok is not true — refuse to strap")
            return 1
    except Exception as e:
        log(f"Cannot read last run: {e}")
        return 1
    reg = root / "feature_registry.py"
    if reg.is_file():
        subprocess.run([sys.executable, "-m", "py_compile", str(reg)], check=False)
        log(f"compiled {reg}")
    seal = {
        "strapped_at_utc": datetime.now(timezone.utc).isoformat(),
        "policy": "DO_NOT_REPLACE_CURRENT_SCRIPTS",
        "feature_policy": "ACCEPT_ALL_FEATURES",
        "final_ok": True,
    }
    (prod / "STRAP_SEAL.json").write_text(json.dumps(seal, indent=2), encoding="utf-8")
    (prod / "ACTIVE_STRAP").write_text(seal["strapped_at_utc"], encoding="utf-8")
    log("STRAPPED — project secured for production runtime")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
