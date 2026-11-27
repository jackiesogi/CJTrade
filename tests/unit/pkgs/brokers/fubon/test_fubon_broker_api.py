"""FubonBrokerAPI against a fake fubon_neo session.

`FubonSDK` is replaced by FakeSDK, so no login or network call can happen.
The fake keeps today's order book the way Fubon reports it, which is how these
tests check what the adapter sends and how it reads the replies.
"""
from types import SimpleNamespace as NS

import pytest
from cjtrade.pkgs.brokers.fubon import fubon_broker_api as mod
from cjtrade.pkgs.models.order import OrderStatus
from fubon_neo.constant import BSAction
from fubon_neo.constant import MarketType
from fubon_neo.constant import TimeInForce

CREDS = dict(personal_id="A123456789", api_key="fake-key", cert_path="fake.pfx", cert_pass="pw")


def ok(data):
    return NS(is_success=True, message=None, data=data)


def fail(message):
    return NS(is_success=False, message=message, data=None)


class FakeStock:
    def __init__(self, sdk):
        self.sdk = sdk
        self.book = []          # today's OrderResults
        self.sent = []          # repr of every Order sent
        self.place_reply = None
        self.cancel_reply = None
        self.quote = NS(symbol="2330", market="TAIEX", open_price=1.0, high_price=2.0, low_price=0.5,
                        last_price=1.5, total_volume=10, bid_price=1.4, bid_volume=3,
                        ask_price=1.6, ask_volume=4)

    def place_order(self, account, order, unblock=None):
        self.sent.append(repr(order))
        if self.place_reply is not None:
            return self.place_reply
        text = repr(order)
        qty = int(text.split("quantity: ")[1].split(",")[0])
        odd = "IntradayOdd" in text
        r = NS(status=10, filled_qty=0, after_qty=qty, quantity=qty, seq_no=f"{len(self.book) + 1:011d}",
               order_no=f"x{len(self.book) + 1:04d}", date="2026/11/27",
               market_type=MarketType.IntradayOdd if odd else MarketType.Common,
               buy_sell=BSAction.Sell if "Sell" in text else BSAction.Buy, stock_no="2330",
               after_price=1.5, price=1.5, price_type=None, after_price_type=None,
               time_in_force=TimeInForce.ROD, last_time="10:00:00", filled_money=0,
               user_def=text.split('user_def: "')[1].split('"')[0], error_message=None)
        self.book.append(r)
        return ok(r)

    def get_order_results(self, account):
        return ok(list(self.book))

    def cancel_order(self, account, target, unblock=None):
        if self.cancel_reply is not None:
            return self.cancel_reply
        target.status = 30 if not target.filled_qty else 40
        target.after_qty = target.filled_qty
        return ok(target)

    def query_symbol_quote(self, account, symbol, market_type=None):
        self.sdk.quote_market = market_type
        return ok(self.quote)


class FakeSDK:
    instances = []

    def __init__(self, url=None):
        self.url = url
        self.stock = FakeStock(self)
        self.accounting = NS(
            bank_remain=lambda a: ok(NS(balance="123,456", available_balance="100000")),
            unrealized_gains_and_loses=lambda a: ok([NS(stock_no="2330", tradable_qty=5,
                                                        cost_price=1000.0, unrealized_profit=50,
                                                        unrealized_loss=0)]))
        self.login_reply = ok([NS(name="n", account="26", branch_no="6460", account_type="stock"),
                               NS(name="n", account="28", branch_no="6460", account_type="stock")])
        self.logins = []
        self.callbacks = {}
        self.logged_out = False
        FakeSDK.instances.append(self)

    def apikey_login(self, *args):
        self.logins.append(("apikey", args))
        return self.login_reply

    def login(self, *args):
        self.logins.append(("password", args))
        return self.login_reply

    def logout(self):
        self.logged_out = True

    def set_on_order(self, cb):
        self.callbacks["order"] = cb

    def set_on_order_changed(self, cb):
        self.callbacks["changed"] = cb

    def set_on_filled(self, cb):
        self.callbacks["filled"] = cb

    def set_on_event(self, cb):
        self.callbacks["event"] = cb


@pytest.fixture(autouse=True)
def fake_sdk(monkeypatch):
    FakeSDK.instances.clear()
    monkeypatch.setattr(mod, "FubonSDK", FakeSDK)


@pytest.fixture
def api(tmp_path):
    a = mod.FubonBrokerAPI(**CREDS, mirror_db_path=str(tmp_path / "fubon.db"))
    assert a.connect()
    yield a
    a.disconnect()


def sdk(api):
    return api.sdk


