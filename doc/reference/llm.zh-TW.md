# LLM 用戶端

Gemini 和 Azure OpenAI 需要安裝 `llm` extra。

!!! warning
    `generate_response` 會呼叫遠端模型：輸出不固定，每次呼叫都會用掉 API 額度。

::: cjtrade.pkgs.llm._llm_base.LLMClientBase

::: cjtrade.pkgs.llm.gemini

::: cjtrade.pkgs.llm.azure_openai

::: cjtrade.pkgs.llm.chatpdf

::: cjtrade.pkgs.llm.mock_llm

::: cjtrade.pkgs.llm.llm_pool
