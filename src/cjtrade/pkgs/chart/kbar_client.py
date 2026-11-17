from enum import Enum
from typing import Any
from typing import List
from typing import Optional

from cjtrade.pkgs.chart._chart_base import KbarChartBase
from cjtrade.pkgs.chart._plotly import PlotlyKbarChart
from cjtrade.pkgs.chart.models.kbar_data import KbarData
from cjtrade.pkgs.models.product import Product


class KbarChartType(str, Enum):
    """Available chart backends (only plotly)."""
    PLOTLY = "plotly"


class KbarChartClient:
    """Front end that creates a chart backend and forwards calls to it.

    Parameters
    ----------
    chart_type : KbarChartType, default KbarChartType.PLOTLY
        Backend to use.
    auto_save : bool, default True
        Passed to the backend; for plotly, rewrite the HTML file on every update.
    **config
        Extra backend arguments (plotly: ``width``, ``height``).

    Raises
    ------
    ValueError
        If `chart_type` is not supported.

    Warnings
    --------
    With ``auto_save=True`` (the default) the plotly backend writes
    ``kbar_<symbol>_<timestamp>.html`` in the current directory on updates.
    """
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

    # TODO: Decopule with `Product` class
    def set_kbar_data(self, data: List[KbarData], product: Product) -> None:
        """Replace the chart's bars with `data` for `product`.

        Parameters
        ----------
        data : list of KbarData
            Bars in time order.
        product : Product
            The product the bars belong to.

        Warnings
        --------
        With auto-save on, writes the chart's HTML file.
        """
        if self.chart:
            self.chart.set_kbar_data(data, product)

    def set_product(self, product: Product) -> None:
        """Set product without data, useful for live data streams."""
        if self.chart:
            self.chart.set_product(product)

    def append_kbar(self, kbar: KbarData) -> None:
        """Append one bar to the chart.

        Parameters
        ----------
        kbar : KbarData
            The new bar.

        Warnings
        --------
        With auto-save on and a product set, rewrites the chart's HTML file.
        """
        if self.chart:
            self.chart.append_kbar(kbar)

    def render_chart(self) -> Any:
        """Return the backend's figure, or None if there is no chart."""
        if self.chart:
            return self.chart.render_chart()
        return None

    def show_chart(self) -> None:
        """Display the chart through the backend.

        Warnings
        --------
        Plotly writes the HTML file, or opens a browser if no product is set.
        """
        if self.chart:
            self.chart.show_chart()

    def save_chart(self, filename: str) -> None:
        """Save the chart to `filename`.

        Parameters
        ----------
        filename : str
            Output path.

        Warnings
        --------
        Writes a file.
        """
        if self.chart:
            self.chart.save_chart(filename)

    def set_theme(self, theme: str) -> None:
        """Set the colour theme if the backend supports themes.

        Parameters
        ----------
        theme : str
            Theme name (plotly: ``nordic``, ``gruvbox``, ``light``, ``dark``).
        """
        if self.chart and hasattr(self.chart, 'set_theme'):
            self.chart.set_theme(theme)

    def switch_chart_type(self, chart_type: KbarChartType, **new_config) -> None:
        """Replace the backend, carrying over existing bars and product.

        Parameters
        ----------
        chart_type : KbarChartType
            New backend.
        **new_config
            Backend arguments; they replace the previous config.

        Warnings
        --------
        Rarely useful: plotly is the only backend.
        """
        old_data = self.chart.kbar_data if self.chart else []
        old_product = self.chart.product if self.chart else None

        self.chart_type = chart_type
        self.config = new_config
        self._create_chart()

        if old_data and old_product:
            self.set_kbar_data(old_data, old_product)

    # TODO: Currently only support add batch data, need to support streaming update
    def add_indicator(self, name: str, values: List[float], color: str = 'orange', mode: str = 'lines', row: int = 1) -> None:
        """Add an overlay indicator to the current chart.

        `values` should align with current kbar_data length (or will be aligned).

        Parameters
        ----------
        name : str
            Display name.
        values : list of float
            Numeric values, or NaN for missing.
        color : str, default 'orange'
            Line color.
        mode : str, default 'lines'
            Plotly mode (e.g., 'lines').
        row : int, default 1
            Subplot row to attach (1=price, 2=volume).

        Warnings
        --------
        Redraws the whole chart; with auto-save on, rewrites the HTML file.
        """
        if self.chart and hasattr(self.chart, 'indicators'):
            self.chart.indicators.append({'name': name, 'values': values, 'color': color, 'mode': mode, 'row': row})
            # Recreate chart to ensure new trace added
            # TODO: optimize to just add trace without full redraw
            self.chart._create_chart()

    def remove_indicator(self, name: str) -> None:
        """Remove every indicator called `name` and redraw the chart.

        Parameters
        ----------
        name : str
            Indicator display name.

        Warnings
        --------
        With auto-save on, rewrites the HTML file.
        """
        if self.chart and hasattr(self.chart, 'indicators'):
            self.chart.indicators = [i for i in self.chart.indicators if i.get('name') != name]
            # TODO: optimize to just add trace without full redraw
            self.chart._create_chart()

    def get_output_filename(self) -> str:
        """Return the chart's HTML filename, or ``"No file generated"``."""
        if hasattr(self.chart, 'output_filename') and self.chart.output_filename:
            return self.chart.output_filename
        return "No file generated"
