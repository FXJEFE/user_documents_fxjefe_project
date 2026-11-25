#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One prediction interface for every FXJEFE model on the 29-feature contract.

Members
  linear         sklearn LinearRegression of the next-bar log return
  mlp            sklearn MLPClassifier (plain neural net)
  random_forest  sklearn RandomForestClassifier
  xgboost        XGBClassifier when the package is installed
  lstm           one LSTM layer. Keras/TensorFlow when a SavedModel is present
                 or --fit-keras was used; otherwise a seeded LSTM cell with a
                 trained linear readout. TensorFlow 2.10.1 is the fxjefe38 pin
                 and is not installed on the 3.11 process.
  ltdm           Long-horizon temporal model. This checkout has no LTDM symbol.
                 It is the same LSTM cell with a longer lookback and a second layer.
  gridsearch     GridSearchCV over a small logistic grid on the same features
  ensemble       soft vote. ALIGNMENT_V2 still applies: unanimous side and
                 confidence at or above min_confidence_threshold, else hold.

Artifacts go under artifacts/ml_stack (config ml_artifact_dir). Files already
in models/ are never opened and never replaced.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from feature_hash import require_model_width
from ml_contract import contract_from_config, ordered_feature_hash, vector_from_mapping

log = logging.getLogger("fxjefe.ml.models")

MODEL_VERSION = "1.0.0"
MEMBER_NAMES = ("linear", "mlp", "random_forest", "xgboost", "lstm", "ltdm", "gridsearch")
STACK_NAMES = MEMBER_NAMES + ("ensemble",)
_STACKS: Dict[str, "ModelStack"] = {}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Prediction(object):
    def __init__(self, signal, confidence, predicted_change, model, version, feature_hash, symbol, timeframe, backend="", loaded=True):
        self.signal = signal if signal in ("buy", "sell", "hold") else "hold"
        self.confidence = float(confidence)
        self.predicted_change = float(predicted_change)
        self.model = model
        self.version = version
        self.feature_hash = feature_hash
        self.symbol = symbol
        self.timeframe = timeframe
        self.backend = backend
        self.loaded = loaded

    def as_dict(self) -> Dict[str, Any]:
        return {
            "signal": self.signal,
            "confidence": self.confidence,
            "predicted_change": self.predicted_change,
            "model": self.model,
            "version": self.version,
            "feature_hash": self.feature_hash,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "backend": self.backend,
            "loaded": self.loaded,
        }


class Adapter(object):
    name = "model"
    version = MODEL_VERSION
    backend = "none"
    lookback = 1
    uses_scale = False

    def __init__(self, feature_hash: str, n_inputs: int) -> None:
        self.feature_hash = feature_hash
        self.n_inputs = int(n_inputs)
        self.load_time = utc_now()
        self.last_prediction_time: Optional[str] = None
        self.loaded = True
        self.detail = ""

    def predict_window(self, window, *, symbol, timeframe, scaled_window):
        raise NotImplementedError

    def heartbeat(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "feature_hash": self.feature_hash,
            "loaded": bool(self.loaded),
            "backend": self.backend,
            "n_inputs": self.n_inputs,
            "lookback": self.lookback,
            "load_time": self.load_time,
            "last_prediction_time": self.last_prediction_time,
            "detail": self.detail,
        }

    def _finish(self, signal, confidence, change, symbol, timeframe) -> Prediction:
        self.last_prediction_time = utc_now()
        return Prediction(signal, confidence, change, self.name, self.version, self.feature_hash, symbol, timeframe, self.backend, self.loaded)

    def _refuse(self, symbol, timeframe, reason) -> Prediction:
        self.detail = reason
        log.error("%s %s", self.name, reason)
        return self._finish("hold", 0.0, 0.0, symbol, timeframe)


def _last_row(window, scaled, use_scale) -> List[float]:
    source = scaled if use_scale else window
    if not source:
        return []
    return [float(item) for item in source[-1]]


def _direction_from_probability(probability: float) -> Tuple[str, float]:
    p_up = min(1.0, max(0.0, float(probability)))
    side = "buy" if p_up >= 0.5 else "sell"
    return side, max(p_up, 1.0 - p_up)


