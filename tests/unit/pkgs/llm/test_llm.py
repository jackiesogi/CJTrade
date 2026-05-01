"""Unit tests for cjtrade.pkgs.llm — tests pool logic and client base without real API calls."""
import pytest
from cjtrade.pkgs.llm._llm_base import LLMClientBase
from cjtrade.pkgs.llm.llm_pool import LLMPool


# ── Stub LLM for testing ─────────────────────────────────────────────────────

class StubLLM(LLMClientBase):
    """A test double that returns a canned response or raises."""

    def __init__(self, name: str, response: str = None, error: Exception = None):
        super().__init__(model_name=name, api_key="fake")
        self._response = response
        self._error = error
        self.call_count = 0

    def generate_response(self, prompt: str) -> str:
        self.call_count += 1
        if self._error:
            raise self._error
        return self._response or f"[{self.model_name}] {prompt}"


# ═══════════════════════════════════════════════════════════════════════════════
# LLMClientBase
# ═══════════════════════════════════════════════════════════════════════════════

class TestLLMClientBase:
    def test_init(self):
        base = LLMClientBase(model_name="test-model", api_key="key123")
        assert base.model_name == "test-model"
        assert base.api_key == "key123"
        assert base.is_connected is False

    def test_default_generate_response(self):
        base = LLMClientBase(model_name="test")
        resp = base.generate_response("hello")
        assert "implement" in resp.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# LLMPool
# ═══════════════════════════════════════════════════════════════════════════════

class TestLLMPool:
    def test_single_llm_success(self):
        llm = StubLLM("model-a", response="answer")
        pool = LLMPool([llm])
        result = pool.generate_response("question")
        assert result == "answer"
        assert llm.call_count == 1

    def test_fallback_on_first_failure(self):
        failing = StubLLM("bad", error=RuntimeError("API down"))
        working = StubLLM("good", response="ok")
        pool = LLMPool([failing, working])
        result = pool.generate_response("hello")
        assert result == "ok"
        assert failing.call_count == 1
        assert working.call_count == 1

    def test_wraps_around_pool(self):
        """If all fail except the last, it wraps around."""
        fail1 = StubLLM("a", error=RuntimeError("fail"))
        fail2 = StubLLM("b", error=RuntimeError("fail"))
        good = StubLLM("c", response="success")
        pool = LLMPool([fail1, fail2, good])
        result = pool.generate_response("test")
        assert result == "success"

    def test_get_current_llm(self):
        llm_a = StubLLM("a")
        llm_b = StubLLM("b")
        pool = LLMPool([llm_a, llm_b])
        assert pool.get_current_llm() is llm_a

    def test_get_next_llm(self):
        llm_a = StubLLM("a")
        llm_b = StubLLM("b")
        pool = LLMPool([llm_a, llm_b])
        assert pool.get_next_llm() is llm_b

    def test_empty_pool_raises(self):
        pool = LLMPool([])
        with pytest.raises(Exception, match="No LLMs available"):
            pool.get_current_llm()

    def test_empty_pool_get_next_raises(self):
        pool = LLMPool([])
        with pytest.raises(Exception, match="No LLMs available"):
            pool.get_next_llm()

    def test_fallback_updates_index(self):
        fail1 = StubLLM("a", error=RuntimeError("fail"))
        good = StubLLM("b", response="ok")
        pool = LLMPool([fail1, good])
        pool.generate_response("x")
        # After fallback, current should be 'b'
        assert pool.get_current_llm() is good


# ═══════════════════════════════════════════════════════════════════════════════
# GeminiClient / AzureOpenAIClient / ChatPDFClient — init-only tests
# (We don't call generate_response since that hits real APIs)
# ═══════════════════════════════════════════════════════════════════════════════

class TestGeminiClientInit:
    def test_init(self):
        from cjtrade.pkgs.llm.gemini import GeminiClient
        client = GeminiClient(model_name="gemini-test", api_key="fake_key")
        assert client.model_name == "gemini-test"
        assert client.api_key == "fake_key"
        assert client.client is None  # only created on generate_response


class TestAzureOpenAIClientInit:
    def test_init(self, monkeypatch):
        # Patch AzureOpenAI to avoid real HTTP connection on init
        import cjtrade.pkgs.llm.azure_openai as mod
        monkeypatch.setattr(mod, "AzureOpenAI", lambda **kwargs: None)

        from cjtrade.pkgs.llm.azure_openai import AzureOpenAIClient
        client = AzureOpenAIClient(
            model_name="gpt-4o", api_key="fake",
            deployment="gpt-4o", endpoint="https://fake.openai.azure.com"
        )
        assert client.model_name == "gpt-4o"
        assert client.deployment == "gpt-4o"


class TestChatPDFClientInit:
    def test_init(self):
        from cjtrade.pkgs.llm.chatpdf import ChatPDFClient
        client = ChatPDFClient(api_key="fake_key", pdf_src="src_abc123")
        assert client.api_key == "fake_key"
        assert client.pdf_src == "src_abc123"
        assert client.model_name == "chatpdf"
