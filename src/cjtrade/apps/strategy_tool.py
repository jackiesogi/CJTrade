"""
apps/strategy_tool.py
~~~~~~~~~~~~~~~~~~~~~~
The strategy-authoring API, as a command-line tool, for callers that are not
this Python process.

FinHub is the caller. It deliberately does not depend on cjtrade -- it talks to
the engine and the broker over HTTP and starts them with `uv run` in this
checkout -- so it cannot import user_strategy to validate what someone typed.
This is the same boundary the supervisor already crosses, crossed the same way.

    strategy-tool template --name "My strategy" --symbol 2317
    strategy-tool check < strategy.py
    strategy-tool api

Everything answers one JSON object on stdout. Exit status is 0 whenever the
question was answered, including "this source has eleven errors in it" -- a
non-zero status is reserved for the tool itself failing, so a caller can tell
"your strategy is broken" from "the checker is broken".
"""
from __future__ import annotations

import argparse
import json
import sys

from cjtrade.pkgs.strategy.user_strategy import api_reference
from cjtrade.pkgs.strategy.user_strategy import check
from cjtrade.pkgs.strategy.user_strategy import collect_params
from cjtrade.pkgs.strategy.user_strategy import starter_source


def _read_source(path: str | None) -> str:
    if path:
        with open(path, encoding="utf-8") as handle:
            return handle.read()
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="strategy-tool",
        description="Validate, describe and scaffold CJTrade strategies.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_template = sub.add_parser(
        "template", help="a complete starter strategy, filled in")
    p_template.add_argument("--name", default="My strategy")
    p_template.add_argument("--symbol", default="2317")

    p_check = sub.add_parser(
        "check", help="diagnostics and declared parameters for a source file")
    p_check.add_argument("--file", default=None,
                         help="read from here instead of stdin")

    sub.add_parser("api", help="every name a strategy may use")

    args = parser.parse_args(argv)

    if args.command == "template":
        payload = {"source": starter_source(args.name, args.symbol)}

    elif args.command == "check":
        source = _read_source(args.file)
        diagnostics = [d.to_dict() for d in check(source)]
        # Parameters need the module to run, and a module with errors in it
        # either will not run or will run the wrong way, so they are only
        # collected once the source is known to be sound. An empty list here
        # means "not known", which is why `ok` is reported separately.
        ok = not any(d["severity"] == "error" for d in diagnostics)
        payload = {
            "ok": ok,
            "diagnostics": diagnostics,
            "params": collect_params(source) if ok else [],
        }

    elif args.command == "api":
        payload = {"entries": api_reference()}

    else:                                   # argparse makes this unreachable
        parser.error(f"unknown command {args.command!r}")
        return 2

    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
