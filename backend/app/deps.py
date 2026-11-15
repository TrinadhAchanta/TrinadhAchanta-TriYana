"""Authentication and role-based authorization helpers."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from .config import PROVIDER_APP_NAME, ROLE_APPS
from .db import get_db
from .models import Role, User
from .services import accounts


PROVIDER_ROLES = (Role.doctor, Role.courier, Role.pharmacist, Role.phlebotomist, Role.physio)


def current_user(authorization: str | None = Header(default=None), x_triyana_app: str | None = Header(default=None),
                 db: Session = Depends(get_db)) -> User:
    """Demo bearer-token auth. Production: OIDC/OAuth2 with MFA for clinicians."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "Sign in required."})
    token = authorization.split(" ", 1)[1].strip()
    user = accounts.user_for_token(db, token)
    if not user:
        raise HTTPException(status_code=401, detail={"code": "unauthenticated", "message": "Invalid session."})
    # Two apps, two logins: patients use Triyana, providers use the provider app (config.PROVIDER_APP_NAME).
    if x_triyana_app == "provider" and user.role not in PROVIDER_ROLES:
        raise HTTPException(status_code=403, detail={"code": "wrong_app", "message": f"This is the {PROVIDER_APP_NAME} app for doctors, physiotherapists, couriers and pharmacists. Patients sign in to the Triyana app."})
    if x_triyana_app == "patient" and user.role in PROVIDER_ROLES:
        raise HTTPException(status_code=403, detail={"code": "wrong_app", "message": f"Providers sign in to the {PROVIDER_APP_NAME} app."})
    if x_triyana_app in ROLE_APPS and user.role.value not in ROLE_APPS[x_triyana_app]["roles"]:
        raise HTTPException(status_code=403, detail={"code": "wrong_app", "message": accounts.wrong_role_app_message(x_triyana_app)})
    return user


def require(*roles: Role):
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail={"code": "forbidden_role", "message": "Your role cannot perform this action."})
        return user

    return checker
