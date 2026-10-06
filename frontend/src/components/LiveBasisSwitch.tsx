import copy from "@/content/copy.ko.json";

/** 결과 목록 위의 "장중 기준" 전환 스위치. 접근이 있을 때만 부모가 그린다. */
export function LiveBasisSwitch({ on, onChange }: { on: boolean; onChange: (on: boolean) => void }) {
  return (
    <div className="live-switch">
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-describedby="live-switch-hint"
        className="live-switch__control"
        onClick={() => onChange(!on)}
      >
        <span className="live-switch__track" aria-hidden="true">
          <span className="live-switch__thumb" />
        </span>
        <span className="live-switch__label">{copy.liveScreen.switchLabel}</span>
        <span className="live-switch__state">{on ? copy.liveScreen.switchOnState : copy.liveScreen.switchOffState}</span>
      </button>
      <span id="live-switch-hint" className="live-switch__hint">
        {copy.liveScreen.switchHint}
      </span>
    </div>
  );
}
