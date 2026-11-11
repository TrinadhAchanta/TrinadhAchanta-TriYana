"""Authentication and role-based authorization helpers."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Role, User


def current_user(authorization: str | None = Header(default=None), db: Session = Depends(get_db)) -> User:
    """Demo bearer-token auth. Production: OIDC/OAuth2 with MFA for clinicians."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "Sign in required."})
    token = authorization.split(" ", 1)[1].strip()
    user = db.scalars(select(User).where(User.token == token)).first()
    if not user:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "Invalid session."})
    return user


def require(*roles: Role):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail={"code": "forbidden_role", "message": "Your role cannot perform this action."})
        return user

    return checker
