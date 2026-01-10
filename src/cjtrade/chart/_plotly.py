import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List
from datetime import datetime

from cjtrade.chart._chart_base import KbarChartBase
from cjtrade.chart.models.kbar_data import KbarData
from cjtrade.models.product import Product


class PlotlyKbarChart(KbarChartBase):
    def __init__(self, width: int = 1200, height: int = 600, auto_save: bool = True):
        super().__init__()
        self.width = width
        self.height = height
        self.auto_save = auto_save
        self.fig = None
        self.output_filename = None
        self.theme = "nordic"

    def set_theme(self, theme: str) -> None:
        valid_themes = ['nordic', 'light', 'dark']
        if theme not in valid_themes:
            raise ValueError(f"Invalid theme '{theme}'. Valid themes: {valid_themes}")
        self.theme = theme

        if self.fig and hasattr(self, 'kbar_data') and self.kbar_data:
            self._create_chart()

    def _get_theme_config(self) -> dict:
        themes = {
            'nordic': {
                'plot_bgcolor': '#2e3440',
                'paper_bgcolor': '#2e3440',
                'font_color': '#eceff4',
                'grid_color': '#434c5e',
                'candlestick_up': '#bf616a',
                'candlestick_down': '#a3be8c',
                'volume_color': '#5e81ac',
                'modebar': {'bgcolor': 'rgba(0,0,0,0)', 'color': '#eceff4'},
                'config': {
                    'displayModeBar': False,
                    'scrollZoom': True,
                    'doubleClick': 'autosize',
                    'showTips': False,
                    'modeBarButtonsToRemove': ['pan2d', 'select2d', 'lasso2d'],
                    'displaylogo': False
                }
            },
            'light': {
                'plot_bgcolor': 'white',
                'paper_bgcolor': 'white',
                'font_color': 'black',
                'grid_color': '#e6e6e6',
                'candlestick_down': '#26a69a',
                'candlestick_up': '#ef5350',
                'volume_color': 'lightblue',
                'modebar': {'bgcolor': 'rgba(255,255,255,0.8)', 'color': 'black'},
                'config': {
                    'displayModeBar': True,
                    'scrollZoom': True,
                    'doubleClick': 'autosize',
                    'modeBarButtonsToRemove': ['pan2d', 'select2d', 'lasso2d'],
                    'displaylogo': False
                }
            },
            'dark': {
                'plot_bgcolor': 'black',
                'paper_bgcolor': 'black',
                'font_color': 'white',
                'grid_color': '#333333',
                'candlestick_down': '#00ff00',
                'candlestick_up': '#ff0000',
                'volume_color': '#404040',
                'modebar': {'bgcolor': 'rgba(0,0,0,0)', 'color': 'white'},
                'config': {
                    'displayModeBar': False,
                    'scrollZoom': True,
                    'doubleClick': 'autosize',
                    'showTips': False,
                    'modeBarButtonsToRemove': ['pan2d', 'select2d', 'lasso2d'],
                    'displaylogo': False
                }
            }
        }
        return themes.get(self.theme, themes['nordic'])

    def set_kbar_data(self, data: List[KbarData], product: Product) -> None:
        self.kbar_data = data
        self.product = product
        self._generate_filename()
        self._create_chart()

    def set_product(self, product: Product) -> None:
        """Set product and generate filename without needing data"""
        self.product = product
        self._generate_filename()
        # print(f"Chart will be saved to: {self.output_filename}")

    def _generate_filename(self) -> None:
        if self.product:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.output_filename = f"kbar_{self.product.symbol}_{timestamp}.html"

    def append_kbar(self, kbar: KbarData) -> None:
        # Initialize data list if empty
        if not hasattr(self, 'kbar_data') or self.kbar_data is None:
            self.kbar_data = []

        self.kbar_data.append(kbar)

        # Create chart if this is the first data
        if len(self.kbar_data) == 1:
            self._create_chart()
        else:
            self._update_chart_data()

        if self.auto_save and self.output_filename:
            self._auto_save()

    def _auto_save(self) -> None:
        if self.fig and self.output_filename:
            theme_config = self._get_theme_config()
            self.fig.write_html(self.output_filename, config=theme_config['config'])
            print(f"Chart auto-saved to: {self.output_filename}")

    def _create_chart(self) -> None:
        if not self.kbar_data or not self.product:
            return
        theme_config = self._get_theme_config()

        self.fig = make_subplots(
            rows=2, cols=1,
            row_heights=[0.7, 0.3],
            vertical_spacing=0.15,
            subplot_titles=[f"{self.product.symbol} Kbar Chart", "Volume"],
            shared_xaxes=True
        )

        timestamps = [kbar.timestamp for kbar in self.kbar_data]
        opens = [kbar.open for kbar in self.kbar_data]
        highs = [kbar.high for kbar in self.kbar_data]
        lows = [kbar.low for kbar in self.kbar_data]
        closes = [kbar.close for kbar in self.kbar_data]
        volumes = [kbar.volume for kbar in self.kbar_data]

        candlestick = go.Candlestick(
            x=timestamps,
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name="Price",
            increasing_line_color=theme_config['candlestick_up'],
            decreasing_line_color=theme_config['candlestick_down']
        )

        volume_bar = go.Bar(
            x=timestamps,
            y=volumes,
            name="Volume",
            marker_color=theme_config['volume_color']
        )

        self.fig.add_trace(candlestick, row=1, col=1)
        self.fig.add_trace(volume_bar, row=2, col=1)

        self.fig.update_layout(
            width=self.width,
            height=self.height,
            xaxis_rangeslider_visible=False,
            showlegend=False,
            plot_bgcolor=theme_config['plot_bgcolor'],
            paper_bgcolor=theme_config['paper_bgcolor'],
            font_color=theme_config['font_color'],
            modebar=theme_config['modebar']
        )

        # Update axes with natural auto-scaling
        self.fig.update_xaxes(
            gridcolor=theme_config['grid_color'],
            linecolor=theme_config['font_color'],
            rangeslider_visible=False,
            fixedrange=False,
            autorange=True
        )

        # Price chart y-axis (row 1) - let plotly auto-scale naturally
        self.fig.update_yaxes(
            gridcolor=theme_config['grid_color'],
            linecolor=theme_config['font_color'],
            fixedrange=False,
            autorange=True,
            row=1, col=1
        )

        # Volume chart y-axis (row 2) - start from 0, auto-scale max
        self.fig.update_yaxes(
            gridcolor=theme_config['grid_color'],
            linecolor=theme_config['font_color'],
            fixedrange=False,
            autorange=True,
            rangemode='tozero',
            row=2, col=1
        )

        if self.auto_save and self.output_filename:
            self._auto_save()

    def _update_chart_data(self) -> None:
        if not self.fig:
            self._create_chart()
            return

        with self.fig.batch_update():
            timestamps = [kbar.timestamp for kbar in self.kbar_data]
            opens = [kbar.open for kbar in self.kbar_data]
            highs = [kbar.high for kbar in self.kbar_data]
            lows = [kbar.low for kbar in self.kbar_data]
            closes = [kbar.close for kbar in self.kbar_data]
            volumes = [kbar.volume for kbar in self.kbar_data]

            self.fig.data[0].x = timestamps
            self.fig.data[0].open = opens
            self.fig.data[0].high = highs
            self.fig.data[0].low = lows
            self.fig.data[0].close = closes

            self.fig.data[1].x = timestamps
            self.fig.data[1].y = volumes

    def render_chart(self) -> go.Figure:
        if not self.fig:
            self._create_chart()
        return self.fig

    def show_chart(self) -> None:
        if not self.fig:
            self._create_chart()

        theme_config = self._get_theme_config()

        if self.output_filename:
            import os
            abs_path = os.path.abspath(self.output_filename)
            self.fig.write_html(
                abs_path,
                config=theme_config['config']
            )
            print(f"Chart saved to: {abs_path}")
            print(f"Open in browser: file://{abs_path}")
        else:
            # Fallback to old behavior if no filename set
            self.fig.show(config=theme_config['config'])

    def save_chart(self, filename: str) -> None:
        if not self.fig:
            self._create_chart()

        if filename.endswith('.html'):
            self.fig.write_html(filename)
        elif filename.endswith('.png'):
            self.fig.write_image(filename)
        elif filename.endswith('.pdf'):
            self.fig.write_image(filename)
        else:
            self.fig.write_html(f"{filename}.html")

