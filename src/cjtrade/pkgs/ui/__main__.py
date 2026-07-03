"""
Allow ``python -m cjtrade.pkgs.ui <form.toml> [--renderer=<name>]`` to be used
as the eval source in shell scripts:

    eval "$(uv run python -m cjtrade.pkgs.ui myform.toml --renderer=web "$@")"
"""
import argparse
import sys

from .engine import FormEngine


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m cjtrade.pkgs.ui",
        description="Run a FormEngine and print shell export lines.",
    )
    parser.add_argument("config", help="Path to the .toml form definition")
    parser.add_argument("--renderer", default="auto", help="Renderer: auto / web / cli / zenity")
    args = parser.parse_args()

    engine = FormEngine(args.config, renderer=args.renderer)
    engine.print_exports(engine.run())


if __name__ == "__main__":
    main()
