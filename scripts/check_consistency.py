"""對照白皮書代號、觸發時機、目錄路徑；失敗時以非零碼退出。"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from narratron.hardware.pools import HardwarePool, SceneComplexity, select_pool
from narratron.naming import (
    AGENTS,
    ARCHITECTURE_PATHS,
    CHARPASS,
    DEFERRED_MODULE_STEMS,
    FORBIDDEN_IDENTIFIERS,
    FRONTEND,
    HARDWARE_POOLS,
    MODEL_FARM,
    PLUGIN_MATRIX,
    TRIGGER_LABELS,
    TRINITY_CORE,
    VAULT_TABLES,
)
from narratron.plugins.context import PluginContext, TriggerPhase
from narratron.plugins.registry import PLUGIN_CLASSES, iter_plugins, trigger_key
from narratron.plugins.router import Router
from narratron.vault.schema import VAULT_TABLES as SCHEMA_TABLES


def _fail(errors: list[str], msg: str) -> None:
    errors.append(msg)


def check_paths(errors: list[str]) -> None:
    for rel in ARCHITECTURE_PATHS:
        path = ROOT / rel
        if not path.is_file():
            _fail(errors, f"架構路徑缺失：{rel}")
    for _code, _zh, rel in FRONTEND:
        if not (ROOT / rel).is_file():
            _fail(errors, f"用戶層說明缺失：{rel}")
    for _en, _cls, _zh, rel in TRINITY_CORE:
        if not (ROOT / rel).is_file():
            _fail(errors, f"核心內核缺失：{rel}")
    for _code, _zh, rel in AGENTS:
        if not (ROOT / rel).is_file():
            _fail(errors, f"智能體缺失：{rel}")
    for _pid, _code, _zh, _trig, rel in PLUGIN_MATRIX:
        if not (ROOT / rel).is_file():
            _fail(errors, f"外掛缺失：{rel}")
    for _cls, rel in MODEL_FARM:
        if not (ROOT / rel).is_file():
            _fail(errors, f"Model Farm 缺失：{rel}")


def check_plugins(errors: list[str]) -> None:
    if len(PLUGIN_MATRIX) != 13:
        _fail(errors, f"PLUGIN_MATRIX 應為 13 筆，實際 {len(PLUGIN_MATRIX)}")
    if len(PLUGIN_CLASSES) != 13:
        _fail(errors, f"PLUGIN_CLASSES 應為 13 筆，實際 {len(PLUGIN_CLASSES)}")

    for plugin_id, code, name_zh, trigger, rel in PLUGIN_MATRIX:
        cls = PLUGIN_CLASSES.get(code)
        if cls is None:
            _fail(errors, f"註冊表缺少 {code}")
            continue
        inst = cls()
        if inst.plugin_id != plugin_id:
            _fail(errors, f"{code}.plugin_id={inst.plugin_id!r} ≠ {plugin_id!r}")
        if inst.code != code:
            _fail(errors, f"{code}.code={inst.code!r}")
        if inst.name_zh != name_zh:
            _fail(errors, f"{code}.name_zh={inst.name_zh!r} ≠ {name_zh!r}")
        if trigger_key(tuple(inst.triggers)) != trigger:
            _fail(errors, f"{code} 觸發時機 {trigger_key(tuple(inst.triggers))} ≠ {trigger}")
        if Path(rel).stem != code.lower():
            _fail(errors, f"{code} 檔名應為 {code.lower()}.py，實際 {rel}")

    extra = set(PLUGIN_CLASSES) - {row[1] for row in PLUGIN_MATRIX}
    if extra:
        _fail(errors, f"多餘外掛類：{sorted(extra)}")


def check_whitepaper_matrix(errors: list[str]) -> None:
    text = (ROOT / "docs" / "whitepaper-v2.md").read_text(encoding="utf-8")
    rows = re.findall(
        r"\*\*P(\d+)\*\*\s*\|\s*`([^`]+)`\s*\|\s*([^|]+)\|\s*[^|]+\|\s*([^|]+)\|",
        text,
    )
    parsed: list[tuple[str, str, str, str]] = []
    for num, code, zh, timing in rows:
        parsed.append(
            (
                f"P{num}",
                code.strip(),
                zh.strip(),
                timing.strip(),
            )
        )
    if len(parsed) != 13:
        _fail(errors, f"白皮書外掛表解析到 {len(parsed)} 列，預期 13")
        return
    for spec, (pid, code, zh, timing) in zip(PLUGIN_MATRIX, parsed, strict=True):
        exp_pid, exp_code, exp_zh, exp_trig, _rel = spec
        label = TRIGGER_LABELS[exp_trig]
        if (pid, code, zh, timing) != (exp_pid, exp_code, exp_zh, label):
            _fail(
                errors,
                "白皮書列與凍結表不一致："
                f" 文件={(pid, code, zh, timing)} 凍結={(exp_pid, exp_code, exp_zh, label)}",
            )


def check_hardware(errors: list[str]) -> None:
    mapping = {row[0]: (row[2], row[1], row[3]) for row in HARDWARE_POOLS}
    for member in HardwarePool:
        expected = mapping.get(member.name)
        if expected is None:
            _fail(errors, f"多餘算力枚舉 {member.name}")
            continue
        py_name, code, _zh = expected
        if member.value != py_name:
            _fail(errors, f"{member.name} value={member.value!r} ≠ {py_name!r}")
        if code.split()[0] not in member.value:
            _fail(errors, f"{member.name} 與代號 {code} 無法對上 {member.value}")
    pool = select_pool(SceneComplexity(character_count=99, vfx_level=10))
    if pool is not HardwarePool.L1:
        _fail(errors, f"select_pool 應回傳 L1 MidCore，實際 {pool}")
    result = Router().run(PluginContext(shot_id="shot-0", phase=TriggerPhase.PRE))
    if result.metadata.get("pool") != HardwarePool.L1.value:
        _fail(errors, f"Router stub 應回傳 MidCore，實際 {result.metadata}")


def check_vault(errors: list[str]) -> None:
    if tuple(SCHEMA_TABLES) != VAULT_TABLES:
        _fail(errors, f"schema 表名 {SCHEMA_TABLES} ≠ {VAULT_TABLES}")


def check_agents(errors: list[str]) -> None:
    from narratron.agents import NODE_ORDER
    from narratron.agents.director import Director
    from narratron.agents.keeper import Keeper
    from narratron.agents.muxer import Muxer
    from narratron.agents.parser import Parser
    from narratron.agents.runner import Runner

    expected = tuple(row[0] for row in AGENTS)
    if NODE_ORDER != expected:
        _fail(errors, f"LangGraph 節點序 {NODE_ORDER} ≠ {expected}")
    classes = {
        "Parser": Parser,
        "Director": Director,
        "Keeper": Keeper,
        "Runner": Runner,
        "Muxer": Muxer,
    }
    for name, cls in classes.items():
        if cls.__name__ != name:
            _fail(errors, f"智能體類名 {cls.__name__} ≠ {name}")


def check_forbidden_and_deferred(errors: list[str]) -> None:
    py_files = list((ROOT / "narratron").rglob("*.py"))
    py_files += list((ROOT / "scripts").rglob("*.py"))
    py_files += list((ROOT / "tests").rglob("*.py"))
    for path in py_files:
        stem = path.stem.lower()
        if stem in DEFERRED_MODULE_STEMS:
            _fail(errors, f"本階段禁止模組檔：{path.relative_to(ROOT)}")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            _fail(errors, f"語法錯誤 {path}: {exc}")
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in FORBIDDEN_IDENTIFIERS:
                    _fail(
                        errors,
                        f"禁止別名 {node.name} 出現於 {path.relative_to(ROOT)}",
                    )


def check_no_invented_plugin_files(errors: list[str]) -> None:
    allowed = {row[1].lower() for row in PLUGIN_MATRIX}
    allowed |= {"bus", "context", "registry", "__init__"}
    for path in (ROOT / "narratron" / "plugins").glob("*.py"):
        if path.stem not in allowed:
            _fail(errors, f"外掛目錄出現未凍結檔名：{path.name}")


def check_architecture_mentions(errors: list[str]) -> None:
    arch = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    required = [
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
        "narratron/vault/state_vault.py",
        "narratron/core/logic_core.py",
        "narratron/core/causal_link.py",
        "narratron/core/compressor.py",
        "narratron/plugins/bus.py",
        "narratron/hardware/pools.py",
        "narratron/models/farm.py",
        "docker-compose.yml",
        "docker/init-vault.sql",
    ]
    for rel in required:
        if rel.replace("\\", "/") not in arch.replace("\\", "/"):
            _fail(errors, f"architecture.md 未對照路徑 {rel}")


def check_charpass(errors: list[str]) -> None:
    _en, _code, _zh, ext, package_rel = CHARPASS
    if ext != ".charpass":
        _fail(errors, f"CHARPASS 副檔名應為 .charpass，實際 {ext}")
    doc = ROOT / "docs" / "charpass.md"
    if not doc.is_file():
        _fail(errors, "規格缺失：docs/charpass.md")
    package = ROOT / "narratron" / "charpass"
    if not package.is_dir():
        _fail(errors, f"格式層缺失：{package_rel}")
        return
    required = (
        "__init__.py",
        "schema.py",
        "schema.json",
        "container.py",
        "checksum.py",
        "compat.py",
        "crypto.py",
        "causal.py",
        "vault_bridge.py",
        "store.py",
        "exceptions.py",
    )
    for name in required:
        if not (package / name).is_file():
            _fail(errors, f"charpass 缺失 {name}")
    if "Charpass" in PLUGIN_CLASSES or "CharacterPassport" in PLUGIN_CLASSES:
        _fail(errors, "Character Passport 不得算進 13 外掛")


def main() -> int:
    errors: list[str] = []
    check_paths(errors)
    check_plugins(errors)
    check_whitepaper_matrix(errors)
    check_hardware(errors)
    check_vault(errors)
    check_agents(errors)
    check_forbidden_and_deferred(errors)
    check_no_invented_plugin_files(errors)
    check_architecture_mentions(errors)
    check_charpass(errors)
    if errors:
        print("一致性檢查失敗：")
        for item in errors:
            print(f"  - {item}")
        return 1
    print("一致性檢查通過：代號、13 外掛觸發時機、架構路徑均 1:1。")
    print(f"  外掛 {len(list(iter_plugins()))} ／ 算力池 {len(list(HardwarePool))} ／ 表 {list(SCHEMA_TABLES)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
