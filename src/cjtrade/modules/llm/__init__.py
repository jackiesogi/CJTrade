import logging
import random  # for stub
from dataclasses import dataclass
from enum import Enum, auto

log = logging.getLogger("cjtrade.modules.llm")

class LLMBackend(Enum):
    OPENAI = auto()
    LOCAL = auto()
    ANTHROPIC = auto()

# default
DEFAULT_LLM_BACKEND = LLMBackend.OPENAI


@dataclass
class SentimentScore:
    symbol: str             # Company
    sentiment_score: float  # [-1.0, 1.0]
    confidence: float       # Confidence of this analysis
    source: str
    timestamp: str 

class LargeLanguageModel:
    def __init__(self, backend: LLMBackend = DEFAULT_LLM_BACKEND, api_key=''):
        self.backend = backend
        self.api_key = api_key
        return object


    # information is from online platform  -> since it is plain text we need to know the symbol first
    def GetSentimentScore(self, symbol, information) -> float:
        # call LLM process logic (sentiment_score: )
        score = random.uniform(-1.0, 1.0)
        log.debug(f"Processing the sentiment score for online information about '{symbol}': {score}")
        return score


    def GetSymbolFromText(self, text):
        possible_stub_result = ['0050', '2330', '2357', '2454']
        log.debug('Trying to determine the target company of these information is about ...')
        result = possible_stub_result[random.randint(0, 3)]
        log.debug(f"These information are about symbol: {result}")
        return result
