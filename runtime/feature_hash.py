#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load the repository-root feature-hash contract by file path.

Importing the name ``feature_hash`` from this directory would select this file
and recurse, so the root module is loaded by its path.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent / "feature_hash.py"
_SPEC = importlib.util.spec_from_file_location("fxjefe_feature_hash_root", str(_PATH))
_MODULE = importlib.util.module_from_spec(_SPEC)
sys.modules.setdefault("fxjefe_feature_hash_root", _MODULE)
_SPEC.loader.exec_module(_MODULE)

align_feature_vector = _MODULE.align_feature_vector
all_roles_match = _MODULE.all_roles_match
canonical_bytes = _MODULE.canonical_bytes
demo = _MODULE.demo
feature_hash = _MODULE.feature_hash
feature_hash_pair = _MODULE.feature_hash_pair
hashes_equal = _MODULE.hashes_equal
normalize_features = _MODULE.normalize_features
require_model_width = _MODULE.require_model_width
snapshot_dict = _MODULE.snapshot_dict
