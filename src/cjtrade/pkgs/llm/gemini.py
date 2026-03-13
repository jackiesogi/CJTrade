from google import genai

from ._llm_base import LLMClientBase

class GeminiClient(LLMClientBase):
    def __init__(self, model_name: str = "gemini-3-flash-preview", api_key: str = None):
        self.client = None
        super().__init__(model_name=model_name, api_key=api_key)

    def generate_response(self, prompt: str) -> str:
        self.client = genai.Client(api_key=self.api_key)
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )
        return response.text
