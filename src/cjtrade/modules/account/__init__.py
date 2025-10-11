import cjtrade.modules.account.access as AC
from dataclasses import dataclass
# import cjtrade.modules.account.access

@dataclass
class KeyObject:
    api_key: str
    secret_key: str
    ca_path: str
    ca_password: str

def AccountAccess(keyobj, simulation):
    return AC.AccountAccessObject(keyobj, simulation)