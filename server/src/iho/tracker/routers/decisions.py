from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from iho.tracker.auth import Identity, current_identity, get_or_create_person
from iho.tracker.db import get_db
from iho.tracker.events import record
from iho.tracker.models import Decision, Person, utcnow
from iho.tracker.routers.events import history
from iho.tracker.routers.common import change, check_expect, decision_out, resolve_person, resolve_project, sent_fields
from iho.tracker.schemas import DecisionDecide, DecisionIn, DecisionOut, DecisionPatch, DecisionReopen, EventOut
from iho.tracker.visibility import decision_filter

router = APIRouter(prefix="/api/decisions")


def _base(db: Session, ident: Identity):
    q = db.query(Decision).options(joinedload(Decision.decider), joinedload(Decision.requester), joinedload(Decision.project))
    f = decision_filter(db, ident)
    return q.filter(f) if f is not None else q


@router.get("", response_model=list[DecisionOut])
def list_decisions(
    decider: str | None = None,
    requester: str | None = None,
    project: str | None = None,
    status_: str = Query(default="open", alias="status"),
    as_of: date | None = None,
    db: Session = Depends(get_db),
    ident: Identity = Depends(current_identity),
):
    as_of = as_of or date.today()
    q = _base(db, ident)
    if status_ != "all":
        q = q.filter(Decision.status == status_)
    if decider:
        q = q.filter(Decision.decider.has(Person.email == decider.lower()))
    if requester:
        q = q.filter(Decision.requester.has(Person.email == requester.lower()))
    if project:
        q = q.filter(Decision.project.has(slug=project))
    return [decision_out(d, as_of) for d in q.order_by(Decision.deadline.nulls_last(), Decision.opened_at).all()]


def _get(db: Session, ident: Identity, decision_id: int) -> Decision:
    d = _base(db, ident).filter(Decision.id == decision_id).one_or_none()
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decisao nao existe ou nao e visivel")
    return d


@router.get("/{decision_id}", response_model=DecisionOut)
def get_decision(decision_id: int, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    return decision_out(_get(db, ident, decision_id), date.today())


@router.get("/{decision_id}/events", response_model=list[EventOut])
def decision_events(decision_id: int, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    """Historico da decisao. Mesma visibilidade do GET da decisao: nao visivel da 404."""
    _get(db, ident, decision_id)
    return history(db, "decision", decision_id)


@router.post("", response_model=DecisionOut, status_code=201)
def create_decision(body: DecisionIn, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    d = Decision(
        project=resolve_project(db, body.project),
        question=body.question.strip(),
        decider=get_or_create_person(db, body.decider_email),
        requester=resolve_person(db, body.requester_email, ident.person),
        opened_at=body.opened_at or date.today(),
        deadline=body.deadline,
        priority=body.priority,
        visibility=body.visibility,
    )
    db.add(d)
    db.flush()
    record(db, actor_id=ident.person.id, entity_type="decision", entity_id=d.id, kind="created",
           payload={"decider": d.decider.email, "deadline": str(d.deadline) if d.deadline else None, "visibility": d.visibility})
    db.commit()
    return decision_out(d, date.today())


@router.patch("/{decision_id}", response_model=DecisionOut)
def update_decision(decision_id: int, body: DecisionPatch, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    """Edita no lugar (id preservado). Mesma regra de quem pode do decide."""
    d = _base(db, ident).filter(Decision.id == decision_id).one_or_none()
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decisao nao existe ou nao e visivel")
    if d.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "decisao ja resolvida nao se edita")
    if ident.person.id not in (d.decider_id, d.requester_id) and not ident.is_leadership:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "so quem decide, quem pediu ou lideranca")
    data = sent_fields(body, required=("decider_email", "requester_email", "priority", "question", "visibility"))
    changes: dict = {}
    if "decider_email" in data:
        p = get_or_create_person(db, data["decider_email"])
        if change(changes, "decider", d.decider.email, p.email):
            d.decider = p
    if "requester_email" in data:
        p = get_or_create_person(db, data["requester_email"])
        if change(changes, "requester", d.requester.email, p.email):
            d.requester = p
    if "question" in data:
        question = data["question"].strip()
        if not question:
            raise HTTPException(422, "question vazia")
        if change(changes, "question", d.question, question):
            d.question = question
    if "project" in data:
        project = resolve_project(db, data["project"])
        if change(changes, "project", d.project.slug if d.project else None, project.slug if project else None):
            d.project = project
    for k in ("deadline", "priority", "visibility"):
        if k in data and change(changes, k, getattr(d, k), data[k]):
            setattr(d, k, data[k])
    if changes:
        record(db, actor_id=ident.person.id, entity_type="decision", entity_id=d.id, kind="updated", payload={"changes": changes})
        db.commit()
    return decision_out(d, date.today())


def _can_resolve(d: Decision, ident: Identity) -> None:
    if ident.person.id not in (d.decider_id, d.requester_id) and not ident.is_leadership:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "so quem decide, quem pediu ou lideranca")


@router.post("/{decision_id}/decide", response_model=DecisionOut)
def decide(decision_id: int, body: DecisionDecide, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    d = _base(db, ident).filter(Decision.id == decision_id).one_or_none()
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decisao nao existe ou nao e visivel")
    # antes do status: "o id 6 e outra pergunta" ajuda mais que "ja resolvida"
    check_expect(body.expect_question_contains, d.question, kind="decisao", entity_id=d.id, field="question")
    if d.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "decisao ja resolvida")
    _can_resolve(d, ident)
    d.status = body.status
    d.decided_at = utcnow()
    d.outcome = body.outcome
    record(db, actor_id=ident.person.id, entity_type="decision", entity_id=d.id, kind=body.status,
           payload={"open_days": (date.today() - d.opened_at).days,
                    "late_days": (date.today() - d.deadline).days if d.deadline else None})
    db.commit()
    return decision_out(d, date.today())


@router.post("/{decision_id}/reopen", response_model=DecisionOut)
def reopen(decision_id: int, body: DecisionReopen, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    """Desfaz decide/drop (WMS-284): volta a pendente. O desfecho errado nao some: fica no
    evento `reopened` (previous_status, previous_outcome, previous_decided_at, reason), alem
    do `decided`/`dropped` original. Mesma regra de quem pode do decide."""
    d = _base(db, ident).filter(Decision.id == decision_id).one_or_none()
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "decisao nao existe ou nao e visivel")
    if d.status == "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "decisao ja esta pendente")
    _can_resolve(d, ident)
    payload = {"previous_status": d.status, "previous_outcome": d.outcome,
               "previous_decided_at": d.decided_at.isoformat() if d.decided_at else None,
               "reason": body.reason.strip()}
    d.status = "open"
    d.outcome = None
    d.decided_at = None
    record(db, actor_id=ident.person.id, entity_type="decision", entity_id=d.id, kind="reopened", payload=payload)
    db.commit()
    return decision_out(d, date.today())