class TestConstruction:
    def test_missing_credentials_are_named(self):
        with pytest.raises(ValueError, match="personal_id.*api_key or password"):
            mod.FubonBrokerAPI(cert_path="x.pfx")

    def test_a_password_is_enough_instead_of_an_api_key(self, tmp_path):
        a = mod.FubonBrokerAPI(personal_id="A1", password="pw", cert_path="x.pfx",
                               mirror_db_path=str(tmp_path / "f.db"))
        assert a.connect() and a.sdk.logins[0][0] == "password"

    def test_a_server_url_is_passed_to_the_sdk(self, tmp_path):
        a = mod.FubonBrokerAPI(**CREDS, url="wss://example.test", mirror_db_path=str(tmp_path / "f.db"))
        assert a.sdk.url == "wss://example.test"


class TestConnect:
    def test_api_key_login_sends_id_key_and_certificate(self, api):
        assert sdk(api).logins == [("apikey", ("A123456789", "fake-key", "fake.pfx", "pw"))]
        assert api.is_connected() and api.account.account == "26"

    def test_a_chosen_account_number_is_used(self, tmp_path):
        a = mod.FubonBrokerAPI(**CREDS, account="28", mirror_db_path=str(tmp_path / "f.db"))
        assert a.connect() and a.account.account == "28"

    def test_a_refused_login_gives_false(self, tmp_path, monkeypatch):
        a = mod.FubonBrokerAPI(**CREDS, mirror_db_path=str(tmp_path / "f.db"))
        a.sdk.login_reply = fail("The cert file location my be wrong 38")
        assert a.connect() is False and not a.is_connected()

    def test_no_stock_account_gives_false(self, tmp_path):
        a = mod.FubonBrokerAPI(**CREDS, mirror_db_path=str(tmp_path / "f.db"))
        a.sdk.login_reply = ok([NS(account="9", account_type="futopt")])
        assert a.connect() is False

    def test_connecting_installs_the_report_callbacks(self, api):
        assert set(sdk(api).callbacks) == {"order", "changed", "filled", "event"}

    def test_disconnect_logs_out(self, api):
        api.disconnect()
        assert sdk(api).logged_out and not api.is_connected()

    def test_every_call_needs_a_connection(self, tmp_path):
        a = mod.FubonBrokerAPI(**CREDS, mirror_db_path=str(tmp_path / "f.db"))
        for call in (a.get_balance, a.get_positions, a.sync_state, a.list_orders):
            with pytest.raises(ConnectionError):
                call()


class TestAccount:
    def test_balance_is_the_bank_balance(self, api):
        assert api.get_balance() == 123456.0

    def test_positions_come_from_unrealised_pnl(self, api):
        [p] = api.get_positions()
        assert (p.symbol, p.quantity, p.avg_cost, p.unrealized_pnl) == ("2330", 5, 1000.0, 50.0)

    def test_a_refused_query_raises_with_fubons_message(self, api):
        sdk(api).accounting.bank_remain = lambda a: fail("busy")
        with pytest.raises(RuntimeError, match="busy"):
            api.get_balance()

    def test_quotes_use_the_odd_lot_book_when_asked(self, api):
        from cjtrade.pkgs.models.product import Product
        assert api.get_snapshots([Product("2330")])[0].close == 1.5
        api.get_bid_ask(Product("2330"), intraday_odd=True)
        assert str(sdk(api).quote_market) == "MarketType.IntradayOdd"


class TestPlaceOrder:
    def test_an_odd_lot_buy_is_sent_as_shares_and_mapped(self, api):
        r = api.buy_stock("2330", 3, 1.5)
        sent = sdk(api).stock.sent[0]
        assert "buy_sell: Buy" in sent and "quantity: 3" in sent and "IntradayOdd" in sent
        assert r.status == OrderStatus.COMMITTED_WAIT_MATCHING and r.linked_order
        assert mod.get_cj_order_id_from_db(conn=api.db, bkr_order_id="2026/11/27:00000000001") \
            == r.linked_order

    def test_a_board_lot_sell_is_sent_in_shares(self, api):
        api.sell_stock("2330", 2, 1.5, intraday_odd=False)
        sent = sdk(api).stock.sent[0]
        assert "buy_sell: Sell" in sent and "quantity: 2000" in sent and "market_type: Common" in sent

    def test_an_order_breaking_fubons_rules_is_not_sent(self, api):
        r = api.buy_stock("2330", 1000, 1.5)
        assert r.status == OrderStatus.REJECTED and "999" in r.message
        assert sdk(api).stock.sent == []

    def test_a_refused_order_is_rejected_with_fubons_message(self, api):
        sdk(api).stock.place_reply = fail("餘額不足")
        r = api.buy_stock("2330", 1, 1.5)
        assert r.status == OrderStatus.REJECTED and "餘額不足" in r.message


