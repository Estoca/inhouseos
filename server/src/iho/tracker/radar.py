"""O que saiu do radar de uma pessoa (WMS-283).

A visao de cada pessoa so traz acoes em que ela e requester ou waiting_on. Reatribuir
(PATCH, WMS-276) tira o item da visao sem rastro. Aqui se le o rastro que o PATCH ja
deixa: o evento `updated` com payload.changes = {requester|waiting_on: {from, to}}.

- moved_away: acoes abertas que, numa janela, deixaram de ter a pessoa como requester ou
  waiting_on. Vai no digest para informar, nunca como pendencia.
- formerly: acoes que em algum momento tiveram a pessoa como parte e nao tem mais.

Nos dois casos a lista passa pela visibilidade de quem chama (action_filter): ter sido
parte nao da acesso a um item que a pessoa hoje nao veria.
"""
from datetime import datetime, timezone

from sqlalchemy import String, cast
from sqlalchemy.orm import Session, joinedload

from iho.tracker.auth import Identity
from iho.tracker.models import Action, Event, Person
from iho.tracker.routers.common import action_url
from iho.tracker.schemas import MovedAwayOut, PersonOut
from iho.tracker.visibility import action_filter

ROLES = ("requester", "waiting_on")


def as_utc(dt: datetime) -> datetime:
    """SQLite devolve sem fuso, Postgres com (LEARNINGS). Sem fuso = UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _role_changes(ev: Event):
    changes = (ev.payload or {}).get("changes") or {}
    for role in ROLES:
        c = changes.get(role)
        if isinstance(c, dict):
            yield role, c.get("from"), c.get("to")


def _updated_events(db: Session, email: str):
    # pre-filtro barato no texto do payload; a checagem exata e feita em Python
    return (db.query(Event).options(joinedload(Event.actor))
            .filter(Event.entity_type == "action", Event.kind.in_(("created", "updated")))
            .filter(cast(Event.payload, String).like(f"%{email}%")))


def _visible_actions(db: Session, ident: Identity, ids: set[int]):
    q = db.query(Action).options(joinedload(Action.requester), joinedload(Action.waiting_on), joinedload(Action.project))
    f = action_filter(db, ident)
    if f is not None:
        q = q.filter(f)
    return q.filter(Action.id.in_(ids or {-1}))


def formerly_ids(db: Session, person: Person) -> set[int]:
    """Ids de acoes em que a pessoa foi requester ou waiting_on em algum momento
    (criacao ou qualquer PATCH), e que hoje nao a tem em nenhum dos dois papeis."""
    email = person.email
    ids: set[int] = set()
    for ev in _updated_events(db, email):
        if ev.kind == "created" and (ev.payload or {}).get("waiting_on") == email:
            ids.add(ev.entity_id)
        for _, old, new in _role_changes(ev):
            if email in (old, new):
                ids.add(ev.entity_id)
    if not ids:
        return ids
    still = db.query(Action.id).filter(Action.id.in_(ids)).filter(
        (Action.requester_id == person.id) | (Action.waiting_on_id == person.id))
    return ids - {i for (i,) in still}


def moved_away(db: Session, ident: Identity, person: Person, since: datetime, until: datetime) -> list[MovedAwayOut]:
    since, until = as_utc(since), as_utc(until)
    lost: dict[int, dict] = {}  # action_id -> {roles, event mais recente}
    evs = _updated_events(db, person.email).filter(Event.kind == "updated").order_by(Event.at, Event.id)
    for ev in evs:
        at = as_utc(ev.at)
        if not (since <= at <= until):
            continue
        roles = [role for role, old, _ in _role_changes(ev) if old == person.email]
        if roles:
            entry = lost.setdefault(ev.entity_id, {"roles": set()})
            entry["roles"].update(roles)
            entry["event"] = ev  # ordenado por data: fica o mais recente
    if not lost:
        return []
    rows = _visible_actions(db, ident, set(lost)).filter(Action.status == "open").filter(
        Action.requester_id != person.id, Action.waiting_on_id != person.id).all()
    out = []
    for a in rows:
        entry = lost[a.id]
        ev = entry["event"]
        out.append(MovedAwayOut(
            id=a.id,
            url=action_url(a.id),
            title=a.title,
            project=a.project.slug if a.project else None,
            lost_roles=[r for r in ROLES if r in entry["roles"]],
            requester=PersonOut.model_validate(a.requester),
            waiting_on=PersonOut.model_validate(a.waiting_on),
            changed_by=PersonOut.model_validate(ev.actor) if ev.actor else None,
            changed_at=as_utc(ev.at),
        ))
    return sorted(out, key=lambda m: m.changed_at, reverse=True)
