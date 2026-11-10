#!/usr/bin/env python3
"""Show what is actually in the ArenaX price cache, and where it breaks.

    uv run python scripts/price_db_report.py                 # every symbol, one row each
    uv run python scripts/price_db_report.py -s 2317         # one symbol, in detail
    uv run python scripts/price_db_report.py -s 2317 --months --days
    uv run python scripts/price_db_report.py -s 2317 --from 2026-01-01 --to 2026-07-01

The main picture is a timeline: one solid bar from the first bar to the last,
broken wherever data is missing, with the ends and every break dated.

Why this exists
---------------
A replay is only as good as its bars, and a thin patch does not announce
itself. Two failure modes that cost real debugging time:

1. A month-sized hole. ArenaX picks a random backtest start date, so a run can
   land on a window the cache does not hold; the engine replays whatever bars
   exist and the result looks like a legitimate flat stretch.

2. A coverage row with no bars behind it. `_persist_kbars` records coverage and
   inserts bars as two separate steps, and `compute_missing_ranges` consults
   the COVERAGE table, not the bars. A coverage row spanning a gap therefore
   makes that gap permanent: nothing will refetch it, because the cache
   believes it is already covered. The coverage audit is the only way to see
   this.

Read-only: opens the database with mode=ro, so it is safe to run against a
live server without contending for a write lock.
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import date
from datetime import datetime
from datetime import timedelta

# A regular TWSE session is 09:00-13:30, so 270 one-minute bars. Taken from the
# calendar rather than a literal so the two cannot drift apart.
try:
    from cjtrade.apps.ArenaX.trading_calendar import TradingCalendar
    _CAL = TradingCalendar()
    BARS_PER_DAY = int(
        (datetime.combine(date.today(), _CAL.REGULAR.close)
         - datetime.combine(date.today(), _CAL.REGULAR.open)).total_seconds() // 60
    )
except Exception:                                    # pragma: no cover
    _CAL = None
    BARS_PER_DAY = 270

FULL, PARTIAL, EMPTY = "█", "▒", " "


def _default_db() -> str:
    try:
        from cjtrade.pkgs import paths
        return str(paths.price_db_path())
    except Exception:                                # pragma: no cover
        return "arenax_price.db"


def _connect(path: str) -> sqlite3.Connection:
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        con.execute("SELECT 1 FROM arenax_prices LIMIT 1")
        return con
    except sqlite3.OperationalError as exc:
        sys.exit(f"cannot read {path}: {exc}")


def _ts_clause(args) -> tuple[str, list]:
    clause, params = "", []
    if args.date_from:
        clause += " AND ts >= ?"
        params.append(int(datetime.fromisoformat(args.date_from).timestamp()))
    if args.date_to:
        clause += " AND ts < ?"
        params.append(int(datetime.fromisoformat(args.date_to).timestamp()))
    return clause, params


def _walk(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


# ── the axis ─────────────────────────────────────────────────────────────────

def market_days(con, args) -> list[date]:
    """Every date on which ANY symbol has bars, in order.

    This is the timeline's axis, and it stands in for a holiday calendar the
    repo does not have: TradingCalendar.is_trading_day is weekends-only, and
    its docstring points at pkgs/utils/ncal.py for holiday data that ncal.py
    does not actually contain.

    Using open days rather than calendar days is what makes a break mean
    something. On a calendar axis every Lunar New Year is a seven-day hole, so
    the eye learns to ignore holes -- which is exactly the wrong lesson.
    """
    clause, params = _ts_clause(args)
    return sorted(
        date.fromisoformat(d) for (d,) in con.execute(
            "SELECT DISTINCT date(ts,'unixepoch','localtime') "
            "FROM arenax_prices WHERE timeframe=?" + clause,
            [args.timeframe] + params)
    )


def symbol_days(con, args, symbol: str) -> dict[date, int]:
    clause, params = _ts_clause(args)
    return {
        date.fromisoformat(d): n for d, n in con.execute(
            "SELECT date(ts,'unixepoch','localtime') d, COUNT(*) "
            "FROM arenax_prices WHERE symbol=? AND timeframe=?" + clause +
            " GROUP BY d", [symbol, args.timeframe] + params)
    }


# ── the timeline ─────────────────────────────────────────────────────────────

def _cells(axis: list[date], have: dict[date, int], width: int,
           min_bars: int) -> tuple[str, list[tuple[int, int]]]:
    """Render the bar, and return the cell spans that are entirely missing.

    A cell covers several market days once the range is long, so three states
    are needed: a solid block only when every day in the cell is there and
    complete, a break only when none of them are, and a half-tone in between.
    Collapsing the middle case into either of the others would either hide a
    real hole or cry wolf over one short session.
    """
    n = len(axis)
    out, breaks = [], []
    for c in range(width):
        lo = c * n // width
        hi = max(lo + 1, (c + 1) * n // width)
        days = axis[lo:hi]
        present = [d for d in days if d in have]
        if not present:
            out.append(EMPTY)
            if breaks and breaks[-1][1] == c:
                breaks[-1] = (breaks[-1][0], c + 1)
            else:
                breaks.append((c, c + 1))
        elif len(present) == len(days) and all(have[d] >= min_bars for d in present):
            out.append(FULL)
        else:
            out.append(PARTIAL)
    return "".join(out), breaks


def _gap_runs(axis: list[date], have: dict[date, int]) -> list[tuple[date, date, int]]:
    """Contiguous runs of market days this symbol has no bars for."""
    runs: list[tuple[date, date, int]] = []
    start = prev = None
    count = 0
    for d in axis:
        if d in have:
            if start is not None:
                runs.append((start, prev, count))
                start = prev = None
                count = 0
            continue
        if start is None:
            start = d
        prev = d
        count += 1
    if start is not None:
        runs.append((start, prev, count))
    return runs


def _stack_labels(items: list[tuple[int, str]], width: int) -> list[str]:
    """Lay labels out under the bar, dropping to a new line on collision."""
    lines: list[list[str]] = []
    for pos, text in sorted(items):
        pos = max(0, min(pos, width - 1))
        for row in lines:
            cur = "".join(row).rstrip()
            if len(cur) + 1 <= pos:
                row.extend([" "] * (pos - len(cur)))
                row.extend(list(text))
                break
        else:
            row = [" "] * pos + list(text)
            lines.append(row)
    return ["".join(r) for r in lines]


def timeline(axis: list[date], have: dict[date, int], args,
             label: str = "", width: int | None = None,
             show_breaks: bool = True) -> None:
    if not axis:
        print("  (no data in range)")
        return
    width = width or args.width
    bar, breaks = _cells(axis, have, width, args.min_bars)
    first = min(have) if have else axis[0]
    last = max(have) if have else axis[-1]

    pad = f"{label:<8}" if label else ""
    print(f"  {pad}{first:%Y-%m-%d} |{bar}| {last:%Y-%m-%d}")

    if not show_breaks or not breaks:
        return
    # One marker per break, dated, stacked so they do not overwrite each other.
    runs = _gap_runs(axis, have)
    marks: list[tuple[int, str]] = []
    n = len(axis)
    for a, b, cnt in runs:
        mid = (axis.index(a) + axis.index(b)) // 2
        pos = mid * width // max(n, 1)
        span = f"{a:%Y-%m-%d}" if a == b else f"{a:%Y-%m-%d}..{b:%Y-%m-%d}"
        marks.append((pos, f"^ {span} ({cnt}d)"))
    # Two spaces of indent, the label, "YYYY-MM-DD" and " |" — so a marker at
    # bar position p lands under the cell it describes.
    offset = 2 + len(pad) + len("YYYY-MM-DD") + 2
    for line in _stack_labels(marks, width):
        print(" " * offset + line)


# ── overview ─────────────────────────────────────────────────────────────────

def overview(con, args) -> None:
    axis = market_days(con, args)
    if not axis:
        print("no bars in that range")
        return
    clause, params = _ts_clause(args)
    syms = [s for (s,) in con.execute(
        "SELECT symbol FROM arenax_prices WHERE timeframe=?" + clause +
        " GROUP BY symbol ORDER BY COUNT(*) DESC", [args.timeframe] + params)]

    width = max(20, args.width - 10)
    print(f"axis: {len(axis)} market days, {axis[0]} .. {axis[-1]}  "
          f"(1 cell = {len(axis)/width:.1f} days)\n")
    for sym in syms:
        have = symbol_days(con, args, sym)
        timeline(axis, have, args, label=sym, width=width, show_breaks=False)

    print(f"\n  {FULL} complete   {PARTIAL} some days missing or short   "
          f"'{EMPTY}' no data")
    print("  Rows share one axis, so a break under another row's solid run is "
          "this symbol's\n  gap, not a market holiday. -s <symbol> dates every "
          "break and audits coverage.")


# ── per-symbol detail ────────────────────────────────────────────────────────

def monthly(have: dict[date, int], axis: list[date]) -> None:
    print("\n-- bars per month " + "-" * 56)
    open_per_month: dict[str, int] = {}
    for d in axis:
        open_per_month[f"{d.year:04d}-{d.month:02d}"] = \
            open_per_month.get(f"{d.year:04d}-{d.month:02d}", 0) + 1
    got_per_month: dict[str, list[int]] = {}
    for d, n in have.items():
        got_per_month.setdefault(f"{d.year:04d}-{d.month:02d}", []).append(n)

    print(f"  {'month':<9}{'bars':>9} {'days':>8}  of the market's open days")
    for key in sorted(open_per_month):
        counts = got_per_month.get(key, [])
        expected = open_per_month[key]
        got = len(counts)
        w = 30
        filled = round(got / expected * w) if expected else 0
        note = "  MISSING" if got == 0 else ""
        print(f"  {key:<9}{sum(counts):>9,} {got:>3}/{expected:<4} "
              f"{FULL * filled}{'.' * (w - filled)}{note}")


def thin_days(have: dict[date, int], args) -> None:
    if args.timeframe != "1m":
        return
    thin = sorted((n, d) for d, n in have.items() if n < args.min_bars)
    print(f"\n-- short sessions (under {args.min_bars} of {BARS_PER_DAY} bars) "
          + "-" * 22)
    if not thin:
        print("  none")
        return
    print(f"  {len(thin)} day(s). These sit inside the bar as {PARTIAL}, not a "
          f"break:")
    for n, d in thin[:12]:
        w = 30
        filled = round(n / BARS_PER_DAY * w)
        print(f"    {d}  {n:>4}  {FULL * filled}{'.' * (w - filled)}")
    if len(thin) > 12:
        print(f"    ... and {len(thin) - 12} more")


def sources(con, args) -> None:
    clause, params = _ts_clause(args)
    rows = list(con.execute(
        "SELECT source, COUNT(*) FROM arenax_prices "
        "WHERE symbol=? AND timeframe=?" + clause +
        " GROUP BY source ORDER BY 2 DESC", [args.symbol, args.timeframe] + params))
    total = sum(n for _, n in rows) or 1
    print("\n-- where the bars came from " + "-" * 45)
    for src, n in rows:
        print(f"  {src or '(unset)':<14}{n:>9,}  {n/total*100:>5.1f}%")
    if len(rows) > 1:
        print("  Sources are not interchangeable: yfinance keeps roughly a "
              "month of 1m\n  history, so an old range filled from it is "
              "unlikely to be complete.")


def coverage_audit(con, args) -> None:
    print("\n-- coverage audit " + "-" * 55)
    rows = list(con.execute(
        "SELECT start_ts, end_ts, source FROM arenax_symbol_coverage "
        "WHERE symbol=? AND timeframe=? ORDER BY start_ts",
        [args.symbol, args.timeframe]))
    if not rows:
        print("  no coverage rows — every fetch will re-ask the broker")
        return

    print(f"  {'claimed range':<25}{'days':>5}{'bars':>9}{'expected':>10}  status")
    suspect = []
    for s, e, _src in rows:
        a, b = datetime.fromtimestamp(s).date(), datetime.fromtimestamp(e).date()
        n = con.execute(
            "SELECT COUNT(*) FROM arenax_prices WHERE symbol=? AND timeframe=? "
            "AND ts BETWEEN ? AND ?", [args.symbol, args.timeframe, s, e]
        ).fetchone()[0]
        td = sum(1 for d in _walk(a, b) if (_CAL.is_trading_day(d) if _CAL
                                            else d.weekday() < 5))
        expected = td * BARS_PER_DAY if args.timeframe == "1m" else td
        if n == 0:
            status = "EMPTY -- gap is now permanent"
            suspect.append((s, a, b))
        elif expected and n < expected * 0.5:
            status = f"only {n/expected*100:.0f}% present"
            suspect.append((s, a, b))
        else:
            status = "ok"
        print(f"  {a}..{b}  {td:>5}{n:>9,}{expected:>10,}  {status}")

    if suspect:
        print(f"\n  {len(suspect)} suspect row(s). compute_missing_ranges() reads "
              f"this table,\n  not the bars, so these ranges will never be "
              f"refetched. To let the next\n  fetch fill them, drop the row:")
        for s, a, b in suspect:
            print(f"    DELETE FROM arenax_symbol_coverage WHERE symbol="
                  f"'{args.symbol}' AND start_ts={s};   -- {a}..{b}")


def detail(con, args) -> None:
    axis = market_days(con, args)
    have = symbol_days(con, args, args.symbol)
    if not have:
        print(f"\n{args.symbol}: no {args.timeframe} bars in range")
        return

    total = sum(have.values())
    runs = _gap_runs(axis, have)
    missing = sum(c for _, _, c in runs)
    print(f"\n{args.symbol}  {args.timeframe}   {total:,} bars over "
          f"{len(have)} of the market's {len(axis)} open days"
          f"   ({len(have)/len(axis)*100:.1f}% covered)\n")

    timeline(axis, have, args)

    print(f"\n  1 cell = {len(axis)/args.width:.1f} market days.   "
          f"{FULL} complete   {PARTIAL} missing or short   '{EMPTY}' no data")
    if missing:
        print(f"  {missing} open day(s) missing in {len(runs)} run(s). "
              f"Weekends and holidays are off the axis,\n  so every break "
              f"above is data this symbol lacks while others have it.")
    else:
        print("  No breaks: every day the market was open is present.")

    thin_days(have, args)
    sources(con, args)
    coverage_audit(con, args)

    if args.months:
        monthly(have, axis)
    if args.days:
        print("\n-- every day " + "-" * 60)
        for d in sorted(have):
            n = have[d]
            w = 40
            filled = round(n / BARS_PER_DAY * w)
            print(f"  {d}  {n:>4}  {FULL * filled}{'.' * (w - filled)}")


def main() -> None:
    term = shutil.get_terminal_size((100, 24)).columns
    p = argparse.ArgumentParser(
        description="Report ArenaX price-cache completeness as a timeline.",
        epilog="Read-only; safe to run while a server is using the database.")
    p.add_argument("-s", "--symbol", help="detail for one symbol, e.g. 2317")
    p.add_argument("-t", "--timeframe", default="1m")
    p.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD")
    p.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="exclusive")
    p.add_argument("--width", type=int, default=max(30, min(term, 120) - 30),
                   help="timeline width in characters")
    p.add_argument("--months", action="store_true", help="add a monthly table")
    p.add_argument("--days", action="store_true", help="list every day")
    p.add_argument("--min-bars", type=int, default=int(BARS_PER_DAY * 0.9),
                   help=f"a 1m day below this counts as short (default "
                        f"{int(BARS_PER_DAY * 0.9)} of {BARS_PER_DAY})")
    p.add_argument("--db", default=None, help="override the database path")
    args = p.parse_args()

    path = args.db or _default_db()
    con = _connect(path)
    print(f"price cache: {path}")
    print(f"1m session  : {BARS_PER_DAY} bars/day "
          f"({'from TradingCalendar' if _CAL else 'assumed'})")
    if args.symbol:
        detail(con, args)
    else:
        print()
        overview(con, args)


if __name__ == "__main__":
    main()
