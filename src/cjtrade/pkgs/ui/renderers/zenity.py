"""Zenity renderer — each field is a GTK dialog via subprocess zenity."""
from __future__ import annotations

import subprocess
import sys
from typing import Any

from ..base_renderer import FormRenderer
from ..schema import FormField
from ..schema import FormSchema


def _zenity(*args: str, **kwargs) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["zenity", *args], capture_output=True, text=True, **kwargs)
    except FileNotFoundError:
        raise RuntimeError(
            "zenity not found. Install with:\n"
            "  Ubuntu/Debian: sudo apt install zenity\n"
            "  Arch:          sudo pacman -S zenity\n"
            "  macOS:         brew install zenity"
        )


class ZenityRenderer(FormRenderer):
    """
    Renders each field as a native GTK dialog using ``zenity``.

    Requires ``zenity`` to be installed on the system.
    If the user closes/cancels any non-optional dialog the process exits.
    """

    def render(self, schema: FormSchema) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for f in schema.fields:
            value = self._render_field(f)
            results[f.name] = value
        return results

    # ------------------------------------------------------------------
    def _render_field(self, f: FormField) -> Any:
        default = f.resolved_default()

        match f.type:
            case "checkbox":
                return self._checkbox(f, default)
            case "select":
                return self._select(f, default)
            case "number":
                return self._number(f, default)
            case _:  # text
                return self._text(f, default)

    # ------------------------------------------------------------------
    def _text(self, f: FormField, default: Any) -> str | None:
        entry_text = str(default) if default is not None else ""
        hint = f.placeholder or entry_text
        result = _zenity(
            "--entry",
            f"--title={f.label}",
            f"--text={f.label}" + (f"\n({hint})" if hint and hint != entry_text else ""),
            f"--entry-text={entry_text}",
        )
        if result.returncode != 0:
            if f.optional:
                return default
            sys.exit(0)
        val = result.stdout.strip()
        return val if val else default

    # ------------------------------------------------------------------
    def _number(self, f: FormField, default: Any) -> int | float | None:
        entry_text = str(default) if default is not None else ""
        hints = []
        if f.min is not None:
            hints.append(f"min={f.min:g}")
        if f.step is not None:
            hints.append(f"step={f.step:g}")
        label_text = f.label + (f"\n({', '.join(hints)})" if hints else "")

        while True:
            result = _zenity(
                "--entry",
                f"--title={f.label}",
                f"--text={label_text}",
                f"--entry-text={entry_text}",
            )
            if result.returncode != 0:
                if f.optional:
                    return default
                sys.exit(0)
            raw = result.stdout.strip()
            if not raw:
                return default
            try:
                val = int(raw) if "." not in raw else float(raw)
                if f.min is not None and val < f.min:
                    _zenity("--error", f"--text=Minimum value is {f.min:g}.")
                    continue
                return val
            except ValueError:
                _zenity("--error", f"--text='{raw}' is not a valid number.")

    # ------------------------------------------------------------------
    def _select(self, f: FormField, default: Any) -> str:
        options = f.options or []
        default_str = str(default) if default is not None else ""
        result = _zenity(
            "--list",
            "--column=Option",
            f"--title={f.label}",
            f"--text=Choose {f.label}:",
            *options,
        )
        if result.returncode != 0:
            return default_str
        val = result.stdout.strip()
        return val if val in options else default_str

    # ------------------------------------------------------------------
    def _checkbox(self, f: FormField, default: Any) -> bool:
        default_bool = bool(default) if not isinstance(default, bool) else default
        result = _zenity(
            "--question",
            f"--title={f.label}",
            f"--text={f.label}",
            *(["--default-cancel"] if not default_bool else []),
        )
        return result.returncode == 0
