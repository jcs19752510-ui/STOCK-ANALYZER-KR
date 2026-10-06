/**
 * 장중 기준 화면의 상태 모양과 빈 상태. 컨트롤러(요청 쪽)와 화면 훅이 함께 쓰는 얇은 모듈이다(요청·오류 코드 규칙은 담지 않는다).
 */
import { DEFAULT_REFRESH_SECONDS, EMPTY_CHANGE_LOG, type ChangeLog } from "./logic.ts";
import type { LiveError, LiveMeta, LiveScreenKind } from "./types.ts";

export interface LiveQuery {
  kind: LiveScreenKind;
  /** `page`·`snapshot_id`를 뺀 조건 문자열(일봉 화면의 빌더가 만든 것에서 `stripLiveParams`로 정리) */
  params: string;
}

export interface LiveHttp {
  status: number;
  body: unknown;
}

export interface LiveScreenView<T> {
  query: LiveQuery | null;
  page: number;
  /** 마지막으로 성공한 응답의 데이터(조건이 바뀌면 비워진다) */
  data: T | null;
  meta: LiveMeta | null;
  /** 마지막 성공 응답을 받은 시각(브라우저 epoch 초) */
  receivedAt: number | null;
  /** 응답 봉투의 서버 시각(epoch 초). 계산 시각의 경과를 시계 어긋남 없이 구하는 데 쓴다. */
  generatedAt: number | null;
  /** 요청이 진행 중 */
  loading: boolean;
  paused: boolean;
  pinnedSnapshotId: string | null;
  /** 가장 최근 시도의 오류(성공하면 null). `data`가 남아 있으면 "지연" 상태다. */
  error: LiveError | null;
  failures: number;
  /** 다음 재시도까지(ms). 재시도하지 않거나 일시정지면 null */
  retryInMs: number | null;
  refreshSeconds: number;
  changeLog: ChangeLog;
  names: Record<string, string>;
  /** 일시정지 중 고정한 계산 결과가 만료되어 새로 계산했음 */
  expiredNotice: boolean;
  seq: number;
}

export const EMPTY_LIVE_VIEW: LiveScreenView<never> = {
  query: null,
  page: 1,
  data: null,
  meta: null,
  receivedAt: null,
  generatedAt: null,
  loading: false,
  paused: false,
  pinnedSnapshotId: null,
  error: null,
  failures: 0,
  retryInMs: null,
  refreshSeconds: DEFAULT_REFRESH_SECONDS,
  changeLog: EMPTY_CHANGE_LOG,
  names: {},
  expiredNotice: false,
  seq: 0,
};

