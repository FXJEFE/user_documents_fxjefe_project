#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checksum verification relative to PROJECT_ROOT."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from path_resolver import ProjectRootError, build_context

log = logging.getLogger("fxjefe.monitor")


SKIP_PARTS = {".git", ".venv", "fxjefe", "fxjefe38", "venv", "__pycache__", "Logs", "logs", "production", "state"}
HASH_SUFFIXES = {".py", ".txt", ".json", ".ps1", ".bat", ".yml", ".md"}
HASH_NAMES = {"Makefile", "Dockerfile", "config.json", "configftmo.example.json", "pipeline_manifest.json"}


def iter_hashed_files(root: Path):
    files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_PARTS for part in path.parts):
            continue
        if path.name in ("checksums.json", "SHA256SUMS"):
            continue
        if path.suffix.lower() in HASH_SUFFIXES or path.name in HASH_NAMES:
            files.append(path)
    return sorted(files, key=lambda item: str(item.relative_to(root)).replace("\\", "/"))


def generate(root: Path) -> Dict[str, str]:
    checksums = {}
    for path in iter_hashed_files(root):
        rel = str(path.relative_to(root)).replace("\\", "/")
        checksums[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    target = root / "checksums.json"
    target.write_text(json.dumps(checksums, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("[SHA256] wrote {0} entries to {1}".format(len(checksums), target))
    return checksums


def verify(root: Path) -> int:
    sums = root / "checksums.json"
    if sums.is_file():
        expected = json.loads(sums.read_text(encoding="utf-8"))
    else:
        alt = root / "SHA256SUMS"
        if not alt.is_file():
            print(
                "[SHA256] checksums.json is missing under {0}. "
                "Generate it with: python verify_checksums.py --generate --project-dir {0}".format(root)
            )
            return 1
        expected = {}
        for line in alt.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) >= 2:
                expected[parts[-1]] = parts[0]
    ok, bad, missing = 0, [], []
    for name, want in sorted(expected.items()):
        p = root / name
        if not p.is_file():
            missing.append(name); continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        if got == want:
            ok += 1; print(f"[SHA256] OK  {name}")
        else:
            bad.append(name); print(f"[SHA256] BAD {name}")
    print("[SHA256] ok={0} bad={1} missing={2}".format(ok, len(bad), len(missing)))
    return 0 if not bad and not missing else 1


def run(ctx: Dict[str, Any]) -> int:
    root = ctx["project_root"]
    code = ctx.get("code_root")
    if not (root / "checksums.json").is_file() and not (root / "SHA256SUMS").is_file():
        if code and (Path(code) / "checksums.json").is_file():
            root = Path(code)
        else:
            message = (
                "checksums.json is missing under {0}. "
                "Generate it with: python verify_checksums.py --generate --project-dir {0}"
            ).format(root)
            log.error(message)
            print("[SHA256] {0}".format(message))
            return 1
    return verify(root)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify SHA256 checksums under PROJECT_ROOT")
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--paper", "--dry-run", action="store_true", dest="dry_run")
    parser.add_argument("--generate", action="store_true", help="write checksums.json for this tree")
    args = parser.parse_args(argv)
    if args.generate:
        from path_resolver import resolve_project_root
        try:
            root = resolve_project_root(args.project_dir, require_exists=True)
        except ProjectRootError as exc:
            print("[FATAL] {0}".format(exc), file=sys.stderr)
            return 2
        generate(root)
        return 0
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        ctx = build_context(args.project_dir, live=not args.dry_run)
    except ProjectRootError as exc:
        print("[FATAL] {0}".format(exc), file=sys.stderr)
        return 2
    ctx["dry_run"] = bool(args.dry_run)
    logging.info("PROJECT_ROOT=%s", ctx["project_root"])
    return run(ctx)


if __name__ == "__main__":
    raise SystemExit(main())
