#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Local margin/volume/stops pre-checks before order_check/order_send."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from path_resolver import stage_main

log = logging.getLogger("fxjefe.execution")

@dataclass
class PrecheckResult:
    ok: bool
    reason: str = ""
    volume: float = 0.0
    margin_est: float = 0.0
    free_margin: float = 0.0

def precheck_local(mt5: Any, symbol: str, side: str, volume: float,
                   sl: float = 0.0, price: Optional[float] = None,
                   max_margin_frac: float = 0.3) -> PrecheckResult:
    info = mt5.symbol_info(symbol)
    if info is None:
        return PrecheckResult(False, "no_symbol")
    if not mt5.symbol_select(symbol, True):
        return PrecheckResult(False, "symbol_select_failed")
    if int(getattr(info, "trade_mode", 4)) == 0:
        return PrecheckResult(False, "trade_disabled")
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return PrecheckResult(False, "no_tick")
    side = side.lower()
    if side not in ("buy", "sell"):
        return PrecheckResult(False, "bad_side")
    px = price if price is not None else (tick.ask if side == "buy" else tick.bid)
    step = float(info.volume_step or 0.01) or 0.01
    vmin = float(info.volume_min or step)
    vmax = float(info.volume_max or volume)
    vol = max(vmin, min(vmax, round(volume / step) * step))
    if vol < vmin:
        return PrecheckResult(False, "volume_below_min", volume=vol)
    point = float(info.point or 1e-5)
    stops = int(getattr(info, "trade_stops_level", 0) or 0)
    if sl and stops > 0 and abs(px - sl) < stops * point:
        return PrecheckResult(False, "stops_level", volume=vol)
    acc = mt5.account_info()
    if acc is None:
        return PrecheckResult(False, "no_account", volume=vol)
    free = float(getattr(acc, "margin_free", 0) or 0)
    leverage = float(getattr(acc, "leverage", 100) or 100)
    contract = float(getattr(info, "trade_contract_size", 100000) or 100000)
    margin_est = (contract * vol * px) / max(leverage, 1.0)
    try:
        order_type = mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL
        calc = mt5.order_calc_margin(order_type, symbol, vol, px)
        if calc is not None and calc > 0:
            margin_est = float(calc)
    except Exception:
        pass
    if free <= 0:
        return PrecheckResult(False, "no_free_margin", volume=vol, margin_est=margin_est, free_margin=free)
    if margin_est > free * max_margin_frac:
        return PrecheckResult(False, "margin_cap", volume=vol, margin_est=margin_est, free_margin=free)
    return PrecheckResult(True, "ok", volume=vol, margin_est=margin_est, free_margin=free)


def run(ctx: Dict[str, Any]) -> int:
    """Paper execution. This checkout never calls order_send."""
    dry_run = bool(ctx.get("dry_run", True))
    emit = bool(ctx.get("signal_emit"))
    clear = bool(ctx.get("ftmo_clear"))
    log.info("execution dry_run=%s signal_emit=%s ftmo_clear=%s", dry_run, emit, clear)
    ctx["order_sent"] = False
    if not emit or not clear:
        log.info("execution: no order (signal or FTMO gate did not clear an order)")
        return 0 if dry_run or not emit else 1
    if dry_run:
        log_dir = ctx["project_root"] / "Logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "paper": True,
            "order_send": False,
            "signal_emit": emit,
            "ftmo_clear": clear,
        }
        with (log_dir / "paper_orders.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        log.info("execution: paper intent recorded; order_send not called")
        return 0
    log.error("refusing live order_send; this checkout has no order execution script")
    return 1


def main(argv: Optional[list] = None) -> int:
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
