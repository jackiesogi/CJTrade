"""
cjtrade.pkgs.strategy.parameters.presets
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Interval-based parameter presets.

Different intervals (1m, 5m, 1h, 1d) require different parameter values
for the same strategy to work effectively.

This module centralizes all preset values per interval.
"""
# TODO: Adjust params for 5m, 1h, 1d
INTERVAL_PRESETS = {
    "1m": {
        # Bollinger Band
        "bb__window_size": 100,
        "bb__min_width_pct": 0.01,
        "bb__std_dev": 2.0,

        # Support-Resistance
        "sr__lookback_days": 20,
        "sr__support_threshold_pct": 0.005,
        "sr__resistance_threshold_pct": 0.005,
        "sr__breakout_mode": False,
        "sr__interval": "1m",

        # DCA
        "dca__buy_frequency_days": 1,
        "dca__max_position_pct": 0.03,

        # Risk Management
        "risk__max_position_pct": 0.03,
    },
    "5m": {
        "bb__window_size": 20,
        "bb__min_width_pct": 0.008,
        "bb__std_dev": 2.0,

        "sr__lookback_days": 2,
        "sr__support_threshold_pct": 0.008,
        "sr__resistance_threshold_pct": 0.008,
        "sr__breakout_mode": False,
        "sr__interval": "5m",

        "dca__buy_frequency_days": 3,
        "dca__max_position_pct": 0.03,

        "risk__max_position_pct": 0.04,
    },
    "1h": {
        "bb__window_size": 20,
        "bb__min_width_pct": 0.01,
        "bb__std_dev": 2.0,

        "sr__lookback_days": 5,
        "sr__support_threshold_pct": 0.01,
        "sr__resistance_threshold_pct": 0.01,
        "sr__breakout_mode": False,
        "sr__interval": "1h",

        "dca__buy_frequency_days": 7,
        "dca__max_position_pct": 0.04,

        "risk__max_position_pct": 0.05,
    },
    "1d": {
        "bb__window_size": 20,
        "bb__min_width_pct": 0.01,
        "bb__std_dev": 2.0,

        "sr__lookback_days": 20,
        "sr__support_threshold_pct": 0.01,
        "sr__resistance_threshold_pct": 0.01,
        "sr__breakout_mode": False,
        "sr__interval": "1d",

        "dca__buy_frequency_days": 30,
        "dca__max_position_pct": 0.05,

        "risk__max_position_pct": 0.05,
    },
}


def get_interval_presets(interval: str) -> dict:
    """Get base presets for given interval.

    Parameters
    ----------
    interval : str
        '1m', '5m', '1h', '1d'

    Returns
    -------
    dict
        Preset parameters for this interval (deep copy to avoid mutations)

    Raises
    ------
    ValueError
        If interval is not supported
    """
    if interval not in INTERVAL_PRESETS:
        raise ValueError(
            f"Unknown interval: {interval}. "
            f"Supported: {list(INTERVAL_PRESETS.keys())}"
        )

    import copy

    return copy.deepcopy(INTERVAL_PRESETS[interval])


def get_supported_intervals() -> list:
    """Get list of supported intervals.

    Returns
    -------
    list[str]
        List of supported interval strings
    """
    return list(INTERVAL_PRESETS.keys())
