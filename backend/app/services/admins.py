"""Triyana Ops admin accounts: each admin has their own email + password login for /admin.

* Admins are separate from patient and provider accounts, so a doctor or patient login can never open /admin.
* Admins add and remove other admins in /admin → Admins. You can't remove yourself or the last admin.
* ``TRIYANA_ADMINS`` seeds admins at startup, so logins survive a database that is wiped on every deploy:
  ``email:password`` entries separated by ``;`` or new lines (passwords may contain ``:`` and ``,``).
  An entry is created when missing; changing its password in the env var resets that admin's password.
* The old shared key (``TRIYANA_ADMIN_KEY``, or ``demo-admin`` on the demo site) only works while no admin
  account exists, to create the first one.
"""
from __future__ import annotations

import hashlib
import os
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..errors import Conflict, Forbidden, NotFound
from ..models import AdminAccount, AdminSession, utcnow
from .accounts import (_check_rate, _fail, check_password, hash_password, normalize_email,
                       validate_password)

SESSION_PREFIX = "tya_"
SESSION_HOURS = 12
_DUMMY_HASH = hash_password("timing-equaliser-1")


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _fingerprint(email: str, password: str) -> str:
    secret = os.environ.get("TRIYANA_SECRET", "triyana-demo-secret-change-me")
    return hashlib.sha256(f"admin-env:{email}:{password}:{secret}".encode()).hexdigest()


def _name_from_email(email: str) -> str:
    return email.split("@", 1)[0].replace(".", " ").replace("_", " ").title()[:120]


def admin_dict(a: AdminAccount) -> dict:
    return {"id": a.id, "email": a.email, "name": a.name, "active": a.active,
            "from_env": a.env_fingerprint is not None, "created_by": a.created_by,
            "created_at": a.created_at.isoformat() if a.created_at else None,
            "last_login_at": a.last_login_at.isoformat() if a.last_login_at else None}


def active_admins_exist(db: Session) -> bool:
    return db.scalars(select(AdminAccount.id).where(AdminAccount.active.is_(True)).limit(1)).first() is not None


