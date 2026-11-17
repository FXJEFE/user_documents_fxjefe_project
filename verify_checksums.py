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


def verify(root: Path) -> int:
    sums = root / "checksums.json"
    if sums.is_file():
        expected = json.loads(sums.read_text(encoding="utf-8"))
    else:
        alt = root / "SHA256SUMS"
        if not alt.is_file():
            print("[SHA256] no checksums file"); return 1
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
    if not (root / "checksums.json").is_file() and not (root / "SHA256SUMS").is_file():
        message = "no checksums.json or SHA256SUMS under PROJECT_ROOT; integrity manifest was not shipped in this checkout"
        if ctx.get("dry_run", True):
            log.info(message)
            return 0
        log.error(message)
        return 1
    return verify(root)


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Verify SHA256 checksums under PROJECT_ROOT")
    parser.add_argument("--project-dir", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
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
