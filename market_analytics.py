#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live or replay analytics for the traded ensemble.

Pulls bars (MetaTrader5 when the terminal is connected, otherwise the replay
CSV), scores every configured symbol and timeframe, and compares the live
window with the training rows and, when a separate historical file exists,
that file. Results go to the health document, Logs/analytics.csv, and
Logs/analytics.jsonl. This loop does not send orders.
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from health_client import endpoint_for, query
from health_state import record_analytics, record_models
from ml_contract import (
    build_feature_frame,
    contract_from_config,
    historical_frame_path,
    load_market_frame,
    market_universe,
    ordered_feature_hash,
    population_stability,
    replay_csv_path,
    sign_accuracy,
)
from ml_models import STACK_NAMES, load_or_fit
from path_resolver import ProjectRootError, add_mode_arguments, build_context, load_config, resolve_project_root

log = logging.getLogger("fxjefe.analytics")
CSV_FIELDS = [
    "time", "symbol", "timeframe", "model", "signal", "confidence", "predicted_change",
    "feature_hash", "feature_drift_psi", "prediction_drift", "insample_sign_accuracy",
    "live_sign_accuracy", "historical_feature_psi", "historical_baseline", "bars",
]


def run(ctx: Dict[str, Any]) -> int:
    return run_once(ctx)


def run_forever(ctx: Dict[str, Any]) -> int:
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    interval = float(cfg.get("analytics_interval_seconds") or 5.0)
    while True:
        code = run_once(ctx)
        if code != 0:
            return code
        try:
            time.sleep(max(0.2, interval))
        except KeyboardInterrupt:
            return 0


def run_once(ctx: Dict[str, Any]) -> int:
    root = Path(ctx["project_root"])
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    if not cfg:
        try:
            cfg = load_config(root)
        except (OSError, ValueError):
            cfg = {}
        ctx["config"] = cfg
    contract = list(ctx.get("features") or contract_from_config(cfg))
    if not contract:
        log.info("analytics skipped; feature contract is empty")
        return 0
    symbols, timeframes = market_universe(cfg, ctx.get("ftmo") if isinstance(ctx.get("ftmo"), dict) else None)
    raw = load_market_frame(
        root,
        cfg,
        symbols,
        timeframes,
        mt5=ctx.get("mt5"),
        connected=bool(ctx.get("mt5_connected")),
        bars=int(cfg.get("analytics_bars") or 300),
    )
    if raw is None or len(raw) == 0:
        log.info("analytics has no bars (MT5 unavailable and replay csv missing)")
        record_analytics(root, cfg, {"rows": 0, "detail": "no bars"})
        return 0
    features = build_feature_frame(raw, contract)
    if len(features) == 0:
        log.info("analytics feature frame is empty")
        return 0
    stack = ctx.get("model_stack")
    if stack is None or not getattr(stack, "any_loaded", False):
        stack = load_or_fit(ctx, features)
        ctx["model_stack"] = stack
    window = int(cfg.get("analytics_live_window") or 20)
    digest = ordered_feature_hash(contract)
    historical = _historical_features(root, cfg, contract, replay_csv_path(root, cfg))
    rows = []
    seen = set()
    for (symbol, timeframe), group in features.groupby(["symbol", "timeframe"], sort=False):
        key = (str(symbol), str(timeframe).upper())
        seen.add(key)
        rows.append(_score_group(group.reset_index(drop=True), stack, contract, window, digest, historical))
    if symbols:
        configured = {(symbol, timeframe.upper()) for symbol in symbols for timeframe in timeframes}
        for symbol, timeframe in sorted(configured - seen):
            log.info("analytics skipped %s %s; no bars in the current pull", symbol, timeframe)
    _write_outputs(root, rows)
    summary = {
        "rows": len(rows),
        "symbols": sorted({row["symbol"] for row in rows}),
        "timeframes": sorted({row["timeframe"] for row in rows}),
        "feature_hash": digest,
        "latest": rows[-1] if rows else {},
        "records": rows,
    }
    record_analytics(root, cfg, summary)
    record_models(root, cfg, stack.heartbeats(), digest, len(contract))
    ping = _ping(root, cfg)
    if isinstance(ping, dict):
        loaded = [item.get("name") for item in (ping.get("models") or []) if isinstance(item, dict) and item.get("loaded")]
        log.info("health ping models_loaded=%s/%s names=%s", len(loaded), len(STACK_NAMES), ",".join(str(item) for item in loaded))
    else:
        log.info("health ping unavailable; status file still updated")
    for row in rows:
        log.info(
            "analytics %s %s signal=%s confidence=%s predicted_change=%s feature_drift_psi=%s prediction_drift=%s live_accuracy=%s historical_psi=%s",
            row["symbol"], row["timeframe"], row["signal"], row["confidence"], row["predicted_change"],
            row["feature_drift_psi"], row["prediction_drift"], row["live_sign_accuracy"], row["historical_feature_psi"],
        )
    ctx["analytics_rows"] = rows
    return 0


