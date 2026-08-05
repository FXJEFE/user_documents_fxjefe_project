# FXJEFE

Production trading / ML runtime (mentor line).

## Policy
- **UTF-8 ONLY** for Python, CSV, MQL5, JSON, configs
- **ACCEPT_ALL_FEATURES** — preferred lists are defaults; nothing refused
- **Signal gate** — emit only when model loaded and featureset matches EA + server + Predict.mq5 + GenerateFeatures.mq5
- **Feature hashing** — scalable set/ordered SHA-256 identity
- **DO NOT REPLACE CURRENT SCRIPTS** on inventory by default

## Quick start
```bash
cd ~/Documents/FXJEFE_Project
python3 runtime_lock.py          # expect status 200
python3 encoding_utf8.py --fix  # UTF-8 normalize
python3 feature_hash.py
python3 signal_gate.py
```

## Demo
Demo is a **comment/label only** — does not disable systems.
