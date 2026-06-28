# Source code in `apps`

See [Here](./apps/README.md)

# Source code in `pkgs`

## `analytics/`

Provide commonly-used analytics methods.

- **Fundamental (基本面)**: EPS, PB Ratio, PE Ratio, Dividends ...
- **Technical (技術面)**: SMA, MACD, RSI indicators ...
- **Informational (消息面)**: News webscraping from Cnyes(鉅亨網) and levarage LLM for sentiment analysis.


## `brokers/`

Provide **integration with different brokers' API**, for example sinopac (永豐證券), cathay (國泰證券), to allow user to port their trading-related apps to different broker platforms.

See [here](./pkgs/brokers/README.md) for more info.


## `chart/`

Provide method to draw, render, save kbar (K線) chart.


## `db/`

Database core operations.


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
