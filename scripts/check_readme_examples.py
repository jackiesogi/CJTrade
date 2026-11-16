#!/usr/bin/env python3
"""
scripts/check_readme_examples.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Check that the commands in the READMEs still get off the ground.

WHAT THIS IS FOR
----------------
The thing worth catching is a documented command that dies in its first
seconds -- the reader copies it, it errors, and the docs are now worse than
nothing. The case that prompted this: `poc/backtest.sh` eval's the form's
stdout, webbrowser.open() wrote a line of its own onto that stdout, and the
shell tried to execute it.

Note what that failure looked like, because it decides the design: the script
printed `command not found` and then **exited 0**, having run the backtest on
empty variables. An exit-status check would have passed it. So a launch is
judged on its OUTPUT as well as its status, and the output patterns below are
the point of this script rather than a detail of it.

WHAT IT IS NOT FOR
------------------
Most of these commands cannot be run to completion here: they clone the repo,
start servers, place orders, or stop on a form waiting for a human. "Still
running when the timeout expires" is therefore a PASS -- it got off the ground,
which is the question being asked. Whether the run it then performs is correct
is what tests/ is for.

MARKERS
-------
Every fenced code block in the covered files must carry one, on the line
before the fence:

    <!-- cjcheck: smoke -->          launch it; must not die badly
    <!-- cjcheck: smoke timeout=20 --> ... with a longer leash
    <!-- cjcheck: run -->            launch it; must EXIT 0
    <!-- cjcheck: static -->         do not launch; check what can be checked
                                     statically (see _static_checks)
    <!-- cjcheck: skip reason="..." --> excluded, with the reason recorded

A block with no marker is an error. That is deliberate: it means a new example
cannot be added without someone deciding how it gets checked, so coverage
cannot quietly decay.

WHAT `static` DOES AND DOES NOT ESTABLISH
-----------------------------------------
It checks, from the repository alone:

* `uv run NAME` -- NAME is in [project.scripts] AND its "module:function"
  target resolves to a file that defines that function. Both halves: `osystem`
  is declared and its module was deleted, so the name alone passes.
* `uv run python -m pkg.mod` -- the module exists on disk.
* paths -- anything starting poc/ src/ scripts/ tests/ doc/ img/ exp/ exists.
* `--flags` -- accepted by the command on that line, read from the script's
  own source plus the cli_arg entries of any poc/*.toml it drives.
* URLs on a known port -- the path is a route that port's server declares.
* python blocks -- they parse.

It does NOT establish that the names inside a python block exist. A snippet
calling a method that was renamed still passes, and the brokers guide is mostly
such snippets, so treat `static` on a python block as a syntax check and
nothing more.

Anything it cannot read, it keeps quiet about rather than guessing: a URL on an
unrecognised port, or a command whose flags are not visible in its source
(`atest` forwards argv to a shell script), is skipped. A check that cries wolf
gets switched off, and then it is worth less than nothing.

USAGE
-----
    uv run python scripts/check_readme_examples.py          # everything
    uv run python scripts/check_readme_examples.py --no-smoke   # static only
    uv run python scripts/check_readme_examples.py --list       # what is covered

`--no-smoke` (or CJ_CHECK_NO_SMOKE=1) leaves only the static checks, which take
well under a second and need no network, no server and no broker.
"""
from __future__ import annotations

import argparse
import ast
import atexit
import os
import re
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import tomllib
import urllib.request
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The hand-written READMEs. poc/trading_engine/README.md and doc/ are out of
# scope on purpose; add them here when they are ready to be held to this.
COVERED = [
    "README.md",
    "src/cjtrade/README.md",
    "src/cjtrade/apps/README.md",
    "src/cjtrade/apps/ArenaX/README.md",
    "src/cjtrade/apps/CJEdit/README.md",
    "src/cjtrade/apps/CJNews/README.md",
    "src/cjtrade/apps/cjtrade_shell/README.md",
    "src/cjtrade/apps/cjtrade_system/README.md",
    "src/cjtrade/pkgs/brokers/README.md",
]

