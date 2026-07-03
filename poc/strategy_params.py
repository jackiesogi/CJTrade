"""
poc/strategy_params.py
~~~~~~~~~~~~~~~~~~~~~~~
Dynamically build and present a CLI form for the non-fixed parameters of a
chosen strategy, using PARAM_SCHEMA defaults as pre-filled values.

Called from poc/backtest.sh (two-step eval pattern)::

    eval "$(uv run python poc/strategy_params.py \
            --strategy "$STRATEGY" --interval "$INTERVAL")"

Outputs a single shell export line::

    export PARAMS='bb__window_size:20,bb__min_width_pct:0.01,risk__max_position_pct:0.05'

Pass --params with an existing value to pre-fill the form on re-runs.
"""
from __future__ import annotations

import argparse

from cjtrade.pkgs.strategy.parameters.manager import ParameterManager
from cjtrade.pkgs.strategy.parameters.schema import PARAM_SCHEMA
from cjtrade.pkgs.ui.engine import FormEngine


# ---------------------------------------------------------------------------
# TOML builder
# ---------------------------------------------------------------------------

def _field_toml(key: str, schema: dict, default_val) -> str:
    """Return a [[field]] TOML block for a single PARAM_SCHEMA entry."""
    t = schema["type"]
    if t in ("int", "float"):
        form_type = "number"
    elif t == "bool":
        form_type = "checkbox"
    elif t == "str" and schema.get("enum"):
        form_type = "select"
    else:
        form_type = "text"

    label = schema.get("description", key).replace('"', '\\"')

    lines = [
        "[[field]]",
        f'name    = "{key}"',
        f'label   = "{label}"',
        f'type    = "{form_type}"',
    ]

    if default_val is not None:
        if isinstance(default_val, bool):
            lines.append(f'default = {"true" if default_val else "false"}')
        elif isinstance(default_val, str):
            lines.append(f'default = "{default_val}"')
        else:
            lines.append(f"default = {default_val}")

    lines.append("optional = true")

    config: list[str] = []
    if form_type == "number":
        if schema.get("min") is not None:
            config.append(f'min  = {schema["min"]}')
        if schema.get("max") is not None:
            config.append(f'max  = {schema["max"]}')
        if schema.get("step") is not None:
            config.append(f'step = {schema["step"]}')
    elif form_type == "select":
        opts = "[" + ", ".join(f'"{o}"' for o in schema["enum"]) + "]"
        config.append(f"options = {opts}")

    if config:
        lines.append("[field.config]")
        lines.extend(config)

    return "\n".join(lines)


def build_params_toml(
    strategy: str,
    interval: str,
    existing_params: str | None = None,
) -> str:
    """Return a TOML string suitable for FormEngine(toml_str=...)."""
    param_config = ParameterManager.load_params(
        interval=interval, strategy_name=strategy
    )
    defaults = param_config.params

    pre_filled: dict = {}
    if existing_params:
        pre_filled = ParameterManager._parse_string_params(existing_params)

    blocks = [f'title = "{strategy} Parameters"', ""]

    for key, schema in PARAM_SCHEMA.items():
        if schema.get("fixed"):
            continue
        strategies = schema.get("strategies", [])
        if strategy not in strategies and "*" not in strategies:
            continue

        default_val = pre_filled.get(key, defaults.get(key, schema.get("default")))
        blocks.append(_field_toml(key, schema, default_val))
        blocks.append("")

    return "\n".join(blocks)


def _dict_to_params_str(values: dict) -> str:
    """Convert form result dict → 'key:val,key:val' for PARAMS env var."""
    parts = []
    for key, val in values.items():
        if val is None or val == "":
            continue
        parts.append(f"{key}:{val}")
    return ",".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Dynamic strategy parameter form — prints 'export PARAMS=...' to stdout"
    )
    ap.add_argument("--strategy", required=True, help="Strategy class name")
    ap.add_argument(
        "--interval",
        required=True,
        choices=["1m", "5m", "1h", "1d"],
        help="Kbar interval",
    )
    ap.add_argument(
        "--params",
        default=None,
        help="Existing PARAMS string for pre-fill (e.g. 'bb__window_size:20')",
    )
    args = ap.parse_args()

    toml_str = build_params_toml(args.strategy, args.interval, args.params)

    if "[[field]]" not in toml_str:
        print("export PARAMS=''")
    else:
        engine = FormEngine(toml_str=toml_str, renderer="web")
        values = engine.run()
        params_str = _dict_to_params_str(values)
        escaped = params_str.replace("'", "'\\''")
        print(f"export PARAMS='{escaped}'")
