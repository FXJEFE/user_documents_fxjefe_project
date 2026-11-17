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
    "maxdailylosspercent": "max_daily_loss_percent",
    "dailylosspercent": "max_daily_loss_percent",
    "maxdailyloss": "max_daily_loss_percent",
    "maxtotalddpercent": "max_total_drawdown_percent",
    "maxdrawdownpercent": "max_total_drawdown_percent",
    "maxtotaldrawdownpercent": "max_total_drawdown_percent",
    "maxlosspercent": "max_total_drawdown_percent",
    "maxtraderiskpct": "max_trade_risk_percent",
    "riskpercent": "max_trade_risk_percent",
    "maxriskpercent": "max_trade_risk_percent",
    "maxpositionsize": "max_position_size",
    "maxlot": "max_position_size",
    "stoplossmultiplier": "stop_loss_multiplier",
}

LOSS_KEYS = ("max_daily_loss_percent", "max_total_drawdown_percent")


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
        name = _norm_key(key)
        if not name or name in rules:
            continue
        if isinstance(value, (dict, list)):
            continue
        try:
            number = _as_float(value)
        except (TypeError, ValueError):
            continue
        rules[name] = number
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
            "No ftmoconfig/FTMOConfig/ftmo_config file exists in this repo or the "
            "accessible sibling repos (saturnsync, April25AmenAlignment, 420-25). "
            "Refusing to invent daily-loss or drawdown limits.".format(
                ", ".join(searched), ", ".join(EMBEDDED_KEYS)
            )
        )
    if not any(key in rules for key in LOSS_KEYS):
        return (
            "FTMO config {0} has no max daily-loss or max total-drawdown percent. "
            "Refusing to invent one.".format(rules.get("source"))
        )
    for key in LOSS_KEYS:
        if key not in rules:
            continue
        value = float(rules[key])
        if not (0.0 < value <= 100.0):
            return "FTMO limit {0}={1} is outside 0 < percent <= 100".format(key, value)
    for key in ("max_trade_risk_percent", "max_position_size", "stop_loss_multiplier"):
        if key in rules and float(rules[key]) < 0:
            return "FTMO limit {0} is negative".format(key)
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
    for key in LOSS_KEYS + ("max_trade_risk_percent", "max_position_size", "stop_loss_multiplier"):
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
    checks = (
        ("max_daily_loss_percent", _loss_percent(account.get("day_start_equity"), equity), "daily loss"),
        ("max_total_drawdown_percent", _loss_percent(account.get("initial_balance"), equity), "total drawdown"),
    )
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
            log.error("FTMO breach: %s %.4f%% >= limit %.4f%%. Orders blocked.", label, observed, limit)
            ctx["ftmo_clear"] = False
            ctx["orders_allowed"] = False
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
