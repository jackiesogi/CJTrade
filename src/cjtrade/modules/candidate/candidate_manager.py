import logging
import inspect

log = logging.getLogger("cjtrade.modules.candidate.candidate_manager")

class CandidateManager:
    def __init__(self):
        log.debug('Initialize CandidateManger instance')
        self.__track_symbol__ = []
        
    def GetTrackedSymbols(self) -> list:
        __tracked_symbol__ = ['0050', '2330']
        log.debug(f'Get tracked symbols: {__tracked_symbol__}')
        return __tracked_symbol__