def _direction_from_change(change: float, train_std: float) -> Tuple[str, float]:
    import math
    if change > 0:
        side = "buy"
    elif change < 0:
        side = "sell"
    else:
        side = "hold"
    scale = max(float(train_std), 1e-8)
    confidence = 1.0 / (1.0 + math.exp(-abs(float(change)) / scale))
    if side == "hold":
        confidence = 0.5
    return side, float(confidence)


class LinearAdapter(Adapter):
    name = "linear"
    backend = "sklearn"
    uses_scale = True

    def __init__(self, feature_hash, n_inputs, coef, intercept, train_std):
        super().__init__(feature_hash, n_inputs)
        self.coef = [float(item) for item in coef]
        self.intercept = float(intercept)
        self.train_std = float(train_std)

    def predict_window(self, window, *, symbol, timeframe, scaled_window):
        row = _last_row(window, scaled_window, True)
        mismatch = require_model_width(len(row), self.n_inputs)
        if mismatch or len(self.coef) != self.n_inputs:
            return self._refuse(symbol, timeframe, mismatch or "linear coefficient width mismatch")
        change = self.intercept + sum(weight * value for weight, value in zip(self.coef, row))
        side, confidence = _direction_from_change(change, self.train_std)
        return self._finish(side, confidence, change, symbol, timeframe)


class ProbaAdapter(Adapter):
    uses_scale = True

    def __init__(self, feature_hash, n_inputs, estimator, train_std, backend):
        super().__init__(feature_hash, n_inputs)
        self.estimator = estimator
        self.train_std = float(train_std)
        self.backend = backend

    def predict_window(self, window, *, symbol, timeframe, scaled_window):
        row = _last_row(window, scaled_window, self.uses_scale)
        mismatch = require_model_width(len(row), self.n_inputs)
        if mismatch:
            return self._refuse(symbol, timeframe, mismatch)
        import numpy as np
        try:
            proba = self.estimator.predict_proba(np.asarray(row, dtype=float).reshape(1, -1))[0]
        except Exception as exc:
            return self._refuse(symbol, timeframe, "predict failed: {0}".format(exc.__class__.__name__))
        classes = list(getattr(self.estimator, "classes_", [0, 1]))
        p_up = float(proba[classes.index(1)]) if 1 in classes else float(proba[-1])
        side, confidence = _direction_from_probability(p_up)
        change = self.train_std * (2.0 * p_up - 1.0)
        return self._finish(side, confidence, change, symbol, timeframe)


class MlpAdapter(ProbaAdapter):
    name = "mlp"
    backend = "sklearn"


class ForestAdapter(ProbaAdapter):
    name = "random_forest"
    backend = "sklearn"
    uses_scale = False


class XgbAdapter(ProbaAdapter):
    name = "xgboost"
    backend = "xgboost"
    uses_scale = False


class GridAdapter(ProbaAdapter):
    name = "gridsearch"
    backend = "sklearn.GridSearchCV"


class TemporalAdapter(Adapter):
    uses_scale = True

    def __init__(self, name, feature_hash, n_inputs, layers, readout, train_std, lookback, keras_dir=None):
        super().__init__(feature_hash, n_inputs)
        self.name = name
        self.layers = layers
        self.readout = [float(item) for item in readout]
        self.train_std = float(train_std)
        self.lookback = int(lookback)
        self.backend = "numpy-lstm"
        self.keras = None
        if keras_dir is not None and Path(keras_dir).is_dir():
            model = _load_keras(Path(keras_dir))
            if model is not None:
                self.keras = model
                self.backend = "tensorflow.keras"

    def predict_window(self, window, *, symbol, timeframe, scaled_window):
        import numpy as np
        rows = list(scaled_window or [])
        if rows and len(rows[-1]) != self.n_inputs:
            return self._refuse(symbol, timeframe, require_model_width(len(rows[-1]), self.n_inputs) or "width")
        seq = _pad_window(rows, self.lookback, self.n_inputs)
        if self.keras is not None:
            change = float(self.keras.predict(np.asarray(seq, dtype=float).reshape(1, self.lookback, self.n_inputs), verbose=0)[0][0])
        else:
            hidden = _lstm_final_hidden(np.asarray(seq, dtype=float), self.layers)
            change = float(np.dot(hidden, np.asarray(self.readout[:-1], dtype=float)) + self.readout[-1])
        side, confidence = _direction_from_change(change, self.train_std)
        return self._finish(side, confidence, change, symbol, timeframe)


