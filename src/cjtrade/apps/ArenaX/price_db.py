# TODO: 考慮直接放棄這個抽象（現在在 pkgs 的 db_api 已經有 insert / get 兩個功能的實現）
# 藉由一次一次的 price fetching 來慢慢填滿 local database,
# 這樣等到資料慢慢齊全後, price fetching 就會越來越快,
# 同時也減少對 broker-api usage 的壓力
from datetime import datetime
from typing import List
from typing import Optional
from typing import Tuple

from cjtrade.pkgs.db.db_api import compute_missing_ranges
from cjtrade.pkgs.db.db_api import connect_sqlite
from cjtrade.pkgs.db.db_api import get_coverage_ranges
from cjtrade.pkgs.db.db_api import get_price_from_arenax_local_price_db
from cjtrade.pkgs.db.db_api import insert_price_to_arenax_local_price_db
from cjtrade.pkgs.db.db_api import prepare_arenax_local_price_db_tables
from cjtrade.pkgs.db.db_api import upsert_coverage_range
from cjtrade.pkgs.models.kbar import Kbar


# This code is designed for ArenaX backend to CURD price data into local price database
class ArenaX_LocalPriceDB:
    def __init__(self, path):
        self.path = path
        self.conn = None

    def connect(self):
        self.conn = connect_sqlite(self.path)
        # Ensure that the necessary tables are created (and migrated if needed)
        prepare_arenax_local_price_db_tables(conn=self.conn)

    def disconnect(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    # ------------------------------------------------------------------
    # Price data CRUD
    # ------------------------------------------------------------------

    def insert_price(self, symbol: str,
                     timeframe: str = "1m",
                     price: Kbar = None,
                     source: str = "unknown",
                     overwrite: bool = True) -> bool:
        return insert_price_to_arenax_local_price_db(conn=self.conn,
                                                     symbol=symbol,
                                                     price=price,
                                                     timeframe=timeframe,
                                                     source=source,
                                                     overwrite=overwrite)

    def insert_prices_batch(self, symbol: str,
                            kbars: List[Kbar],
                            timeframe: str = "1m",
                            source: str = "unknown",
                            overwrite: bool = False) -> int:
        """Insert multiple Kbars.  Returns number of successfully inserted rows."""
        count = 0
        for kb in kbars:
            ok = insert_price_to_arenax_local_price_db(
                conn=self.conn, symbol=symbol, price=kb,
                timeframe=timeframe, source=source, overwrite=overwrite
            )
            if ok:
                count += 1
        return count

    def get_price(self, symbol: str,
                  timeframe: str = "1m",
                  start_ts: Optional[datetime] = None,
                  end_ts: Optional[datetime] = None) -> List[Kbar]:
        return get_price_from_arenax_local_price_db(conn=self.conn,
                                                    symbol=symbol,
                                                    timeframe=timeframe,
                                                    start_ts=start_ts,
                                                    end_ts=end_ts)

    def clear_db(self):
        raise NotImplementedError("Clear DB functionality is not implemented yet.")

    # ------------------------------------------------------------------
    # Coverage tracking
    # ------------------------------------------------------------------

    def get_coverage(self, symbol: str,
                     timeframe: str = "1m") -> List[Tuple[int, int]]:
        """Return sorted, merged list of (start_ts_epoch, end_ts_epoch) cached intervals."""
        return get_coverage_ranges(self.conn, symbol, timeframe)

    def get_missing_ranges(self, symbol: str,
                           timeframe: str,
                           start_ts: datetime,
                           end_ts: datetime) -> List[Tuple[int, int]]:
        """Return list of (start_epoch, end_epoch) sub-intervals NOT present in cache.

        Both ``start_ts`` and ``end_ts`` are ``datetime`` objects; epochs are returned
        as Unix seconds so callers can convert back with ``datetime.fromtimestamp()``.
        """
        s_epoch = int(start_ts.timestamp())
        e_epoch = int(end_ts.timestamp())
        return compute_missing_ranges(self.conn, symbol, timeframe, s_epoch, e_epoch)

    def record_coverage(self, symbol: str,
                        timeframe: str,
                        start_ts: datetime,
                        end_ts: datetime,
                        source: str = "unknown"):
        """Record that [start_ts, end_ts] is now available in the local price cache."""
        s_epoch = int(start_ts.timestamp())
        e_epoch = int(end_ts.timestamp())
        upsert_coverage_range(self.conn, symbol, timeframe, s_epoch, e_epoch, source)
