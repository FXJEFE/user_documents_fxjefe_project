#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""JSON status document shared by the pipeline, the ZMQ health server, and the dashboard."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def status_path(root: Path, cfg: Optional[Dict[str, Any]] = None) -> Path:
    raw = str((cfg or {}).get("health_status_file") or "Logs/health_status.json").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = Path(root) / path
    return path


def empty_state() -> Dict[str, Any]:
    return {
        "status": "running",
        "updated": utc_now(),
        "pipeline": {"stages": []},
        "mt5": {"connected": False, "detail": ""},
        "models": [],
        "analytics": {},
        "feature_hash": "",
        "feature_count": 0,
    }


def load_state(root: Path, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    path = status_path(root, cfg)
    if not path.is_file():
        return empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_state()
    if not isinstance(data, dict):
        return empty_state()
    base = empty_state()
    base.update(data)
    return base


def write_state(root: Path, cfg: Optional[Dict[str, Any]], state: Dict[str, Any]) -> Path:
    path = status_path(root, cfg)
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated"] = utc_now()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(str(temporary), str(path))
    return path


def update_state(root: Path, cfg: Optional[Dict[str, Any]], **sections: Any) -> Dict[str, Any]:
    state = load_state(root, cfg)
    for key, value in sections.items():
        state[key] = value
    write_state(root, cfg, state)
    return state


def record_stage(root: Path, cfg: Optional[Dict[str, Any]], script: str, stage_state: str, detail: str = "") -> None:
    state = load_state(root, cfg)
    pipeline = state.get("pipeline") if isinstance(state.get("pipeline"), dict) else {"stages": []}
    stages = list(pipeline.get("stages") or [])
    row = {"script": script, "state": stage_state, "detail": detail, "updated": utc_now()}
    for index, item in enumerate(stages):
        if isinstance(item, dict) and item.get("script") == script:
            stages[index] = row
            break
    else:
        stages.append(row)
    pipeline["stages"] = stages
    state["pipeline"] = pipeline
    write_state(root, cfg, state)


def record_mt5(root: Path, cfg: Optional[Dict[str, Any]], connected: bool, detail: str) -> None:
    update_state(root, cfg, mt5={"connected": bool(connected), "detail": detail})


def record_models(root: Path, cfg: Optional[Dict[str, Any]], models: Any, feature_hash: str, feature_count: int) -> None:
    update_state(root, cfg, models=list(models), feature_hash=feature_hash, feature_count=int(feature_count))


def record_analytics(root: Path, cfg: Optional[Dict[str, Any]], summary: Dict[str, Any]) -> None:
    update_state(root, cfg, analytics=summary)
