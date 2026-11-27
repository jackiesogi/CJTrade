"""YuantaBrokerAPI against a fake Spark API.

The fake trader answers every call through OnResponse on another thread, as
the real assembly does, with the objects and fields Yuanta documents. No
.NET runtime or DLL is needed.
"""
import threading
from types import SimpleNamespace as NS

import pytest
from cjtrade.pkgs.brokers.yuanta import _internal_func as yx
from cjtrade.pkgs.brokers.yuanta import yuanta_broker_api as mod
from cjtrade.pkgs.models.order import Order
from cjtrade.pkgs.models.order import OrderAction
from cjtrade.pkgs.models.order import OrderLot
from cjtrade.pkgs.models.order import OrderStatus
from cjtrade.pkgs.models.order import OrderType
from cjtrade.pkgs.models.order import PriceType
from cjtrade.pkgs.models.product import Product

ACCOUNT = "S98875005091"
DAY = NS(ushtYear=2026, bytMon=11, bytDay=27)


class Event:
    """`trader.OnResponse += handler`."""

    def __init__(self):
        self.handlers = []

    def __iadd__(self, h):
        self.handlers.append(h)
        return self


class FakeList(list):
    def Add(self, x):
        self.append(x)


class GenericList:
    """`List[StockOrder]()` from System.Collections.Generic."""

    def __getitem__(self, item_type):
        return FakeList


class FakeTrader:
    def __init__(self, world):
        self.world = world
        self.OnResponse = Event()
        self.calls = []

    def _answer(self, mark, index, name, value, delay=0.01):
        def fire():
            for h in self.OnResponse.handlers:
                h(mark, index, name, None, value)
        threading.Timer(delay, fire).start()
        return True

    def SetLogType(self, t):
        pass

    def Open(self, mode):
        self.calls.append(("Open", mode))
        return self._answer(0, 1, "", "Connect")

    def Login(self, *args):
        self.calls.append(("Login", args))
        w = self.world
        status = NS(MsgCode=w.login_code, MsgContent="執行成功!" if w.login_code == "0001" else "失敗", Count=1)
        return self._answer(1, 0, "Login", NS(LoginStatus=status, LoginList=[NS(Account=ACCOUNT)]))

    def LogOut(self):
        self.calls.append(("LogOut",))

    def Close(self):
        pass

    def Dispose(self):
        pass

    def GetBankBalance(self, account, lng):
        return self._answer(1, 0, "GetBankBalance", NS(BankBalanceList=[NS(AvailableBalance=12345.0, Message="")]))

    def GetStoreSummary(self, account, lng):
        rows = [NS(StkCode="2330", StockQty=10, Price=1000.0, MarketPrice=1010.0, MarketAmt=10100.0, ReturnAmt=80.0)]
        return self._answer(1, 0, "GetStoreSummary", NS(StkStoreList=rows))

    def GetWatchListAll(self, account, quotes, lng):
        rows = [NS(StkCode=q.StockCode, DealPrice=1500.0 if q.MarketType == "TWSE" or q.StockCode != "6488" else 600.0,
                   OpenRefPrice=1.0, OpenPrice=1490.0, HighPrice=1510.0, LowPrice=1480.0, TotalVol=99,
                   BuyPrice=1495.0, SellPrice=1500.0, VolFlag=1)
                for q in quotes if q.MarketType == "TWSE" and q.StockCode != "6488"
                or q.MarketType == "TWOTC"]
        self.world.quote_markets.append([q.MarketType for q in quotes])
        return self._answer(1, 0, "GetWatchListAll", NS(QueryWatchList=rows))

    def SendStockOrder(self, account, orders, lng):
        o = orders[0]
        self.calls.append(("SendStockOrder", o))
        w = self.world
        if w.send_refused:
            return False
        if o.TradeKind == yx.TRADE_CANCEL:
            for r in w.book:
                if r.OrderNo == o.OrderNo:
                    r.OrderStatus = yx.ORDER_CANCELLED
            data = NS(ReplyCode=0, OrderNO=o.OrderNo, TradeDate=DAY, ErrNO="", Advisory="")
        elif w.reply_code:
            data = NS(ReplyCode=w.reply_code, OrderNO="", TradeDate=DAY, ErrNO="P201", Advisory="餘額不足")
        else:
            no = f"H{len(w.book) + 1:05d}"
            shares = o.OrderQty * (1 if o.APCode == yx.AP_INTRADAY_ODD else 1000)
            w.book.append(NS(OrderNo=no, TradeDate=DAY, CompanyNo=o.StkCode, BS=o.BuySell, Price=o.Price,
                             PriceFlag="2", AfterQty=shares, OkQty=0, OrderStatus=yx.ORDER_ACCEPTED,
                             APCode=o.APCode, BasketNo=o.BasketNo, Time_in_Force=o.Time_in_force,
                             OrderType="0", AcceptDate=DAY, AcceptTime=NS(bytHour=9, bytMin=30, bytSec=1),
                             CancelFlag="Y", ErrorMessage="", ErrorNo=""))
            data = NS(ReplyCode=0, OrderNO=no, TradeDate=DAY, ErrNO="", Advisory="")
        return self._answer(1, 0, "SendStockOrder",
                            NS(ResultCount=NS(MsgCode="0001", MsgContent="OK", Count=1), ResultList=[data]))

    def GetOrderTradeReport(self, not_show_cancel, account, lng):
        if self.world.report_silent:
            return True
        return self._answer(1, 0, "GetOrderTradeReport", NS(StkOrderList=list(self.world.book)))

    # helpers for tests
    def push_report(self, row):
        for h in self.OnResponse.handlers:
            h(2, 0, "RR_RealReport", None, row)


