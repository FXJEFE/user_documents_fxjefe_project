# FXJEFE

Production ML + MetaTrader 5 trading runtime (mentor line).

**Policy:** UTF-8 only · all features permitted · no filtering / labeling / blocking of feature names · signals only when model is loaded and featureset matches EA + server + Predict.mq5 + GenerateFeatures.mq5.

Repo: https://github.com/FXJEFE/user_documents_fxjefe_project

---

## Project root (all OS)

```text
~/Documents/FXJEFE_Project
Windows: %USERPROFILE%\\Documents\\FXJEFE_Project
```

---

## Quick setup

### 1. Clone

```bash
mkdir -p ~/Documents
cd ~/Documents
git clone https://github.com/FXJEFE/user_documents_fxjefe_project.git FXJEFE_Project
cd FXJEFE_Project
```

### 2. Python

Windows uses two virtualenvs under `PROJECT_ROOT`. `fxjefe` is Python 3.11 (pipeline, golden server, MetaTrader5, optional onnxruntime). `fxjefe38` is Python 3.8.10 (TA-Lib wheel plus TensorFlow 2.10.1). `setup_windows.bat` installs either interpreter per-user when it is missing and pip-installs `requirements.txt` and `requirements-fxjefe38.txt`.

**Windows**

```bat
cd /d %USERPROFILE%\Documents\FXJEFE_Project
setup_windows.bat
run_pipeline.bat
```

`run_pipeline.bat` is **LIVE MODE**. It sends orders after `configftmo.json`, `MT5_ACCOUNT`, `MT5_PASSWORD`, and `MT5_SERVER` are present and the FTMO, margin, feature-hash, and MT5 gates pass. Add `--paper` (or `--dry-run`) for a run that does not send orders. `--live` is accepted and changes nothing.

Override the project directory (must already exist and contain this repo):

```bat
set FXJEFE_PROJECT_DIR=D:\FXJEFE_Project
setup_windows.bat
run_pipeline.bat
```

**macOS / Linux** (training and checks; MetaTrader5 itself is Windows-only)

```bash
python3.8 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip setuptools wheel
pip install -r requirements_linux.txt
python run_pipeline.py --paper --project-dir "$PWD"
```

On macOS use `requirements_mac.txt` instead of `requirements_linux.txt`.

### 3. Environment

```bash
cp .env.example .env
```

Edit `.env` with MT5 account values locally. Never commit `.env`.

### 4. Pipeline

`run_pipeline.py` resolves `PROJECT_ROOT` (`--project-dir`, then `FXJEFE_PROJECT_DIR`, then legacy `FXJEFE_PROJECT_ROOT`, then `Path.home() / "Documents" / "FXJEFE_Project"`), logs that path, and exits if the directory is missing. Stage order is `pipeline_manifest.json`:

1. `path_resolver.py`, `validate_config.py`, `ftmo_rules.py` — root, config, FTMO rules
2. `mt5_connection.py` — terminal health (required in live mode)
3. `data_stage.py`, `audit_config_paths.py`
4. `feature_hash.py`, `realized_vol_features.py`, `garch_async.py`, `garch_multistep.py`
5. `feature_importance_nan.py` — no fit while `skip_training_in_pipeline` is true
6. `runtime/signal_gate.py`, `trade_policy_config.py`
7. `ftmo_rules.py` `run_gate` — blocks the pipeline on a breach
8. `strategy_loop.py` — sends orders in live mode; `--paper` records the decision only
9. `mt5_latency_bench.py`, `verify_checksums.py`

Copy `configftmo.example.json` to `configftmo.json`. Live mode fails closed without that file. Credentials stay in `MT5_ACCOUNT`, `MT5_PASSWORD`, `MT5_SERVER`, and optional `MT5_PATH`.

Scripts named by older manifests (`mt5_data_sync.py`, `train_models.py`, `ai_server.py`, `pipelinerun_production.py`, `runtime_lock.py`, and the rest) are not in this checkout.

---

## Feature policy (ALL OK)

| Rule | Value |
|------|--------|
| `feature_policy` | `ACCEPT_ALL_FEATURES` |
| Filter / block / refuse feature names | **Never** |
| Strip feature arrays | **Never** |
| Preferred 17 / 28 lists | Defaults for wiring only |
| Signal emit | Model loaded **and** featureset hash matches EA + server + Predict.mq5 + GenerateFeatures.mq5 |

---

## Encoding

UTF-8 only for `.py`, `.csv`, `.mq5`, `.mqh`, `.json`, configs.

```bash
python runtime/encoding_utf8.py --fix --root .
python runtime/encoding_utf8.py --scan --root .
```

---

## MT5

Live terminals (Pepperstone / Vantage / FTMO) run on **Windows** (native or VM).  
Mac/Linux: training, feature engineering, AI server.  
EA: allow WebRequest for `http://127.0.0.1:8080` (and LAN IP if split hosts).

---

## Do not commit

- `.env` (secrets)
- `venv/`
- `__pycache__/`
- `*.pkl` model binaries unless intentional
- live broker passwords

See `.gitignore`.
