from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from iho.tracker.auth import Identity, current_identity
from iho.tracker.db import get_db
from iho.tracker.events import record
from iho.tracker.models import Event
from iho.tracker.schemas import EventIn, EventOut, PersonOut

router = APIRouter(prefix="/api/events")


def history(db: Session, entity_type: str, entity_id: int) -> list[EventOut]:
    """Historico de um item, do mais antigo ao mais novo. Quem chama ja checou que a pessoa
    ve o item (a mesma visibilidade do GET do item): ver o item e ver o historico dele."""
    q = db.query(Event).options(joinedload(Event.actor)).filter(
        Event.entity_type == entity_type, Event.entity_id == entity_id)
    return [_out(e) for e in q.order_by(Event.at, Event.id).all()]


def _out(e: Event) -> EventOut:
    return EventOut(id=e.id, at=e.at, actor=PersonOut.model_validate(e.actor) if e.actor else None,
                    entity_type=e.entity_type, entity_id=e.entity_id, kind=e.kind, payload=e.payload)


@router.get("", response_model=list[EventOut])
def list_events(
    entity_type: str | None = None,
    entity_id: int | None = None,
    kind: str | None = None,
    since: datetime | None = None,
    limit: int = Query(default=200, le=1000),
    db: Session = Depends(get_db),
    ident: Identity = Depends(current_identity),
):
    q = db.query(Event).options(joinedload(Event.actor))
    if not ident.sees_everything:
        # sem visao total, so os proprios eventos; a leitura por entidade passa pelos endpoints de acao/decisao
        q = q.filter(Event.actor_id == ident.person.id)
    if entity_type:
        q = q.filter(Event.entity_type == entity_type)
    if entity_id is not None:
        q = q.filter(Event.entity_id == entity_id)
    if kind:
        q = q.filter(Event.kind == kind)
    if since:
        q = q.filter(Event.at >= since)
    return [_out(e) for e in q.order_by(Event.at.desc()).limit(limit).all()]


@router.post("", response_model=EventOut, status_code=201)
def create_event(body: EventIn, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    """A LLM registra: cobrou (nudged), cobrou e nada aconteceu (nudge_ignored),
    processo nao seguido (process_deviation, payload.process_ref aponta para a Estoca brain),
    decisao mantida privada (decision_kept_private, sem conteudo). Tudo append-only."""
    if body.kind == "note" and body.entity_type == "action":
        if body.entity_id is None:
            raise HTTPException(422, "note em acao precisa de entity_id")
        from iho.tracker.routers.actions import _load  # import local: actions importa este modulo
        _load(db, body.entity_id, ident)  # 404 se a acao nao existe ou nao e visivel
    e = record(db, actor_id=ident.person.id, entity_type=body.entity_type, entity_id=body.entity_id, kind=body.kind, payload=body.payload)
    db.commit()
    db.refresh(e)
    return _out(e)
