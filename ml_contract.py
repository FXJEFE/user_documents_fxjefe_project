#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared 29-feature contract for every FXJEFE model.

Names and their ordered SHA-256 come from config.json (ALIGNMENT_V2).
TA-Lib fills the columns it owns when the fxjefe38 stack is installed.
The numpy path is the fallback so paper runs and CI do not need the C library.
Symbols and timeframes are read from config, then from the FTMO file.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from feature_hash import align_feature_vector, feature_hash

log = logging.getLogger("fxjefe.ml.contract")

CONTRACT_COUNT = 29
MQL_ARRAY = re.compile(r"FXJEFE_FEATURES\s*\[[^\]]*\]\s*=\s*\{(.*?)\};", re.S)
MQL_NAME = re.compile(r'"([A-Za-z0-9_]+)"')
TIMEFRAME_ATTR = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def contract_from_config(cfg: Optional[Dict[str, Any]]) -> List[str]:
    raw = (cfg or {}).get("features") or []
    return [str(item).strip() for item in raw if str(item).strip()]


def ordered_feature_hash(names: Sequence[str]) -> str:
    return feature_hash(list(names), mode="ordered")


def vector_from_mapping(values: Optional[Dict[str, Any]], contract: Sequence[str]) -> List[float]:
    return align_feature_vector(values, contract)


def read_mql_features(path: Path) -> List[str]:
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    found = MQL_ARRAY.search(text)
    if not found:
        return []
    return MQL_NAME.findall(found.group(1))


def mql_contract_paths(code_root: Path) -> Dict[str, Path]:
    root = Path(code_root)
    return {
        "predict_mqh": root / "mql5" / "Include" / "predict.mqh",
        "predict_mq5": root / "mql5" / "Experts" / "Predict.mq5",
        "generatefeatures_mq5": root / "mql5" / "Scripts" / "GenerateFeatures.mq5",
    }


def mql_feature_roles(code_root: Path) -> Dict[str, List[str]]:
    paths = mql_contract_paths(code_root)
    roles: Dict[str, List[str]] = {}
    mqh = read_mql_features(paths["predict_mqh"])
    predict = read_mql_features(paths["predict_mq5"]) or list(mqh)
    generate = read_mql_features(paths["generatefeatures_mq5"])
    if mqh:
        roles["predict_mqh"] = mqh
        roles["ea"] = list(mqh)
        roles["predict_mq5"] = predict
    if generate:
        roles["generatefeatures_mq5"] = generate
    return roles


def sources_match_contract(code_root: Path, contract: Sequence[str]) -> Tuple[bool, List[str]]:
    expected = list(contract)
    problems = [label for label, names in mql_feature_roles(code_root).items() if list(names) != expected]
    return len(problems) == 0, problems


def market_universe(cfg: Optional[Dict[str, Any]], rules: Optional[Dict[str, Any]] = None) -> Tuple[List[str], List[str]]:
    """Symbols and timeframes from config.json, then the FTMO file."""
    cfg = cfg or {}
    rules = rules or {}
    symbols = _name_list(cfg.get("symbols")) or _name_list(rules.get("symbols"))
    timeframes = _name_list(cfg.get("timeframes")) or _name_list(rules.get("timeframes"))
    if not timeframes:
        from fxjefe_paths import TIMEFRAMES_DEFAULT
        timeframes = [str(item) for item in TIMEFRAMES_DEFAULT]
    return symbols, timeframes


def _name_list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def replay_csv_path(root: Path, cfg: Optional[Dict[str, Any]]) -> Optional[Path]:
    cfg = cfg or {}
    raw = str(cfg.get("replay_csv") or "data/replay_sample.csv").strip()
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.is_file():
        return candidate
    sample = root / "data" / "replay_sample.csv"
    if sample.is_file():
        return sample
    return None


def historical_frame_path(root: Path, cfg: Optional[Dict[str, Any]]) -> Optional[Path]:
    from path_resolver import historical_csv
    path = historical_csv(root, cfg or {})
    if path.is_file() and path.stat().st_size > 0:
        return path
    return None


