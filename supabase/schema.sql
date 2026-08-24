-- ============================================
-- Narratron Supabase Schema
-- 角色数据 / 佇列 / 用户
-- ============================================

-- 启用必要扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- 1. 用户表（Supabase Auth 自动管理，这里扩展字段）
-- ============================================
CREATE TABLE IF NOT EXISTS public.user_profiles (
    id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    display_name TEXT,
    avatar_url TEXT,
    role TEXT NOT NULL DEFAULT 'user',  -- user / admin
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 自动创建 user_profile
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.user_profiles (id, display_name)
    VALUES (NEW.id, NEW.raw_user_meta_data->>'display_name')
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- ============================================
-- 2. 角色核心（身份锚点）
-- ============================================
CREATE TABLE IF NOT EXISTS public.character_cores (
    id BIGSERIAL PRIMARY KEY,
    uuid UUID UNIQUE NOT NULL DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES public.user_profiles(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    codename TEXT,
    gender_spectrum FLOAT CHECK (gender_spectrum BETWEEN 0 AND 1),
    base_age INTEGER NOT NULL DEFAULT 25,
    identity_anchor JSONB NOT NULL DEFAULT '{}',
    tags TEXT[] DEFAULT '{}',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cores_user ON public.character_cores(user_id);
CREATE INDEX IF NOT EXISTS idx_cores_name ON public.character_cores(name);
CREATE INDEX IF NOT EXISTS idx_cores_tags ON public.character_cores USING GIN(tags);

-- ============================================
-- 3. 角色档案（可版本化）
-- ============================================
CREATE TABLE IF NOT EXISTS public.character_profiles (
    id BIGSERIAL PRIMARY KEY,
    core_id BIGINT NOT NULL REFERENCES public.character_cores(id) ON DELETE CASCADE,
    version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT true,
    project_name TEXT,
    manifest JSONB NOT NULL DEFAULT '{}',
    style_preset TEXT,
    outfit_config JSONB DEFAULT '{}',
    created_by TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(core_id, version)
);

CREATE INDEX IF NOT EXISTS idx_profiles_core ON public.character_profiles(core_id);
CREATE INDEX IF NOT EXISTS idx_profiles_active ON public.character_profiles(is_active) WHERE is_active = true;

-- ============================================
-- 4. 角色变体（生成结果缓存）
-- ============================================
CREATE TABLE IF NOT EXISTS public.character_variants (
    id BIGSERIAL PRIMARY KEY,
    core_id BIGINT NOT NULL REFERENCES public.character_cores(id) ON DELETE CASCADE,
    profile_id BIGINT REFERENCES public.character_profiles(id) ON DELETE SET NULL,
    variant_hash VARCHAR(64) NOT NULL,
    evolution_params JSONB NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending / running / ready / failed / waiting
    priority INTEGER DEFAULT 0,
    result_url TEXT,
    result_metadata JSONB DEFAULT '{}',
    error_message TEXT,
    retry_count INTEGER DEFAULT 0,
    max_retries INTEGER DEFAULT 3,
    queue_wait_ms INTEGER,
    generation_duration_ms INTEGER,
    review_status TEXT,  -- pending / accepted / rejected
    effective_status TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at TIMESTAMPTZ,
    UNIQUE(core_id, variant_hash)
);

CREATE INDEX IF NOT EXISTS idx_variants_core ON public.character_variants(core_id);
CREATE INDEX IF NOT EXISTS idx_variants_status ON public.character_variants(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_variants_priority ON public.character_variants(status, priority) WHERE status = 'pending';

-- ============================================
-- 5. 生图配置（singleton）
-- ============================================
CREATE TABLE IF NOT EXISTS public.imaging_config (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    provider TEXT NOT NULL DEFAULT 'null',
    base_url TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    api_key TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.imaging_config (id, provider, base_url, model)
VALUES (1, 'null', '', '')
ON CONFLICT (id) DO NOTHING;

-- ============================================
-- 6. 自动更新 updated_at
-- ============================================
CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_cores_updated ON public.character_cores;
CREATE TRIGGER trg_cores_updated BEFORE UPDATE ON public.character_cores
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

DROP TRIGGER IF EXISTS trg_profiles_updated ON public.character_profiles;
CREATE TRIGGER trg_profiles_updated BEFORE UPDATE ON public.character_profiles
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

DROP TRIGGER IF EXISTS trg_variants_updated ON public.character_variants;
CREATE TRIGGER trg_variants_updated BEFORE UPDATE ON public.character_variants
    FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

-- ============================================
-- 7. RLS（Row Level Security）
-- ============================================
ALTER TABLE public.user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.character_cores ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.character_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.character_variants ENABLE ROW LEVEL SECURITY;

-- 用户只能读写自己的 profile
CREATE POLICY "Users can view own profile" ON public.user_profiles
    FOR SELECT USING (auth.uid() = id);
CREATE POLICY "Users can update own profile" ON public.user_profiles
    FOR UPDATE USING (auth.uid() = id);

-- 角色：所有人可读，登录用户可写自己的
CREATE POLICY "Anyone can view characters" ON public.character_cores
    FOR SELECT USING (true);
CREATE POLICY "Users can create own characters" ON public.character_cores
    FOR INSERT WITH CHECK (auth.uid() = user_id);
CREATE POLICY "Users can update own characters" ON public.character_cores
    FOR UPDATE USING (auth.uid() = user_id);
CREATE POLICY "Users can delete own characters" ON public.character_cores
    FOR DELETE USING (auth.uid() = user_id);

-- 档案：跟随角色权限
CREATE POLICY "Anyone can view profiles" ON public.character_profiles
    FOR SELECT USING (true);
CREATE POLICY "Users can manage own profiles" ON public.character_profiles
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.character_cores
            WHERE character_cores.id = character_profiles.core_id
            AND character_cores.user_id = auth.uid()
        )
    );

-- 变体：跟随角色权限
CREATE POLICY "Anyone can view variants" ON public.character_variants
    FOR SELECT USING (true);
CREATE POLICY "Users can manage own variants" ON public.character_variants
    FOR ALL USING (
        EXISTS (
            SELECT 1 FROM public.character_cores
            WHERE character_cores.id = character_variants.core_id
            AND character_cores.user_id = auth.uid()
        )
    );
