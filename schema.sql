PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    subtitle TEXT NOT NULL,
    category TEXT NOT NULL CHECK(category IN ('气泡饮料', '茶与咖啡', '果汁', '饮用水')),
    price_cents INTEGER NOT NULL CHECK(price_cents BETWEEN 100 AND 99900),
    stock INTEGER NOT NULL CHECK(stock BETWEEN 0 AND 999),
    color TEXT NOT NULL,
    label TEXT NOT NULL,
    shape TEXT NOT NULL DEFAULT 'can',
    active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0, 1))
);

CREATE TABLE IF NOT EXISTS wallets (
    id TEXT PRIMARY KEY,
    balance_cents INTEGER NOT NULL DEFAULT 0 CHECK(balance_cents BETWEEN 0 AND 100000)
);

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    wallet_id TEXT NOT NULL REFERENCES wallets(id),
    product_id INTEGER NOT NULL REFERENCES products(id),
    product_name TEXT NOT NULL,
    amount_cents INTEGER NOT NULL CHECK(amount_cents > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE TABLE IF NOT EXISTS operations (
    wallet_id TEXT NOT NULL REFERENCES wallets(id),
    request_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    response TEXT NOT NULL,
    PRIMARY KEY (wallet_id, request_id)
);

CREATE INDEX IF NOT EXISTS orders_wallet_created ON orders(wallet_id, created_at DESC);
