#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load an FTMO rules file and block orders when those rules are breached.

This module does not ship numeric limits. If no FTMO config is present, validation
fails closed. Python configs are parsed with ast.literal_eval and are never imported.
"""
from __future__ import annotations

import ast
import configparser
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from path_resolver import load_config, stage_main

log = logging.getLogger("fxjefe.ftmo")

FILE_CANDIDATES = (
    "configftmo.json",
    "ftmoconfig.json",
    "ftmo_config.json",
    "FTMOConfig.json",
    "ftmoconfig.ini",
    "ftmo_config.ini",
    "FTMOConfig.ini",
    "ftmoconfig.py",
    "ftmo_config.py",
    "FTMOConfig.py",
    os.path.join("config", "ftmoconfig.json"),
    os.path.join("config", "ftmo_config.json"),
    os.path.join("config", "FTMOConfig.json"),
)

EMBEDDED_KEYS = ("ftmo", "FTMO", "ftmo_config", "FTMOConfig", "ftmoconfig")
PY_NAMES = {"FTMO_CONFIG", "ftmo_config", "FTMOConfig", "ftmoconfig"}
SECRET_KEYS = {
    "password",
    "passwd",
    "secret",
    "token",
    "login",
    "accountlogin",
    "account_login",
    "mt5password",
    "mt5_password",
    "mt5account",
    "mt5_account",
    "accountnumber",
    "account_number",
}

ALIASES = {
    "maxdrawdownpercent": "max_drawdown_percent",
    "maxdrawdownpct": "max_drawdown_percent",
    "maxtotalddpercent": "max_drawdown_percent",
    "maxtotalddpct": "max_drawdown_percent",
    "maxtotaldrawdownpercent": "max_drawdown_percent",
    "maxlosspercent": "max_drawdown_percent",
    "maxdailylosspercent": "max_daily_loss_percent",
    "maxdailylosspct": "max_daily_loss_percent",
    "dailylosspercent": "max_daily_loss_percent",
    "dailylosspct": "max_daily_loss_percent",
    "maxdailyloss": "max_daily_loss_percent",
    "riskpercent": "risk_percent",
    "riskpct": "risk_percent",
    "maxtraderiskpct": "risk_percent",
    "maxriskpercent": "risk_percent",
    "profittargetpercent": "profit_target_percent",
    "profittargetpct": "profit_target_percent",
    "minmarginlevelpercent": "min_margin_level_percent",
    "minmarginlevelpct": "min_margin_level_percent",
    "maxpositionsize": "max_position_size",
    "maxlot": "max_position_size",
    "maxleverage": "max_leverage",
    "stoplossmultiplier": "stop_loss_multiplier",
    "accountbalanceref": "account_balance_ref",
    "minconfidence": "min_confidence",
}

STRING_KEYS = {
    "account": "account",
    "pythonexecutable": "python_executable",
    "mt5mql5dir": "mt5_mql5_dir",
    "aiserverurl": "ai_server_url",
    "predictpath": "predict_path",
}
BOOL_KEYS = {"closepositionsonstop": "close_positions_on_stop"}
LIST_KEYS = {"timeframes": "timeframes", "symbols": "symbols"}
LIMIT_KEYS = (
    "max_drawdown_percent",
    "max_daily_loss_percent",
    "risk_percent",
    "profit_target_percent",
    "min_margin_level_percent",
    "max_position_size",
    "max_leverage",
    "stop_loss_multiplier",
    "account_balance_ref",
    "min_confidence",
)
# max_drawdown_percent alone is enough. A daily-loss key is optional.
REQUIRED_ANY = ("max_drawdown_percent", "max_daily_loss_percent")
DEFAULT_MIN_MARGIN_LEVEL_PERCENT = 300.0


def _norm_key(key: str) -> str:
    compact = "".join(ch for ch in str(key).lower() if ch.isalnum())
    return ALIASES.get(compact, "")


def _flatten(value: Any) -> List[Tuple[str, Any]]:
    pairs: List[Tuple[str, Any]] = []
    if isinstance(value, dict):
        for key, item in value.items():
            pairs.append((str(key), item))
            pairs.extend(_flatten(item))
    elif isinstance(value, list):
        for item in value:
            pairs.extend(_flatten(item))
    return pairs


def _as_float(value: Any) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError("not a number")
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().rstrip("%").strip()
    return float(text)


def _reject_secrets(pairs: List[Tuple[str, Any]]) -> Optional[str]:
    for key, _value in pairs:
        compact = "".join(ch for ch in str(key).lower() if ch.isalnum())
        if compact in SECRET_KEYS or str(key).strip().lower() in SECRET_KEYS:
            return str(key)
    return None


def _rules_from_mapping(raw: Dict[str, Any], source: str) -> Dict[str, Any]:
    pairs = _flatten(raw)
    secret = _reject_secrets(pairs)
    if secret:
        raise ValueError(
            "FTMO config {0} contains credential field {1!r}. "
            "Remove it and pass MT5 credentials only through the environment.".format(source, secret)
        )
    rules: Dict[str, Any] = {"source": source}
    for key, value in pairs:
        compact = "".join(ch for ch in str(key).lower() if ch.isalnum())
        if compact in STRING_KEYS and STRING_KEYS[compact] not in rules and isinstance(value, str):
            rules[STRING_KEYS[compact]] = value.strip()
            continue
        if compact in BOOL_KEYS and BOOL_KEYS[compact] not in rules:
            if isinstance(value, bool):
                rules[BOOL_KEYS[compact]] = value
                continue
            if isinstance(value, str) and value.strip().lower() in ("true", "false"):
                rules[BOOL_KEYS[compact]] = value.strip().lower() == "true"
                continue
        if compact in LIST_KEYS and LIST_KEYS[compact] not in rules and isinstance(value, list):
            rules[LIST_KEYS[compact]] = [str(item).strip() for item in value if str(item).strip()]
            continue
        name = _norm_key(key)
        if not name or name in rules or isinstance(value, (dict, list)):
            continue
        try:
            number = _as_float(value)
        except (TypeError, ValueError):
            continue
        rules[name] = number
    if "min_margin_level_percent" not in rules:
        rules["min_margin_level_percent"] = DEFAULT_MIN_MARGIN_LEVEL_PERCENT
    return rules


def _load_json(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("FTMO JSON root must be an object: {0}".format(path))
    return _rules_from_mapping(data, str(path))


def _load_ini(path: Path) -> Dict[str, Any]:
    parser = configparser.ConfigParser()
    read = parser.read(str(path), encoding="utf-8")
    if not read:
        raise ValueError("cannot read FTMO ini: {0}".format(path))
    raw: Dict[str, Any] = {}
    for section in parser.sections():
        raw.update(dict(parser.items(section)))
    if parser.defaults():
        raw.update(dict(parser.defaults()))
    return _rules_from_mapping(raw, str(path))


def _load_py(path: Path) -> Dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = [target.id for target in node.targets if isinstance(target, ast.Name)]
        if not any(name in PY_NAMES for name in names):
            continue
        value = ast.literal_eval(node.value)
        if not isinstance(value, dict):
            raise ValueError("FTMO python assignment must be a dict literal: {0}".format(path))
        return _rules_from_mapping(value, str(path))
    raise ValueError(
        "FTMO python file {0} has no literal FTMO_CONFIG/ftmo_config/FTMOConfig dict. "
        "The file was not executed.".format(path)
    )


def _load_file(path: Path) -> Dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return _load_json(path)
    if suffix == ".ini":
        return _load_ini(path)
    if suffix == ".py":
        return _load_py(path)
    raise ValueError("unsupported FTMO config type: {0}".format(path))


def find_ftmo_config(root: Path, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return normalized rules or a dict with found=False. Never fills in limits."""
    searched = [str(root / name) for name in FILE_CANDIDATES]
    for name in FILE_CANDIDATES:
        path = root / name
        if path.is_file():
            rules = _load_file(path)
            rules["found"] = True
            rules["searched"] = searched
            return rules
    if cfg is None:
        try:
            cfg = load_config(root)
        except (OSError, ValueError, json.JSONDecodeError):
            cfg = {}
    for key in EMBEDDED_KEYS:
        embedded = cfg.get(key) if isinstance(cfg, dict) else None
        if isinstance(embedded, dict):
            rules = _rules_from_mapping(embedded, "config.json:{0}".format(key))
            rules["found"] = True
            rules["searched"] = searched
            return rules
    return {"found": False, "source": "", "searched": searched}


