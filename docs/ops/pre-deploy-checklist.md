# 배포 전 사용자 확인 체크리스트 (2026-10-02)

> **배포 방법(Oracle 무료 VM + R2 백업 + 승인형 자동 배포)은 `docs/ops/oracle-deploy-guide.md`** 를 따른다(DEC-060). 이 체크리스트의 A~D는 그 문서의 1번·13번과 함께 확인한다.

개발 쪽에서 끝낸 일은 `docs/stock-detail/02-test-report.md`·`docs/ops/daily-batch-runbook.md` 참조.
아래는 **사용자만 할 수 있는** 항목이다. 하나라도 미결이면 배포(12단계)를 진행하지 않는다.

## A. 데이터 약관·법률 (R3, REQ-022) — 켜기 전 확인 항목
> **현재 기본은 켜짐(DEC-050)**: 차트·일자별 시세·목록 시세가 보인다. **외부 공개 배포 전에는 아래 확인 결과에 따라 `PUBLIC_API_PRICE_EXPOSURE_ENABLED=false`, `NEXT_PUBLIC_PRICE_EXPOSURE_ENABLED=false`(프론트 재빌드)로 끌지 결정한다.** 내 PC 개발·검수용은 기본 그대로 쓰면 된다.
- [ ] 공공데이터포털 "금융위원회_주식시세정보" 약관 원문 재확인. 원문은 *"상업적 목적 여부와 상관없이 제3자 무단 제공 및 재배포가 엄격히 금지"* 이며, 상업 이용은 원천 소유자(KRX Data Marketplace) 경유를 안내한다(`docs/harness/02-planning.md` §4-3).
- [ ] **일봉 시세 원값 공개(DEC-041)**가 위 약관의 "재배포"에 해당하는지 KRX 서면 문의 또는 변호사 검토로 확정. 해당하면 ① 꺼진 상태 유지(가공 지표만) ② KRX Data Marketplace 정식 이용 계약 후 켠다. 허용되면 스위치를 켠다.
- [ ] DART 재무 수치(공시 정보) 이용 조건 확인(opendart 이용약관, 출처 표기 의무 여부).
- [ ] **Q4(REQ-022)**: 패턴 스크리닝 화면 명칭 "급등 전 압축주"와 "급등 이력" 문구의 공개 배포 적합성(법률·표현 검토). 서비스 이름은 가칭이라 상표 검색도 함께.
- [ ] 면책 문구·금지 표현(추천/수익보장 등) 최종 법률 검수(REQ-007~010).

## B. 실기기·시각 검수 (R4, R8)
- [ ] (스위치를 끈 배포 설정 확인용) 종목 상세에 현재가·차트·일자별 시세가 없고 안내 문구·실적·수급·조건 체크 탭만 보이는지.
- [ ] iPhone Safari / Android Chrome에서 `/`, `/screener`, `/stocks/005930`: 가로 스크롤 없음, 탭·버튼 터치 44px 이상, 차트 터치 이동·선택 동작.
- [ ] 종목 상세: 헤더 현재가·전일대비, 차트(캔들·MA·거래량·MACD), 일자별 시세 표, 실적 탭 "-" 표기, 수급 "준비 중".
- [ ] 라이트/다크, 확대 200%에서 레이아웃 깨짐 없음, 키보드(Tab·←→·Esc)·스크린리더 기본 흐름.
- [ ] 데이터 지연 안내("N영업일 지연")가 최신일 기준으로 맞게 표시.

## C. 환경 설정 (배포 시)
- [ ] `PUBLIC_API_INTERNAL_TOKEN`(API·프론트 동일 값, 프론트는 `NEXT_PUBLIC_` 접두어 금지), `FRONTEND_TRUSTED_PROXY_HOPS`, API 앞 프록시가 있으면 `PUBLIC_API_TRUSTED_PROXY_IPS` (DEC-045).
- [ ] `PUBLIC_API_CORS_ALLOWED_ORIGINS`를 실제 프론트 도메인으로, HTTPS 강제(HSTS).
- [ ] 사용자 PC에서 `scripts/register_daily_batch_task.ps1` 1회 실행, `DATA_FRESHNESS_WEBHOOK_URL` 설정, 다음 날 `logs/daily_batch.log`로 첫 따라잡기 확인(누락 4거래일 09-22·23·30, 10-01).
- [ ] 공공데이터 일일 호출 한도(마이페이지 확인)와 실제 공개 시각 확인 후 14:30/18:30 조정.

## C-2. 개인 로컬 모드(증권사 시세, DEC-052) — 외부 공개 배포 시 반드시 꺼짐
- [ ] API 환경에 `LOCAL_INTRADAY_ENABLED`, `KIS_APP_KEY`, `KIS_APP_SECRET`이 **없다**(또는 false). 프론트 빌드에 `NEXT_PUBLIC_LOCAL_INTRADAY_ENABLED`가 **없다**.
- [ ] 서버/컨테이너에 `.env`·`.local/kis_token.json`이 올라가지 않았다.
- [ ] 개인 PC에서 켜 쓸 때는 `docs/ops/local-intraday-guide.md` §8 안전 수칙을 지킨다. 사용자 PC에서 `scripts/kis_smoke_test.py`를 장중에 1회 실행해 실제 응답을 확인했다(미확인 항목: 테스트 결과서 §8-1).

## D. 기능 범위 (R7)
- [x] 수급(투자자별): **미제공 유지로 결정(DEC-049)**. 호가·뉴스도 제외 유지. 재개는 R3 법률 검토 이후 KRX Data Marketplace 비용·약관 확인부터.
