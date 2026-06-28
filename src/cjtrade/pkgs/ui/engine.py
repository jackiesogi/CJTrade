"""
FormEngine — ties schema loading, renderer selection, and result handling.

Quick usage
-----------
    from cjtrade.pkgs.ui.engine import FormEngine

    result = FormEngine("my_form.toml", renderer="cli").run()
    # result = {"watch_list": "2330", "fund": 500000, ...}

Renderer strings
----------------
"cli"    — interactive terminal prompts
"zenity" — GTK dialogs via the ``zenity`` binary
"web"    — local HTML form opened in the browser
"auto"   — zenity if available, else cli
"""
from __future__ import annotations

import os
import shutil
import sys
import threading
from pathlib import Path
from typing import Any
from typing import Callable

from .base_renderer import FormRenderer
from .schema import FormSchema
from .user_state import UserState


class FormEngine:
    """
    High-level facade: load schema → pick renderer → collect input → return results.

    Parameters
    ----------
    schema_path:
        Path to the TOML schema file.
    renderer:
        ``"cli"`` | ``"zenity"`` | ``"web"`` | ``"auto"`` | a :class:`FormRenderer` instance.
    web_port:
        Port for the WebRenderer (default 9876).
    """

    def __init__(
        self,
        schema_path: str | Path | None = None,
        toml_str: str | None = None,
        renderer: str | FormRenderer = "auto",
        web_port: int = 9876,
    ) -> None:
       # 必須提供其中一個，而且只能提供一個
        if (schema_path is None) == (toml_str is None):
            raise ValueError(
                "Provide exactly one of schema_path or toml_str."
            )

        if schema_path is not None:
            self.schema = FormSchema.load(schema_path)
            state_name = Path(schema_path).stem
        else:
            self.schema = FormSchema.loads(toml_str)
            state_name = "inline"

        self._renderer = self._resolve(renderer, web_port)
        self._state = UserState(state_name)

        # Build persist_map: {field_name → persist_key} for fields that opt in
        self._persist_map: dict[str, str] = {
            f.name: f.persist_key
            for f in self.schema.fields
            if f.persist_key
        }

    # ------------------------------------------------------------------
    def _inject_persisted_defaults(self) -> None:
        """
        Push state-file values into each field's resolved_default by temporarily
        making the persisted dict available on the field.

        We do this by monkey-patching a ``_persisted`` attribute on each FormField
        so that ``resolved_default(persisted=...)`` can be called by the renderer
        without the renderer needing to know about UserState.

        Renderers call ``field.resolved_default()``; we patch it here to a closure
        that already has the persisted data baked in.
        """
        persisted = self._state.data
        for f in self.schema.fields:
            # Bind persisted data into the field's resolved_default call
            original_resolved = f.resolved_default

            def _patched(p=persisted, _orig=original_resolved):
                return _orig(persisted=p)

            f.resolved_default = _patched  # type: ignore[method-assign]

    # ------------------------------------------------------------------
    def _parse_cli_args(self) -> dict[str, Any]:
        """
        Scan ``sys.argv[1:]`` for any ``cli_arg`` flags registered in the schema.

        Supports:
          - ``--flag value``   (value-bearing flags)
          - ``--flag=value``   (inline assignment)
          - ``--flag``         (bare flag for checkbox fields → True)
        Returns a dict of ``{field_name: coerced_value}`` for every flag found.
        """
        argv = sys.argv[1:]
        overrides: dict[str, Any] = {}
        for f in self.schema.fields:
            if not f.cli_arg:
                continue
            flag = f.cli_arg
            for i, arg in enumerate(argv):
                if arg.startswith(flag + "="):
                    raw = arg[len(flag) + 1:]
                elif arg == flag:
                    # Bare flag with a following non-flag value?
                    next_is_value = (
                        i + 1 < len(argv) and not argv[i + 1].startswith("-")
                    )
                    if f.type == "checkbox":
                        # --compare → True, no value needed
                        overrides[f.name] = True
                        break
                    elif next_is_value:
                        raw = argv[i + 1]
                    else:
                        continue
                else:
                    continue
                try:
                    overrides[f.name] = f.coerce(raw)
                except ValueError:
                    overrides[f.name] = raw
                break
        return overrides

    # ------------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        """
        Present the form, **block** until submitted, persist relevant values,
        and return the result dict.

        Fields whose ``cli_arg`` flag was found in ``sys.argv`` are skipped
        entirely — the renderer never sees them.
        """
        import dataclasses

        self._inject_persisted_defaults()

        cli_overrides = self._parse_cli_args()

        # Build a schema containing only the fields that still need prompting
        if cli_overrides:
            remaining = [f for f in self.schema.fields if f.name not in cli_overrides]
            prompt_schema = dataclasses.replace(self.schema, fields=remaining)
        else:
            prompt_schema = self.schema

        try:
            if prompt_schema.fields:
                result = self._renderer.render(prompt_schema)
            else:
                result = {}
        except KeyboardInterrupt:
            print("\n\n  Cancelled.", file=sys.stderr)
            sys.exit(0)

        # Merge: CLI-provided values win; renderer fills the rest
        merged = {**result, **cli_overrides}

        if self._persist_map:
            self._state.save(merged, self._persist_map)
        #print(merged, file=sys.stderr)
        return merged

    # ------------------------------------------------------------------
    def run_async(
        self,
        callback: Callable[[dict[str, Any]], None],
        *,
        on_cancel: Callable[[], None] | None = None,
        daemon: bool = True,
    ) -> threading.Thread:
        """
        Show the form in a **background thread** and call *callback* when done.

        The calling thread is **never blocked** — it can keep doing work
        (e.g. running a live strategy) while the user fills the form.

        Parameters
        ----------
        callback:
            Called with the result dict once the user submits.
            Runs on the background thread, so keep it thread-safe
            (use a ``threading.Lock`` if you mutate shared state).
        on_cancel:
            Optional callable invoked if the user cancels (Ctrl-C / dialog close).
            If ``None``, cancellation is silently ignored.
        daemon:
            When ``True`` (default) the thread won't prevent the program from
            exiting if the main thread finishes first.

        Returns
        -------
        threading.Thread
            The background thread (already started).
            Call ``.join()`` if you later want to wait for it.

        Example
        -------
        ::

            engine = FormEngine("modify_strategy.toml", renderer="web")

            def apply_changes(result):
                strategy.update_params(result)  # runs on bg thread

            t = engine.run_async(callback=apply_changes)
            # main thread keeps running…
            strategy.run()         # ← not blocked
            t.join()               # ← optionally wait at the end
        """
        def _worker():
            try:
                result = self._renderer.render(self.schema)
            except KeyboardInterrupt:
                if on_cancel:
                    on_cancel()
                return
            callback(result)

        t = threading.Thread(target=_worker, daemon=daemon, name="FormEngine-async")
        t.start()
        return t

    # ------------------------------------------------------------------
    def run_and_export(self) -> dict[str, Any]:
        """
        Like :meth:`run`, but also writes each field's result into the env var
        named by ``field.env_out`` (if set). Useful when the form feeds a shell script.
        """
        results = self.run()
        for f in self.schema.fields:
            if f.env_out and f.name in results and results[f.name] is not None:
                os.environ[f.env_out] = str(results[f.name])
        return results

    # ------------------------------------------------------------------
    def print_exports(self, results: dict[str, Any]) -> None:
        """
        Print ``export VAR=value`` lines for all fields that have an ``env_out`` key.
        Pipe this into a shell ``eval`` to inject values into the calling process.
        """
        for f in self.schema.fields:
            if f.env_out and f.name in results:
                val = results[f.name]
                if val is None:
                    continue
                # Shell-safe quoting for simple values
                escaped = str(val).replace("'", "'\\''")
                print(f"export {f.env_out}='{escaped}'")

    # ------------------------------------------------------------------
    @staticmethod
    def _resolve(renderer: str | FormRenderer, web_port: int) -> FormRenderer:
        if isinstance(renderer, FormRenderer):
            return renderer

        match renderer:
            case "cli":
                from .renderers.cli import CLIRenderer
                return CLIRenderer()
            case "zenity":
                from .renderers.zenity import ZenityRenderer
                return ZenityRenderer()
            case "web":
                from .renderers.web import WebRenderer
                return WebRenderer(port=web_port)
            case "auto":
                if shutil.which("zenity"):
                    from .renderers.zenity import ZenityRenderer
                    return ZenityRenderer()
                from .renderers.cli import CLIRenderer
                return CLIRenderer()
            case _:
                raise ValueError(
                    f"Unknown renderer '{renderer}'. "
                    "Choose from: cli, zenity, web, auto"
                )
