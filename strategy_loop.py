#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""One pass over configured symbols and timeframes.

Paper mode records the decision and does not call order_send.
order_send runs in the default live mode after the FTMO gate has cleared.
Pass --paper or --dry-run to skip order_send.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

from feature_hash import align_feature_vector
from fxjefe_paths import TIMEFRAMES_DEFAULT, mql5_layout
from margin_precheck import guard_lot
from path_resolver import stage_main

log = logging.getLogger("fxjefe.strategy")


def sentiment_score(symbol: str, ctx: Dict[str, Any]) -> Tuple[float, str]:
    """Pluggable sentiment. Neutral when no scorer is available. Never raises into paper mode."""
    fn = ctx.get("sentiment_fn")
    if fn is None:
        return 0.0, "neutral"
    try:
        value = fn(symbol)
    except Exception as exc:
        log.info("sentiment unavailable for %s (%s); using neutral", symbol, exc.__class__.__name__)
        return 0.0, "neutral"
    if isinstance(value, tuple) and len(value) == 2:
        try:
            return float(value[0]), str(value[1])
        except (TypeError, ValueError):
            return 0.0, "neutral"
    try:
        return float(value), "scored"
    except (TypeError, ValueError):
        return 0.0, "neutral"


def _http_json(url: str, payload: Optional[Dict[str, Any]] = None, timeout: float = 3.0) -> Optional[Dict[str, Any]]:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except (urllib.error.URLError, ValueError, TimeoutError):
        return None
    try:
        body = json.loads(raw)
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def server_signal(ctx: Dict[str, Any], symbol: str, timeframe: str, features: Dict[str, float]) -> Optional[Dict[str, Any]]:
    rules = ctx.get("ftmo") or {}
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    base = str(rules.get("ai_server_url") or cfg.get("ai_server_url") or "").rstrip("/")
    path = str(rules.get("predict_path") or "/predict")
    if not path.startswith("/"):
        path = "/" + path
    if not base:
        return None
    health = _http_json(base + "/health")
    if not health or health.get("status") != "running":
        return None
    return _http_json(base + path, {"symbol": symbol, "timeframe": timeframe, "features": features})


def _predicted_change(remote: Optional[Dict[str, Any]], local: Optional[Dict[str, Any]]) -> Optional[float]:
    for source in (remote, local):
        if not isinstance(source, dict) or source.get("predicted_change") is None:
            continue
        try:
            return float(source["predicted_change"])
        except (TypeError, ValueError):
            continue
    return None


def _direction(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in ("buy", "sell"):
        return text
    return "hold"


def combine_signal(ctx: Dict[str, Any], symbol: str, timeframe: str) -> Dict[str, Any]:
    cfg = ctx.get("config") if isinstance(ctx.get("config"), dict) else {}
    rules = ctx.get("ftmo") or {}
    contract = [str(name) for name in (cfg.get("features") or [])]
    raw = ctx.get("feature_row") if isinstance(ctx.get("feature_row"), dict) else {}
    vector = align_feature_vector(raw, contract) if contract else []
    features = {name: vector[index] for index, name in enumerate(contract)} if contract else {}
    remote = server_signal(ctx, symbol, timeframe, features)
    local = ctx.get("local_prediction") if isinstance(ctx.get("local_prediction"), dict) else None
    score, sentiment_label = sentiment_score(symbol, ctx)
    min_confidence = float(cfg.get("min_confidence_threshold", rules.get("min_confidence", 0.77)))
    votes = []
    if remote:
        votes.append((_direction(remote.get("signal")), float(remote.get("confidence") or 0.0), "server"))
    if local:
        votes.append((_direction(local.get("signal")), float(local.get("confidence") or 0.0), "local"))
    directional = [item for item in votes if item[0] in ("buy", "sell") and item[1] >= min_confidence]
    sides = {item[0] for item in directional}
    if len(sides) == 1:
        side = next(iter(sides))
        confidence = min(item[1] for item in directional)
    else:
        side, confidence = "hold", 0.0
    change = _predicted_change(remote, local)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "signal": side,
        "confidence": confidence,
        "predicted_change": change,
        "sentiment": sentiment_label,
        "sentiment_score": score,
        "min_confidence": min_confidence,
        "features": features,
    }


def _reference_equity(ctx: Dict[str, Any]) -> float:
    account = ctx.get("account") or {}
    rules = ctx.get("ftmo") or {}
    for value in (account.get("equity"), account.get("balance"), rules.get("account_balance_ref")):
        if value is not None:
            try:
                number = float(value)
            except (TypeError, ValueError):
                continue
            if number > 0:
                return number
    return 0.0


def desired_lot(ctx: Dict[str, Any]) -> float:
    rules = ctx.get("ftmo") or {}
    max_lot = float(rules.get("max_position_size") or 0.0)
    risk = float(rules.get("risk_percent") or 0.0)
    if max_lot <= 0 or risk <= 0:
        return 0.0
    step = 0.01
    lot = max_lot * (risk / 100.0)
    lot = min(max_lot, round(int(lot / step) * step, 8))
    return lot


