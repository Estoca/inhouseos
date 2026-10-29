from datetime import date
from difflib import SequenceMatcher

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from iho.tracker.auth import Identity, current_identity, get_or_create_person
from iho.tracker.db import get_db
from iho.tracker.events import record
from iho.tracker.models import Action, Person, utcnow
from iho.tracker.radar import formerly_ids
from iho.tracker.routers.events import history
from iho.tracker.routers.common import action_out, actions_out, change, fold, notes_by_action, check_expect, overdue_by, resolve_person, resolve_project, sent_fields
from iho.tracker.schemas import ActionClose, ActionIn, ActionOut, ActionPatch, ActionReopen, EventOut
from iho.tracker.visibility import action_filter

router = APIRouter(prefix="/api/actions")


def _load(db: Session, action_id: int, ident: Identity) -> Action:
    q = db.query(Action).options(joinedload(Action.requester), joinedload(Action.waiting_on), joinedload(Action.project))
    f = action_filter(db, ident)
    if f is not None:
        q = q.filter(f)
    a = q.filter(Action.id == action_id).one_or_none()
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "acao nao existe ou nao e visivel para voce")
    return a


def _one(db: Session, a: Action, as_of: date) -> ActionOut:
    return action_out(a, as_of, notes_by_action(db, [a.id]).get(a.id))


def _external(v: str | None) -> str | None:
    v = (v or "").replace("\n", " ").strip()
    return v or None


def _check_review(waiting_external: str | None, review_at: date | None) -> None:
    if review_at and not waiting_external:
        raise HTTPException(422, "review_at so vale para espera de terceiro (waiting_external)")


DUPLICATE_RATIO = 0.8  # titulo parecido o bastante para perguntar antes de criar
DUPLICATE_SHOWN = 5


def similar_open(db: Session, waiting_on_id: int, title: str) -> list[Action]:
    """Pendencias abertas da mesma pessoa com titulo parecido (sem caixa nem acento). E o caso do
    rollout de 08-10: o mesmo pedido registrado pela LLM de duas pessoas (quem pediu e quem deve,
    ou dois colegas que pediram a mesma coisa), e cada um virou uma acao."""
    t = fold(title)
    rows = db.query(Action).options(joinedload(Action.requester)).filter(
        Action.status == "open", Action.waiting_on_id == waiting_on_id).all()
    scored = [(SequenceMatcher(None, t, fold(a.title)).ratio(), a) for a in rows]
    return [a for r, a in sorted(scored, key=lambda x: -x[0]) if r >= DUPLICATE_RATIO][:DUPLICATE_SHOWN]


def _duplicate_message(found: list[Action]) -> str:
    items = "; ".join(f"OL-{a.id:04d} \"{a.title}\" (pedida por {a.requester.email}, desde {a.asked_at.isoformat()})"
                      for a in found)
    return (f"possivel duplicata: ja existe pendencia aberta parecida para a mesma pessoa: {items}. Nada foi gravado. "
            "Se e o mesmo pedido, use a existente (tracker_record_event note, ou tracker_update_action). "
            "Se e outro pedido, chame de novo com allow_duplicate=true e um titulo que diferencie os dois.")


def _formerly_ids(db: Session, ident: Identity, who: str) -> set[int]:
    """`formerly=me` ou e-mail (WMS-283). De outra pessoa, so lideranca dela (reportes) ou visao
    total, como o digest. O resultado ainda passa pelo action_filter de quem chama."""
    email = ident.email if who.strip().lower() == "me" else who.strip().lower()
    if email != ident.email and not (ident.sees_everything or (ident.is_leadership and email in ident.reports)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "formerly de outra pessoa so para lideranca dela")
    person = db.query(Person).filter(Person.email == email).one_or_none()
    return formerly_ids(db, person) if person else set()


