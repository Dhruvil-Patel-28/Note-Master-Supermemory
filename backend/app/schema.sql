CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS captures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    type TEXT NOT NULL CHECK (type IN ('text', 'voice', 'doc')),
    raw_content_ref TEXT,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'processing', 'indexed', 'failed')),
    error TEXT,
    sensitivity_tier TEXT NOT NULL DEFAULT 'none'
        CHECK (sensitivity_tier IN ('none', 'moderate', 'high')),
    document_group_id INTEGER,
    version_number INTEGER NOT NULL DEFAULT 1,
    is_latest INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_captures_one_latest
    ON captures(document_group_id) WHERE is_latest = 1 AND document_group_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_captures_group ON captures(document_group_id);
CREATE INDEX IF NOT EXISTS idx_captures_status ON captures(status);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query TEXT,
    retrieved_source_ids TEXT,
    sensitive_access INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS captures_fts USING fts5(
    content,
    tokenize = 'unicode61'
);