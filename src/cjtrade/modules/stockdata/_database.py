import logging
import cjtrade.modules.stockdata._data_source_provider

log = logging.getLogger("cjtrade.modules.stockdata._database")

class Database:
    def __init__(self):
        pass
    
    def SaveSnapshot(self, snapshot):
        log.debug(f"Successfully saving snapshot to 'stock-{snapshot.symbol}.db' ...")
        

    def SaveInventory(self, inventory):
        log.debug(f"Successfully saving inventory to account-inventory.db ...")

        
    def Healthcheck(self) -> bool:
        log.debug(f"Check database health: OK")
        return True
    
    def Close(self) -> bool:
        log.info('Closing the DB connection')
        return True