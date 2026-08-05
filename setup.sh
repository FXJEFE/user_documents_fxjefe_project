#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
if [ ! -d fxjefe ]; then
  python3 -m venv fxjefe
fi
source fxjefe/bin/activate
pip install -U pip setuptools wheel
if [ -f requirements_mac.txt ] && [ "$(uname)" = Darwin ]; then
  pip install -r requirements_mac.txt || true
elif [ -f requirements_linux.txt ]; then
  pip install -r requirements_linux.txt || true
fi
python verify_checksums.py || true
python runtime_lock.py || true
if command -v docker >/dev/null 2>&1; then
  docker build -t fxjefe .
  echo "RUN: docker run --rm -p 8080:8080 fxjefe"
else
  echo "Docker not installed — host venv fxjefe is ready"
fi