# Output that means "this died on the launch pad". Matched against stdout and
# stderr together, and fatal even when the command exits 0 -- see the module
# docstring for why that is not paranoia.
DEATH_PATTERNS = [
    (r"command not found", "a stray line reached a shell"),
    (r"Traceback \(most recent call last\)", "unhandled exception"),
    (r"ModuleNotFoundError", "a module the example needs is missing"),
    (r"\bImportError\b", "an import in the example's path is broken"),
    (r"No such file or directory", "a path the example names is gone"),
    (r"unrecognized arguments", "a flag the example passes is not accepted"),
    (r"error: argument", "a flag the example passes is rejected"),
    (r"invalid choice", "a value the example passes is not a valid choice"),
    (r"is not a valid", "a value the example passes is not accepted"),
    (r"Unknown renderer", "the renderer the example asks for does not exist"),
    (r"\bUsageError\b|^usage: .*\n.*error:", "the command rejected its own usage"),
]

# Never launch anything that could reach a real broker, however it is marked.
# A smoke test is not worth an order.
FORBIDDEN_IN_LAUNCH = [
    "sinopac",
    "--mode real",
    "--mode=real",
    "--backend real",
    "--backend=real",
]

# Where pkgs/ui's web renderer serves its form (FormEngine's web_port default).
FORM_PORT = 9876

MARKER_RE = re.compile(r"<!--\s*cjcheck:\s*(?P<body>.*?)\s*-->", re.S)
FENCE_RE = re.compile(r"^```(?P<lang>\w*)[^\n]*\n(?P<body>.*?)^```", re.S | re.M)
VALID_MODES = {"smoke", "run", "static", "skip"}


@dataclass
class Block:
    path: str
    line: int
    lang: str
    body: str
    mode: str
    opts: dict = field(default_factory=dict)

    @property
    def where(self) -> str:
        return f"{self.path}:{self.line}"


# ── parsing ──────────────────────────────────────────────────────────────────

def parse_marker(raw: str) -> tuple[str, dict]:
    """'smoke timeout=20' -> ('smoke', {'timeout': '20'})."""
    parts = shlex.split(raw)
    if not parts:
        raise ValueError("empty cjcheck marker")
    mode, opts = parts[0], {}
    for p in parts[1:]:
        key, _, value = p.partition("=")
        opts[key] = value
    return mode, opts


def collect(path: str) -> tuple[list[Block], list[str]]:
    """Every fenced block in `path`, plus complaints about missing markers."""
    text = (ROOT / path).read_text(encoding="utf-8")
    blocks, problems = [], []

    # A marker owns the fence that follows it with nothing but whitespace in
    # between. Built as a lookup rather than searched backwards from each
    # fence, so "the marker above" cannot quietly mean one several paragraphs
    # up when the nearest comment is something else.
    owned: dict[int, str] = {}
    for mk in MARKER_RE.finditer(text):
        rest = text[mk.end():]
        gap = rest[: len(rest) - len(rest.lstrip())]
        if gap.count("\n") <= 1:
            fence = FENCE_RE.search(text, mk.end())
            if fence and text[mk.end():fence.start()].strip() == "":
                owned[fence.start()] = mk.group("body")

    for m in FENCE_RE.finditer(text):
        line = text[: m.start()].count("\n") + 1
        marker = owned.get(m.start())
        if marker is None:
            problems.append(
                f"{path}:{line}: fenced block has no <!-- cjcheck: ... --> "
                f"marker. Add one (smoke | run | static | skip reason=\"...\")."
            )
            continue
        try:
            mode, opts = parse_marker(marker)
        except ValueError as exc:
            problems.append(f"{path}:{line}: {exc}")
            continue
        if mode not in VALID_MODES:
            problems.append(
                f"{path}:{line}: unknown cjcheck mode {mode!r} "
                f"(expected one of {', '.join(sorted(VALID_MODES))})"
            )
            continue
        if mode == "skip" and not opts.get("reason"):
            problems.append(
                f"{path}:{line}: `skip` needs reason=\"...\" so an unchecked "
                f"example is a decision rather than an omission."
            )
            continue
        blocks.append(Block(path, line, m.group("lang"), m.group("body"), mode, opts))
    return blocks, problems


# ── static checks ────────────────────────────────────────────────────────────

