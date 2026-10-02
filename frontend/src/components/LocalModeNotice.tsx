import copy from "@/content/copy.ko.json";

/** 개인 로컬 모드 안내 — 내 증권사 계정으로 받은 시세를 외부에 공개하지 않도록 상기시킨다(DEC-052). */
export function LocalModeNotice() {
  return (
    <p className="local-notice" role="note">
      {copy.stockDetail.localNotice}
    </p>
  );
}
