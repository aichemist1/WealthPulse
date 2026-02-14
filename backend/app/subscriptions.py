from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import Session, select
from sqlmodel import col

from app.models import Subscriber, SubscriberToken


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class IssuedToken:
    token: str
    expires_at: datetime


def issue_token(
    *,
    session: Session,
    subscriber_id: str,
    purpose: str,
    ttl_hours: int = 48,
) -> IssuedToken:
    token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
    row = SubscriberToken(
        token_hash=_hash_token(token),
        purpose=purpose,
        subscriber_id=subscriber_id,
        expires_at=expires_at,
    )
    session.add(row)
    session.commit()
    return IssuedToken(token=token, expires_at=expires_at)


def _get_valid_token_row(*, session: Session, token: str, purpose: str) -> Optional[SubscriberToken]:
    th = _hash_token(token)
    now = datetime.utcnow()
    return session.exec(
        select(SubscriberToken)
        .where(
            col(SubscriberToken.token_hash) == th,
            col(SubscriberToken.purpose) == purpose,
            col(SubscriberToken.used_at) == None,  # noqa: E711
            col(SubscriberToken.expires_at) >= now,
        )
        .order_by(col(SubscriberToken.created_at).desc())
    ).first()


def upsert_subscriber(*, session: Session, email: str) -> Subscriber:
    email_n = normalize_email(email)
    if not email_n or "@" not in email_n:
        raise ValueError("Invalid email")

    s = session.exec(select(Subscriber).where(col(Subscriber.email) == email_n)).first()
    if s is None:
        s = Subscriber(email=email_n, status="pending")
        session.add(s)
        session.commit()
        session.refresh(s)
        return s

    # If previously unsubscribed, allow re-subscribe by returning to pending.
    if s.status == "unsubscribed":
        s.status = "pending"
        s.unsubscribed_at = None
        session.add(s)
        session.commit()
        session.refresh(s)

    return s


def confirm_subscription(*, session: Session, token: str) -> bool:
    row = _get_valid_token_row(session=session, token=token, purpose="confirm")
    if row is None:
        return False
    sub = session.exec(select(Subscriber).where(col(Subscriber.id) == row.subscriber_id)).first()
    if sub is None:
        return False

    now = datetime.utcnow()
    row.used_at = now
    sub.status = "active"
    sub.confirmed_at = sub.confirmed_at or now
    session.add(row)
    session.add(sub)
    session.commit()
    return True


def unsubscribe(*, session: Session, token: str) -> bool:
    row = _get_valid_token_row(session=session, token=token, purpose="unsubscribe")
    if row is None:
        return False
    sub = session.exec(select(Subscriber).where(col(Subscriber.id) == row.subscriber_id)).first()
    if sub is None:
        return False

    now = datetime.utcnow()
    row.used_at = now
    sub.status = "unsubscribed"
    sub.unsubscribed_at = now
    session.add(row)
    session.add(sub)
    session.commit()
    return True

