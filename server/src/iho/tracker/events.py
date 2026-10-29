from sqlalchemy.orm import Session

from iho.tracker.models import Event


def record(db: Session, *, actor_id: int | None, entity_type: str, entity_id: int | None, kind: str, payload: dict | None = None) -> Event:
    ev = Event(actor_id=actor_id, entity_type=entity_type, entity_id=entity_id, kind=kind, payload=payload)
    db.add(ev)
    db.flush()
    return ev
