"""Run the trading engine once, offline, on recorded bars.

``engine_run`` loads ``fixtures/2357_1m.csv.gz`` into a price file, starts
``arenaxd --backend=backtest --data=offline`` on it, runs ``cjtrade`` over
the window and hands the tests the exit code, the logs and the saved result.
Nothing reaches the network, and everything written goes to a temporary
``CJTRADE_HOME``.

The bars are Sinopac 1m bars for 2357, 2024-04-29 .. 2024-05-24 (Taipei
time), copied from a local price cache. The run replays the first 10 days.
"""
from __future__ import annotations

import csv
import gzip
import os
import socket
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import requests
from cjtrade.pkgs.marketdata import PriceCache
from cjtrade.pkgs.models.backtest import BacktestResult

DATA = Path(__file__).parent / "fixtures" / "2357_1m.csv.gz"
SYMBOL = "2357"            # Bot_B's symbol in BOT_ROSTER
START = "2024-04-29"
DAYS = 10
FUND = 1_000_000
PORT = 8802                # arenaxd's backtest port, which cjtrade expects
# The engine binds these too; another run on the machine would collide.
ENGINE_PORTS = (5555, 5556, 8898)
TZ = ZoneInfo("Asia/Taipei")
BIN = Path(sys.executable).parent


@dataclass
class EngineRun:
    returncode: int
    engine_log: str
    server_log: str
    result: BacktestResult


def _port_in_use(port: int) -> bool:
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def _load_price_db(path: Path) -> None:
    """Write the CSV's bars into a price file, as preload-prices would."""
    PriceCache(str(path)).conn            # creates the tables
    with gzip.open(DATA, "rt", newline="") as f:
        rows = [(SYMBOL, "1m",
                 int(datetime.strptime(r["time"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ).timestamp()),
                 float(r["open"]), float(r["high"]), float(r["low"]),
                 float(r["close"]), float(r["volume"]), "fixture")
                for r in csv.DictReader(f)]
    with sqlite3.connect(path) as conn:
        conn.executemany(
            "INSERT INTO arenax_prices (symbol, timeframe, ts, open, high, low, close, volume, source)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        conn.execute(
            "INSERT INTO arenax_symbol_coverage (symbol, timeframe, start_ts, end_ts, source)"
            " VALUES (?, '1m', ?, ?, 'fixture')", (SYMBOL, rows[0][2] - 60, rows[-1][2]))


def _wait_ready(server: subprocess.Popen, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.poll() is not None:
            raise RuntimeError(f"arenaxd exited with {server.returncode} during startup")
        try:
            if requests.get(f"http://127.0.0.1:{PORT}/health", timeout=2).json().get("running"):
                return
        except requests.RequestException:
            pass
        time.sleep(1)
    raise RuntimeError(f"arenaxd not ready after {timeout:.0f}s")


@pytest.fixture(scope="session")
def engine_run(tmp_path_factory) -> EngineRun:
    busy = [p for p in (PORT, *ENGINE_PORTS) if _port_in_use(p)]
    if busy:
        pytest.skip(f"port(s) {busy} in use; stop the other arenaxd/cjtrade first")

    work = tmp_path_factory.mktemp("engine")
    db = work / "prices.db"
    _load_price_db(db)
    env = {**os.environ, "CJTRADE_HOME": str(work / "home"), "CJTRADE_OFFLINE": "1",
           "TZ": "Asia/Taipei", "AX_BACKTEST_DURATION_DAYS": str(DAYS + 15),
           "AX_INITIAL_BALANCE": str(FUND)}
    server_log = work / "arenax.log"
    with open(server_log, "w") as out:
        server = subprocess.Popen(
            [BIN / "arenaxd", "--backend=backtest", f"--port={PORT}", "--data=offline",
             f"--price-db={db}"], env=env, stdout=out, stderr=subprocess.STDOUT)
    try:
        _wait_ready(server)
        engine = subprocess.run(
            [BIN / "cjtrade", "--broker=arenax", "--mode=backtest", f"--watch-list={SYMBOL}",
             f"--fund={FUND}", f"--days={DAYS}", f"--start-date={START}", "--speed=0"],
            env=env, capture_output=True, text=True, timeout=600)
    finally:
        server.terminate()
        try:
            server.wait(timeout=20)
        except subprocess.TimeoutExpired:
            server.kill()

    engine_log = engine.stdout + engine.stderr
    (work / "engine.log").write_text(engine_log)
    reports = sorted((work / "home").rglob("engine_*.pkl"))
    assert reports, f"no result saved; engine log in {work}"
    return EngineRun(engine.returncode, engine_log, server_log.read_text(),
                     BacktestResult.load(str(reports[-1])))
