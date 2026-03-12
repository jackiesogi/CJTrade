from cjtrade.llm._llm_base import LLMClientBase
from openai import AzureOpenAI

class AzureOpenAIClient(LLMClientBase):
    def __init__(self, model_name: str = "gpt-4o", api_key: str = None, deployment: str = "gpt-4o", endpoint: str = ""):
        super().__init__(model_name=model_name, api_key=api_key)
        self.deployment = deployment
        self.client = AzureOpenAI(
            api_version="2024-12-01-preview",
            azure_endpoint=endpoint,
            api_key=self.api_key,
        )

    def generate_response(self, prompt: str) -> str:
        response = self.client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": "You're a quant trading assistant.",
                },
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
            max_tokens=4096,
            temperature=1.0,
            top_p=1.0,
            model=self.deployment
        )
        return response.choices[0].message.content
