import os

import shioaji as sj
from dotenv import load_dotenv

load_dotenv()

api = sj.Shioaji(simulation=False)
api.login(
    api_key=os.environ.get("API_KEY", ""),
    secret_key=os.environ.get("SECRET_KEY", ""),
)
api.activate_ca(
    ca_path=os.environ.get("CA_CERT_PATH", ""),
    ca_passwd=os.environ.get("CA_PASSWORD", ""),
)

def get_unfilled_trades(api):
    api.update_status()
    trades = api.list_trades()
    for trade in trades:
        if trade.status.status != sj.constant.Status.Filled and trade.status.status != sj.constant.Status.Cancelled:
            return trade

# print(len(trades))

trade = get_unfilled_trades(api)
assert trade is not None, "No unfilled trades found"
initial_qty = trade.order.quantity
initial_cancel_qty = trade.status.cancel_quantity
print(f"Trade {trade.order.id}: quantity={initial_qty}, cancel_quantity={initial_cancel_qty}")
print(f"Effective quantity: {initial_qty - initial_cancel_qty}")
print(f"Reducing by 1...")

api.update_order(trade, qty=1)  # reduce quantity by 1
api.update_status()
trade = get_unfilled_trades(api)
assert trade is not None, "No unfilled trades found after update"
print(f"After update: quantity={trade.order.quantity}, cancel_quantity={trade.status.cancel_quantity}")
print(f"Effective quantity: {trade.order.quantity - trade.status.cancel_quantity}")

# Verify the cancel_quantity increased by 1
assert trade.status.cancel_quantity == initial_cancel_qty + 1, \
    f"Expected cancel quantity to be {initial_cancel_qty + 1}, got {trade.status.cancel_quantity}"
print("✅ Successfully reduced order quantity by 1")

api.logout()