def _require_limits(rules: Dict[str, Any]) -> Optional[str]:
    if not rules.get("found"):
        searched = rules.get("searched") or []
        return (
            "No FTMO config found under PROJECT_ROOT. Looked for: {0}. "
            "Also checked config.json keys {1}. "
            "The primary filename is configftmo.json. "
            "Refusing to invent drawdown or risk limits.".format(
                ", ".join(searched), ", ".join(EMBEDDED_KEYS)
            )
        )
    if not any(key in rules for key in REQUIRED_ANY):
        return (
            "FTMO config {0} has no max_drawdown_percent (a daily-loss key is optional). "
            "Refusing to invent one.".format(rules.get("source"))
        )
    for key in ("max_drawdown_percent", "max_daily_loss_percent", "risk_percent", "profit_target_percent", "min_confidence"):
        if key not in rules:
            continue
        value = float(rules[key])
        if not (0.0 < value <= 100.0):
            return "FTMO limit {0}={1} is outside 0 < percent <= 100".format(key, value)
    if "min_margin_level_percent" in rules and float(rules["min_margin_level_percent"]) <= 0:
        return "min_margin_level_percent must be positive"
    for key in ("max_position_size", "max_leverage", "account_balance_ref", "stop_loss_multiplier"):
        if key in rules and float(rules[key]) <= 0:
            return "FTMO limit {0} must be positive".format(key)
    if "python_executable" in rules and "venv311" in str(rules["python_executable"]).replace("\\", "/").lower():
        return "python_executable must be the project fxjefe venv, not venv311"
    return None


