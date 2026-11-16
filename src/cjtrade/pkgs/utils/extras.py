"""Optional dependencies, and the error raised when one is missing.

CJTrade's core (ArenaX, backtesting, the shell, reports) installs with a plain
``pip install cjtrade``. Integrations that pull in a heavy or vendor-specific
SDK are extras in pyproject.toml:

    sinopac   shioaji                    the Sinopac broker
    llm       google-genai, openai       Gemini and Azure OpenAI clients
    news      newsapi-python             the NewsAPI news provider
    all       every extra above

A module that needs one imports it inside a ``try`` and, when it is absent,
raises ``missing_extra(...)`` at the point of use rather than at import time,
so importing the module that holds it never fails.
"""

_INSTALL_HINT = (
    "pip install 'cjtrade[{extra}]'  (or `uv sync --extra {extra}` in a "
    "checkout)"
)


def missing_extra(extra: str, cause: BaseException | None = None) -> ImportError:
    """The ImportError to raise when the ``extra`` optional dependency is absent."""
    detail = f" ({cause})" if cause else ""
    return ImportError(
        f"This feature needs the '{extra}' extra{detail}. Install it with: "
        + _INSTALL_HINT.format(extra=extra)
    )
