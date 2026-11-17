#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pipeline order, PROJECT_ROOT, and FTMO gate tests. Python 3.8."""
from __future__ import annotations

import json
import os
import re
import shutil
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


def _project(root, ftmo=None):
    shutil.copy(str(REPO / "config.json"), str(root / "config.json"))
    if ftmo is not None:
        (root / "ftmo_config.json").write_text(json.dumps(ftmo), encoding="utf-8")


def _run(root, extra_env=None, live=False):
    cmd = [sys.executable, str(REPO / "run_pipeline.py"), "--project-dir", str(root)]
    if live:
        cmd.append("--live")
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
            self.assertIn("script=margin_precheck.py", output)
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
            self.assertNotIn("script=margin_precheck.py", output)

    def test_live_without_terminal_stops_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _project(root, {"max_daily_loss_percent": 5, "max_total_drawdown_percent": 10})
            proc = _run(root, {
                "FXJEFE_ACCOUNT_EQUITY": "10000",
                "FXJEFE_DAY_START_EQUITY": "10000",
                "FXJEFE_INITIAL_BALANCE": "10000",
            }, live=True)
            output = proc.stdout + proc.stderr
            self.assertNotEqual(proc.returncode, 0, output)
            self.assertNotIn("script=margin_precheck.py", output)

    def test_sources_do_not_hardcode_credentials(self):
        assigned = re.compile(r"(?i)(account|login|password)\s*=\s*['\"][^'\"]+['\"]")
        numbered = re.compile(r"(?i)(account|login)\s*=\s*\d{5,}")
        for path in REPO.rglob("*.py"):
            if any(part in path.parts for part in (".git", "tests")):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("order_send(", text, path.name)
            self.assertIsNone(assigned.search(text), path.name)
            self.assertIsNone(numbered.search(text), path.name)


if __name__ == "__main__":
    unittest.main()