def run(ctx: Dict[str, Any]) -> int:
    """Validate that an FTMO rules file exists and contains enforceable loss limits."""
    root = ctx["project_root"]
    cfg = ctx.get("config")
    try:
        rules = find_ftmo_config(root, cfg if isinstance(cfg, dict) else None)
        error = _require_limits(rules)
    except (OSError, ValueError, json.JSONDecodeError, configparser.Error, SyntaxError) as exc:
        log.error("FTMO config rejected: %s", exc)
        ctx["ftmo"] = {"found": False}
        ctx["ftmo_clear"] = False
        return 1
    ctx["ftmo"] = rules
    if error:
        log.error("%s", error)
        ctx["ftmo_clear"] = False
        return 1
    for key in LIMIT_KEYS + ("close_positions_on_stop", "account", "python_executable", "mt5_mql5_dir"):
        if key in rules:
            log.info("FTMO rule %s=%s source=%s", key, rules[key], rules.get("source"))
    return 0


def _env_float(name: str) -> Optional[float]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    return float(raw)


def account_snapshot(ctx: Dict[str, Any]) -> Dict[str, Optional[float]]:
    account = dict(ctx.get("account") or {})
    mapping = (
        ("balance", "FXJEFE_ACCOUNT_BALANCE"),
        ("equity", "FXJEFE_ACCOUNT_EQUITY"),
        ("day_start_equity", "FXJEFE_DAY_START_EQUITY"),
        ("initial_balance", "FXJEFE_INITIAL_BALANCE"),
        ("peak", "FXJEFE_EQUITY_PEAK"),
    )
    for field, env_name in mapping:
        if account.get(field) is None:
            account[field] = _env_float(env_name)
    if account.get("equity") is None:
        account["equity"] = account.get("balance")
    ctx["account"] = account
    return account


