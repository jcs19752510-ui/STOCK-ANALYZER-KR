"""통합 서비스 배포 파일(DEC-078) 정적 점검. 시험 환경에 Docker가 없어 이미지를 빌드하지 못하므로,
Dockerfile이 참조하는 경로·실행 명령이 맞는지 파일 기준으로 확인한다. (Render 블루프린트 시험은 DEC-101에서 삭제)"""

# ruff: noqa: E501
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = (REPO / "deploy" / "unified.Dockerfile").read_text(encoding="utf-8")


def final_stage() -> str:
    return DOCKERFILE.split("FROM python:3.12-slim-bookworm", 1)[1]


def test_복사하는_로컬_경로가_모두_존재한다() -> None:
    for line in DOCKERFILE.splitlines():
        m = re.match(r"^COPY\s+(?!--from)(?:--chown=\S+\s+)?(.+)\s+\S+$", line.strip())
        if not m:
            continue
        for src in m.group(1).split():
            assert (REPO / src.rstrip("/")).exists(), f"COPY 원본 없음: {src}"


def test_컨테이너에_필요한_코드_폴더가_들어간다() -> None:
    for needed in ("alembic.ini", "db", "shared", "services", "scripts", "data", "requirements.txt"):
        assert re.search(rf"^COPY {re.escape(needed)}\b", final_stage(), re.M), needed


def test_일반_계정으로_실행하고_공식_기동기만_쓴다() -> None:
    tail = final_stage()
    assert tail.index("USER app") < tail.index("CMD ")
    assert 'CMD ["python", "scripts/run_unified.py"]' in tail
    assert "uvicorn services" not in DOCKERFILE  # DEF-SEC-03: 직접 실행 금지(공식 기동기 경유)
    assert (REPO / "scripts" / "run_unified.py").exists() and (REPO / "scripts" / "run_public_api.py").exists()


def test_웹_실행에_필요한_산출물이_최종_이미지에_있다() -> None:
    tail = final_stage()
    for item in ("/usr/local/bin/node", "/app/node_modules", "/app/.next", "/app/next.config.mjs"):
        assert item in tail, item
    assert "UNIFIED_WEB_DIR=/app/frontend" in tail
    assert "./frontend/node_modules" in tail and "./frontend/.next" in tail
    assert "libstdc++6" in tail and "tzdata" in tail


def test_내_PC_전용_기능은_이미지에서_꺼져_있다() -> None:
    assert "NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED" not in re.sub(r"#.*", "", DOCKERFILE)


def test_자동_배포_워크플로는_없다() -> None:
    assert not (REPO / ".github" / "workflows" / "render-deploy.yml").exists()  # Render 미사용(DEC-100)
    assert not (REPO / "render.yaml").exists()  # DEC-101: Render 설정 파일 삭제
