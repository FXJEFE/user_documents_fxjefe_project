#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scan all project .py files for config path usage."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Optional

from path_resolver import config_file, stage_main

# Simple substring markers — avoid fragile regex escaping
MARKERS = [
    "config.json",
    "FXJEFE_CONFIG",
    "config_path",
    "CONFIG_PATH",
    "load_config",
    "read_config",
]

def effective_config(root: Path) -> Path:
    return config_file(root)

def scan_file(path: Path, root: Path) -> dict:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"file": str(path.relative_to(root)), "error": str(e)}
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        if any(m.lower() in low or m in line for m in MARKERS):
            hits.append({"line": i, "text": line.strip()[:120]})
    return {
        "file": str(path.relative_to(root)).replace("\\", "/"),
        "mentions_config": len(hits) > 0,
        "hit_count": len(hits),
        "hits": hits[:8],
    }

def run(ctx: Dict[str, Any]) -> int:
    root = ctx["project_root"]
    print("ROOT", root)
    cfg = effective_config(root)
    print("EFFECTIVE_CONFIG", cfg)
    print("EXISTS", cfg.is_file())
    if not cfg.is_file():
        print("[ERROR] config file missing")
        return 1
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        print("KEYS", len(data))
        print("policy", data.get("feature_policy"))
        print("gate", data.get("min_confidence_threshold"))
        for key in ("log_path", "data_path", "models_path", "scripts_path", "historical_csv", "ai_server_url", "api_port"):
            if key in data:
                print("  cfg[{0}]={1!r}".format(key, data.get(key)))
    except Exception as exc:
        print("JSON_ERROR", exc)
        return 1
    print("---")
    rows = []
    for path in sorted(root.rglob("*.py")):
        if any(part in path.parts for part in (".git", "fxjefe", ".venv", "venv", "__pycache__", "site-packages")):
            continue
        rows.append(scan_file(path, root))
    with_cfg = [row for row in rows if row.get("mentions_config")]
    without = [row for row in rows if not row.get("mentions_config") and not row.get("error")]
    print("scripts_total={0} with_config_ref={1} without={2}".format(len(rows), len(with_cfg), len(without)))
    print()
    print("=== SCRIPTS THAT REFERENCE CONFIG ===")
    for row in with_cfg:
        print("\n{0}  hits={1}".format(row["file"], row["hit_count"]))
        for hit in row.get("hits") or []:
            print("  L{0}: {1}".format(hit["line"], hit["text"]))
    print()
    print("=== NO CONFIG REFERENCE ===")
    for row in without:
        print(row["file"])
    out = root / "production" / "config_path_audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "root": str(root),
        "effective_config": str(cfg),
        "exists": cfg.is_file(),
        "with_config": with_cfg,
        "without_config": [row["file"] for row in without],
    }, indent=2), encoding="utf-8")
    print("\nwrote", out)
    return 0


def main(argv: Optional[list] = None) -> int:
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
