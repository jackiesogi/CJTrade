"""
FormField dataclass and FormSchema TOML loader.

TOML DSL spec
-------------
Each ``[[field]]`` block maps directly to a FormField.
Type-specific options live in a ``[field.config]`` sub-table:

    [[field]]
    name        = "fund"          # required – result dict key (optional for type="display")
    label       = "Initial Fund"  # required – display label
    type        = "number"        # text | number | select | multiselect | checkbox | date | file | display
    default     = 500000          # hardcoded default
    env_in      = "MY_ENV_VAR"    # env var read as default (beats `default`)
    env_out     = "INITIAL_FUND"  # env var the result is exported into
    placeholder = "500000"        # hint shown in prompt
    optional    = true            # if true, empty input is accepted
    [field.config]
    min      = 1000               # number: lower bound
    max      = 9999               # number: upper bound
    step     = 1000               # number: increment hint
    options  = ["a","b","c"]      # select / multiselect: choices
    filter   = "*.toml"           # file: extension filter hint
    multiple = false              # file: allow selecting multiple files
    heading  = "Title"            # display: heading text
    body     = "Body paragraph"   # display: body / description text
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
    """One field of a form, as declared by a ``[[field]]`` TOML block.

    Parameters
    ----------
    name : str
        Result dict key.
    label : str
        Display label.
    type : str
        text | number | select | multiselect | checkbox | date | file | display.
    default : Any, optional
        Hardcoded default.
    env_in : str, optional
        Env var read as default (beats `default`).
    env_out : str, optional
        Env var the result is exported into.
    placeholder : str, optional
        Hint shown in the prompt.
    optional : bool, optional
        If true, empty input is accepted.
    persist_key : str, optional
        Key used in the per-schema state file.
    cli_arg : str, optional
        CLI flag, e.g. "--watch-list"; the prompt is skipped if it is given.
    config : dict, optional
        Type-specific options from ``[field.config]``.
    """
    name: str
    label: str
    type: str  # "text" | "number" | "select" | "multiselect" | "checkbox" | "date" | "file" | "display"

    default: Any = None
    env_in: str | None = None            # env var read as default (input direction)
    env_out: str | None = None           # env var the result is exported into (output direction)
    placeholder: str | None = None
    optional: bool = False
    persist_key: str | None = None       # key used in the per-schema state file
    cli_arg: str | None = None           # CLI flag, e.g. "--watch-list" (skips prompt if provided)

    # Type-specific options — set via [field.config] in TOML.
    config: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Config accessors (typed convenience wrappers around self.config)
    # ------------------------------------------------------------------
    @property
    def eff_min(self) -> float | None:
        """``config["min"]`` as a float, or None."""
        v = self.config.get("min")
        return float(v) if v is not None else None

    @property
    def eff_max(self) -> float | None:
        """``config["max"]`` as a float, or None."""
        v = self.config.get("max")
        return float(v) if v is not None else None

    @property
    def eff_step(self) -> float | None:
        """``config["step"]`` as a float, or None."""
        v = self.config.get("step")
        return float(v) if v is not None else None

    @property
    def eff_options(self) -> list | None:
        """``config["options"]`` for select / multiselect, or None."""
        return self.config.get("options")

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
        """Effective default — priority: env-var > state-file > TOML default > None.

        Parameters
        ----------
        persisted : dict, optional
            State-file values, keyed by ``persist_key``.

        Returns
        -------
        Any
            For multiselect, a list (comma-separated strings are split).
        """
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
        """Convert a raw value from the renderer into the correct Python type.

        Raises
        ------
        ValueError
            If a number field's value does not parse.
        """
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
    """A whole form: a title and its fields.

    Parameters
    ----------
    title : str
        Form title.
    fields : list of FormField
        Fields in declaration order.
    """
    title: str
    fields: list[FormField]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FormSchema":
        """Build a schema from parsed TOML data.

        Fields without a ``name`` are named ``_display_<index>``; ``title``
        defaults to "Form".

        Raises
        ------
        KeyError
            If a field has no ``type``.
        """
        title = data.get("title", "Form")

        fields = [
            FormField(
                name=fd.get("name", f"_display_{i}"),
                label=fd.get("label", ""),
                type=fd["type"],
                default=fd.get("default"),
                env_in=fd.get("env_in"),
                env_out=fd.get("env_out"),
                placeholder=fd.get("placeholder"),
                optional=fd.get("optional", False),
                persist_key=fd.get("persist_key"),
                cli_arg=fd.get("cli_arg"),
                config=fd.get("config", {}),
            )
            for i, fd in enumerate(data.get("field", []))
        ]

        return cls(title=title, fields=fields)

    @classmethod
    def loads(cls, toml_str: str) -> "FormSchema":
        """Build a schema from a TOML string."""
        return cls.from_dict(tomllib.loads(toml_str))

    @classmethod
    def load(cls, path: str | Path) -> "FormSchema":
        """Build a schema from a TOML file; the title defaults to the file stem."""
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
