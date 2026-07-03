"""CLI renderer — interactive field-by-field prompts in the terminal."""
from __future__ import annotations

import re
import sys
from typing import Any

from ..base_renderer import FormRenderer
from ..schema import FormField
from ..schema import FormSchema

# ANSI helpers (degrade gracefully when not a tty)
# UI output goes to stderr (stdout is captured by eval "$(...)")
_TTY   = sys.stderr.isatty()
_BOLD  = "\033[1m"   if _TTY else ""
_DIM   = "\033[2m"   if _TTY else ""
_CYAN  = "\033[96m"  if _TTY else ""
_GREEN = "\033[92m"  if _TTY else ""
_RED   = "\033[91m"  if _TTY else ""
_RESET = "\033[0m"   if _TTY else ""

# readline pre-fill support (available on Linux/macOS; silently skipped on Windows)
try:
    import readline as _rl
    _HAS_READLINE = True
except ImportError:
    _HAS_READLINE = False


def _rl_safe(prompt: str) -> str:
    """Wrap ANSI escape sequences with readline's non-printing markers.

    Without this, readline strips the ESC byte (0x1B) from the prompt and
    displays raw ``[96m`` characters instead of colours.
    ``\\001``/``\\002`` tell readline these bytes are invisible so it keeps
    cursor-position accounting correct.
    """
    if not _HAS_READLINE:
        return prompt
    return re.sub(r'(\033\[[0-9;]*m)', r'\001\1\002', prompt)


def _prefill_input(prompt: str, prefill: str) -> str:
    """Write prompt to stderr (so it's visible under eval $(...)), then read from stdin."""
    # Write the prompt to stderr — it won't be captured by $()
    sys.stderr.write(prompt)
    sys.stderr.flush()
    if _HAS_READLINE and prefill:
        _inserted = [False]

        def _startup():
            _rl.insert_text(str(prefill))

        def _pre_input():
            if not _inserted[0]:
                _inserted[0] = True
                _rl.insert_text(str(prefill))
                _rl.redisplay()

        _rl.set_startup_hook(_startup)
        _rl.set_pre_input_hook(_pre_input)
        try:
            return input("")   # empty prompt: already written to stderr
        finally:
            _rl.set_startup_hook(None)
            _rl.set_pre_input_hook(None)
    return input("")   # empty prompt: already written to stderr


def _hr(char: str = "─", width: int = 56) -> str:
    return char * width


