from cjtrade.pkgs.models.product import Product


def unlikely_fill_buy_price(client, symbol):
    return round(client.get_snapshots([Product(symbol)])[0].close * 0.91, 2)

def unlikely_fill_sell_price(client, symbol):
    return round(client.get_snapshots([Product(symbol)])[0].close * 1.09, 2)

def likely_fill_buy_price(client, symbol):
    return round(client.get_snapshots([Product(symbol)])[0].close * 1.09, 2)

def likely_fill_sell_price(client, symbol):
    return round(client.get_snapshots([Product(symbol)])[0].close * 0.91, 2)
