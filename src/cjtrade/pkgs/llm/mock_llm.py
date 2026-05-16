import time

from ._llm_base import LLMClientBase

class MockLLMClient(LLMClientBase):
    def __init__(self, model_name: str = "", api_key: str = None):
        self.client = None
        super().__init__(model_name=model_name, api_key=api_key)

    def generate_response(self, prompt: str) -> str:
        time.sleep(1)
        response = {"john": "doe", "foo": "bar", "text": f"Hello from MockLLM: {prompt}"}
        return response['text']
