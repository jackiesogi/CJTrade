"""
cjtrade.pkgs.strategy.parameters.config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
ParameterConfig: encapsulates all parameters + metadata for one run.

Tracks:
- Final parameter values
- Which preset was used as base
- What user overrides were applied
- Hash for experiment reproducibility
"""
import hashlib
import json
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from typing import Any
from typing import Dict


@dataclass
class ParameterConfig:
    """Holds all parameters for a strategy run.

    Attributes
    ----------
    interval : str
        KBar interval ('1m', '5m', '1h', '1d')
    strategy_name : str
        Strategy name ('BollingerStrategy', 'SupportResistanceStrategy', etc.)
    params : dict
        Final resolved parameters (preset + overrides)
    base_preset : dict
        The interval preset we started with
    user_overrides : dict
        User-specified overrides (what params they changed)
    created_at : str
        ISO timestamp of when this config was created
    """

    interval: str
    strategy_name: str
    params: Dict[str, Any]

    # Metadata
    base_preset: Dict[str, Any] = field(default_factory=dict)
    user_overrides: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now().isoformat()
    )

    @property
    def params_hash(self) -> str:
        """Hash of params for reproducibility and experiment tracking.

        Returns
        -------
        str
            8-char SHA256 hash of params
        """
        params_json = json.dumps(self.params, sort_keys=True)
        return hashlib.sha256(params_json.encode()).hexdigest()[:8]

    def to_dict(self) -> dict:
        """Serialize to dict for logging/saving.

        Returns
        -------
        dict
            Dictionary representation suitable for JSON serialization
        """
        return {
            "interval": self.interval,
            "strategy_name": self.strategy_name,
            "params": self.params,
            "params_hash": self.params_hash,
            "base_preset": self.base_preset,
            "user_overrides": self.user_overrides,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        """Serialize to JSON string.

        Returns
        -------
        str
            JSON representation
        """
        return json.dumps(self.to_dict(), indent=2)
