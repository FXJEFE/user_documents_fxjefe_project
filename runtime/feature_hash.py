#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FXJEFE feature hashing — scalable featureset identity (UTF-8)."""
from __future__ import annotations
import hashlib, json
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

def normalize_features(names: Optional[Iterable[str]]) -> List[str]:
    if not names:
        return []
    return [str(x).strip() for x in names if str(x).strip()]

def canonical_bytes(names: Sequence[str], *, mode: str = "set") -> bytes:
    feats = normalize_features(names)
    if mode == "ordered":
        payload = "\n".join(feats) + ("\n" if feats else "")
    else:
        payload = "\n".join(sorted(set(feats))) + ("\n" if feats else "")
    return payload.encode("utf-8")

def feature_hash(names: Optional[Iterable[str]], *, mode: str = "set", length: Optional[int] = None) -> str:
    digest = hashlib.sha256(canonical_bytes(list(names or []), mode=mode)).hexdigest()
    return digest[:int(length)] if length else digest

def hashes_equal(a, b, *, mode: str = "set") -> bool:
    return feature_hash(a, mode=mode) == feature_hash(b, mode=mode)

def all_roles_match(sets: Dict[str, Sequence[str]], *, mode: str = "set") -> Tuple[bool, dict]:
    order = ["model", "ea", "server", "predict_mq5", "generatefeatures_mq5", "mq5"]
    hashes = {k: feature_hash(v, mode=mode) for k, v in sets.items()}
    non_empty = {k: h for k, h in hashes.items() if h != feature_hash([], mode=mode)}
    if len(non_empty) < 2:
        return False, {"hashes": hashes, "reason": "need two non-empty sets"}
    ref_key = next(k for k in order if k in non_empty)
    ref = non_empty[ref_key]
    mismatches = [k for k, h in non_empty.items() if h != ref]
    return len(mismatches) == 0, {"ok": not mismatches, "reference": ref_key, "reference_hash": ref, "hashes": hashes, "mismatches": mismatches}

if __name__ == "__main__":
    demo = ["price", "atr", "rsi", "macd_diff"]
    print(feature_hash(demo, mode="set", length=16))
    print(all_roles_match({"model": demo, "ea": list(reversed(demo)), "server": demo}))
