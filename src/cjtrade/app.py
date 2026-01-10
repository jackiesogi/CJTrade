# main.py (skeleton, put under src/cjtrade or project root)
import asyncio
import signal
import logging
import random
import os
#import cjtrade.tasks
from threading import Thread
from datetime import datetime, timedelta
from dotenv import load_dotenv

import cjtrade.modules.analysis as ANALYSIS
import cjtrade.modules.account as ACCOUNT
import cjtrade.modules.database as DATABASE
import cjtrade.modules.stockdata as STOCK
import cjtrade.modules.candidate as CAND
import cjtrade.modules.ui.web as WEB

# TODO: Gradually take new modules from service_oriented branch to here to make it a system.

# CONFIG (tune these)
log = logging.getLogger("cjtrade.main")
logging.basicConfig(
    level=logging.DEBUG,
    format="[%(asctime)s] %(levelname)-8s:  %(message)s"
)

PRICE_INTERVAL_SECONDS = 60        # price fetch interval (for daily/1min strategies set larger)
DECISION_INTERVAL_SECONDS = 30     # fusion / staging interval
INVENTORY_UPDATE_SECONDS = 300     # update holdings backup
HEALTHCHECK_INTERVAL_SECONDS = 15
DB_PATH = "cjtrade-stock.db"
SHUTDOWN = False                   # for graceful shutdown

# Global variables will be initialized in main()
bank = None
database = None
fetcher = None
cand_manager = None


# queues for intra-process communication
# SnapshotBatch = {
#     "ts": datetime,
#     "snapshots": { "2330": snapshot_obj, "0050": snapshot_obj, ... },
#     "provider": "broker" | "yahoo"
# }
price_queue = asyncio.Queue(maxsize=100)       # snapshots from fetch_data -> consumed by Strategy

# Signal = {
#     "symbol": "2330",
#     "side": "buy" or "sell",
#     "qty": 100,
#     "price": 123.4,         # optional: limit price
#     "ts": datetime,
#     "tech_score": 0.72,
#     "reason": "turtle breakout"
# }
signal_queue = asyncio.Queue(maxsize=100)      # signals from Strategy -> DecisionFusion

# StagingOrder = {
#     "staging_id": int,   # 對 DB 的 reference
#     "symbol": "2330",
#     "side": "buy",
#     "qty": 100,
#     "price": 123.4,
#     "final_score": 0.82,
#     "created_by": "fusion" or "ui",
#     "auto": False
# }
order_staging_queue = asyncio.Queue()          # for Executor


async def price_fetcher_thread(database, fetcher, candidate_manager):
    """Periodic fetch price snapshots and push to price_queue and DB."""

    global price_fetcher_thread_alive

    while not SHUTDOWN:
        try:
            symbols = candidate_manager.GetTrackedSymbols(database)      # inventory + candidate pool

            for source, symlist in symbols.items():
                # print(f"Source: {source}")
                for sym in symlist:
                    snapshot = fetcher.GetPriceData(sym)          # should be quick; if heavy, make async
                    database.SaveSnapshot(snapshot)

            # push to queue non-blocking
            try:
                price_queue.put_nowait((datetime.utcnow(), snapshot))
            except asyncio.QueueFull:
                log.warning("price_queue full, dropping snapshot")
        except Exception as e:
            log.exception("price_fetcher error: %s", e)
            # Notifier.alert("price_fetcher error", str(e))
        await asyncio.sleep(PRICE_INTERVAL_SECONDS)


# async def strategy_loop():
#     """Consume price snapshots, generate strategy signals."""
#     while not SHUTDOWN:
#         ts, snapshots = await price_queue.get()
#         try:
#             # for each snapshot run technical rules
#             signals = []
#             for sym, snap in snapshots.items():
#                 sig = analysis.RunTechnicalRules(sym, snap, method=auto)  # returns None or dict(signal)
#                 if sig:
#                     signals.append(sig)
#             # push signals to fusion queue
#             for s in signals:
#                 await signal_queue.put(s)
#         except Exception as e:
#             log.exception("strategy_loop error: %s", e)
#         finally:
#             price_queue.task_done()

# async def decision_fusion_loop():
#     """Consume signals and AI scores, perform fusion, push to staging or direct exec."""
#     while not SHUTDOWN:
#         try:
#             sig = await signal_queue.get()
#             sym = sig['symbol']
#             tech_score = sig.get('score', 0.0)
#             ai_score = DB.get_latest_ai_score(sym) or 0.0
#             flow_score = DB.get_flow_score(sym) or 0.0

