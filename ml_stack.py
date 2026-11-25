#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load or fit the shared model stack and publish model heartbeats.

Paper mode fits provisional artifacts when none exist. Live mode only loads
artifacts that are already there. models/ is never written.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from health_state import record_models
from ml_contract import (
    build_feature_frame,
    contract_from_config,
    load_market_frame,
    market_universe,
    mql_feature_roles,
    ordered_feature_hash,
    sources_match_contract,
)
from ml_models import STACK_NAMES, artifact_dir, clear_cache, fit_stack, load_or_fit
from path_resolver import ProjectRootError, add_mode_arguments, build_context, load_config, resolve_project_root

log = logging.getLogger("fxjefe.ml.stack")


def run(ctx: Dict[str, Any]) -> int:
    root = Path(ctx["project_root"])
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else None
    if cfg is None:
        try:
            cfg = load_config(root)
        except (OSError, ValueError):
            cfg = {}
        ctx["config"] = cfg
    contract = contract_from_config(cfg)
    ctx["features"] = contract
    if len(contract) != 29:
        log.error("feature contract has %s names; ALIGNMENT_V2 requires 29", len(contract))
        return 1
    code_root = Path(ctx.get("code_root") or Path(__file__).resolve().parent)
    matched, problems = sources_match_contract(code_root, contract)
    roles = mql_feature_roles(code_root)
    ctx["feature_roles"] = {
        "model": list(contract),
        "ea": roles.get("ea") or list(contract),
        "server": list(contract),
        "predict_mq5": roles.get("predict_mq5") or list(contract),
        "generatefeatures_mq5": roles.get("generatefeatures_mq5") or list(contract),
    }
    if not matched:
        log.error("MQL feature lists differ from config.json: %s", ", ".join(problems))
    digest = ordered_feature_hash(contract)
    symbols, timeframes = market_universe(cfg, ctx.get("ftmo") if isinstance(ctx.get("ftmo"), dict) else None)
    frame = load_market_frame(
        root,
        cfg,
        symbols,
        timeframes,
        mt5=ctx.get("mt5"),
        connected=bool(ctx.get("mt5_connected")),
        bars=int(cfg.get("analytics_bars") or 300),
    )
    features = build_feature_frame(frame, contract) if len(getattr(frame, "index", [])) else frame
    stack = load_or_fit(ctx, features, force=bool(ctx.get("ml_force_fit")))
    ctx["model_stack"] = stack
    ctx["feature_hash"] = digest
    record_models(root, cfg, stack.heartbeats(), digest, len(contract))
    loaded = [row["name"] for row in stack.heartbeats() if row.get("loaded")]
    log.info(
        "models loaded %s/%s names=%s hash=%s provisional=%s",
        len(loaded),
        len(STACK_NAMES),
        ",".join(loaded) if loaded else "none",
        digest[:16],
        stack.provisional,
    )
    for row in stack.heartbeats():
        log.info(
            "model heartbeat name=%s loaded=%s version=%s backend=%s load_time=%s",
            row.get("name"),
            row.get("loaded"),
            row.get("version"),
            row.get("backend"),
            row.get("load_time"),
        )
    return 0


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Fit or load the FXJEFE model stack")
    parser.add_argument("--project-dir", default=None)
    add_mode_arguments(parser)
    parser.add_argument("--fit", action="store_true", help="write artifacts the golden server is allowed to trade")
    parser.add_argument("--fit-keras", action="store_true", help="also fit TensorFlow/Keras LSTM and LTDM when TensorFlow is installed")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        ctx = build_context(args.project_dir, live=not (args.paper or args.fit or args.fit_keras))
    except ProjectRootError as exc:
        print("[FATAL] {0}".format(exc), file=sys.stderr)
        return 2
    try:
        ctx["config"] = load_config(ctx["project_root"])
    except (OSError, ValueError):
        ctx["config"] = {}
    ctx["code_root"] = Path(__file__).resolve().parent
    if args.fit or args.fit_keras:
        ctx["dry_run"] = True
        ctx["ml_force_fit"] = True
        contract = contract_from_config(ctx["config"])
        if len(contract) != 29:
            log.error("feature contract has %s names; ALIGNMENT_V2 requires 29", len(contract))
            return 1
        symbols, timeframes = market_universe(ctx["config"], None)
        raw = load_market_frame(
            ctx["project_root"],
            ctx["config"],
            symbols,
            timeframes,
            bars=int(ctx["config"].get("analytics_bars") or 300),
        )
        features = build_feature_frame(raw, contract)
        clear_cache()
        stack = fit_stack(
            features,
            contract,
            ctx["config"],
            artifact_dir(ctx["project_root"], ctx["config"]),
            provisional=False,
            fit_keras=bool(args.fit_keras),
        )
        record_models(ctx["project_root"], ctx["config"], stack.heartbeats(), stack.feature_hash, len(contract))
        log.info("explicit fit wrote traded artifacts provisional=%s", stack.provisional)
        return 0 if stack.any_loaded else 1
    return run(ctx)


if __name__ == "__main__":
    raise SystemExit(main())
