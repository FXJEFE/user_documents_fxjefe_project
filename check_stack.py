#!/usr/bin/env python3
mods = ["numpy", "pandas", "flask", "sklearn", "xgboost", "joblib", "requests"]
optional = ["arch", "pandas_ta", "fastapi", "tensorflow"]
ok = True
for m in mods:
    try:
        __import__(m if m != "sklearn" else "sklearn")
        print("OK", m)
    except Exception as e:
        print("FAIL", m, e); ok = False
for m in optional:
    try:
        __import__(m); print("OK", m)
    except Exception as e:
        print("SKIP", m, e)
print("stack", "OK" if ok else "INCOMPLETE")
raise SystemExit(0 if ok else 1)