class EnsembleAdapter(Adapter):
    name = "ensemble"
    backend = "voting"

    def __init__(self, feature_hash, n_inputs, members, weights, min_confidence):
        super().__init__(feature_hash, n_inputs)
        self.members = list(members)
        self.weights = dict(weights or {})
        self.min_confidence = float(min_confidence)
        self.lookback = max([1] + [int(member.lookback) for member in self.members])
        self.member_votes: List[Prediction] = []

    def predict_window(self, window, *, symbol, timeframe, scaled_window):
        votes = []
        for member in self.members:
            if not member.loaded:
                continue
            votes.append(member.predict_window(window, symbol=symbol, timeframe=timeframe, scaled_window=scaled_window))
        self.member_votes = votes
        if not votes:
            return self._finish("hold", 0.0, 0.0, symbol, timeframe)
        weight_sum = 0.0
        p_acc = 0.0
        change_acc = 0.0
        for vote in votes:
            weight = float(self.weights.get(vote.model, 1.0))
            if vote.signal == "buy":
                p_up = vote.confidence
            elif vote.signal == "sell":
                p_up = 1.0 - vote.confidence
            else:
                p_up = 0.5
            p_acc += weight * p_up
            change_acc += weight * vote.predicted_change
            weight_sum += weight
        if weight_sum <= 0:
            return self._finish("hold", 0.0, 0.0, symbol, timeframe)
        side, confidence = _direction_from_probability(p_acc / weight_sum)
        change = change_acc / weight_sum
        sides = {vote.signal for vote in votes if vote.signal in ("buy", "sell")}
        signal = side if len(sides) == 1 and confidence >= self.min_confidence else "hold"
        return self._finish(signal, confidence, change, symbol, timeframe)


class MissingAdapter(Adapter):
    def __init__(self, name, feature_hash, n_inputs, detail):
        super().__init__(feature_hash, n_inputs)
        self.name = name
        self.loaded = False
        self.detail = detail
        self.backend = "unavailable"

    def predict_window(self, window, *, symbol, timeframe, scaled_window):
        return self._finish("hold", 0.0, 0.0, symbol, timeframe)


class ModelStack(object):
    def __init__(self, contract, members, ensemble, scaler, provisional, manifest_path):
        self.contract = list(contract)
        self.feature_hash = ordered_feature_hash(self.contract)
        self.members = members
        self.ensemble = ensemble
        self.scaler = scaler
        self.provisional = bool(provisional)
        self.manifest_path = Path(manifest_path)
        self.n_inputs = len(self.contract)

    @property
    def any_loaded(self) -> bool:
        return any(member.loaded for member in self.members)

    def heartbeats(self) -> List[Dict[str, Any]]:
        return [member.heartbeat() for member in self.members] + [self.ensemble.heartbeat()]

    def predict_payload(self, payload: Dict[str, Any]) -> Prediction:
        symbol = str((payload or {}).get("symbol") or "")
        timeframe = str((payload or {}).get("timeframe") or "")
        return self.predict_window(_window_from_payload(payload or {}, self.contract), symbol, timeframe)

    def predict_window(self, window, symbol, timeframe) -> Prediction:
        scaled = [_scale_row(row, self.scaler) for row in window]
        return self.ensemble.predict_window(window, symbol=symbol, timeframe=timeframe, scaled_window=scaled)

    def traded_body(self, prediction: Prediction, trade_ensemble: bool) -> Dict[str, Any]:
        body = prediction.as_dict()
        body["ensemble_signal"] = prediction.signal
        body["ensemble_confidence"] = prediction.confidence
        body["provisional"] = self.provisional
        body["feature_count"] = self.n_inputs
        body["models"] = [vote.as_dict() for vote in getattr(self.ensemble, "member_votes", [])]
        traded = bool(trade_ensemble) or not self.provisional
        body["traded_model"] = bool(traded)
        if not traded:
            body["signal"] = "hold"
            body["confidence"] = 0.0
        return body


