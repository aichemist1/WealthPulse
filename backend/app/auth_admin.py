from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Optional


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(txt: str) -> bytes:
    pad = "=" * (-len(txt) % 4)
    return base64.urlsafe_b64decode((txt + pad).encode("utf-8"))


@dataclass(frozen=True)
class AdminToken:
    token: str
    expires_at: int


def issue_admin_token(*, secret: str, ttl_hours: int = 24, now_s: Optional[int] = None) -> AdminToken:
    now = int(now_s if now_s is not None else time.time())
    exp = now + int(max(1, ttl_hours) * 3600)
    payload = {"v": 1, "iat": now, "exp": exp}
    payload_b = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    data = _b64url_encode(payload_b)
    sig = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).digest()
    token = f"{data}.{_b64url_encode(sig)}"
    return AdminToken(token=token, expires_at=exp)


def verify_admin_token(*, secret: str, token: str, now_s: Optional[int] = None) -> dict[str, Any] | None:
    try:
        data, sig_txt = token.split(".", 1)
    except Exception:
        return None
    try:
        sig = _b64url_decode(sig_txt)
    except Exception:
        return None

    expected = hmac.new(secret.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected):
        return None

    try:
        payload = json.loads(_b64url_decode(data).decode("utf-8"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int):
        return None
    now = int(now_s if now_s is not None else time.time())
    if now >= exp:
        return None
    return payload


def admin_secret(*, admin_password: str, admin_token_secret: str) -> str:
    """
    Prefer an explicit token secret; fall back to the password for pilot simplicity.
    """

    s = (admin_token_secret or "").strip()
    if s:
        return s
    return (admin_password or "").strip()


def verify_bearer_header(*, secret: str, authorization: str) -> bool:
    if not authorization:
        return False
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return False
    tok = parts[1].strip()
    if not tok:
        return False
    return verify_admin_token(secret=secret, token=tok) is not None

