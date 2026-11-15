"""Push alerts: the app subscribes a phone/browser so new requests reach it while locked."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Header
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..deps import current_user
from ..models import User
from ..services import push
from ..services.accounts import PROVIDER_ROLES
from ..services.common import notify

router = APIRouter(prefix="/api/push", tags=["push"])


class Keys(BaseModel):
    p256dh: str = Field(max_length=200)
    auth: str = Field(max_length=64)


class SubscribeIn(BaseModel):
    endpoint: str = Field(max_length=1000)
    keys: Keys


class EndpointIn(BaseModel):
    endpoint: str = Field(max_length=1000)


@router.get("/key")
def key():
    return {"public_key": push.public_key()}


@router.post("/subscribe")
def subscribe(body: SubscribeIn, user: User = Depends(current_user), db: Session = Depends(get_db),
              x_triyana_app: str | None = Header(default=None)):
    # Alerts open the app the phone subscribed from: Heros, or the Pharmacy / Rider app.
    app: str = x_triyana_app if x_triyana_app in config.ROLE_APPS else (
        "provider" if user.role in PROVIDER_ROLES else "patient")
    return push.subscribe(db, user, body.endpoint, body.keys.p256dh, body.keys.auth, app)


@router.post("/unsubscribe")
def unsubscribe(body: EndpointIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    push.unsubscribe(db, user, body.endpoint)
    return {"ok": True}


@router.get("/status")
def status(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"devices": push.count(db, user.id)}


@router.post("/test")
def test(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Send a test alert to every device this person turned alerts on for."""
    provider = user.role in PROVIDER_ROLES
    notify(db, [user], "Alerts are on", "You'll get new requests here even when your phone is locked." if provider
           else "We'll tell you here when your doctor is on the way.", "push:test")
    db.commit()
    return {"devices": push.count(db, user.id)}
