"""통합 서비스 배포 파일(DEC-078) 정적 점검. 시험 환경에 Docker가 없어 이미지를 빌드하지 못하므로,
Dockerfile이 참조하는 경로·실행 명령·블루프린트 환경변수·워크플로 조건이 서로 맞는지 파일 기준으로 확인한다."""

# ruff: noqa: E501
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
DOCKERFILE = (REPO / "deploy" / "unified.Dockerfile").read_text(encoding="utf-8")
BLUEPRINT = yaml.safe_load((REPO / "render.yaml").read_text(encoding="utf-8"))  # 전환 후 운영 블루프린트(통합)
LIVE_BLUEPRINT = yaml.safe_load((REPO / "deploy" / "render" / "render.two-services.yaml").read_text(encoding="utf-8"))  # 이전 2개 서비스(롤백용)
WORKFLOW = (REPO / ".github" / "workflows" / "render-deploy.yml").read_text(encoding="utf-8")


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


def test_브라우저_번들_빌드_인자가_블루프린트_환경변수와_맞는다() -> None:
    args = set(re.findall(r"^ARG (NEXT_PUBLIC_[A-Z_]+)", DOCKERFILE, re.M))
    keys = {e["key"] for e in BLUEPRINT["services"][0]["envVars"]}
    assert {"NEXT_PUBLIC_BROWSER_API_BASE_URL", "NEXT_PUBLIC_AUTH_ENABLED", "NEXT_PUBLIC_API_BASE_URL"} <= args
    assert args <= keys  # 빌드 인자는 Render 환경변수(= 빌드 인자로 전달됨)로 모두 공급된다


def test_블루프린트는_서비스_1개이고_웹_이름과_주소를_유지한다() -> None:
    assert len(BLUEPRINT["services"]) == 1
    svc = BLUEPRINT["services"][0]
    assert svc["name"] == "stock-analyzer-web" and svc["name"] in {s["name"] for s in LIVE_BLUEPRINT["services"]}
    assert svc["dockerfilePath"] == "./deploy/unified.Dockerfile" and svc["healthCheckPath"] == "/healthz"
    assert svc["branch"] == "PROD_SCH" and svc["autoDeployTrigger"] == "off" and svc["plan"] == "starter"


def test_블루프린트가_기존_두_서비스의_환경변수를_빠짐없이_포함한다() -> None:
    merged = {e["key"] for e in BLUEPRINT["services"][0]["envVars"]}
    web = {e["key"] for e in next(s for s in LIVE_BLUEPRINT["services"] if s["name"] == "stock-analyzer-web")["envVars"]}
    api = {e["key"] for e in next(s for s in LIVE_BLUEPRINT["services"] if s["name"] == "stock-analyzer-api")["envVars"]}
    assert web <= merged, f"웹 값 누락: {web - merged}"
    # API 쪽에서 통합 후에도 필요한 값(주소·포트·프록시 대역·CORS는 제외: 같은 컨테이너 내부 통신이라 필요 없다)
    dropped = {"PUBLIC_API_CORS_ALLOWED_ORIGINS", "PUBLIC_API_TRUSTED_PROXY_IPS", "PUBLIC_API_LOG_PEER_IPS", "PUBLIC_API_HOST", "PUBLIC_API_PORT"}
    assert api - dropped <= merged, f"API 값 누락: {api - dropped - merged}"


def test_비밀값은_저장소에_값을_쓰지_않는다() -> None:
    env = {e["key"]: e for e in BLUEPRINT["services"][0]["envVars"]}
    for key in ("PUBLIC_API_DATABASE_URL", "PUBLIC_API_AUTH_DATABASE_URL", "PUBLIC_API_INTERNAL_TOKEN", "SESSION_SECRET"):
        assert env[key].get("sync") is False and "value" not in env[key], key


def test_통합_구성의_고정값() -> None:
    env = {e["key"]: e.get("value") for e in BLUEPRINT["services"][0]["envVars"]}
    assert env["NEXT_PUBLIC_API_BASE_URL"] == "http://127.0.0.1:8000"  # 같은 컨테이너 내부 API 주소(run_unified.py 기본 포트와 같다)
    assert env["PUBLIC_API_REQUIRE_INTERNAL_TOKEN"] == "true"
    assert env["PUBLIC_API_REQUIRE_TRUSTED_PROXY"] == "false"  # true면 프록시 대역이 비어 API가 기동을 거부한다
    assert env["PORT"] == "3000"


def test_워크플로는_API_배포_훅_없이도_배포한다() -> None:
    gate = re.search(r"for v in ([A-Z_ ]+); do", WORKFLOW).group(1).split()
    assert "RENDER_DEPLOY_HOOK_WEB" in gate and "RENDER_DEPLOY_HOOK_API" not in gate
    assert 'if [ -n "$RENDER_DEPLOY_HOOK_API" ]' in WORKFLOW
    assert "deploy/**" not in WORKFLOW.split("paths-ignore:")[1].split("workflow_dispatch")[0].replace("deploy/tests/**", "")  # 배포 파일 변경은 배포를 일으킨다
