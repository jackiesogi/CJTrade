from cjtrade.pkgs.analytics.technical.talib_wrapper import TALibWrapper

# Global instance, allowing users to directly import ta from technical
ta = TALibWrapper()

__all__ = ['ta', 'TALibWrapper']

# simple test code
# definition:
#   - sys: code that should handle by system and try not to expose to users
#   - adv: code that can be exposed to "advanced" users
#   - usr: code that should be exposed to users (like Pine Script style API)
if __name__ == "__main__":
    import numpy as np
    from cjtrade.pkgs.logger import get_console
    from cjtrade.pkgs.logger import setup_logging
    setup_logging()
    out = get_console("analytics.technical")
    # closes = np.array([1, 2, 3, 4, 5], dtype=float)

    # market.ohlcv() -> what API an user may want to use
    # A seeded random walk, so the demo needs no broker or network.
    closes = 100 + np.cumsum(np.random.default_rng(0).normal(0, 1, 250))

    out.info("SMA: %s", ta.sma(closes, timeperiod=3))
    out.info("EMA: %s", ta.ema(closes, timeperiod=3))

    exit(0)
