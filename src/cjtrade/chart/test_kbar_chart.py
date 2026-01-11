from datetime import datetime, time, timedelta
import os
from time import sleep
from cjtrade.chart import KbarChartClient, KbarChartType, KbarData
from cjtrade.models.product import Product
from cjtrade.analytics.technical.models.market_state import OHLCVState
from cjtrade.core.account_client import *
from dotenv import load_dotenv


def demo_kbar_chart():
    product = Product(symbol="2330")

    base_time = datetime.now()
    sample_data = []

    for i in range(20):
        ohlcv_state = OHLCVState(
            ts=base_time + timedelta(minutes=i),
            o=500 + i * 0.5,
            h=502 + i * 0.4,
            l=499 + i * 0.2,
            c=501 + i * 0.3,
            v=1000 + i * 100
        )

        kbar_data = KbarData.from_ohlcv_state(ohlcv_state, symbol="2330")
        sample_data.append(kbar_data)

    chart_client = KbarChartClient(
        chart_type=KbarChartType.PLOTLY,
        auto_save=True,
        width=1400,
        height=1000
    )

    chart_client.set_kbar_data(sample_data, product)

    chart_client.show_chart()

    chart_client.save_chart("demo_kbar_chart")


def test_kbar_chart_historical_data():

    # Broker setup
    load_dotenv()
    config = {
        'api_key': os.environ["API_KEY"],
        'secret_key': os.environ["SECRET_KEY"],
        'ca_path': os.environ["CA_CERT_PATH"],
        'ca_passwd': os.environ["CA_PASSWORD"],
        'simulation': False  # Use production environment to see actual holdings
    }
    real = AccountClient(BrokerType.SINOPAC, **config)
    broker = AccountClient(BrokerType.MOCK, real_account=real)
    broker.connect()
    product = Product(symbol="0050")

    # Drawer setup
    drawer = KbarChartClient(
        chart_type=KbarChartType.PLOTLY,
        auto_save=True,
        width=1200,
        height=600
    )

    # Set product to generate filename
    drawer.set_product(product)

    # TODO: Remove these when mock_broker.get_kbars() is stable
    # 現在 mock broker 的 get_snapshots() 理論上是要回傳正常的市場即時詳細資訊
    # 但實際上當初的實作（拿歷史資料來 replay）最後是回傳 1分K
    # 所以：
    #   [x] mock broker 要有 get_kbars() 的實作，然後把既有的邏輯搬過去
    #   [x] kbar 在 broker 的層面要有自己獨立的資料結構，而不應該依賴 Snapshot / OHLCVState
    # 因此以下的處理邏輯才會有些奇怪，明明是呼叫 get_snapshot()，但實際上需要把他的 ohlcv 轉成
    # KbarData（chart 模組自己獨立的 ohlcv）來用
    for i in range(10):
        # wrong_snapshot = broker.get_snapshots([product])[0]
        # min_kbar = KbarData(
        #     timestamp=wrong_snapshot.timestamp,
        #     open=wrong_snapshot.open,
        #     high=wrong_snapshot.high,
        #     low=wrong_snapshot.low,
        #     close=wrong_snapshot.close,
        #     volume=wrong_snapshot.volume,
        #     symbol=product.symbol
        # )

        # Note that following line has been adjusted to progress the time by the index i.
        raw = broker.get_kbars(product, start='2026-01-06', end='2026-01-07', interval='1m')[i]
        min_kbar = KbarData(
            timestamp=raw.timestamp,
            open=raw.open,
            high=raw.high,
            low=raw.low,
            close=raw.close,
            volume=raw.volume,
            symbol=product.symbol
        )

        print(f"Appending kbar: {min_kbar}")

        drawer.append_kbar(min_kbar)
        drawer.show_chart()
        sleep(60)


