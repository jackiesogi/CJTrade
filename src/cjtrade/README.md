# Source code

## `analytics/`

Provide commonly-used analytics methods.

- **Fundamental (基本面)**: EPS, PB Ratio, PE Ratio, Dividends ...
- **Technical (技術面)**: SMA, MACD, RSI indicators ...
- **Informational (消息面)**: News webscraping from Cnyes(鉅亨網) and levarage LLM for sentiment analysis.


## `brokers/`

Provide **integration with different brokers' API**, for example sinopac (永豐證券), cathay (國泰證券), to allow user to port their trading-related apps to different broker platforms.

See [here](./brokers/README.md) for more info.


## `chart/`

(Probably will renamed to `ui` in the future)

Provide method to draw, render, save kbar (K線) chart.


## `core/`

Core service, class, application logic.


## `legacy/`

Don't touch it.


## `llm/`

Provide unified interface to different LLM service (Available backend: Gemini 3)


## `models/`

Common data types for this whole project, for example

- `Position` (倉位).
- `Order` (訂單).
- `Product` (金融商品).
- `Quote` (報價).

and more.


## `tests/`

Generic test scripts for integration test.

Note that broker-specific tests here need to be specified clearly by their names. Otherwise, just consider to put it under `brokers/{broker_name}/tests/` to avoid ambiguity.