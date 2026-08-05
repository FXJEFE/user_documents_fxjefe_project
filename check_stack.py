#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FXJEFE stack smoke test with robust error handling."""
from __future__ import annotations
import importlib, sys, traceback
from typing import List, Tuple

REQUIRED = [
    ("numpy", "numpy"), ("pandas", "pandas"), ("flask", "flask"),
    ("sklearn", "sklearn"), ("joblib", "joblib"), ("requests", "requests"),
]
OPTIONAL = [
    ("xgboost", "xgboost"), ("arch", "arch"), ("pandas_ta", "pandas_ta"),
    ("fastapi", "fastapi"), ("tensorflow", "tensorflow"), ("MetaTrader5", "MetaTrader5"),
]

def try_import(label: str, module: str) -> Tuple[str, str]:
    try:
        importlib.import_module(module)
        return "OK", ""
    except ImportError as e:
        return "FAIL", f"{type(e).__name__}: {e}"
    except OSError as e:
        return "FAIL", f"OSError: {e}"
    except Exception as e:
        return "FAIL", f"{type(e).__name__}: {e}"

def main() -> int:
    print(f"Python {sys.version.split()[0]}  executable={sys.executable}")
    hard_fail = False
    rows: List[str] = []
    for label, mod in REQUIRED:
        status, detail = try_import(label, mod)
        if status == "OK":
            print(f"OK   {label}")
        else:
            hard_fail = True
            print(f"FAIL {label}  {detail}")
            rows.append(f"REQUIRED {label}: {detail}")
    for label, mod in OPTIONAL:
        status, detail = try_import(label, mod)
        if status == "OK":
            print(f"OK   {label}")
        else:
            hint = ""
            if label == "xgboost" and "libomp" in detail:
                hint = "  \u2192 brew install libomp"
            if label == "pandas_ta":
                hint = "  \u2192 pip install pandas-ta (optional)"
            if label == "MetaTrader5":
                hint = "  \u2192 Windows only"
            print(f"SKIP {label}  {detail}{hint}")
            rows.append(f"OPTIONAL {label}: {detail}")
    if hard_fail:
        print("stack INCOMPLETE (required packages missing)")
        return 1
    print("stack OK (required packages present)")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("interrupted", file=sys.stderr)
        raise SystemExit(130)
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
