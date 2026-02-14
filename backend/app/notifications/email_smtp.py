from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Optional

from app.settings import settings


class EmailSendError(RuntimeError):
    pass


def send_email_smtp(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> None:
    """
    Minimal SMTP sender for pilot stage.

    Required env:
    - WEALTHPULSE_SMTP_HOST
    - WEALTHPULSE_SMTP_USER
    - WEALTHPULSE_SMTP_PASSWORD
    - WEALTHPULSE_SMTP_FROM_EMAIL
    """

    host = (settings.smtp_host or "").strip()
    user = (settings.smtp_user or "").strip()
    password = settings.smtp_password or ""
    from_email = (settings.smtp_from_email or "").strip()

    if not host or not user or not password or not from_email:
        raise EmailSendError(
            "SMTP settings missing. Set WEALTHPULSE_SMTP_HOST/USER/PASSWORD/FROM_EMAIL."
        )

    msg = EmailMessage()
    msg["From"] = f"{settings.smtp_from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        if settings.smtp_use_starttls:
            with smtplib.SMTP(host, int(settings.smtp_port), timeout=30) as s:
                s.ehlo()
                s.starttls()
                s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(host, int(settings.smtp_port), timeout=30) as s:
                s.login(user, password)
                s.send_message(msg)
    except Exception as e:
        raise EmailSendError(str(e)) from e

