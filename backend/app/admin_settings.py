from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlmodel import Session, select
from sqlmodel import col

from app.models import AdminSetting


def get_setting(session: Session, key: str) -> Optional[dict[str, Any]]:
    row = session.exec(select(AdminSetting).where(col(AdminSetting.key) == key)).first()
    return row.value if row is not None else None


def set_setting(session: Session, key: str, value: dict[str, Any]) -> AdminSetting:
    row = session.exec(select(AdminSetting).where(col(AdminSetting.key) == key)).first()
    if row is None:
        row = AdminSetting(key=key, value=value, updated_at=datetime.utcnow())
    else:
        row.value = value
        row.updated_at = datetime.utcnow()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row

