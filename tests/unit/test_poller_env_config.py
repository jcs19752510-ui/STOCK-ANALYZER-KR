"""시세 수신기 호출 간격 환경설정(DEC-097): 기본 초당 약 8건, 하한·잘못된 값 방어."""

from services.public_api.api.local_market import DEFAULT_ENV_MIN_INTERVAL, poller_config_from_env
from services.public_api.realtime.market import calls_per_cycle


def test_default_interval_is_eight_calls_per_second(monkeypatch):
    monkeypatch.delenv("KIS_MARKET_MIN_INTERVAL", raising=False)
    cfg = poller_config_from_env()
    assert cfg.min_interval == DEFAULT_ENV_MIN_INTERVAL == 0.125
    # 전 종목(2766) 한 바퀴 이론 시간 ≈ 12초(공식 한도 20건/초의 40%)
    assert 10 < calls_per_cycle(2766) * cfg.min_interval < 14
    assert 1 / cfg.min_interval <= 20 * 0.5


def test_env_override_and_floor(monkeypatch):
    monkeypatch.setenv("KIS_MARKET_MIN_INTERVAL", "0.5")
    assert poller_config_from_env().min_interval == 0.5
    monkeypatch.setenv("KIS_MARKET_MIN_INTERVAL", "0.001")
    assert poller_config_from_env().min_interval == 0.06  # 하한: 한도 초과 방지
    monkeypatch.setenv("KIS_MARKET_MIN_INTERVAL", "abc")
    assert poller_config_from_env().min_interval == DEFAULT_ENV_MIN_INTERVAL
