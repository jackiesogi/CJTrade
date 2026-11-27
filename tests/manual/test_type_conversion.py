import logging
import os
import sys
from pathlib import Path

from cjtrade.pkgs.brokers.account_client import *
from cjtrade.pkgs.brokers.sinopac._internal_func import _from_sinopac_product
from cjtrade.pkgs.config.broker_settings import setting
from dotenv import load_dotenv
from shioaji import Shioaji as sj

load_dotenv()

# Suppress verbose logging
logging.getLogger('shioaji').setLevel(logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)

config = {
    'api_key': setting("SINOPAC_API_KEY", "API_KEY"),
    'secret_key': setting("SINOPAC_SECRET_KEY", "SECRET_KEY"),
    'ca_path': setting("SINOPAC_CA_CERT_PATH", "CA_CERT_PATH"),
    'ca_passwd': setting("SINOPAC_CA_PASSWORD", "CA_PASSWORD"),
    'simulation': False  # Use production environment to see actual holdings
}


def test_sinopac_contract_to_cj_product(client: AccountClient):
    sj_contract = client.broker.api.Contracts.Stocks.TSE.TSE2890
    cj_product = _from_sinopac_product(sj_contract)
    print(f"Original Product: {sj_contract}")
    print(f"Converted Product: {cj_product}")
    assert cj_product is not None
    assert cj_product.symbol == "2890"
    assert cj_product.exchange == "TSE"


if __name__ == "__main__":
    client = AccountClient(BrokerType.SINOPAC, **config)
    client.connect()
    test_sinopac_contract_to_cj_product(client)
    client.disconnect()
