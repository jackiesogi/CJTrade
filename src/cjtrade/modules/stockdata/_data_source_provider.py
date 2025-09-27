import random
from dataclasses import dataclass

@dataclass
class Snapshot:
    symbol: str
    price: float
    volume: int = 0
    
def GetPriceData(symbol: str):
    s = Snapshot(
        symbol=symbol,
        price=random.randint(1, 100),
        volume=random.randint(1, 10000)
    )
    return s