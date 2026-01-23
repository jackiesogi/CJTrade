-- This is sqlite3-flavored SQL
-- Ledger of trade fills
CREATE TABLE IF NOT EXISTS fills (
    fill_id             TEXT PRIMARY KEY,         -- 本地 or broker fill id
    order_id            TEXT,                      -- nullable

    user_id             TEXT NOT NULL,

    broker              TEXT NOT NULL,

    product_id          TEXT NOT NULL,
    side                TEXT NOT NULL,
    filled_price        REAL NOT NULL,
    filled_quantity     INTEGER NOT NULL,
    filled_time         TEXT NOT NULL,             -- exchange timestamp
    received_at         TEXT NOT NULL              -- client receive time

    -- source              TEXT NOT NULL DEFAULT 'BROKER'  -- BROKER / SYNC / MANUAL
    -- Reserved / Optional fields
    -- broker_trade_id     TEXT,                      -- optional
    -- raw_response        TEXT                       -- optional JSON
);

CREATE INDEX IF NOT EXISTS idx_fills_user_product
ON fills (user_id, product_id);

CREATE INDEX IF NOT EXISTS idx_fills_order
ON fills (order_id);

CREATE INDEX IF NOT EXISTS idx_fills_filled_time
ON fills (filled_time);


-- Create 5 dummy fills for testing
-- INSERT INTO fills (fill_id, order_id, user_id, broker, product_id, side, filled_price, filled_quantity, filled_time, received_at) VALUES
-- ('fill_001', 'order_001', 'user_123', 'sinopac', 'AAPL', 'BUY', 150.0, 10, '2024-01-01T10:00:00Z', '2024-01-01T10:00:01Z'),
-- ('fill_002', 'order_001', 'user_123', 'sinopac', 'AAPL', 'BUY', 151.0, 5, '2024-01-01T10:05:00Z', '2024-01-01T10:05:01Z'),
-- ('fill_003', 'order_002', 'user_123', 'sinopac', 'AAPL', 'SELL', 152.0, 8, '2024-01-02T11:00:00Z', '2024-01-02T11:00:01Z'),
-- ('fill_004', 'order_003', 'user_456', 'sinopac', 'TSLA', 'BUY', 700.0, 3, '2024-01-03T12:00:00Z', '2024-01-03T12:00:01Z'),
-- ('fill_005', 'order_003', 'user_456', 'sinopac', 'TSLA', 'BUY', 705.0, 2, '2024-01-03T12:05:00Z', '2024-01-03T12:05:01Z');