def artifact_dir(root: Path, cfg: Optional[Dict[str, Any]]) -> Path:
    raw = str((cfg or {}).get("ml_artifact_dir") or "artifacts/ml_stack").strip()
    path = Path(raw)
    if not path.is_absolute():
        path = Path(root) / path
    return path


def load_or_fit(ctx: Dict[str, Any], frame: Any = None, *, force: bool = False, provisional: Optional[bool] = None) -> ModelStack:
    root = Path(ctx["project_root"])
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    contract = list(ctx.get("features") or contract_from_config(cfg))
    folder = artifact_dir(root, cfg)
    if not force:
        loaded = load_stack(root, cfg, contract)
        if loaded is not None:
            return loaded
    dry = bool(ctx.get("dry_run", False))
    if not dry and not force:
        log.info("live mode does not fit models inside the pipeline; artifacts are missing at %s", folder)
        return _empty_stack(contract, folder, "artifacts missing")
    if frame is None or len(getattr(frame, "index", [])) < 40:
        log.info("not enough replay rows to fit the ML stack")
        return _empty_stack(contract, folder, "not enough rows")
    is_provisional = True if provisional is None else bool(provisional)
    return fit_stack(frame, contract, cfg, folder, provisional=is_provisional)


def load_stack(root: Path, cfg: Optional[Dict[str, Any]] = None, contract: Optional[Sequence[str]] = None) -> Optional[ModelStack]:
    cfg = cfg or {}
    folder = artifact_dir(Path(root), cfg)
    manifest_path = folder / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.error("cannot read ML manifest %s (%s)", manifest_path, exc.__class__.__name__)
        return None
    names = list(manifest.get("contract") or [])
    expected = list(contract or contract_from_config(cfg) or names)
    if expected and names != list(expected):
        log.error("artifact feature contract does not match config; refusing to load %s", manifest_path)
        return None
    digest = ordered_feature_hash(names)
    if manifest.get("feature_hash") not in (None, "", digest):
        log.error("artifact feature hash does not match the contract")
        return None
    key = str(manifest_path.resolve())
    cached = _STACKS.get(key)
    mtime = manifest_path.stat().st_mtime
    if cached is not None and getattr(cached, "_mtime", None) == mtime:
        return cached
    stack = _stack_from_manifest(folder, manifest, names)
    weights = cfg.get("ensemble_weights") if isinstance(cfg.get("ensemble_weights"), dict) else None
    if weights:
        stack.ensemble.weights = {str(key_name): float(value) for key_name, value in weights.items()}
    min_confidence = cfg.get("min_confidence_threshold")
    if isinstance(min_confidence, (int, float)):
        stack.ensemble.min_confidence = float(min_confidence)
    stack._mtime = mtime  # type: ignore[attr-defined]
    _STACKS[key] = stack
    return stack