def _entry_points() -> dict[str, str]:
    """{name: "module:function"} from [project.scripts]."""
    data = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return dict(data.get("project", {}).get("scripts", {}))


# Which server answers on which port, and where its routes are declared.
# Keyed by port because there is more than one server: checking an engine URL
# against ArenaX's route table reported /status as a missing route, which is a
# false alarm -- it is the trading engine's, on 8898. A check that cries wolf
# gets switched off, so an unknown port is skipped rather than guessed at.
ROUTE_SOURCES = {
    (8801, 8802, 8803): (
        "src/cjtrade/apps/ArenaX/brokerside_server.py",
        r'@app\.(?:get|post|put|delete|route)\("([^"]+)"\)',
    ),
    (8898,): (
        "poc/trading_engine/status_api.py",
        r'add_(?:get|post)\("([^"]+)"',
    ),
}


def _route_tables() -> dict[int, set[str]]:
    """Route paths per port, read without importing a thing."""
    tables: dict[int, set[str]] = {}
    for ports, (path, pattern) in ROUTE_SOURCES.items():
        src_file = ROOT / path
        if not src_file.exists():
            continue
        found = set(re.findall(pattern, src_file.read_text()))
        # <string:order_id> and {bot_id} both become a wildcard, so a concrete
        # URL in the docs can match the route it is an example of.
        routes = {re.sub(r"<[^>]+>|\{[^}]+\}", "*", r) for r in found}
        for port in ports:
            tables[port] = routes
    return tables


def _entry_target_problem(name: str, spec: str) -> str | None:
    """Whether `name = "module:function"` points at something that exists.

    The name being declared is not the same as the entry point working:
    `osystem` is declared and its module was deleted, so it has been dead and
    advertised at the same time. Checking the name alone would have passed it.
    """
    module, _, func = spec.partition(":")
    path = ROOT / "src" / Path(*module.split("."))
    file = path.with_suffix(".py")
    if not file.exists():
        if (path / "__init__.py").exists():
            file = path / "__init__.py"
        else:
            return f"its module {module} does not exist"
    if func and not re.search(rf"^\s*(?:async\s+)?def\s+{re.escape(func)}\b",
                              file.read_text(), re.M):
        return f"{file.relative_to(ROOT)} defines no {func}()"
    return None


def _accepted_flags(command: str) -> set[str] | None:
    """Flags a command accepts, or None when that cannot be established.

    None rather than an empty set, because "this script declares no flags" and
    "this script's flags are not readable from here" must not look alike --
    treating the second as the first would reject every documented flag. `atest`
    is the case in point: it forwards argv to a bash script, so nothing about
    its flags is visible in the Python.
    """
    source: Path | None = None
    extra: set[str] = set()

    if command.endswith(".sh"):
        source = ROOT / command
        # A form-driven script's real flag list lives in its TOML schema, as
        # cli_arg; the script itself only names the few it reads directly.
        for toml_name in re.findall(r'"?(poc/[\w.]+\.toml)"?',
                                    source.read_text() if source.exists() else ""):
            toml_file = ROOT / toml_name
            if toml_file.exists():
                extra |= set(re.findall(r'cli_arg\s*=\s*"([^"]+)"',
                                        toml_file.read_text()))
    else:
        rel = ROOT / "src" / Path(*command.split("."))
        for candidate in (rel.with_suffix(".py"), rel / "__init__.py"):
            if candidate.exists():
                source = candidate
                break

    if source is None or not source.exists():
        return None
    text = source.read_text()
    declared = set(re.findall(r'add_argument\(\s*"(--[\w-]+)"', text))
    declared |= set(re.findall(r'"(--[\w-]+)"', text))
    declared |= set(re.findall(r"'(--[\w-]+)'", text))
    declared |= set(re.findall(r"(--[\w-]+)\)", text))       # case --flag=*)
    declared |= set(re.findall(r"(--[\w-]+)=\*", text))
    declared |= extra
    return declared or None


def _route_matches(path: str, routes: set[str]) -> bool:
    for r in routes:
        if r == path:
            return True
        if "*" in r:
            pattern = "^" + re.escape(r).replace(r"\*", "[^/]+") + "$"
            if re.match(pattern, path):
                return True
    return False


