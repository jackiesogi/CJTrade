"""Run a hand-written BaseStrategy subclass through the one-shot backtest engine.

    ARENAX_PORT=8802 uv run python exp/bin/custom_backtest.py \
        --file exp/strategies/my_strat.py \
        --symbol 2317 --start 2021-01-01 --duration 1461 --interval 1m \
        --balance 1000000 --params 'lookback:1350,band:2.5,pos_pct:0.5'

Exists because the built-in strategies cap every lookback at 100 bars, which on
1m bars is 100 minutes -- so none of them can express a daily-horizon idea at
the resolution the experiment runs at. `cjtrade_oneshot_backtest` only accepts
its six built-ins; this takes a file instead, and is otherwise the same path:
the same ArenaX kbars, the same BacktestEngine, the same CostModel, the same
printed summary, and a pickle `insight` reads.

Output contract matches cjtrade_oneshot_backtest: the last lines are the pickle
path and `Structured report:  insight <sid>`.

Parameters reach the strategy as ctx.params. They are NOT validated against
PARAM_SCHEMA -- a hand-written strategy names its own knobs.
"""
from __future__ import annotations

import argparse
import importlib.util
import inspect
import logging
import sys
import uuid
from pathlib import Path
from typing import Any
from typing import Dict

logging.basicConfig(level=logging.INFO,
                    format="[%(asctime)s] %(levelname)-7s : %(message)s")
log = logging.getLogger("custom_backtest")

from cjtrade.pkgs.analytics.backtest.engine import BacktestEngine
from cjtrade.pkgs.analytics.evaluation.quantstats import BacktestReport
from cjtrade.pkgs.brokers.arenax.arenax_broker_api import ArenaXBrokerAPI_v2
from cjtrade.pkgs.models.cost import CostModel
from cjtrade.pkgs.models.product import Product
from cjtrade.pkgs.strategy.base_strategy import BaseStrategy
from cjtrade.pkgs import paths


def _coerce(raw: str) -> Any:
    low = raw.strip().lower()
    if low in ("true", "false"):
        return low == "true"
    if low in ("none", "null"):
        return None
    for cast in (int, float):
        try:
            return cast(raw)
        except ValueError:
            pass
    return raw


def parse_params(spec: str | None) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for piece in (spec or "").split(","):
        piece = piece.strip()
        if not piece:
            continue
        if ":" not in piece:
            raise SystemExit(f"--params entry {piece!r} is not key:value")
        key, _, val = piece.partition(":")
        out[key.strip()] = _coerce(val)
    return out


def load_strategy(path: Path, class_name: str | None) -> BaseStrategy:
    """Import `path` and instantiate its BaseStrategy subclass."""
    spec = importlib.util.spec_from_file_location(f"exp_strategy_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    if class_name:
        cls = getattr(module, class_name, None)
        if cls is None:
            raise SystemExit(f"{path} has no class {class_name!r}")
        candidates = [cls]
    else:
        candidates = [
            obj for _, obj in inspect.getmembers(module, inspect.isclass)
            if issubclass(obj, BaseStrategy) and obj is not BaseStrategy
            and obj.__module__ == spec.name
        ]
    if not candidates:
        raise SystemExit(
            f"{path} defines no BaseStrategy subclass. Subclass BaseStrategy and "
            f"implement on_bar(self, bar, ctx) -> list[Signal]."
        )
    if len(candidates) > 1:
        names = ", ".join(c.__name__ for c in candidates)
        raise SystemExit(f"{path} defines several strategies ({names}); pass --class")
    return candidates[0]()


def main() -> int:
    ap = argparse.ArgumentParser(description="One-shot backtest of a strategy file")
    ap.add_argument("--file", required=True, help="path to the .py holding the strategy")
    ap.add_argument("--class", dest="class_name", default=None,
                    help="class to instantiate (only needed if the file has several)")
    ap.add_argument("--symbol", required=True, help="ticker, or comma-separated tickers")
    ap.add_argument("--start", required=True, help="YYYY-MM-DD")
    ap.add_argument("--duration", type=int, required=True, help="calendar days")
    ap.add_argument("--interval", default="1m", choices=["1m", "5m", "1h", "1d"])
    ap.add_argument("--balance", type=float, default=1_000_000.0)
    ap.add_argument("--params", default=None, help="'key:val,key:val' -> ctx.params")
    args = ap.parse_args()

    from datetime import datetime, timedelta

    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"no such strategy file: {path}")
    strategy = load_strategy(path, args.class_name)
    params = parse_params(args.params)

    symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
    start_dt = datetime.strptime(args.start, "%Y-%m-%d").date()
    end_dt = start_dt + timedelta(days=args.duration)
    start_s, end_s = start_dt.isoformat(), end_dt.isoformat()
    log.info(f"[Custom] Time Range: {start_s} to {end_s} ({args.duration} days)")

    api = ArenaXBrokerAPI_v2()
    kbars = []
    for sym in symbols:
        got = api.get_kbars(Product(symbol=sym), start_s, end_s, args.interval)
        if not got:
            log.warning(f"[Custom] No kbars for {sym} [{start_s} - {end_s}], skipping.")
            continue
        kbars.extend(got)
    if not kbars:
        raise RuntimeError(
            f"No kbars found for {','.join(symbols)} in range {start_s} - {end_s}"
        )
    kbars.sort(key=lambda k: k.timestamp)

    session_id = str(uuid.uuid4())
    cost_model = CostModel()
    engine = BacktestEngine(
        kbars=kbars, symbol=None, initial_balance=args.balance,
        params=params, session_id=session_id, cost_model=cost_model,
    )
    result = engine.run(strategy)

    strat_name = getattr(strategy, "name", type(strategy).__name__)
    result.provenance = {
        "path": "custom-oneshot",
        "produced_by": "exp/bin/custom_backtest.py",
        "strategy": strat_name,
        "strategy_long_name": type(strategy).__name__,
        "strategy_file": str(path),
        "symbols": symbols,
        "interval": args.interval,
        "requested_start": start_s,
        "requested_end": end_s,
        "duration_days": args.duration,
        "start_was_explicit": True,
        "bars": len(kbars),
        "initial_balance": args.balance,
        "params": params,
        "params_hash": None,
        "cost_model": {
            "commission_rate": cost_model.commission_rate,
            "commission_discount": cost_model.commission_discount,
            "min_commission": cost_model.min_commission,
            "stock_tax_rate": cost_model.stock_tax_rate,
            "etf_tax_rate": cost_model.etf_tax_rate,
            "slippage_model": cost_model.slippage_model,
            "slippage_pct": cost_model.slippage_pct,
        },
        "execution_model": (
            "A signal fills in the bar that produced it, at the signal's own "
            "price, with no limit check and no latency. Rejected only for "
            "insufficient cash or shares. No risk gate, no per-bot capital "
            "allocation, no order-rate cap and no drawdown halt."
        ),
        "comparable_to_engine": False,
    }

    report = BacktestReport(result)
    report.summary()

    stem = paths.reports_dir() / f"oneshot_{'_'.join(symbols)}_{session_id[:8]}"
    pkl_path = f"{stem}.pkl"
    try:
        result.save(pkl_path)
        log.info(f"[Custom] result saved → {pkl_path}")
    except Exception as exc:
        log.warning(f"[Custom] could not save the result: {exc}")
        pkl_path = None

    print()
    if pkl_path:
        print(f"  result  {pkl_path}")
        print(f"\n  Structured report:  insight {session_id[:8]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
