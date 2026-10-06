# 통합 이미지(DEC-078): 웹(Next.js)과 API(FastAPI)를 컨테이너 1개에서 함께 실행한다.
# 진입점 scripts/run_unified.py 가 API(내부 127.0.0.1:8000)를 먼저 띄운 뒤 웹(공개 PORT)을 띄우고 둘을 감시한다.
# NEXT_PUBLIC_* 값은 브라우저 번들에 빌드 때 들어간다(빌드 인자). API 주소 기본값은 같은 컨테이너 내부 주소다.
# 저장소 루트에서 빌드:  docker build -f deploy/unified.Dockerfile .
FROM node:22-bookworm-slim AS web-build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./

ARG NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
ARG NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED=false
ARG NEXT_PUBLIC_PATTERN_SCREEN_ENABLED=true
ARG NEXT_PUBLIC_BROWSER_API_BASE_URL
ARG NEXT_PUBLIC_AUTH_ENABLED
# 일부러 설정하지 않음: NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED (내 PC 전용 기능은 공개 배포에서 꺼 둔다).
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED=${NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED} \
    NEXT_PUBLIC_PATTERN_SCREEN_ENABLED=${NEXT_PUBLIC_PATTERN_SCREEN_ENABLED} \
    NEXT_PUBLIC_BROWSER_API_BASE_URL=${NEXT_PUBLIC_BROWSER_API_BASE_URL} \
    NEXT_PUBLIC_AUTH_ENABLED=${NEXT_PUBLIC_AUTH_ENABLED}
RUN npm run build

FROM node:22-bookworm-slim AS web-deps
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    UNIFIED_API_PORT=8000 \
    UNIFIED_WEB_DIR=/app/frontend

# tzdata: 코드가 ZoneInfo("Asia/Seoul")을 쓴다. libstdc++6: node 실행 파일이 필요로 한다.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata libstdc++6 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app

COPY --from=web-build /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY db ./db
COPY shared ./shared
COPY services ./services
COPY scripts ./scripts
COPY data ./data

COPY --from=web-deps --chown=app:app /app/node_modules ./frontend/node_modules
COPY --from=web-build --chown=app:app /app/package.json /app/package-lock.json /app/next.config.mjs ./frontend/
COPY --from=web-build --chown=app:app /app/.next ./frontend/.next

USER app
EXPOSE 3000
# 공식 기동기만 쓴다(uvicorn 직접 실행 금지: DEF-SEC-03). run_unified.py 가 run_public_api.py 와 next 를 실행한다.
CMD ["python", "scripts/run_unified.py"]
