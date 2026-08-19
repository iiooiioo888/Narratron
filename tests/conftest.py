"""測試共用：每次重置預設 State Vault，避免跨測試污染。"""

from __future__ import annotations

import os
from collections.abc import Iterator

os.environ.setdefault("VAULT_BACKEND", "memory")

import pytest

from narratron.vault.state_vault import reset_default_vault


@pytest.fixture(autouse=True)
def _reset_vault() -> Iterator[None]:
    reset_default_vault()
    yield
    reset_default_vault()
