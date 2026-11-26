"""The strategy checker, which lives in the CJTrade checkout.

FinHub does not depend on cjtrade -- it talks to the engine and the broker over
HTTP and starts them with `uv run` -- so validating what somebody typed is a
subprocess in that checkout, the same way starting a run is. See
clients/__init__.py for why that boundary exists and
cjtrade/apps/strategy_tool.py for the other side of it.

Three questions, one process each:

    template(name, symbol)  -> a complete starter strategy
    check(source)           -> diagnostics, and the parameters it declares
    api_reference()         -> every name a strategy may use

A check costs about a second, nearly all of it importing TA-Lib, which is why
the editor validates on save and on demand rather than on every keystroke. The
API reference is identical until the checkout changes, so it is read once and
kept.
"""
from __future__ import annotations

import json
import subprocess
import sys
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from cjtrade.pkgs.logger import get_logger

log = get_logger("FinHub.strategy")

# Long enough for a cold `uv run` -- the first call after a checkout changes
# can resolve the environment -- and short enough that a hung subprocess does
# not hold a request open until the browser gives up.
TIMEOUT_S = 45.0

# A strategy nobody can save is better than a request that never returns, so
# the source is bounded before it ever reaches a subprocess. Generous: the
# starter template is about 2 KB.
MAX_SOURCE_BYTES = 256 * 1024


class StrategyToolError(Exception):
    """The checker could not be run, or did not answer.

    Distinct from "the source has errors in it", which is a successful answer.
    strategy-tool exits 0 for that on purpose.
    """


class StrategyTool:
    def __init__(self, python: str = sys.executable):
        self.python = python
        self._api_cache: Optional[List[dict]] = None
        self._templates_cache: Optional[List[dict]] = None

    # -- questions --------------------------------------------------------

    def template(self, name: str, symbol: str, kind: str = "bb") -> str:
        payload = self._run(["template", "--kind", kind,
                             "--name", name, "--symbol", symbol])
        return payload.get("source", "")

    def templates(self) -> List[dict]:
        """Which starter strategies there are. Cached like the API reference:
        identical until the checkout changes."""
        if self._templates_cache is None:
            self._templates_cache = self._run(["templates"]).get("templates", [])
        return self._templates_cache

    def check(self, source: str) -> Dict[str, Any]:
        """Returns {"ok": bool, "diagnostics": [...], "params": [...]}."""
        encoded = source.encode("utf-8")
        if len(encoded) > MAX_SOURCE_BYTES:
            return {
                "ok": False,
                "diagnostics": [{
                    "message": (f"this file is {len(encoded) // 1024} KB; the "
                                f"limit is {MAX_SOURCE_BYTES // 1024} KB"),
                    "line": 1, "offset": 1, "severity": "error",
                }],
                "params": [],
            }
        return self._run(["check"], stdin=encoded)

    def api_reference(self) -> List[dict]:
        if self._api_cache is None:
            self._api_cache = self._run(["api"]).get("entries", [])
        return self._api_cache

    def forget_api(self) -> None:
        """Drop the cached answers, for when the checkout has changed."""
        self._api_cache = None
        self._templates_cache = None

    # -- plumbing ---------------------------------------------------------

    def _run(self, args: List[str], stdin: bytes = b"") -> Dict[str, Any]:
        argv = [self.python, "-m", "cjtrade.apps.strategy_tool", *args]
        try:
            proc = subprocess.run(
                argv, input=stdin, capture_output=True,
                timeout=TIMEOUT_S, check=False)
        except FileNotFoundError as exc:
            raise StrategyToolError(
                f"cannot run {self.python!r}") from exc
        except subprocess.TimeoutExpired as exc:
            raise StrategyToolError(
                f"the strategy checker did not answer within "
                f"{TIMEOUT_S:.0f}s") from exc

        if proc.returncode != 0:
            # strategy-tool answers 0 even for a source full of errors, so a
            # non-zero status means the tool itself failed: a broken checkout,
            # a missing dependency, an import error in cjtrade.
            detail = (proc.stderr or b"").decode("utf-8", "replace").strip()
            log.error("strategy-tool %s exited %d: %s", args[0],
                      proc.returncode, detail[-2000:])
            raise StrategyToolError(
                f"the strategy checker failed: "
                f"{detail.splitlines()[-1] if detail else 'no output'}")

        try:
            return json.loads(proc.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StrategyToolError(
                "the strategy checker answered something that was not "
                "JSON") from exc
