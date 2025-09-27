import logging
from dataclasses import dataclass

log = logging.getLogger("cjtrade.modules.account.access")

@dataclass
class InventoryItem:
    symbol: str
    volume: int
    avg_price: float

    def __init__(self, symbol: str, avg_price: float, volume: int):
        self.symbol = symbol
        self.volume = 100
        self.avg_price = avg_price


@dataclass
class Inventory:
    inventory: list

class AccountAccess:
    def __init__(self):
        pass
    

    def Login(self) -> bool:
        log.info('Login successful')
        return True


    def Logout(self) -> bool:
        log.info('Logout successful')
        return True
    

    def FetchInventory(self) -> list:
        log.info('Fetching account inventory ...')
        inv_1 = InventoryItem("0050", 50.74, 1000)
        inv_2 = InventoryItem("2330", 784.12, 1000)
        inventory = []
        inventory.append(inv_1)
        inventory.append(inv_2)
        return inventory