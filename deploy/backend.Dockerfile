# Backend image: public API, batch jobs and DB migrations all use this one image.
# Build from the repo root:  docker build -f deploy/backend.Dockerfile .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# tzdata: the code uses ZoneInfo("Asia/Seoul"); the slim image has no timezone database.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY db ./db
COPY shared ./shared
COPY services ./services
COPY scripts ./scripts
COPY data ./data

USER app
EXPOSE 8000
# The official launcher (never run uvicorn directly: DEF-SEC-03, proxy header trust).
CMD ["python", "scripts/run_public_api.py"]