def _margin_inputs(ctx: Dict[str, Any], symbol: str, lot: float, price: float) -> Tuple[float, float, float, float]:
    """Return margin_per_lot, notional_per_lot, margin_used, free_margin."""
    account = ctx.get("account") or {}
    equity = _reference_equity(ctx)
    margin_used = float(account.get("margin") or 0.0)
    free = account.get("margin_free")
    if free is None:
        free = equity - margin_used
    mt5 = ctx.get("mt5") if ctx.get("mt5_connected") else None
    margin_per_lot = 0.0
    notional_per_lot = 0.0
    if mt5 is not None and lot > 0 and price > 0:
        try:
            info = mt5.symbol_info(symbol)
            contract = float(getattr(info, "trade_contract_size", 0.0) or 0.0) if info is not None else 0.0
            notional_per_lot = contract * price
            order_type = mt5.ORDER_TYPE_BUY
            calc = mt5.order_calc_margin(order_type, symbol, 1.0, price)
            if calc is not None and float(calc) > 0:
                margin_per_lot = float(calc)
        except Exception as exc:
            log.info("order_calc_margin unavailable for %s (%s)", symbol, exc.__class__.__name__)
    if margin_per_lot <= 0 and notional_per_lot <= 0 and equity > 0 and lot > 0:
        # No terminal quote: budget margin as a fraction of equity and let the guard shrink it.
        margin_per_lot = equity * (float((ctx.get("ftmo") or {}).get("risk_percent") or 0.0) / 100.0) / lot
    return margin_per_lot, notional_per_lot, margin_used, float(free)


def _price(ctx: Dict[str, Any], symbol: str, side: str) -> Optional[float]:
    mt5 = ctx.get("mt5") if ctx.get("mt5_connected") else None
    if mt5 is None:
        return None
    try:
        tick = mt5.symbol_info_tick(symbol)
    except Exception:
        return None
    if tick is None:
        return None
    return float(tick.ask if side == "buy" else tick.bid)


def send_live_order(mt5: Any, symbol: str, side: str, lot: float, price: float) -> Any:
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(lot),
        "type": mt5.ORDER_TYPE_BUY if side == "buy" else mt5.ORDER_TYPE_SELL,
        "price": float(price),
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    return mt5.order_send(request)


def _record(ctx: Dict[str, Any], row: Dict[str, Any]) -> None:
    log_dir = ctx["project_root"] / "Logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with (log_dir / "paper_orders.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")


def run(ctx: Dict[str, Any]) -> int:
    dry_run = bool(ctx.get("dry_run", False))
    rules = ctx.get("ftmo") or {}
    ctx["order_sent"] = False
    ctx["close_positions"] = bool(rules.get("close_positions_on_stop"))
    layout = mql5_layout(rules)
    log.info(
        "MQL5 root=%s Experts=%s Include=%s Files=%s",
        layout["root"],
        layout["Experts"],
        layout["Include"],
        layout["Files"],
    )
    if ctx.get("block_new_entries") or not ctx.get("ftmo_clear"):
        log.info(
            "execution: no new entries (ftmo_clear=%s block_new_entries=%s). Open positions are not closed.",
            ctx.get("ftmo_clear"),
            ctx.get("block_new_entries"),
        )
        return 0 if dry_run or ctx.get("block_new_entries") or not ctx.get("signal_emit") else 1
    symbols = [str(item) for item in (rules.get("symbols") or []) if str(item).strip()]
    timeframes = [str(item) for item in (rules.get("timeframes") or list(TIMEFRAMES_DEFAULT))]
    if not symbols:
        log.info("execution: no symbols configured; no orders")
        return 0
    if not ctx.get("signal_emit"):
        log.info("execution: signal gate did not emit; no orders")
        return 0
    equity = _reference_equity(ctx)
    min_level = float(rules.get("min_margin_level_percent") or 300.0)
    max_lot = float(rules.get("max_position_size") or 0.0)
    max_leverage = float(rules.get("max_leverage") or 0.0)
    for symbol in symbols:
        for timeframe in timeframes:
            decision = combine_signal(ctx, symbol, timeframe)
            log.info(
                "signal %s %s %s confidence=%s predicted_change=%s sentiment=%s",
                symbol,
                timeframe,
                decision["signal"],
                decision["confidence"],
                decision.get("predicted_change"),
                decision["sentiment"],
            )
            if decision["signal"] not in ("buy", "sell"):
                continue
            lot = desired_lot(ctx)
            price = _price(ctx, symbol, decision["signal"]) or 0.0
            margin_per_lot, notional_per_lot, margin_used, free_margin = _margin_inputs(ctx, symbol, lot, price)
            guarded = guard_lot(
                lot,
                equity,
                margin_used,
                free_margin,
                margin_per_lot,
                notional_per_lot,
                min_level,
                max_lot,
                max_leverage,
            )
            if guarded <= 0:
                log.info("margin guard skipped %s %s (level floor %s)", symbol, timeframe, min_level)
                continue
            if dry_run:
                _record(ctx, {
                    "paper": True,
                    "order_send": False,
                    "symbol": symbol,
                    "timeframe": timeframe,
                    "side": decision["signal"],
                    "lot": guarded,
                })
                log.info("paper intent %s %s %s lot=%s; order_send not called", symbol, timeframe, decision["signal"], guarded)
                continue
            mt5 = ctx.get("mt5")
            if mt5 is None or price <= 0:
                log.error("live order refused for %s; terminal price is unavailable", symbol)
                return 1
            result = send_live_order(mt5, symbol, decision["signal"], guarded, price)
            ctx["order_sent"] = True
            log.info("order_send %s %s lot=%s result=%s", symbol, decision["signal"], guarded, getattr(result, "retcode", result))
    return 0


def main(argv=None) -> int:
    return stage_main(run, argv)


if __name__ == "__main__":
    raise SystemExit(main())
