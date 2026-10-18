from datetime import datetime, timezone

from sqlalchemy import DateTime, TypeDecorator, func
from sqlalchemy.orm import DeclarativeBase, mapped_column


class Base(DeclarativeBase):
    pass


class AwareDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("datetime must include a timezone")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


def created_at_column():
    return mapped_column(AwareDateTime(), server_default=func.now())


def updated_at_column():
    return mapped_column(AwareDateTime(), server_default=func.now(), onupdate=func.now())
