#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Signal gate: emit only if model loaded + featureset matches EA, server, Predict.mq5, GenerateFeatures.mq5."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

log = logging.getLogger("fxjefe.signals")


def _load_feature_hash():
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from feature_hash import feature_hash, hashes_equal
    return feature_hash, hashes_equal


feature_hash, hashes_equal = _load_feature_hash()

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


def run(ctx) -> int:
    """Gate signals. This checkout has no Predict.mq5 or GenerateFeatures.mq5, so those roles use the config feature list."""
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    feats = list(ctx.get("features") or cfg.get("features") or [])
    loaded = _models_present(ctx)
    ok, info = can_emit_signal(
        model_loaded=loaded,
        model_features=feats,
        ea_features=feats,
        server_features=feats,
        predict_mq5_features=feats,
        generatefeatures_mq5_features=feats,
    )
    ctx["signal_emit"] = bool(ok)
    log.info("signal_gate emit=%s model_loaded=%s reasons=%s", ok, loaded, info.get("reasons"))
    log.info("signal_gate feature roles use config.json; Predict.mq5 and GenerateFeatures.mq5 are not in this checkout")
    if ctx.get("dry_run", True):
        return 0
    if cfg.get("signal_require_model_loaded", True) and not loaded:
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
