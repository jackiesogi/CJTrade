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
    type: str  # "text" | "number" | "select" | "multiselect" | "checkbox" | "date" | "file"
    sublabel: str | None = None              # for type="text" (used by some renderers)

    default: Any = None
    env_in: str | None = None            # env var read as default (input direction)
    env_out: str | None = None           # env var the result is exported into (output direction)
    placeholder: str | None = None
    options: list[str] | None = None     # for type="select" (legacy flat; prefer [field.config])
    min: float | None = None             # for type="number" (legacy flat; prefer [field.config])
    max: float | None = None             # for type="number"
    step: float | None = None            # for type="number" (legacy flat; prefer [field.config])
    optional: bool = False
    persist_key: str | None = None       # key used in the per-schema state file
    cli_arg: str | None = None           # CLI flag, e.g. "--watch-list" (skips prompt if provided)

    # Type-specific options block — mirrors [field.config] in TOML.
    # Config values take precedence over the legacy flat fields above.
    config: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Effective accessors (config block wins over legacy flat fields)
    # ------------------------------------------------------------------
    @property
    def eff_min(self) -> float | None:
        v = self.config.get("min")
        return float(v) if v is not None else self.min

    @property
    def eff_max(self) -> float | None:
        v = self.config.get("max")
        return float(v) if v is not None else self.max

    @property
    def eff_step(self) -> float | None:
        v = self.config.get("step")
        return float(v) if v is not None else self.step

    @property
    def eff_options(self) -> list | None:
        return self.config.get("options", self.options)

    @property
    def eff_filter(self) -> str | None:
        """File filter / glob pattern hint (e.g. ``*.toml``)."""
        return self.config.get("filter")

    @property
    def eff_multiple(self) -> bool:
        """Whether a file picker allows multiple selection."""
        return bool(self.config.get("multiple", False))

    # ------------------------------------------------------------------
    def resolved_default(self, persisted: dict | None = None) -> Any:
        """Effective default — priority: env-var > state-file > TOML default > None."""
        if self.env_in:
            env_val = os.environ.get(self.env_in)
            if env_val is not None:
                if self.type == "multiselect":
                    return [x.strip() for x in env_val.split(",") if x.strip()]
                return env_val
        if persisted and self.persist_key and self.persist_key in persisted:
            return persisted[self.persist_key]
        # Normalise multiselect: TOML arrays are returned as-is;
        # plain strings are treated as comma-separated.
        if self.type == "multiselect" and isinstance(self.default, str):
            return [x.strip() for x in self.default.split(",") if x.strip()]
        return self.default

    # ------------------------------------------------------------------
    def coerce(self, raw: Any) -> Any:
        """Convert a raw value from the renderer into the correct Python type."""
        if self.type == "checkbox":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("y", "yes", "true", "1")
        if self.type == "multiselect":
            if isinstance(raw, list):
                return raw
            # Accept "2330,0050" or "2330 0050"
            return [x.strip() for x in str(raw).replace(",", " ").split() if x.strip()]
        if self.type in ("date", "file"):
            return str(raw)
        if self.type == "number":
            raw = str(raw).strip()
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FormSchema":
        title = data.get("title", "Form")

        fields = [
            FormField(
                name=fd["name"],
                label=fd["label"],
                type=fd["type"],
                sublabel=fd.get("sublabel"),
                default=fd.get("default"),
                env_in=fd.get("env_in"),
                env_out=fd.get("env_out"),
                placeholder=fd.get("placeholder"),
                options=fd.get("options"),
                min=float(fd["min"]) if "min" in fd else None,
                max=float(fd["max"]) if "max" in fd else None,
                step=float(fd["step"]) if "step" in fd else None,
                optional=fd.get("optional", False),
                persist_key=fd.get("persist_key"),
                cli_arg=fd.get("cli_arg"),
                config=fd.get("config", {}),
            )
            for fd in data.get("field", [])
        ]

        return cls(title=title, fields=fields)

    @classmethod
    def loads(cls, toml_str: str) -> "FormSchema":
        return cls.from_dict(tomllib.loads(toml_str))

    @classmethod
    def load(cls, path: str | Path) -> "FormSchema":
        path = Path(path)
        with open(path, "rb") as fh:
            data = tomllib.load(fh)

        schema = cls.from_dict(data)

        if "title" not in data:
            schema.title = path.stem

        return schema

    # ------------------------------------------------------------------
    def defaults(self) -> dict[str, Any]:
        """Return a dict of resolved default values for every field."""
        return {f.name: f.resolved_default() for f in self.fields}
