"""Tests for scripts/check_readme_examples.py.

A checker nobody checks is a checker that quietly stops catching things, and
the specific thing this one exists to catch is subtle: the failure that
prompted it printed `command not found` and then exited 0. So the first test
below reproduces that shape -- a healthy exit status over a broken run -- and
asserts it is still reported.

The fixtures are synthetic on purpose. Proving the detector works by breaking
the real poc/backtest.sh would mean a test that leaves the repository damaged
if it fails halfway.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "check_readme_examples.py"


def _load():
    """Import scripts/check_readme_examples.py, which is not a package.

    Registered in sys.modules before it executes: @dataclass resolves its
    annotations through sys.modules[cls.__module__], so a module that is not
    there yet fails at class-definition time with an opaque AttributeError.
    """
    spec = importlib.util.spec_from_file_location("cjcheck", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cjcheck():
    return _load()


def _block(cjcheck, body: str, mode: str = "smoke", **opts):
    return cjcheck.Block(path="fixture.md", line=1, lang="sh", body=body,
                         mode=mode, opts={"timeout": "3", **opts})


# ── the failure this script exists for ───────────────────────────────────────

def test_stray_stdout_reaching_eval_is_reported(cjcheck):
    """A line of noise in an eval's input, with a 0 exit status.

    This is poc/backtest.sh's bug in miniature: something printed on the
    channel the shell was about to execute. `eval` ran it, bash said `command
    not found`, and because the *last* command in the eval succeeded the script
    carried on and exited 0.
    """
    body = (
        'eval "$(printf \'Opening browser...\\nexport FOO=1\\n\')"\n'
        'echo "carried on with FOO=$FOO"\n'
    )
    problems = cjcheck._launch(_block(cjcheck, body))
    assert problems, "a command that printed `command not found` was passed"
    assert "stray line reached a shell" in problems[0]


def test_exit_status_alone_would_have_missed_it(cjcheck):
    """Guards the reasoning above rather than the code.

    If this ever fails, the fixture stopped exiting 0 and the test above is no
    longer testing what it claims to.
    """
    body = 'eval "$(printf \'Opening browser...\\nexport FOO=1\\n\')"\n'
    problems = cjcheck._launch(_block(cjcheck, body))
    assert not any("exited" in p for p in problems)


# ── launching ────────────────────────────────────────────────────────────────

def test_a_healthy_command_passes(cjcheck):
    problems = cjcheck._launch(_block(cjcheck, 'echo "export FOO=1"\n'))
    assert problems == []


def test_smoke_accepts_a_command_that_does_not_terminate(cjcheck):
    """Still running when the timeout expires is the PASS case.

    Most documented commands start a server or stop on a form. "It got off the
    ground" is the question being asked.
    """
    problems = cjcheck._launch(_block(cjcheck, "sleep 30\n", timeout="1"))
    assert problems == []


def test_smoke_rejects_a_command_that_dies(cjcheck):
    problems = cjcheck._launch(_block(cjcheck, "exit 3\n"))
    assert problems and "exited 3" in problems[0]


def test_run_requires_a_zero_exit(cjcheck):
    problems = cjcheck._launch(_block(cjcheck, "exit 1\n", mode="run"))
    assert problems and "exited 1" in problems[0]


def test_run_rejects_a_command_that_never_finishes(cjcheck):
    problems = cjcheck._launch(
        _block(cjcheck, "sleep 30\n", mode="run", timeout="1"))
    assert problems and "had not finished" in problems[0]


def test_a_traceback_is_reported(cjcheck):
    body = "python3 -c 'raise SystemError(\"boom\")'\n"
    problems = cjcheck._launch(_block(cjcheck, body))
    assert problems and "unhandled exception" in problems[0]


def test_a_real_broker_is_never_launched(cjcheck):
    """Marking a sinopac command `smoke` must not place an order."""
    problems = cjcheck._launch(
        _block(cjcheck, "uv run cjtrade --broker=sinopac\n"))
    assert problems and "real broker" in problems[0]


# ── static checks ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def static(cjcheck):
    entries = cjcheck._entry_points()
    tables = cjcheck._route_tables()

    def check(body: str, lang: str = "sh"):
        block = cjcheck.Block("fixture.md", 1, lang, body, "static", {})
        return cjcheck._static_checks(block, entries, tables)

    return check


def test_a_missing_path_is_reported(static):
    problems = static("bash poc/does_not_exist.sh --flag\n")
    assert problems and "path does not exist" in problems[0]


def test_a_real_path_is_accepted(static):
    assert static("bash poc/backtest.sh\n") == []


def test_an_unknown_entry_point_is_reported(static):
    problems = static("uv run definitely-not-a-script\n")
    assert problems and "[project.scripts]" in problems[0]


def test_a_retired_route_is_reported(static):
    """The ArenaX API moved from /control/* to /api/v1/* and the docs did not.

    Exactly the drift this check exists for.
    """
    problems = static("curl http://127.0.0.1:8801/control/get-market-time\n")
    assert problems and "is not a route the server on port 8801" in problems[0]


def test_a_current_route_is_accepted(static):
    assert static("curl http://127.0.0.1:8801/api/v1/clock\n") == []


def test_another_server_is_judged_by_its_own_routes(static):
    """8898 is the trading engine, not ArenaX.

    One route table for every port reported /status as missing, which is a
    false alarm -- and a check that cries wolf gets switched off.
    """
    assert static("curl http://127.0.0.1:8898/status\n") == []
    problems = static("curl http://127.0.0.1:8898/api/v1/clock\n")
    assert problems and "port 8898" in problems[0]


def test_an_unknown_port_is_not_guessed_at(static):
    assert static("curl http://127.0.0.1:12345/whatever\n") == []


def test_a_declared_but_dead_entry_point_is_reported(cjcheck):
    """A name declared in [project.scripts] whose module was deleted.

    `osystem` used to be exactly this. Checking only that the name is declared
    passed it, so the target is resolved too.
    """
    entries = dict(cjcheck._entry_points())
    entries["dead"] = "cjtrade.apps.no_such_module:main"
    block = cjcheck.Block("fixture.md", 1, "sh", "uv run dead\n", "static", {})
    problems = cjcheck._static_checks(block, entries, cjcheck._route_tables())
    assert problems and "does not exist" in problems[0]


def test_an_unaccepted_flag_is_reported(static):
    problems = static("bash poc/backtest.sh --no-such-flag\n")
    assert problems and "does not accept --no-such-flag" in problems[0]


def test_documented_flags_are_accepted(static):
    body = ("bash poc/backtest.sh --watch-list 2317 --fund 5000000 "
            "--interval 1d --strategy BollingerStrategy --renderer=cli\n")
    assert static(body) == []


def test_flags_are_not_judged_against_another_command(static):
    """Two commands in one block keep their own flag lists."""
    body = ("bash poc/backtest.sh --renderer=cli\n"
            "bash poc/backtest_full_simulation.sh --speed=60\n")
    assert static(body) == []


def test_a_command_whose_flags_are_unknowable_is_skipped(static):
    """atest forwards argv to a bash script, so its flags are not visible.

    Skipped rather than rejected: "declares no flags" and "flags not readable
    from here" must not look alike.
    """
    assert static("uv run atest --broker=arenax --group=all\n") == []


def test_a_parameterised_route_is_accepted(static):
    body = "curl http://127.0.0.1:8801/api/v1/market/2330/snapshot\n"
    assert static(body) == []


def test_python_examples_must_parse(static):
    problems = static("def broken(\n", lang="python")
    assert problems and "does not parse" in problems[0]


# ── markers ──────────────────────────────────────────────────────────────────

def test_every_documented_example_is_classified(cjcheck):
    """No fenced block in a covered README may be unmarked.

    This is the property that stops coverage decaying: a new example cannot be
    added without someone deciding how it is checked.
    """
    problems = []
    for path in cjcheck.COVERED:
        assert (cjcheck.ROOT / path).exists(), f"{path} is covered but missing"
        _, trouble = cjcheck.collect(path)
        problems.extend(trouble)
    assert problems == [], "\n".join(problems)


def test_skip_without_a_reason_is_rejected(cjcheck, tmp_path, monkeypatch):
    doc = tmp_path / "x.md"
    doc.write_text("<!-- cjcheck: skip -->\n```sh\necho hi\n```\n")
    monkeypatch.setattr(cjcheck, "ROOT", tmp_path)
    _, problems = cjcheck.collect("x.md")
    assert problems and "needs reason" in problems[0]


def test_an_unknown_mode_is_rejected(cjcheck, tmp_path, monkeypatch):
    doc = tmp_path / "x.md"
    doc.write_text("<!-- cjcheck: wibble -->\n```sh\necho hi\n```\n")
    monkeypatch.setattr(cjcheck, "ROOT", tmp_path)
    _, problems = cjcheck.collect("x.md")
    assert problems and "unknown cjcheck mode" in problems[0]


def test_a_marker_only_owns_the_fence_it_precedes(cjcheck, tmp_path,
                                                  monkeypatch):
    """A marker separated from the fence by prose owns nothing.

    Otherwise "the marker above" could silently mean one several paragraphs up,
    and a block would be checked under a mode nobody chose for it.
    """
    doc = tmp_path / "x.md"
    doc.write_text(
        "<!-- cjcheck: static -->\n\nSome prose in between.\n\n"
        "```sh\necho hi\n```\n"
    )
    monkeypatch.setattr(cjcheck, "ROOT", tmp_path)
    blocks, problems = cjcheck.collect("x.md")
    assert blocks == []
    assert problems and "has no <!-- cjcheck" in problems[0]
