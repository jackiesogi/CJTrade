import os

import requests

# os.environ["NTFY_SH_ENABLE"] = "y"

if os.getenv("NTFY_SH_ENABLE", "n").lower() == "y":

    def push_to_ntfy_sh(title: str, message: str):
        topic = os.getenv("NTFY_SH_TOPIC", "CJTrade")
        server = os.getenv("NTFY_SH_SERVER", "https://ntfy.sh")

        req = requests.post(
            f"{server}/{topic}",
            data=message.encode("utf-8"),
            headers={"Title": title, "Tags": "chart_with_upwards_trend"},
        )

        print(req.status_code, req.text)

else:
    def push_to_ntfy_sh(title: str, message: str):
        pass


if __name__ == "__main__":
    push_to_ntfy_sh("New order", "This is a test message.")
