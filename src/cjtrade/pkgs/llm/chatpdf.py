import json

import requests

from ._llm_base import LLMClientBase

class ChatPDFClient(LLMClientBase):
    """LLM client that asks questions about a PDF via the ChatPDF API.

    Parameters
    ----------
    model_name : str, default "chatpdf"
        Name of the model.
    api_key : str, optional
        ChatPDF API key.
    pdf_src : str, optional
        ChatPDF source ID of the uploaded PDF.
    """
    def __init__(self, model_name: str = "chatpdf", api_key: str = None, pdf_src: str = None):
        self.client = None
        self.pdf_src = pdf_src
        super().__init__(model_name=model_name, api_key=api_key)

    def generate_response(self, prompt: str) -> str:
        """Send `prompt` about the PDF to ChatPDF and return its reply.

        Parameters
        ----------
        prompt : str
            The user message.

        Returns
        -------
        str
            The ``content`` field of the API response.

        Raises
        ------
        Exception
            If the API returns a non-200 status; the message is the response body.

        Warnings
        --------
        Calls a remote API over the network: output is non-deterministic
        and each call uses API quota.
        """
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json"
        }

        data = {
            "sourceId": self.pdf_src,
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        }

        # print("HEADERS:", headers)
        # print("DATA:", json.dumps(data, indent=2))

        response = requests.post(
            "https://api.chatpdf.com/v1/chats/message",
            headers=headers,
            data=json.dumps(data)
        )

        # print("STATUS:", response.status_code)
        # print("BODY:", response.text)

        if response.status_code != 200:
            raise Exception(response.text)

        return response.json()["content"]
