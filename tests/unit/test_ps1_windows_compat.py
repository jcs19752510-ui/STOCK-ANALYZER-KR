"""Windows PowerShell 5.1 호환 정적 점검(DEC-103). Linux에서는 5.1을 실행할 수 없어 소스를 기준으로 확인한다.

- PowerShell 6+에서만 되는 구성요소가 없어야 한다(작업 스케줄러는 `powershell.exe` = 5.1로 실행한다).
- 한글 등 비ASCII가 있는 .ps1은 UTF-8 BOM이 있어야 한다(BOM이 없으면 5.1은 시스템 ANSI로 읽는다).
- 한글 PC(cp949)·영문 PC(cp1252)로 잘못 읽어도 구조 문자(따옴표·괄호·중괄호 등)가 보존되어야 한다.
"""

# ruff: noqa: E501
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PS1 = sorted(p for p in (REPO / "scripts").glob("*.ps1"))

PS6_ONLY = [
    r"\$IsWindows", r"\$IsLinux", r"\$IsMacOS", r"SkipHttpErrorCheck", r"SkipCertificateCheck", r"-AdditionalChildPath",
    r"-LeafBase", r"ForEach-Object[^|\n]*-Parallel", r"GetRelativePath", r"ConvertFrom-Json[^|\n]*-AsHashtable", r"Test-Json",
    r"-AsByteStream", r"-Encoding\s+(utf8BOM|utf8NoBOM|oem)\b", r"\?\?", r"\?\.", r"(?<![\w$])&&(?![\w$])", r"\|\|",
]


def _code_lines(text: str):
    for line in text.splitlines():
        if not line.lstrip().startswith("#"):
            yield line


def test_ps1_files_exist():
    assert len(PS1) >= 6


@pytest.mark.parametrize("path", PS1, ids=lambda p: p.name)
def test_no_powershell6_only_constructs(path):
    code = "\n".join(_code_lines(path.read_text(encoding="utf-8-sig")))
    code = re.sub(r'"[^"\n]*"', '""', code)  # 문자열 안의 ||, ?? 등은 문법이 아니다
    code = re.sub(r"'[^'\n]*'", "''", code)
    hits = [pat for pat in PS6_ONLY if re.search(pat, code)]
    assert not hits, f"{path.name}: PowerShell 6+ 전용 구성요소 {hits}"


@pytest.mark.parametrize("path", PS1, ids=lambda p: p.name)
def test_non_ascii_scripts_have_bom_and_survive_ansi_misreads(path):
    raw = path.read_bytes()
    if all(b < 128 for b in raw):
        return  # 순수 ASCII는 인코딩 해석에 영향받지 않는다
    assert raw[:3] == b"\xef\xbb\xbf", f"{path.name}: 비ASCII가 있는데 UTF-8 BOM이 없다 → PowerShell 5.1이 ANSI로 잘못 읽는다"
    text = raw.decode("utf-8-sig")
    body = raw[3:]  # BOM 없이 읽히는 최악의 경우를 흉내 낸다(파일이 BOM 없이 저장·복사됐을 때)
    for enc in ("cp949", "cp1252"):
        wrong = body.decode(enc, errors="replace")
        for ch in "\"'(){}$`|;[]":
            assert text.count(ch) == wrong.count(ch), f"{path.name}: {enc}로 오독하면 구조 문자 {ch!r}가 변한다"


def test_powershell_files_tracked_in_git_match_scanned_set():
    tracked = subprocess.check_output(["git", "ls-files", "scripts/*.ps1"], cwd=REPO, text=True).split()
    assert {Path(t).name for t in tracked} == {p.name for p in PS1}
