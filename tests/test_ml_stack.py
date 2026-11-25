#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ML stack, health ping, and replay analytics. No live MT5 terminal."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

os.environ.setdefault("FXJEFE_FEATURE_BACKEND", "numpy")

import health_server  # noqa: E402
import ml_contract  # noqa: E402
import ml_models  # noqa: E402
from health_client import query  # noqa: E402


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _project(root: Path, ftmo=True):
    cfg = json.loads((REPO / "config.json").read_text(encoding="utf-8"))
    cfg["api_port"] = _free_port()
    cfg["ai_server_url"] = "http://127.0.0.1:{0}".format(cfg["api_port"])
    cfg["zmq_health_port"] = _free_port()
    cfg["health_http_port"] = _free_port()
    (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "data" / "replay_sample.csv", data / "replay_sample.csv")
    if ftmo:
        shutil.copy(REPO / "configftmo.example.json", root / "configftmo.json")
    return cfg


class ContractTests(unittest.TestCase):
    def test_mql_sources_match_the_29_feature_hash(self):
        contract = json.loads((REPO / "config.json").read_text(encoding="utf-8"))["features"]
        self.assertEqual(len(contract), 29)
        ok, problems = ml_contract.sources_match_contract(REPO, contract)
        self.assertTrue(ok, problems)
        self.assertEqual(
            ml_contract.ordered_feature_hash(contract),
            "8188812e402fca6a55928bfbdb4a91b0f9a89d80ac182b44428c4d208672caa0",
        )

    def test_replay_frame_is_multi_symbol_and_width_29(self):
        cfg = json.loads((REPO / "config.json").read_text(encoding="utf-8"))
        symbols, timeframes = ml_contract.market_universe(cfg, None)
        frame = ml_contract.load_market_frame(REPO, cfg, symbols, timeframes, connected=False)
        features = ml_contract.build_feature_frame(frame, cfg["features"])
        self.assertGreaterEqual(set(features["symbol"]), {"EURUSD", "GBPUSD"})
        self.assertGreaterEqual(set(features["timeframe"]), {"M1", "H1"})
        self.assertEqual(list(features.columns[:29]), cfg["features"])
        row = features.iloc[-1]
        self.assertTrue(all(float(row[name]) == float(row[name]) for name in cfg["features"]))

    def test_keras_builder_is_absent_without_tensorflow(self):
        model = ml_models.build_keras_temporal("lstm", 8, 29)
        try:
            import tensorflow  # noqa: F401
        except Exception:
            self.assertIsNone(model)
            ltdm = ml_models.build_keras_temporal("ltdm", 16, 29)
            self.assertIsNone(ltdm)