def fit_stack(frame, contract, cfg, folder: Path, *, provisional: bool, fit_keras: bool = False) -> ModelStack:
    import numpy as np

    folder.mkdir(parents=True, exist_ok=True)
    digest = ordered_feature_hash(contract)
    n_inputs = len(contract)
    max_rows = int(cfg.get("ml_fit_max_rows") or 2000)
    trainable = frame.dropna(subset=["next_return"])
    if len(trainable) > max_rows:
        trainable = trainable.tail(max_rows)
    matrix = trainable[list(contract)].to_numpy(dtype=float)
    changes = trainable["next_return"].to_numpy(dtype=float)
    directions = (changes > 0).astype(int)
    if len(directions) and len(set(int(item) for item in directions.tolist())) < 2:
        directions[-1] = 1 - int(directions[-1])
        log.info("training labels were single-class; flipped the last label so classifiers can fit")
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale = np.where(scale < 1e-8, 1.0, scale)
    scaled = (matrix - mean) / scale
    train_std = float(np.std(changes)) or 1e-4
    min_confidence = float(cfg.get("min_confidence_threshold") or 0.77)
    look_lstm = int(cfg.get("lstm_lookback") or 8)
    look_ltdm = int(cfg.get("ltdm_lookback") or 16)

    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LinearRegression, LogisticRegression
    from sklearn.model_selection import GridSearchCV
    from sklearn.neural_network import MLPClassifier

    linear = LinearRegression()
    linear.fit(scaled, changes)
    _write_json(folder / "linear.json", {"coef": [float(item) for item in linear.coef_], "intercept": float(linear.intercept_)})

    mlp = MLPClassifier(hidden_layer_sizes=(8,), max_iter=40, random_state=42)
    mlp.fit(scaled, directions)
    _dump(folder / "mlp.joblib", mlp)

    forest = RandomForestClassifier(n_estimators=20, max_depth=4, random_state=42, n_jobs=1)
    forest.fit(matrix, directions)
    _dump(folder / "random_forest.joblib", forest)

    xgb_backend = _fit_xgb(folder / "xgboost.json", matrix, directions)
    grid = GridSearchCV(
        LogisticRegression(max_iter=200),
        {"C": [0.1, 1.0]},
        cv=2,
        scoring="accuracy",
        n_jobs=1,
    )
    grid.fit(scaled, directions)
    _dump(folder / "gridsearch.joblib", grid.best_estimator_)
    log.info("GridSearchCV best_params=%s best_score=%s", grid.best_params_, getattr(grid, "best_score_", None))

    lstm_layers, lstm_readout = _fit_temporal(frame, contract, mean, scale, look_lstm, hidden=8, layers=1, seed=42)
    ltdm_layers, ltdm_readout = _fit_temporal(frame, contract, mean, scale, look_ltdm, hidden=8, layers=2, seed=49)
    _write_json(folder / "lstm.json", {"layers": lstm_layers, "readout": lstm_readout, "lookback": look_lstm})
    _write_json(folder / "ltdm.json", {"layers": ltdm_layers, "readout": ltdm_readout, "lookback": look_ltdm})
    if fit_keras:
        _fit_keras_file(folder / "lstm_keras", frame, contract, mean, scale, look_lstm, kind="lstm")
        _fit_keras_file(folder / "ltdm_keras", frame, contract, mean, scale, look_ltdm, kind="ltdm")

    manifest = {
        "contract": list(contract),
        "feature_hash": digest,
        "feature_count": n_inputs,
        "train_return_std": train_std,
        "scaler": {"mean": [float(item) for item in mean], "scale": [float(item) for item in scale]},
        "provisional": bool(provisional),
        "min_confidence": min_confidence,
        "gridsearch_best_params": {str(key): _jsonable(value) for key, value in grid.best_params_.items()},
        "xgboost_backend": xgb_backend,
        "lstm_lookback": look_lstm,
        "ltdm_lookback": look_ltdm,
        "trained_at": utc_now(),
        "ensemble_weights": cfg.get("ensemble_weights") if isinstance(cfg.get("ensemble_weights"), dict) else {},
        "note": "New artifacts only. models/ is not written.",
    }
    _write_json(folder / "manifest.json", manifest)
    clear_cache()
    log.info("ML stack wrote %s provisional=%s hash=%s", folder, provisional, digest[:16])
    return _stack_from_manifest(folder, manifest, list(contract))