class World:
    def __init__(self):
        self.login_code = "0001"
        self.book = []
        self.reply_code = 0
        self.send_refused = False
        self.report_silent = False
        self.quote_markets = []


@pytest.fixture
def world(monkeypatch):
    w = World()
    spark = NS(Trader=lambda: FakeTrader(w), StockOrder=NS, Quote=NS, List=GenericList(),
               enumEnvironmentMode=NS(UAT="UAT", PROD="PROD"), enumLangType=NS(UTF8="UTF8"),
               enumLogType=NS(COMMON="COMMON"), enumMarketType=NS(TWSE="TWSE", TWOTC="TWOTC"))
    monkeypatch.setattr(mod._spark, "load", lambda dll_dir: spark)
    monkeypatch.setattr(mod, "MIN_QUERY_INTERVAL", 0.0)
    return w


CONFIG = dict(account=ACCOUNT, password="1234", cert_path="/c.pfx", cert_pass="yuanta",
              dll_dir="/spark", timeout=2)


@pytest.fixture
def api(world, tmp_path):
    a = mod.YuantaBrokerAPI(**CONFIG, mirror_db_path=str(tmp_path / "y.db"))
    assert a.connect()
    yield a
    a.disconnect()


def order(**kw):
    base = dict(product=Product("2330"), action=OrderAction.BUY, price=1000.0, quantity=1,
                price_type=PriceType.LMT, order_type=OrderType.ROD, order_lot=OrderLot.IntraDayOdd)
    base.update(kw)
    return Order(**base)


class TestConstruction:
    def test_missing_settings_are_named(self, world, monkeypatch):
        monkeypatch.setattr(mod.sys, "platform", "linux")
        with pytest.raises(ValueError, match="account.*dll_dir.*cert_path"):
            mod.YuantaBrokerAPI(password="x")

    def test_windows_needs_no_certificate(self, world, monkeypatch):
        monkeypatch.setattr(mod.sys, "platform", "win32")
        mod.YuantaBrokerAPI(account=ACCOUNT, password="x", dll_dir="/d")

    def test_the_test_environment_is_the_default_and_others_are_refused(self, world):
        assert mod.YuantaBrokerAPI(**CONFIG).environment == "UAT"
        with pytest.raises(ValueError, match="UAT or PROD"):
            mod.YuantaBrokerAPI(**CONFIG, environment="dev")