class StackTests(unittest.TestCase):
    def test_fit_loads_every_model_and_leaves_models_dir_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _project(root, ftmo=False)
            (root / "models").mkdir()
            sentinel = root / "models" / "keep.pkl"
            sentinel.write_bytes(b"original-model")
            import ml_stack
            ctx = {
                "project_root": root,
                "dry_run": True,
                "code_root": REPO,
                "config": cfg,
                "mt5_connected": False,
            }
            self.assertEqual(ml_stack.run(ctx), 0)
            heartbeats = ctx["model_stack"].heartbeats()
            loaded = {row["name"]: row for row in heartbeats if row.get("loaded")}
            for name in ml_models.STACK_NAMES:
                self.assertIn(name, loaded, heartbeats)
                self.assertEqual(loaded[name]["feature_hash"], ctx["feature_hash"])
                self.assertTrue(loaded[name]["load_time"])
                self.assertEqual(loaded[name]["n_inputs"], 29)
            prediction = ctx["model_stack"].predict_window([[1.0] + [0.0] * 28], "EURUSD", "M1")
            self.assertIn(prediction.signal, ("buy", "sell", "hold"))
            self.assertIsInstance(prediction.predicted_change, float)
            self.assertTrue(ctx["model_stack"].ensemble.last_prediction_time)
            refused = ctx["model_stack"].predict_window([[0.0] * 28], "EURUSD", "M1")
            self.assertEqual(refused.signal, "hold")
            self.assertEqual(sentinel.read_bytes(), b"original-model")
            self.assertFalse(any((root / "models").glob("*.joblib")))
            self.assertTrue((root / "artifacts" / "ml_stack" / "manifest.json").is_file())

    def test_health_ping_lists_loaded_models_and_http_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _project(root, ftmo=False)
            import ml_stack
            ctx = {"project_root": root, "dry_run": True, "code_root": REPO, "config": cfg, "mt5_connected": False}
            self.assertEqual(ml_stack.run(ctx), 0)
            ctx["model_stack"].predict_window([[1.0] + [0.0] * 28], "EURUSD", "M1")
            from health_state import record_models
            record_models(root, cfg, ctx["model_stack"].heartbeats(), ctx["feature_hash"], 29)
            server = health_server.HealthServer(root, cfg, 0, 0, "127.0.0.1")
            thread = threading.Thread(target=server.serve, daemon=True)
            thread.start()
            for _ in range(50):
                if server.bound_zmq and server.bound_http:
                    break
                time.sleep(0.05)
            self.assertTrue(server.bound_zmq, "zmq socket did not bind")
            try:
                ping = query(server.bound_zmq, "PING", timeout_ms=2000)
                self.assertIsNotNone(ping)
                self.assertTrue(ping.get("pong"))
                names = [item["name"] for item in ping["models"] if item.get("loaded")]
                for name in ml_models.STACK_NAMES:
                    self.assertIn(name, names)
                self.assertTrue(any(item.get("last_prediction_time") for item in ping["models"]))
                with urllib.request.urlopen("http://127.0.0.1:{0}/status".format(server.bound_http), timeout=2) as response:
                    status = json.loads(response.read().decode("utf-8"))
                self.assertEqual(status.get("status"), "running")
                self.assertEqual(len(status.get("models") or []), len(ml_models.STACK_NAMES))
            finally:
                server.stop()
                thread.join(timeout=3)

    def test_analytics_writes_predicted_change_for_each_symbol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _project(root, ftmo=False)
            import market_analytics
            ctx = {"project_root": root, "dry_run": True, "code_root": REPO, "config": cfg, "mt5_connected": False}
            self.assertEqual(market_analytics.run_once(ctx), 0)
            text = (root / "Logs" / "analytics.csv").read_text(encoding="utf-8")
            self.assertIn("predicted_change", text)
            self.assertIn("EURUSD", text)
            self.assertIn("GBPUSD", text)
            self.assertIn("feature_drift_psi", text)
            rows = ctx["analytics_rows"]
            self.assertGreaterEqual(len(rows), 4)
            self.assertTrue(all("predicted_change" in row for row in rows))


class PipelineReplayTests(unittest.TestCase):
    def test_paper_pipeline_on_replay_pings_loaded_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = _project(root, ftmo=True)
            env = os.environ.copy()
            for key in list(env):
                if key.startswith("FXJEFE_") or key.startswith("MT5_"):
                    env.pop(key, None)
            env["PYTHONPATH"] = str(REPO)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["FXJEFE_FEATURE_BACKEND"] = "numpy"
            proc = subprocess.run(
                [sys.executable, str(REPO / "run_pipeline.py"), "--project-dir", str(root), "--paper"],
                cwd=str(REPO),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
            output = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, output[-4000:])
            self.assertIn("PAPER MODE", output)
            self.assertIn("models loaded 8/8", output)
            self.assertIn("health ping models_loaded=8/8", output)
            self.assertIn("analytics EURUSD", output)
            self.assertIn("order_sent=False", output)
            status = json.loads((root / "Logs" / "health_status.json").read_text(encoding="utf-8"))
            loaded = [item["name"] for item in status["models"] if item.get("loaded")]
            self.assertEqual(len(loaded), 8)
            self.assertTrue((root / "Logs" / "analytics.csv").is_file())
            self.assertIn(str(cfg["zmq_health_port"]), output)


if __name__ == "__main__":
    unittest.main()
