#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

echo "[FXJEFE-SETUP] root=$ROOT"

if [ ! -d fxjefe ]; then
  python3 -m venv fxjefe
  echo "[FXJEFE-SETUP] created venv fxjefe"
else
  echo "[FXJEFE-SETUP] using existing venv fxjefe"
fi

# shellcheck disable=SC1091
source fxjefe/bin/activate
python -m pip install -U pip setuptools wheel

if [ -f requirements_mac.txt ] && [ "$(uname -s)" = "Darwin" ]; then
  pip install -r requirements_mac.txt || pip install numpy pandas flask joblib
elif [ -f requirements_linux.txt ]; then
  pip install -r requirements_linux.txt || pip install numpy pandas flask joblib
fi

echo "[FXJEFE-SETUP] SHA256 verification (required)"
if [ ! -f verify_checksums.py ]; then
  echo "[FXJEFE-SETUP] FAIL: verify_checksums.py missing"
  exit 1
fi
if [ ! -f checksums.json ] && [ ! -f SHA256SUMS ]; then
  echo "[FXJEFE-SETUP] FAIL: checksums.json or SHA256SUMS missing"
  exit 1
fi
python verify_checksums.py
echo "[FXJEFE-SETUP] SHA256 ALL VALID"

if [ -f runtime_lock.py ]; then
  python runtime_lock.py || echo "[FXJEFE-SETUP] runtime_lock returned non-zero (continue)"
fi

if command -v docker >/dev/null 2>&1; then
  docker build -t fxjefe .
  echo "[FXJEFE-SETUP] docker image fxjefe built"
  echo "[FXJEFE-SETUP] run: docker run --rm -p 8080:8080 fxjefe"
else
  echo "[FXJEFE-SETUP] Docker not installed — host fxjefe venv ready"
fi

echo "[FXJEFE-SETUP] DONE"
