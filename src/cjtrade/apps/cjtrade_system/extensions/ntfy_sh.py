import os

import requests
from cjtrade.pkgs.logger import get_logger

log = get_logger("cjtrade_system.ntfy")

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

        log.info("push %s/%s: %d %s", server, topic, req.status_code, req.text)

else:
    def push_to_ntfy_sh(title: str, message: str):
        pass


if __name__ == "__main__":
    from cjtrade.pkgs.logger import setup_logging
    setup_logging()
    push_to_ntfy_sh("New order", "This is a test message.")