def _loss_percent(baseline: Optional[float], current: Optional[float]) -> Optional[float]:
    if baseline is None or current is None or baseline <= 0:
        return None
    if current >= baseline:
        return 0.0
    return (baseline - current) / baseline * 100.0


def run_gate(ctx: Dict[str, Any]) -> int:
    """Compare the account snapshot with the loaded FTMO limits. No orders are sent."""
    rules = ctx.get("ftmo") or {}
    if not rules.get("found"):
        loaded = run(ctx)
        if loaded != 0:
            return loaded
        rules = ctx.get("ftmo") or {}
    try:
        account = account_snapshot(ctx)
    except ValueError as exc:
        log.error("account snapshot is not numeric: %s", exc)
        ctx["ftmo_clear"] = False
        return 1
    equity = account.get("equity")
    ctx["close_positions"] = bool(rules.get("close_positions_on_stop"))
    ctx["block_new_entries"] = False
    reference = rules.get("account_balance_ref")
    if reference is None:
        reference = account.get("initial_balance")
    checks = []
    if "max_drawdown_percent" in rules:
        checks.append(("max_drawdown_percent", _loss_percent(reference, equity), "drawdown vs reference balance"))
        if account.get("peak") is not None:
            checks.append(("max_drawdown_percent", _loss_percent(account.get("peak"), equity), "drawdown vs peak"))
    if "max_daily_loss_percent" in rules:
        checks.append(("max_daily_loss_percent", _loss_percent(account.get("day_start_equity"), equity), "daily loss"))
    missing_observation = False
    for key, observed, label in checks:
        if key not in rules:
            continue
        limit = float(rules[key])
        if observed is None:
            missing_observation = True
            log.warning("FTMO %s limit is %s%% but the account snapshot has no baseline", label, limit)
            continue
        log.info("FTMO %s %.4f%% limit %.4f%%", label, observed, limit)
        if observed >= limit:
            ctx["block_new_entries"] = True
            ctx["ftmo_clear"] = False
            ctx["orders_allowed"] = False
            log.error(
                "FTMO breach: %s %.4f%% >= limit %.4f%%. New entries blocked. "
                "Open positions are not closed (close_positions_on_stop=%s).",
                label,
                observed,
                limit,
                ctx["close_positions"],
            )
            return 1
    if (
        equity is not None
        and reference is not None
        and float(reference) > 0
        and "profit_target_percent" in rules
    ):
        gain = (float(equity) - float(reference)) / float(reference) * 100.0
        log.info("FTMO profit vs reference %.4f%% target %.4f%%", gain, float(rules["profit_target_percent"]))
        if gain >= float(rules["profit_target_percent"]):
            ctx["block_new_entries"] = True
            ctx["ftmo_clear"] = False
            ctx["orders_allowed"] = False
            log.error(
                "FTMO stop: profit target %.4f%% reached (%.4f%%). New entries blocked. "
                "Open positions are not closed (close_positions_on_stop=%s).",
                float(rules["profit_target_percent"]),
                gain,
                ctx["close_positions"],
            )
            return 1
    if missing_observation:
        ctx["ftmo_clear"] = False
        ctx["orders_allowed"] = False
        if ctx.get("dry_run", True):
            log.info("FTMO gate could not be fully evaluated; paper mode will not send orders")
            return 0
        log.error("live mode requires an account snapshot to evaluate FTMO rules")
        return 1
    ctx["ftmo_clear"] = True
    ctx["orders_allowed"] = bool(ctx.get("signal_emit")) and not ctx.get("dry_run", True)
    log.info("FTMO gate clear; orders_allowed=%s", ctx["orders_allowed"])
    return 0


def main(argv: Optional[list] = None) -> int:
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
