#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Signal gate: emit only if model loaded + featureset matches EA, server, Predict.mq5, GenerateFeatures.mq5."""
from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

log = logging.getLogger("fxjefe.signals")


def _load_feature_hash_module():
    path = Path(__file__).resolve().parent.parent / "feature_hash.py"
    spec = importlib.util.spec_from_file_location("fxjefe_feature_hash_root", str(path))
    module = importlib.util.module_from_spec(spec)
    sys.modules["fxjefe_feature_hash_root"] = module
    spec.loader.exec_module(module)
    return module


_feature_hash = _load_feature_hash_module()
feature_hash = _feature_hash.feature_hash
hashes_equal = _feature_hash.hashes_equal

AUTO_ENABLED = True
DEMO_COMMENT = "# DEMO: label only; does not disable systems."

def _norm(names: Optional[Iterable[str]]) -> List[str]:
    if not names:
        return []
    return [str(x).strip() for x in names if str(x).strip()]

def same_featureset(a: Sequence[str], b: Sequence[str], *, order_matters: bool = False) -> bool:
    if hashes_equal is not None:
        return hashes_equal(a, b, mode="ordered" if order_matters else "set")
    return (list(a) == list(b)) if order_matters else (set(a) == set(b))

def can_emit_signal(*, model_loaded: bool, model_features=None, ea_features=None, server_features=None,
                    predict_mq5_features=None, generatefeatures_mq5_features=None, mq5_features=None,
                    order_matters: bool = False) -> Tuple[bool, dict]:
    info = {"auto_enabled": AUTO_ENABLED, "demo_comment": DEMO_COMMENT, "model_loaded": bool(model_loaded), "emit": False, "reasons": []}
    if not model_loaded:
        info["reasons"].append("model not loaded"); return False, info
    model_f, ea_f, server_f = _norm(model_features), _norm(ea_features), _norm(server_features)
    pred_f = _norm(predict_mq5_features) or _norm(mq5_features)
    gen_f = _norm(generatefeatures_mq5_features) or _norm(mq5_features)
    for label, val in [("model", model_f), ("EA", ea_f), ("server", server_f), ("Predict.mq5", pred_f), ("GenerateFeatures.mq5", gen_f)]:
        if not val:
            info["reasons"].append(f"{label} feature set empty"); return False, info
    checks = {
        "model_vs_ea": same_featureset(model_f, ea_f, order_matters=order_matters),
        "model_vs_server": same_featureset(model_f, server_f, order_matters=order_matters),
        "model_vs_predict_mq5": same_featureset(model_f, pred_f, order_matters=order_matters),
        "model_vs_generatefeatures_mq5": same_featureset(model_f, gen_f, order_matters=order_matters),
        "predict_vs_generatefeatures_mq5": same_featureset(pred_f, gen_f, order_matters=order_matters),
    }
    info["matches"] = checks
    if feature_hash:
        info["hashes"] = {k: feature_hash(v, length=16) for k, v in [("model", model_f), ("ea", ea_f), ("server", server_f), ("predict_mq5", pred_f), ("generatefeatures_mq5", gen_f)]}
    if not all(checks.values()):
        info["reasons"].append("featureset mismatch: " + str([k for k,v in checks.items() if not v])); return False, info
    info["emit"] = True
    info["reasons"].append("model loaded + featureset aligned")
    return True, info

def _models_present(ctx) -> bool:
    paths = ctx.get("paths") or {}
    raw = paths.get("models_path")
    folder = Path(raw) if raw else ctx["project_root"] / "models"
    if not folder.is_dir():
        return False
    patterns = ("*.pkl", "*.joblib", "*.ubj", "*xgb*.json", "*model*.json")
    return any(folder.glob(pattern) for pattern in patterns)


def _role_features(ctx, cfg, contract):
    roles = ctx.get("feature_roles") if isinstance(ctx.get("feature_roles"), dict) else {}
    def pick(name):
        if name in roles:
            return list(roles[name] or [])
        return list(contract)
    return {
        "model": pick("model"),
        "ea": pick("ea"),
        "server": pick("server"),
        "predict_mq5": pick("predict_mq5"),
        "generatefeatures_mq5": pick("generatefeatures_mq5"),
    }


def _signature_widths(ctx):
    import json
    from pathlib import Path
    paths = ctx.get("paths") or {}
    raw = paths.get("models_path")
    folder = Path(raw) if raw else ctx["project_root"] / "models"
    widths = []
    if not folder.is_dir():
        return widths
    for path in sorted(folder.glob("*.signature.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log.error("cannot read model signature %s", path)
            widths.append(-1)
            continue
        if "n_inputs" in data:
            widths.append(int(data["n_inputs"]))
        elif isinstance(data.get("features"), list):
            widths.append(len(data["features"]))
    return widths


def run(ctx) -> int:
    """Refuse to emit when the featureset contract does not match, and fail on a 28-input model."""
    all_roles_match = _feature_hash.all_roles_match
    require_model_width = _feature_hash.require_model_width
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else None
    if cfg is None:
        from path_resolver import load_config
        try:
            cfg = load_config(ctx["project_root"])
        except (OSError, ValueError):
            cfg = {}
        ctx["config"] = cfg
    contract = list(ctx.get("features") or cfg.get("features") or [])
    for width in _signature_widths(ctx):
        message = require_model_width(width, len(contract))
        if message:
            log.error("%s", message)
            ctx["signal_emit"] = False
            return 1
    loaded = _models_present(ctx)
    roles = _role_features(ctx, cfg, contract)
    matched, info = all_roles_match(roles, mode="ordered")
    require_match = bool(cfg.get("signal_require_featureset_match", True))
    ok, gate_info = can_emit_signal(
        model_loaded=loaded,
        model_features=roles["model"],
        ea_features=roles["ea"],
        server_features=roles["server"],
        predict_mq5_features=roles["predict_mq5"],
        generatefeatures_mq5_features=roles["generatefeatures_mq5"],
        order_matters=True,
    )
    if require_match and not matched:
        ok = False
        log.error("signal_require_featureset_match: roles do not match %s", info.get("mismatches"))
    ctx["signal_emit"] = bool(ok and (matched or not require_match))
    log.info("signal_gate emit=%s model_loaded=%s match=%s reasons=%s", ctx["signal_emit"], loaded, matched, gate_info.get("reasons"))
    if ctx["signal_emit"]:
        return 0
    if not ctx.get("dry_run", False) and cfg.get("signal_require_model_loaded", True) and not loaded:
        log.error("live mode requires a model file under the models path")
        return 1
    return 0


def main(argv=None) -> int:
    code_root = Path(__file__).resolve().parent.parent
    if str(code_root) not in sys.path:
        sys.path.insert(0, str(code_root))
    from path_resolver import stage_main
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
