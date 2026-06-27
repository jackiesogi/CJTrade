"""
cjtrade.pkgs.ui — TOML-driven universal form system.

Public API
----------
    from cjtrade.pkgs.ui import FormEngine, FormSchema, FormField

    result = FormEngine("my_form.toml", renderer="auto").run()
"""
from .base_renderer import FormRenderer
from .engine import FormEngine
from .schema import FormField
from .schema import FormSchema

__all__ = ["FormEngine", "FormField", "FormSchema", "FormRenderer"]
