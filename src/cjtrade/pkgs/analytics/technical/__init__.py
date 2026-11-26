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
    from cjtrade.pkgs.brokers.arenax.legacy.mock_broker_api import MockBrokerAPI
    from cjtrade.pkgs.logger import get_console
    from cjtrade.pkgs.logger import setup_logging
    from cjtrade.pkgs.models.product import Product
    setup_logging()
    out = get_console("analytics.technical")
    # closes = np.array([1, 2, 3, 4, 5], dtype=float)

    # market.ohlcv() -> what API an user may want to use
    market = MockBrokerAPI()        # sys or adv
    market.connect()                # sys or adv

    #######  USER CODE STARTS HERE  #######

    closes = market.get_kbars(product=Product("0050"), start="2023-01-01", end="2023-12-31", interval="1d")
    closes = np.array([kbar.close for kbar in closes], dtype=float)  # sys

    out.info("SMA: %s", ta.sma(closes, timeperiod=3))
    out.info("EMA: %s", ta.ema(closes, timeperiod=3))

    #######   USER CODE ENDS HERE   #######
    market.disconnect()             # sys
    exit(0)