def _looks_like_repo_path(token: str) -> bool:
    if "/" not in token or token.startswith(("http", "-", "$", "~")):
        return False
    if token.startswith(("127.0.0.1", "localhost")):
        return False
    head = token.split("/")[0]
    return head in {"poc", "src", "scripts", "tests", "doc", "img", "exp"}


def _static_checks(b: Block, entries: dict[str, str],
                   tables: dict[int, set[str]]) -> list[str]:
    """Everything about a block that can be settled by reading the repo.

    Deliberately content-driven rather than author-declared: the block says
    what it is and the applicable checks follow, so there is no second list to
    keep in step with the first.
    """
    out = []

    if b.lang == "python":
        # Syntax only. Whether the names in the snippet exist is NOT checked --
        # see the module docstring.
        try:
            ast.parse(b.body)
        except SyntaxError as exc:
            out.append(f"{b.where}: python example does not parse: {exc}")
        return out

    # `uv run <name>` must be a declared entry point whose target resolves.
    for name in re.findall(r"uv run (?!python\b|pytest\b|--)([\w.-]+)", b.body):
        if name not in entries:
            out.append(
                f"{b.where}: `uv run {name}` is not in [project.scripts] "
                f"(have: {', '.join(sorted(entries))})"
            )
            continue
        broken = _entry_target_problem(name, entries[name])
        if broken:
            out.append(f"{b.where}: `uv run {name}` is declared but {broken}")

    # `uv run python -m pkg.mod` must resolve to a file.
    for mod in re.findall(r"uv run python -m ([\w.]+)", b.body):
        rel = Path("src") / Path(*mod.split("."))
        if not (ROOT / rel).with_suffix(".py").exists() and not (ROOT / rel).is_dir():
            out.append(f"{b.where}: `-m {mod}` does not resolve to a module")

    # Paths named in the block must exist.
    for token in re.findall(r"[\w./-]+", b.body):
        token = token.rstrip(".,:;")
        if _looks_like_repo_path(token) and not (ROOT / token).exists():
            out.append(f"{b.where}: path does not exist: {token}")

    out.extend(_flag_checks(b))

    # curl/watch URLs must hit a route the server on THAT port declares.
    for port, url_path in re.findall(
            r"https?://(?:127\.0\.0\.1|localhost):(\d+)(/[\w/<>*.-]*)", b.body):
        routes = tables.get(int(port))
        if routes is None:
            continue            # nothing known answers there; do not guess
        url_path = url_path.rstrip("/") or "/"
        if not _route_matches(url_path, routes):
            out.append(
                f"{b.where}: {url_path} is not a route the server on port "
                f"{port} declares. Did the API move?"
            )
    return out


def _flag_checks(b: Block) -> list[str]:
    """Every --flag in the block must be one its command accepts.

    A flag renamed in poc/*.toml breaks the documented command and changes
    nothing else, so nothing else notices.
    """
    out = []
    invocations = (
        [(m, m) for m in re.findall(r"bash ([\w/.-]+\.sh)", b.body)]
        + [(m, m) for m in re.findall(r"uv run python -m ([\w.]+)", b.body)]
    )
    for command, _ in invocations:
        accepted = _accepted_flags(command)
        if accepted is None:
            continue
        # Only the flags on this command's own line, so a block holding several
        # commands does not judge one against another's flag list. Line
        # continuations are joined first.
        joined = re.sub(r"\\\s*\n\s*", " ", b.body)
        for line in joined.splitlines():
            if command not in line:
                continue
            for flag in re.findall(r"(--[\w-]+)", line):
                if flag not in accepted:
                    out.append(
                        f"{b.where}: `{command}` does not accept {flag}"
                    )
    return out


# ── launching ────────────────────────────────────────────────────────────────

_BROWSER_STUB: str | None = None
STUB_MARKER = "cjcheck-browser-stub"


