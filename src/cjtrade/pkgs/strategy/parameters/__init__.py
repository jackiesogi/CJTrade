"""
cjtrade.pkgs.strategy.parameters
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Strategy parameter management system.

Provides:
- Interval-based parameter presets (1m, 5m, 1h, 1d)
- Parameter schema definition, validation, and constraints
- Configuration objects for tracking parameter usage
- ParameterManager for orchestrating the entire lifecycle

Usage
-----
    from cjtrade.pkgs.strategy.parameters.manager import ParameterManager

    config = ParameterManager.load_params(
        interval="1d",
        strategy_name="BollingerBands",
        user_overrides={"bb__window_size": 30}
    )

    # Use config.params in BacktestEngine
    print(config.params_hash)  # Track experiments
"""

__all__ = [
    "ParameterManager",
    "ParameterConfig",
    "PARAM_SCHEMA",
    "INTERVAL_PRESETS",
]

from cjtrade.pkgs.strategy.parameters.manager import ParameterManager
from cjtrade.pkgs.strategy.parameters.config import ParameterConfig
from cjtrade.pkgs.strategy.parameters.schema import PARAM_SCHEMA
from cjtrade.pkgs.strategy.parameters.presets import INTERVAL_PRESETS
