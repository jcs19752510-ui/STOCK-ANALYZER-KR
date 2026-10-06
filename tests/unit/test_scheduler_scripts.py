"""Windows 작업 스케줄러 스크립트의 정적 점검 — PowerShell이 없는 환경이라 실행 대신 구조를 검사한다(DEC-093).

실제 등록·실행은 사용자 PC에서만 확인할 수 있다(결과서 참조). 여기서는 오타·경로·파일 인코딩로 인한 조용한 실패를 막는다.
"""

# ruff: noqa: E501
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"


def test_all_ps1_scripts_are_ascii_only_except_the_documented_wrapper():
    """Windows PowerShell 5.1은 BOM 없는 .ps1을 CP949로 읽어 한글이 깨진다 — 이 스크립트들은 영문만 쓴다."""
    for name in ("register_daily_batch_task.ps1", "fix_local_data.ps1", "restart_local.ps1", "update_to_latest.ps1", "setup_everything.ps1", "start_local_api.ps1"):
        data = (SCRIPTS / name).read_bytes()
        assert all(b < 128 for b in data), f"{name}에 한글/비ASCII 바이트가 있습니다"


def test_register_script_registers_three_tasks_with_existing_targets():
    text = (SCRIPTS / "register_daily_batch_task.ps1").read_text(encoding="utf-8")
    names = re.search(r"\$names = @\((.*?)\)", text, re.S).group(1)
    assert all(n in names for n in ("StockScreenerKR-DailyBatch", "StockScreenerKR-FreshnessCheck", "StockScreenerKR-InvestorFlow"))
    assert text.count("Register-ScheduledTask") == 3
    # 호출하는 파이썬 스크립트가 실제로 있고, 래퍼가 받는 매개변수 이름과 같다
    wrapper = (SCRIPTS / "run_daily_batch.ps1").read_text(encoding="utf-8")
    assert "[string]$Script" in wrapper and "[string]$LogName" in wrapper
    for target in re.findall(r"-Script (scripts\\[a-z_]+\.py)", text):
        assert (ROOT / target.replace("\\", "/")).exists(), target
    assert 'New-ScheduledTaskTrigger -Daily -At "20:10"' in text
    assert "collect_investor_flow.py" in text and "investor_flow.log" in text


def test_investor_flow_is_scheduled_after_its_own_20_00_cutoff():
    flow = (SCRIPTS / "collect_investor_flow.py").read_text(encoding="utf-8")
    assert "20:00" in flow  # 스크립트 자체 규칙: 20:00 이전엔 당일 행 미적재
    assert "10 20 * * *" in (SCRIPTS / "crontab.example").read_text(encoding="utf-8")


def test_fix_script_registers_when_any_task_missing():
    text = (SCRIPTS / "fix_local_data.ps1").read_text(encoding="utf-8")
    assert "StockScreenerKR-InvestorFlow" in text and "$null -eq $task -or $null -eq $taskFlow" in text


def test_fix_script_loads_all_calendar_files():
    text = (SCRIPTS / "fix_local_data.ps1").read_text(encoding="utf-8")
    assert 'data\\calendar' in text and '-Filter "20??.yaml"' in text and "load_calendar.py" in text
    assert (ROOT / "data" / "calendar" / "2027.yaml").exists()