def _browser_stub() -> str:
    """A stand-in browser launcher that talks but opens nothing.

    `BROWSER=true` was the obvious choice and it was wrong: the leak this
    whole script exists to catch came OUT of the browser launcher, so a silent
    launcher suppresses the bug along with the window. Verified -- with
    BROWSER=true the hook passed a deliberately reintroduced copy of it.

    So the stub is deliberately chatty on stdout, the way macOS's osascript is
    when webbrowser hands it fd 1. Nothing opens, and if that line ever reaches
    a shell it becomes `cjcheck-browser-stub:: command not found` and the
    DEATH_PATTERNS catch it. Being a stub also makes the check portable: a
    Linux CI box has no osascript and would otherwise never see this class of
    bug at all.
    """
    global _BROWSER_STUB
    if _BROWSER_STUB and Path(_BROWSER_STUB).exists():
        return _BROWSER_STUB
    fh = tempfile.NamedTemporaryFile("w", suffix=".sh", prefix="cjcheck_browser_",
                                     delete=False)
    fh.write(
        "#!/bin/bash\n"
        "# Stand-in for a browser launcher, installed by\n"
        "# scripts/check_readme_examples.py. Writes to whatever fd 1 it\n"
        "# inherits, exactly as osascript does, and opens nothing.\n"
        f'echo "{STUB_MARKER}: $*"\n'
        "exit 0\n"
    )
    fh.close()
    os.chmod(fh.name, 0o755)
    _BROWSER_STUB = fh.name
    atexit.register(lambda: Path(fh.name).unlink(missing_ok=True))
    return _BROWSER_STUB


def _launch_env() -> dict:
    env = dict(os.environ)
    # See _browser_stub: noisy on purpose, and opens nothing.
    env["BROWSER"] = _browser_stub()
    # Belt and braces for anything that consults it before trading.
    env["SIMULATION"] = "y"
    # Stop a stale AX_* from a developer's shell deciding which backend the
    # example talks to -- the same shadowing poc/backtest.sh unsets.
    for key in ("AX_HOST_PORT", "AX_HOST_ADDRESS", "AX_LAUNCH_MODE", "AX_STATE_FILE"):
        env.pop(key, None)
    return env


def _launch(b: Block) -> list[str]:
    """Start the block, watch it for `timeout` seconds, report how it died.

    Returns [] when it survived (smoke) or exited 0 (run).
    """
    body = b.body
    lowered = body.lower()
    for bad in FORBIDDEN_IN_LAUNCH:
        if bad in lowered:
            return [
                f"{b.where}: marked `{b.mode}` but contains {bad!r}; a launch "
                f"could reach a real broker. Mark it `static` or `skip`."
            ]

    timeout = float(b.opts.get("timeout", 8))

    # The block goes to a FILE, not to `bash -s`. Both channels are needed and
    # they are not the same channel: the script arrives one way, and the blank
    # lines that answer a terminal form arrive on stdin. Piping the script into
    # stdin collapses them, and then bash sits waiting for more commands after
    # the last one -- a command that had finished in a second looked like it
    # had hung for twenty.
    with tempfile.NamedTemporaryFile("w", suffix=".sh", prefix="cjcheck_",
                                     delete=False) as fh:
        fh.write(body + "\n")
        script = fh.name

    proc = subprocess.Popen(
        ["bash", script],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=_launch_env(),
        text=True,
        start_new_session=True,      # so the whole tree can be killed
    )
    try:
        # Empty lines on stdin: a terminal form takes its defaults instead of
        # raising EOFError at the first prompt, which would look like a failure
        # of the example rather than of the way it was run.
        #
        # A broken pipe stops the writing, not the watching. The process may
        # have closed stdin and carried on, and cutting the observation short
        # there would call a command healthy for the one second it took to shut
        # its own stdin.
        deadline = time.monotonic() + timeout
        feeding = True
        last_submit = 0.0
        while time.monotonic() < deadline and proc.poll() is None:
            if feeding:
                try:
                    proc.stdin.write("\n")
                    proc.stdin.flush()
                except (BrokenPipeError, ValueError, OSError):
                    feeding = False
            # A run can show more than one form in sequence (poc/backtest.sh
            # shows two), so keep answering rather than answering once.
            now = time.monotonic()
            if now - last_submit > 1.0:
                if _answer_waiting_form():
                    last_submit = now
            time.sleep(0.25)
    finally:
        os.unlink(script)

    status = proc.poll()
    survived = status is None
    if survived:
        _kill_tree(proc)
    try:
        output = proc.stdout.read() or ""
    except Exception:
        output = ""

    problems = []
    for pattern, why in DEATH_PATTERNS:
        hit = re.search(pattern, output, re.M)
        if hit:
            problems.append(
                f"{b.where}: {why} — matched {hit.group(0)!r}\n"
                + _excerpt(output)
            )
            break

    if b.mode == "run" and status not in (0, None):
        problems.append(
            f"{b.where}: marked `run` but exited {status}\n" + _excerpt(output)
        )
    elif b.mode == "run" and survived:
        problems.append(
            f"{b.where}: marked `run` but had not finished after {timeout:g}s. "
            f"Use `smoke` if it is not meant to terminate."
        )
    elif b.mode == "smoke" and status not in (0, None):
        problems.append(
            f"{b.where}: exited {status} within {timeout:g}s\n" + _excerpt(output)
        )
    return problems


