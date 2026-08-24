"""敘事自舉：一句話 → 世界觀擬合 + 角色護照初稿 + 種子劇本。

不是第六個智能體；由 Parser / Director 在偵測到角色簡述時呼叫。
"""

from narratron.narrative.bootstrap import (
    BootstrapResult,
    apply_overrides,
    bootstrap_from_brief,
    identity_from_input,
    looks_like_character_brief,
    looks_like_screenplay,
    maybe_bootstrap,
    resolve_ensure_identity,
)
from narratron.narrative.world_bible import WorldBible, fit_world, load_world_bible

__all__ = [
    "BootstrapResult",
    "WorldBible",
    "apply_overrides",
    "bootstrap_from_brief",
    "identity_from_input",
    "fit_world",
    "load_world_bible",
    "looks_like_character_brief",
    "looks_like_screenplay",
    "maybe_bootstrap",
    "resolve_ensure_identity",
]
