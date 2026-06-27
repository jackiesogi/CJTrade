"""
UserState — per-schema local persistence.

Reads and writes ``~/.config/cjtrade/form_state/{schema_stem}.json``.
Only fields that declare ``persist_key`` in the TOML are persisted.

Priority reminder (enforced in FormField.resolved_default):
    os.environ[env_in]           ← highest
        state_file[persist_key]
            field.default (TOML)
                None               ← lowest
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_STATE_DIR = Path.home() / ".config" / "cjtrade" / "form_state"


class UserState:
    """
    Thin JSON key-value store scoped to one schema.

    Parameters
    ----------
    schema_stem:
        Used as the file name — e.g. ``"poc_default"`` →
        ``~/.config/cjtrade/form_state/poc_default.json``.
    """

    def __init__(self, schema_stem: str) -> None:
        self._path = _STATE_DIR / f"{schema_stem}.json"
        self._data: dict[str, Any] = self._load()

    # ------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def save(self, results: dict[str, Any], persist_map: dict[str, str]) -> None:
        """
        Persist values from *results* whose field name appears in *persist_map*.

        Parameters
        ----------
        results:
            The dict returned by a renderer (field_name → value).
        persist_map:
            ``{field_name: persist_key}`` — built by FormEngine from the schema.
        """
        for field_name, key in persist_map.items():
            if field_name in results and results[field_name] is not None:
                self._data[key] = results[field_name]

        _STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    @property
    def data(self) -> dict[str, Any]:
        """The raw persisted key→value dict (read-only view)."""
        return dict(self._data)