@router.get("", response_model=list[ActionOut])
def list_actions(
    waiting_on: str | None = None,
    requester: str | None = None,
    project: str | None = None,
    status_: str = Query(default="open", alias="status"),
    overdue: bool = False,
    as_of: date | None = None,
    formerly: str | None = Query(default=None, description="me ou e-mail: acoes que ja tiveram a pessoa como requester/waiting_on e nao tem mais"),
    db: Session = Depends(get_db),
    ident: Identity = Depends(current_identity),
):
    as_of = as_of or date.today()
    q = db.query(Action).options(joinedload(Action.requester), joinedload(Action.waiting_on), joinedload(Action.project))
    f = action_filter(db, ident)
    if f is not None:
        q = q.filter(f)
    if status_ != "all":
        q = q.filter(Action.status == status_)
    if waiting_on:
        q = q.join(Person, Action.waiting_on_id == Person.id).filter(Person.email == waiting_on.lower())
    if requester:
        q = q.filter(Action.requester.has(Person.email == requester.lower()))
    if project:
        q = q.filter(Action.project.has(slug=project))
    if formerly:
        q = q.filter(Action.id.in_(_formerly_ids(db, ident, formerly) or {-1}))
    rows = q.order_by(Action.sev, Action.asked_at).all()
    if overdue:
        rows = [a for a in rows if overdue_by(a, as_of) > 0]
    return actions_out(db, rows, as_of)


