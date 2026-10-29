"""GET /api/team/stuck: ha quanto tempo cada pendencia do time esta travada (0.16.0, LAB-9).

Para quem lidera ajudar a destravar, nao para cobrar. Por isso: pessoas em ordem alfabetica, nunca por
volume (nao e ranking); sem notas, fonte nem evidencia (o titulo basta, e item sensivel ja entra com
titulo neutro); espera de terceiro (`waiting_external`) a parte, fora do "travado".

Escopo: `arvore` (padrao, todo mundo abaixo do gestor) ou `direto` (quem responde a ele). Quem ve: o
proprio gestor, quem esta acima dele no organograma, C-level e admin; `all=true` (todo mundo) so
C-level e admin. O organograma vem do escritorio, em cache (app/org.py).
"""
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from iho.tracker import org
from iho.tracker.auth import Identity, current_identity
from iho.tracker.config import settings
from iho.tracker.db import get_db
from iho.tracker.models import Action, Person
from iho.tracker.routers.common import action_url, overdue_by
from iho.tracker.schemas import (OrgInfoOut, PersonOut, TeamBandsOut, TeamCountsOut, TeamItemOut, TeamMemberOut,
                         TeamPersonOut, TeamStuckOut, TeamSummaryOut)

router = APIRouter()
TOP = 5  # itens do bloco do digest


def band(age_days: int) -> str:
    return "ate_7" if age_days <= 7 else "de_8_a_30" if age_days <= 30 else "mais_30"


def overdue_reason(a: Action, ob: int) -> str | None:
    if ob <= 0:
        return None
    # mesma regra do overdue_by: com prazo, vence pelo prazo ate alguem cobrar depois dele
    if a.due_at and not (a.last_bump_at > a.due_at and a.last_bump_at > a.asked_at):
        return "due_at"
    return "sla"


def resolve_team(db: Session, ident: Identity, gestor: str | None, scope: str, all_: bool):
    """(gestor ou None, {membro: reporte direto do gestor por onde entra}, quem chama ve tudo)."""
    # com o organograma do escritorio em cache, ele manda; sem ele, os diretos do token completam
    token_reports = set() if org.sync_from_office(db, ident.token) else ident.reports
    see_all = ident.sees_everything or org.is_c_level(db, ident.email)
    kids = org.children(db)
    if all_:
        if not see_all:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "visao de todo mundo so para C-level")
        return None, {p.email: None for p in db.query(Person).filter(Person.active.is_(True))}, see_all
    g = (gestor or ident.email).strip().lower()
    mine = org.tree(db, ident.email, kids)
    for e in token_reports:
        mine.setdefault(e, e)
    if g != ident.email and not see_all and g not in mine:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "time de outro gestor so para quem esta acima dele no organograma")
    members = {e: e for e in org.direct(db, g, kids)} if scope == "direto" else org.tree(db, g, kids)
    if g == ident.email:
        for e in token_reports:
            members.setdefault(e, e)
    members.pop(g, None)
    if not members and g == ident.email and not see_all:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "visao do time so para quem lidera: o organograma nao mostra reportes seus")
    return g, members, see_all


def _counts() -> TeamCountsOut:
    return TeamCountsOut(bands=TeamBandsOut())


def _add(c: TeamCountsOut, item: TeamItemOut, role: str | None) -> None:
    if item.waiting_external:
        c.external += 1
        return
    c.open += 1
    if role == "owes":
        c.owes += 1
    elif role == "waits":
        c.waits += 1
    c.overdue += item.overdue
    c.self_notes += item.self_note
    setattr(c.bands, item.band, getattr(c.bands, item.band) + 1)


def page_url(gestor: str | None, ident: Identity, scope: str, all_: bool) -> str:
    q = {}
    if all_:
        q["all"] = "1"
    elif gestor and gestor != ident.email:
        q["gestor"] = gestor
    if scope == "direto" and not all_:
        q["scope"] = "direto"
    base = f"{settings.public_base_url.rstrip('/')}/team"
    return f"{base}?{urlencode(q)}" if q else base