# ------------------------------------------------------------------ env seeding
def parse_env(raw: str | None) -> list[tuple[str, str]]:
    out = []
    for part in (raw or "").replace("\r", "").replace("\n", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError("TRIYANA_ADMINS entries must look like email:password")
        email, password = part.split(":", 1)
        out.append((normalize_email(email), password.strip()))
    return out


def seed_from_env(db: Session, raw: str | None = None) -> list[str]:
    """Create or update the admins listed in TRIYANA_ADMINS. Returns the emails touched."""
    raw = os.environ.get("TRIYANA_ADMINS") if raw is None else raw
    try:
        entries = parse_env(raw)
    except Exception as e:  # never stop the app from starting over a typo; log it instead
        print(f"[triyana] TRIYANA_ADMINS ignored: {getattr(e, 'message', e)}")
        return []
    touched = []
    for email, password in entries:
        fp = _fingerprint(email, password)
        a = db.scalars(select(AdminAccount).where(AdminAccount.email == email)).first()
        if a is None:
            db.add(AdminAccount(email=email, name=_name_from_email(email), password_hash=hash_password(password),
                                env_fingerprint=fp, created_by="TRIYANA_ADMINS"))
            touched.append(email)
        elif a.env_fingerprint != fp:
            # The password in the env var changed (or the account now comes from it): apply it.
            a.password_hash, a.env_fingerprint, a.active = hash_password(password), fp, True
            _revoke_sessions(db, a)
            touched.append(email)
    db.commit()
    return touched


# ------------------------------------------------------------------ sessions
def login(db: Session, email: str, password: str) -> tuple[AdminAccount, str]:
    email = (email or "").strip().lower()
    key = f"admin:{email}"
    _check_rate(key)
    a = db.scalars(select(AdminAccount).where(AdminAccount.email == email)).first()
    if a is None or not a.active:
        check_password(password, _DUMMY_HASH)  # same work either way, so timing doesn't reveal admins
        _fail(key)
        raise Forbidden("bad_credentials", "Wrong email or password.")
    if not check_password(password, a.password_hash):
        _fail(key)
        raise Forbidden("bad_credentials", "Wrong email or password.")
    token = SESSION_PREFIX + secrets.token_urlsafe(32)
    now = utcnow()
    db.add(AdminSession(admin_id=a.id, token_hash=_hash_token(token), created_at=now,
                        expires_at=now + timedelta(hours=SESSION_HOURS)))
    a.last_login_at = now
    audit.record(db, None, "admin.login", "admin", a.id, admin=a.email)
    db.commit()
    return a, token


def admin_for_token(db: Session, token: str | None) -> AdminAccount | None:
    if not token or not token.startswith(SESSION_PREFIX):
        return None
    s = db.scalars(select(AdminSession).where(AdminSession.token_hash == _hash_token(token))).first()
    if not s or s.revoked or s.expires_at < utcnow():
        return None
    a = db.get(AdminAccount, s.admin_id)
    return a if a and a.active else None


def logout(db: Session, token: str) -> None:
    s = db.scalars(select(AdminSession).where(AdminSession.token_hash == _hash_token(token))).first()
    if s:
        s.revoked = True
        db.commit()


def _revoke_sessions(db: Session, a: AdminAccount) -> None:
    for s in db.scalars(select(AdminSession).where(AdminSession.admin_id == a.id, AdminSession.revoked.is_(False))):
        s.revoked = True


# ------------------------------------------------------------------ managing admins
def list_admins(db: Session) -> list[dict]:
    rows = db.scalars(select(AdminAccount).order_by(AdminAccount.active.desc(), AdminAccount.id)).all()
    return [admin_dict(a) for a in rows]


def add_admin(db: Session, name: str, email: str, password: str, by: str) -> dict:
    email = normalize_email(email)
    name = (name or "").strip() or _name_from_email(email)
    validate_password(password)
    a = db.scalars(select(AdminAccount).where(AdminAccount.email == email)).first()
    if a is not None and a.active:
        raise Conflict("admin_exists", "That email is already an admin.")
    if a is None:
        a = AdminAccount(email=email, name=name[:120], password_hash=hash_password(password), created_by=by)
        db.add(a)
    else:  # re-adding someone who was removed
        a.name, a.password_hash, a.active, a.created_by = name[:120], hash_password(password), True, by
    db.flush()
    audit.record(db, None, "admin.added", "admin", a.id, admin=email, by=by)
    db.commit()
    return admin_dict(a)


def remove_admin(db: Session, admin_id: int, me: AdminAccount) -> dict:
    a = db.get(AdminAccount, admin_id)
    if a is None or not a.active:
        raise NotFound("not_found", "Admin not found.")
    if a.id == me.id:
        raise Conflict("cannot_remove_self", "You can't remove yourself. Ask another admin to do it.")
    count = db.scalar(select(func.count(AdminAccount.id)).where(AdminAccount.active.is_(True)))
    if count <= 1:
        raise Conflict("last_admin", "There must always be at least one admin.")
    a.active = False
    _revoke_sessions(db, a)
    audit.record(db, None, "admin.removed", "admin", a.id, admin=a.email, by=me.email)
    db.commit()
    return admin_dict(a)


def change_password(db: Session, me: AdminAccount, current: str, new: str, keep_token: str | None) -> None:
    if not check_password(current, me.password_hash):
        raise Forbidden("bad_credentials", "Your current password is not right.")
    validate_password(new)
    me.password_hash = hash_password(new)
    for s in db.scalars(select(AdminSession).where(AdminSession.admin_id == me.id, AdminSession.revoked.is_(False))):
        if keep_token is None or s.token_hash != _hash_token(keep_token):
            s.revoked = True  # sign out every other browser
    audit.record(db, None, "admin.password_changed", "admin", me.id, admin=me.email)
    db.commit()

