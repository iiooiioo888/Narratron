"""專案根 conftest：必須放在 rootdir，才會在 pytest_configure 之前載入。

tests/conftest.py 只在收集 tests/ 時才載入，那時 tmpdir 外掛可能已把
basetemp 定在 C:\\Users\\...\\Temp。C 槽一滿，生圖會被記成 status=failed。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TEST_TMP = Path(__file__).resolve().parent / ".pytest-tmp"
_PYTEST_BASE = _TEST_TMP / "run"
_SYS_TMP = _TEST_TMP / "sys"
_PYTEST_BASE.mkdir(parents=True, exist_ok=True)
_SYS_TMP.mkdir(parents=True, exist_ok=True)
_SYS_TMP_STR = str(_SYS_TMP)

os.environ["TMP"] = _SYS_TMP_STR
os.environ["TEMP"] = _SYS_TMP_STR
os.environ["TMPDIR"] = _SYS_TMP_STR
os.environ["PYTEST_DEBUG_TEMPROOT"] = str(_TEST_TMP)
tempfile.tempdir = _SYS_TMP_STR
os.environ.setdefault("VAULT_BACKEND", "memory")

import pytest


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """tmpdir 外掛會快取 factory；在它之後覆寫到專案碟。"""
    from _pytest.tmpdir import TempPathFactory

    config.option.basetemp = str(_PYTEST_BASE)
    rebuilt = TempPathFactory.from_config(config, _ispytest=True)
    factory = getattr(config, "_tmp_path_factory", None)
    if factory is None:
        config._tmp_path_factory = rebuilt
        return
    factory._given_basetemp = rebuilt._given_basetemp
    factory._basetemp = None
    config._tmp_path_factory = factory
