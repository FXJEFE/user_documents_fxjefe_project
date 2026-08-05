#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Async/sync GARCH(1,1) for FXJEFE garch_vol."""
from __future__ import annotations
import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Sequence, Union
import numpy as np
import pandas as pd
try:
    from arch import arch_model
except ImportError:
    arch_model = None
_executor = ThreadPoolExecutor(max_workers=2)

def garch_vol_sync(returns, window: int = 100, scale: float = 100.0) -> float:
    if arch_model is None:
        return 0.0
    try:
        if isinstance(returns, pd.Series):
            r = returns.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
        else:
            r = pd.Series(np.asarray(returns, dtype=float)).replace([np.inf, -np.inf], np.nan).dropna()
        if len(r) < max(20, window // 5):
            return 0.0
        r_win = r.iloc[-window:] * scale
        res = arch_model(r_win, vol="Garch", p=1, q=1, mean="Zero", rescale=False).fit(disp="off", show_warning=False)
        vol = float(res.conditional_volatility.iloc[-1]) / scale
        return float(vol) if np.isfinite(vol) and vol >= 0 else 0.0
    except Exception:
        return 0.0

async def garch_vol_async(returns, window: int = 100, scale: float = 100.0) -> float:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, lambda: garch_vol_sync(returns, window=window, scale=scale))

def garch_vol_from_close_df(df: pd.DataFrame, price_col: str = "close", window: int = 100) -> float:
    if df is None or df.empty or price_col not in df.columns:
        return 0.0
    close = pd.to_numeric(df[price_col], errors="coerce")
    rets = np.log(close / close.shift(1)).replace([np.inf, -np.inf], np.nan).dropna()
    return garch_vol_sync(rets, window=window)
