import time

from ._llm_base import LLMClientBase

class MockLLMClient(LLMClientBase):
    """Offline LLM client for tests that echoes the prompt.

    Parameters
    ----------
    model_name : str, default ""
        Name of the model (unused).
    api_key : str, optional
        API key (unused).
    """
    def __init__(self, model_name: str = "", api_key: str = None):
        self.client = None
        super().__init__(model_name=model_name, api_key=api_key)

    def generate_response(self, prompt: str) -> str:
        """Wait one second and return ``"Hello from MockLLM: <prompt>"``.

        Parameters
        ----------
        prompt : str
            The prompt to echo.

        Returns
        -------
        str
            The canned reply.
        """
        time.sleep(1)
        response = {"john": "doe", "foo": "bar", "text": f"Hello from MockLLM: {prompt}"}
        return response['text']