class TestSyncAndList:
    def test_sync_returns_open_orders_and_skips_finished_ones(self, api):
        a = api.buy_stock("2330", 1, 1.5)
        b = api.buy_stock("2330", 2, 1.5)
        sdk(api).stock.book[1].status = 50
        sdk(api).stock.book[1].filled_qty = 2
        assert [r.linked_order for r in api.sync_state()] == [a.linked_order]
        assert b.linked_order not in [r.linked_order for r in api.sync_state()]

    def test_orders_placed_outside_cjtrade_are_ignored_by_sync_but_listed(self, api):
        api.buy_stock("2330", 1, 1.5)
        stranger = NS(**vars(sdk(api).stock.book[0]))
        stranger.seq_no, stranger.user_def = "00000000099", None
        sdk(api).stock.book.append(stranger)
        assert len(api.sync_state()) == 1
        assert [t.id for t in api.list_orders()][1] == "N/A"

    def test_a_failed_query_gives_an_empty_list(self, api):
        sdk(api).stock.get_order_results = lambda a: fail("timeout")
        assert api.sync_state() == [] and api.list_orders() == []

    def test_listed_orders_use_cjtrade_spellings(self, api):
        api.sell_stock("2330", 2, 1.5, intraday_odd=False)
        [t] = api.list_orders()
        assert (t.action, t.quantity, t.order_lot) == ("SELL", 2, "Common")

    def test_an_order_is_found_by_its_user_def_when_the_map_is_lost(self, api):
        r = api.buy_stock("2330", 1, 1.5)
        api.db.execute("DELETE FROM CJ_OrderMap")
        with api._lock:
            api._orders[r.linked_order] = NS(seq_no=None)
        assert [s.linked_order for s in api.sync_state()] == [r.linked_order]


class TestCancel:
    def test_an_open_order_is_cancelled(self, api):
        r = api.buy_stock("2330", 1, 1.5)
        c = api.cancel_order(r.linked_order)
        assert c.status == OrderStatus.CANCELLED and c.linked_order == r.linked_order

    def test_a_filled_order_cannot_be_cancelled(self, api):
        r = api.buy_stock("2330", 1, 1.5)
        sdk(api).stock.book[0].status, sdk(api).stock.book[0].filled_qty = 50, 1
        c = api.cancel_order(r.linked_order)
        assert c.status == OrderStatus.REJECTED and "FILLED" in c.message

    def test_an_unknown_order_is_rejected(self, api):
        assert "not found" in api.cancel_order("nope").message

    def test_a_refused_cancel_is_rejected(self, api):
        r = api.buy_stock("2330", 1, 1.5)
        sdk(api).stock.cancel_reply = fail("刪單失敗")
        c = api.cancel_order(r.linked_order)
        assert c.status == OrderStatus.REJECTED and "刪單失敗" in c.message

    def test_cancelling_a_partly_filled_order_cancels_the_rest(self, api):
        r = api.buy_stock("2330", 5, 1.5)
        sdk(api).stock.book[0].filled_qty = 2
        c = api.cancel_order(r.linked_order)
        assert c.status == OrderStatus.CANCELLED and c.metadata["filled_qty"] == 2


class TestReports:
    def test_fills_are_partial_until_the_order_is_complete(self, api):
        events = []
        api.register_order_callback(events.append)
        r = api.buy_stock("2330", 5, 1.5)
        fill = NS(seq_no="00000000001", date="2026/11/27", filled_qty=2, filled_price=1.5,
                  stock_no="2330", buy_sell=BSAction.Buy, user_def=None)
        sdk(api).callbacks["filled"](None, fill)
        sdk(api).callbacks["filled"](None, NS(**{**vars(fill), "filled_qty": 3}))
        assert [e.new_status for e in events] == [OrderStatus.PARTIAL, OrderStatus.FILLED]
        assert [e.filled_quantity for e in events] == [2, 3]
        assert events[0].order_id == r.linked_order and events[1].old_status == OrderStatus.PARTIAL
        assert events[1].filled_value == 4.5

    def test_an_order_report_carries_the_new_status(self, api):
        events = []
        api.register_order_callback(events.append)
        r = api.buy_stock("2330", 1, 1.5)
        report = NS(**vars(sdk(api).stock.book[0]))
        report.status = 30
        sdk(api).callbacks["changed"](None, report)
        assert events[-1].new_status == OrderStatus.CANCELLED and events[-1].order_id == r.linked_order

    def test_reports_for_other_orders_and_failing_callbacks_are_harmless(self, api):
        def boom(event):
            raise RuntimeError("x")
        api.register_order_callback(boom)
        sdk(api).callbacks["order"](None, NS(seq_no="999", date="2026/11/27", user_def=None))
        api.buy_stock("2330", 1, 1.5)
        sdk(api).callbacks["order"](None, sdk(api).stock.book[0])   # boom is logged, not raised


class TestIdentity:
    def test_the_broker_is_fubon_and_runs_on_the_wall_clock(self, api):
        t = api.get_market_time()
        assert api.get_broker_name() == "fubon"
        assert t["playback_speed"] == 1.0 and t["paused"] is False


def test_account_client_builds_the_fubon_adapter(tmp_path):
    from cjtrade.pkgs.brokers.account_client import AccountClient
    from cjtrade.pkgs.brokers.account_client import BrokerType
    client = AccountClient(BrokerType.FUBON, **CREDS, mirror_db_path=str(tmp_path / "f.db"))
    assert isinstance(client.broker_api, mod.FubonBrokerAPI)
