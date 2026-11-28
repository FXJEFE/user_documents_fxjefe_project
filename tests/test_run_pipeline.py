#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pipeline order, PROJECT_ROOT, and FTMO gate tests. Python 3.8."""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import ftmo_rules  # noqa: E402
import mt5_connection  # noqa: E402
import path_resolver  # noqa: E402
import run_pipeline  # noqa: E402

GROUP_ORDER = run_pipeline.GROUP_ORDER


def _clean_env(extra=None):
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("FXJEFE_") or key.startswith("MT5_"):
            env.pop(key, None)
    env["PYTHONPATH"] = str(REPO)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if extra:
        env.update(extra)
    return env


def _free_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _project(root, ftmo=None):
    cfg = json.loads((REPO / "config.json").read_text(encoding="utf-8"))
    port = _free_port()
    cfg["api_port"] = port
    cfg["ai_server_url"] = "http://127.0.0.1:{0}".format(port)
    (root / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    if ftmo is not None:
        (root / "configftmo.json").write_text(json.dumps(ftmo), encoding="utf-8")


def _run(root, extra_env=None, paper=True, extra_args=None):
    cmd = [sys.executable, str(REPO / "run_pipeline.py"), "--project-dir", str(root)]
    if paper:
        cmd.append("--paper")
    if extra_args:
        cmd.extend(extra_args)
    return subprocess.run(
        cmd,
        cwd=str(root),
        env=_clean_env(extra_env),
        capture_output=True,
        text=True,
    )


class ProjectRootTests(unittest.TestCase):
    def test_default_is_documents_fxjefe_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            expected = home / "Documents" / "FXJEFE_Project"
            expected.mkdir(parents=True)
            env = _clean_env()
            env["HOME"] = str(home)
            env["USERPROFILE"] = str(home)
            script = (
                "import os\n"
                "from pathlib import Path\n"
                "import path_resolver\n"
                "print(path_resolver.resolve_project_root())\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", script],
                cwd=str(REPO),
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(Path(proc.stdout.strip()), expected.resolve())

    def test_env_and_cli_precedence(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            chosen = base / "cli"
            from_dir = base / "dir"
            legacy = base / "legacy"
            for path in (chosen, from_dir, legacy):
                path.mkdir()
            old_dir = os.environ.get("FXJEFE_PROJECT_DIR")
            old_legacy = os.environ.get("FXJEFE_PROJECT_ROOT")
            os.environ["FXJEFE_PROJECT_DIR"] = str(from_dir)
            os.environ["FXJEFE_PROJECT_ROOT"] = str(legacy)
            try:
                self.assertEqual(path_resolver.resolve_project_root(str(chosen)), chosen.resolve())
                self.assertEqual(path_resolver.resolve_project_root(), from_dir.resolve())
                os.environ.pop("FXJEFE_PROJECT_DIR")
                self.assertEqual(path_resolver.resolve_project_root(), legacy.resolve())
            finally:
                if old_dir is None:
                    os.environ.pop("FXJEFE_PROJECT_DIR", None)
                else:
                    os.environ["FXJEFE_PROJECT_DIR"] = old_dir
                if old_legacy is None:
                    os.environ.pop("FXJEFE_PROJECT_ROOT", None)
                else:
                    os.environ["FXJEFE_PROJECT_ROOT"] = old_legacy

    def test_missing_root_message(self):
        missing = Path(tempfile.gettempdir()) / "fxjefe-missing-project-root-59ff"
        if missing.exists():
            shutil.rmtree(str(missing))
        proc = subprocess.run(
            [sys.executable, str(REPO / "run_pipeline.py"), "--project-dir", str(missing)],
            cwd=str(REPO),
            env=_clean_env(),
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not exist", proc.stderr)
        self.assertIn(str(missing), proc.stderr)

    def test_absolute_path_outside_root_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            root.mkdir()
            outside = Path(tmp) / "outside-models"
            outside.mkdir()
            (root / "config.json").write_text(
                json.dumps({"models_path": str(outside), "feature_policy": "ACCEPT_ALL_FEATURES"}),
                encoding="utf-8",
            )
            paths = path_resolver.resolve(root)
            self.assertEqual(paths["models_path"], str(root / "models"))
            self.assertTrue(str(paths["historical_csv"]).startswith(str(root)))


class FtmoTests(unittest.TestCase):
    def test_missing_config_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rules = ftmo_rules.find_ftmo_config(root, {})
            self.assertFalse(rules["found"])
            ctx = {"project_root": root, "config": {}, "dry_run": True}
            self.assertEqual(ftmo_rules.run(ctx), 1)

    def test_python_literal_is_not_executed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "pwned.txt"
            (root / "ftmo_config.py").write_text(
                "open(r'{0}', 'w').write('x')\n"
                "FTMO_CONFIG = {{'max_daily_loss_percent': 5, 'max_total_drawdown_percent': 10}}\n".format(marker),
                encoding="utf-8",
            )
            rules = ftmo_rules.find_ftmo_config(root, {})
            self.assertTrue(rules["found"])
            self.assertFalse(marker.exists())
            self.assertEqual(rules["max_daily_loss_percent"], 5.0)

    def test_credential_field_rejected_without_echoing_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "not-a-real-password"
            (root / "ftmo_config.json").write_text(
                json.dumps({
                    "max_daily_loss_percent": 5,
                    "max_total_drawdown_percent": 10,
                    "password": secret,
                }),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as caught:
                ftmo_rules.find_ftmo_config(root, {})
            self.assertNotIn(secret, str(caught.exception))

    def test_breach_blocks_before_clear(self):
        rules = {
            "found": True,
            "source": "test",
            "max_daily_loss_percent": 5.0,
            "max_total_drawdown_percent": 10.0,
        }
        ctx = {
            "project_root": Path("."),
            "dry_run": True,
            "ftmo": rules,
            "account": {
                "equity": 9000.0,
                "balance": 9000.0,
                "day_start_equity": 10000.0,
                "initial_balance": 10000.0,
            },
        }
        self.assertEqual(ftmo_rules.run_gate(ctx), 1)
        self.assertFalse(ctx["ftmo_clear"])


class Mt5ConnectionTests(unittest.TestCase):
    def test_env_credentials_are_not_stored_on_the_snapshot(self):
        class Info(object):
            balance = 10.0
            equity = 10.0
            margin_free = 4.0
            login = 999001

        class Fake(object):
            def __init__(self):
                self.kwargs = None

            def initialize(self, **kwargs):
                self.kwargs = kwargs
                return True

            def account_info(self):
                return Info()

        fake = Fake()
        old = {key: os.environ.get(key) for key in ("MT5_ACCOUNT", "MT5_PASSWORD", "MT5_SERVER", "MT5_PATH")}
        os.environ["MT5_ACCOUNT"] = "42"
        os.environ["MT5_PASSWORD"] = "secret-value"
        os.environ["MT5_SERVER"] = "Demo-Server"
        os.environ["MT5_PATH"] = ""
        try:
            ctx = {"dry_run": False, "mt5": fake}
            self.assertEqual(mt5_connection.run(ctx), 0)
        finally:
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
        self.assertEqual(fake.kwargs["login"], 42)
        self.assertEqual(fake.kwargs["password"], "secret-value")
        self.assertNotIn("login", ctx["account"])
        self.assertNotIn("password", ctx["account"])


class PipelineTests(unittest.TestCase):
    def test_manifest_order_and_imports(self):
        stages = run_pipeline.load_manifest(REPO)
        groups = [stage["group"] for stage in stages]
        last = -1
        for group in groups:
            index = GROUP_ORDER.index(group)
            self.assertGreaterEqual(index, last)
            last = index
        self.assertEqual(groups[0], "project_root_config_ftmo")
        self.assertEqual(stages[0]["script"], "path_resolver.py")
        self.assertIn("ftmo_risk_gate", groups)
        gate_at = groups.index("ftmo_risk_gate")
        exec_at = groups.index("execution")
        self.assertLess(gate_at, exec_at)
        for stage in stages:
            self.assertTrue((REPO / stage["script"]).is_file())
            run_pipeline.load_module(stage["script"], REPO)

    def test_dry_run_with_fixture_rules_sends_no_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root, {"max_daily_loss_percent": 5, "max_total_drawdown_percent": 10})
            proc = _run(root, {
                "FXJEFE_ACCOUNT_EQUITY": "10000",
                "FXJEFE_ACCOUNT_BALANCE": "10000",
                "FXJEFE_DAY_START_EQUITY": "10000",
                "FXJEFE_INITIAL_BALANCE": "10000",
            })
            output = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, output)
            self.assertIn("PROJECT_ROOT=", output)
            self.assertIn(str(root), output)
            self.assertIn("no order", output)
            self.assertIn("order_sent=False", output)
            self.assertIn("script=strategy_loop.py", output)
            self.assertFalse((root / "Logs" / "paper_orders.jsonl").exists())

    def test_missing_ftmo_config_stops_before_mt5(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root, ftmo=None)
            proc = _run(root)
            output = proc.stdout + proc.stderr
            self.assertNotEqual(proc.returncode, 0, output)
            self.assertIn("No FTMO config", output)
            self.assertNotIn("script=mt5_connection.py", output)

    def test_breach_stops_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root, {"MaxDailyLossPercent": 5, "max_drawdown_percent": 10})
            proc = _run(root, {
                "FXJEFE_ACCOUNT_EQUITY": "9000",
                "FXJEFE_DAY_START_EQUITY": "10000",
                "FXJEFE_INITIAL_BALANCE": "10000",
            })
            output = proc.stdout + proc.stderr
            self.assertNotEqual(proc.returncode, 0, output)
            self.assertIn("FTMO breach", output)
            self.assertNotIn("script=strategy_loop.py", output)

    def test_live_without_terminal_stops_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root, {"max_daily_loss_percent": 5, "max_total_drawdown_percent": 10})
            (root / "models").mkdir()
            (root / "models" / "placeholder.pkl").write_bytes(b"not-a-real-model")
            proc = _run(root, {
                "FXJEFE_ACCOUNT_EQUITY": "10000",
                "FXJEFE_DAY_START_EQUITY": "10000",
                "FXJEFE_INITIAL_BALANCE": "10000",
                "MT5_ACCOUNT": "1",
                "MT5_PASSWORD": "test-only",
                "MT5_SERVER": "Demo",
            }, paper=False)
            output = proc.stdout + proc.stderr
            self.assertNotEqual(proc.returncode, 0, output)
            self.assertIn("LIVE MODE", output)
            self.assertIn("MetaTrader5 is not installed", output)
            self.assertNotIn("script=strategy_loop.py", output)
            self.assertNotIn("test-only", output)

    def test_live_default_fails_closed_without_rules_or_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root, ftmo=None)
            missing_rules = _run(root, paper=False)
            text = missing_rules.stdout + missing_rules.stderr
            self.assertNotEqual(missing_rules.returncode, 0, text)
            self.assertIn("LIVE MODE", text)
            self.assertIn("configftmo.json", text)
            self.assertNotIn("script=mt5_connection.py", text)
            _project(root, {"max_drawdown_percent": 6.66})
            missing_creds = _run(root, paper=False, extra_args=["--live"])
            creds_text = missing_creds.stdout + missing_creds.stderr
            self.assertNotEqual(missing_creds.returncode, 0, creds_text)
            self.assertIn("MT5_ACCOUNT", creds_text)
            self.assertIn("LIVE MODE", creds_text)

    def test_dry_run_alias_stays_paper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root, {"max_drawdown_percent": 6.66, "account_balance_ref": 200000})
            proc = _run(root, {
                "FXJEFE_ACCOUNT_EQUITY": "200000",
                "FXJEFE_INITIAL_BALANCE": "200000",
            }, paper=False, extra_args=["--dry-run"])
            output = proc.stdout + proc.stderr
            self.assertEqual(proc.returncode, 0, output)
            self.assertIn("PAPER MODE", output)
            self.assertNotIn("LIVE MODE", output)

    def test_sources_do_not_hardcode_credentials(self):
        assigned = re.compile(r"(?i)(account|login|password)\s*=\s*['\"][^'\"]+['\"]")
        numbered = re.compile(r"(?i)(account|login)\s*=\s*\d{5,}")
        skip = {".git", "tests", ".venv", "venv", "fxjefe", "fxjefe38", "__pycache__"}
        for path in REPO.rglob("*.py"):
            if any(part in path.parts for part in skip):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertIsNone(assigned.search(text), path.name)
            self.assertIsNone(numbered.search(text), path.name)


