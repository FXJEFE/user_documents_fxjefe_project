#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Start the FXJEFE MT5 pipeline stages in dependency order.

Default mode is dry-run/paper: no order is sent. A stage that returns non-zero
stops the pipeline. FTMO limits are read from an FTMO config file; they are not
invented when that file is missing.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

from path_resolver import ProjectRootError, build_context

CODE_ROOT = Path(__file__).resolve().parent
GROUP_ORDER = (
    "project_root_config_ftmo",
    "mt5_health",
    "data",
    "features",
    "model",
    "signals",
    "ftmo_risk_gate",
    "execution",
    "monitoring",
)
log = logging.getLogger("fxjefe.pipeline")


def check_interpreter() -> int:
    version = sys.version.split()[0]
    if sys.version_info[:2] != (3, 8):
        print(
            "[FATAL] Python 3.8 is required (Windows target is 3.8.10). This interpreter is {0}.".format(version),
            file=sys.stderr,
        )
        return 2
    if sys.platform == "win32" and version != "3.8.10":
        print(
            "[FATAL] Windows pipeline requires Python 3.8.10 exactly. This interpreter is {0}.".format(version),
            file=sys.stderr,
        )
        return 2
    return 0


def load_manifest(code_root: Path = CODE_ROOT) -> List[Dict[str, Any]]:
    path = code_root / "pipeline_manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    stages = data.get("stages")
    if not isinstance(stages, list) or not stages:
        raise ValueError("pipeline_manifest.json has no stages")
    last = -1
    for stage in stages:
        group = stage.get("group")
        script = stage.get("script")
        if group not in GROUP_ORDER:
            raise ValueError("unknown pipeline group: {0}".format(group))
        index = GROUP_ORDER.index(group)
        if index < last:
            raise ValueError("pipeline group out of order: {0}".format(group))
        last = index
        if not script or not (code_root / script).is_file():
            raise ValueError("pipeline script is missing: {0}".format(script))
        stage.setdefault("entry", "run")
    return stages


def load_module(script: str, code_root: Path = CODE_ROOT) -> Any:
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    path = code_root / script
    module_name = "fxjefe_stage_" + script.replace("\\", "_").replace("/", "_").replace(".", "_")
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError("cannot load {0}".format(path))
    module = importlib.util.module_from_spec(spec)
    # Python 3.8 dataclasses look the class module up in sys.modules while the
    # class body is still executing. Register the module before exec.
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    return module


def _configure_logging(root: Path) -> None:
    log_dir = root / "Logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(str(log_dir / "pipeline.log"), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def execute(ctx: Dict[str, Any], stages: List[Dict[str, Any]]) -> int:
    total = len(stages)
    log.info("dry_run=%s", ctx.get("dry_run", True))
    log.info("stage_order=%s", " -> ".join(item["script"] + ":" + item.get("entry", "run") for item in stages))
    for index, stage in enumerate(stages, start=1):
        script = stage["script"]
        entry = stage.get("entry") or "run"
        group = stage["group"]
        log.info("START %s/%s group=%s script=%s entry=%s", index, total, group, script, entry)
        try:
            module = load_module(script, ctx.get("code_root") or CODE_ROOT)
            fn = getattr(module, entry, None)
            if fn is None:
                log.error("%s has no %s()", script, entry)
                return 1
            rc = int(fn(ctx) or 0)
        except Exception as exc:
            log.exception("stage %s failed: %s", script, exc)
            return 1
        if rc != 0:
            log.error(
                "ABORT at %s/%s %s %s() returned %s. Later stages were not started.",
                index,
                total,
                script,
                entry,
                rc,
            )
            return rc
        log.info("OK %s", script if entry == "run" else "{0}:{1}".format(script, entry))
    if ctx.get("order_sent"):
        log.error("pipeline finished with order_sent set; paper mode must not send orders")
        return 1
    log.info("pipeline finished dry_run=%s order_sent=%s", ctx.get("dry_run", True), ctx.get("order_sent"))
    return 0


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="FXJEFE MT5 pipeline (dry-run by default)")
    parser.add_argument("--project-dir", default=None, help="PROJECT_ROOT. Overrides FXJEFE_PROJECT_DIR.")
    parser.add_argument("--live", action="store_true", help="disable dry-run/paper mode")
    args = parser.parse_args(argv)
    version_rc = check_interpreter()
    if version_rc != 0:
        return version_rc
    try:
        ctx = build_context(args.project_dir, live=args.live)
    except ProjectRootError as exc:
        print("[FATAL] {0}".format(exc), file=sys.stderr)
        return 2
    ctx["code_root"] = CODE_ROOT
    _configure_logging(ctx["project_root"])
    log.info("PROJECT_ROOT=%s", ctx["project_root"])
    log.info("CODE_ROOT=%s", CODE_ROOT)
    log.info("Python %s", sys.version.split()[0])
    try:
        stages = load_manifest(CODE_ROOT)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.error("pipeline manifest rejected: %s", exc)
        return 2
    return execute(ctx, stages)


if __name__ == "__main__":
    raise SystemExit(main())
