"""
apps/insight.py
~~~~~~~~~~~~~~~~
Turn a finished run into something an expert can diagnose in one read.

    insight                      the most recent run
    insight 51702f96             by session id, or any unique prefix
    insight path/to/engine_x.pkl an explicit result file
    insight --list               what runs are on this machine

Reads either kind of run: the oneshot backtester's `oneshot_*.pkl` and the
trading engine's `engine_*.pkl`. They are NOT comparable with each other --
oneshot fills a signal in the bar that produced it while the engine waits for
a close to cross a limit price -- so the report leads with which path produced
the numbers, taken from the result's `provenance`.

Writes two files next to the run's own artefacts and prints both paths: a
markdown report to read, and a JSON document to parse.

WHY IT JOINS TWO SOURCES
------------------------
The pickle a run leaves behind says what the strategy *did*. It does not say
what the market *was doing*, and it cannot be made to: a BacktestResult holds
an equity curve, a fill history and nothing else. On a real 6-month run that
is 481 priced minutes out of 34,845 -- 1.4% -- and they are the minutes the
strategy chose to act in, which is the least neutral sample of a market there
is. Worse, that run's fills stopped five months before its equity curve did, so
for most of it the pickle holds no price information at all. Reconstructing the
price from the equity curve only works while a position is open, and a
mean-reversion strategy is flat most of the time.

So the questions worth asking -- did this stock suit the strategy only in a
particular stretch, is this parameter too sensitive for this market -- cannot
be answered from the pickle alone. They can be answered by reading the 1-minute
OHLCV this machine already has on disk (pkgs/paths.price_db_path) for the same
window and the same symbols, and putting the two side by side.

Coverage is reported rather than assumed. The database holds what has been
fetched, which is not always the whole window: of four symbols checked over one
run's window, three had all 131 trading days and one had 75.

WHAT IT STILL CANNOT SEE
------------------------
Said out loud in the report rather than left as a silence. The engine knows
several things that never reach the pickle: how many signals the risk gate
refused and why, how many a bot suppressed because an order was already in
flight, the per-bar `last_decision` a strategy reported, and the strategy's own
parameters. A reader who does not know those are missing will attribute a quiet
run to the strategy when the engine may have been the one refusing.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import statistics
import sys
from collections import Counter
from collections import defaultdict
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.pkgs import paths
from cjtrade.pkgs.models.backtest import BacktestResult

# Taipei is UTC+8 with no DST, and every datetime in this codebase is a naive
# Taipei value. The price database stores true epoch seconds, so this is the
# one conversion between them.
TAIPEI_OFFSET = timedelta(hours=8)
EPOCH = datetime(1970, 1, 1)

# The fee schedule the backtest backend applies, so a fill can be tested
# against it. A 0.1425% commission with a NT$20 minimum means an order under
# NT$14,035 pays more than the rate -- which is a sizing defect, not a
# strategy result, and it is invisible in a P&L total.
COMMISSION_RATE = 0.001425
COMMISSION_FLOOR = 20.0

# Thresholds the findings section flags on. Deliberately explicit and few: a
# report that flags everything flags nothing.
FEE_FLOOR_SHARE_FLAG = 0.25      # this share of fills paying the minimum
COST_VS_GROSS_FLAG = 0.50        # costs this much of gross P&L
CONCENTRATION_FLAG = 0.80        # top 3 days this much of total P&L
IDLE_TAIL_FLAG = 0.20            # last fifth of the window with no fills


# ═══════════════════════════════════════════════════════════════════════════
#  Finding — one flagged observation, with the number behind it
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Finding:
    """Something worth an expert's attention, and the evidence for it.

    `what` names the observation, `evidence` is the number that triggered it,
    and `why` says what it usually means. The three are kept apart so a reader
    can disagree with the interpretation while still trusting the number.
    """
    severity: str                # high | medium | low
    what: str
    evidence: str
    why: str

    def to_dict(self) -> dict:
        return asdict(self)


# ═══════════════════════════════════════════════════════════════════════════
#  Market side — the 1m OHLCV this machine already has
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SessionStats:
    """What one symbol's market did in one trading day."""
    date: str
    bars: int
    open: float
    high: float
    low: float
    close: float
    change_pct: float            # close vs open
    range_pct: float             # (high - low) / open
    vol_bp: float                # stdev of 1m returns, in basis points
    efficiency: float            # 0-100: net move over path travelled
    trendiness: float            # the same, over a random walk's expectation
    regime: str                  # trending | ranging | neutral

    def to_dict(self) -> dict:
        return asdict(self)


def _to_epoch(stamp: datetime) -> int:
    """Naive Taipei datetime -> true epoch seconds.

    Arithmetic against a fixed epoch rather than `datetime.timestamp()`,
    which reads a naive value as the *machine's* local time and would make
    this report depend on where it is run.
    """
    return int((stamp - TAIPEI_OFFSET - EPOCH).total_seconds())


def _epoch_to_taipei(ts: int) -> datetime:
    """True epoch seconds -> naive Taipei datetime. Inverse of _to_epoch."""
    return EPOCH + timedelta(seconds=int(ts)) + TAIPEI_OFFSET


def _open_price_db(path: Path) -> Optional[sqlite3.Connection]:
    """Read-only, and tolerant of the WAL a running broker leaves behind.

    A plain read-only open fails outright when a stale -wal exists and the
    directory is not writable, which is the normal state while a broker is up.
    `immutable=1` ignores the WAL instead: a post-hoc report can afford to miss
    whatever has not been checkpointed, and refusing to open at all would be
    worse.
    """
    if not path.exists():
        return None
    for uri in (f"file:{path}?mode=ro", f"file:{path}?mode=ro&immutable=1"):
        try:
            con = sqlite3.connect(uri, uri=True)
            con.execute("select 1 from arenax_prices limit 1")
            return con
        except sqlite3.Error:
            continue
    return None


def efficiency_ratio(closes: List[float]) -> float:
    """Net displacement over total path travelled, 0-100.

    Scale-free, so the same number means the same thing on a 50 ETF and a 1,000
    semiconductor, and on a session as on a month. A random walk of n steps
    sits near 100/sqrt(n); a clean one-way move approaches 100. The same
    measure pkgs/strategy/adx.py switches regime on, so a report and a strategy
    describe the market the same way.
    """
    if len(closes) < 2:
        return 0.0
    path = sum(abs(closes[i] - closes[i - 1]) for i in range(1, len(closes)))
    if path <= 0:
        return 0.0
    return min(100.0, abs(closes[-1] - closes[0]) / path * 100.0)


def trendiness(closes: List[float]) -> float:
    """Session efficiency against what a random walk of the same length would
    have managed. 1.0 means the day travelled exactly as far as chance.

    The raw ratio cannot be compared across different numbers of bars: a
    random walk of n steps scores about 100/sqrt(n), so a 266-bar session sits
    near 6 and a 20-bar window near 23 with neither being more directional
    than the other. Dividing by that baseline removes the length, which is
    what makes one threshold work on a session the way adx.py's works on its
    rolling window.
    """
    if len(closes) < 3:
        return 0.0
    baseline = 100.0 / math.sqrt(len(closes) - 1)
    return efficiency_ratio(closes) / baseline if baseline else 0.0


# Measured over 3,987 real sessions across the eight most-covered symbols in
# this machine's price history: these cut the days 55% ranging, 27% neutral,
# 17% trending. The raw 40/20 thresholds adx.py uses are deliberately NOT
# reused here -- at session length they put 98.3% of days in one bucket and
# left `trending` unreachable, which makes a regime table that cannot inform.
TRENDING_ABOVE = 1.5
RANGING_BELOW = 0.75


def _regime_of(trend: float) -> str:
    if trend > TRENDING_ABOVE:
        return "trending"
    if trend < RANGING_BELOW:
        return "ranging"
    return "neutral"