def _answer_waiting_form(port: int = FORM_PORT) -> bool:
    """Submit a form the launched command is waiting on. True if one was there.

    Without this the web renderer is a wall the check cannot get past, and the
    failure that prompted this whole script lives on the far side of it:
    `eval "$(...)"` captures the form process's stdout but does not RUN any of
    it until that process exits, which happens when the form is submitted. A
    launch that only waits therefore never reaches the eval -- verified, the
    hook passed a reintroduced copy of the bug until this existed.

    An empty POST is all it takes: the handler fills every field from its own
    defaults, so there is nothing to scrape and no values for this script to
    get wrong. Measured against the strategy-parameter form, an empty body came
    back as
    `export PARAMS='bb__window_size:20,bb__min_width_pct:0.01,...'`.
    """
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
            pass
    except OSError:
        return False
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}", data=b"", method="POST")
        with urllib.request.urlopen(request, timeout=3):
            return True
    except Exception:
        # A listener that is not the form, or one that went away between the
        # connect and the post. Not this script's business either way.
        return False


def _kill_tree(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass


def _excerpt(output: str, lines: int = 12) -> str:
    tail = output.strip().splitlines()[-lines:]
    return "\n".join("        | " + line for line in tail)


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[3])
    ap.add_argument("--no-smoke", action="store_true",
                    help="static checks only; launch nothing")
    ap.add_argument("--list", action="store_true",
                    help="print every block and how it is checked, then exit")
    args = ap.parse_args()

    no_smoke = args.no_smoke or os.environ.get("CJ_CHECK_NO_SMOKE") == "1"

    blocks, problems = [], []
    for path in COVERED:
        if not (ROOT / path).exists():
            problems.append(f"{path}: covered by this check but missing")
            continue
        found, trouble = collect(path)
        blocks.extend(found)
        problems.extend(trouble)

    if args.list:
        for b in blocks:
            first = next((ln for ln in b.body.splitlines() if ln.strip()), "")
            note = b.opts.get("reason", "")
            print(f"{b.mode:7} {b.where:52} {first[:60]}"
                  + (f"   ({note})" if note else ""))
        print(f"\n{len(blocks)} block(s)")
        return 1 if problems else 0

    entries, tables = _entry_points(), _route_tables()

    for b in blocks:
        if b.mode == "skip":
            continue
        problems.extend(_static_checks(b, entries, tables))

    launched = 0
    if not no_smoke:
        for b in blocks:
            if b.mode not in ("smoke", "run"):
                continue
            launched += 1
            print(f"  launching {b.where} ... ", end="", flush=True)
            trouble = _launch(b)
            print("FAIL" if trouble else "ok")
            problems.extend(trouble)

    checked = sum(1 for b in blocks if b.mode != "skip")
    skipped = sum(1 for b in blocks if b.mode == "skip")
    if problems:
        print(f"\n{len(problems)} problem(s) in the README examples:\n",
              file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("\nThe docs promise these work. Fix the example, or the code it "
              "documents.", file=sys.stderr)
        return 1

    print(f"README examples: {checked} checked ({launched} launched), "
          f"{skipped} skipped, {len(blocks)} total — all good.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
