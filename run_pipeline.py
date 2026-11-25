#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Start the FXJEFE MT5 pipeline stages in dependency order.

Default mode is LIVE: real orders are sent after the gates pass. Pass --paper
or --dry-run to record decisions without order_send. --live is accepted and
does not change that default. A stage that returns non-zero stops the pipeline.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from fxjefe_paths import venv_python
from path_resolver import ProjectRootError, add_mode_arguments, build_context, load_config

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
    if sys.platform == "win32" and sys.version_info[:2] == (3, 8) and version != "3.8.10":
        print(
            "[FATAL] Windows Python 3.8 feature venv must be 3.8.10 exactly. This interpreter is {0}.".format(version),
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


def _record_stage(ctx: Dict[str, Any], script: str, state: str, detail: str = "") -> None:
    try:
        from health_state import record_stage
        cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else None
        record_stage(ctx["project_root"], cfg, script, state, detail)
    except Exception:
        log.info("health stage status was not recorded for %s", script)


def execute(ctx: Dict[str, Any], stages: List[Dict[str, Any]]) -> int:
    total = len(stages)
    log.info("dry_run=%s", ctx.get("dry_run", True))
    log.info("stage_order=%s", " -> ".join(item["script"] + ":" + item.get("entry", "run") for item in stages))
    for index, stage in enumerate(stages, start=1):
        script = stage["script"]
        entry = stage.get("entry") or "run"
        group = stage["group"]
        log.info("START %s/%s group=%s script=%s entry=%s", index, total, group, script, entry)
        _record_stage(ctx, script, "running")
        try:
            rc = _run_stage(ctx, stage)
        except Exception as exc:
            log.exception("stage %s failed: %s", script, exc)
            _record_stage(ctx, script, "failed", exc.__class__.__name__)
            return 1
        if rc != 0:
            _record_stage(ctx, script, "failed", "exit {0}".format(rc))
            log.error(
                "ABORT at %s/%s %s %s() returned %s. Later stages were not started.",
                index,
                total,
                script,
                entry,
                rc,
            )
            return rc
        _record_stage(ctx, script, "ok")
        log.info("OK %s", script if entry == "run" else "{0}:{1}".format(script, entry))
    if ctx.get("dry_run", True) and ctx.get("order_sent"):
        log.error("pipeline finished with order_sent set; paper mode must not send orders")
        return 1
    log.info("pipeline finished dry_run=%s order_sent=%s", ctx.get("dry_run", True), ctx.get("order_sent"))
    return 0


def _child_env() -> Dict[str, str]:
    """Give stage subprocesses the repo root, including runtime/signal_gate.py."""
    env = os.environ.copy()
    root = str(CODE_ROOT)
    parts = [item for item in env.get("PYTHONPATH", "").split(os.pathsep) if item]
    if root not in parts:
        env["PYTHONPATH"] = os.pathsep.join([root] + parts) if parts else root
    return env


def _run_stage(ctx: Dict[str, Any], stage: Dict[str, Any]) -> int:
    script = stage["script"]
    entry = stage.get("entry") or "run"
    code_root = Path(ctx.get("code_root") or CODE_ROOT)
    which = stage.get("python") or "fxjefe"
    if which == "fxjefe38":
        other = venv_python(ctx["project_root"], "fxjefe38")
        if other and Path(other).resolve() != Path(sys.executable).resolve():
            cmd = [str(other), str(code_root / script), "--project-dir", str(ctx["project_root"])]
            if ctx.get("dry_run"):
                cmd.append("--paper")
            log.info("fxjefe38 %s", " ".join(cmd))
            completed = subprocess.run(cmd, env=_child_env())
            return int(completed.returncode)
    module = load_module(script, code_root)
    fn = getattr(module, entry, None)
    if fn is None:
        log.error("%s has no %s()", script, entry)
        return 1
    return int(fn(ctx) or 0)


def _health(url: str) -> bool:
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=2) as response:
            if response.status != 200:
                return False
            body = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return isinstance(body, dict) and body.get("status") == "running"


