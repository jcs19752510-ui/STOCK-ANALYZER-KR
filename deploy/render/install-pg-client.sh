#!/usr/bin/env bash
# GitHub Actions(ubuntu)에 PostgreSQL 클라이언트(pg_dump 등)를 설치한다.
# pg_dump는 접속하는 서버보다 버전이 낮으면 거부하므로, Neon 서버 버전(기본 18)에 맞춘다.
# 사용: bash deploy/render/install-pg-client.sh [메이저버전]   (환경변수 PG_CLIENT_MAJOR로도 지정 가능)
set -euo pipefail

major="${1:-${PG_CLIENT_MAJOR:-18}}"
case "$major" in
  ''|*[!0-9]*) echo "[오류] 버전은 숫자여야 합니다: '$major'" >&2; exit 2 ;;
esac

sudo apt-get update -qq
sudo apt-get install -y -qq postgresql-common
# 공식 PGDG 저장소 등록(기본 우분투 저장소에는 최신 메이저가 없을 수 있다)
sudo /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
sudo apt-get install -y -qq "postgresql-client-${major}"

bin="/usr/lib/postgresql/${major}/bin"
[ -x "$bin/pg_dump" ] || { echo "[오류] $bin/pg_dump 가 없습니다" >&2; exit 1; }
# 여러 버전이 있어도 방금 설치한 것이 먼저 잡히도록 한다.
if [ -n "${GITHUB_PATH:-}" ]; then echo "$bin" >> "$GITHUB_PATH"; fi
export PATH="$bin:$PATH"
pg_dump --version