class TestConnect:
    def test_login_with_a_certificate_sends_it_first(self, api):
        assert ("Open", "UAT") in api.trader.calls
        login = next(c for c in api.trader.calls if c[0] == "Login")
        assert login[1] == ("/c.pfx", "yuanta", ACCOUNT, "1234")

    def test_a_refused_login_gives_false(self, world, tmp_path):
        world.login_code = "0102"
        a = mod.YuantaBrokerAPI(**CONFIG, mirror_db_path=str(tmp_path / "y.db"))
        assert a.connect() is False and not a.is_connected()

    def test_a_missing_dll_gives_false(self, world, tmp_path, monkeypatch):
        def no_dll(d):
            raise mod._spark.SparkUnavailable("YuantaSparkAPI.dll not found")
        monkeypatch.setattr(mod._spark, "load", no_dll)
        assert mod.YuantaBrokerAPI(**CONFIG, mirror_db_path=str(tmp_path / "y.db")).connect() is False

    def test_disconnect_logs_out(self, api):
        api.disconnect()
        assert ("LogOut",) in api.trader.calls and not api.is_connected()


class TestBridge:
    def test_a_call_without_a_response_times_out(self, api, world):
        world.report_silent = True
        api.timeout = 0.2
        with pytest.raises(RuntimeError, match="no response"):
            api._report()

    def test_a_call_refused_at_once_raises(self, api, world):
        world.send_refused = True
        r = api.buy_stock("2330", 1, 1000.0)
        assert r.status == OrderStatus.REJECTED and "refused by the Spark API" in r.message

    def test_an_error_response_with_no_function_name_fails_the_waiting_call(self, api):
        def send():
            threading.Timer(0.01, lambda: api._on_response(1, 5, "", None, "功能代碼錯誤或權限不足")).start()
            return True
        with pytest.raises(RuntimeError, match="權限不足"):
            api._call("GetBankBalance", send)


class TestAccount:
    def test_balance_positions_and_quotes(self, api):
        assert api.get_balance() == 12345.0
        [p] = api.get_positions()
        assert (p.symbol, p.quantity, p.avg_cost, p.current_price, p.unrealized_pnl) == \
            ("2330", 10, 1000.0, 1010.0, 80.0)
        assert api.get_snapshots([Product("2330")])[0].close == 1500.0

    def test_an_otc_symbol_is_asked_again_as_otc(self, api, world):
        assert api.get_snapshots([Product("6488")])[0].close == 600.0
        assert world.quote_markets == [["TWSE"], ["TWOTC"]]


class TestOrders:
    def test_an_odd_lot_buy_is_sent_with_the_cjtrade_id(self, api, world):
        r = api.buy_stock("2330", 3, 1000.0)
        sent = next(c[1] for c in api.trader.calls if c[0] == "SendStockOrder")
        assert (sent.APCode, sent.OrderQty, sent.BuySell, sent.PriceFlag, sent.Time_in_force) == \
            (yx.AP_INTRADAY_ODD, 3, "B", " ", "0")
        assert sent.BasketNo == r.linked_order and r.status == OrderStatus.COMMITTED_WAIT_MATCHING
        assert mod.get_cj_order_id_from_db(conn=api.db, bkr_order_id="2026/11/27:H00001") == r.linked_order

    def test_a_board_lot_market_order_is_sent_in_lots_at_market(self, api):
        api.place_order(order(order_lot=OrderLot.Common, quantity=2, price_type=PriceType.MKT,
                              price=None, order_type=OrderType.IOC))
        sent = next(c[1] for c in api.trader.calls if c[0] == "SendStockOrder")
        assert (sent.APCode, sent.OrderQty, sent.PriceFlag, sent.Price, sent.Time_in_force) == \
            (yx.AP_BOARD_LOT, 2, "M", 0.0, "3")

    def test_an_order_breaking_the_rules_is_not_sent(self, api):
        r = api.place_order(order(quantity=1000))
        assert r.status == OrderStatus.REJECTED and "999" in r.message
        assert not [c for c in api.trader.calls if c[0] == "SendStockOrder"]

    def test_a_refused_order_carries_yuantas_reason(self, api, world):
        world.reply_code = 1
        r = api.buy_stock("2330", 1, 1000.0)
        assert r.status == OrderStatus.REJECTED and "P201" in r.message and "餘額不足" in r.message

    def test_sync_reads_partial_and_filled_orders(self, api, world):
        a = api.buy_stock("2330", 5, 1000.0)
        b = api.buy_stock("2330", 1, 1000.0)
        world.book[0].OkQty = 2
        world.book[1].OkQty, world.book[1].AfterQty = 1, 1
        assert [(s.linked_order, s.status) for s in api.sync_state()] == [(a.linked_order, OrderStatus.PARTIAL)]
        assert api._status_cache[b.linked_order] == OrderStatus.FILLED

    def test_orders_placed_elsewhere_are_listed_but_not_synced(self, api, world):
        api.buy_stock("2330", 1, 1000.0)
        world.book.append(NS(**{**vars(world.book[0]), "OrderNo": "X99999", "BasketNo": ""}))
        assert len(api.sync_state()) == 1
        assert [t.id for t in api.list_orders()][1] == "N/A"

    def test_cancel_sends_trade_kind_4_for_the_order(self, api, world):
        r = api.buy_stock("2330", 1, 1000.0)
        c = api.cancel_order(r.linked_order)
        sent = [c2[1] for c2 in api.trader.calls if c2[0] == "SendStockOrder"][-1]
        assert c.status == OrderStatus.CANCELLED
        assert (sent.TradeKind, sent.OrderNo, sent.StkCode, sent.TradeDate) == \
            (yx.TRADE_CANCEL, "H00001", "2330", "2026/11/27")

    def test_a_filled_or_uncancellable_order_is_not_cancelled(self, api, world):
        r = api.buy_stock("2330", 1, 1000.0)
        world.book[0].CancelFlag = "N"
        assert "cannot be cancelled now" in api.cancel_order(r.linked_order).message
        world.book[0].OkQty, world.book[0].AfterQty = 1, 1
        assert "FILLED" in api.cancel_order(r.linked_order).message
        assert "not found" in api.cancel_order("nope").message


