from cjtrade.pkgs.llm._llm_base import LLMClientBase
from cjtrade.pkgs.utils.extras import missing_extra

try:
    from openai import AzureOpenAI
except ImportError:  # the 'llm' extra is not installed
    AzureOpenAI = None

class AzureOpenAIClient(LLMClientBase):
    """LLM client for Azure OpenAI chat completions.

    Parameters
    ----------
    model_name : str, default "gpt-4o"
        Name of the model.
    api_key : str, optional
        Azure OpenAI API key.
    deployment : str, default "gpt-4o"
        Azure deployment name sent as the request's model.
    endpoint : str, default ""
        Azure OpenAI endpoint URL.

    Raises
    ------
    ImportError
        If the 'llm' extra (``openai``) is not installed.
    """
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
        """Send `prompt` to the Azure deployment and return its text reply.

        A fixed system message ("You're a quant trading assistant.") is
        prepended.

        Parameters
        ----------
        prompt : str
            The user prompt.

        Returns
        -------
        str
            The model's reply.

        Warnings
        --------
        Calls a remote API over the network: output is non-deterministic
        (temperature 1.0) and each call uses paid quota.
        """
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
