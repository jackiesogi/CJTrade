@echo off

set broker=%1
set balance=%2

if "%broker%"=="" (
    echo Usage: %0 ^<broker^> [balance]
    echo Example: %0 mock 10000
    exit /b 1
)

if "%balance%"=="" (
    set balance=10000.0
)

if "%USERNAME%"=="" (
    for /f %%i in ('whoami') do set USERNAME=%%i
)

set out_file=%broker%_%USERNAME%.json

echo {> "%out_file%"
echo     "balance": 0.0,>> "%out_file%"
echo     "positions": [],>> "%out_file%"
echo     "orders_placed": [],>> "%out_file%"
echo     "orders_committed": [],>> "%out_file%"
echo     "orders_filled": [],>> "%out_file%"
echo     "orders_cancelled": [],>> "%out_file%"
echo     "all_order_status": {},>> "%out_file%"
echo     "fill_history": []>> "%out_file%"
echo }>> "%out_file%"

jq ".balance = %balance%" "%out_file%" > tmp.json
move /y tmp.json "%out_file%" >nul

echo Initialized account state for broker '%broker%' with balance %balance% in file '%out_file%'
