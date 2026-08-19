CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shots (
    id TEXT PRIMARY KEY,
    scene_id TEXT NOT NULL,
    "order" INTEGER NOT NULL,
    camera_language TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS trace_log (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL,
    shot_id TEXT,
    happened_at TIMESTAMPTZ,
    cause TEXT NOT NULL DEFAULT '',
    effect TEXT NOT NULL DEFAULT '',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    entity_id TEXT,
    kind TEXT NOT NULL DEFAULT 'reference_image',
    uri TEXT NOT NULL DEFAULT '',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_entities_kind ON entities (kind);
CREATE INDEX IF NOT EXISTS idx_shots_scene_order ON shots (scene_id, "order");
CREATE INDEX IF NOT EXISTS idx_trace_log_entity ON trace_log (entity_id);
CREATE INDEX IF NOT EXISTS idx_trace_log_shot ON trace_log (shot_id);
CREATE INDEX IF NOT EXISTS idx_assets_entity ON assets (entity_id);
