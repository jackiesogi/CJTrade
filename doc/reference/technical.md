# Technical indicators

`ta` (an instance of `TALibWrapper`) wraps TA-Lib. Each method takes NumPy
arrays and returns arrays of the same length, `NaN` until the window is full.
The authoring module has its own `ta` that returns only the latest value.

::: cjtrade.pkgs.analytics.technical.talib_wrapper
