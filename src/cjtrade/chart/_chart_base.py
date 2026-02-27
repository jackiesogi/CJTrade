from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import List
from typing import Optional

from cjtrade.chart.models.kbar_data import KbarData
from cjtrade.models.product import Product


class KbarChartBase(ABC):
    def __init__(self):
        self.product: Optional[Product] = None
        self.kbar_data: List[KbarData] = []

    @abstractmethod
    def set_kbar_data(self, data: List[KbarData], product: Product) -> None:
        pass

    @abstractmethod
    def append_kbar(self, kbar: KbarData) -> None:
        pass

    @abstractmethod
    def render_chart(self) -> Any:
        pass

    @abstractmethod
    def show_chart(self) -> None:
        pass

    @abstractmethod
    def save_chart(self, filename: str) -> None:
        pass
