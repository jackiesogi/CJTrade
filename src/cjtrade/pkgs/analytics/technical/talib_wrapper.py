import numpy as np
import talib

class TALibWrapper:
    """Pine Script style API"""

    # Moving Averages Indicators
    def sma(self, real, timeperiod=20):
        """Simple Moving Average"""
        return talib.SMA(real, timeperiod=timeperiod)

    def ema(self, real, timeperiod=20):
        """Exponential Moving Average"""
        return talib.EMA(real, timeperiod=timeperiod)

    def wma(self, real, timeperiod=20):
        """Weighted Moving Average"""
        return talib.WMA(real, timeperiod=timeperiod)

    # Bollinger Bands
    def bb(self, real, timeperiod=20, nbdevup=2, nbdevdn=2, matype=0):
        """Bollinger Bands"""
        return talib.BBANDS(real, timeperiod=timeperiod,
                           nbdevup=nbdevup, nbdevdn=nbdevdn, matype=matype)

    # Momentum Indicators
    def rsi(self, real, timeperiod=14):
        """Relative Strength Index"""
        return talib.RSI(real, timeperiod=timeperiod)

    def macd(self, real, fastperiod=12, slowperiod=26, signalperiod=9):
        """MACD - Moving Average Convergence Divergence"""
        macd, signal, hist = talib.MACD(real, fastperiod=fastperiod,
                                        slowperiod=slowperiod,
                                        signalperiod=signalperiod)
        return macd, signal, hist

    def stoch(self, high, low, close, fastk_period=5, slowk_period=3,
              slowd_period=3, slowk_matype=0, slowd_matype=0):
        """Stochastic"""
        slowk, slowd = talib.STOCH(high, low, close,
                                   fastk_period=fastk_period,
                                   slowk_period=slowk_period,
                                   slowd_period=slowd_period,
                                   slowk_matype=slowk_matype,
                                   slowd_matype=slowd_matype)
        return slowk, slowd

    # Volatility
    def atr(self, high, low, close, timeperiod=14):
        """Average True Range"""
        return talib.ATR(high, low, close, timeperiod=timeperiod)

    def adx(self, high, low, close, timeperiod=14):
        """Average Directional Index"""
        return talib.ADX(high, low, close, timeperiod=timeperiod)
