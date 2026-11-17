from abc import ABC
from abc import abstractmethod
from typing import Any
from typing import List
from typing import Optional

from cjtrade.pkgs.chart.models.kbar_data import KbarData
from cjtrade.pkgs.models.product import Product


class KbarChartBase(ABC):
    """Abstract base for K-bar (candlestick) chart backends."""
    def __init__(self):
        self.product: Optional[Product] = None
        self.kbar_data: List[KbarData] = []

    @abstractmethod
    def set_kbar_data(self, data: List[KbarData], product: Product) -> None:
        """Replace the chart's bars with `data` for `product`.

        Parameters
        ----------
        data : list of KbarData
            Bars in time order.
        product : Product
            The product the bars belong to.
        """
        pass

    @abstractmethod
    def append_kbar(self, kbar: KbarData) -> None:
        """Append one bar to the chart.

        Parameters
        ----------
        kbar : KbarData
            The new bar.
        """
        pass

    @abstractmethod
    def render_chart(self) -> Any:
        """Build and return the backend's figure object."""
        pass

    @abstractmethod
    def show_chart(self) -> None:
        """Display the chart."""
        pass

    @abstractmethod
    def save_chart(self, filename: str) -> None:
        """Save the chart to `filename`.

        Parameters
        ----------
        filename : str
            Output path.
        """
        pass
