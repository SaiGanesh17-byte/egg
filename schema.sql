CREATE TABLE IF NOT EXISTS symbols (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    file_path TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT,
    content_hash TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_symbols_name_kind ON symbols (name, kind);

CREATE TABLE IF NOT EXISTS graph_edges (
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    label TEXT,
    PRIMARY KEY (source_id, target_id, edge_type, label)
);

CREATE INDEX IF NOT EXISTS idx_edges_target ON graph_edges (target_id, edge_type);
CREATE INDEX IF NOT EXISTS idx_edges_source ON graph_edges (source_id, edge_type);

CREATE TABLE IF NOT EXISTS file_hashes (
    file_path TEXT PRIMARY KEY,
    content_hash TEXT NOT NULL,
    last_indexed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_contexts (
    symbol_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    context_payload JSON NOT NULL,
    status TEXT DEFAULT 'PENDING',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(symbol_id) REFERENCES symbols(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS discovered_declarations (
    qualified_name TEXT PRIMARY KEY,
    decl_kind TEXT NOT NULL,
    file_path TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS class_hierarchy (
    child_id TEXT NOT NULL,
    parent_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    unqualified INTEGER DEFAULT 0,
    PRIMARY KEY (child_id, parent_id)
);

CREATE TABLE IF NOT EXISTS instantiations (
    class_id TEXT NOT NULL,
    instantiation_type TEXT NOT NULL,
    file_path TEXT NOT NULL,
    line_number INTEGER NOT NULL,
    PRIMARY KEY (class_id, file_path, line_number)
);
