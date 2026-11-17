#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Rolling-window imputation + feature importance (NaN-safe)."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from path_resolver import stage_main

log = logging.getLogger("fxjefe.model")


def _libs():
    import numpy as np
    import pandas as pd
    return np, pd


def rolling_impute(df, cols: list, window: int = 20):
    np, pd = _libs()
    out = df.copy()
    for c in cols:
        if c not in out.columns:
            out[c] = 0.0
            continue
        s = pd.to_numeric(out[c], errors="coerce").replace([np.inf, -np.inf], np.nan)
        roll = s.rolling(window, min_periods=1).median()
        out[c] = s.fillna(roll).ffill().fillna(0.0)
    return out

def feature_importance_nan_safe(df, features: list, y_col: str):
    np, pd = _libs()
    from sklearn.ensemble import RandomForestClassifier
    data = rolling_impute(df, list(features) + [y_col])
    X = data[features].to_numpy(dtype=float)
    y = data[y_col].to_numpy()
    mask = np.isfinite(X).all(axis=1) & np.isfinite(y)
    X, y = X[mask], y[mask]
    clf = RandomForestClassifier(n_estimators=200, random_state=42, n_jobs=-1)
    clf.fit(X, y)
    return pd.Series(clf.feature_importances_, index=features).sort_values(ascending=False), clf


def run(ctx: Dict[str, Any]) -> int:
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    skip = bool(cfg.get("skip_training_in_pipeline", True)) or bool(ctx.get("dry_run", True))
    if skip:
        log.info("model fit skipped (dry-run or skip_training_in_pipeline)")
        ctx["model_fitted"] = False
        return 0
    log.error("training is not implemented in this checkout; set skip_training_in_pipeline to keep the pipeline paper-only")
    return 1


def main(argv: Optional[list] = None) -> int:
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
