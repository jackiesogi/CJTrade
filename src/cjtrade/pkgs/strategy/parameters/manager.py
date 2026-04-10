"""
cjtrade.pkgs.strategy.parameters.manager
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ParameterManager: orchestrates parameter loading, validation, and merging.

Workflow:
    1. Load preset for interval
    2. Parse user overrides (if string format)
    3. Validate each override against schema
    4. Merge base preset + validated overrides
    5. Return ParameterConfig with metadata
"""
import logging
from typing import Any
from typing import Dict
from typing import Optional

from cjtrade.pkgs.strategy.parameters.config import ParameterConfig
from cjtrade.pkgs.strategy.parameters.presets import get_interval_presets
from cjtrade.pkgs.strategy.parameters.presets import get_supported_intervals
from cjtrade.pkgs.strategy.parameters.schema import PARAM_SCHEMA
from cjtrade.pkgs.strategy.parameters.schema import validate_param

log = logging.getLogger(__name__)

# Known strategy names (for reference and validation)
KNOWN_STRATEGIES = {
    "BollingerStrategy",
    "BollingerBands",  # Alias
    "SupportResistanceStrategy",
    "Support-Resistance",  # Alias
    "DCA_Monthly",
    "DCA",  # Alias
    "BaselineStrategy",
    "Baseline_0050",  # Alias
}


class ParameterManager:
    """Managing parameters lifecycle: load → validate → merge."""

    @staticmethod
    def load_params(
        interval: str,
        strategy_name: str,
        user_overrides: Optional[Dict[str, Any] | str] = None,
    ) -> ParameterConfig:
        """Load params: preset → validate → merge → track.

        Parameters
        ----------
        interval : str
            '1m', '5m', '1h', '1d'
        strategy_name : str
            Strategy name. Can be:
            - Known strategy: 'BollingerBands', 'SupportResistanceStrategy', 'DCA_Monthly', etc.
            - Custom string: 'my_custom_strategy', 'exp_v1_bb_tuning', etc.

            Known strategies: BollingerStrategy, BollingerBands, SupportResistanceStrategy,
            Support-Resistance, DCA_Monthly, DCA, BaselineStrategy, Baseline_0050.

            Custom names are allowed for flexibility (useful for experiment tracking).
            Unknown strategy names will log a warning but still work.
        user_overrides : dict | str, optional
            Parameters user wants to change (will override presets).
            Can be:
            - dict: {"bb__window_size": 30, "risk__max_position_pct": 0.1}
            - str:  "bb__window_size:30,risk__max_position_pct:0.1"

        Returns
        -------
        ParameterConfig
            Ready-to-use params + metadata

        Raises
        ------
        ValueError
            If interval/strategy unknown or params invalid
        """
        # 1. Validate interval
        if interval not in get_supported_intervals():
            raise ValueError(
                f"Unknown interval: {interval}. "
                f"Supported: {get_supported_intervals()}"
            )

        # 2. Load preset
        preset = get_interval_presets(interval)
        log.info(f"[ParamManager] Loaded preset for interval={interval}")

        # 3. Parse user overrides
        if isinstance(user_overrides, str):
            user_overrides = ParameterManager._parse_string_params(user_overrides)

        user_overrides = user_overrides or {}

        # 4. Validate and merge
        final_params = preset.copy()

        for key, value in user_overrides.items():
            is_valid, error = validate_param(key, value)
            if not is_valid:
                raise ValueError(f"Invalid param override: {error}")

            # Check if parameter is marked as "fixed" (auto-set, no override)
            if key in PARAM_SCHEMA and PARAM_SCHEMA[key].get("fixed"):
                log.warning(
                    f"[ParamManager] Param {key} is fixed for this interval, "
                    f"ignoring override (using preset value: {preset.get(key)})"
                )
                continue

            final_params[key] = value
            log.info(f"[ParamManager] Override: {key} = {value}")

        # 5. Check strategy_name (informational)
        if strategy_name not in KNOWN_STRATEGIES:
            log.warning(
                f"[ParamManager] Strategy '{strategy_name}' not in known list. "
                f"Known: {sorted(KNOWN_STRATEGIES)}. "
                f"This is OK for custom/experiment names (e.g., grid_search_trial_42)."
            )

        # 6. Build config
        config = ParameterConfig(
            interval=interval,
            strategy_name=strategy_name,
            params=final_params,
            base_preset=preset,
            user_overrides=user_overrides,
        )

        log.info(
            f"[ParamManager] Final params hash: {config.params_hash} "
            f"(strategy={strategy_name}, interval={interval})"
        )
        return config

    @staticmethod
    def _parse_string_params(param_str: str) -> Dict[str, Any]:
        """Parse 'bb__window_size:30,bb__min_width_pct:0.02' → dict.

        Parameters
        ----------
        param_str : str
            Comma-separated key:value pairs

        Returns
        -------
        dict
            Parsed parameters

        Raises
        ------
        ValueError
            If format is invalid
        """
        result = {}

        if not param_str or param_str.strip() == "":
            return result

        try:
            for pair in param_str.split(","):
                pair = pair.strip()
                if not pair:
                    continue

                if ":" not in pair:
                    raise ValueError(
                        f"Invalid format in '{pair}': expected 'key:value'"
                    )

                key, val = pair.split(":", 1)
                key = key.strip()
                val = val.strip()

                # Try to parse as int, float, bool, or keep as str
                if val.lower() in ("true", "false"):
                    result[key] = val.lower() == "true"
                else:
                    for converter in [int, float]:
                        try:
                            result[key] = converter(val)
                            break
                        except ValueError:
                            pass
                    else:
                        result[key] = val  # Keep as string if no converter worked

        except Exception as e:
            raise ValueError(f"Failed to parse params string '{param_str}': {e}")

        return result

    @staticmethod
    def show_params(
        interval: str, strategy_name: str = None, user_overrides: str = None
    ) -> str:
        """Generate human-readable parameter display.

        Useful for --show-params CLI option.

        Parameters
        ----------
        interval : str
            Interval
        strategy_name : str, optional
            Strategy name (for documentation)
        user_overrides : str, optional
            User overrides string

        Returns
        -------
        str
            Formatted parameter display
        """
        config = ParameterManager.load_params(
            interval=interval,
            strategy_name=strategy_name or "Unknown",
            user_overrides=user_overrides,
        )

        lines = [
            "=" * 80,
            f"Parameter Configuration",
            "=" * 80,
            f"  Interval:       {config.interval}",
            f"  Strategy:       {config.strategy_name}",
            f"  Params Hash:    {config.params_hash}",
            f"  Created:        {config.created_at}",
            "",
            "Base Preset (from interval):",
            "-" * 80,
        ]

        for key, val in sorted(config.base_preset.items()):
            lines.append(f"  {key:<40} = {val}")

        if config.user_overrides:
            lines.extend(
                [
                    "",
                    "User Overrides:",
                    "-" * 80,
                ]
            )
            for key, val in sorted(config.user_overrides.items()):
                old_val = config.base_preset.get(key, "N/A")
                lines.append(f"  {key:<40} : {old_val} → {val}")

        lines.extend(
            [
                "",
                "Final Parameters (used by BacktestEngine):",
                "-" * 80,
            ]
        )
        for key, val in sorted(config.params.items()):
            lines.append(f"  {key:<40} = {val}")

        lines.append("=" * 80)

        return "\n".join(lines)
