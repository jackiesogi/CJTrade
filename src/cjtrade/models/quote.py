import datetime
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List

from cjtrade.models.order import *


@dataclass
class Quote:
    symbol: str
    price: float
    volume: int
    timestamp: str

# ts=1673620200000000000,
# code='2330',
# exchange='TSE',
# open=507.0,
# high=509.0,
# low=499.0,
# close=500.0,
# tick_type=<TickType.Sell: 'Sell'>,
# change_price=13.5,
# change_rate=2.77,
# change_type=<ChangeType.Up: 'Up'>,
# average_price=502.42,
# volume=48,
# total_volume=77606,
# amount=24000000,
# total_amount=38990557755,
# yesterday_volume=20963.0,
# buy_price=500.0,
# buy_volume=122.0,
# sell_price=501.0,
# sell_volume=1067,
# volume_ratio=3.7
# OCHLV
@dataclass
class Snapshot:
    symbol: str
    exchange: str
    timestamp: datetime.datetime
    open: float
    close: float
    high: float
    low: float
    volume: int
    average_price: float
    action: OrderAction  # Buy/Sell/None
    buy_price: float
    buy_volume: int
    sell_price: float
    sell_volume: int