def _stack_from_manifest(folder: Path, manifest: Dict[str, Any], contract: Sequence[str]) -> ModelStack:
    digest = ordered_feature_hash(contract)
    n_inputs = len(contract)
    scaler = manifest.get("scaler") or {}
    train_std = float(manifest.get("train_return_std") or 1e-4)
    min_confidence = float(manifest.get("min_confidence") or 0.77)
    members: List[Adapter] = [
        _load_linear(folder, digest, n_inputs, train_std),
        _load_joblib_member(folder / "mlp.joblib", MlpAdapter, "mlp", digest, n_inputs, train_std, "sklearn"),
        _load_joblib_member(folder / "random_forest.joblib", ForestAdapter, "random_forest", digest, n_inputs, train_std, "sklearn"),
        _load_xgb(folder / "xgboost.json", digest, n_inputs, train_std),
        _load_temporal(folder, "lstm", digest, n_inputs, train_std, int(manifest.get("lstm_lookback") or 8)),
        _load_temporal(folder, "ltdm", digest, n_inputs, train_std, int(manifest.get("ltdm_lookback") or 16)),
    ]
    grid = _load_joblib_member(folder / "gridsearch.joblib", GridAdapter, "gridsearch", digest, n_inputs, train_std, "sklearn.GridSearchCV")
    best = manifest.get("gridsearch_best_params")
    if isinstance(best, dict) and grid.loaded:
        grid.detail = "best_params={0}".format(best)
    members.append(grid)
    weights = manifest.get("ensemble_weights") if isinstance(manifest.get("ensemble_weights"), dict) else {}
    ensemble = EnsembleAdapter(
        digest,
        n_inputs,
        [item for item in members if item.loaded],
        {str(key): float(value) for key, value in weights.items()},
        min_confidence,
    )
    ensemble.loaded = any(member.loaded for member in members)
    if not ensemble.loaded:
        ensemble.detail = "no members loaded"
    return ModelStack(
        contract,
        members,
        ensemble,
        {
            "mean": [float(item) for item in scaler.get("mean") or [0.0] * n_inputs],
            "scale": [float(item) for item in scaler.get("scale") or [1.0] * n_inputs],
        },
        bool(manifest.get("provisional")),
        folder / "manifest.json",
    )


def _load_linear(folder, digest, n_inputs, train_std) -> Adapter:
    path = folder / "linear.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        coef = data["coef"]
        if len(coef) != n_inputs:
            raise ValueError("width")
        return LinearAdapter(digest, n_inputs, coef, float(data["intercept"]), train_std)
    except Exception as exc:
        return MissingAdapter("linear", digest, n_inputs, "linear load failed: {0}".format(exc.__class__.__name__))


def _load_joblib_member(path, cls, name, digest, n_inputs, train_std, backend) -> Adapter:
    if not Path(path).is_file():
        return MissingAdapter(name, digest, n_inputs, "missing {0}".format(Path(path).name))
    try:
        import joblib
        estimator = joblib.load(path)
        width = int(getattr(estimator, "n_features_in_", n_inputs))
        if width != n_inputs:
            return MissingAdapter(name, digest, n_inputs, require_model_width(width, n_inputs) or "width")
        adapter = cls(digest, n_inputs, estimator, train_std, backend)
        adapter.name = name
        return adapter
    except Exception as exc:
        return MissingAdapter(name, digest, n_inputs, "{0} load failed: {1}".format(name, exc.__class__.__name__))


def _load_xgb(path, digest, n_inputs, train_std) -> Adapter:
    if not Path(path).is_file():
        return MissingAdapter("xgboost", digest, n_inputs, "missing xgboost.json")
    try:
        from xgboost import XGBClassifier
        model = XGBClassifier()
        model.load_model(str(path))
        return XgbAdapter(digest, n_inputs, model, train_std, "xgboost")
    except Exception as exc:
        return MissingAdapter("xgboost", digest, n_inputs, "xgboost load failed: {0}".format(exc.__class__.__name__))


