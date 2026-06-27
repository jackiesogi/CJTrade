"""Abstract base class for all form renderers."""
from __future__ import annotations

from abc import ABC
from abc import abstractmethod
from typing import Any

from .schema import FormSchema


class FormRenderer(ABC):
    """
    A FormRenderer takes a :class:`FormSchema` and presents it to the user
    via some UI backend (CLI, Zenity, web, …).

    Implementors must override :meth:`render`.
    The returned dict maps ``field.name → coerced Python value``.
    """

    @abstractmethod
    def render(self, schema: FormSchema) -> dict[str, Any]:
        """
        Show the form and collect user input.

        Returns
        -------
        dict
            ``{field_name: value}`` for every field in *schema*.
            Values are already coerced to the correct Python type via
            :meth:`~schema.FormField.coerce`.

        Raises
        ------
        KeyboardInterrupt
            If the user cancels (renderers should let this propagate).
        RuntimeError
            If a required backend tool (e.g. ``zenity``) is not available.
        """
