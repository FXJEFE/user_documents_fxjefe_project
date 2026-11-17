#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FXJEFE feature hashing — scalable featureset identity (UTF-8)."""
from __future__ import annotations
import hashlib
import json
import logging
import sys
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from path_resolver import stage_main

log = logging.getLogger("fxjefe.features")

def normalize_features(names: Optional[Iterable[str]]) -> List[str]:
    if not names:
        return []
    return [str(x).strip() for x in names if str(x).strip()]

def canonical_bytes(names: Sequence[str], *, mode: str = "set") -> bytes:
    """UTF-8 bytes of names joined by newline. No extra trailing newline."""
    feats = normalize_features(names)
    if mode == "ordered":
        payload = "\n".join(feats)
    else:
        payload = "\n".join(sorted(set(feats)))
    return payload.encode("utf-8")

def feature_hash(names: Optional[Iterable[str]], *, mode: str = "set", length: Optional[int] = None) -> str:
    digest = hashlib.sha256(canonical_bytes(list(names or []), mode=mode)).hexdigest()
    return digest[:int(length)] if length else digest

def feature_hash_pair(names: Optional[Iterable[str]]) -> Dict[str, Any]:
    feats = normalize_features(names)
    return {
        "count": len(feats),
        "unique": len(set(feats)),
        "hash_set": feature_hash(feats, mode="set"),
        "hash_set_short": feature_hash(feats, mode="set", length=16),
        "hash_ordered": feature_hash(feats, mode="ordered"),
        "hash_ordered_short": feature_hash(feats, mode="ordered", length=16),
    }

def hashes_equal(a, b, *, mode: str = "set") -> bool:
    return feature_hash(a, mode=mode) == feature_hash(b, mode=mode)

def all_roles_match(sets: Dict[str, Sequence[str]], *, mode: str = "set") -> Tuple[bool, Dict[str, Any]]:
    """True when every non-empty role shares one hash. Empty roles are ignored.

    Reference preference: model, ea, server, predict_mq5, generatefeatures_mq5.
    """
    order = ["model", "ea", "server", "predict_mq5", "generatefeatures_mq5"]
    hashes = {key: feature_hash(value, mode=mode) for key, value in sets.items()}
    non_empty = {key: hashes[key] for key, value in sets.items() if normalize_features(value)}
    if not non_empty:
        return True, {"ok": True, "reference": None, "reference_hash": None, "hashes": hashes, "mismatches": [], "reason": "no non-empty roles"}
    ref_key = next((key for key in order if key in non_empty), next(iter(non_empty)))
    ref = non_empty[ref_key]
    mismatches = [key for key, digest in non_empty.items() if digest != ref]
    return len(mismatches) == 0, {
        "ok": not mismatches,
        "reference": ref_key,
        "reference_hash": ref,
        "hashes": hashes,
        "mismatches": mismatches,
    }


def align_feature_vector(values: Optional[Dict[str, Any]], contract: Sequence[str]) -> List[float]:
    """Ordered contract vector. Missing keys become 0.0. Names are not filtered out."""
    row = values or {}
    out = []
    for name in contract:
        if name in row and row[name] is not None:
            try:
                number = float(row[name])
            except (TypeError, ValueError):
                number = 0.0
        else:
            number = 0.0
        out.append(number)
    return out


def require_model_width(n_inputs: Optional[int], contract_len: int) -> Optional[str]:
    """Fail loudly when a model signature does not match the contract, including 28 vs 29."""
    if n_inputs is None:
        return None
    if int(n_inputs) != int(contract_len):
        return (
            "model signature has {0} inputs; the feature contract has {1}. "
            "Refusing to emit. A 28-input model does not match the 29-feature contract.".format(
                int(n_inputs), int(contract_len)
            )
        )
    return None


def demo() -> None:
    forward = ["spread", "sentiment"]
    reverse = list(reversed(forward))
    print("set_equal", hashes_equal(forward, reverse, mode="set"))
    print("ordered_equal", hashes_equal(forward, reverse, mode="ordered"))
    print("pair", json.dumps(feature_hash_pair(forward)))

def snapshot_dict(names: Sequence[str], *, kind: str = "features") -> Dict[str, Any]:
    feats = normalize_features(names)
    pair = feature_hash_pair(feats)
    return {"kind": kind, "features": feats, "count": len(feats), "unique": len(set(feats)), **{k: pair[k] for k in pair if k.startswith("hash")}}

def run(ctx: Dict[str, Any]) -> int:
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else None
    if cfg is None:
        from path_resolver import load_config
        try:
            cfg = load_config(ctx["project_root"])
        except (OSError, ValueError):
            cfg = {}
        ctx["config"] = cfg
    feats = cfg.get("features") or []
    if not isinstance(feats, list) or not feats:
        log.error("config features list is empty")
        return 1
    ctx["features"] = [str(item) for item in feats]
    log.info(
        "feature_hash count=%s set=%s ordered=%s",
        len(ctx["features"]),
        feature_hash(ctx["features"], mode="set", length=16),
        feature_hash(ctx["features"], mode="ordered", length=16),
    )
    return 0


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--demo" in argv:
        demo()
        return 0
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