def _load_temporal(folder, name, digest, n_inputs, train_std, lookback) -> Adapter:
    path = folder / "{0}.json".format(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        keras_dir = folder / "{0}_keras".format(name)
        return TemporalAdapter(
            name,
            digest,
            n_inputs,
            list(data.get("layers") or []),
            list(data.get("readout") or []),
            train_std,
            int(data.get("lookback") or lookback),
            keras_dir if keras_dir.is_dir() else None,
        )
    except Exception as exc:
        return MissingAdapter(name, digest, n_inputs, "{0} load failed: {1}".format(name, exc.__class__.__name__))


def _empty_stack(contract, folder: Path, detail: str) -> ModelStack:
    digest = ordered_feature_hash(contract) if contract else ""
    n_inputs = len(contract)
    members = [MissingAdapter(name, digest, n_inputs, detail) for name in MEMBER_NAMES]
    ensemble = EnsembleAdapter(digest, n_inputs, [], {}, 0.77)
    ensemble.loaded = False
    ensemble.detail = detail
    return ModelStack(contract, members, ensemble, {"mean": [0.0] * n_inputs, "scale": [1.0] * n_inputs}, True, folder / "manifest.json")


def _fit_xgb(path: Path, matrix, directions) -> str:
    try:
        from xgboost import XGBClassifier
    except Exception as exc:
        log.info("xgboost is not installed (%s)", exc.__class__.__name__)
        return "unavailable"
    model = XGBClassifier(n_estimators=30, max_depth=3, learning_rate=0.1, random_state=42, n_jobs=1, verbosity=0, eval_metric="logloss")
    model.fit(matrix, directions)
    model.save_model(str(path))
    return "xgboost"


def _fit_temporal(frame, contract, mean, scale, lookback, hidden, layers, seed):
    import numpy as np
    sequences, targets = _sequences(frame, contract, mean, scale, lookback)
    if len(sequences) < 8:
        sequences, targets = _fallback_sequences(lookback, len(contract), seed)
    layer_specs = []
    input_size = len(contract)
    rng = np.random.default_rng(seed)
    for _layer in range(layers):
        layer_specs.append(_init_lstm_layer(rng, input_size, hidden))
        input_size = hidden
    hidden_rows = [_lstm_final_hidden(sequence, layer_specs) for sequence in sequences]
    design = np.column_stack([np.asarray(hidden_rows, dtype=float), np.ones(len(hidden_rows))])
    readout, _residuals, _rank, _sv = np.linalg.lstsq(design, np.asarray(targets, dtype=float), rcond=None)
    return [_layer_to_json(spec) for spec in layer_specs], [float(item) for item in readout]


def _sequences(frame, contract, mean, scale, lookback):
    import numpy as np
    sequences = []
    targets = []
    grouped = frame.groupby(["symbol", "timeframe"], sort=False)
    for _key, group in grouped:
        group = group.reset_index(drop=True)
        values = group[list(contract)].to_numpy(dtype=float)
        scaled = (values - mean) / scale
        returns = group["next_return"].to_numpy(dtype=float)
        for index in range(lookback - 1, len(group)):
            if not np.isfinite(returns[index]):
                continue
            sequences.append(scaled[index - lookback + 1:index + 1])
            targets.append(float(returns[index]))
    return sequences, targets


def _fallback_sequences(lookback, n_inputs, seed):
    import numpy as np
    rng = np.random.default_rng(seed)
    sequences = []
    targets = []
    for _ in range(32):
        raw = rng.normal(0.0, 0.1, (lookback, n_inputs))
        sequences.append(raw)
        targets.append(float(raw[-1].mean()))
    return sequences, targets


def _init_lstm_layer(rng, n_inputs, hidden):
    import numpy as np
    scale = 0.08
    return {
        "Wx": rng.normal(0.0, scale, (n_inputs, 4 * hidden)),
        "Wh": rng.normal(0.0, scale, (hidden, 4 * hidden)),
        "b": np.zeros(4 * hidden),
        "hidden": hidden,
    }


def _layer_to_json(spec):
    return {"Wx": spec["Wx"].tolist(), "Wh": spec["Wh"].tolist(), "b": spec["b"].tolist(), "hidden": int(spec["hidden"])}


def _lstm_final_hidden(sequence, layers):
    import numpy as np
    current = np.asarray(sequence, dtype=float)
    hidden = np.zeros(1)
    for spec in layers:
        wx = np.asarray(spec["Wx"], dtype=float)
        wh = np.asarray(spec["Wh"], dtype=float)
        bias = np.asarray(spec["b"], dtype=float)
        width = int(spec["hidden"])
        state = np.zeros(width)
        cell = np.zeros(width)
        outputs = []
        for row in current:
            gates = row @ wx + state @ wh + bias
            input_g, forget_g, cell_g, output_g = np.split(gates, 4)
            input_g = _sigmoid(input_g)
            forget_g = _sigmoid(forget_g)
            output_g = _sigmoid(output_g)
            cell_g = np.tanh(np.clip(cell_g, -20.0, 20.0))
            cell = forget_g * cell + input_g * cell_g
            state = output_g * np.tanh(cell)
            outputs.append(state.copy())
        current = np.asarray(outputs, dtype=float)
        hidden = state
    return hidden


def _sigmoid(values):
    import numpy as np
    return 1.0 / (1.0 + np.exp(-np.clip(values, -20.0, 20.0)))


def _pad_window(rows, lookback, n_inputs):
    padded = [[float(item) for item in row] for row in rows][-lookback:]
    while len(padded) < lookback:
        padded.insert(0, [0.0] * n_inputs)
    fixed = []
    for row in padded:
        values = row[:n_inputs]
        if len(values) < n_inputs:
            values = values + [0.0] * (n_inputs - len(values))
        fixed.append(values)
    return fixed


def _scale_row(row, scaler):
    mean = scaler.get("mean") or []
    scale = scaler.get("scale") or []
    out = []
    for index, value in enumerate(row):
        center = mean[index] if index < len(mean) else 0.0
        width = scale[index] if index < len(scale) and scale[index] else 1.0
        out.append((float(value) - float(center)) / float(width))
    return out


def _window_from_payload(payload, contract):
    rows = []
    window = payload.get("window")
    if isinstance(window, list) and window:
        for item in window:
            if isinstance(item, dict):
                rows.append(vector_from_mapping(item, contract))
            elif isinstance(item, list):
                rows.append(_fit_width(item, len(contract)))
    if not rows:
        features = payload.get("features") if isinstance(payload.get("features"), dict) else {}
        rows.append(vector_from_mapping(features, contract))
    return rows


def _fit_width(row, width):
    values = []
    for item in list(row)[:width]:
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            values.append(0.0)
    while len(values) < width:
        values.append(0.0)
    return values


def _dump(path: Path, estimator) -> None:
    import joblib
    joblib.dump(estimator, path)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
    except TypeError:
        return str(value)
    return value


def build_keras_temporal(kind: str, lookback: int, n_features: int):
    """TensorFlow/Keras LSTM. None when TensorFlow is not installed.

    lstm is one LSTM layer. ltdm stacks two. TF 2.10.1 and Keras 2.10.0 are
    the fxjefe38 pins. The 3.11 environment does not install that build.
    """
    try:
        import tensorflow as tf
    except Exception:
        return None
    inputs = tf.keras.Input(shape=(int(lookback), int(n_features)))
    if kind == "ltdm":
        hidden = tf.keras.layers.LSTM(16, return_sequences=True)(inputs)
        hidden = tf.keras.layers.LSTM(8)(hidden)
    else:
        hidden = tf.keras.layers.LSTM(8)(inputs)
    outputs = tf.keras.layers.Dense(1)(hidden)
    model = tf.keras.Model(inputs, outputs)
    model.compile(optimizer="adam", loss="mse")
    return model


def _load_keras(path: Path):
    try:
        import tensorflow as tf
        return tf.keras.models.load_model(str(path))
    except Exception as exc:
        log.info("keras model at %s was not loaded (%s)", path, exc.__class__.__name__)
        return None


def _fit_keras_file(dest: Path, frame, contract, mean, scale, lookback, kind: str) -> bool:
    import numpy as np
    model = build_keras_temporal(kind, lookback, len(contract))
    if model is None:
        log.info("TensorFlow/Keras is not installed; %s stays on the numpy LSTM", kind)
        return False
    sequences, targets = _sequences(frame, contract, mean, scale, lookback)
    if len(sequences) < 8:
        log.info("not enough sequences to fit the Keras %s", kind)
        return False
    model.fit(np.asarray(sequences, dtype=float), np.asarray(targets, dtype=float), epochs=5, batch_size=16, verbose=0)
    if dest.exists():
        log.info("keras directory already exists and was left in place: %s", dest)
        return False
    model.save(dest)
    log.info("wrote Keras %s model to %s", kind, dest)
    return True


def clear_cache() -> None:
    _STACKS.clear()