def load_sessions(con: sqlite3.Connection, symbol: str,
                  first: datetime, last: datetime) -> List[SessionStats]:
    """Per-trading-day statistics for `symbol` over the window."""
    rows = con.execute(
        "select ts, open, high, low, close from arenax_prices "
        "where symbol = ? and timeframe = '1m' and ts between ? and ? "
        "order by ts",
        (symbol, _to_epoch(first), _to_epoch(last))).fetchall()

    by_day: Dict[str, list] = defaultdict(list)
    for ts, o, h, low, c in rows:
        if c is None:
            continue
        by_day[_epoch_to_taipei(ts).strftime("%Y-%m-%d")].append(
            (o, h, low, c))

    out: List[SessionStats] = []
    for date in sorted(by_day):
        bars = by_day[date]
        closes = [b[3] for b in bars]
        opens = [b[0] for b in bars if b[0] is not None] or closes
        highs = [b[1] for b in bars if b[1] is not None] or closes
        lows = [b[2] for b in bars if b[2] is not None] or closes
        first_open, last_close = opens[0], closes[-1]
        rets = [(closes[i] - closes[i - 1]) / closes[i - 1]
                for i in range(1, len(closes)) if closes[i - 1]]
        out.append(SessionStats(
            date=date, bars=len(bars), open=round(first_open, 2),
            high=round(max(highs), 2), low=round(min(lows), 2),
            close=round(last_close, 2),
            change_pct=round((last_close - first_open) / first_open * 100, 3)
            if first_open else 0.0,
            range_pct=round((max(highs) - min(lows)) / first_open * 100, 3)
            if first_open else 0.0,
            vol_bp=round(statistics.pstdev(rets) * 10_000, 1)
            if len(rets) > 1 else 0.0,
            efficiency=round(efficiency_ratio(closes), 1),
            trendiness=round(trendiness(closes), 2),
            regime=_regime_of(trendiness(closes)),
        ))
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  Strategy side — what the pickle holds
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class Activity:
    """What the strategy did, counted."""
    fills: int = 0
    buys: int = 0
    sells: int = 0
    symbols: List[str] = field(default_factory=list)
    traded_value: float = 0.0
    commission: float = 0.0
    tax: float = 0.0
    slippage: float = 0.0
    fee_floor_fills: int = 0     # fills that paid the NT$20 minimum
    median_order_value: float = 0.0
    first_fill: Optional[str] = None
    last_fill: Optional[str] = None

    @property
    def costs(self) -> float:
        return self.commission + self.tax + self.slippage

    def to_dict(self) -> dict:
        out = asdict(self)
        out["costs"] = round(self.costs, 2)
        return out


def summarise_activity(fills: List[dict]) -> Activity:
    act = Activity()
    if not fills:
        return act
    values = []
    for f in fills:
        qty = abs(int(f.get("quantity") or 0))
        price = float(f.get("price") or 0.0)
        value = qty * price
        values.append(value)
        act.fills += 1
        if str(f.get("action", "")).upper() == "BUY":
            act.buys += 1
        else:
            act.sells += 1
        act.traded_value += value
        commission = float(f.get("commission") or 0.0)
        act.commission += commission
        act.tax += float(f.get("tax") or 0.0)
        act.slippage += float(f.get("slippage_cost") or 0.0)
        # Did this order pay the minimum rather than the rate? Compared with a
        # tolerance because the backend rounds to cents.
        if commission and abs(commission - COMMISSION_FLOOR) < 0.01 \
                and value * COMMISSION_RATE < COMMISSION_FLOOR:
            act.fee_floor_fills += 1
    act.symbols = sorted({str(f.get("symbol")) for f in fills})
    act.median_order_value = round(statistics.median(values), 2)
    stamps = sorted(str(f.get("time")) for f in fills if f.get("time"))
    act.first_fill, act.last_fill = (stamps[0], stamps[-1]) if stamps else (None, None)
    act.traded_value = round(act.traded_value, 2)
    act.commission = round(act.commission, 2)
    act.tax = round(act.tax, 2)
    act.slippage = round(act.slippage, 2)
    return act


def performance(result: BacktestResult) -> Dict[str, Any]:
    """The risk-adjusted metrics, from the same quantstats the tearsheet uses.

    Here rather than left to the HTML because an experimenter comparing runs
    should not have to open a browser or import the library to read a Sharpe.
    `BacktestReport.metrics()` already computed three of these; the rest come
    off quantstats directly.

    TWO LAYERS, ON PURPOSE
    ----------------------
    The top level holds a short, explicitly named core. `tearsheet` holds
    EVERY row quantstats puts in its HTML report, mirrored by calling
    `qs.reports.metrics(mode="full")` rather than by naming metrics here, so
    the two can never drift and a quantstats upgrade that adds a metric is
    picked up without a change to this file.

    Both exist because they answer different questions. The core keys are ours
    and will not move, which is what a script sweeping parameters needs.
    `tearsheet` keys are derived from quantstats' display labels, so they can
    change when quantstats does -- and its values carry display precision
    (Sharpe -9.59, not -9.589301), because matching the HTML is the point of
    it. Read the core when you are comparing runs; read `tearsheet` when you
    are checking this against the tearsheet.

    An earlier version of this curated the list and left out `exposure` --
    quantstats labels it "Time in Market" in the HTML -- on the grounds that
    the name reads like capital at risk when it counts periods with a non-zero
    return. That was the wrong call twice over: it is the metric an
    experimenter looks for first, and it is the one that explains why the
    Sharpe below moves with position size. It is in the core now.
    """
    out: Dict[str, Any] = {"available": False}
    try:
        import quantstats as qs
    except ImportError:
        out["reason"] = "quantstats is not installed"
        return out

    try:
        returns = result.to_returns()
    except Exception as exc:
        out["reason"] = f"no return series ({type(exc).__name__})"
        return out
    if returns is None or len(returns) < 2:
        out["reason"] = (f"only {0 if returns is None else len(returns)} "
                         f"return observation(s); a dispersion measured from "
                         f"fewer than two is not a number worth printing")
        return out

    periods = result._returns_periods_per_year
    # 252 means the curve was resampled to days; the other value is the
    # single-day fallback in to_returns(), where every annualised number below
    # is extrapolated from one session and should not be compared with a
    # multi-day run's.
    daily = periods == 252

    def stat(name, **kwargs):
        """One metric, or None if it is not a finite number.

        The finiteness check is load-bearing, not defensive tidying. Calmar is
        CAGR over max drawdown, and a run that never drew down divides by zero
        -- quantstats returns inf, and `json.dumps(inf)` emits the literal
        `Infinity`, which is not valid JSON and fails a strict parser. Since
        the whole point of the JSON document is that something else parses it,
        an undefined ratio has to be reported as null rather than as a value.
        """
        fn = getattr(qs.stats, name, None)
        if fn is None:
            return None
        try:
            value = float(fn(returns, **kwargs))
        except Exception:
            return None
        return round(value, 6) if math.isfinite(value) else None

    out.update({
        "available": True,
        "resolution": "daily" if daily else "minute",
        "periods_per_year": periods,
        "observations": int(len(returns)),
        "sharpe": stat("sharpe", periods=periods),
        "sortino": stat("sortino", periods=periods),
        "calmar": stat("calmar", periods=periods),
        "cagr": stat("cagr", periods=periods),
        "volatility_annual": stat("volatility", periods=periods),
        "max_drawdown": stat("max_drawdown"),
        # quantstats calls this "Time in Market" in the HTML report. It counts
        # the share of periods with a non-zero return, which is not the share
        # of capital deployed -- but it is the standard name, so it keeps it.
        "time_in_market": stat("exposure"),
        "recovery_factor": stat("recovery_factor"),
        "ulcer_index": stat("ulcer_index"),
        "best_period": stat("best"),
        "worst_period": stat("worst"),
        # Named for the unit they are in, because this report also carries a
        # win rate over round trips and the two are not the same quantity.
        "winning_periods_pct": stat("win_rate"),
        "value_at_risk_95": stat("value_at_risk"),
        "cvar_95": stat("cvar"),
        # A Sharpe summarises a distribution by two moments. These two say
        # whether that was a reasonable thing to do.
        "skew": stat("skew"),
        "kurtosis": stat("kurtosis"),
    })
    nonzero = int((returns.abs() > 1e-12).sum())
    out["flat_periods"] = int(len(returns)) - nonzero
    out["tearsheet"] = tearsheet(returns, periods)
    # The HTML report renders three data tables, not one: the metrics table
    # above, a drawdown-periods table and a monthly/EOY returns table. All
    # three are here so this document is a complete substitute for it.
    out["drawdowns"] = drawdown_periods(returns)
    out["monthly_returns"] = monthly_returns(returns)
    return out