class ContractTests(unittest.TestCase):
    def test_hash_demo_reverse_changes_only_ordered(self):
        import feature_hash
        forward = ["spread", "sentiment"]
        backward = list(reversed(forward))
        self.assertTrue(feature_hash.hashes_equal(forward, backward, mode="set"))
        self.assertFalse(feature_hash.hashes_equal(forward, backward, mode="ordered"))
        pair = feature_hash.feature_hash_pair(["b", "a", "b"])
        self.assertEqual(pair["count"], 3)
        self.assertEqual(pair["unique"], 2)
        self.assertEqual(len(pair["hash_set_short"]), 16)
        self.assertEqual(feature_hash.canonical_bytes(["a", "b"], mode="set"), b"a\nb")
        self.assertEqual(feature_hash.canonical_bytes(["b", "a"], mode="ordered"), b"b\na")

    def test_empty_roles_are_ignored(self):
        import feature_hash
        ok, info = feature_hash.all_roles_match(
            {"model": ["price", "atr"], "ea": ["atr", "price"], "server": [], "predict_mq5": ["price", "atr"]},
            mode="set",
        )
        self.assertTrue(ok)
        self.assertEqual(info["reference"], "model")
        self.assertNotIn("server", info["mismatches"])

    def test_align_missing_keys_are_zero_and_28_fails(self):
        import feature_hash
        contract = json.loads((REPO / "config.json").read_text(encoding="utf-8"))["features"]
        self.assertEqual(len(contract), 29)
        vector = feature_hash.align_feature_vector({"price": 1.5}, contract)
        self.assertEqual(len(vector), 29)
        self.assertEqual(vector[0], 1.5)
        self.assertEqual(vector[1], 0.0)
        message = feature_hash.require_model_width(28, 29)
        self.assertIsNotNone(message)
        self.assertIn("28", message)

    def test_signal_stage_fails_loudly_on_28_inputs(self):
        import run_pipeline
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root, {"max_drawdown_percent": 6.66})
            models = root / "models"
            models.mkdir()
            (models / "demo.signature.json").write_text(json.dumps({"n_inputs": 28}), encoding="utf-8")
            module = run_pipeline.load_module("runtime/signal_gate.py", REPO)
            ctx = {
                "project_root": root,
                "dry_run": True,
                "config": json.loads((root / "config.json").read_text(encoding="utf-8")),
                "paths": {"models_path": str(models)},
                "features": json.loads((REPO / "config.json").read_text(encoding="utf-8"))["features"],
            }
            self.assertEqual(module.run(ctx), 1)
            self.assertFalse(ctx["signal_emit"])

    def test_configftmo_is_primary_and_drawdown_alone_is_enough(self):
        import ftmo_rules
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "ftmo_config.json").write_text(json.dumps({"max_drawdown_percent": 1}), encoding="utf-8")
            (root / "configftmo.json").write_text(
                (REPO / "configftmo.example.json").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            rules = ftmo_rules.find_ftmo_config(root, {})
            self.assertTrue(str(rules["source"]).endswith("configftmo.json"))
            self.assertAlmostEqual(rules["max_drawdown_percent"], 6.66)
            self.assertAlmostEqual(rules["risk_percent"], 33.3)
            self.assertAlmostEqual(rules["profit_target_percent"], 11.1)
            self.assertFalse(rules["close_positions_on_stop"])
            self.assertEqual(rules["account"], "demo-200k")
            self.assertEqual(rules["account_balance_ref"], 200000)
            self.assertEqual(rules["python_executable"], "fxjefe")
            ctx = {"project_root": root, "config": {}, "dry_run": True}
            self.assertEqual(ftmo_rules.run(ctx), 0)

    def test_drawdown_and_profit_block_entries_without_closing(self):
        import ftmo_rules
        rules = {
            "found": True,
            "source": "test",
            "max_drawdown_percent": 6.66,
            "profit_target_percent": 11.1,
            "account_balance_ref": 200000,
            "close_positions_on_stop": False,
        }
        stopped = {
            "project_root": Path("."),
            "dry_run": True,
            "ftmo": rules,
            "account": {"equity": 186680.0, "balance": 186680.0},
        }
        self.assertEqual(ftmo_rules.run_gate(stopped), 1)
        self.assertTrue(stopped["block_new_entries"])
        self.assertFalse(stopped["close_positions"])
        target = {
            "project_root": Path("."),
            "dry_run": True,
            "ftmo": rules,
            "account": {"equity": 222200.0, "balance": 222200.0},
        }
        self.assertEqual(ftmo_rules.run_gate(target), 1)
        self.assertTrue(target["block_new_entries"])
        self.assertFalse(target["close_positions"])

    def test_paper_does_not_send_and_live_does_after_gate(self):
        import run_pipeline
        module = run_pipeline.load_module("strategy_loop.py", REPO)

        class Tick(object):
            bid = 1.1
            ask = 1.1002

        class Info(object):
            trade_contract_size = 100000.0

        class Result(object):
            retcode = 10009

        class Fake(object):
            ORDER_TYPE_BUY = 0
            ORDER_TYPE_SELL = 1
            TRADE_ACTION_DEAL = 1
            ORDER_TIME_GTC = 0
            ORDER_FILLING_IOC = 1

            def __init__(self):
                self.sent = 0
                self.closed = 0

            def order_send(self, request):
                self.sent += 1
                return Result()

            def order_calc_margin(self, order_type, symbol, volume, price):
                return 100.0 * volume

            def symbol_info(self, symbol):
                return Info()

            def symbol_info_tick(self, symbol):
                return Tick()

            def positions_get(self):
                self.closed += 1
                return []

        example = json.loads((REPO / "configftmo.example.json").read_text(encoding="utf-8"))
        example["symbols"] = ["EURUSD"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = {
                "project_root": root,
                "ftmo": example,
                "ftmo_clear": True,
                "signal_emit": True,
                "block_new_entries": False,
                "config": {"features": ["price", "atr"], "min_confidence_threshold": 0.77},
                "local_prediction": {"signal": "buy", "confidence": 0.9},
                "account": {"equity": 200000.0, "balance": 200000.0, "margin": 0.0, "margin_free": 200000.0},
            }
            fake = Fake()
            paper = dict(base)
            paper.update({"dry_run": True, "mt5": fake, "mt5_connected": True})
            self.assertEqual(module.run(paper), 0)
            self.assertEqual(fake.sent, 0)
            self.assertEqual(fake.closed, 0)
            self.assertFalse(paper["order_sent"])
            live = dict(base)
            live.update({"dry_run": False, "mt5": fake, "mt5_connected": True})
            self.assertEqual(module.run(live), 0)
            self.assertGreater(fake.sent, 0)
            self.assertEqual(fake.closed, 0)
            self.assertTrue(live["order_sent"])


if __name__ == "__main__":
    unittest.main()