@router.post("", response_model=ActionOut, status_code=201)
def create_action(body: ActionIn, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    today = date.today()
    requester = resolve_person(db, body.requester_email, ident.person)
    waiting_on = get_or_create_person(db, body.waiting_on_email)
    project = resolve_project(db, body.project)
    external = _external(body.waiting_external)
    _check_review(external, body.review_at)
    title = body.title.replace("\n", " ").strip()
    if not body.allow_duplicate:
        found = similar_open(db, waiting_on.id, title)
        if found:
            raise HTTPException(status.HTTP_409_CONFLICT, _duplicate_message(found))
    a = Action(
        type=body.type,
        project=project,
        requester=requester,
        waiting_on=waiting_on,
        title=title,
        source=body.source,
        source_ref=body.source_ref,
        asked_at=body.asked_at or today,
        last_bump_at=body.asked_at or today,
        sev=body.sev,
        waiting_external=external,
        review_at=body.review_at,
        due_at=body.due_at,
        created_by_id=ident.person.id,
    )
    db.add(a)
    db.flush()
    payload = {"waiting_on": waiting_on.email, "sev": a.sev, "source": a.source}
    if body.allow_duplicate:
        payload["allow_duplicate"] = True
    if external:
        payload["waiting_external"] = external
    if a.due_at:
        payload["due_at"] = a.due_at.isoformat()
    record(db, actor_id=ident.person.id, entity_type="action", entity_id=a.id, kind="created", payload=payload)
    db.commit()
    return _one(db, _load(db, a.id, ident), today)


@router.get("/{action_id}", response_model=ActionOut)
def get_action(action_id: int, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    return _one(db, _load(db, action_id, ident), date.today())


@router.get("/{action_id}/events", response_model=list[EventOut])
def action_events(action_id: int, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    """Historico da acao (created, bumped, updated com antes/depois, closed, reopened, nudged...).
    Mesma visibilidade do GET da acao: nao visivel da 404."""
    _load(db, action_id, ident)
    return history(db, "action", action_id)


@router.patch("/{action_id}", response_model=ActionOut)
def update_action(action_id: int, body: ActionPatch, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    """Edita no lugar: o id nao muda, a numeracao das visoes locais continua valendo e o
    historico mostra `updated` com antes/depois em vez de fechado+novo."""
    a = _load(db, action_id, ident)
    if a.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "acao fechada nao se edita; reabra antes")
    if ident.person.id not in (a.requester_id, a.waiting_on_id, a.created_by_id) and not ident.is_leadership:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "so quem pediu, quem deve, quem criou ou lideranca")
    data = sent_fields(body, required=("waiting_on_email", "requester_email", "sev", "title"))
    changes: dict = {}
    if "waiting_on_email" in data:
        p = get_or_create_person(db, data["waiting_on_email"])
        if change(changes, "waiting_on", a.waiting_on.email, p.email):
            a.waiting_on = p
    if "requester_email" in data:
        p = get_or_create_person(db, data["requester_email"])
        if change(changes, "requester", a.requester.email, p.email):
            a.requester = p
    if "title" in data:
        title = data["title"].replace("\n", " ").strip()
        if not title:
            raise HTTPException(422, "title vazio")
        if change(changes, "title", a.title, title):
            a.title = title
    if "project" in data:
        project = resolve_project(db, data["project"])
        if change(changes, "project", a.project.slug if a.project else None, project.slug if project else None):
            a.project = project
    for k in ("sev", "source", "source_ref", "due_at"):
        if k in data and change(changes, k, getattr(a, k), data[k]):
            setattr(a, k, data[k])
    # espera de terceiro. Voltar para espera interna reinicia o relogio do SLA hoje: durante a
    # espera de fora nao havia ninguem da Estoca a cobrar, entao contar esse tempo como atraso
    # de quem acompanha seria mentira. Fica registrado no `updated` (last_bump_at from/to),
    # nao como bump, porque ninguem cobrou ninguem.
    external = _external(data["waiting_external"]) if "waiting_external" in data else a.waiting_external
    review_at = data["review_at"] if "review_at" in data else a.review_at
    if a.waiting_external and not external:
        if "review_at" not in data:
            review_at = None  # sem espera de fora nao ha o que reavaliar
        change(changes, "last_bump_at", a.last_bump_at, date.today())
        a.last_bump_at = date.today()
    _check_review(external, review_at)
    if change(changes, "waiting_external", a.waiting_external, external):
        a.waiting_external = external
    if change(changes, "review_at", a.review_at, review_at):
        a.review_at = review_at
    if changes:
        record(db, actor_id=ident.person.id, entity_type="action", entity_id=a.id, kind="updated", payload={"changes": changes})
        db.commit()
    # sem recarregar: quem reatribuiu para outra pessoa pode deixar de ver a acao
    return _one(db, a, date.today())


@router.post("/{action_id}/bump", response_model=ActionOut)
def bump(action_id: int, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    a = _load(db, action_id, ident)
    if a.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "acao nao esta aberta")
    a.last_bump_at = date.today()
    record(db, actor_id=ident.person.id, entity_type="action", entity_id=a.id, kind="bumped")
    db.commit()
    return _one(db, a, date.today())


@router.post("/{action_id}/close", response_model=ActionOut)
def close(action_id: int, body: ActionClose, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    a = _load(db, action_id, ident)
    # antes do status: "o id 6 e outra acao" ajuda mais que "ja fechada"
    check_expect(body.expect_title_contains, a.title, kind="acao", entity_id=a.id, field="title")
    if a.status != "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "acao ja fechada")
    payload = {"status": body.status, "evidence": body.evidence, "open_days": (date.today() - a.asked_at).days}
    if body.status == "duplicate":
        if not body.duplicate_of:
            raise HTTPException(422, "status duplicate pede duplicate_of: o id da acao que fica")
        if body.duplicate_of == a.id:
            raise HTTPException(422, "duplicate_of nao pode ser a propria acao")
        keep = _load(db, body.duplicate_of, ident)  # tem de existir e ser visivel para quem fecha
        a.duplicate_of_id = keep.id
        payload["duplicate_of"] = keep.id
    elif body.duplicate_of:
        raise HTTPException(422, "duplicate_of so vale com status duplicate")
    if body.status == "not_mine" and ident.person.id != a.waiting_on_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not_mine e a propria pessoa dizendo que nao reconhece a pendencia: "
                            "so quem deve (waiting_on) usa. Para corrigir quem deve, tracker_update_action")
    a.status = body.status
    a.closed_at = utcnow()
    a.closed_evidence = body.evidence
    record(db, actor_id=ident.person.id, entity_type="action", entity_id=a.id, kind="closed", payload=payload)
    db.commit()
    return _one(db, a, date.today())


@router.post("/{action_id}/reopen", response_model=ActionOut)
def reopen(action_id: int, body: ActionReopen | None = None, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    """Volta a aberta. Como na decisao, o fechamento anterior fica no evento `reopened`
    (previous_status, previous_evidence) com o motivo. Corpo opcional (compativel)."""
    a = _load(db, action_id, ident)
    if a.status == "open":
        raise HTTPException(status.HTTP_409_CONFLICT, "acao ja aberta")
    reason = (body.reason or "").strip() if body else ""
    payload = {"previous_status": a.status, "previous_evidence": a.closed_evidence, "reason": reason or None}
    if a.duplicate_of_id:
        payload["previous_duplicate_of"] = a.duplicate_of_id
    a.duplicate_of_id = None
    a.status = "open"
    a.closed_at = None
    a.closed_evidence = None
    a.last_bump_at = date.today()
    record(db, actor_id=ident.person.id, entity_type="action", entity_id=a.id, kind="reopened", payload=payload)
    db.commit()
    return _one(db, a, date.today())
