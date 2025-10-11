import logging
import time
from urllib import response
import ollama
import random  # for stub
from dataclasses import dataclass
from enum import Enum, auto

log = logging.getLogger("cjtrade.modules.llm")

class LLMBackend(Enum):
    OPENAI = auto()
    LOCAL = auto()
    ANTHROPIC = auto()
    OLLAMA = "llama3.1:8b"  # specify the model here

# default
DEFAULT_LLM_BACKEND = LLMBackend.LOCAL


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

    # TODO: Implement actual LLM call and delete this stub
    def pseudo_LLM_endpoint(self, prompt: str) -> str:
        sleep_time = random.randint(1, 3)
        time.sleep(sleep_time)
        responses = [
            "The stock is expected to rise due to strong earnings.",
            "Market conditions are uncertain; exercise caution.",
            "Positive sentiment around the company's new product launch."
        ]
        result = responses[random.randint(0, 2)]
        return result
    
    def ollama_LLM_endpoint(self, prompt: str) -> str:
        response = ollama.chat(
            model="llama3.1:8b",
            messages=[
                {"role": "user", "content": prompt},
            ]
        )
        return response["message"]["content"]

    
    def SendLLMEndpoint(self, prompt: str) -> str:
        return self.ollama_LLM_endpoint(prompt)


    # General Purpose LLM call
    def SendPrompt(self, prompt: str) -> str:
        # call LLM process logic
        result = self.SendLLMEndpoint(prompt) 
        log.debug(f"LLM response for prompt '{prompt}': {result}")
        return str(result)


    # CJTrade-Specific LLM call
    # information is from online platform  -> since it is plain text we need to know the symbol first
    def GetSentimentScore(self, symbol, information) -> map:
        # call LLM process logic (sentiment_score: )
        score = random.uniform(-1.0, 1.0)
        prompt = f"Analyze the sentiment of the following information about {symbol}: {information}"
        result = self.SendPrompt(prompt)
        log.debug(f"Processing the sentiment score for online information about '{symbol}': {score}")
        return map(score, confidence:=random.uniform(0.5, 1.0))


    def GetSymbolFromText(self, text):
        possible_stub_result = ['0050', '2330', '2357', '2454']
        log.debug('Trying to determine the target company of these information is about ...')
        result = possible_stub_result[random.randint(0, 3)]
        log.debug(f"These information are about symbol: {result}")
        return result