def verify_prelude(ctx: Dict[str, Any]) -> int:
    """runtime_lock, feature_hash, signal_gate, verify_checksums, then golden /health."""
    code_root = Path(ctx.get("code_root") or CODE_ROOT)
    project = ctx["project_root"]
    steps = (
        ("runtime_lock.py", project),
        ("feature_hash.py", project),
        ("runtime/signal_gate.py", project),
        ("verify_checksums.py", code_root),
    )
    for script, folder in steps:
        cmd = [sys.executable, str(code_root / script), "--project-dir", str(folder)]
        if ctx.get("dry_run"):
            cmd.append("--paper")
        log.info("verify %s", " ".join(cmd))
        completed = subprocess.run(cmd, env=_child_env())
        if completed.returncode != 0:
            log.error("verification failed: %s exit %s", script, completed.returncode)
            return int(completed.returncode)
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else load_config(project)
    base = str(cfg.get("ai_server_url") or "http://127.0.0.1:{0}".format(cfg.get("api_port") or 8080)).rstrip("/")
    health = base + "/health"
    if not _health(base):
        cmd = [sys.executable, str(code_root / "ai_server_golden.py"), "--project-dir", str(project)]
        log.info("start %s", " ".join(cmd))
        proc = subprocess.Popen(cmd, env=_child_env())
        ctx["golden_server"] = proc
        ready = False
        for _ in range(40):
            if proc.poll() is not None:
                break
            if _health(base):
                ready = True
                break
            time.sleep(0.1)
        if not ready:
            log.error("ai_server_golden /health failed: %s", health)
            return 1
    log.info("golden /health ok %s", health)
    _start_health(ctx)
    return 0


def _stop_process(proc: Any) -> None:
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=3)
    except subprocess.TimeoutExpired:
        proc.kill()


def _stop_server(ctx: Dict[str, Any]) -> None:
    _stop_process(ctx.get("golden_server"))
    _stop_process(ctx.get("health_server"))


def _start_health(ctx: Dict[str, Any]) -> None:
    """ZMQ status server. A bind failure is logged and does not stop the pipeline."""
    try:
        from health_server import start_subprocess
    except Exception as exc:
        log.info("health server is not available (%s)", exc.__class__.__name__)
        return
    proc = start_subprocess(Path(ctx["project_root"]))
    ctx["health_server"] = proc
    if proc is None:
        return
    time.sleep(0.3)
    if proc.poll() is not None:
        log.info("health server exited early (%s); pipeline continues without the ping socket", proc.returncode)
        ctx["health_server"] = None


LIVE_BANNER = (
    "============================================================\n"
    "LIVE MODE\n"
    "Real orders are sent only after configftmo.json, MT5 credentials,\n"
    "the FTMO gate, the margin guard, the feature-hash match, and MT5 health pass.\n"
    "============================================================"
)


def require_live_prereqs(root: Path) -> int:
    """Live mode refuses to continue without the rules file and MT5 env credentials."""
    rules = root / "configftmo.json"
    if not rules.is_file():
        log.error("LIVE MODE requires configftmo.json at %s", rules)
        print("[FATAL] LIVE MODE requires configftmo.json at {0}".format(rules), file=sys.stderr)
        return 1
    missing = [
        name for name in ("MT5_ACCOUNT", "MT5_PASSWORD", "MT5_SERVER")
        if not os.environ.get(name, "").strip()
    ]
    if missing:
        log.error("LIVE MODE requires %s in the environment. Values are not printed.", ", ".join(missing))
        print(
            "[FATAL] LIVE MODE requires {0} in the environment. Values are not printed.".format(", ".join(missing)),
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="FXJEFE MT5 pipeline (live by default)")
    parser.add_argument("--project-dir", default=None, help="PROJECT_ROOT. Overrides FXJEFE_PROJECT_DIR.")
    add_mode_arguments(parser)
    args = parser.parse_args(argv)
    version_rc = check_interpreter()
    if version_rc != 0:
        return version_rc
    try:
        ctx = build_context(args.project_dir, live=not args.paper)
    except ProjectRootError as exc:
        print("[FATAL] {0}".format(exc), file=sys.stderr)
        return 2
    ctx["code_root"] = CODE_ROOT
    _configure_logging(ctx["project_root"])
    log.info("PROJECT_ROOT=%s", ctx["project_root"])
    log.info("CODE_ROOT=%s", CODE_ROOT)
    log.info("Python %s (fxjefe=3.11, fxjefe38=3.8.10)", sys.version.split()[0])
    if ctx.get("dry_run"):
        log.info("PAPER MODE")
        print("PAPER MODE")
    else:
        log.info(LIVE_BANNER)
        print(LIVE_BANNER)
        prereq = require_live_prereqs(ctx["project_root"])
        if prereq != 0:
            return prereq
    try:
        stages = load_manifest(CODE_ROOT)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.error("pipeline manifest rejected: %s", exc)
        return 2
    try:
        verified = verify_prelude(ctx)
        if verified != 0:
            return verified
        return execute(ctx, stages)
    finally:
        _stop_server(ctx)


if __name__ == "__main__":
    raise SystemExit(main())
