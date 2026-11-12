"""Online medicine shop endpoints (patient app)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..deps import require
from ..models import Role, User
from ..services import dispatch
from ..services import orders as order_svc
from ..services import privacy as privacy_svc
from ..services import shop as shop_svc

router = APIRouter()
patient = require(Role.patient)


class LineIn(BaseModel):
    medication_id: int
    packs: int = Field(ge=1, le=shop_svc.MAX_PACKS)


class BasketIn(BaseModel):
    items: list[LineIn] = Field(min_length=1, max_length=shop_svc.MAX_LINES)


class IntentIn(BasketIn):
    pharmacy_id: int
    delivery_option: str


class CheckoutIn(IntentIn):
    payment_method: str
    payment_token: str = Field(max_length=300)
    idempotency_key: str = Field(min_length=8, max_length=80)
    expected_total: float | None = None


def _items(body: BasketIn) -> list[dict]:
    return [i.model_dump() for i in body.items]


@router.get("/api/shop/products")
def products(q: str = Query("", max_length=60), category: str = Query("", max_length=40),
             user: User = Depends(patient), db: Session = Depends(get_db)):
    return shop_svc.catalog(db, user, q, category)


@router.post("/api/shop/quote")
def quote(body: BasketIn, user: User = Depends(patient), db: Session = Depends(get_db)):
    return shop_svc.quote(db, user, _items(body))


@router.post("/api/shop/payment-intent")
def payment_intent(body: IntentIn, user: User = Depends(patient), db: Session = Depends(get_db)):
    privacy_svc.require_care(db, user)
    return shop_svc.payment_intent(db, user, _items(body), body.pharmacy_id, body.delivery_option)


@router.post("/api/shop/checkout", status_code=201)
def checkout(body: CheckoutIn, user: User = Depends(patient), db: Session = Depends(get_db)):
    privacy_svc.require_care(db, user)
    order = shop_svc.checkout(db, user, items=_items(body), pharmacy_id=body.pharmacy_id,
                              delivery_option=body.delivery_option, payment_method=body.payment_method,
                              payment_token=body.payment_token, idempotency_key=body.idempotency_key,
                              expected_total=body.expected_total)
    return order_svc.serialize_order(db, order, user)


@router.get("/api/shop/orders")
def my_shop_orders(user: User = Depends(patient), db: Session = Depends(get_db)):
    dispatch.sweep(db)
    return [order_svc.serialize_order(db, o, user) for o in shop_svc.list_orders(db, user)]