def load_market_frame(
    root: Path,
    cfg: Optional[Dict[str, Any]],
    symbols: Sequence[str],
    timeframes: Sequence[str],
    mt5: Any = None,
    connected: bool = False,
    bars: int = 300,
) -> Any:
    """Live bars from MetaTrader5, otherwise a CSV replay file."""
    import pandas as pd

    if connected and mt5 is not None and symbols:
        live = _frame_from_mt5(mt5, symbols, timeframes, bars)
        if live is not None and len(live):
            return live
        log.info("MT5 returned no bars; using the replay csv")
    path = replay_csv_path(root, cfg)
    if path is None:
        log.info("no MT5 bars and no replay csv under %s", root)
        return pd.DataFrame()
    return _filter_universe(_frame_from_csv(path), symbols, timeframes)


def _filter_universe(frame: Any, symbols: Sequence[str], timeframes: Sequence[str]) -> Any:
    if frame is None or len(frame) == 0:
        return frame
    out = frame
    if symbols and "symbol" in out.columns:
        wanted = {item.upper() for item in symbols}
        present = set(out["symbol"].astype(str).str.upper())
        if present & wanted:
            out = out[out["symbol"].astype(str).str.upper().isin(wanted)]
    if timeframes and "timeframe" in out.columns:
        wanted_tf = {item.upper() for item in timeframes}
        present_tf = set(out["timeframe"].astype(str).str.upper())
        if present_tf & wanted_tf:
            out = out[out["timeframe"].astype(str).str.upper().isin(wanted_tf)]
    return out.reset_index(drop=True)


