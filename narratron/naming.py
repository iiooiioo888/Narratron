"""命名凍結表：程式唯一真相來源。禁止別名。"""

from __future__ import annotations

from typing import Final

SLOGAN: Final = "Every Frame Carries Its Past."
PLATFORM: Final = "Narratron"
PLATFORM_ZH: Final = "敘事體"

# 三大核心內核：官方英文代號（含空格）→ Python 類名
TRINITY_CORE: Final = (
    ("Logic Core", "LogicCore", "邏輯內核", "narratron/core/logic_core.py"),
    ("Causal Link", "CausalLink", "因果橋", "narratron/core/causal_link.py"),
    ("Compressor", "Compressor", "壓縮器", "narratron/core/compressor.py"),
)

# LangGraph 節點名必須等於英文代號
AGENTS: Final = (
    ("Parser", "解析器", "narratron/agents/parser.py"),
    ("Director", "調度器", "narratron/agents/director.py"),
    ("Keeper", "守護器", "narratron/agents/keeper.py"),
    ("Runner", "執行器", "narratron/agents/runner.py"),
    ("Muxer", "合流器", "narratron/agents/muxer.py"),
)

# 觸發時機字串必須與白皮書一致：生成前 / 生成後 / 生成前/後
PLUGIN_MATRIX: Final = (
    ("P1", "Tracer", "追跡", "pre", "narratron/plugins/tracer.py"),
    ("P2", "Fixer", "固形", "pre", "narratron/plugins/fixer.py"),
    ("P3", "Forker", "分岔", "pre", "narratron/plugins/forker.py"),
    ("P4", "Painter", "調色", "pre", "narratron/plugins/painter.py"),
    ("P5", "Mover", "擬動", "pre_post", "narratron/plugins/mover.py"),
    ("P6", "Screener", "篩檢", "post", "narratron/plugins/screener.py"),
    ("P7", "Router", "路由", "pre", "narratron/plugins/router.py"),
    ("P8", "Recycler", "重生", "pre", "narratron/plugins/recycler.py"),
    ("P9", "Player", "配樂", "post", "narratron/plugins/player.py"),
    ("P10", "Filter", "濾聲", "post", "narratron/plugins/filter.py"),
    ("P11", "Cropper", "裁切", "post", "narratron/plugins/cropper.py"),
    ("P12", "Exporter", "轉檔", "post", "narratron/plugins/exporter.py"),
    ("P13", "Maker", "製本", "post", "narratron/plugins/maker.py"),
)

TRIGGER_LABELS: Final = {
    "pre": "生成前",
    "post": "生成後",
    "pre_post": "生成前/後",
}

HARDWARE_POOLS: Final = (
    ("L0", "Big Core", "BigCore", "大核"),
    ("L1", "Mid Core", "MidCore", "中核"),
    ("L2", "Alt Core", "AltCore", "備核"),
    ("L3", "Light Core", "LightCore", "輕核"),
)

FRONTEND: Final = (
    ("Pad", "寫板", "frontend/pad.md"),
    ("Timeline", "時軌", "frontend/timeline.md"),
    ("Dashboard", "總覽", "frontend/dashboard.md"),
    ("Map", "因果圖", "frontend/map.md"),
    ("Player", "播放器", "frontend/player.md"),
)

VAULT_TABLES: Final = ("entities", "shots", "trace_log", "assets")

MODEL_FARM: Final = (
    ("Flux", "narratron/models/flux.py"),
    ("Wan", "narratron/models/wan.py"),
    ("Veo", "narratron/models/veo.py"),
    ("TTS", "narratron/models/tts.py"),
    ("FFmpeg", "narratron/models/ffmpeg.py"),
)

# 格式層（非智能體、非外掛）：Character Passport / .charpass
CHARPASS: Final = (
    "Character Passport",
    "Charpass",
    "角色護照",
    ".charpass",
    "narratron/charpass/",
)

ARCHITECTURE_PATHS: Final = (
    "frontend/pad.md",
    "frontend/timeline.md",
    "frontend/dashboard.md",
    "frontend/map.md",
    "frontend/player.md",
    "narratron/api/app.py",
    "narratron/agents/parser.py",
    "narratron/agents/director.py",
    "narratron/agents/keeper.py",
    "narratron/agents/runner.py",
    "narratron/agents/muxer.py",
    "narratron/agents/graph.py",
    "narratron/agents/state.py",
    "narratron/vault/state_vault.py",
    "narratron/vault/schema.py",
    "narratron/vault/chroma.py",
    "narratron/vault/redis_cache.py",
    "narratron/vault/trace_log.py",
    "narratron/core/logic_core.py",
    "narratron/core/causal_link.py",
    "narratron/core/compressor.py",
    "narratron/plugins/bus.py",
    "narratron/hardware/pools.py",
    "narratron/hardware/scheduler.py",
    "narratron/hardware/tier_store.py",
    "narratron/models/farm.py",
    "docker-compose.yml",
    "docker/init-vault.sql",
)

# 程式識別符中禁止出現的別名（類名 / 檔名 stem）
FORBIDDEN_IDENTIFIERS: Final = frozenset(
    {
        "ContinuityCop",
        "Continuity_Cop",
        "Guard",
        "Watcher",
        "Planner",
        "Storyboarder",
        "ShotSplitter",
        "Extractor",
        "Ingestor",
        "ScriptReader",
        "Generator",
        "Worker",
        "Executor",
        "Composer",
        "Editor",
        "PostProcessor",
        "PromptTranslator",
        "PromptEngine",
        "Summarizer",
        "TokenSaver",
        "MemoryBank",
        "WorldState",
        "ContinuityDB",
        "PluginHub",
        "AddonSystem",
        "GPUPool",
        "HeavyCore",
        "BackupNPU",
        "ScriptBox",
        "GraphView",
        "CausalGraph",
        "NarraTron",
        "NarrativeTron",
        "PoolSelector",
        "Preview",
        "Viewer",
    }
)

# Beta/Gamma 才准建檔的模組 stem；本階段出現即為衝突
DEFERRED_MODULE_STEMS: Final = frozenset(
    {
        "importer",
        "gni",
        "common_sense",
        "personalized_theater",
        "personalized_narrative",
    }
)
