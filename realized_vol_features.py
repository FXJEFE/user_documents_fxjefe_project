#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Realized volatility features for FXJEFE."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from path_resolver import historical_csv, stage_main

log = logging.getLogger("fxjefe.features")

_np = None
_pd = None


def _libs():
    global _np, _pd
    if _np is None or _pd is None:
        import numpy as np
        import pandas as pd
        _np = np
        _pd = pd
    return _np, _pd

def log_returns(close):
    np, pd = _libs()
    c = pd.to_numeric(close, errors="coerce")
    r = np.log(c / c.shift(1))
    return r.replace([np.inf, -np.inf], np.nan)

def realized_vol(close, window: int = 20, annualize: bool = False,
                 periods_per_year: float = 252.0 * 24 * 12):
    np, pd = _libs()
    r = log_returns(close)
    rv = np.sqrt(r.pow(2).rolling(window, min_periods=max(2, window // 5)).sum())
    if annualize:
        rv = rv * np.sqrt(periods_per_year / window)
    return rv

def realized_vol_std(close, window: int = 20):
    return log_returns(close).rolling(window, min_periods=max(2, window // 5)).std()

def parkinson_vol(high, low, window: int = 20):
    np, pd = _libs()
    h = pd.to_numeric(high, errors="coerce")
    l = pd.to_numeric(low, errors="coerce")
    hl = np.log(h / l).replace([np.inf, -np.inf], np.nan)
    const = 1.0 / (4.0 * np.log(2.0))
    var = (hl.pow(2) * const).rolling(window, min_periods=max(2, window // 5)).mean()
    return np.sqrt(var)

def garman_klass_vol(open_, high, low, close, window: int = 20):
    np, pd = _libs()
    o = pd.to_numeric(open_, errors="coerce")
    h = pd.to_numeric(high, errors="coerce")
    l = pd.to_numeric(low, errors="coerce")
    c = pd.to_numeric(close, errors="coerce")
    log_hl = np.log(h / l).replace([np.inf, -np.inf], np.nan)
    log_co = np.log(c / o).replace([np.inf, -np.inf], np.nan)
    term = 0.5 * log_hl.pow(2) - (2.0 * np.log(2.0) - 1.0) * log_co.pow(2)
    var = term.rolling(window, min_periods=max(2, window // 5)).mean()
    return np.sqrt(var.clip(lower=0))

def add_realized_vol_features(df, window: int = 20):
    np, pd = _libs()
    out = df.copy()
    cols = {str(c).lower(): c for c in out.columns}
    def col(name):
        return cols.get(name)
    c_close = col("close")
    if c_close is None:
        out["realized_vol"] = 0.0
        return out
    out["realized_vol"] = realized_vol(out[c_close], window=window)
    out["realized_vol_std"] = realized_vol_std(out[c_close], window=window)
    c_high, c_low, c_open = col("high"), col("low"), col("open")
    if c_high is not None and c_low is not None:
        out["parkinson_vol"] = parkinson_vol(out[c_high], out[c_low], window=window)
    if all(x is not None for x in (c_open, c_high, c_low, c_close)):
        out["garman_klass_vol"] = garman_klass_vol(
            out[c_open], out[c_high], out[c_low], out[c_close], window=window)
    for c in list(out.columns):
        if "vol" in str(c).lower() or c == "realized_vol":
            out[c] = pd.to_numeric(out[c], errors="coerce").replace([np.inf, -np.inf], np.nan).ffill().fillna(0.0)
    return out

def last_realized_vol(df, window: int = 20) -> float:
    np, pd = _libs()
    tmp = add_realized_vol_features(df, window=window)
    v = tmp["realized_vol"].iloc[-1]
    return float(v) if np.isfinite(v) else 0.0


def _csv_path(ctx: Dict[str, Any]):
    if ctx.get("historical_csv"):
        from pathlib import Path
        return Path(ctx["historical_csv"])
    return historical_csv(ctx["project_root"], ctx.get("config") or {})


def run(ctx: Dict[str, Any]) -> int:
    path = _csv_path(ctx)
    if not path.is_file():
        message = "realized vol skipped; historical csv missing: {0}".format(path)
        if ctx.get("dry_run", True):
            log.info(message)
            return 0
        log.error(message)
        return 1
    try:
        np, pd = _libs()
    except ImportError as exc:
        log.error("numpy/pandas required for realized vol: %s", exc)
        return 1
    frame = pd.read_csv(path)
    value = last_realized_vol(frame)
    ctx["realized_vol"] = value
    log.info("realized_vol=%s", value)
    return 0


def main(argv: Optional[list] = None) -> int:
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
