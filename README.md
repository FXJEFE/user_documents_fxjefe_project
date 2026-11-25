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

## Health server, ML stack, and market analytics

Every model reads the same 29-name contract from `config.json` (`signal_require_featureset_match`). The ordered hash is `8188812e402fca6a55928bfbdb4a91b0f9a89d80ac182b44428c4d208672caa0`. `mql5/Include/predict.mqh`, `mql5/Experts/Predict.mq5`, and `mql5/Scripts/GenerateFeatures.mq5` carry that same name list. Copy those files into the terminal `Include`, `Experts`, and `Scripts` folders on the Windows machine when you want the live EA to pick them up. This repo does not write into the MetaQuotes directory.

There is no `LTDM` class in the previous checkout. Here LTDM is the long-horizon temporal model: the LSTM cell with `ltdm_lookback` (default 16) and a second layer. `lstm` uses `lstm_lookback` (default 8) and one layer. On `fxjefe38` (Python 3.8.10) those two can also be fit with TensorFlow 2.10.1 / Keras 2.10.0 (`--fit-keras`). On `fxjefe` (Python 3.11) the same JSON weights run as a numpy LSTM, because TensorFlow 2.10.1 is pinned to 3.8.10. TA-Lib 0.4.28 is the pinned wheel in `requirements-fxjefe38.txt`. When TA-Lib is missing, the numpy formulas fill the same 29 columns.

The voting ensemble is the common prediction: `signal`, `confidence`, `predicted_change`. Members are linear regression, an MLP, random forest, XGBoost, LSTM, LTDM, and a `GridSearchCV` logistic model. New files are written only under `artifacts/ml_stack`. Nothing under `models/` is opened or replaced. A paper auto-fit is marked provisional. `/predict` keeps `signal` at `hold` and puts the vote on `ensemble_signal` until you run `ml_stack.py --fit` or set `ensemble_is_traded_model` to true. Existing FTMO, margin, feature-hash, and 0.77 confidence rules are unchanged.

Symbols and timeframes come from `config.json`, then from `configftmo.json`. The replay file is `data/replay_sample.csv` (EURUSD and GBPUSD, M1/M5/M15/H1).

The health server is ZMQ REQ/REP on `tcp://127.0.0.1:5555` (config `zmq_health_port`). Commands are `PING`, `STATUS`, and `MODELS`. The same JSON is HTTP `GET http://127.0.0.1:8081/status` and the ping document is `GET http://127.0.0.1:8081/health`. Each model heartbeat has `name`, `version`, `feature_hash`, `load_time`, and `last_prediction_time`. `Predict.mq5` calls that ping on init and posts the feature window to `/predict`. Allow WebRequest for `http://127.0.0.1:8081` as well as port 8080. Compile the ZMQ branch by defining `FXJEFE_HAVE_ZMQ` after mql-zmq is installed.

`market_analytics.py` pulls bars with MetaTrader5 when the terminal is connected and otherwise reads the replay CSV. It records predicted change, feature PSI against the training window, prediction drift, and sign accuracy of predicted versus realized change. A separate historical CSV is scored when `historical_csv` exists and is a different file. Output is `Logs/analytics.csv`, `Logs/analytics.jsonl`, and the health document. The loop does not send orders.

### Windows commands

```bat
cd /d %USERPROFILE%\Documents\FXJEFE_Project
copy /Y configftmo.example.json configftmo.json

fxjefe\Scripts\python.exe health_server.py --project-dir %USERPROFILE%\Documents\FXJEFE_Project
```

Second window, after the server prints its bind line:

```bat
cd /d %USERPROFILE%\Documents\FXJEFE_Project
fxjefe\Scripts\python.exe market_analytics.py --project-dir %USERPROFILE%\Documents\FXJEFE_Project --paper
fxjefe\Scripts\python.exe health_client.py --project-dir %USERPROFILE%\Documents\FXJEFE_Project PING
fxjefe\Scripts\python.exe health_client.py --project-dir %USERPROFILE%\Documents\FXJEFE_Project STATUS
type Logs\health_status.json
type Logs\analytics.csv
```

