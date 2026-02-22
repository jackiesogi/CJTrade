# CJ Trade

![CJTrade](./img/combined.png)

## Introduction

CJ Trade is a trading system for `TWSE`. It comes with multiple great, out-of-the-box features, including:
- AI-driven dicision
- Robust technical analysis
- Feedback-driven, dynamic strategy.

## Project TODO
Note that the todos listed here is for those brand new feature, those still don't have a specific file to put into, or those not sure where to put.
If it is a modification to existing logic, please mark todo directly in that file, and it will be easier to trace using todo tree extension.

- [ ] Add `get_latest_kbar() -> Kbar` or related feature that can fetch exact one kbar.
- [x] Add abstraction to database interaction and think about what and how to record. (sqlite3 first)
- [ ] Add candidate manager related feature.
- [ ] Add `Dash` package and work with stateful UI (not only kbar chart but also some buttons and fields).

### Kbar aggregation interval consistency
- For mock securities, YFinance supports: 1m,2m,5m,15m,30m,60m,90m,1h,1d,5d,1wk,1mo,3mo
- For sinopac securities, Sinopac supports: N/A (Only 1m kbar)
- For unified `AccountClient` class requires: 1m,3m,5m,10m,15m,20m,30m,45m,1h,90m,2h,1d,1w,1M
Consider to align `AccountClient` requirements with yfinance so that there won't be any conversion needed.

## Run
Please install `uv` on your os first.
[https://docs.astral.sh/uv/getting-started/installation/](https://docs.astral.sh/uv/getting-started/installation/)

```sh
git clone https://github.com/jackiesogi/CJTrade
cd CJTrade
uv python install 3.12
uv venv --python 3.12
uv sync

source .venv/bin/activate # For Linux / macOS
.\.venv\Scripts\activate  # For Windows

mkdir data
```

### Play around using mock broker

:warning: Note that please paste line by line to avoid issue.

```sh
# For those who don't have a securities account but still want to try it out,
# try adding --broker=mock to use the mock environment (no login required):

# generate mock environment config template (Linux)
bash scripts/gen_config.sh mock

# generate mock environment config template (Windows)
.\scripts\gen_config.bat mock

# connect to mock broker
uv run cjtrade --broker=mock

# For testing all the features in cjtrade shell (Linux)
bash tests/test_cjtrade_shell_all_cmds.sh
```

### Sinopac users

```sh
# Get your required api keys from https://ai.sinotrade.com.tw/python/Main/index.aspx#pag4:
bash scripts/gen_config.sh sinopac # or .\scripts\gen_config.bat sinopac on Windows
echo "# -------- Overwritten part --------" >> sinopac_system.cjconf
echo "API_KEY=${YOUR_SINOPAC_API_KEY}" >> sinopac_system.cjconf
echo "SECRET_KEY=${YOUR_SINOPAC_SECRET_KEY}" >> sinopac_system.cjconf
echo "CA_CERT_PATH=${YOUR_SINOPAC_CA_PATH}" >> sinopac_system.cjconf
echo "CA_PASSWORD=${YOUR_SINOPAC_CA_PASSWORD}" >> sinopac_system.cjconf

# After configuring properly, you can connect to sinopac securities
uv run cjtrade --broker=sinopac

# For testing all the features in cjtrade shell
bash tests/test_cjtrade_shell_all_cmds.sh
```

## Test
1. Run basic tests: all command in cjtrade shell
```sh
uv run test --broker=sinopac --group=all
```

2. Run full tests: test hotpaths (normal input / edge cases / stress tests)
```sh
# Note that this will execute stress tests
# Add --delay=n to wait n sec after each test case done to avoid running out of API quota
./tests/test_broker_api_stability.py --broker=mock --delay=8
```


## For clear, maintainable branch design
- `master`: Master branch.
- `broker/{brokername}`: Broker's API bridging, data handling, broker-specific features and tests.
- `test/{optinonal-name}`: Generic test script and integration test. (For testing broker's API stability -> `broker/{brokername}`)
- `ui/{ui-type}`: Rendering chart, web interface, etc.
- `misc/{misc-type}`: LLM / analytics features.
