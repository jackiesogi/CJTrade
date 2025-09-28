import logging
import shioaji as sj
import os
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
        


class Inventory:
    def __init__(self):
        self.inventory = []  # list of inventory item

    def ToSymbolList(self):
        result = []
        for inv_item in self.inventory:
            result.append(inv_item.symbol)
        return result
    
class AccountAccessObject:
    def __init__(self, keyobj, simulation):
        self.__sj__ = self.Login(keyobj, simulation)


    def Healthcheck(self) -> bool:
        return True


    def Login(self, keyobj, simulation) -> sj.Shioaji:
        # api = sj.Shioaji(simulation=simulation)
        # accounts = api.login(
        #     api_key=keyobj.api_key,
        #     secret_key=keyobj.secret_key
        # )
        # log.info('Login successful')
        # return api
        return None


    def Logout(self) -> bool:
        # self.__sj__.logout()
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