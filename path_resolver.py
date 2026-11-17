#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Single PROJECT_ROOT resolution for the FXJEFE pipeline.

Order:
  1. --project-dir (passed in by the caller)
  2. FXJEFE_PROJECT_DIR
  3. FXJEFE_PROJECT_ROOT (legacy alias, used only when FXJEFE_PROJECT_DIR is unset)
  4. Path.home() / "Documents" / "FXJEFE_Project"

Data, model, log, and config paths are resolved under that root.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

log = logging.getLogger("fxjefe.paths")


class ProjectRootError(RuntimeError):
    """Raised when the resolved project directory is missing."""


def resolve_project_root(cli_dir: Optional[str] = None, require_exists: bool = True) -> Path:
    if cli_dir is not None and str(cli_dir).strip():
        source = "--project-dir"
        raw = str(cli_dir).strip()
    else:
        env_dir = os.environ.get("FXJEFE_PROJECT_DIR", "").strip()
        if env_dir:
            source = "FXJEFE_PROJECT_DIR"
            raw = env_dir
        else:
            legacy = os.environ.get("FXJEFE_PROJECT_ROOT", "").strip()
            if legacy:
                source = "FXJEFE_PROJECT_ROOT"
                raw = legacy
            else:
                source = "default"
                raw = str(Path.home() / "Documents" / "FXJEFE_Project")
    root = Path(os.path.abspath(os.path.expanduser(raw)))
    if require_exists and not root.is_dir():
        raise ProjectRootError(
            "PROJECT_ROOT does not exist: {0} (source={1}). "
            "Clone the repo to the Documents/FXJEFE_Project folder, "
            "set FXJEFE_PROJECT_DIR, or pass --project-dir.".format(root, source)
        )
    return root


def project_root() -> Path:
    """Return the resolved root without requiring it to exist (import-safe)."""
    return resolve_project_root(require_exists=False)


def config_file(root: Path) -> Path:
    env = os.environ.get("FXJEFE_CONFIG", "").strip()
    if not env:
        return root / "config.json"
    path = Path(os.path.expanduser(env))
    if not path.is_absolute():
        path = root / path
    return path


def load_config(root: Optional[Path] = None) -> Dict[str, Any]:
    root = root or project_root()
    path = config_file(root)
    if not path.is_file():
        return {}
    raw = path.read_text(encoding="utf-8-sig")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object: {0}".format(path))
    return data


def _under_root(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def _pick(root: Path, cfg: Dict[str, Any], key: str, default_rel: str) -> str:
    raw = cfg.get(key)
    text = raw.strip() if isinstance(raw, str) else ""
    if text:
        candidate = Path(os.path.expanduser(text))
        if candidate.is_absolute():
            if _under_root(root, candidate):
                return str(candidate)
            log.warning(
                "%s is absolute and outside PROJECT_ROOT; using the default under the root instead: %s",
                key,
                candidate,
            )
        else:
            return str(root / candidate)
    if default_rel:
        return str(root / default_rel)
    return str(root)


def historical_csv(root: Path, cfg: Optional[Dict[str, Any]] = None) -> Path:
    cfg = cfg or {}
    raw = cfg.get("historical_csv") or cfg.get("data_csv") or "data/raw_ohlcv.csv"
    candidate = Path(os.path.expanduser(str(raw)))
    if candidate.is_absolute():
        if _under_root(root, candidate):
            return candidate
        log.warning("historical csv path is outside PROJECT_ROOT and was ignored: %s", candidate)
        return root / "data" / "raw_ohlcv.csv"
    return root / candidate


def resolve(root: Optional[Path] = None) -> Dict[str, str]:
    root = root or project_root()
    try:
        cfg = load_config(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("config not loaded: %s", exc)
        cfg = {}
    return {
        "project_root": str(root),
        "venv_dir": str(root / "fxjefe"),
        "venv38_dir": str(root / "fxjefe38"),
        "scripts_path": _pick(root, cfg, "scripts_path", ""),
        "models_path": _pick(root, cfg, "models_path", "models"),
        "data_path": _pick(root, cfg, "data_path", "data"),
        "log_path": _pick(root, cfg, "log_path", "Logs"),
        "config_path": str(config_file(root)),
        "historical_csv": str(historical_csv(root, cfg)),
    }


def build_context(cli_dir: Optional[str] = None, live: bool = False) -> Dict[str, Any]:
    root = resolve_project_root(cli_dir, require_exists=True)
    return {
        "project_root": root,
        "dry_run": not live,
        "code_root": Path(__file__).resolve().parent,
        "order_sent": False,
        "signal_emit": False,
        "ftmo_clear": False,
        "mt5_connected": False,
    }


def stage_main(run, argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=(getattr(run, "__doc__", None) or "FXJEFE stage"))
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--live", action="store_true", help="disable dry-run/paper mode")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        ctx = build_context(args.project_dir, live=args.live)
    except ProjectRootError as exc:
        print("[FATAL] {0}".format(exc), file=sys.stderr)
        return 2
    logging.info("PROJECT_ROOT=%s", ctx["project_root"])
    return int(run(ctx) or 0)


def run(ctx: Dict[str, Any]) -> int:
    """Log PROJECT_ROOT and the paths derived from it."""
    root = ctx["project_root"]
    paths = resolve(root)
    ctx["paths"] = paths
    log.info("PROJECT_ROOT=%s", root)
    for key in (
        "config_path",
        "data_path",
        "historical_csv",
        "models_path",
        "log_path",
        "scripts_path",
        "venv_dir",
    ):
        log.info("path %s=%s", key, paths[key])
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Resolve FXJEFE PROJECT_ROOT and data paths")
    parser.add_argument("--project-dir", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        root = resolve_project_root(args.project_dir, require_exists=True)
    except ProjectRootError as exc:
        print("[FATAL] {0}".format(exc), file=sys.stderr)
        return 2
    logging.info("PROJECT_ROOT=%s", root)
    print(json.dumps(resolve(root), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
