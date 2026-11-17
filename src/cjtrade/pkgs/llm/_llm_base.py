class LLMClientBase:
    """Base class for LLM clients.

    Parameters
    ----------
    model_name : str
        Name of the model to use.
    api_key : str, optional
        API key for the provider.
    """
    def __init__(self, model_name: str, api_key: str = None):
        self.model_name = model_name
        self.api_key = api_key
        self.is_connected = False

    def generate_response(self, prompt: str) -> str:
        """Return a reply to `prompt`; subclasses must override this.

        Parameters
        ----------
        prompt : str
            The full prompt.

        Returns
        -------
        str
            A fixed message saying the method is not implemented.

        Warnings
        --------
        Placeholder: the base class does not call any model.
        """
        return "Response from base LLM client class," \
        "you need to implement this method rather than calling me directly."
