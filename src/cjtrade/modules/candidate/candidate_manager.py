import logging
import inspect
import cjtrade.modules.news as NEWS

log = logging.getLogger("cjtrade.modules.candidate.candidate_manager")

class CandidateManager:
    def __init__(self, account):
        log.debug('Initialize CandidateManger instance')
        self.__track_symbols__ = []  # track_symbols = inventory + high_interest + low_interest
        self.__cand_interest_low__ = []
        self.__cand_interest_high__ = []
        self.__account__ = account

    def GetTrackedSymbols(self, database, cached=True) -> dict:
        # __tracked_symbols__ = ['0050', '2330']
        inventory = database.GetInventory(self.__account__)  # 要注意一下 db.GetInventory 是回傳 list of InventoryItem
        symbol_list = []
        for inv in inventory:
            symbol_list.append(inv.symbol)
            
        __tracked_symbols__ = {
            "inventory": symbol_list,
            "high": self.FetchHighInterested(),
            "low": self.FetchLowInterested()
        }
        log.debug(f'Get tracked symbols: {__tracked_symbols__}')
        return __tracked_symbols__  # Caller 邏輯好像把它用 for each 當 list 來迭代 檢查一下


    def FetchHighInterested(self):
        # Call `news` module for info gathering and `llm` module for analyzing online information
        # And the randomly-picked symbols that is verified to be healthy stock by `analysis` module
        return NEWS.GetHighInterested()


    def FetchLowInterested(self):
        return NEWS.GetLowInterested()


    # Should only call by `ui` module i.e. {gui|cli|web}.
    def AddManualHighInterested(self):
        pass


    # Should only call by `ui` module i.e. {gui|cli|web}.
    def AddManualLowInterested(self):
        pass
    