def _frame_from_csv(path: Path) -> Any:
    import pandas as pd

    frame = pd.read_csv(path)
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if "symbol" not in frame.columns:
        frame["symbol"] = ""
    if "timeframe" not in frame.columns:
        frame["timeframe"] = ""
    frame["symbol"] = frame["symbol"].astype(str)
    frame["timeframe"] = frame["timeframe"].astype(str).str.upper()
    for column in ("open", "high", "low", "close", "volume"):
        if column not in frame.columns:
            frame[column] = 0.0
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    for column in ("spread", "sentiment"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    return frame


def _frame_from_mt5(mt5: Any, symbols: Sequence[str], timeframes: Sequence[str], bars: int) -> Optional[Any]:
    import pandas as pd

    rows = []
    for symbol in symbols:
        for timeframe in timeframes:
            table = _mt5_rates(mt5, symbol, timeframe, bars)
            if table is None or len(table) == 0:
                log.info("MT5 returned no bars for %s %s", symbol, timeframe)
                continue
            table = table.copy()
            table["symbol"] = symbol
            table["timeframe"] = str(timeframe).upper()
            rows.append(table)
    if not rows:
        return None
    return pd.concat(rows, ignore_index=True)


def _mt5_rates(mt5: Any, symbol: str, timeframe: str, bars: int) -> Optional[Any]:
    import pandas as pd

    attr = TIMEFRAME_ATTR.get(str(timeframe).upper())
    if not attr or not hasattr(mt5, attr):
        log.info("timeframe %s has no MT5 constant on this terminal", timeframe)
        return None
    try:
        rates = mt5.copy_rates_from_pos(symbol, getattr(mt5, attr), 0, int(bars))
    except Exception as exc:
        log.info("copy_rates_from_pos failed for %s %s (%s)", symbol, timeframe, exc.__class__.__name__)
        return None
    if rates is None:
        return None
    frame = pd.DataFrame(rates)
    if frame.empty:
        return frame
    frame.columns = [str(column).strip().lower() for column in frame.columns]
    if "tick_volume" in frame.columns and "volume" not in frame.columns:
        frame["volume"] = frame["tick_volume"]
    if "volume" not in frame.columns and "real_volume" in frame.columns:
        frame["volume"] = frame["real_volume"]
    return frame


def build_feature_frame(frame: Any, contract: Sequence[str]) -> Any:
    """Causal features for every symbol/timeframe group. Missing values are 0.0."""
    import pandas as pd

    columns = list(contract) + ["symbol", "timeframe", "close", "next_return"]
    if frame is None or len(frame) == 0:
        return pd.DataFrame(columns=columns)
    pieces = []
    grouped = frame.groupby(["symbol", "timeframe"], sort=False, dropna=False)
    for (symbol, timeframe), group in grouped:
        pieces.append(_features_for_group(group.copy(), contract, str(symbol), str(timeframe)))
    if not pieces:
        return pd.DataFrame(columns=columns)
    return pd.concat(pieces, ignore_index=True)


def _features_for_group(group: Any, contract: Sequence[str], symbol: str, timeframe: str) -> Any:
    import numpy as np
    import pandas as pd

    group = group.reset_index(drop=True)
    if "time" in group.columns:
        group = group.sort_values("time").reset_index(drop=True)
    close = _col(group, "close")
    high = _col(group, "high", close)
    low = _col(group, "low", close)
    open_ = _col(group, "open", close)
    volume = _col(group, "volume", np.ones(len(group)))
    computed = _numpy_features(open_, high, low, close, volume)
    if _use_talib():
        computed = _overlay_talib(computed, high, low, close, volume)
    _apply_garch_last(computed, close)
    computed["spread"] = _col(group, "spread", np.zeros(len(group))) if "spread" in group.columns else np.zeros(len(group))
    computed["sentiment"] = _col(group, "sentiment", np.zeros(len(group))) if "sentiment" in group.columns else np.zeros(len(group))
    computed["price"] = close
    next_return = np.full(len(close), np.nan)
    if len(close) > 1:
        next_return[:-1] = np.log(np.maximum(close[1:], 1e-12) / np.maximum(close[:-1], 1e-12))
    out = {}
    for name in contract:
        values = computed.get(name)
        if values is None:
            out[name] = np.zeros(len(close))
        else:
            out[name] = np.nan_to_num(np.asarray(values, dtype=float), nan=0.0, posinf=0.0, neginf=0.0)
    table = pd.DataFrame(out)
    table["symbol"] = symbol
    table["timeframe"] = timeframe
    table["close"] = close
    table["next_return"] = next_return
    if "time" in group.columns:
        table["time"] = group["time"].astype(str).values
    return table


def _col(group: Any, name: str, fallback: Any = None) -> Any:
    import numpy as np
    import pandas as pd

    if name in group.columns:
        return pd.to_numeric(group[name], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    if fallback is None:
        return np.zeros(len(group))
    return np.asarray(fallback, dtype=float)


def _use_talib() -> bool:
    import os
    if os.environ.get("FXJEFE_FEATURE_BACKEND", "").strip().lower() == "numpy":
        return False
    try:
        from fxjefe_optional import HAS_TALIB
        return bool(HAS_TALIB)
    except Exception:
        return False


def _numpy_features(open_: Any, high: Any, low: Any, close: Any, volume: Any) -> Dict[str, Any]:
    import numpy as np

    prev_close = np.roll(close, 1)
    prev_close[0] = close[0]
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    atr = _wilder(tr, 14)
    ema_fast = _ema(close, 12)
    ema_slow = _ema(close, 26)
    macd = ema_fast - ema_slow
    macd_signal = _ema(macd, 9)
    typical = (high + low + close) / 3.0
    weight = np.where(volume > 0, volume, 1.0)
    vwap = np.cumsum(typical * weight) / np.maximum(np.cumsum(weight), 1e-12)
    return {
        "price": close,
        "atr": atr,
        "ema_diff": ema_fast - ema_slow,
        "rsi": _rsi(close, 14),
        "garch_vol": _ewma_vol(close, 0.94),
        "macd_diff": macd - macd_signal,
        "vwap": vwap,
        "price_vwap_diff": close - vwap,
        "bb_position": _bb_position(close, 20),
        "roc": _ratio_change(close, 10),
        "stochastic": _stochastic(high, low, close, 14),
        "cci": _cci(typical, 20),
        "williams": _williams(high, low, close, 14),
        "momentum": close - _shift(close, 10),
        "realized_vol": _realized(close, 20),
        "chaikin_vol": _ratio_change(_ema(np.maximum(high - low, 0.0), 10), 10),
        "adx": _adx(high, low, close, 14),
        "rvi": _ema(close - open_, 10) / np.maximum(_ema(np.maximum(high - low, 0.0), 10), 1e-12),
        "obv": _obv(close, volume),
        "volume_delta": volume - _shift(volume, 1),
        "ad_line": np.cumsum((((close - low) - (high - close)) / np.maximum(high - low, 1e-12)) * volume),
        "vol_osc": _ema(volume, 5) - _ema(volume, 10),
        "supertrend": _supertrend_distance(high, low, close, atr, 3.0),
        "hma": _hma(close, 16),
        "ichimoku_tenkan": (_rolling_max(high, 9) + _rolling_min(low, 9)) / 2.0,
        "sar": _sar(high, low, 0.02, 0.2),
        "dpo": _shift(close, 20 // 2 + 1) - _rolling_mean(close, 20),
    }


def _overlay_talib(computed: Dict[str, Any], high: Any, low: Any, close: Any, volume: Any) -> Dict[str, Any]:
    try:
        import talib
    except Exception as exc:
        log.info("TA-Lib overlay skipped (%s)", exc.__class__.__name__)
        return computed
    try:
        computed["atr"] = talib.ATR(high, low, close, timeperiod=14)
        computed["rsi"] = talib.RSI(close, timeperiod=14)
        macd, signal, _hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
        computed["macd_diff"] = macd - signal
        computed["roc"] = talib.ROC(close, timeperiod=10) / 100.0
        slowk, _slowd = talib.STOCH(high, low, close)
        computed["stochastic"] = slowk
        computed["cci"] = talib.CCI(high, low, close, timeperiod=20)
        computed["williams"] = talib.WILLR(high, low, close, timeperiod=14)
        computed["momentum"] = talib.MOM(close, timeperiod=10)
        computed["adx"] = talib.ADX(high, low, close, timeperiod=14)
        computed["obv"] = talib.OBV(close, volume)
        computed["sar"] = talib.SAR(high, low, acceleration=0.02, maximum=0.2)
    except Exception as exc:
        log.info("TA-Lib feature overlay failed (%s); numpy values kept", exc.__class__.__name__)
    return computed


def _apply_garch_last(computed: Dict[str, Any], close: Any) -> None:
    try:
        from fxjefe_optional import HAS_ARCH
    except Exception:
        return
    if not HAS_ARCH or len(close) < 30:
        return
    try:
        import pandas as pd
        from garch_async import garch_vol_from_close_df
        value = float(garch_vol_from_close_df(pd.DataFrame({"close": close})))
    except Exception:
        return
    if value > 0:
        computed["garch_vol"][-1] = value


def _shift(values: Any, periods: int) -> Any:
    out = values.copy()
    if periods <= 0 or len(values) == 0:
        return out
    out[periods:] = values[:-periods]
    out[:periods] = values[0]
    return out


def _ema(values: Any, period: int) -> Any:
    import numpy as np
    out = np.zeros(len(values), dtype=float)
    if len(values) == 0:
        return out
    alpha = 2.0 / (float(period) + 1.0)
    out[0] = float(values[0])
    for index in range(1, len(values)):
        value = values[index]
        if not np.isfinite(value):
            out[index] = out[index - 1]
        else:
            out[index] = alpha * float(value) + (1.0 - alpha) * out[index - 1]
    return out


def _wilder(values: Any, period: int) -> Any:
    import numpy as np
    out = np.zeros(len(values), dtype=float)
    if len(values) == 0:
        return out
    if len(values) < period:
        return _ema(values, max(2, period))
    out[period - 1] = float(np.mean(values[:period]))
    for index in range(period, len(values)):
        out[index] = (out[index - 1] * (period - 1) + float(values[index])) / float(period)
    out[:period - 1] = out[period - 1]
    return out


def _rsi(close: Any, period: int) -> Any:
    import numpy as np
    delta = np.diff(close, prepend=close[0])
    gain = _wilder(np.clip(delta, 0.0, None), period)
    loss = _wilder(np.clip(-delta, 0.0, None), period)
    return 100.0 - (100.0 / (1.0 + gain / np.maximum(loss, 1e-12)))


def _rolling_mean(values: Any, period: int) -> Any:
    import numpy as np
    out = np.zeros(len(values), dtype=float)
    csum = np.cumsum(values)
    for index in range(len(values)):
        start = max(0, index - period + 1)
        total = csum[index] - (csum[start - 1] if start else 0.0)
        out[index] = total / float(index - start + 1)
    return out


def _rolling_std(values: Any, period: int) -> Any:
    import numpy as np
    out = np.zeros(len(values), dtype=float)
    for index in range(len(values)):
        start = max(0, index - period + 1)
        window = values[start:index + 1]
        out[index] = float(np.std(window)) if len(window) else 0.0
    return out


def _rolling_max(values: Any, period: int) -> Any:
    import numpy as np
    out = np.zeros(len(values), dtype=float)
    for index in range(len(values)):
        start = max(0, index - period + 1)
        out[index] = float(np.max(values[start:index + 1]))
    return out


def _rolling_min(values: Any, period: int) -> Any:
    import numpy as np
    out = np.zeros(len(values), dtype=float)
    for index in range(len(values)):
        start = max(0, index - period + 1)
        out[index] = float(np.min(values[start:index + 1]))
    return out


def _bb_position(close: Any, period: int) -> Any:
    import numpy as np
    mid = _rolling_mean(close, period)
    std = np.maximum(_rolling_std(close, period), 1e-12)
    return (close - mid) / (2.0 * std)


def _ratio_change(values: Any, period: int) -> Any:
    import numpy as np
    base = _shift(values, period)
    return values / np.maximum(np.abs(base), 1e-12) - 1.0


def _stochastic(high: Any, low: Any, close: Any, period: int) -> Any:
    import numpy as np
    highest = _rolling_max(high, period)
    lowest = _rolling_min(low, period)
    return 100.0 * (close - lowest) / np.maximum(highest - lowest, 1e-12)


def _cci(typical: Any, period: int) -> Any:
    import numpy as np
    mid = _rolling_mean(typical, period)
    deviation = np.zeros(len(typical), dtype=float)
    for index in range(len(typical)):
        start = max(0, index - period + 1)
        deviation[index] = float(np.mean(np.abs(typical[start:index + 1] - mid[index])))
    return (typical - mid) / np.maximum(0.015 * deviation, 1e-12)


def _williams(high: Any, low: Any, close: Any, period: int) -> Any:
    import numpy as np
    highest = _rolling_max(high, period)
    lowest = _rolling_min(low, period)
    return -100.0 * (highest - close) / np.maximum(highest - lowest, 1e-12)


def _realized(close: Any, window: int) -> Any:
    try:
        import pandas as pd
        from realized_vol_features import realized_vol
        return realized_vol(pd.Series(close), window=window).to_numpy(dtype=float)
    except Exception:
        return _ewma_vol(close, 0.94)


def _ewma_vol(close: Any, lam: float) -> Any:
    import numpy as np
    returns = np.zeros(len(close), dtype=float)
    if len(close) > 1:
        returns[1:] = np.log(np.maximum(close[1:], 1e-12) / np.maximum(close[:-1], 1e-12))
    var = np.zeros(len(close), dtype=float)
    var[0] = returns[0] ** 2
    for index in range(1, len(close)):
        var[index] = lam * var[index - 1] + (1.0 - lam) * (returns[index] ** 2)
    return np.sqrt(np.maximum(var, 0.0))


def _adx(high: Any, low: Any, close: Any, period: int) -> Any:
    import numpy as np
    up = high - _shift(high, 1)
    down = _shift(low, 1) - low
    plus_dm = np.where((up > down) & (up > 0), up, 0.0)
    minus_dm = np.where((down > up) & (down > 0), down, 0.0)
    prev = _shift(close, 1)
    tr = np.maximum(high - low, np.maximum(np.abs(high - prev), np.abs(low - prev)))
    tr_s = np.maximum(_wilder(tr, period), 1e-12)
    plus_di = 100.0 * _wilder(plus_dm, period) / tr_s
    minus_di = 100.0 * _wilder(minus_dm, period) / tr_s
    dx = 100.0 * np.abs(plus_di - minus_di) / np.maximum(plus_di + minus_di, 1e-12)
    return _wilder(dx, period)


def _obv(close: Any, volume: Any) -> Any:
    import numpy as np
    direction = np.sign(np.diff(close, prepend=close[0]))
    return np.cumsum(direction * volume)


def _supertrend_distance(high: Any, low: Any, close: Any, atr: Any, multiplier: float) -> Any:
    import numpy as np
    hl2 = (high + low) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    final_upper = upper.copy()
    final_lower = lower.copy()
    trend = np.ones(len(close))
    for index in range(1, len(close)):
        if close[index - 1] <= final_upper[index - 1]:
            final_upper[index] = min(upper[index], final_upper[index - 1])
        if close[index - 1] >= final_lower[index - 1]:
            final_lower[index] = max(lower[index], final_lower[index - 1])
        if trend[index - 1] > 0:
            trend[index] = -1.0 if close[index] < final_lower[index] else 1.0
        else:
            trend[index] = 1.0 if close[index] > final_upper[index] else -1.0
    line = np.where(trend > 0, final_lower, final_upper)
    return (close - line) / np.maximum(atr, 1e-12)


def _wma(values: Any, period: int) -> Any:
    import numpy as np
    period = max(1, int(period))
    weights = np.arange(1, period + 1, dtype=float)
    out = np.zeros(len(values), dtype=float)
    for index in range(len(values)):
        start = max(0, index - period + 1)
        window = values[start:index + 1]
        used = weights[-len(window):]
        out[index] = float(np.dot(window, used) / used.sum()) if len(window) else 0.0
    return out


def _hma(values: Any, period: int) -> Any:
    import numpy as np
    half = max(1, period // 2)
    root = max(1, int(round(float(np.sqrt(period)))))
    return _wma(2.0 * _wma(values, half) - _wma(values, period), root)


def _sar(high: Any, low: Any, step: float, maximum: float) -> Any:
    import numpy as np
    n = len(high)
    out = np.zeros(n, dtype=float)
    if n == 0:
        return out
    bull = True
    ep = float(high[0])
    acc = step
    sar = float(low[0])
    out[0] = sar
    for index in range(1, n):
        sar = sar + acc * (ep - sar)
        if bull:
            sar = min(sar, float(low[index - 1]), float(low[index]))
            if high[index] > ep:
                ep = float(high[index])
                acc = min(maximum, acc + step)
            if low[index] < sar:
                bull = False
                sar = ep
                ep = float(low[index])
                acc = step
        else:
            sar = max(sar, float(high[index - 1]), float(high[index]))
            if low[index] < ep:
                ep = float(low[index])
                acc = min(maximum, acc + step)
            if high[index] > sar:
                bull = True
                sar = ep
                ep = float(high[index])
                acc = step
        out[index] = sar
    return out


def population_stability(expected: Sequence[float], actual: Sequence[float], bins: int = 5) -> float:
    """PSI of actual versus expected. 0 when the sample is too small to bin."""
    import numpy as np
    left = np.asarray(list(expected), dtype=float)
    right = np.asarray(list(actual), dtype=float)
    left = left[np.isfinite(left)]
    right = right[np.isfinite(right)]
    if len(left) < bins or len(right) < 2:
        return 0.0
    edges = np.unique(np.percentile(left, np.linspace(0, 100, bins + 1)))
    if len(edges) < 3:
        return 0.0

    def _share(values: Any) -> Any:
        hist, _edges = np.histogram(values, bins=edges)
        share = hist.astype(float) / max(float(hist.sum()), 1.0)
        share = np.clip(share, 1e-3, None)
        return share / share.sum()

    baseline = _share(left)
    current = _share(right)
    return float(np.sum((current - baseline) * np.log(current / baseline)))


def sign_accuracy(predicted: Sequence[float], realized: Sequence[float]) -> Optional[float]:
    import numpy as np
    pred = np.asarray(list(predicted), dtype=float)
    real = np.asarray(list(realized), dtype=float)
    mask = np.isfinite(pred) & np.isfinite(real) & (pred != 0.0) & (real != 0.0)
    if int(mask.sum()) == 0:
        return None
    return float(np.mean(np.sign(pred[mask]) == np.sign(real[mask])))


def write_replay_sample(path: Path, bars: int = 80) -> Path:
    """Deterministic multi-symbol, multi-timeframe OHLCV for paper replay."""
    import numpy as np
    import pandas as pd

    path.parent.mkdir(parents=True, exist_ok=True)
    symbols = (("EURUSD", 1.10), ("GBPUSD", 1.27))
    timeframes = ("M1", "M5", "M15", "H1")
    rows = []
    for s_index, (symbol, start) in enumerate(symbols):
        for t_index, timeframe in enumerate(timeframes):
            rng = np.random.default_rng(1000 + s_index * 10 + t_index)
            step = np.arange(bars)
            returns = 0.00018 * np.sin(step / 4.0 + t_index) + rng.normal(0.0, 0.00022, bars)
            close = start * np.exp(np.cumsum(returns))
            open_ = np.roll(close, 1)
            open_[0] = close[0]
            high = np.maximum(open_, close) * (1.0 + rng.uniform(0.0, 0.0004, bars))
            low = np.minimum(open_, close) * (1.0 - rng.uniform(0.0, 0.0004, bars))
            volume = rng.integers(80, 1200, bars).astype(float)
            for index in range(bars):
                rows.append({
                    "time": "2024-01-{0:02d}T{1:02d}:{2:02d}:00Z".format(1 + (index // 24), index % 24, (t_index * 5) % 60),
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "open": float(open_[index]),
                    "high": float(high[index]),
                    "low": float(low[index]),
                    "close": float(close[index]),
                    "volume": float(volume[index]),
                    "spread": 0.00012,
                    "sentiment": 0.0,
                })
    pd.DataFrame(rows).to_csv(path, index=False)
    return path
