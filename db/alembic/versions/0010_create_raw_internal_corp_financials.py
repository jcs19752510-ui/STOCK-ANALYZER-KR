"""create raw_internal.raw_corp_financials table + grants (DART 연동, PER/PBR·업종 실데이터)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-22

DART(전자공시시스템) OpenAPI에서 수집한 재무 원문(지배기업 소유주지분 기준
당기순이익/자본총계)을 저장한다. 공공데이터포털 "금융위원회_주식시세정보"가
PER/PBR을 제공하지 않는다는 사실이 실측(DEF-005)으로 확정된 이후 도입한
대체 소스다 — KRX Open API의 "주식" 카테고리(8개 API)에도 PER/PBR·업종분류가
없고, KRX Data Marketplace의 해당 상품은 유료 구매 항목으로 확인되어(2026-09-22
사용자 실측 스크린샷) 무료·API 경로인 DART로 전환했다.

이 테이블은 `raw_ohlcv`/`raw_fundamentals`(0004)와 동일하게 raw_internal
스키마·batch_worker 전용 권한 패턴을 따른다(DEF-003 교훈 — 테이블 생성과
GRANT를 같은 리비전에 포함, api_service에는 REVOKE로 무권한 상태를 명시).

재무제표는 일별이 아니라 분기/연도 단위로 갱신되므로 `raw_fundamentals`처럼
(stock_code, trade_date) 복합키가 아니라 **stock_code 단일 PK로 "가장 최근
확인된 값"만 유지**한다(매일 배치가 재수집해도 같은 분기 데이터면 그대로
덮어써 최신 상태를 유지, 이력 보존은 이번 범위에 포함하지 않음).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "raw_corp_financials",
        sa.Column("stock_code", sa.String(length=6), primary_key=True, nullable=False),
        sa.Column("corp_code", sa.String(length=8), nullable=False),
        sa.Column("bsns_year", sa.String(length=4), nullable=False),
        sa.Column("reprt_code", sa.String(length=5), nullable=False),
        sa.Column("fs_div", sa.String(length=3), nullable=False),
        # 지배기업 소유주지분 기준(연결) 또는 총계(개별, 자회사 없어 지배지분
        # 항목이 없는 경우) 당기순이익. 음수(적자) 가능 — PER 산정 불가 판단에
        # 그대로 쓰인다(화면 "PER 산정 불가(적자기업 등)" 표시, 지어내지 않음).
        sa.Column("net_income", sa.Numeric(), nullable=True),
        sa.Column("equity", sa.Numeric(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "source_batch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("public_serving.batch_run.batch_run_id"),
            nullable=True,
        ),
        schema="raw_internal",
    )

    op.execute(
        "GRANT SELECT, INSERT, UPDATE ON raw_internal.raw_corp_financials TO batch_worker"
    )
    op.execute("REVOKE ALL ON raw_internal.raw_corp_financials FROM api_service")


def downgrade() -> None:
    op.execute("REVOKE ALL ON raw_internal.raw_corp_financials FROM batch_worker")
    op.drop_table("raw_corp_financials", schema="raw_internal")
