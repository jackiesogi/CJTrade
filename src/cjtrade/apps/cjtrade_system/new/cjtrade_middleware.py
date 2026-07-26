CJD_PORT = 5000
CJD_HOST = "localhost"

class CJT:
    def __init__(self):
        self.host = CJD_HOST
        self.port = CJD_PORT
        self.base_url = f"http://{self.host}:{self.port}"

    def _get(self, endpoint):
        import requests
        url = f"{self.base_url}/{endpoint}"
        response = requests.get(url)
        return response.json()

    def _post(self, endpoint, data):
        import requests
        url = f"{self.base_url}/{endpoint}"
        response = requests.post(url, json=data)
        return response.json()

    def upload_new_strategy(self, strategy_id, strategy_name, strategy_code):
        data = {
            "strategy_id": strategy_id,
            "strategy_name": strategy_name,
            "strategy_code": strategy_code
        }
        return self._post("upload_strategy", data)