One paper pass of the whole pipeline, including the model load and one analytics pass:

```bat
cd /d %USERPROFILE%\Documents\FXJEFE_Project
run_pipeline.bat --paper
```

Promote a fit so `/predict` can trade the ensemble, still subject to the existing FTMO gate:

```bat
fxjefe\Scripts\python.exe ml_stack.py --fit --project-dir %USERPROFILE%\Documents\FXJEFE_Project
fxjefe38\Scripts\python.exe ml_stack.py --fit-keras --project-dir %USERPROFILE%\Documents\FXJEFE_Project
```

`--fit-keras` needs the `fxjefe38` environment. It writes `artifacts/ml_stack/lstm_keras` and `ltdm_keras` only when those directories are absent.

### Docker image

The Linux image runs the paper pipeline on replay data and then stays up so the models-loaded ping can be checked. MetaTrader5 is a Windows package. This image does not attach to a terminal, send a live order, or install TensorFlow 2.10 / TA-Lib. Those stay on the Windows `fxjefe` and `fxjefe38` environments. Point a live terminal at the Windows host with `run_pipeline.bat`.

Credentials are not copied into the image. `.dockerignore` drops `.env`, key files, `configftmo.json`, `models/`, and `*.pkl`. Pass `MT5_ACCOUNT`, `MT5_PASSWORD`, `MT5_SERVER`, and `MT5_PATH` at runtime. The paper command does not need them. `docker_entry.py` refuses `--live` because this container cannot reach the terminal.

`stage_bundle.ps1` reads `C:\Users\FullSend\Documents\FXJEFE_Project` and copies `models\`, `data\*.csv`, and `configftmo.json` into a stage directory. It hashes the source before and after the copy and stops if a source file changes. It does not delete or edit the source. Files whose names or JSON keys look like credentials are skipped, and the secret value is not printed. The stage manifest is `manifest.sha256.json`.

```bat
cd /d %USERPROFILE%\Documents\FXJEFE_Project
powershell -NoProfile -ExecutionPolicy Bypass -File stage_bundle.ps1 -Source C:\Users\FullSend\Documents\FXJEFE_Project -Destination .\stage
```

Build and run on the Linux machine. The health check requests `http://127.0.0.1:8081/health` and requires at least one loaded model.

```bash
docker build -t fxjefe:latest .
docker compose up -d
docker inspect --format '{{.State.Health.Status}}' fxjefe
python health_client.py --project-dir . PING
```

Published ports are bound to `127.0.0.1` on the host. Open them further only with a firewall rule you choose.

Private registry and a VPS, after `docker login` to that registry:

```bash
docker tag fxjefe:latest registry.example.com/fxjefe/fxjefe:latest
docker push registry.example.com/fxjefe/fxjefe:latest
```

On the VPS:

```bash
docker login registry.example.com
docker pull registry.example.com/fxjefe/fxjefe:latest
docker tag registry.example.com/fxjefe/fxjefe:latest fxjefe:latest
export MT5_ACCOUNT= MT5_PASSWORD= MT5_SERVER=
docker compose up -d
```

Copy the `stage` directory to the VPS if you want the owner's models and CSV mounted read-only at `/stage`. The container copies them into its own tree and does not write back to the mount.

## Still checked on the Windows machine (LocalLarry)

MetaTrader5 live bars, the TA-Lib C library versus the numpy fallback, a real TensorFlow 2.10 fit, and merging `predict.mqh` into the terminal tree. Those pieces are not executed in CI.

## Do not commit

- `.env` (secrets)
- `venv/`
- `__pycache__/`
- `*.pkl` model binaries unless intentional
- live broker passwords

See `.gitignore`.
