#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Automated FXJEFE config.json validation. Exit 0=OK, 1=errors, 2=fatal."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from path_resolver import config_file, stage_main

REQUIRED_KEYS = {"feature_policy": str, "min_confidence_threshold": (int, float)}
RECOMMENDED_KEYS = {"features": list, "historical_csv": str, "log_path": str, "data_path": str,
                    "models_path": str, "ai_server_url": str, "api_port": (int, str), "talib_defaults": dict}
ALLOWED_POLICIES = {"ACCEPT_ALL_FEATURES", "ACCEPT_ALL", "STRICT", "LOCKED"}

def config_path(root: Path) -> Path:
    return config_file(root)

def load(path: Path) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    if not path.is_file():
        return {}, [f"missing file: {path}"]
    raw = path.read_text(encoding="utf-8")
    if raw.startswith("\ufeff"):
        errors.append("BOM present — strip UTF-8 BOM")
        raw = raw.lstrip("\ufeff")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        return {}, [f"invalid JSON: {e}"]
    if not isinstance(data, dict):
        return {}, ["config root must be a JSON object"]
    return data, errors

def check_types(data: Dict[str, Any]) -> List[str]:
    errs = []
    for key, typ in REQUIRED_KEYS.items():
        if key not in data:
            errs.append(f"missing required key: {key}")
        elif not isinstance(data[key], typ):
            errs.append(f"key {key!r} bad type")
    return errs

def check_values(data: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    errs, warns = [], []
    pol = data.get("feature_policy")
    if isinstance(pol, str) and pol not in ALLOWED_POLICIES:
        warns.append(f"feature_policy {pol!r} unusual")
    gate = data.get("min_confidence_threshold")
    if isinstance(gate, (int, float)):
        if not (0.0 <= float(gate) <= 1.0):
            errs.append(f"gate out of range: {gate}")
    feats = data.get("features")
    if isinstance(feats, list) and len(feats) != len(set(map(str, feats))):
        warns.append("features list has duplicates")
    for key in ("log_path", "data_path", "models_path", "scripts_path"):
        val = data.get(key)
        if isinstance(val, str) and val.strip() == "":
            warns.append(f"{key} is empty string")
        if isinstance(val, str) and (":\\" in val or val.startswith("C:")):
            warns.append(f"{key} Windows path: {val}")
    return errs, warns

def check_paths(data: Dict[str, Any], root: Path) -> Tuple[List[str], List[str]]:
    errs, warns = [], []
    hist = data.get("historical_csv") or "data/raw_ohlcv.csv"
    if isinstance(hist, str):
        p = Path(hist) if Path(hist).is_absolute() else root / hist
        if not p.is_file():
            warns.append(f"historical_csv not found: {p}")
    log_p = data.get("log_path") or "Logs"
    if isinstance(log_p, str) and log_p.strip():
        lp = Path(log_p) if Path(log_p).is_absolute() else root / log_p
        try:
            lp.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            errs.append(f"cannot create log_path {lp}: {e}")
    return errs, warns

def run(ctx: Dict[str, Any]) -> int:
    root = ctx["project_root"]
    path = config_path(root)
    print("[CONFIG-VALIDATE] path={0}".format(path))
    data, load_errs = load(path)
    if load_errs and not data:
        for err in load_errs:
            print("[ERROR] {0}".format(err))
        return 2
    errors, warnings = list(load_errs), []
    errors.extend(check_types(data))
    value_errors, value_warnings = check_values(data)
    errors.extend(value_errors)
    warnings.extend(value_warnings)
    path_errors, path_warnings = check_paths(data, root)
    errors.extend(path_errors)
    warnings.extend(path_warnings)
    for key in RECOMMENDED_KEYS:
        if key not in data:
            warnings.append("recommended key missing: {0}".format(key))
    for warning in warnings:
        print("[WARN] {0}".format(warning))
    for err in errors:
        print("[ERROR] {0}".format(err))
    summary = {
        "path": str(path),
        "ok": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "policy": data.get("feature_policy"),
        "gate": data.get("min_confidence_threshold"),
        "feature_count": len(data["features"]) if isinstance(data.get("features"), list) else None,
    }
    out = root / "production" / "config_validate.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print("[CONFIG-VALIDATE] wrote {0}".format(out))
    print("[CONFIG-VALIDATE] " + ("FAIL" if errors else "OK"))
    ctx["config"] = data
    return 1 if errors else 0


def main(argv: Optional[list] = None) -> int:
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
