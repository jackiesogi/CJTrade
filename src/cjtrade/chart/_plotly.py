import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List
from datetime import datetime

from cjtrade.chart._chart_base import KbarChartBase
from cjtrade.chart.models.kbar_data import KbarData
from cjtrade.models.product import Product

# Theme configurations moved outside the class
CHART_THEMES = {
    'nordic': {
        'plot_bgcolor': '#2e3440',
        'paper_bgcolor': '#2e3440',
        'font_color': '#eceff4',
        'grid_color': '#434c5e',
        'candlestick_up': '#bf616a',      # Red for up
        'candlestick_down': '#a3be8c',    # Green for down
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
    'gruvbox': {
        'plot_bgcolor': '#282828',        # Gruvbox dark background
        'paper_bgcolor': '#282828',       # Gruvbox dark background
        'font_color': '#ebdbb2',          # Gruvbox light foreground
        'grid_color': '#504945',          # Gruvbox gray
        'candlestick_up': '#fb4934',      # Red for up (Gruvbox bright red)
        'candlestick_down': '#b8bb26',    # Green for down (Gruvbox bright green)
        'volume_color': '#83a598',        # Gruvbox bright blue
        'modebar': {'bgcolor': 'rgba(0,0,0,0)', 'color': '#ebdbb2'},
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
        'candlestick_up': '#ef5350',      # Red for up
        'candlestick_down': '#26a69a',    # Green for down
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
        'plot_bgcolor': '#0d1117',        # GitHub dark background
        'paper_bgcolor': '#0d1117',       # GitHub dark background
        'font_color': '#f0f6fc',          # GitHub dark text
        'grid_color': '#21262d',          # GitHub dark border
        'candlestick_up': '#f85149',      # Red for up (GitHub red)
        'candlestick_down': '#56d364',    # Green for down (GitHub green)
        'volume_color': '#58a6ff',        # GitHub blue
        'modebar': {'bgcolor': 'rgba(0,0,0,0)', 'color': '#f0f6fc'},
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
        valid_themes = list(CHART_THEMES.keys())
        if theme not in valid_themes:
            raise ValueError(f"Invalid theme '{theme}'. Valid themes: {valid_themes}")
        self.theme = theme

        if self.fig and hasattr(self, 'kbar_data') and self.kbar_data:
            self._create_chart()

    def _get_theme_config(self) -> dict:
        return CHART_THEMES.get(self.theme, CHART_THEMES['nordic'])

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
        print(f"ts: {kbar.timestamp}, open: {kbar.open}, high: {kbar.high}, low: {kbar.low}, close: {kbar.close}, volume: {kbar.volume}")

        # Create chart if this is the first data
        if len(self.kbar_data) == 1:
            self._create_chart()
        else:
            self._update_chart_data()

        if self.auto_save and self.output_filename:
            self._auto_save()

    def _save_html_with_template(self, filename: str) -> None:
        if not self.fig:
            return

        import os
        import plotly.io as pio

        theme_config = self._get_theme_config()

        # Generate HTML div for the chart
        html_content = pio.to_html(
            self.fig,
            config=theme_config['config'],
            div_id="plotly-div",
            include_plotlyjs=True,
            full_html=False
        )

        # Read template HTML
        template_path = os.path.join(os.path.dirname(__file__), 'templates', 'chart_template.html')
        with open(template_path, 'r', encoding='utf-8') as f:
            template = f.read()

        def calculate_nav_bgcolor(paper_bg):
            if paper_bg == '#0d1117':  # GitHub dark
                return '#161b22'
            elif paper_bg == '#2e3440':  # Nordic
                return '#3b4252'
            elif paper_bg == '#282828':  # Gruvbox
                return '#32302f'
            elif paper_bg == 'white':  # Light
                return '#f8f9fa'
            else:  # Fallback
                return paper_bg

        nav_bgcolor = calculate_nav_bgcolor(theme_config['paper_bgcolor'])
        accent_color = '#58a6ff' if theme_config['paper_bgcolor'] == '#0d1117' else '#3498db'
        border_color = '#30363d' if theme_config['paper_bgcolor'] == '#0d1117' else '#34495e'

        if accent_color == '#58a6ff':
            accent_color_rgb = '88, 166, 255'
        else:
            accent_color_rgb = '52, 152, 219'

        # Auto refresh meta tag
        extra_head = '<meta http-equiv="refresh" content="2">' if self.auto_save else ''

        full_html = template.format(
            paper_bgcolor=theme_config['paper_bgcolor'],
            font_color=theme_config['font_color'],
            nav_bgcolor=nav_bgcolor,
            accent_color=accent_color,
            accent_color_rgb=accent_color_rgb,
            border_color=border_color,
            chart_width=self.width,
            chart_height=self.height,
            chart_content=html_content,
            theme_name=self.theme,
            extra_head=extra_head
        )

        # Handle absolute path or relative path
        if not os.path.isabs(filename):
             filename = os.path.abspath(filename)

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(full_html)

        # TODO: Temporarily disable print statements
        # print(f"Chart saved to: {filename}")
        # print(f"Open in browser: file://{filename}")

    def _auto_save(self) -> None:
        if self.fig and self.output_filename:
            self._save_html_with_template(self.output_filename)

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

        # Create continuous x-axis indices and custom timestamps for multi-day data
        x_indices, tick_vals, tick_texts = self._prepare_time_axis()

        opens = [kbar.open for kbar in self.kbar_data]
        highs = [kbar.high for kbar in self.kbar_data]
        lows = [kbar.low for kbar in self.kbar_data]
        closes = [kbar.close for kbar in self.kbar_data]
        volumes = [kbar.volume for kbar in self.kbar_data]

        candlestick = go.Candlestick(
            x=x_indices,  # Use indices instead of timestamps
            open=opens,
            high=highs,
            low=lows,
            close=closes,
            name="Price",
            increasing_line_color=theme_config['candlestick_up'],
            decreasing_line_color=theme_config['candlestick_down']
        )

        volume_bar = go.Bar(
            x=x_indices,  # Use indices instead of timestamps
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
            modebar=theme_config['modebar'],
            margin=dict(l=20, r=20, t=20, b=20)
        )

        # Update axes with custom time labels
        self.fig.update_xaxes(
            gridcolor=theme_config['grid_color'],
            linecolor=theme_config['font_color'],
            rangeslider_visible=False,
            fixedrange=False,
            autorange=True,
            tickmode='array',
            tickvals=tick_vals,
            ticktext=tick_texts,
            tickangle=45,
            showgrid=True
        )

        # Price chart y-axis (row 1) - let plotly auto-scale naturally
        self.fig.update_yaxes(
            gridcolor=theme_config['grid_color'],
            linecolor=theme_config['font_color'],
            fixedrange=False,
            autorange=True,
            showgrid=True,
            row=1, col=1
        )

        # Volume chart y-axis (row 2) - start from 0, auto-scale max
        self.fig.update_yaxes(
            gridcolor=theme_config['grid_color'],
            linecolor=theme_config['font_color'],
            fixedrange=False,
            autorange=True,
            rangemode='tozero',
            showgrid=True,
            row=2, col=1
        )

        for i in range(1, 3):
            self.fig.update_xaxes(
                showline=True,
                linecolor=theme_config['font_color'],
                row=i, col=1
            )
            self.fig.update_yaxes(
                showline=True,
                linecolor=theme_config['font_color'],
                row=i, col=1
            )

        if self.auto_save and self.output_filename:
            self._auto_save()

    def _prepare_time_axis(self):
        """
        Prepare continuous x-axis indices and custom tick labels for multi-day K-bar data.
        Eliminates gaps between trading sessions while maintaining readable time labels.
        """
        if not self.kbar_data:
            return [], [], []

        x_indices = list(range(len(self.kbar_data)))
        tick_vals = []
        tick_texts = []

        # Determine appropriate tick interval based on data density
        total_bars = len(self.kbar_data)

        if total_bars <= 50:
            # For small datasets, show every few bars
            step = max(1, total_bars // 10)
        elif total_bars <= 300:
            # For single day or short periods, show hourly or half-hourly
            step = max(1, total_bars // 8)
        else:
            # For longer periods, show daily markers and some intraday
            step = max(1, total_bars // 15)

        # Group kbars by trading date
        current_date = None

        for i in range(0, total_bars, step):
            if i >= total_bars:
                break

            kbar = self.kbar_data[i]
            kbar_date = kbar.timestamp.date()

            # Check if this is start of new trading day
            if current_date != kbar_date:
                current_date = kbar_date
                # For new day, show date
                tick_vals.append(i)
                tick_texts.append(kbar_date.strftime('%m/%d'))
            else:
                # For same day, show time
                tick_vals.append(i)
                tick_texts.append(kbar.timestamp.strftime('%H:%M'))

        # Always add the last bar for completeness
        if total_bars > 1 and (total_bars - 1) not in tick_vals:
            tick_vals.append(total_bars - 1)
            last_kbar = self.kbar_data[-1]
            tick_texts.append(last_kbar.timestamp.strftime('%H:%M'))

        return x_indices, tick_vals, tick_texts

    def _update_chart_data(self) -> None:
        if not self.fig:
            self._create_chart()
            return

        with self.fig.batch_update():
            x_indices, tick_vals, tick_texts = self._prepare_time_axis()

            opens = [kbar.open for kbar in self.kbar_data]
            highs = [kbar.high for kbar in self.kbar_data]
            lows = [kbar.low for kbar in self.kbar_data]
            closes = [kbar.close for kbar in self.kbar_data]
            volumes = [kbar.volume for kbar in self.kbar_data]

            self.fig.data[0].x = x_indices
            self.fig.data[0].open = opens
            self.fig.data[0].high = highs
            self.fig.data[0].low = lows
            self.fig.data[0].close = closes

            self.fig.data[1].x = x_indices
            self.fig.data[1].y = volumes

            # Update x-axis ticks
            self.fig.update_xaxes(
                tickmode='array',
                tickvals=tick_vals,
                ticktext=tick_texts,
                tickangle=45
            )

    def render_chart(self) -> go.Figure:
        if not self.fig:
            self._create_chart()
        return self.fig

    def show_chart(self) -> None:
        if not self.fig:
            self._create_chart()

        if self.output_filename:
            self._save_html_with_template(self.output_filename)
        else:
            # Fallback to old behavior if no filename set
            theme_config = self._get_theme_config()
            self.fig.show(config=theme_config['config'])

    def save_chart(self, filename: str) -> None:
        if not self.fig:
            self._create_chart()

        if filename.endswith('.png'):
            self.fig.write_image(filename)
        elif filename.endswith('.pdf'):
            self.fig.write_image(filename)
        else:
            if not filename.endswith('.html'):
                filename = f"{filename}.html"
            self._save_html_with_template(filename)

