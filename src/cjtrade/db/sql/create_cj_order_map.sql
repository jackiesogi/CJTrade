
CREATE TABLE IF NOT EXISTS CJ_OrderMap (
    cj_order_id             TEXT PRIMARY KEY,
    broker_order_id         TEXT NOT NULL,
    broker                  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ordermap_broker_order_id
ON CJ_OrderMap(broker_order_id);