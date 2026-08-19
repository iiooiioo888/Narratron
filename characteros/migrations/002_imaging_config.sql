-- 增量 migration：新增 imaging_config（既有 DB 執行此檔即可）
CREATE TABLE IF NOT EXISTS imaging_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    provider VARCHAR(50) NOT NULL DEFAULT 'null',
    base_url VARCHAR(512) NOT NULL DEFAULT 'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
    model VARCHAR(255) NOT NULL DEFAULT 'wan2.7-image-pro',
    api_key TEXT,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

INSERT INTO imaging_config (id, provider, base_url, model)
VALUES (
    1,
    'null',
    'https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1',
    'wan2.7-image-pro'
)
ON CONFLICT (id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger WHERE tgname = 'update_imaging_config_updated_at'
    ) THEN
        CREATE TRIGGER update_imaging_config_updated_at
            BEFORE UPDATE ON imaging_config
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    END IF;
END $$;
