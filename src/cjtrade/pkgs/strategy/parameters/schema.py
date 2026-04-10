"""
cjtrade.pkgs.strategy.parameters.schema
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Parameter schema: definition, type, range, constraints.

Enables:
- Parameter validation
- Grid search / optimization (know the search space)
- Documentation of what params are available
"""
from typing import Any
from typing import Dict
from typing import Tuple

PARAM_SCHEMA: Dict[str, Dict[str, Any]] = {
    # ========== Bollinger Band ==========
    "bb__window_size": {
        "type": "int",
        "min": 5,
        "max": 100,
        "step": 5,
        "default": 20,
        "description": "Bollinger Band window size (periods/days)",
        "strategies": ["BollingerStrategy"],
    },
    "bb__min_width_pct": {
        "type": "float",
        "min": 0.001,
        "max": 0.1,
        "step": 0.001,
        "default": 0.01,
        "description": "Min band width % to trade",
        "strategies": ["BollingerStrategy"],
    },
    "bb__std_dev": {
        "type": "float",
        "min": 1.0,
        "max": 3.0,
        "default": 2.0,
        "fixed": True,  # Usually fixed at 2.0, not optimized
        "description": "Standard deviation multiplier for bands",
        "strategies": ["BollingerStrategy"],
    },
    # ========== Support-Resistance ==========
    "sr__lookback_days": {
        "type": "int",
        "min": 1,
        "max": 100,
        "step": 1,
        "default": 20,
        "description": "Lookback period for S/R levels",
        "strategies": ["SupportResistanceStrategy"],
    },
    "sr__support_threshold_pct": {
        "type": "float",
        "min": 0.001,
        "max": 0.1,
        "step": 0.001,
        "default": 0.01,
        "description": "Distance from support level (%)",
        "strategies": ["SupportResistanceStrategy"],
    },
    "sr__resistance_threshold_pct": {
        "type": "float",
        "min": 0.001,
        "max": 0.1,
        "step": 0.001,
        "default": 0.01,
        "description": "Distance from resistance level (%)",
        "strategies": ["SupportResistanceStrategy"],
    },
    "sr__breakout_mode": {
        "type": "bool",
        "default": False,
        "description": "Buy on breakout above resistance",
        "strategies": ["SupportResistanceStrategy"],
    },
    "sr__interval": {
        "type": "str",
        "enum": ["1m", "5m", "1h", "1d"],
        "default": "1d",
        "fixed": True,  # Auto-set based on interval, not user-configurable
        "description": "KBar interval hint for bars_per_day calculation",
        "strategies": ["SupportResistanceStrategy"],
    },
    # ========== DCA ==========
    "dca__buy_frequency_days": {
        "type": "int",
        "min": 1,
        "max": 365,
        "step": 1,
        "default": 30,
        "fixed": True,  # Auto-set based on interval
        "description": "Days between buys",
        "strategies": ["DCA_Monthly"],
    },
    "dca__max_position_pct": {
        "type": "float",
        "min": 0.01,
        "max": 0.5,
        "step": 0.01,
        "default": 0.03,
        "description": "Max position size as fraction of equity",
        "strategies": ["DCA_Monthly"],
    },
    # ========== Donchian Breakout ==========
    "donchian__period": {
        "type": "int",
        "min": 5,
        "max": 100,
        "step": 5,
        "default": 20,
        "description": "Donchian channel lookback period (days)",
        "strategies": ["DonchianBreakoutStrategy"],
    },
    "donchian__breakout_mode": {
        "type": "str",
        "enum": ["close", "touch"],
        "default": "close",
        "description": "Breakout trigger: 'close' = close above/below, 'touch' = price touches",
        "strategies": ["DonchianBreakoutStrategy"],
    },
    "donchian__trailing_stop_pct": {
        "type": "float",
        "min": 0.0,
        "max": 0.5,
        "step": 0.01,
        "default": 0.0,
        "description": "Trailing stop as % of entry price (0.0 = disabled)",
        "strategies": ["DonchianBreakoutStrategy"],
    },
    # ========== ADX Adaptive ==========
    "adx__period": {
        "type": "int",
        "min": 5,
        "max": 50,
        "step": 1,
        "default": 14,
        "description": "ADX calculation period",
        "strategies": ["ADXAdaptiveStrategy"],
    },
    "adx__strong_threshold": {
        "type": "float",
        "min": 20.0,
        "max": 60.0,
        "step": 5.0,
        "default": 40.0,
        "description": "ADX threshold to enter strong trend (Donchian breakout mode)",
        "strategies": ["ADXAdaptiveStrategy"],
    },
    "adx__weak_threshold": {
        "type": "float",
        "min": 10.0,
        "max": 40.0,
        "step": 2.0,
        "default": 20.0,
        "description": "ADX threshold to enter consolidation (SNR mode)",
        "strategies": ["ADXAdaptiveStrategy"],
    },
    "adx__donchian_period": {
        "type": "int",
        "min": 5,
        "max": 100,
        "step": 5,
        "default": 20,
        "description": "Donchian breakout lookback period in trend mode",
        "strategies": ["ADXAdaptiveStrategy"],
    },
    "adx__snr_lookback_days": {
        "type": "int",
        "min": 1,
        "max": 100,
        "step": 1,
        "default": 20,
        "description": "S/R lookback period in consolidation mode",
        "strategies": ["ADXAdaptiveStrategy"],
    },
    "adx__snr_threshold_pct": {
        "type": "float",
        "min": 0.001,
        "max": 0.1,
        "step": 0.001,
        "default": 0.01,
        "description": "Distance from S/R level to trigger trade (%)",
        "strategies": ["ADXAdaptiveStrategy"],
    },
    # ========== Common Risk ==========
    "risk__max_position_pct": {
        "type": "float",
        "min": 0.01,
        "max": 0.5,
        "step": 0.01,
        "default": 0.05,
        "description": "Max position size as fraction of equity",
        "strategies": ["*"],  # All strategies
    },
}


