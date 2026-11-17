#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GARCH(1,1) — returns 0.0 if arch missing or fit fails."""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

from path_resolver import historical_csv, stage_main

log = logging.getLogger("fxjefe.features")
_executor = None


def _pool():
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=2)
    return _executor


def _libs():
    import numpy as np
    import pandas as pd
    try:
        from arch import arch_model
    except Exception:
        arch_model = None
    return np, pd, arch_model

def garch_vol_sync(returns, window=100, scale=100.0) -> float:
    np, pd, arch_model = _libs()
    if arch_model is None:
        return 0.0
    try:
        if isinstance(returns, pd.Series):
            r = returns.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
        else:
            r = pd.Series(np.asarray(returns, dtype=float)).replace([np.inf, -np.inf], np.nan).dropna()
        if len(r) < max(20, window // 5):
            return 0.0
        res = arch_model(r.iloc[-window:] * scale, vol="Garch", p=1, q=1, mean="Zero", rescale=False).fit(disp="off", show_warning=False)
        vol = float(res.conditional_volatility.iloc[-1]) / scale
        return float(vol) if np.isfinite(vol) and vol >= 0 else 0.0
    except Exception:
        return 0.0

async def garch_vol_async(returns, window=100, scale=100.0) -> float:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_pool(), lambda: garch_vol_sync(returns, window=window, scale=scale))

def garch_vol_from_close_df(df, price_col="close", window=100) -> float:
    np, pd, _arch_model = _libs()
    if df is None or getattr(df, "empty", True) or price_col not in getattr(df, "columns", []):
        return 0.0
    try:
        close = pd.to_numeric(df[price_col], errors="coerce")
        rets = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
        return garch_vol_sync(rets, window=window)
    except Exception:
        return 0.0


def _csv_path(ctx: Dict[str, Any]):
    if ctx.get("historical_csv"):
        from pathlib import Path
        return Path(ctx["historical_csv"])
    return historical_csv(ctx["project_root"], ctx.get("config") or {})


def run(ctx: Dict[str, Any]) -> int:
    path = _csv_path(ctx)
    if not path.is_file():
        message = "garch skipped; historical csv missing: {0}".format(path)
        if ctx.get("dry_run", True):
            log.info(message)
            return 0
        log.error(message)
        return 1
    try:
        _np, pd, _arch = _libs()
        frame = pd.read_csv(path)
    except ImportError as exc:
        log.error("numpy/pandas required for garch: %s", exc)
        return 1
    value = garch_vol_from_close_df(frame)
    ctx["garch_vol"] = value
    log.info("garch_vol=%s", value)
    return 0


def main(argv: Optional[list] = None) -> int:
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
