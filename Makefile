# FXJEFE Makefile — venv name ALWAYS fxjefe
# Never overwrites OG scripts; versioned pyc only under production/pyc-v*/

.PHONY: help venv install-mac install-linux install-win verify lock compile-pyc ci-check pipeline strap

ROOT := $(shell pwd)
VENV := fxjefe
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
ifeq ($(OS),Windows_NT)
  PYTHON := $(VENV)/Scripts/python.exe
  PIP := $(VENV)/Scripts/pip.exe
endif

help:
	@echo "FXJEFE targets:"
	@echo "  make venv          create fxjefe venv"
	@echo "  make install-mac   pip install requirements_mac.txt"
	@echo "  make install-linux pip install requirements_linux.txt"
	@echo "  make install-win   pip install requirements_win.txt"
	@echo "  make verify        path_resolver + feature hash + signal gate"
	@echo "  make lock          runtime_lock.py expect 200 (not shipped in this checkout)"
	@echo "  make pipeline      run_pipeline.py dry-run against this directory"
	@echo "  make compile-pyc   versioned pyc under production/pyc-v*/ (NEVER replace OG .py)"
	@echo "  make strap         secure_strap after first green FINAL"
	@echo "  make ci-check      non-destructive CI verification"

venv:
	@test -d $(VENV) || python3 -m venv $(VENV)
	@echo "venv ready: $(ROOT)/$(VENV)"

install-mac: venv
	$(PYTHON) -m pip install -U pip setuptools wheel
	$(PIP) install -r requirements_mac.txt

install-linux: venv
	$(PYTHON) -m pip install -U pip setuptools wheel
	$(PIP) install -r requirements_linux.txt

install-win: venv
	$(PYTHON) -m pip install -U pip setuptools wheel
	$(PIP) install -r requirements_win.txt

verify:
	$(PYTHON) path_resolver.py --project-dir $(ROOT)
	$(PYTHON) -m py_compile feature_hash.py runtime/signal_gate.py run_pipeline.py
	@echo "VERIFY OK"

lock:
	$(PYTHON) runtime_lock.py

pipeline:
	$(PYTHON) run_pipeline.py --project-dir $(ROOT)

compile-pyc:
	$(PYTHON) compile_versioned_pyc.py

strap:
	$(PYTHON) secure_strap.py

ci-check:
	$(PYTHON) -c "import run_pipeline; stages=run_pipeline.load_manifest(); assert stages[0]['script']=='path_resolver.py'; assert stages[-1]['script']=='verify_checksums.py'; print('stages', len(stages))"
	$(PYTHON) -m unittest discover -s tests -v
	@echo "CI-CHECK OK"
