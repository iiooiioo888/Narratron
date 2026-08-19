"""`.charpass` 語意化版本相容。"""

from __future__ import annotations

from dataclasses import dataclass, field

from narratron.charpass.exceptions import CharpassVersionError
from narratron.charpass.schema import PARSER_VERSION


@dataclass(frozen=True)
class SemVer:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass
class CompatResult:
    version: SemVer
    compatible: bool
    warning: str | None = None
    errors: list[str] = field(default_factory=list)


def parse_semver(raw: str | None, *, default: str | None = None) -> SemVer:
    text = (raw or default or "0.0.0").strip()
    if text.startswith("v"):
        text = text[1:]
    parts = text.split(".")
    nums: list[int] = []
    for index in range(3):
        chunk = parts[index] if index < len(parts) else "0"
        digits = ""
        for char in chunk:
            if char.isdigit():
                digits += char
            else:
                break
        nums.append(int(digits or "0"))
    return SemVer(nums[0], nums[1], nums[2])


def parser_version() -> SemVer:
    return parse_semver(PARSER_VERSION)


def check_version(file_version: str | None, *, parser: str | None = None) -> CompatResult:
    parsed_file = parse_semver(file_version, default="1.0.0")
    parsed_parser = parse_semver(parser or PARSER_VERSION)
    if parsed_file.major == parsed_parser.major:
        return CompatResult(version=parsed_file, compatible=True)
    if parsed_file.major == parsed_parser.major + 1:
        return CompatResult(
            version=parsed_file,
            compatible=True,
            warning=(
                f"檔案主版本 {parsed_file} 比解析器 {parsed_parser} 新一個主版本；"
                "未知欄位將原樣保留。"
            ),
        )
    if parsed_file.major >= parsed_parser.major + 2:
        raise CharpassVersionError(
            f"檔案主版本 {parsed_file} 比解析器 {parsed_parser} 新兩個主版本以上，拒絕讀取。"
        )
    if parsed_file.major < parsed_parser.major:
        return CompatResult(
            version=parsed_file,
            compatible=True,
            warning=f"檔案主版本 {parsed_file} 舊於解析器 {parsed_parser}；以相容模式讀取。",
        )
    return CompatResult(version=parsed_file, compatible=True)
