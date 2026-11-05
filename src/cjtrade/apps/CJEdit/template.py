# TODO: make template management dynamic,
# rather than storing it in one file and mantain manually...

GeneralImport = """\
import os
from cjtrade.pkgs import paths
from cjtrade.pkgs.analytics.fundamental import *
from cjtrade.pkgs.analytics.informational.news_client import *
from cjtrade.pkgs.analytics.technical.models import *
from cjtrade.pkgs.analytics.technical.strategies.fixed_price import *
from cjtrade.pkgs.brokers.account_client import *
from cjtrade.pkgs.chart.kbar_client import KbarChartClient
from cjtrade.pkgs.chart.kbar_client import KbarChartType
from cjtrade.pkgs.config.config_loader import load_supported_config_files
from cjtrade.pkgs.models import *

loaded = load_supported_config_files()

config = {
    'api_key': os.environ["API_KEY"],
    'secret_key': os.environ["SECRET_KEY"],
    'ca_path': os.environ["CA_CERT_PATH"],
    'ca_passwd': os.environ["CA_PASSWORD"],
    'simulation': True if os.environ.get("SIMULATION") == "y" else False,

    'username': os.environ.get('USERNAME', 'user000'),
    'news_source': os.environ.get('NEWS_SOURCE', 'cnyes'),
    'arenax_host': os.environ.get('ARENAX_HOST', 'localhost'),
    'arenax_port': int(os.environ.get('ARENAX_PORT', 8801)),
}

"""

def get_general_import_str(broker, arenax_backend):
    result = GeneralImport
    if broker == "sinopac":
        result += """
config["state_file"] = f"./sinopac_{config['username']}.json"
config["mirror_db_path"] = str(paths.mirror_db_path("sinopac", config["username"]))

######## YOUR STRATEGY STARTS HERE ########
client = AccountClient(BrokerType.SINOPAC, **config)
client.connect()

# start here >>>




client.disconnect()
########  YOUR STRATEGY ENDS HERE  ########
"""
    elif broker == "arenax" and arenax_backend == "demo":
        result += """
config['api_key'] = 'testkey123'
config['arenax_port'] = '8801'

######## YOUR STRATEGY STARTS HERE ########
client = AccountClient(BrokerType.ARENAX, **config)
client.connect()

# start here >>>




client.disconnect()
########  YOUR STRATEGY ENDS HERE  ########
"""
    elif broker == "arenax" and arenax_backend == "backtest":
        result += """
config['api_key'] = 'testkey123'
config['arenax_port'] = '8802'

######## YOUR STRATEGY STARTS HERE ########
client = AccountClient(BrokerType.ARENAX, **config)
client.connect()

# start here >>>




client.disconnect()
########  YOUR STRATEGY ENDS HERE  ########
"""
    elif broker == "arenax" and arenax_backend == "paper":
        result += """
config['api_key'] = 'testkey123'
config['arenax_port'] = '8803'

######## YOUR STRATEGY STARTS HERE ########
client = AccountClient(BrokerType.ARENAX, **config)
client.connect()

# start here >>>




client.disconnect()
########  YOUR STRATEGY ENDS HERE  ########
"""
    return result
