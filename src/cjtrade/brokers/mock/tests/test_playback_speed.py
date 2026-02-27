from cjtrade.brokers.mock._mock_broker_backend import *
from cjtrade.brokers.mock.mock_broker_api import *

def test_playback_speed():

    def test_playback_speed_1x(mbb):
        mbb.market.set_playback_speed(1.0)
        start = mbb.market.get_market_time()['mock_current_time']
        time.sleep(10)
        end = mbb.market.get_market_time()['mock_current_time']
        print(f"1x test: start={start}, end={end}, delta={(end - start).total_seconds()} seconds")
        assert 9 <= (end - start).total_seconds() <= 11

    def test_playback_speed_5x(mbb):
        mbb.market.set_playback_speed(5.0)
        start = mbb.market.get_market_time()['mock_current_time']
        time.sleep(10)
        end = mbb.market.get_market_time()['mock_current_time']
        print(f"5x test: start={start}, end={end}, delta={(end - start).total_seconds()} seconds")
        assert 48 <= (end - start).total_seconds() <= 52

    def test_playback_speed_10x(mbb):
        mbb.market.set_playback_speed(10.0)
        start = mbb.market.get_market_time()['mock_current_time']
        time.sleep(5)
        end = mbb.market.get_market_time()['mock_current_time']
        print(f"10x test: start={start}, end={end}, delta={(end - start).total_seconds()} seconds")
        assert 48 <= (end - start).total_seconds() <= 52

    import time
    mbb = MockBrokerBackend(price_mode=PriceMode.HISTORICAL)
    mbb.market.set_historical_time(datetime.datetime.now(), days_back=10)
    mbb.market.create_historical_market("2330")

    test_playback_speed_1x(mbb)
    test_playback_speed_5x(mbb)
    test_playback_speed_10x(mbb)
    print("All playback speed tests passed.")


def test_snapshot_playback_speed():

    def test_speed_120x(mbb):
        print("Starting 120x kbar speed test...")
        mbb.market.set_playback_speed(120.0)
        start = mbb.market.get_market_time()['mock_current_time']
        for i in range(10):
            snapshot = mbb.snapshot("2357")
            print(f"ts: {snapshot.timestamp}, o: {snapshot.open}, h: {snapshot.high}, l: {snapshot.low}, c: {snapshot.close}, v: {snapshot.volume}")
            time.sleep(1)
        end = mbb.market.get_market_time()['mock_current_time']
        print(f"10x test: start={start}, end={end}, delta={(end - start).total_seconds()} seconds")

    def test_speed_1200x(mbb):
        print("Starting 1200x kbar speed test...")
        mbb.market.set_playback_speed(1200.0)
        start = mbb.market.get_market_time()['mock_current_time']
        for i in range(10):
            snapshot = mbb.snapshot("2357")
            print(f"ts: {snapshot.timestamp}, o: {snapshot.open}, h: {snapshot.high}, l: {snapshot.low}, c: {snapshot.close}, v: {snapshot.volume}")
            time.sleep(1)
        end = mbb.market.get_market_time()['mock_current_time']
        print(f"30x test: start={start}, end={end}, delta={(end - start).total_seconds()} seconds")

    import time
    mbb = MockBrokerBackend(price_mode=PriceMode.HISTORICAL)
    mbb.market.set_historical_time(datetime.datetime.now(), days_back=10)
    mbb.market.create_historical_market("2357")

    test_speed_120x(mbb)
    test_speed_1200x(mbb)

if __name__ == "__main__":
    test_playback_speed()
    test_snapshot_playback_speed()
