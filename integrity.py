#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FXJEFE integrity: generate/validate SHA256, JSON parse, package signatures."""
from __future__ import annotations
import argparse, hashlib, json, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from path_resolver import ProjectRootError, resolve_project_root

SKIP_PARTS = {"fxjefe", "venv", ".venv", "__pycache__", ".git", "production", "logs", "Logs", "state", "models"}
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

def root_dir(cli_dir: Optional[str] = None) -> Path:
    return resolve_project_root(cli_dir, require_exists=True)

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def iter_core_files(root: Path) -> List[Path]:
    files = []
    for p in root.rglob("*"):
        if not p.is_file() or any(part in SKIP_PARTS for part in p.parts):
            continue
        name = p.name
        if name.endswith(".py") or name.startswith("requirements_") or name in {
            "config.json", "pipeline_manifest.json", "Makefile", "Dockerfile",
            "setup.sh", "docker-compose.yml", ".env.example", "VENV.txt",
        }:
            files.append(p)
    return sorted(files, key=lambda x: str(x.relative_to(root)))

def generate(root: Path) -> Dict[str, str]:
    checksums = {}
    for p in iter_core_files(root):
        rel = str(p.relative_to(root)).replace("\\", "/")
        if rel in ("checksums.json", "SHA256SUMS", "integrity_report.json"):
            continue
        checksums[rel] = sha256_file(p)
    (root / "checksums.json").write_text(json.dumps(checksums, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "SHA256SUMS").write_text("\n".join(f"{h}  {n}" for n, h in sorted(checksums.items())) + "\n", encoding="utf-8")
    print(f"[INTEGRITY] generated {len(checksums)} checksums")
    return checksums

def load_expected(root: Path) -> Dict[str, str]:
    cj = root / "checksums.json"
    if cj.is_file():
        data = json.loads(cj.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in data.items()}
    alt = root / "SHA256SUMS"
    if not alt.is_file():
        raise FileNotFoundError("checksums.json or SHA256SUMS required")
    expected = {}
    for line in alt.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2:
            expected[parts[-1]] = parts[0]
    return expected

def validate(root: Path) -> int:
    expected = load_expected(root)
    ok = bad = missing = 0
    for name, want in sorted(expected.items()):
        p = root / name
        if not p.is_file():
            print(f"[INTEGRITY] MISSING {name}"); missing += 1; continue
        got = sha256_file(p)
        if got == want:
            print(f"[INTEGRITY] OK  {name}"); ok += 1
        else:
            print(f"[INTEGRITY] BAD {name}"); bad += 1
    print(f"[INTEGRITY] ok={ok} bad={bad} missing={missing}")
    return 0 if bad == 0 and missing == 0 else 1

def json_check(paths: List[str], root: Path) -> int:
    rc = 0
    for rel in paths:
        p = root / rel
        if not p.is_file():
            print(f"[JSON] MISSING {p}"); rc = 1; continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"[JSON] ERROR {p}: {e}"); rc = 1; continue
        if p.name == "pipeline_manifest.json":
            rc |= _check_manifest(data if isinstance(data, dict) else {}, root)
        elif p.name == "config.json":
            print(f"[JSON] OK config keys={len(data) if isinstance(data, dict) else 0}")
        else:
            print(f"[JSON] OK {p.name}")
    return rc

def _check_manifest(data: Dict[str, Any], root: Path) -> int:
    stages = data.get("stages")
    if not isinstance(stages, list) or not stages:
        print("[JSON] manifest has no stages")
        return 1
    rc = 0
    last = -1
    for stage in stages:
        group = stage.get("group")
        script = stage.get("script")
        if group not in GROUP_ORDER:
            print("[JSON] unknown group {0}".format(group))
            rc = 1
            continue
        index = GROUP_ORDER.index(group)
        if index < last:
            print("[JSON] group out of order {0}".format(group))
            rc = 1
        last = index
        if not script or not (root / script).is_file():
            print("[JSON] missing stage script {0}".format(script))
            rc = 1
        else:
            print("[JSON] OK {0}".format(script))
    return rc


def package_signatures(root: Path) -> int:
    report = {"created_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version, "requirements_files": {}, "pip_freeze": []}
    for req in sorted(root.glob("requirements_*.txt")):
        report["requirements_files"][req.name] = {"sha256": sha256_file(req), "bytes": req.stat().st_size}
    try:
        out = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True, stderr=subprocess.DEVNULL)
        lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
        report["pip_freeze"] = lines
        report["pip_freeze_sha256"] = sha256_bytes("\n".join(lines).encode())
    except Exception as e:
        report["pip_freeze_error"] = str(e)
    path = root / "production" / "PACKAGE_SIGNATURES.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[PACKAGES] wrote {path}")
    return 0

def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-dir", default=None)
    ap.add_argument("command", choices=["generate", "validate", "json-check", "packages", "all"])
    ap.add_argument("paths", nargs="*")
    args = ap.parse_args(argv)
    try:
        root = root_dir(args.project_dir)
    except ProjectRootError as exc:
        print("[FATAL] {0}".format(exc), file=sys.stderr)
        return 2
    print("PROJECT_ROOT={0}".format(root))
    if args.command == "generate":
        generate(root); return 0
    if args.command == "validate":
        return validate(root)
    if args.command == "json-check":
        return json_check(args.paths or ["config.json", "pipeline_manifest.json", "checksums.json"], root)
    if args.command == "packages":
        return package_signatures(root)
    generate(root)
    rc = validate(root)
    rc |= json_check(["config.json"] + (["pipeline_manifest.json"] if (root / "pipeline_manifest.json").is_file() else []), root)
    rc |= package_signatures(root)
    return rc

if __name__ == "__main__":
    raise SystemExit(main())