def validate_param(key: str, value: Any) -> Tuple[bool, str]:
    """Check if param value is valid according to schema.

    Parameters
    ----------
    key : str
        Parameter name
    value : Any
        Parameter value

    Returns
    -------
    (is_valid, error_message)
        Tuple of (bool, str). If valid, error_message is empty.
    """
    if key not in PARAM_SCHEMA:
        return False, f"Unknown param: {key}"

    schema = PARAM_SCHEMA[key]
    param_type = schema["type"]

    # Type check
    type_map = {"int": int, "float": float, "str": str, "bool": bool}
    expected_type = type_map[param_type]

    if not isinstance(value, expected_type):
        return False, f"{key} must be {param_type}, got {type(value).__name__}"

    # Range check for numeric types
    if param_type in ("int", "float"):
        if "min" in schema and value < schema["min"]:
            return False, f"{key}={value} < min {schema['min']}"
        if "max" in schema and value > schema["max"]:
            return False, f"{key}={value} > max {schema['max']}"

    # Enum check
    if "enum" in schema and value not in schema["enum"]:
        return False, f"{key}={value} not in {schema['enum']}"

    return True, ""


def can_optimize(key: str) -> bool:
    """Check if param can be optimized (not fixed).

    Parameters
    ----------
    key : str
        Parameter name

    Returns
    -------
    bool
        True if parameter can be optimized
    """
    if key not in PARAM_SCHEMA:
        return False
    return not PARAM_SCHEMA[key].get("fixed", False)


def get_param_range(key: str) -> Dict[str, Any]:
    """Get optimization range for a parameter.

    Parameters
    ----------
    key : str
        Parameter name

    Returns
    -------
    dict
        Dict with 'min', 'max', 'step', 'type'
    """
    if key not in PARAM_SCHEMA or not can_optimize(key):
        return {}

    schema = PARAM_SCHEMA[key]
    return {
        "type": schema["type"],
        "min": schema.get("min"),
        "max": schema.get("max"),
        "step": schema.get("step"),
        "default": schema.get("default"),
    }
