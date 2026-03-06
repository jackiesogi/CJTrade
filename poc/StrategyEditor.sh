############################################################################
#                                                                          #
#     CJ Strategy Editor PoC using zenity for GUI                          #
#     (consider using wxWidgets / electron for a more robust solution)     #
#                                                                          #
############################################################################
#!/bin/bash

zenity() {
    command zenity --width=1000 --height=600 "$@"
}

# launch a simple window that has a "load config" button which opens a file selector
config_path=$(zenity --file-selection --title="Select a configuration file")
echo "Selected config file: $config_path"

# cjtrade system should consume a config object that will define its behavior
#   pass

# use zenity to run a multi-line text editor
user_script="$(zenity --text-info --title="Edit Strategy" --editable)"
echo "User script content:"
echo "$user_script"

#### Example of user_script content:
# closes = market.get_kbars(product=Product("0050"), start="2023-01-01", end="2023-12-31", interval="1d")
# closes = np.array([kbar.close for kbar in closes], dtype=float)  # sys
# print("SMA:", ta.sma(closes, timeperiod=3))
# print("EMA:", ta.ema(closes, timeperiod=3))

ts=$(date +%s)

# write sys part to .cj file first
echo "import numpy as np
from cjtrade.analytics.technical import ta
from cjtrade.brokers.mock.mock_broker_api import MockBrokerAPI
from cjtrade.models.product import Product
# market.ohlcv() -> what API an user may want to use
market = MockBrokerAPI()        # sys or adv
market.connect()                # sys or adv" > ./data/${ts}_strategy.cj

echo "$user_script" >> ./data/${ts}_strategy.cj   # <-- .cj is basically a .py file

echo "market.disconnect()             # sys
exit(0)" >> ./data/${ts}_strategy.cj

if [ -z "$user_script" ]; then
    echo "No script entered. Exiting."
    rm -f ./data/${ts}_strategy.cj
    exit 1
fi

output="$(uv run python ./data/${ts}_strategy.cj)"
echo "$output" > /tmp/cj.log

zenity --text-info --title="Script Output" --width=800 --height=400 --filename=/tmp/cj.log
