# UNIT-19~22 구현·검증 결과 (2026-10-02, DEC-041 종목 상세 C안 1단계)

## 1. 구현 요약
| UNIT | 내용 | 산출물 |
|---|---|---|
| 19 | 공개 일봉 테이블 `public_serving.daily_prices`(0012) + Derivation Batch 복사(`sync_daily_prices`, 멱등 upsert, KRX만, 400일 보존) | `db/alembic/versions/0012_*.py`, `shared/db_models/public_serving.py`(DailyPrice), `services/derivation_batch/repository.py`·`run_derivation.py` |
| 20 | `GET /api/v1/stocks/{code}/prices`(일봉·전일대비·신선도), `GET /api/v1/stocks/{code}/pattern-check`(단일 종목 조건 체크, 서열 필드 없음) | `api/prices.py`, `db/price_repository.py`, `schemas/prices.py`, `api/pattern.py` |
| 21 | 지표 계산(SMA·EMA·MACD·주/월봉 집계) + SVG 차트(캔들·MA5/10/20/60·거래량·MACD, 포인터·방향키 선택) | `frontend/src/lib/chartIndicators.ts`, `components/StockChart.tsx` |
| 22 | 종목 상세: 헤더(현재가·전일대비·기준일), 탭(차트·일자별 시세·투자자 준비 중·조건 체크) | `components/StockDetailTabs.tsx`, `app/stocks/[code]/page.tsx`, `lib/stockDetailApi.ts` |

원칙 유지: `api_service`의 `raw_internal` 접근 차단 그대로(테스트로 확인), 기존 `/screen`·`/screen/pattern` 응답 계약 불변, 새 의존성 없음(`package.json` 불변), 호가 탭·뉴스 없음, 수급은 "준비 중" 안내.

## 2. 실제 실행 결과
- `pytest tests/unit tests/integration`: **686 passed** (착수 전 658 → +28: 일봉 단위 17, 일봉 통합 7, 조건 체크 단위 3·통합 1).
- 프론트 지표 계산: `node --experimental-strip-types --test scripts/check-chart-indicators.mjs` **10 pass**(SMA·EMA·MACD 독립 계산 대조, 주/월봉 경계, 결측 처리).
- `tsc --noEmit`·`eslint src`·`lint-forbidden-copy` 통과, ruff 통과(변경 파일).
- 개발 DB(승인): 0012 적용 → 2026-09-21 파생 재실행 SUCCESS → `daily_prices` 339,313행(2026-04-01~09-21). 개발 백엔드(4001) 재시작.
- 실브라우저(4000 `/stocks/032640`): 헤더 14,490 ▲440(3.13%) 2026-09-21 종가 기준, 캔들·MA·거래량·MACD 표시, 탭 4개 전환(터치 높이 44px), 일자별 표·조건 체크 값이 API와 일치, 가로 페이지 스크롤 없음(1280 기준).

## 3. 한계·미확인
- 모바일 폭(360px) 실브라우저 점검, 키보드(←→) 선택 동작의 실기 점검은 아직 하지 않음.
- 개발 DB 데이터는 2026-09-21까지(최신일 파생은 재무·시총 미수집으로 보류) → "7영업일 지연" 안내가 표시되는 것이 정상.
- 일봉 복사는 파생 배치 실행 시점에 동기화됨(배치 스케줄은 사용자 보류 사항).
- UNIT-22 후반(관심종목형 리스트 행 스타일), UNIT-23(실적 탭: DART에서 매출·영업이익 확장 필요, 현재 순이익·자본만 보유)은 미착수.