def build(db: Session, ident: Identity, gestor: str | None = None, scope: str = "arvore", all_: bool = False,
          as_of: date | None = None, limit: int = 50) -> TeamStuckOut:
    as_of = as_of or date.today()
    g, members, see_all = resolve_team(db, ident, gestor, scope, all_)
    people = {p.email: p for p in db.query(Person).filter(Person.email.in_(list(members) or ["-"]))}
    members = {e: v for e, v in members.items() if e not in people or people[e].active}
    names = org.names(db, list(members) + [v for v in members.values() if v] + ([g] if g else []))

    def member(email: str) -> TeamMemberOut:
        p = people.get(email)
        return TeamMemberOut(email=email, name=(p.name if p else None) or names.get(email))

    ids = {people[e].id: e for e in members if e in people}
    opts = (joinedload(Action.requester), joinedload(Action.waiting_on), joinedload(Action.project))
    rows = db.query(Action).options(*opts).filter(Action.status == "open").filter(
        or_(Action.waiting_on_id.in_(list(ids) or [-1]), Action.requester_id.in_(list(ids) or [-1]))).all()

    involved = {p.email for a in rows for p in (a.requester, a.waiting_on)} - set(names)
    names.update(org.names(db, list(involved)))

    def pout(p: Person) -> PersonOut:
        # pessoa sem nome no tracker (entrou por e-mail): o organograma tem
        out = PersonOut.model_validate(p)
        return out if out.name else out.model_copy(update={"name": names.get(p.email)})

    per = {e: _counts() for e in members}
    totals = _counts()
    items: list[TeamItemOut] = []
    external: list[TeamItemOut] = []
    for a in rows:
        w_in, r_in = a.waiting_on_id in ids, a.requester_id in ids
        self_note = a.requester_id == a.waiting_on_id
        who = ids[a.waiting_on_id] if w_in else ids[a.requester_id]
        ob = overdue_by(a, as_of)
        age = (as_of - a.asked_at).days
        via = members.get(who)
        item = TeamItemOut(
            id=a.id, url=action_url(a.id), title=a.title, type=a.type, sev=a.sev,
            project=a.project.slug if a.project else None,
            side="deve" if w_in else "espera",
            member=pout(a.waiting_on if w_in else a.requester),
            via=member(via) if via else None,
            requester=pout(a.requester), waiting_on=pout(a.waiting_on),
            unblocker=pout(a.waiting_on), unblocker_in_team=w_in,
            both_in_team=w_in and r_in and not self_note, self_note=self_note,
            asked_at=a.asked_at, age_days=age, band=band(age),
            last_bump_at=a.last_bump_at, bumped=a.last_bump_at > a.asked_at,
            days_without_bump=(as_of - max(a.last_bump_at, a.asked_at)).days,
            overdue=ob > 0, overdue_by=ob, overdue_reason=overdue_reason(a, ob), due_at=a.due_at,
            waiting_external=a.waiting_external, review_at=a.review_at,
            review_due=bool(a.waiting_external and a.review_at and a.review_at <= as_of),
        )
        (external if a.waiting_external else items).append(item)
        _add(totals, item, None)
        if not a.waiting_external:
            totals.owes += w_in
            totals.waits += r_in and not self_note
        if w_in:
            _add(per[ids[a.waiting_on_id]], item, "owes")
        if r_in and not self_note:
            _add(per[ids[a.requester_id]], item, "waits")

    items.sort(key=lambda i: (not i.overdue, -i.age_days, i.sev, i.id))
    external.sort(key=lambda i: (not i.review_due, -i.age_days, i.id))

    def alpha(e: str) -> str:
        m = member(e)
        return (m.name or m.email).casefold()

    kids = org.children(db)
    leaders = set(kids) if see_all else ({ident.email} | {e for e in org.tree(db, ident.email, kids) if e in kids})
    return TeamStuckOut(
        gestor=member(g) if g else None,
        scope="todos" if all_ else scope,
        as_of=as_of,
        org=OrgInfoOut(**org.info(db)),
        members=len(members),
        totals=totals,
        items=items[:limit],
        items_total=len(items),
        external=external,
        people=[TeamPersonOut(person=member(e), direct=(members[e] == e) if g else False,
                              via=member(members[e]) if members[e] and members[e] != e else None, counts=per[e])
                for e in sorted(members, key=alpha)],
        gestores=sorted((member(e) for e in leaders if e != g), key=lambda m: (m.name or m.email).casefold()),
        can_see_all=see_all,
        url=page_url(g, ident, scope, all_),
    )


def summary(db: Session, ident: Identity, as_of: date) -> TeamSummaryOut | None:
    """Bloco do digest: a arvore de quem chama. Quem nao lidera nao recebe nada (nem erro)."""
    try:
        out = build(db, ident, as_of=as_of, limit=TOP)
    except HTTPException:
        return None
    if not out.members:
        return None
    return TeamSummaryOut(scope=out.scope, members=out.members, totals=out.totals, top=out.items,
                          items_total=out.items_total, org=out.org, url=out.url)


@router.get("/api/team/stuck", response_model=TeamStuckOut)
def team_stuck(gestor: str | None = None, scope: str = Query(default="arvore", pattern=r"^(direto|arvore)$"),
               all_: bool = Query(default=False, alias="all"), as_of: date | None = None,
               limit: int = Query(default=50, ge=1, le=1000),
               db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    return build(db, ident, gestor, scope, all_, as_of, limit)
