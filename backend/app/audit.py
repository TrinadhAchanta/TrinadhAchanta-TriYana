"""Hash-chained audit logging for every prescription, cart, order and payment event."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import AuditLog, User, utcnow
from .security import canonical_hash

GENESIS = "0" * 64


def record(db: Session, actor: User | None, action: str, entity: str, entity_id: int | None, **details) -> AuditLog:
    last = db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(1)).first()
    prev_hash = last.hash if last else GENESIS
    created_at = utcnow()
    payload = {
        "prev": prev_hash,
        "at": created_at.isoformat(),
        "actor": actor.id if actor else None,
        "action": action,
        "entity": entity,
        "entity_id": entity_id,
        "details": details,
    }
    entry = AuditLog(
        created_at=created_at,
        actor_user_id=actor.id if actor else None,
        actor_role=actor.role.value if actor else "system",
        action=action,
        entity=entity,
        entity_id=entity_id,
        details=details,
        prev_hash=prev_hash,
        hash=canonical_hash(payload),
    )
    db.add(entry)
    db.flush()
    return entry


def verify_chain(db: Session) -> bool:
    prev = GENESIS
    for e in db.scalars(select(AuditLog).order_by(AuditLog.id)):
        payload = {
            "prev": prev,
            "at": e.created_at.isoformat(),
            "actor": e.actor_user_id,
            "action": e.action,
            "entity": e.entity,
            "entity_id": e.entity_id,
            "details": e.details,
        }
        if e.prev_hash != prev or e.hash != canonical_hash(payload):
            return False
        prev = e.hash
    return True
