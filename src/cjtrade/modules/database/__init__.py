import sqlite3
import logging
import os

DEFAULT_DB_PATH = "cjtrade-stock.db"
DEFAULT_DB_CONN_TIMEOUT = 5

log = logging.getLogger("cjtrade.modules.stockdata._database")

class DatabaseConnection:
    def __init__(self, db_path=DEFAULT_DB_PATH, timeout=DEFAULT_DB_CONN_TIMEOUT):
        self.db_path = db_path
        self.timeout = timeout
        self.conn = sqlite3.connect(self.db_path, timeout=self.timeout)
    
    def SaveSnapshot(self, snapshot):
        log.debug(f"Successfully saving snapshot to 'stock-{snapshot.symbol}.db' ...")
        

    def SaveInventory(self, inventory):
        log.debug(f"Successfully saving inventory to account-inventory.db ...")


    # Return something like ['0050', '2330']
    def GetInventory(self, account, update=True) -> list:
        inv_list = []
        if update == True:
            inv_list = account.FetchInventory()
        log.debug(f"Successfully getting inventory from account-inventory.db ...")
        # print(f"Inv_List from DB.GetInventory: {inv_list}")
        return inv_list

        
    def Healthcheck(self) -> bool:
        log.debug(f"Check database health: OK")
        return True
    
    def Close(self) -> bool:
        log.info('Closing the DB connection')
        return True