def drawdown_periods(returns) -> List[Dict[str, Any]]:
    """Every completed drawdown, worst first.

    The HTML's "Worst 10 Drawdowns" table. A single max-drawdown number says
    how deep the worst one went and nothing about how long it lasted, which is
    the half a reader actually needs: on one synthetic curve here the worst
    drawdown was 316 days, and no scalar in the metrics table says so.

    Empty for a run still underwater at the close -- quantstats only reports
    drawdowns that ended -- which is why `longest_dd_days` in the metrics
    table is null for a losing run rather than wrong.
    """
    try:
        import quantstats as qs
        series = qs.stats.to_drawdown_series(returns)
        frame = qs.stats.drawdown_details(series)
    except Exception:
        return []
    if frame is None or len(frame) == 0:
        return []

    # quantstats is inconsistent about the unit here, so it is normalised once
    # on the way in rather than at each place something reads it.
    # `qs.stats.max_drawdown()` returns a FRACTION (-0.0116) while the
    # `max drawdown` column of `drawdown_details` is a PERCENT (-1.1586) --
    # verified to be exactly a factor of 100 apart on the same series, and
    # against a peak-to-trough computed straight off the equity curve. Left
    # alone it renders as "-115.86%", a drawdown deeper than total ruin, which
    # is the kind of number that makes a reader stop believing the document.
    percent_columns = {"max_drawdown", "99_pct_max_drawdown"}

    out: List[Dict[str, Any]] = []
    try:
        ordered = frame.sort_values(by="max drawdown", ascending=True)
        for _, row in ordered.iterrows():
            entry: Dict[str, Any] = {}
            for label in frame.columns:
                key = _metric_key(str(label))
                value = _metric_value(row[label])
                if key in percent_columns and isinstance(value, float):
                    value = value / 100.0
                entry[key] = value
            out.append(entry)
    except Exception:
        return []
    return out


def monthly_returns(returns) -> Dict[str, Any]:
    """The month-by-month matrix with a year-end column.

    Both the heatmap and the EOY table in the HTML come from this. It is the
    only place a reader can see that a result came from one good month, which
    is the same question `by_day`/`by_regime` answer for the market side.
    """
    try:
        import quantstats as qs
        frame = qs.stats.monthly_returns(returns, eoy=True, compounded=True)
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    if frame is None or len(frame) == 0:
        return {"available": False, "reason": "no complete month in the run"}

    try:
        columns = [str(c) for c in frame.columns]
        rows = {str(year): {str(col): _metric_value(frame.loc[year, col])
                            for col in frame.columns}
                for year in frame.index}
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {"available": True, "columns": columns, "years": rows}


def _metric_key(label: str) -> str:
    """A quantstats display label as a stable-ish snake_case key.

    The labels are meant for a browser, so they carry characters a key should
    not: "CAGR﹪" uses a full-width percent sign, "Sortino/√2" a root, "3Y
    (ann.)" a leading digit and a dot.
    """
    text = (label.strip()
            .replace("√", "sqrt")
            .replace("﹪", "_pct")
            .replace("%", "_pct")
            .replace("/", "_")
            .replace("&", "_and_"))
    out = []
    for char in text.lower():
        out.append(char if char.isalnum() else "_")
    key = "".join(out)
    while "__" in key:
        key = key.replace("__", "_")
    return key.strip("_")


