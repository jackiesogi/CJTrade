"""
UserState — per-schema local persistence.

Reads and writes ``{schema_stem}.json`` in ``cjtrade.pkgs.paths.form_state_dir()``
(formerly ``~/.config/cjtrade/form_state/``).
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

def _state_dir() -> Path:
    """Resolved lazily so CJTRADE_HOME set after import is still honoured.

    Was Path.home()/".config"/"cjtrade"/"form_state", which is the XDG layout
    and therefore wrong on macOS and Windows.
    """
    from cjtrade.pkgs import paths
    return paths.form_state_dir()


class UserState:
    """Thin JSON key-value store scoped to one schema.

    Parameters
    ----------
    schema_stem : str
        Used as the file name — e.g. ``"poc_default"`` →
        ``<form_state_dir>/poc_default.json``.

    Warnings
    --------
    Construction creates the form state directory if missing; an unreadable
    or corrupt state file is treated as empty.
    """

    def __init__(self, schema_stem: str) -> None:
        self._path = _state_dir() / f"{schema_stem}.json"
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
        """Persist values from *results* whose field name appears in *persist_map*.

        None values are not saved.

        Parameters
        ----------
        results : dict
            The dict returned by a renderer (field_name → value).
        persist_map : dict
            ``{field_name: persist_key}`` — built by FormEngine from the schema.

        Warnings
        --------
        Overwrites the state file on disk.
        """
        for field_name, key in persist_map.items():
            if field_name in results and results[field_name] is not None:
                self._data[key] = results[field_name]

        _state_dir().mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    @property
    def data(self) -> dict[str, Any]:
        """The raw persisted key→value dict (read-only view)."""
        return dict(self._data)
