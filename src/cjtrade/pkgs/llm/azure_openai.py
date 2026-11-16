from cjtrade.pkgs.llm._llm_base import LLMClientBase
from cjtrade.pkgs.utils.extras import missing_extra

try:
    from openai import AzureOpenAI
except ImportError:  # the 'llm' extra is not installed
    AzureOpenAI = None

class AzureOpenAIClient(LLMClientBase):
    def __init__(self, model_name: str = "gpt-4o", api_key: str = None, deployment: str = "gpt-4o", endpoint: str = ""):
        super().__init__(model_name=model_name, api_key=api_key)
        self.deployment = deployment
        if AzureOpenAI is None:
            raise missing_extra("llm")
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
