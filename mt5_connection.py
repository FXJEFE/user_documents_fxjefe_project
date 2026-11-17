#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MT5 terminal health check. Credentials come only from the environment."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, Tuple

from path_resolver import stage_main

log = logging.getLogger("fxjefe.mt5")


class CredentialError(RuntimeError):
    pass


def _import_mt5() -> Any:
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:  # ImportError on Linux, OSError if the DLL is missing
        log.info("MetaTrader5 import failed: %s", exc.__class__.__name__)
        return None
    return mt5


def _credentials() -> Tuple[str, Optional[int], str, str]:
    path = os.environ.get("MT5_PATH", "").strip()
    login_raw = os.environ.get("MT5_ACCOUNT", "").strip()
    password = os.environ.get("MT5_PASSWORD", "").strip()
    server = os.environ.get("MT5_SERVER", "").strip()
    if not login_raw and not password and not server:
        return path, None, "", ""
    if not (login_raw and password and server):
        raise CredentialError(
            "MT5_ACCOUNT, MT5_PASSWORD, and MT5_SERVER must all be set, or all left empty "
            "to attach to a terminal that is already logged in"
        )
    try:
        login = int(login_raw)
    except ValueError as exc:
        raise CredentialError("MT5_ACCOUNT must be an integer") from exc
    return path, login, password, server


def _snapshot_from_terminal(mt5: Any) -> Dict[str, Optional[float]]:
    info = mt5.account_info()
    if info is None:
        return {"balance": None, "equity": None, "margin_free": None}
    return {
        "balance": float(getattr(info, "balance", 0.0) or 0.0),
        "equity": float(getattr(info, "equity", 0.0) or 0.0),
        "margin_free": float(getattr(info, "margin_free", 0.0) or 0.0),
    }


def run(ctx: Dict[str, Any]) -> int:
    """Check that MetaTrader5 can be imported and, when present, initialized.

    Login, password, server, and terminal path are read from MT5_* environment
    variables. They are never hardcoded and the login is not written to the log.
    """
    dry_run = bool(ctx.get("dry_run", False))
    mt5 = ctx.get("mt5") if ctx.get("mt5") is not None else _import_mt5()
    if mt5 is None:
        ctx["mt5_connected"] = False
        if dry_run:
            log.info("MetaTrader5 is not installed; continuing in paper mode")
            return 0
        log.error("MetaTrader5 is not installed; live mode cannot check the terminal")
        return 1
    try:
        path, login, password, server = _credentials()
    except CredentialError as exc:
        log.error("%s", exc)
        ctx["mt5_connected"] = False
        return 1
    kwargs: Dict[str, Any] = {}
    if path:
        kwargs["path"] = path
    if login is not None:
        kwargs["login"] = login
        kwargs["password"] = password
        kwargs["server"] = server
        log.info("MT5 initialize using environment credentials (login not logged)")
    elif dry_run:
        log.info("MT5 initialize using the terminal session already logged in")
    else:
        log.error("LIVE MODE requires MT5_ACCOUNT, MT5_PASSWORD, and MT5_SERVER")
        ctx["mt5_connected"] = False
        return 1
    try:
        ok = bool(mt5.initialize(**kwargs))
    except Exception as exc:
        log.error("MT5 initialize raised %s", exc.__class__.__name__)
        ok = False
    if not ok:
        ctx["mt5_connected"] = False
        if dry_run:
            log.info("MT5 terminal is not available; continuing in paper mode")
            return 0
        log.error("MT5 initialize failed")
        return 1
    ctx["mt5"] = mt5
    ctx["mt5_connected"] = True
    ctx["account"] = _snapshot_from_terminal(mt5)
    account = ctx["account"]
    log.info(
        "MT5 connected balance=%s equity=%s margin_free=%s",
        account.get("balance"),
        account.get("equity"),
        account.get("margin_free"),
    )
    return 0


def main(argv=None) -> int:
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