class TestReports:
    def test_fill_reports_are_partial_until_complete(self, api, world):
        events = []
        api.register_order_callback(events.append)
        r = api.buy_stock("2330", 5, 1000.0)
        fill = NS(RptType=yx.RPT_STOCK_FILL, BasketNo=r.linked_order, OrderNo="H00001", OrderDate=DAY,
                  CompanyNo="2330", BS="B", Price=999.0, OrderQty=2, APCode=4, OrderStatus=8)
        api.trader.push_report(fill)
        api.trader.push_report(NS(**{**vars(fill), "OrderQty": 3}))
        assert [e.new_status for e in events] == [OrderStatus.PARTIAL, OrderStatus.FILLED]
        assert [e.filled_quantity for e in events] == [2, 3] and events[1].filled_value == 2997.0

    def test_order_reports_carry_cancel_and_failure(self, api):
        events = []
        api.register_order_callback(events.append)
        r = api.buy_stock("2330", 1, 1000.0)
        base = dict(RptType=yx.RPT_STOCK_ORDER, BasketNo=r.linked_order, OrderNo="H00001", OrderDate=DAY,
                    CompanyNo="2330", BS="B", Price=1000.0, OrderQty=1, APCode=4)
        api.trader.push_report(NS(**base, OrderStatus=3))       # cancel failed: not an event
        api.trader.push_report(NS(**base, OrderStatus=2))
        api.trader.push_report(NS(**base, OrderStatus=1))
        assert [e.new_status for e in events] == [OrderStatus.CANCELLED, OrderStatus.REJECTED]

    def test_reports_for_other_orders_and_failing_callbacks_are_harmless(self, api):
        api.register_order_callback(lambda e: 1 / 0)
        api.trader.push_report(NS(RptType=yx.RPT_STOCK_ORDER, BasketNo="", OrderNo="Z1", OrderDate=DAY,
                                  OrderStatus=0))
        r = api.buy_stock("2330", 1, 1000.0)
        api.trader.push_report(NS(RptType=yx.RPT_STOCK_ORDER, BasketNo=r.linked_order, OrderNo="H00001",
                                  OrderDate=DAY, CompanyNo="2330", BS="B", Price=1.0, OrderQty=1,
                                  APCode=4, OrderStatus=2))


def test_account_client_builds_the_yuanta_adapter(world, tmp_path):
    from cjtrade.pkgs.brokers.account_client import AccountClient
    from cjtrade.pkgs.brokers.account_client import BrokerType
    client = AccountClient(BrokerType.YUANTA, **CONFIG, mirror_db_path=str(tmp_path / "y.db"))
    assert isinstance(client.broker_api, mod.YuantaBrokerAPI)
