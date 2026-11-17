#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check the historical data file under PROJECT_ROOT. Does not download bars."""
from __future__ import annotations

import logging
from typing import Any, Dict

from fxjefe_paths import mql5_layout
from path_resolver import historical_csv, load_config, stage_main

log = logging.getLogger("fxjefe.data")


def run(ctx: Dict[str, Any]) -> int:
    root = ctx["project_root"]
    cfg = ctx.get("config")
    if not isinstance(cfg, dict):
        try:
            cfg = load_config(root)
        except Exception as exc:  # json errors are reported by validate_config
            log.error("cannot load config for data path: %s", exc)
            return 1
        ctx["config"] = cfg
    path = historical_csv(root, cfg)
    ctx["historical_csv"] = str(path)
    log.info("historical_csv=%s", path)
    layout = mql5_layout(ctx.get("ftmo") if isinstance(ctx.get("ftmo"), dict) else None)
    log.info(
        "MQL5 sync root=%s Experts=%s Include=%s Files=%s present=%s",
        layout["root"],
        layout["Experts"],
        layout["Include"],
        layout["Files"],
        layout["root"].is_dir(),
    )
    if path.is_file() and path.stat().st_size > 0:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            rows = sum(1 for _ in handle)
        log.info("historical_csv lines=%s", rows)
        if rows < 2:
            log.error("historical csv has no data rows: %s", path)
            return 1
        return 0
    message = (
        "historical csv not found: {0}. This checkout has no mt5_data_sync.py; "
        "bars are not downloaded here.".format(path)
    )
    if ctx.get("dry_run", True):
        log.info(message)
        return 0
    log.error(message)
    return 1


def main(argv=None) -> int:
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
