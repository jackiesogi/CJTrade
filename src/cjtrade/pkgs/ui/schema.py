"""
FormField dataclass and FormSchema TOML loader.

TOML DSL spec
-------------
Each ``[[field]]`` block maps directly to a FormField:

    [[field]]
    name             = "fund"          # required – result dict key
    label            = "Initial Fund"  # required – display label
    type             = "number"        # text | number | select | checkbox
    default          = 500000          # hardcoded default
    env_in           = "MY_ENV_VAR"   # env var read as default (beats `default`)
    env_out          = "INITIAL_FUND"  # env var the result is exported into
    placeholder      = "500000"        # hint shown in prompt
    options          = ["a","b","c"]   # select only
    min              = 1000            # number only
    step             = 1000            # number only (hint; not enforced by all renderers)
    optional         = true            # if true, empty input is accepted
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# FormField
# ---------------------------------------------------------------------------

@dataclass
class FormField:
    name: str
    label: str
    type: str  # "text" | "number" | "select" | "checkbox"

    default: Any = None
    env_in: str | None = None            # env var read as default (input direction)
    env_out: str | None = None           # env var the result is exported into (output direction)
    placeholder: str | None = None
    options: list[str] | None = None     # for type="select"
    min: float | None = None             # for type="number"
    step: float | None = None            # for type="number"
    optional: bool = False
    persist_key: str | None = None       # key used in the per-schema state file
    cli_arg: str | None = None           # CLI flag, e.g. "--watch-list" (skips prompt if provided)

    # ------------------------------------------------------------------
    def resolved_default(self, persisted: dict | None = None) -> Any:
        """Effective default — priority: env-var > state-file > TOML default > None."""
        if self.env_in:
            env_val = os.environ.get(self.env_in)
            if env_val is not None:
                return env_val
        if persisted and self.persist_key and self.persist_key in persisted:
            return persisted[self.persist_key]
        return self.default

    # ------------------------------------------------------------------
    def coerce(self, raw: str) -> Any:
        """Convert a raw string from the renderer into the correct Python type."""
        if self.type == "checkbox":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("y", "yes", "true", "1")
        if self.type == "number":
            raw = raw.strip()
            try:
                return int(raw) if "." not in raw else float(raw)
            except ValueError:
                raise ValueError(f"'{raw}' is not a valid number for field '{self.name}'")
        return str(raw)


# ---------------------------------------------------------------------------
# FormSchema
# ---------------------------------------------------------------------------

@dataclass
class FormSchema:
    title: str
    fields: list[FormField]

    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: str | Path) -> "FormSchema":
        """Parse a TOML file into a FormSchema."""
        path = Path(path)
        with open(path, "rb") as fh:
            data = tomllib.load(fh)

        title = data.get("title", path.stem)
        fields = [
            FormField(
                name=fd["name"],
                label=fd["label"],
                type=fd["type"],
                default=fd.get("default"),
                env_in=fd.get("env_in"),
                env_out=fd.get("env_out"),
                placeholder=fd.get("placeholder"),
                options=fd.get("options"),
                min=float(fd["min"]) if "min" in fd else None,
                step=float(fd["step"]) if "step" in fd else None,
                optional=fd.get("optional", False),
                persist_key=fd.get("persist_key"),
                cli_arg=fd.get("cli_arg"),
            )
            for fd in data.get("field", [])
        ]
        return cls(title=title, fields=fields)

    # ------------------------------------------------------------------
    def defaults(self) -> dict[str, Any]:
        """Return a dict of resolved default values for every field."""
        return {f.name: f.resolved_default() for f in self.fields}