class CLIRenderer(FormRenderer):
    """
    Renders each field as a terminal prompt.

    UX contract
    -----------
    - Required fields are marked with a red ``*`` after the label.
    - Hints (placeholder, min, env source) appear on the same line as the label.
    - The default value is pre-filled in the edit buffer — press Enter to accept,
      or start typing / backspace to replace it.
    - For ``select`` fields a numbered menu is shown.
    - For ``checkbox`` fields ``y`` / ``n`` is expected.
    - Ctrl-C raises ``KeyboardInterrupt`` (handled by the engine).
    """

    def render(self, schema: FormSchema) -> dict[str, Any]:
        print(f"\n{_BOLD}{_CYAN}{_hr('═')}{_RESET}", file=sys.stderr)
        print(f"{_BOLD}{_CYAN}  {schema.title}{_RESET}", file=sys.stderr)
        print(f"{_BOLD}{_CYAN}{_hr('═')}{_RESET}", file=sys.stderr)
        print(f"{_DIM}  Ctrl-C to abort.{_RESET}\n", file=sys.stderr)

        results: dict[str, Any] = {}
        for f in schema.fields:
            val = self._prompt_field(f)
            if f.type != "display":
                results[f.name] = val

        print(f"\n{_GREEN}✓ All fields collected.{_RESET}\n", file=sys.stderr)
        return results

    # ------------------------------------------------------------------
    def _prompt_field(self, f: FormField) -> Any:
        default = f.resolved_default()

        # Hard-reset terminal attributes before every field so _DIM from the
        # previous field's hint can never bleed into the next label.
        sys.stderr.write("\033[0m")
        sys.stderr.flush()

        # ── label line ────────────────────────────────────────────────
        required_marker = "" if f.optional else f"{_RED}*{_RESET}"
        hints = self._build_hints(f, default)
        hint_str = f"  {_DIM}{hints}{_RESET}" if hints else ""
        print(f"  {_BOLD}{f.label}{required_marker}{_RESET}{hint_str}", file=sys.stderr)

        # ── dispatch ──────────────────────────────────────────────────
        if f.type == "display":
            return self._render_display(f)
        if f.type == "select":
            return self._prompt_select(f, default)
        if f.type == "multiselect":
            return self._prompt_multiselect(f, default)
        if f.type == "checkbox":
            return self._prompt_checkbox(f, default)
        if f.type == "date":
            return self._prompt_date(f, default)
        return self._prompt_text(f, default)  # text | number | file

    # ------------------------------------------------------------------
    @staticmethod
    def _build_hints(f: FormField, default: Any) -> str:
        parts: list[str] = []
        if f.type == "number":
            if f.eff_min is not None:
                parts.append(f"min={f.eff_min:g}")
            if f.eff_max is not None:
                parts.append(f"max={f.eff_max:g}")
            if f.eff_step is not None:
                parts.append(f"step={f.eff_step:g}")
        if f.type == "date":
            parts.append("YYYY-MM-DD")
        if f.type == "file" and f.eff_filter:
            parts.append(f.eff_filter)
        if f.placeholder and (default is None or str(default) != f.placeholder):
            parts.append(f.placeholder)
        if f.env_in:
            parts.append(f"${{env:{f.env_in}}}")
        return f"({', '.join(parts)})" if parts else ""

    # ------------------------------------------------------------------
    def _prompt_select(self, f: FormField, default: Any) -> Any:
        options = f.eff_options or []
        default_str = str(default) if default is not None else ""
        default_idx: int | None = None
        for i, opt in enumerate(options, 1):
            marker = f" {_GREEN}←{_RESET}" if str(opt) == default_str else ""
            print(f"    {_DIM}{i}){_RESET} {opt}{marker}", file=sys.stderr)
            if str(opt) == default_str:
                default_idx = i

        hint = f"[{default_idx}]" if default_idx else ""
        while True:
            try:
                sys.stderr.write(_rl_safe(f"  {_CYAN}▸ {hint} {_RESET}"))
                sys.stderr.flush()
                raw = input("").strip()
            except EOFError:
                raw = ""
            if raw == "" and default_idx is not None:
                return default_str
            try:
                idx = int(raw)
                if 1 <= idx <= len(options):
                    return options[idx - 1]
            except ValueError:
                if raw in options:
                    return raw
            print(f"  {_DIM}  Enter a number 1–{len(options)}.{_RESET}", file=sys.stderr)

    # ------------------------------------------------------------------
    def _prompt_checkbox(self, f: FormField, default: Any) -> bool:
        default_bool = bool(default) if not isinstance(default, bool) else default
        yn = "Y/n" if default_bool else "y/N"
        while True:
            try:
                sys.stderr.write(_rl_safe(f"  {_CYAN}▸ [{yn}]: {_RESET}"))
                sys.stderr.flush()
                raw = input("").strip().lower()
            except EOFError:
                raw = ""
            if raw == "":
                return default_bool
            if raw in ("y", "yes", "true", "1"):
                return True
            if raw in ("n", "no", "false", "0"):
                return False
            print(f"  {_DIM}  Please enter y or n.{_RESET}", file=sys.stderr)

    # ------------------------------------------------------------------
    def _prompt_multiselect(self, f: FormField, default: Any) -> list[str]:
        options = f.eff_options or []
        selected = {str(o) for o in default} if isinstance(default, list) else set()
        for i, opt in enumerate(options, 1):
            marker = f" {_GREEN}←{_RESET}" if str(opt) in selected else ""
            print(f"    {_DIM}{i}){_RESET} {opt}{marker}", file=sys.stderr)
        print(f"  {_DIM}  Space or comma-separated numbers (e.g. 1 3){_RESET}", file=sys.stderr)
        default_hint = ",".join(
            str(i) for i, o in enumerate(options, 1) if str(o) in selected
        )
        hint = f"[{default_hint}]" if default_hint else ""
        while True:
            try:
                sys.stderr.write(_rl_safe(f"  {_CYAN}▸ {hint} {_RESET}"))
                sys.stderr.flush()
                raw = input("").strip()
            except EOFError:
                raw = ""
            if raw == "" and selected:
                return list(selected)
            if not raw:
                if f.optional:
                    return []
                print(f"  {_DIM}  At least one selection required.{_RESET}", file=sys.stderr)
                continue
            tokens = [t for t in raw.replace(",", " ").split() if t]
            result: list[str] = []
            valid = True
            for token in tokens:
                try:
                    idx = int(token)
                    if 1 <= idx <= len(options):
                        result.append(str(options[idx - 1]))
                    else:
                        print(f"  {_DIM}  {idx} is out of range 1–{len(options)}.{_RESET}", file=sys.stderr)
                        valid = False
                        break
                except ValueError:
                    if str(token) in [str(o) for o in options]:
                        result.append(str(token))
                    else:
                        print(f"  {_DIM}  '{token}' is not a valid option.{_RESET}", file=sys.stderr)
                        valid = False
                        break
            if valid and result:
                return result

    # ------------------------------------------------------------------
    def _prompt_date(self, f: FormField, default: Any) -> str | None:
        import re as _re
        _DATE_RE = _re.compile(r"^\d{4}-\d{2}-\d{2}$")
        entry_text = str(default) if default is not None else ""
        bracket = f"{_DIM}[{entry_text}]{_RESET}" if entry_text else ""
        prompt = f"  {_CYAN}▸ {_RESET}{bracket}{_CYAN}: {_RESET}"
        while True:
            try:
                raw = _prefill_input(prompt, entry_text).strip()
            except EOFError:
                raw = entry_text
            if not raw:
                return default
            if _DATE_RE.match(raw):
                return raw
            print(f"  {_RED}  ✗ Expected YYYY-MM-DD (e.g. 2026-01-15).{_RESET}", file=sys.stderr)

    # ------------------------------------------------------------------
    # Use when you want to display some info without expecting user input.
    def _render_display(self, f: FormField) -> None:
        heading = f.config.get("heading", f.label)
        body = f.config.get("body", "")
        if heading:
            print(f"  {_BOLD}{heading}{_RESET}", file=sys.stderr)
        if body:
            print(f"  {_DIM}{body}{_RESET}", file=sys.stderr)
        print(file=sys.stderr)

    # ------------------------------------------------------------------
    def _prompt_text(self, f: FormField, default: Any) -> Any:
        prefill = str(default) if default is not None else ""

        # Always show the default value in dim brackets before the colon,
        # so it's visible even if readline prefill doesn't work on this system.
        bracket = f"{_DIM}[{prefill}]{_RESET}" if prefill else ""
        prompt = f"  {_CYAN}▸ {_RESET}{bracket}{_CYAN}: {_RESET}"

        while True:
            try:
                raw = _prefill_input(prompt, prefill).strip()
            except EOFError:
                raw = prefill

            if raw == "":
                if not f.optional and default is None:
                    print(f"  {_DIM}  This field is required.{_RESET}", file=sys.stderr)
                    continue
                return default

            if f.type == "number":
                try:
                    val = int(raw) if "." not in raw else float(raw)
                except ValueError:
                    print(f"  {_DIM}  Please enter a valid number.{_RESET}", file=sys.stderr)
                    continue
                if f.eff_min is not None and val < f.eff_min:
                    print(f"  {_DIM}  Minimum value is {f.eff_min:g}.{_RESET}", file=sys.stderr)
                    continue
                if f.eff_max is not None and val > f.eff_max:
                    print(f"  {_DIM}  Maximum value is {f.eff_max:g}.{_RESET}", file=sys.stderr)
                    continue
                return val

            return raw
