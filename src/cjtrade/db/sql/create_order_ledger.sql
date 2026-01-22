-- This is sqlite3-flavored SQL
-- Ledger of orders placed
CREATE TABLE orders (
    order_id            TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    broker              TEXT NOT NULL,             -- e.g. 'sinopac'

    product_id          TEXT NOT NULL,             -- symbol or internal id
    side                TEXT NOT NULL CHECK (side IN ('BUY', 'SELL')),
    order_type          TEXT NOT NULL,             -- LIMIT / MARKET / IOC / FOK
    price_type          TEXT NOT NULL,             -- LIMIT / STOP / STOP_LIMIT
    price               REAL,                      -- NULL for MARKET
    quantity            INTEGER NOT NULL,

    status              TEXT NOT NULL,             -- NEW / PARTIAL / FILLED / CANCELED / REJECTED

    created_at          TEXT NOT NULL,             -- ISO-8601
    updated_at          TEXT

    -- Reserved / Optional fields
    -- broker_order_id     TEXT,                      -- optional
    -- raw_response        TEXT                       -- optional JSON
);

CREATE INDEX idx_orders_user_product
ON orders (user_id, product_id);

-- CREATE INDEX idx_orders_broker_order
-- ON orders (broker, broker_order_id);


-- Create 3 dummy orders for testing
INSERT INTO orders (order_id, user_id, broker, product_id, side, order_type, price_type, price, quantity, status, created_at, updated_at) VALUES
('order_001', 'user_123', 'sinopac', 'AAPL', 'BUY', 'LIMIT', 'LIMIT', 150.0, 15, 'NEW', '2024-01-01T09:55:00Z', NULL),
('order_002', 'user_123', 'sinopac', 'AAPL', 'SELL', 'MARKET', 'MARKET', NULL, 8, 'NEW', '2024-01-02T10:55:00Z', NULL),
('order_003', 'user_456', 'sinopac', 'TSLA', 'BUY', 'LIMIT', 'LIMIT', 700.0, 5, 'NEW', '2024-01-03T11:55:00Z', NULL);