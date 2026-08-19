# Narratron CharacterOS - Database Schema
-- PostgreSQL 16+ with JSONB support

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- 1. CHARACTER CORES (身份錨點 - 不可變)
-- ============================================
CREATE TABLE character_cores (
    id SERIAL PRIMARY KEY,
    uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    
    -- 核心身份標識
    name VARCHAR(255) NOT NULL,
    codename VARCHAR(100),  -- 代號，如 "LinMo"
    
    -- 基礎人口統計（唯讀）
    gender_spectrum FLOAT CHECK (gender_spectrum BETWEEN 0 AND 1), -- 0=完全女性，1=完全男性，0.5=中性
    base_age INTEGER NOT NULL, -- 基準年齡
    
    -- 身份錨點描述（JSONB 彈性結構）
    identity_anchor JSONB NOT NULL DEFAULT '{}',
    
    -- 元數據
    tags TEXT[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 索引優化
CREATE INDEX idx_cores_uuid ON character_cores(uuid);
CREATE INDEX idx_cores_name ON character_cores(name);
CREATE INDEX idx_cores_tags ON character_cores USING GIN(tags);
CREATE INDEX idx_cores_identity ON character_cores USING GIN(identity_anchor);

-- ============================================
-- 2. CHARACTER PROFILES (專案檔案 - 可版本化)
-- ============================================
CREATE TABLE character_profiles (
    id SERIAL PRIMARY KEY,
    core_id INTEGER NOT NULL REFERENCES character_cores(id) ON DELETE CASCADE,
    
    -- 版本控制
    version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT true,
    
    -- 專案特定設定
    project_name VARCHAR(255),
    project_id VARCHAR(100),
    
    -- 完整 Profile Manifest (JSONB)
    manifest JSONB NOT NULL DEFAULT '{}',
    
    -- 樣式與外觀設定
    style_preset VARCHAR(100),
    outfit_config JSONB DEFAULT '{}',
    
    -- 元數據
    created_by VARCHAR(100),
    notes TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- 唯一約束：同一核心的同一版本只能有一個 active profile
    UNIQUE(core_id, version)
);

-- 索引優化
CREATE INDEX idx_profiles_core_id ON character_profiles(core_id);
CREATE INDEX idx_profiles_active ON character_profiles(is_active) WHERE is_active = true;
CREATE INDEX idx_profiles_version ON character_profiles(core_id, version);
CREATE INDEX idx_profiles_manifest ON character_profiles USING GIN(manifest);

-- ============================================
-- 3. CHARACTER VARIANTS (變體快取 - 演化結果)
-- ============================================
CREATE TABLE character_variants (
    id SERIAL PRIMARY KEY,
    core_id INTEGER NOT NULL REFERENCES character_cores(id) ON DELETE CASCADE,
    profile_id INTEGER REFERENCES character_profiles(id) ON DELETE SET NULL,
    
    -- 變體指紋（唯一性保證）
    variant_hash VARCHAR(64) NOT NULL,
    
    -- 演化參數快照
    evolution_params JSONB NOT NULL DEFAULT '{}',
    
    -- 狀態機
    status VARCHAR(50) NOT NULL DEFAULT 'pending', -- pending, ready, failed
    priority INTEGER DEFAULT 0,
    
    -- 生成結果
    result_url VARCHAR(512),
    result_metadata JSONB DEFAULT '{}',
    
    -- 錯誤處理
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    
    -- 效能指標
    queue_wait_ms INTEGER,
    generation_duration_ms INTEGER,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- 唯一約束：相同核心 + 相同 Hash 只能有一筆
    UNIQUE(core_id, variant_hash)
);

-- 索引優化
CREATE INDEX idx_variants_core_id ON character_variants(core_id);
CREATE INDEX idx_variants_hash ON character_variants(variant_hash);
CREATE INDEX idx_variants_status ON character_variants(status) WHERE status = 'pending';
CREATE INDEX idx_variants_priority ON character_variants(status, priority) WHERE status = 'pending';
CREATE INDEX idx_variants_created ON character_variants(created_at);

-- ============================================
-- 4. GENERATION LOGS (AI 生成日誌 - 可觀測性)
-- ============================================
CREATE TABLE generation_logs (
    id SERIAL PRIMARY KEY,
    variant_id INTEGER REFERENCES character_variants(id) ON DELETE SET NULL,
    trace_id VARCHAR(64),
    
    -- 模型資訊
    model_used JSONB DEFAULT '{}',
    
    -- 參數記錄
    params_used JSONB DEFAULT '{}',
    
    -- 效能指標
    generation_duration_ms INTEGER,
    queue_wait_duration_ms INTEGER,
    total_duration_ms INTEGER,
    
    -- 品質分數
    quality_score FLOAT,
    face_similarity FLOAT,
    anatomy_score FLOAT,
    
    -- 結果
    success BOOLEAN,
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 索引優化
CREATE INDEX idx_logs_variant ON generation_logs(variant_id);
CREATE INDEX idx_logs_created ON generation_logs(created_at);
CREATE INDEX idx_logs_success ON generation_logs(success) WHERE success = false;

-- ============================================
-- 5. 自動更新 updated_at 的 Trigger
-- ============================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER update_cores_updated_at BEFORE UPDATE ON character_cores
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_profiles_updated_at BEFORE UPDATE ON character_profiles
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_variants_updated_at BEFORE UPDATE ON character_variants
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================
-- 6. 初始數據：林默 (Lin Mo)
-- ============================================
INSERT INTO character_cores (name, codename, gender_spectrum, base_age, identity_anchor, tags, metadata)
VALUES (
    '林默',
    'LinMo',
    0.6,  -- 略偏男性
    28,   -- 基準年齡
    '{
        "face_structure": "oval",
        "eye_color": "dark_brown",
        "hair_color": "black",
        "distinctive_features": ["slight_scar_left_eyebrow", "calm_expression"],
        "voice_timbre": "baritone",
        "personality_archetype": "stoic_protector"
    }'::jsonb,
    ARRAY['protagonist', 'modern', 'urban'],
    '{"narratron_version": "3.0", "creator": "system"}'::jsonb
);

-- 插入對應的 Profile (版本 1)
INSERT INTO character_profiles (core_id, version, is_active, project_name, manifest, style_preset, outfit_config, created_by)
SELECT 
    id,
    1,
    true,
    'Narratron_v3_Demo',
    '{
        "_identity": {
            "name": "林默",
            "age_visual": 28,
            "gender_spectrum": 0.6,
            "ref_images": ["s3://refs/linmo_base_001.jpg"]
        },
        "_style": {
            "outfit": {
                "description": "dark tactical jacket, worn denim jeans, combat boots",
                "color_palette": ["#2C3E50", "#34495E", "#1A1A1A"],
                "material_hints": ["leather", "denim", "metal_zippers"]
            },
            "lighting_preference": "cinematic_noir",
            "camera_angle": "low_angle_heroic"
        },
        "_expression": {
            "base_emotion": "neutral_determined",
            "au_intensity": 0.3,
            "micro_expressions": ["slight_frown", "focused_gaze"]
        },
        "_body": {
            "height_cm": 178,
            "build": "athletic_lean",
            "posture_defaults": {
                "spine_curve": "straight_confident",
                "shoulder_tension": "relaxed_ready"
            }
        }
    }'::jsonb,
    'tactical_modern',
    '{"jacket": "black_leather_tactical", "pants": "worn_denim", "boots": "combat_style"}'::jsonb,
    'system'
FROM character_cores WHERE codename = 'LinMo';
