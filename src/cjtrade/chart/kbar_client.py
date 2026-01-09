from enum import Enum
from typing import List, Optional, Any

from cjtrade.chart._chart_base import KbarChartBase
from cjtrade.chart._plotly import PlotlyKbarChart
from cjtrade.chart.models.kbar_data import KbarData
from cjtrade.models.product import Product


class KbarChartType(str, Enum):
    PLOTLY = "plotly"


class KbarChartClient:
    def __init__(self, chart_type: KbarChartType = KbarChartType.PLOTLY, auto_save: bool = True, **config):
        self.chart_type = chart_type
        self.auto_save = auto_save
        self.config = config
        self.chart: Optional[KbarChartBase] = None
        self._create_chart()

    def _create_chart(self) -> None:
        if self.chart_type == KbarChartType.PLOTLY:
            self.chart = PlotlyKbarChart(auto_save=self.auto_save, **self.config)
        else:
            raise ValueError(f"Unsupported chart type: {self.chart_type}")

    def set_kbar_data(self, data: List[KbarData], product: Product) -> None:
        if self.chart:
            self.chart.set_kbar_data(data, product)

    def set_product(self, product: Product) -> None:
        """Set product without data, useful for live data streams"""
        if self.chart:
            self.chart.set_product(product)

    def append_kbar(self, kbar: KbarData) -> None:
        if self.chart:
            self.chart.append_kbar(kbar)

    def render_chart(self) -> Any:
        if self.chart:
            return self.chart.render_chart()
        return None

    def show_chart(self) -> None:
        if self.chart:
            self.chart.show_chart()

    def save_chart(self, filename: str) -> None:
        if self.chart:
            self.chart.save_chart(filename)

    def set_theme(self, theme: str) -> None:
        if self.chart and hasattr(self.chart, 'set_theme'):
            self.chart.set_theme(theme)

    def switch_chart_type(self, chart_type: KbarChartType, **new_config) -> None:
        old_data = self.chart.kbar_data if self.chart else []
        old_product = self.chart.product if self.chart else None

        self.chart_type = chart_type
        self.config = new_config
        self._create_chart()

        if old_data and old_product:
            self.set_kbar_data(old_data, old_product)

    def get_output_filename(self) -> str:
        if hasattr(self.chart, 'output_filename') and self.chart.output_filename:
            return self.chart.output_filename
        return "No file generated"