def _metric_value(value: Any) -> Any:
    """Keep numbers as numbers, dates as strings, and blanks as null."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value if math.isfinite(float(value)) else None
    text = str(value).strip()
    # quantstats writes "-" for a metric it could not compute, and leaves a
    # cell empty for some. Neither is a value.
    if text in ("", "-", "nan", "NaN", "None"):
        return None
    try:
        number = float(text.rstrip("%"))
    except ValueError:
        return text
    return number if math.isfinite(number) else None


def tearsheet(returns, periods: int) -> Dict[str, Any]:
    """Every row of quantstats' full HTML report, as a dict.

    Mirrored from `qs.reports.metrics(mode="full")` -- the same call the HTML
    is built from -- rather than assembled from a list of metric names here,
    so this cannot fall behind the tearsheet it is supposed to match.
    """
    try:
        import quantstats as qs
        frame = qs.reports.metrics(returns, mode="full", display=False,
                                   periods_per_year=periods)
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    out: Dict[str, Any] = {"available": True, "metrics": {}, "labels": {}}
    try:
        column = frame.columns[0]
        for label, value in frame[column].items():
            key = _metric_key(str(label))
            if not key:
                continue
            out["metrics"][key] = _metric_value(value)
            # The original label kept alongside, so a reader can match a row
            # against the HTML without reversing the key mangling.
            out["labels"][key] = str(label).strip()
    except Exception as exc:
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}

    # One backfill, for one reason: `metrics()` leaves the Max Drawdown cell
    # empty while the HTML report shows a figure, because that block is built
    # from drawdown_details() -- which is empty whenever the series ends still
    # underwater, as a losing run does. `max_drawdown()` answers directly, so
    # the blank is a formatting artefact rather than a missing quantity, and
    # the cell a reader checks first should not be the one that is empty.
    #
    # The other blanks in that block -- Max DD Date, Period Start, Period End,
    # Longest DD Days, Avg. Drawdown Days -- are NOT backfilled. They describe
    # a completed drawdown, and a run that never recovered does not have one.
    # Null is the true answer there.
    if out["metrics"].get("max_drawdown") is None:
        try:
            value = float(qs.stats.max_drawdown(returns))
            if math.isfinite(value):
                out["metrics"]["max_drawdown"] = round(value, 4)
                out["labels"].setdefault("max_drawdown", "Max Drawdown")
        except Exception:
            pass
    return out


@dataclass
class TripStats:
    """Round trips, described the way a trader would ask about them."""
    count: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    gross_pnl: float = 0.0
    gross_wins: float = 0.0
    gross_losses: float = 0.0
    profit_factor: Optional[float] = None
    avg_pnl: float = 0.0
    median_pnl: float = 0.0
    best: float = 0.0
    worst: float = 0.0
    median_hold_days: float = 0.0
    hold_buckets: Dict[str, int] = field(default_factory=dict)
    longest_losing_streak: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def summarise_trips(trips: list) -> TripStats:
    stats = TripStats()
    if not trips:
        return stats
    pnls = [t.pnl for t in trips]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    stats.count = len(trips)
    stats.wins, stats.losses = len(wins), len(losses)
    stats.win_rate = round(len(wins) / len(trips) * 100, 1)
    stats.gross_pnl = round(sum(pnls), 2)
    stats.gross_wins = round(sum(wins), 2)
    stats.gross_losses = round(sum(losses), 2)
    # None rather than infinity when nothing lost: a profit factor with no
    # denominator is not a large number, it is undefined.
    stats.profit_factor = (round(sum(wins) / abs(sum(losses)), 2)
                           if losses and sum(losses) else None)
    stats.avg_pnl = round(statistics.fmean(pnls), 2)
    stats.median_pnl = round(statistics.median(pnls), 2)
    stats.best, stats.worst = round(max(pnls), 2), round(min(pnls), 2)
    holds = [t.holding_days for t in trips]
    stats.median_hold_days = round(statistics.median(holds), 1)
    buckets = Counter()
    for days in holds:
        buckets["same day" if days == 0 else "1-2 days" if days <= 2
                else "3-5 days" if days <= 5 else "over 5 days"] += 1
    stats.hold_buckets = dict(buckets)
    streak = worst = 0
    for pnl in pnls:
        streak = streak + 1 if pnl <= 0 else 0
        worst = max(worst, streak)
    stats.longest_losing_streak = worst
    return stats


# ═══════════════════════════════════════════════════════════════════════════
#  The join — what the market was doing when the strategy acted
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class DayJoin:
    """One trading day, from both sides."""
    date: str
    regime: str
    efficiency: float
    trendiness: float
    change_pct: float
    range_pct: float
    vol_bp: float
    fills: int
    trips_closed: int
    pnl: float

    def to_dict(self) -> dict:
        return asdict(self)


def join_by_day(sessions: List[SessionStats], fills: List[dict],
                trips: list) -> List[DayJoin]:
    """Line the market's days up against the strategy's.

    Keyed on the market's calendar, not the strategy's: the days it did
    nothing are the ones that answer "why did it stop", so a join that dropped
    them would delete the evidence.
    """
    fills_by_day = Counter(str(f.get("time", ""))[:10] for f in fills)
    pnl_by_day: Dict[str, float] = defaultdict(float)
    trips_by_day: Counter = Counter()
    for trip in trips:
        day = str(trip.exit_time)[:10]       # attributed to the exit
        pnl_by_day[day] += trip.pnl
        trips_by_day[day] += 1
    return [DayJoin(
        date=s.date, regime=s.regime, efficiency=s.efficiency,
        trendiness=s.trendiness,
        change_pct=s.change_pct, range_pct=s.range_pct, vol_bp=s.vol_bp,
        fills=fills_by_day.get(s.date, 0),
        trips_closed=trips_by_day.get(s.date, 0),
        pnl=round(pnl_by_day.get(s.date, 0.0), 2),
    ) for s in sessions]


def by_regime(days: List[DayJoin]) -> Dict[str, dict]:
    """Trading and P&L bucketed by what the market was doing.

    This is the bucket that answers "it only suits a particular stretch": a
    strategy whose winning days are all in one regime, and whose losing days
    are all in another, is not a strategy with a bad parameter -- it is a
    strategy that only has an edge in one kind of market.
    """
    out: Dict[str, dict] = {}
    for regime in ("trending", "neutral", "ranging"):
        bucket = [d for d in days if d.regime == regime]
        if not bucket:
            continue
        traded = [d for d in bucket if d.fills]
        pnls = [d.pnl for d in bucket if d.trips_closed]
        out[regime] = {
            "sessions": len(bucket),
            "sessions_traded": len(traded),
            "fills": sum(d.fills for d in bucket),
            "trips_closed": sum(d.trips_closed for d in bucket),
            "pnl": round(sum(d.pnl for d in bucket), 2),
            "winning_days": sum(1 for p in pnls if p > 0),
            "losing_days": sum(1 for p in pnls if p < 0),
            "median_vol_bp": round(statistics.median(
                [d.vol_bp for d in bucket]), 1) if bucket else 0.0,
        }
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  Findings
# ═══════════════════════════════════════════════════════════════════════════

def find_problems(act: Activity, trips: TripStats, days: List[DayJoin],
                  net_pnl: float, window: tuple,
                  trading_days: int = 0) -> List[Finding]:
    """The handful of things that are usually the answer.

    Each one states the number that triggered it. None of them is a verdict:
    an expert should be able to read the evidence and disagree.
    """
    out: List[Finding] = []

    if act.fills == 0:
        # Counted off the equity curve, not off `days`: the market join is
        # keyed on the symbols that were filled, so a run with no fills has no
        # sessions to count and would otherwise report zero days.
        out.append(Finding(
            "high", "The strategy never traded",
            f"0 fills over {trading_days or len(days)} trading day(s)",
            "Either no entry condition was ever true, or every signal was "
            "refused before it reached the broker. The pickle cannot tell "
            "these apart — see what this cannot see."))
        return out

    # Costs against the gross result. Tested against the MAGNITUDE of gross,
    # not against a positive gross: the clearest case of overtrading is a
    # gross of roughly zero -- the trades were a coin flip -- beside a net
    # deeply negative, where the fees were the only thing that compounded.
    # A gross-must-be-positive guard stays silent on exactly that run.
    gross = trips.gross_pnl
    if trips.count and act.costs >= max(abs(gross), 1.0) * COST_VS_GROSS_FLAG:
        per_trip = act.costs / trips.count
        if gross > 0:
            what = "Costs eat most of the gross profit"
            evidence = (f"costs {act.costs:,.0f} against gross {gross:,.0f} "
                        f"({act.costs / gross:.0%}), net {net_pnl:+,.0f}")
        else:
            share = (f", which is {act.costs / abs(net_pnl):.0%} of the net "
                     f"{net_pnl:+,.0f}") if net_pnl else ""
            what = "The loss is the cost of trading, not the trading"
            evidence = (f"{trips.count} round trips were {gross:+,.0f} gross "
                        f"-- near flat -- while costs came to "
                        f"{act.costs:,.0f}{share}")
        out.append(Finding(
            "high",
            what,
            evidence + f"; {per_trip:,.0f} per round trip on a median order "
                       f"of {act.median_order_value:,.0f}",
            "A Taiwan round trip cannot cost less than about 0.585% of the "
            f"position (commission {COMMISSION_RATE:.4%} on each side plus "
            "0.3% transaction tax on the sell), so every trade starts that "
            "far behind. When the gross is flat it means the entry is firing "
            "on moves smaller than that floor: this is a signal frequency "
            "problem, and no exit tuning fixes it."))

    if act.fills and act.fee_floor_fills / act.fills >= FEE_FLOOR_SHARE_FLAG:
        out.append(Finding(
            "medium", "Orders are too small for the fee schedule",
            f"{act.fee_floor_fills} of {act.fills} fills "
            f"({act.fee_floor_fills / act.fills:.0%}) paid the NT${COMMISSION_FLOOR:.0f} "
            f"minimum rather than the {COMMISSION_RATE:.4%} rate; median order "
            f"{act.median_order_value:,.0f}",
            f"Below NT${COMMISSION_FLOOR / COMMISSION_RATE:,.0f} an order pays more "
            "than the rate, so a backtest at this size overstates costs "
            "relative to a real position. This is a sizing setting, not a "
            "strategy result."))

    if trips.count >= 20 and trips.median_hold_days == 0:
        same_day = trips.hold_buckets.get("same day", 0)
        out.append(Finding(
            "medium", "Positions are held for minutes, not days",
            f"{same_day} of {trips.count} round trips opened and closed in "
            f"one session; median hold 0 days",
            "Intraday churn. Worth checking against the costs line above, and "
            "against whether the signal is meant to be a day trade."))

    # Concentration: did a handful of days make all of it?
    earners = sorted((d for d in days if d.pnl), key=lambda d: -abs(d.pnl))
    total = sum(abs(d.pnl) for d in days)
    if len(earners) > 3 and total:
        top3 = sum(abs(d.pnl) for d in earners[:3]) / total
        if top3 >= CONCENTRATION_FLAG:
            out.append(Finding(
                "high", "The result comes from a handful of days",
                f"the 3 biggest days are {top3:.0%} of all P&L movement "
                f"({', '.join(d.date for d in earners[:3])})",
                "A total this concentrated is not evidence of an edge that "
                "repeats. Check what those days had in common — the regime "
                "table is the place to look."))

    # Did it stop trading well before the window ended?
    first, last = window
    if act.last_fill and last:
        span = (last - first).total_seconds()
        idle = (last - datetime.fromisoformat(act.last_fill)).total_seconds()
        if span > 0 and idle / span >= IDLE_TAIL_FLAG:
            out.append(Finding(
                "high", "It stopped trading long before the run ended",
                f"last fill {act.last_fill[:10]}, run ended "
                f"{last:%Y-%m-%d} — the final {idle / span:.0%} of the window "
                f"has no fills",
                "Something turned it off: a condition that stopped being true, "
                "a position it never exited, or the risk gate halting. The "
                "last of those is invisible here."))

    if act.fills and trips.count == 0:
        out.append(Finding(
            "high", "It opened positions and never closed any",
            f"{act.fills} fill(s), 0 completed round trips",
            "Every P&L number here is unrealised and priced at the last mark. "
            "An exit condition that never fires is the usual cause."))

    if trips.count and trips.win_rate >= 60 and net_pnl < 0:
        out.append(Finding(
            "high", "It wins more often than it loses and still loses money",
            f"win rate {trips.win_rate:.0f}% over {trips.count} trips, "
            f"net {net_pnl:,.0f}",
            "The winners are smaller than the losers, or the costs are "
            "larger than the average win. Compare avg win against avg loss "
            "and against the cost per round trip."))

    # Regime concentration of the winners.
    regimes = by_regime(days)
    profitable = {r: v for r, v in regimes.items() if v["pnl"] > 0}
    losing = {r: v for r, v in regimes.items() if v["pnl"] < 0}
    if len(regimes) > 1 and len(profitable) == 1 and losing:
        only = next(iter(profitable))
        out.append(Finding(
            "high", f"It only makes money when the market is {only}",
            "; ".join(f"{r}: {v['pnl']:+,.0f} over {v['sessions']} session(s)"
                      for r, v in regimes.items()),
            "This is a strategy with one regime, not a strategy with a "
            "mistuned parameter. Widening the parameter will not add an edge "
            "to the regimes where it has none; a regime filter that keeps it "
            "out of them might."))

    if not out:
        out.append(Finding(
            "low", "Nothing flagged",
            f"{act.fills} fill(s), {trips.count} round trip(s), "
            f"net {net_pnl:,.0f}",
            "None of the usual failure shapes are present. That is not the "
            "same as an edge — see what this cannot see before concluding."))
    return out


# ═══════════════════════════════════════════════════════════════════════════
#  Reports
# ═══════════════════════════════════════════════════════════════════════════

# (title, body) or (title, body, answered_by) where answered_by names the
# provenance key that closes the gap. A blind spot that provenance has since
# filled in must drop off the list -- a report that prints the parameters in
# one section and calls them invisible in another teaches a reader to stop
# believing the section.
CANNOT_SEE = [
    ("Risk-gate refusals",
     "How many signals were refused before reaching the broker, and for which "
     "of the four reasons (halted, orders-per-bar, duplicate, allocation). A "
     "run whose signals were mostly refused tells you about the gate, not the "
     "strategy. The engine logs each one and counts none."),
    ("Signals a bot suppressed itself",
     "A bot declines to re-signal a symbol while one of its orders is still "
     "in flight. That path is a log.debug, so a strategy that fired 300 times "
     "and placed 15 orders looks identical here to one that fired 15 times."),
    ("Why it did not trade, bar by bar",
     "Every strategy reports a `last_decision` each bar -- 'squeeze: bandwidth "
     "0.4% under the 1.0% floor' and so on. Counting those would name the "
     "parameter that is binding. Master keeps only the last 500 across all "
     "bots and none of them reach the pickle."),
    ("The strategy's own parameters",
     "Window lengths, thresholds, position sizing. Without them a reader can "
     "see that behaviour is too sensitive but not to which number.",
     "params"),
    ("Which symbols were watched",
     "Only the ones that were filled, which is how the market sections below "
     "pick what to load. A symbol the strategy watched all run and never "
     "traded is the most interesting one to look at, and it leaves no trace "
     "in the pickle -- so a run with no fills gets no market section at all.",
     "symbols"),
    ("Bars served and bars dropped",
     "Whether the strategy saw the whole window. A dropped bar is a hole in "
     "its price history that it never knows about."),
]

CAVEATS = [
    "`bar.high` and `bar.low` are the trading DAY's extremes up to that bar, "
    "not that bar's own -- the feed samples one price per bar. A strategy "
    "reading them as per-bar ranges is reading something else.",
    "A fill cannot be observed before the prices that caused it, so an order "
    "placed on bar t is first checked for a fill over (t, t+1]. One bar of "
    "latency is the market's behaviour, not a defect.",
    "Return % here is against initial CASH while final equity is cash plus "
    "holdings, so a run that ends holding a position overstates its return by "
    "whatever the position is worth.",
    "Round-trip P&L is gross: (exit - entry) x quantity, before commission "
    "and tax. The costs line is where they are.",
    "Volatility and regime come from this machine's 1-minute history for the "
    "same window, not from what the engine fed the strategy. They agree when "
    "the run was a replay of that history.",
    "Sharpe, Sortino and Calmar are computed on the ACCOUNT's equity, not on "
    "the capital at risk, so position size moves them on its own. The same "
    "113 signals sized from 3% to 40% of equity span a Sharpe of -9.59 to "
    "-2.41 while the P&L moves the opposite way. Compare them across signal "
    "parameters, not across sizing.",
    "`regime` is one number about one trading day, set against a random walk "
    "of the same length, with cut-offs chosen from how 3,987 real sessions "
    "actually distribute. It says whether a day went somewhere, not why, and "
    "a day can range for five hours and then trend for one.",
]


def cannot_see(provenance: Optional[dict]) -> List[tuple]:
    """The blind spots that are still blind, given what provenance recorded.

    Returns (title, body) pairs with the `answered_by` tag dropped, so the
    renderers do not need to know about the filtering.
    """
    prov = provenance or {}
    out: List[tuple] = []
    for entry in CANNOT_SEE:
        title, body = entry[0], entry[1]
        answered_by = entry[2] if len(entry) > 2 else None
        if answered_by and prov.get(answered_by):
            continue
        out.append((title, body))
    return out


def _num(value: Optional[float]) -> str:
    """A number, or an em dash when quantstats could not produce one."""
    return "—" if value is None else f"{value:,.3f}"


def _pct(value: Optional[float]) -> str:
    """A fraction rendered as a percentage. None becomes an em dash."""
    return "—" if value is None else f"{value * 100:,.2f}%"


def _bar(value: float, scale: float, width: int = 18) -> str:
    """A crude inline bar, so a table can be skimmed without reading numbers."""
    if scale <= 0:
        return ""
    filled = int(min(1.0, abs(value) / scale) * width)
    return ("█" if value >= 0 else "▒") * max(filled, 1 if value else 0)


def render_markdown(doc: dict) -> str:
    """The report a person or an agent reads."""
    out: List[str] = []
    add = out.append
    run, act, trips = doc["run"], doc["activity"], doc["round_trips"]

    add(f"# Run insight — {run['session_id'][:8]}")
    add("")
    add(f"Generated {doc['generated_at']} from `{doc['sources']['result']}`.")
    add("")

    # ── findings first: this is what the report is for ────────────────────
    add("## What stands out")
    add("")
    for f in doc["findings"]:
        add(f"- **[{f['severity']}] {f['what']}**  ")
        add(f"  {f['evidence']}  ")
        add(f"  _{f['why']}_")
    add("")

    # ── provenance: governs how everything below should be read ───────────
    add("## How this run was produced")
    add("")
    prov = doc.get("provenance")
    if not prov:
        add("_The result file records no provenance, so which execution path "
            "produced it is unknown. It predates the field. Treat the "
            "execution assumptions below as unverified: a oneshot run and a "
            "trading-engine run disagree on fills, costs and capital, and "
            "nothing here can tell you which one this was._")
        add("")
    else:
        add("| | |")
        add("|---|---|")
        add(f"| path | **{prov.get('path', 'unknown')}** |")
        add(f"| strategy | {prov.get('strategy', '—')} |")
        add(f"| interval | **{prov.get('interval', '—')}** |")
        add(f"| symbols | {', '.join(prov.get('symbols') or []) or '—'} |")
        add(f"| requested window | {prov.get('requested_start', '—')} → "
            f"{prov.get('requested_end', '—')}"
            + ("" if prov.get("start_was_explicit", True)
               else " ⚠ start date was RANDOM, not given") + " |")
        add(f"| bars fed to the strategy | {prov.get('bars', 0):,} |")
        add(f"| parameter set | `{prov.get('params_hash', '—')}` |")
        add("")
        if prov.get("execution_model"):
            add(f"**Execution model.** {prov['execution_model']}")
            add("")
        if prov.get("comparable_to_engine") is False:
            add("> These numbers are **not** comparable with a trading-engine "
                "run of the same strategy and parameters. The engine places a "
                "limit order that fills only when a later close crosses it, "
                "splits capital across bots, and applies a risk gate — none "
                "of which happens here. Use this to rank candidates, then "
                "confirm the shortlist on the engine.")
            add("")
        params = prov.get("params") or {}
        if params:
            add("<details><summary>Parameters in full</summary>")
            add("")
            add("| parameter | value |")
            add("|---|---|")
            for key in sorted(params):
                add(f"| `{key}` | {params[key]} |")
            add("")
            add("</details>")
            add("")
        costs = prov.get("cost_model") or {}
        if costs:
            add(f"Cost model: commission {costs.get('commission_rate', 0):.4%}"
                f" x {costs.get('commission_discount', 1)} (min NT${costs.get('min_commission', 0):.0f}),"
                f" tax {costs.get('stock_tax_rate', 0):.2%} stock /"
                f" {costs.get('etf_tax_rate', 0):.2%} ETF on sells,"
                f" slippage `{costs.get('slippage_model', 'none')}`"
                + (f" at {costs.get('slippage_pct', 0):.3%}"
                   if costs.get("slippage_model") != "none" else "") + ".")
            add("")

    add("## The run")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| session | `{run['session_id']}` |")
    add(f"| window | {run['first_sample']} → {run['last_sample']} "
        f"({run['trading_days']} trading days, {run['equity_points']} equity points) |")
    add(f"| symbols traded | {', '.join(act['symbols']) or '—'} |")
    add(f"| initial cash | {run['initial_balance']:,.2f} |")
    add(f"| final cash | {run['final_balance']:,.2f} |")
    add(f"| final equity | {run['final_equity']:,.2f} |")
    add(f"| net P&L | {run['net_pnl']:+,.2f} ({run['net_pnl_pct']:+.2f}%) |")
    add(f"| realised / unrealised | {run['realised_pnl']:+,.2f} / "
        f"{run['unrealised_pnl']:+,.2f} |")
    add("")

    add("## How it traded")
    add("")
    add(f"- {act['fills']} fills ({act['buys']} buy, {act['sells']} sell), "
        f"first {act['first_fill'] or '—'}, last {act['last_fill'] or '—'}")
    add(f"- traded value {act['traded_value']:,.0f}, median order "
        f"{act['median_order_value']:,.0f}")
    add(f"- turnover {run['turnover']:.1f}x the starting account")
    add(f"- commission {act['commission']:,.2f} · tax {act['tax']:,.2f}"
        + (f" · slippage {act['slippage']:,.2f}" if act['slippage'] else "")
        + f" · **total {act['costs']:,.2f}**")
    if act["fills"]:
        add(f"- {act['fee_floor_fills']} of {act['fills']} fills paid the "
            f"NT${COMMISSION_FLOOR:.0f} commission minimum")
    add("")

    if trips["count"]:
        add("## Round trips")
        add("")
        add(f"- {trips['count']} completed · win rate {trips['win_rate']:.1f}% "
            f"({trips['wins']} / {trips['losses']})")
        add(f"- gross {trips['gross_pnl']:+,.2f} "
            f"(wins {trips['gross_wins']:+,.2f}, losses {trips['gross_losses']:+,.2f})"
            + (f" · profit factor {trips['profit_factor']}"
               if trips["profit_factor"] is not None else ""))
        add(f"- per trip: avg {trips['avg_pnl']:+,.2f}, median "
            f"{trips['median_pnl']:+,.2f}, best {trips['best']:+,.2f}, "
            f"worst {trips['worst']:+,.2f}")
        add(f"- holding: median {trips['median_hold_days']} days · "
            + ", ".join(f"{k} {v}" for k, v in trips["hold_buckets"].items()))
        add(f"- longest losing streak {trips['longest_losing_streak']}")
        add("")

    # ── risk-adjusted metrics ────────────────────────────────────────────
    perf = doc.get("performance") or {}
    add("## Risk-adjusted performance")
    add("")
    if not perf.get("available"):
        add(f"_Not measured: {perf.get('reason', 'unavailable')}._")
        add("")
    else:
        # "daily"/"minute" reads as an adverb in the prose above and as a
        # noun in the table below, so the table gets its own word.
        unit = "day" if perf["resolution"] == "daily" else "minute"
        add(f"From quantstats over {perf['observations']} "
            f"{perf['resolution']} observations, annualised at "
            f"{perf['periods_per_year']} periods/year.")
        add("")
        add("| | | | |")
        add("|---|---:|---|---:|")
        add(f"| Sharpe | {_num(perf['sharpe'])} "
            f"| max drawdown | {_pct(perf['max_drawdown'])} |")
        add(f"| Sortino | {_num(perf['sortino'])} "
            f"| Calmar | {_num(perf['calmar'])} |")
        add(f"| CAGR | {_pct(perf['cagr'])} "
            f"| annualised volatility | {_pct(perf['volatility_annual'])} |")
        add(f"| time in market | {_pct(perf.get('time_in_market'))} "
            f"| observations | {perf['observations']} |")
        add(f"| best {unit} | {_pct(perf['best_period'])} "
            f"| worst {unit} | {_pct(perf['worst_period'])} |")
        add(f"| winning {unit}s | "
            f"{_pct(perf['winning_periods_pct'])} "
            f"| flat {unit}s | {perf['flat_periods']} |")
        add(f"| VaR 95% | {_pct(perf['value_at_risk_95'])} "
            f"| CVaR 95% | {_pct(perf['cvar_95'])} |")
        add(f"| skew | {_num(perf['skew'])} "
            f"| kurtosis | {_num(perf['kurtosis'])} |")
        add(f"| recovery factor | {_num(perf['recovery_factor'])} "
            f"| Ulcer index | {_num(perf['ulcer_index'])} |")
        add("")
        if perf["resolution"] != "daily":
            add("> ⚠ The run was too short to resample to days, so every "
                "annualised figure above is extrapolated from minute returns "
                "within a single session. Do not compare them with a "
                "multi-day run's.")
            add("")
        add("**Read the Sharpe with the position size in mind.** It is "
            "computed on the whole account's equity, not on the capital "
            "actually at risk, so a strategy that deploys 3% of the account "
            "has a tiny denominator and an inflated |Sharpe|. Measured on "
            "this codebase: the same 113 signals sized at 3%, 5%, 10%, 20% "
            "and 40% of equity give Sharpe −9.59, −5.79, −3.13, −2.41, −2.41 "
            "while net P&L goes the other way, −2,552 to −10,260. Ranking "
            "position sizes by Sharpe inverts the answer. It is safe to "
            "compare runs that differ only in signal parameters, and unsafe "
            "across runs that differ in sizing.")
        add("")
        # Every row of the tearsheet, so this file is a complete substitute
        # for opening the HTML. Collapsed because it is long and most of it is
        # not what a reader came for.
        sheet = perf.get("tearsheet") or {}
        if sheet.get("available") and sheet.get("metrics"):
            labels = sheet.get("labels") or {}
            add(f"<details><summary>Every quantstats metric "
                f"({len(sheet['metrics'])} rows, the same set as the HTML "
                f"tearsheet)</summary>")
            add("")
            add("| metric | value | key |")
            add("|---|---:|---|")
            for key, value in sheet["metrics"].items():
                shown = "—" if value is None else (
                    f"{value:,.4f}" if isinstance(value, float) else value)
                add(f"| {labels.get(key, key)} | {shown} | `{key}` |")
            add("")
            add("</details>")
            add("")
            add("_Those carry the tearsheet's display precision (Sharpe "
                "-9.59, not -9.589301) because matching the HTML is the point "
                "of them. The table above has the full precision, and its key "
                "names are ours rather than quantstats' labels, so a script "
                "should read that one._")
            add("")

        # ── the drawdown-periods table ───────────────────────────────────
        drawdowns = perf.get("drawdowns") or []
        add("### Drawdowns")
        add("")
        if not drawdowns:
            add("_No drawdown ever ended, so quantstats reports none. A run "
                "still below its high-water mark at the close has no "
                "completed drawdown to describe — which is also why "
                "`Longest DD Days` is blank in the table above._")
            add("")
        else:
            add("Worst first. The depth is in the metrics table; the "
                "duration is only here.")
            add("")
            add("| start | valley | end | days | max drawdown |")
            add("|---|---|---|---:|---:|")
            for dd in drawdowns:
                add(f"| {dd.get('start', '—')} | {dd.get('valley', '—')} "
                    f"| {dd.get('end', '—')} | {dd.get('days', '—')} "
                    f"| {_pct(dd.get('max_drawdown'))} |")
            add("")

        # ── the monthly / EOY returns table ──────────────────────────────
        months = perf.get("monthly_returns") or {}
        add("### Returns by month")
        add("")
        if not months.get("available"):
            add(f"_Not available: {months.get('reason', 'unknown')}._")
            add("")
        else:
            columns = months["columns"]
            add("| year | " + " | ".join(columns) + " |")
            add("|---" * (len(columns) + 1) + "|")
            for year, cells in months["years"].items():
                values = " | ".join(_pct(cells.get(c)) for c in columns)
                add(f"| {year} | {values} |")
            add("")
            add("_This is the only place a result built out of one good "
                "month shows itself._")
            add("")

        if perf.get("skew") is not None and perf.get("kurtosis") is not None \
                and (abs(perf["skew"]) > 1 or perf["kurtosis"] > 3):
            add(f"The return distribution is skewed {perf['skew']:+.2f} with "
                f"kurtosis {perf['kurtosis']:.2f}, so it is not normal and a "
                f"Sharpe — which keeps only the first two moments — hides "
                f"most of what the tail is doing. The worst "
                f"{unit} and the CVaR describe that better.")
            add("")

    # ── the join: market against strategy ────────────────────────────────
    market = doc["market"]
    add("## What the market was doing")
    add("")
    if not market["symbols"]:
        add("_No price history on this machine for this window, so nothing "
            "here can be said about the market. The sections below that depend "
            "on it are omitted rather than guessed._")
        add("")
    else:
        for sym, info in market["symbols"].items():
            add(f"**{sym}** — {info['sessions']} sessions "
                f"{info['first']} → {info['last']}, "
                f"{info['bars']:,} one-minute bars")
            if info["weekdays_without_bars"]:
                add(f"- {info['weekdays_without_bars']} weekday(s) in that "
                    f"span have no bars — market holidays and gaps in what "
                    f"has been fetched are indistinguishable here")
            add(f"- price {info['low']:,.2f} … {info['high']:,.2f}, "
                f"net {info['change_pct']:+.2f}% over the window")
            add(f"- median session range {info['median_range_pct']:.2f}%, "
                f"median 1m volatility {info['median_vol_bp']:.1f}bp")
            add("- regimes: " + ", ".join(
                f"{k} {v}" for k, v in info["regime_days"].items()))
            add("")

        regimes = doc["by_regime"]
        if regimes:
            add("### Strategy against regime")
            add("")
            add(f"A session's `trend` is how far it travelled against how far "
                f"a random walk of the same number of bars would have: 1.00 is "
                f"chance, above {TRENDING_ABOVE} is trending, below "
                f"{RANGING_BELOW} is ranging.")
            add("")
            add("| regime | sessions | traded | fills | trips | P&L | "
                "win days | lose days | median vol |")
            add("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
            for name, v in regimes.items():
                add(f"| {name} | {v['sessions']} | {v['sessions_traded']} | "
                    f"{v['fills']} | {v['trips_closed']} | {v['pnl']:+,.0f} | "
                    f"{v['winning_days']} | {v['losing_days']} | "
                    f"{v['median_vol_bp']:.1f}bp |")
            add("")

        days = doc["by_day"]
        traded_days = [d for d in days if d["fills"] or d["trips_closed"]]
        if traded_days:
            add("### Every session it traded")
            add("")
            scale = max((abs(d["pnl"]) for d in traded_days), default=0.0)
            add("| date | regime | trend | chg% | range% | vol | fills | "
                "trips | P&L | |")
            add("|---|---|---:|---:|---:|---:|---:|---:|---:|---|")
            for d in traded_days:
                add(f"| {d['date']} | {d['regime']} | {d['trendiness']:.2f} | "
                    f"{d['change_pct']:+.2f} | {d['range_pct']:.2f} | "
                    f"{d['vol_bp']:.0f}bp | {d['fills']} | {d['trips_closed']} | "
                    f"{d['pnl']:+,.0f} | {_bar(d['pnl'], scale)} |")
            add("")
            idle = len(days) - len(traded_days)
            if idle:
                add(f"_It sat out {idle} of {len(days)} sessions. Those are in "
                    f"the JSON under `by_day`._")
                add("")

    add("## What this cannot see")
    add("")
    add("The engine knows these and the pickle does not carry them. Read the "
        "sections above with that in mind.")
    add("")
    for title, body in doc["cannot_see"]:
        add(f"- **{title}.** {body}")
    add("")

    add("## How these numbers lie")
    add("")
    for caveat in doc["caveats"]:
        add(f"- {caveat}")
    add("")
    return "\n".join(out)


# ═══════════════════════════════════════════════════════════════════════════
#  Assembly
# ═══════════════════════════════════════════════════════════════════════════

def build(result: BacktestResult, result_path: Path) -> dict:
    """Everything the two renderers need, as one plain dict."""
    curve = result.equity_curve or []
    first = datetime.fromisoformat(curve[0]["time"]) if curve else None
    last = datetime.fromisoformat(curve[-1]["time"]) if curve else None
    if first is None and result.start_time:
        first = datetime.fromisoformat(result.start_time)

    act = summarise_activity(result.fill_history or [])
    try:
        raw_trips = result.compute_round_trips()
    except Exception:
        raw_trips = []
    trips = summarise_trips(raw_trips)

    final_equity = (result.final_equity if result.final_equity is not None
                    else result.final_balance)
    net_pnl = final_equity - result.initial_balance

    # ── the market side ──────────────────────────────────────────────────
    db_path = paths.price_db_path()
    con = _open_price_db(db_path)
    sessions_by_symbol: Dict[str, List[SessionStats]] = {}
    market: Dict[str, Any] = {"database": str(db_path), "available": con is not None,
                              "symbols": {}}
    if con is not None and first and last:
        for sym in (act.symbols or []):
            sessions = load_sessions(con, sym, first, last)
            if not sessions:
                continue
            sessions_by_symbol[sym] = sessions
            closes = [s.close for s in sessions]
            regimes = Counter(s.regime for s in sessions)
            # Weekdays between the first and last session present that have no
            # bars. Deliberately NOT called missing data: this codebase has no
            # holiday table (TradingCalendar only knows weekends), so a market
            # holiday and a genuine gap are indistinguishable here. Reported as
            # a count for the reader to judge rather than flagged as a fault.
            present = {s.date for s in sessions}
            span_days = (datetime.fromisoformat(sessions[-1].date)
                         - datetime.fromisoformat(sessions[0].date)).days + 1
            weekdays = sum(
                1 for i in range(span_days)
                if (datetime.fromisoformat(sessions[0].date)
                    + timedelta(days=i)).weekday() < 5)
            market["symbols"][sym] = {
                "sessions": len(sessions),
                "bars": sum(s.bars for s in sessions),
                "first": sessions[0].date, "last": sessions[-1].date,
                "low": min(s.low for s in sessions),
                "high": max(s.high for s in sessions),
                "change_pct": round(
                    (closes[-1] - sessions[0].open) / sessions[0].open * 100, 2)
                if sessions[0].open else 0.0,
                "median_range_pct": round(statistics.median(
                    [s.range_pct for s in sessions]), 3),
                "median_vol_bp": round(statistics.median(
                    [s.vol_bp for s in sessions]), 1),
                "regime_days": dict(regimes),
                "weekdays_without_bars": max(0, weekdays - len(present)),
            }
        con.close()

    # One symbol's calendar drives the day-by-day join. With several, the one
    # with the most sessions is the most complete view of the window.
    anchor = max(sessions_by_symbol.values(), key=len, default=[])
    days = join_by_day(anchor, result.fill_history or [], raw_trips)

    trading_days = len({str(e["time"])[:10] for e in curve})
    doc = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": {
            "result": str(result_path),
            "price_database": str(db_path) if market["available"] else None,
        },
        "run": {
            "session_id": result.session_id or "unknown",
            "start_time": result.start_time,
            "first_sample": curve[0]["time"] if curve else None,
            "last_sample": curve[-1]["time"] if curve else None,
            "equity_points": len(curve),
            "trading_days": trading_days,
            "initial_balance": result.initial_balance,
            "final_balance": result.final_balance,
            "final_equity": round(final_equity, 2),
            "net_pnl": round(net_pnl, 2),
            "net_pnl_pct": round(net_pnl / result.initial_balance * 100, 3)
            if result.initial_balance else 0.0,
            "realised_pnl": round(result.final_balance - result.initial_balance, 2),
            "unrealised_pnl": round(final_equity - result.final_balance, 2),
            "turnover": round(act.traded_value / result.initial_balance, 2)
            if result.initial_balance else 0.0,
        },
        # Which execution path produced this and under what assumptions.
        # getattr, not attribute access: results pickled before the field
        # existed have no value for it, and an old run is exactly the case
        # where a reader most needs to be told the provenance is unknown.
        "provenance": getattr(result, "provenance", None),
        "activity": act.to_dict(),
        "round_trips": trips.to_dict(),
        "performance": performance(result),
        "market": market,
        "by_day": [d.to_dict() for d in days],
        "by_regime": by_regime(days),
        "sessions": {sym: [s.to_dict() for s in ss]
                     for sym, ss in sessions_by_symbol.items()},
        "cannot_see": cannot_see(getattr(result, "provenance", None)),
        "caveats": CAVEATS,
    }
    doc["findings"] = [f.to_dict() for f in find_problems(
        act, trips, days, net_pnl, (first, last), trading_days)]
    return doc


# ═══════════════════════════════════════════════════════════════════════════
#  Finding the run
# ═══════════════════════════════════════════════════════════════════════════

# The two things that write a BacktestResult: the trading engine
# (poc/trading_engine/main2.py) and the oneshot backtester
# (apps/cjtrade_system/cjtrade_oneshot_backtest.py). Both land in reports_dir;
# the prefix is the only thing that distinguishes them by file name, and the
# `provenance` field is what distinguishes them properly.
RUN_PREFIXES = ("engine_", "oneshot_")


def available_runs() -> List[Path]:
    """Every result file on this machine, newest first."""
    directory = paths.reports_dir()
    if not directory.exists():
        return []
    found: List[Path] = []
    for prefix in RUN_PREFIXES:
        found.extend(directory.glob(f"{prefix}*.pkl"))
    # Exclude our own output, which lands beside the run it describes and
    # would otherwise be picked up as a run on the next invocation.
    found = [p for p in found if not p.name.endswith(".insight.pkl")]
    return sorted(found, key=lambda p: p.stat().st_mtime, reverse=True)


def _strip_prefix(stem: str) -> str:
    for prefix in RUN_PREFIXES:
        if stem.startswith(prefix):
            return stem[len(prefix):]
    return stem


def resolve(target: Optional[str]) -> Path:
    """A path, a session prefix, or nothing for the most recent run."""
    if target:
        candidate = Path(target).expanduser()
        if candidate.is_file():
            return candidate
        # Matched against the session id, not the file name: every file is
        # called engine_<id> or oneshot_<symbols>_<id>, so matching the whole
        # stem would make a target of "e" or "one" match every run on the
        # machine for no useful reason.
        key = _strip_prefix(target)
        matches = [p for p in available_runs() if key in _strip_prefix(p.stem)]
        if not matches:
            raise SystemExit(
                f"no run matching {target!r}. Try `insight --list`.")
        if len(matches) > 1:
            names = ", ".join(p.stem for p in matches[:6])
            raise SystemExit(
                f"{target!r} matches {len(matches)} runs ({names}...). "
                f"Use a longer prefix.")
        return matches[0]

    runs = available_runs()
    if not runs:
        raise SystemExit(
            f"no runs found in {paths.reports_dir()}. Finish a run first.")
    return runs[0]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="insight",
        description="Distil a finished run into a report an expert can "
                    "diagnose: what the strategy did, what the market was "
                    "doing, and what stands out.")
    parser.add_argument("run", nargs="?", default=None,
                        help="session id, a unique prefix of one, or a path to "
                             "an engine_*.pkl. Omit for the most recent run.")
    parser.add_argument("--list", action="store_true",
                        help="list the runs on this machine and exit")
    parser.add_argument("--out", default=None, metavar="DIR",
                        help="write the two files here instead of next to the "
                             "run's own artefacts")
    parser.add_argument("--stdout", action="store_true",
                        help="also print the markdown report")
    args = parser.parse_args(argv)

    if args.list:
        runs = available_runs()
        if not runs:
            print(f"No runs in {paths.reports_dir()}.")
            return 0
        print(f"{len(runs)} run(s) in {paths.reports_dir()}:")
        for path in runs:
            when = datetime.fromtimestamp(path.stat().st_mtime)
            # The prefix is how a run names its path without opening the
            # pickle, which keeps --list fast on a directory of hundreds.
            kind = ("oneshot" if path.name.startswith("oneshot_")
                    else "engine" if path.name.startswith("engine_")
                    else "?")
            print(f"  {_strip_prefix(path.stem):<40} {kind:<8} "
                  f"{when:%Y-%m-%d %H:%M}  {path.stat().st_size:>9,} bytes")
        return 0

    result_path = resolve(args.run)
    try:
        result = BacktestResult.load(str(result_path))
    except Exception as exc:
        raise SystemExit(f"could not read {result_path}: {exc}")

    doc = build(result, result_path)

    out_dir = Path(args.out).expanduser() if args.out else result_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = result_path.stem
    md_path = out_dir / f"{stem}.insight.md"
    json_path = out_dir / f"{stem}.insight.json"

    markdown = render_markdown(doc)
    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(json.dumps(doc, indent=2, default=str),
                         encoding="utf-8")

    if args.stdout:
        print(markdown)
        print()

    # The whole point of the command: say where the two files are, plainly,
    # as the last thing on screen.
    flagged = [f for f in doc["findings"] if f["severity"] == "high"]
    prov = doc.get("provenance") or {}
    where = (f" [{prov['path']}"
             + (f", {prov['interval']}" if prov.get("interval") else "")
             + "]") if prov.get("path") else ""
    print(f"Run {doc['run']['session_id'][:8]}{where} — "
          f"{doc['activity']['fills']} fill(s), "
          f"{doc['round_trips']['count']} round trip(s), "
          f"net {doc['run']['net_pnl']:+,.2f}")
    perf = doc.get("performance") or {}
    if perf.get("available"):
        print(f"  Sharpe {_num(perf['sharpe'])} · Sortino "
              f"{_num(perf['sortino'])} · CAGR {_pct(perf['cagr'])} · "
              f"max drawdown {_pct(perf['max_drawdown'])}")
    if not prov:
        print("  ⚠ no provenance recorded — which execution path produced "
              "this is unknown")
    if not doc["market"]["available"]:
        print("  ⚠ no price database, so the market sections are empty")
    elif not doc["market"]["symbols"]:
        print("  ⚠ no price history for this window, so the market sections "
              "are empty")
    if flagged:
        print(f"  {len(flagged)} thing(s) worth a look: "
              + "; ".join(f["what"] for f in flagged))
    print()
    print(f"  report  {md_path}")
    print(f"  json    {json_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
