#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thin path helpers. path_resolver remains the only root resolver."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from path_resolver import (
    ProjectRootError,
    config_file,
    historical_csv,
    load_config,
    resolve,
    resolve_project_root,
)

log = logging.getLogger("fxjefe.paths")

MQL5_DIR_DEFAULT = (
    "C:\\Users\\FullSend\\AppData\\Roaming\\MetaQuotes\\Terminal"
    "\\492CD01931BD0D07A159AEF5B29BF32C\\MQL5"
)
TIMEFRAMES_DEFAULT = ("M1", "M5", "M15", "H1")


def project_root(cli_dir: Optional[str] = None, require_exists: bool = True) -> Path:
    return resolve_project_root(cli_dir, require_exists=require_exists)


def config_path(root: Optional[Path] = None) -> Path:
    return config_file(root or project_root())


def _paths(root: Path) -> Dict[str, str]:
    return resolve(root)


def models_dir(root: Optional[Path] = None) -> Path:
    root = root or project_root()
    return Path(_paths(root)["models_path"])


def data_dir(root: Optional[Path] = None) -> Path:
    root = root or project_root()
    return Path(_paths(root)["data_path"])


def logs_dir(root: Optional[Path] = None) -> Path:
    root = root or project_root()
    return Path(_paths(root)["log_path"])


def features_csv(root: Optional[Path] = None, cfg: Optional[Dict[str, Any]] = None) -> Path:
    root = root or project_root()
    cfg = cfg if cfg is not None else load_config(root)
    raw = ""
    if isinstance(cfg, dict):
        raw = str(cfg.get("features_csv") or cfg.get("historical_csv") or "").strip()
    if raw:
        return historical_csv(root, {"historical_csv": raw})
    return root / "data" / "FXJEFE_Features.csv"


def setup_logging(root: Optional[Path] = None, name: str = "pipeline.log") -> Path:
    root = root or project_root()
    folder = logs_dir(root)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(path), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    logging.info("PROJECT_ROOT=%s", root)
    return path


def mql5_dir(rules: Optional[Dict[str, Any]] = None) -> Path:
    env = os.environ.get("FXJEFE_MQL5_DIR", "").strip()
    if env:
        return Path(os.path.expanduser(env))
    raw = ""
    if isinstance(rules, dict):
        raw = str(rules.get("mt5_mql5_dir") or "").strip()
    if raw:
        return Path(os.path.expanduser(raw))
    return Path(MQL5_DIR_DEFAULT)


def mql5_layout(rules: Optional[Dict[str, Any]] = None) -> Dict[str, Path]:
    base = mql5_dir(rules)
    return {
        "root": base,
        "Experts": base / "Experts",
        "Include": base / "Include",
        "Files": base / "Files",
    }


def venv_python(root: Path, venv_name: str) -> Optional[Path]:
    """Resolve <PROJECT_ROOT>/<venv>/python. Ignores a path that points at venv311."""
    env_key = "FXJEFE_PYTHON38" if venv_name == "fxjefe38" else "FXJEFE_PYTHON"
    override = os.environ.get(env_key, "").strip()
    if override and "venv311" not in override.replace("\\", "/").lower():
        path = Path(os.path.expanduser(override))
        if path.is_file():
            return path
    base = root / venv_name
    if "venv311" in str(base).replace("\\", "/").lower():
        log.warning("refusing python_executable that points at venv311")
        return None
    for relative in ("Scripts/python.exe", "bin/python", "bin/python3"):
        candidate = base / relative
        if candidate.is_file():
            return candidate
    return None


def configured_python(root: Path, rules: Optional[Dict[str, Any]] = None) -> Optional[Path]:
    raw = "fxjefe"
    if isinstance(rules, dict) and rules.get("python_executable"):
        raw = str(rules.get("python_executable")).strip() or "fxjefe"
    if "venv311" in raw.replace("\\", "/").lower():
        log.warning("python_executable points at venv311; using the fxjefe venv instead")
        raw = "fxjefe"
    path = Path(os.path.expanduser(raw))
    if not path.is_absolute():
        path = root / path
    if path.is_dir() or path.name in ("fxjefe", "fxjefe38"):
        return venv_python(root, path.name if path.name in ("fxjefe", "fxjefe38") else "fxjefe")
    if path.is_file():
        return path
    return venv_python(root, "fxjefe")


__all__ = [
    "ProjectRootError",
    "TIMEFRAMES_DEFAULT",
    "config_path",
    "configured_python",
    "data_dir",
    "features_csv",
    "load_config",
    "logs_dir",
    "models_dir",
    "mql5_dir",
    "mql5_layout",
    "project_root",
    "setup_logging",
    "venv_python",
]