#             final_score = DecisionFusion.compute(tech_score, ai_score, flow_score)
#             if DecisionFusion.should_auto_execute(final_score):
#                 # small auto-eecution permitted
#                 order = DecisionFusion.form_order(sig, final_score)
#                 await Executor.execute_order(order, auto=True)  # executor will place and update DB
#             else:
#                 staging = DecisionFusion.form_staging_order(sig, final_score)
#                 DB.insert_order_staging(staging)
#                 Notifier.notify_pending_order(staging)
#             signal_queue.task_done()
#         except Exception as e:
#             log.exception("decision_fusion error: %s", e)
#             await asyncio.sleep(1)

# TODO: Consider event-driven update (Buy / Sell / Dividend / Corporate Action)
async def inventory_update_thread(database, account):
    """Periodically refresh inventory from 永豐"""
    global inventory_update_thread_alive
    while not SHUTDOWN:
        try:
            inventory = account.FetchInventory()  # sync or async depending on your wrapper
            for inv in inventory:
                database.SaveInventory(inv)
        except Exception as e:
            log.exception("inventory_update error: %s", e)
            # Notifier.alert("inventory_update error", str(e))
        await asyncio.sleep(INVENTORY_UPDATE_SECONDS)


async def healthcheck_thread(database, bank):
    while not SHUTDOWN:
        # check heartbeats, DB connection, broker connection
        try:
            # healthy = DB.healthcheck() and AA.is_connected()
            healthy = database.Healthcheck() and bank.Healthcheck()
            if not healthy:
                print('DB not healthy')
                # Notifier.alert("Healthcheck failed")
        except Exception as e:
            log.exception("healthcheck error: %s", e)
        await asyncio.sleep(HEALTHCHECK_INTERVAL_SECONDS)


# async def schedule_aicrawl():
#     """Run AISuggestion tasks at scheduled times (pre/post market) in background worker."""
#     # This can also be delegated to an external scheduler like celery beat
#     while not SHUTDOWN:
#         now = datetime.now()
#         # Example: if time is 08:00 run premarket, 16:30 run postmarket
#         if now.hour == 8 and now.minute == 0:
#             asyncio.create_task(AISugg.run_pre_market())
#         if now.hour == 16 and now.minute == 30:
#             asyncio.create_task(AISugg.run_post_market())
#         await asyncio.sleep(30)

def _signal_handler(sig):
    global SHUTDOWN
    log.info("received signal %s, shutting down...", sig)
    SHUTDOWN = True




async def main():
    global bank, database, fetcher, cand_manager

    # Initialize components
    load_dotenv()
    keyobj = ACCOUNT.KeyObject(
        api_key=os.environ["API_KEY"],
        secret_key=os.environ["SECRET_KEY"],
        ca_path=os.environ["CA_CERT_PATH"],
        ca_password=os.environ["CA_PASSWORD"]
    )

    bank = ACCOUNT.AccountAccess(keyobj, simulation=True)
    database = DATABASE.DatabaseConnection(DB_PATH)
    fetcher = STOCK.PriceFetcher()
    cand_manager = CAND.CandidateManager(bank)

    # register signal handlers
    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(s, lambda s=s: _signal_handler(s))

    # start background tasks
    tasks = [
        asyncio.create_task(price_fetcher_thread(database, fetcher, cand_manager), name="price_fetcher"),
        # asyncio.create_task(strategy_loop(), name="strategy"),
        # asyncio.create_task(decision_fusion_loop(), name="decision_fusion"),
        asyncio.create_task(inventory_update_thread(database, bank), name="inventory_update"),
        asyncio.create_task(healthcheck_thread(database, bank), name="healthcheck"),
        # asyncio.create_task(schedule_aicrawl(), name="scheduler_aicrawl"),
    ]

    ## Start Flask in separate thread (Uncomment when all stub is done) ##
    #flask_thread = Thread(target=WEB.run_flask, kwargs={'host': '0.0.0.0', 'port': 5000}, daemon=True)
    #flask_thread.start()
    ######################################################################


    # wait until shutdown requested
    while not SHUTDOWN:
        await asyncio.sleep(1)

    # graceful shutdown: cancel tasks and wait
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    # final flush and logout
    database.Close()
    bank.Logout()
    log.info("shutdown complete")
