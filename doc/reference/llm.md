# LLM clients

Needs the `llm` extra for Gemini and Azure OpenAI.

!!! warning
    `generate_response` calls a remote model: the output is not
    deterministic and each call uses your API quota.

::: cjtrade.pkgs.llm._llm_base.LLMClientBase

::: cjtrade.pkgs.llm.gemini

::: cjtrade.pkgs.llm.azure_openai

::: cjtrade.pkgs.llm.chatpdf

::: cjtrade.pkgs.llm.mock_llm

::: cjtrade.pkgs.llm.llm_pool
