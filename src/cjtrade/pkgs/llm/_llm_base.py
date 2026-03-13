class LLMClientBase:
    def __init__(self, model_name: str, api_key: str = None):
        self.model_name = model_name
        self.api_key = api_key
        self.is_connected = False

    def generate_response(self, prompt: str) -> str:
        return "Response from base LLM client class," \
        "you need to implement this method rather than calling me directly."
