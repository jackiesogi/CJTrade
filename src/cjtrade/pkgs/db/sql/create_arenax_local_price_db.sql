-- SQLite schema for local price DB (1-min OHLCV), tuned for incremental/backfill
-- Notes:
--  - We store timestamps as INTEGER unix epoch seconds in UTC for compactness and speed.
--  - Use a single `prices` table for all symbols and timeframes, with composite UNIQUE
--    constraint (symbol, timeframe, ts, source) to avoid duplicates and support upserts.
--  - For ~200 symbols * 10 years of 1-min candles you can reach O(10^8) rows. SQLite can
--    handle large files but needs tuning (WAL, increased cache, periodic VACUUM) and may
--    be slower than a dedicated DB for heavy concurrent writes.

PRAGMA journal_mode = WAL;            -- enable WAL for concurrent readers + a single writer
PRAGMA synchronous = NORMAL;          -- balance durability and speed
PRAGMA temp_store = MEMORY;           -- use memory for temp tables
PRAGMA cache_size = 200000;           -- tune to your system memory (negative = KB)

-- Main price table
CREATE TABLE IF NOT EXISTS arenax_prices (
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL, -- '1m', '5m'
    ts INTEGER NOT NULL,     -- Unix epoch
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    source TEXT NOT NULL,    -- 'yfinance', 'sinopac'
    adjusted INTEGER DEFAULT 0,
    fetched_at INTEGER DEFAULT (unixepoch()), -- SQLite 3.38+ recommended
    created_at INTEGER DEFAULT (unixepoch()),
    -- set a composite primary key for efficient upserts and lookups
    PRIMARY KEY (symbol, timeframe, ts, source)
) WITHOUT ROWID;

-- Auxiliary indexes for common queries
CREATE INDEX IF NOT EXISTS idx_arenax_prices_ts ON arenax_prices(ts);

-- Coverage tracking (multi-interval per symbol/timeframe to support gap-fill logic)
-- Each row represents ONE contiguous fetched interval.
-- The old single-row-per-symbol schema is superseded; a migration is applied at connect time.
CREATE TABLE IF NOT EXISTS arenax_symbol_coverage (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol      TEXT     NOT NULL,
    timeframe   TEXT     NOT NULL,
    start_ts    INTEGER  NOT NULL,   -- Unix epoch seconds (inclusive)
    end_ts      INTEGER  NOT NULL,   -- Unix epoch seconds (inclusive)
    source      TEXT     NOT NULL DEFAULT 'unknown',  -- 'yfinance' | 'sinopac' | 'manual'
    last_checked INTEGER           DEFAULT (unixepoch()),
    created_at  INTEGER           DEFAULT (unixepoch())
);
-- Fast range-lookup index
CREATE INDEX IF NOT EXISTS idx_coverage_symbol_tf_start
    ON arenax_symbol_coverage(symbol, timeframe, start_ts);