def test_sinopac_historical_kbars(on_ready=None, symbol="2308",
                                  start="2026-01-07", end="2026-01-08", interval="15m") -> str:
    load_dotenv()
    config = {
        'api_key': os.environ["API_KEY"],
        'secret_key': os.environ["SECRET_KEY"],
        'ca_path': os.environ["CA_CERT_PATH"],
        'ca_passwd': os.environ["CA_PASSWORD"],
        'simulation': False  # Use production environment to see actual holdings
    }
    sinopac = AccountClient(BrokerType.SINOPAC, **config)
    sinopac.connect()
    product = Product(symbol=symbol)

    # Drawer setup
    drawer = KbarChartClient(
        chart_type=KbarChartType.PLOTLY,
        auto_save=True,
        width=900,
        height=1000
    )

    # Set product to generate filename
    drawer.set_product(product)
    drawer.set_theme('nordic')

    # Get only 2026-01-07 data using [start, end) exclusive range
    # end='2026-01-08' will exclude 2026-01-08, getting only 2026-01-07
    kbars = sinopac.get_kbars(product, start=start, end=end, interval=interval)
    print(f"Total kbars: {len(kbars)}")

    first_run = True
    for kbar in kbars:
        drawer.append_kbar(kbar)

        if first_run and on_ready:
            on_ready(drawer.get_output_filename())
            first_run = False

        sleep(0.3)


def test_kbar_aggregation():
    conf = {
        "product": Product(symbol="2308"),
        "start": "2026-01-07",
        "end": "2026-01-08",
    }
    expected_oneday_kbar_in_out = {
        "1m": (250, 270),
        "5m": (50, 55),
        "15m": (17, 20),
        "30m": (9, 10),
        "1h": (4, 5),
        "1d": (1, 1)
    }

    def _in_expected_range(n: int, interval: str) -> bool:
        return expected_oneday_kbar_in_out[interval][0] <= n <= expected_oneday_kbar_in_out[interval][1]

    def assert_kbar_count_valid(kbars, interval: str, broker_name: str = ""):
        n_kbars = len(kbars) if hasattr(kbars, '__len__') else kbars
        expected_range = expected_oneday_kbar_in_out[interval]
        min_expected, max_expected = expected_range

        broker_prefix = f"({broker_name}) " if broker_name else ""

        if _in_expected_range(n_kbars, interval):
            print(f"{broker_prefix}Interval {interval} returned {n_kbars} kbars, within expected range [{min_expected},{max_expected}].")
        else:
            error_msg = (
                f"{broker_prefix}Interval {interval} returned {n_kbars} kbars, "
                f"expected in range [{min_expected},{max_expected}]"
            )
            if hasattr(kbars, '__len__') and len(kbars) <= 5:  # Only show raw kbars if few
                error_msg += f". Raw kbars: {kbars}"

            raise AssertionError(error_msg)


    def test_sinopac_kbar_agg():
        load_dotenv()
        config = {
            'api_key': os.environ["API_KEY"],
            'secret_key': os.environ["SECRET_KEY"],
            'ca_path': os.environ["CA_CERT_PATH"],
            'ca_passwd': os.environ["CA_PASSWORD"],
            'simulation': False  # Use production environment to see actual holdings
        }
        sinopac = AccountClient(BrokerType.SINOPAC, **config)
        sinopac.connect()
        for interval in expected_oneday_kbar_in_out.keys():
            kbars = sinopac.get_kbars(
                product=conf["product"],
                start=conf["start"],
                end=conf["end"],
                interval=interval
            )
            assert_kbar_count_valid(kbars, interval, "Sinopac")

    def test_mock_kbar_agg():
        mock = AccountClient(BrokerType.MOCK)
        mock.connect()
        for interval in expected_oneday_kbar_in_out.keys():
            kbars = mock.get_kbars(
                product=conf["product"],
                start=conf["start"],
                end=conf["end"],
                interval=interval
            )
            assert_kbar_count_valid(kbars, interval, "Mock")

    test_sinopac_kbar_agg()
    test_mock_kbar_agg()


if __name__ == "__main__":
    # demo_kbar_chart()
    # test_kbar_chart_historical_data()
    test_sinopac_historical_kbars()
    # test_kbar_aggregation()