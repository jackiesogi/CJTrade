try:
    from google import genai
except ImportError:  # the 'llm' extra is not installed
    genai = None

from cjtrade.pkgs.utils.extras import missing_extra

from ._llm_base import LLMClientBase

class GeminiClient(LLMClientBase):
    """LLM client for Google Gemini (``google-genai``).

    Parameters
    ----------
    model_name : str, default "gemini-3-flash-preview"
        Gemini model name.
    api_key : str, optional
        Gemini API key.
    """
    def __init__(self, model_name: str = "gemini-3-flash-preview", api_key: str = None):
        self.client = None
        super().__init__(model_name=model_name, api_key=api_key)

    def generate_response(self, prompt: str) -> str:
        """Send `prompt` to Gemini and return its text reply.

        Parameters
        ----------
        prompt : str
            The full prompt.

        Returns
        -------
        str
            The model's reply.

        Raises
        ------
        ImportError
            If the 'llm' extra (``google-genai``) is not installed.

        Warnings
        --------
        Calls a remote API over the network: output is non-deterministic
        and each call uses paid quota.
        """
        if genai is None:
            raise missing_extra("llm")
        self.client = genai.Client(api_key=self.api_key)
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
        )
        return response.text