def _score_group(group, stack, contract, window, digest, historical) -> Dict[str, Any]:
    import numpy as np

    live = group.tail(min(window, len(group)))
    train = group.iloc[:-len(live)] if len(group) > len(live) else group.iloc[0:0]
    symbol = str(group["symbol"].iloc[-1])
    timeframe = str(group["timeframe"].iloc[-1])
    matrix = group[list(contract)].to_numpy(dtype=float)
    prediction = stack.predict_window(matrix.tolist(), symbol, timeframe)
    train_changes, train_realized_sample = _predict_changes(stack, train, contract) if len(train) else ([], [])
    live_changes, live_realized_sample = _predict_changes(stack, live, contract)
    feature_psi = []
    for name in contract:
        left = train[name].to_numpy(dtype=float) if len(train) else group[name].to_numpy(dtype=float)
        feature_psi.append(population_stability(left, live[name].to_numpy(dtype=float)))
    hist_psi = None
    if historical is not None and len(historical):
        hist_group = historical
        if "symbol" in historical.columns:
            matched = historical[(historical["symbol"] == symbol) & (historical["timeframe"].astype(str).str.upper() == timeframe.upper())]
            if len(matched):
                hist_group = matched
        values = []
        for name in contract:
            if name in hist_group.columns:
                values.append(population_stability(hist_group[name].to_numpy(dtype=float), live[name].to_numpy(dtype=float)))
        hist_psi = float(np.mean(values)) if values else None
    train_mean = float(np.mean(train_changes)) if train_changes else 0.0
    live_mean = float(np.mean(live_changes)) if live_changes else float(prediction.predicted_change)
    return {
        "time": str(group["time"].iloc[-1]) if "time" in group.columns else "",
        "symbol": symbol,
        "timeframe": timeframe,
        "model": prediction.model,
        "signal": prediction.signal,
        "confidence": prediction.confidence,
        "predicted_change": prediction.predicted_change,
        "feature_hash": digest,
        "feature_drift_psi": float(np.mean(feature_psi)) if feature_psi else 0.0,
        "prediction_drift": live_mean - train_mean,
        "insample_sign_accuracy": sign_accuracy(train_changes, train_realized_sample),
        "live_sign_accuracy": sign_accuracy(live_changes, live_realized_sample),
        "historical_feature_psi": hist_psi,
        "historical_baseline": "historical_csv" if hist_psi is not None else "training_window",
        "bars": int(len(group)),
    }


def _predict_changes(stack, group, contract):
    if len(group) == 0:
        return [], []
    values = group[list(contract)].to_numpy(dtype=float)
    symbol = str(group["symbol"].iloc[-1])
    timeframe = str(group["timeframe"].iloc[-1])
    lookback = max(1, int(getattr(stack.ensemble, "lookback", 1)))
    indexes = list(range(len(group)))
    if len(indexes) > 24:
        step = max(1, len(indexes) // 24)
        indexes = indexes[::step]
        if indexes[-1] != len(group) - 1:
            indexes.append(len(group) - 1)
    changes = []
    realized = []
    series = group["next_return"] if "next_return" in group.columns else None
    for index in indexes:
        start = max(0, index - lookback + 1)
        prediction = stack.predict_window(values[start:index + 1].tolist(), symbol, timeframe)
        changes.append(prediction.predicted_change)
        if series is None:
            realized.append(float("nan"))
        else:
            try:
                realized.append(float(series.iloc[index]))
            except (TypeError, ValueError):
                realized.append(float("nan"))
    return changes, realized


def _historical_features(root, cfg, contract, replay):
    path = historical_frame_path(root, cfg)
    if path is None:
        return None
    if replay is not None and path.resolve() == replay.resolve():
        return None
    try:
        frame = load_market_frame(root, {"replay_csv": str(path)}, [], [], connected=False)
    except Exception as exc:
        log.info("historical csv was not scored (%s)", exc.__class__.__name__)
        return None
    if frame is None or len(frame) == 0:
        return None
    return build_feature_frame(frame, contract)


def _write_outputs(root: Path, rows: List[Dict[str, Any]]) -> None:
    log_dir = root / "Logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "analytics.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key) for key in CSV_FIELDS})
    with (log_dir / "analytics.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def _ping(root: Path, cfg: dict) -> Optional[dict]:
    try:
        return query(endpoint_for(root, cfg), "PING", timeout_ms=1500)
    except Exception:
        return None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FXJEFE market analytics loop")
    parser.add_argument("--project-dir", default=None)
    add_mode_arguments(parser)
    parser.add_argument("--once", action="store_true", help="score one pass and exit")
    parser.add_argument("--interval", type=float, default=0.0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        ctx = build_context(args.project_dir, live=not args.paper)
    except ProjectRootError as exc:
        print("[FATAL] {0}".format(exc), file=sys.stderr)
        return 2
    try:
        ctx["config"] = load_config(ctx["project_root"])
    except (OSError, ValueError):
        ctx["config"] = {}
    if args.interval:
        ctx["config"]["analytics_interval_seconds"] = args.interval
    ctx["code_root"] = Path(__file__).resolve().parent
    if args.once:
        return run_once(ctx)
    try:
        return run_forever(ctx)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
