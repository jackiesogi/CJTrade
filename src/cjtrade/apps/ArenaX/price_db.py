# TODO: 考慮直接放棄這個抽象（現在在 pkgs 的 db_api 已經有 insert / get 兩個功能的實現）
# 藉由一次一次的 price fetching 來慢慢填滿 local database,
# 這樣等到資料慢慢齊全後, price fetching 就會越來越快,
# 同時也減少對 broker-api usage 的壓力
from cjtrade.pkgs.db.db_api import *

# This code is designed for ArenaX backend to CURD price data into local price database
class ArenaX_LocalPriceDB:
    def __init__(self, path):
        self.path = path
        self.conn = None

    def connect(self):
        self.conn = connect_sqlite(self.path)

    def disconnect(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def insert_price(self, symbol: str,
                     timeframe: str = "1m",
                     price: Kbar = None,
                     source: str = "unknown",
                     overwrite: bool = True):
        return insert_price_to_arenax_local_price_db(conn=self.conn,
                                                     symbol=symbol,
                                                     price=price,
                                                     timeframe=timeframe,
                                                     source=source,
                                                     overwrite=overwrite)

    def get_price(self, symbol: str,
                  timeframe: str = "1m",
                  start_ts: datetime = None,
                  end_ts: datetime = None):
        return get_price_from_arenax_local_price_db(conn=self.conn,
                                                    symbol=symbol,
                                                    timeframe=timeframe,
                                                    start_ts=start_ts,
                                                    end_ts=end_ts)

    # def update_price(self, symbol: str, price: float):
    #     self.price_db[symbol] = price

    # def delete_price(self, symbol: str):
    #     if symbol in self.price_db:
    #         del self.price_db[symbol]

    def clear_db(self):
        raise NotImplementedError("Clear DB functionality is not implemented yet.")
