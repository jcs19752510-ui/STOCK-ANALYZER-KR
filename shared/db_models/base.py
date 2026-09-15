from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """모든 스키마(reference/public_serving/raw_internal) 공용 베이스.

    raw_internal 모델은 이 저장소에 아직 없다(UNIT-02 이후). 03-system-design.md
    §1-3 "/shared: raw 데이터 모델 코드 없음" 원칙에 따라, 이 base는 어떤 스키마의
    모델이든 상속할 수 있는 순수 SQLAlchemy 기반 클래스일 뿐 raw 전용이 아니다.
    """
