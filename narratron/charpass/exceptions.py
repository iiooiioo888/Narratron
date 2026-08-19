"""`.charpass` 格式層例外。"""

from __future__ import annotations


class CharpassError(Exception):
    """角色護照格式或容器錯誤。"""


class CharpassVersionError(CharpassError):
    """語意化版本不相容。"""


class CharpassChecksumError(CharpassError):
    """SHA-256 校驗失敗。"""


class CharpassSignatureError(CharpassError):
    """L1 HMAC / signature.sig 校驗失敗。"""


class CharpassCryptoError(CharpassError):
    """L2 / L3 加解密失敗。"""


class CharpassConflictError(CharpassError):
    """導入衝突（需 confirm 或策略不允許）。"""


class CharpassArchiveOnlyError(CharpassError):
    """角色已被 Trace Log 引用，只准歸檔、不准刪。"""
