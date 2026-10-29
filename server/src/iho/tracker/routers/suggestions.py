"""Sugestoes da LLM e eficacia. Ver DESIGN.md, secao Eficacia."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from iho.tracker.auth import Identity, current_identity, get_or_create_person
from iho.tracker.db import get_db
from iho.tracker.events import record
from iho.tracker.models import Action, Decision, Event, Person, Suggestion, utcnow
from iho.tracker.routers.common import resolve_project
from iho.tracker.schemas import MetricsBucket, MetricsOut, PersonOut, SuggestionIn, SuggestionOut, SuggestionOutcome
from iho.tracker.visibility import _report_ids
from iho.tracker.workdays import SP, business_days

EXPIRE_BUSINESS_DAYS = 2  # sem desfecho depois de 2 dias uteis inteiros: vira ignored

# Desfecho inferido (0.15.0): evento da propria pessoa na entidade da sugestao, dentro da janela.
# O kind da sugestao diz qual evento e "seguir"; qualquer outro evento dela ali e "fez diferente".
FOLLOW_EVENTS = {
    "nudge": {"bumped", "nudged"},
    "close": {"closed"},
    "confirm_assignment": {"closed", "updated"},
    "external_review": {"updated"},
    "decide": {"decided", "dropped"},
}
ENTITY_EVENTS = {
    "action": {"bumped", "nudged", "closed", "updated", "reopened", "note"},
    "decision": {"decided", "dropped", "updated", "reopened", "note"},
}

router = APIRouter()


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite devolve datetime sem fuso; Postgres devolve com. Normaliza para UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _out(s: Suggestion) -> SuggestionOut:
    return SuggestionOut(id=s.id, person=PersonOut.model_validate(s.person), kind=s.kind, entity_type=s.entity_type,
                         entity_id=s.entity_id, project=s.project.slug if s.project else None, text=s.text, rule=s.rule,
                         made_at=s.made_at, outcome=s.outcome, outcome_at=s.outcome_at, outcome_note=s.outcome_note)


def _is_inferred(s: Suggestion) -> bool:
    return s.outcome in ("followed", "deviated") and (s.outcome_note or "").startswith("inferido")


def _is_expired(s: Suggestion) -> bool:
    return s.outcome == "ignored" and (s.outcome_note or "").startswith("expirou")


def _in_window(made: date, day: date) -> bool:
    return len(business_days(made + timedelta(days=1), day)) <= EXPIRE_BUSINESS_DAYS


def _infer(db: Session, s: Suggestion, made: date) -> tuple[str, Event] | None:
    """Desfecho pelos eventos da propria pessoa na acao ou decisao da sugestao, dentro da janela.
    Em 12 a 19-10, 57% das sugestoes com desfecho eram `ignored` por expiracao: a pessoa cobrava
    ou fechava do jeito dela e ninguem registrava. Kind sem regra (other, pre_read...) nao infere."""
    follow = FOLLOW_EVENTS.get(s.kind)
    kinds = ENTITY_EVENTS.get(s.entity_type or "")
    if not follow or not kinds or not s.entity_id:
        return None
    made_at = _aware(s.made_at)
    evs = (db.query(Event)
           .filter(Event.entity_type == s.entity_type, Event.entity_id == s.entity_id,
                   Event.actor_id == s.person_id, Event.kind.in_(kinds))
           .order_by(Event.at, Event.id).all())
    evs = [e for e in evs if _aware(e.at) >= made_at and _in_window(made, _aware(e.at).astimezone(SP).date())]
    if not evs:
        return None
    hit = next((e for e in evs if e.kind in follow), None)
    return ("followed", hit) if hit else ("deviated", evs[0])


def expire_pending(db: Session, today: date | None = None) -> int:
    """Resolve as sugestoes pendentes. Primeiro tenta inferir o desfecho pelos eventos (`_infer`):
    vira `followed` ou `deviated` com nota "inferido". Sem evento e pendente ha EXPIRE_BUSINESS_DAYS
    dias uteis inteiros (sem contar o dia em que foi feita), vira `ignored` com nota "expirou". Em
    09-10, 37% das sugestoes estavam pendentes: sem desfecho a metrica nao existe. Roda quando
    alguem le (digest, lista, metricas); nada agendado. Devolve quantas expiraram."""
    today = today or datetime.now(SP).date()
    rows = db.query(Suggestion).filter(Suggestion.outcome == "pending").all()
    n = inferred = 0
    for s in rows:
        made = _aware(s.made_at).astimezone(SP).date()
        hit = _infer(db, s, made)
        if hit:
            outcome, ev = hit
            s.outcome = outcome
            s.outcome_at = utcnow()
            s.outcome_note = f"inferido: {ev.kind} em {_aware(ev.at).astimezone(SP).date().isoformat()}"
            record(db, actor_id=None, entity_type="suggestion", entity_id=s.id, kind=f"suggestion_{outcome}",
                   payload={"inferred": True, "event_id": ev.id, "event_kind": ev.kind})
            inferred += 1
            continue
        if len(business_days(made + timedelta(days=1), today)) < EXPIRE_BUSINESS_DAYS:
            continue
        s.outcome = "ignored"
        s.outcome_at = utcnow()
        s.outcome_note = f"expirou: sem desfecho em {EXPIRE_BUSINESS_DAYS} dias uteis"
        record(db, actor_id=None, entity_type="suggestion", entity_id=s.id, kind="suggestion_ignored",
               payload={"expired": True, "days_open": (today - made).days})
        n += 1
    if n or inferred:
        db.commit()
    return n


def _visible(db: Session, ident: Identity):
    q = db.query(Suggestion).options(joinedload(Suggestion.person), joinedload(Suggestion.project))
    if ident.sees_everything:
        return q
    people = [ident.person.id, *_report_ids(db, ident)]
    return q.filter(or_(Suggestion.person_id.in_(people), Suggestion.created_by_id == ident.person.id))


@router.get("/api/suggestions", response_model=list[SuggestionOut])
def list_suggestions(person: str | None = None, outcome: str | None = None, kind: str | None = None,
                     since: datetime | None = None, limit: int = Query(default=200, le=1000),
                     db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    expire_pending(db)
    q = _visible(db, ident)
    if person:
        q = q.filter(Suggestion.person.has(Person.email == person.lower()))
    if outcome:
        q = q.filter(Suggestion.outcome == outcome)
    if kind:
        q = q.filter(Suggestion.kind == kind)
    if since:
        q = q.filter(Suggestion.made_at >= since)
    return [_out(s) for s in q.order_by(Suggestion.made_at.desc()).limit(limit).all()]


@router.post("/api/suggestions", response_model=SuggestionOut, status_code=201)
def create_suggestion(body: SuggestionIn, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    person = get_or_create_person(db, body.person_email) if body.person_email else ident.person
    project = resolve_project(db, body.project)
    s = Suggestion(person=person, kind=body.kind, entity_type=body.entity_type, entity_id=body.entity_id, project=project,
                   text=body.text.strip(), rule=body.rule, created_by_id=ident.person.id)
    db.add(s)
    db.flush()
    record(db, actor_id=ident.person.id, entity_type="suggestion", entity_id=s.id, kind="suggested",
           payload={"to": person.email, "kind": s.kind, "rule": s.rule, "entity": [s.entity_type, s.entity_id]})
    db.commit()
    db.refresh(s)
    return _out(s)


@router.post("/api/suggestions/{sid}/outcome", response_model=SuggestionOut)
def set_outcome(sid: int, body: SuggestionOutcome, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    s = _visible(db, ident).filter(Suggestion.id == sid).one_or_none()
    if s is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "sugestao nao existe ou nao e visivel")
    if s.outcome != "pending" and not _is_inferred(s):  # o que a pessoa diz vale mais que o inferido
        raise HTTPException(status.HTTP_409_CONFLICT, f"desfecho ja registrado: {s.outcome}")
    s.outcome = body.outcome
    s.outcome_at = utcnow()
    s.outcome_note = body.note
    record(db, actor_id=ident.person.id, entity_type="suggestion", entity_id=s.id, kind=f"suggestion_{body.outcome}",
           payload={"days_open": (_aware(s.outcome_at) - _aware(s.made_at)).days, "note": body.note})
    db.commit()
    db.refresh(s)
    return _out(s)


def _resolution(db: Session, s: Suggestion) -> datetime | None:
    """Quando a entidade da sugestao foi resolvida, se foi."""
    if s.entity_type == "action" and s.entity_id:
        a = db.get(Action, s.entity_id)
        return a.closed_at if a and a.status == "done" else None
    if s.entity_type == "decision" and s.entity_id:
        d = db.get(Decision, s.entity_id)
        return d.decided_at if d and d.status == "decided" else None
    return None


def _bucket(db: Session, items: list[Suggestion]) -> MetricsBucket:
    c = defaultdict(int)
    days = {"followed": [], "deviated": []}
    resolved = {"followed": 0, "deviated": 0}
    for s in items:
        c[s.outcome] += 1
        c["expired"] += _is_expired(s)
        c["inferred"] += _is_inferred(s)
        if s.outcome in ("followed", "deviated"):
            r = _resolution(db, s)
            if r:
                resolved[s.outcome] += 1
                days[s.outcome].append(max((_aware(r) - _aware(s.made_at)).total_seconds() / 86400, 0))
    decided = c["followed"] + c["deviated"] + c["ignored"]
    avg = lambda xs: round(sum(xs) / len(xs), 1) if xs else None
    return MetricsBucket(total=len(items), followed=c["followed"], deviated=c["deviated"], ignored=c["ignored"],
                         pending=c["pending"], expired=c["expired"], inferred=c["inferred"],
                         adherence=round(c["followed"] / decided, 2) if decided else None,
                         resolved_when_followed=resolved["followed"], resolved_when_deviated=resolved["deviated"],
                         avg_days_to_resolve_followed=avg(days["followed"]), avg_days_to_resolve_deviated=avg(days["deviated"]))


def _reading(b: MetricsBucket) -> list[str]:
    out = []
    decided = b.followed + b.deviated + b.ignored
    if decided < 10:
        out.append(f"amostra pequena ({decided} sugestoes com desfecho); leitura indicativa")
    if b.adherence is not None:
        rf = b.resolved_when_followed / b.followed if b.followed else None
        rd = b.resolved_when_deviated / b.deviated if b.deviated else None
        if b.adherence < 0.5 and rd is not None and rf is not None and rd >= rf:
            out.append("adesao baixa e quem fez diferente resolveu tanto ou mais: a LLM esta sugerindo mal; revisar Compass e plugin")
        elif b.adherence < 0.5 and rd is not None and rf is not None and rd < rf:
            out.append("adesao baixa e quem seguiu resolveu mais: candidato a subir a regua de delegacao nesses tipos de acao")
        elif b.adherence >= 0.8 and rf is not None and rf >= 0.7:
            out.append("adesao alta e resultado bom: a LLM pode ganhar autonomia nesses tipos de acao")
    # Expirada nao e ignorada: ninguem disse o que aconteceu. So a ignorada de fato fala de hora ou canal.
    if b.expired and decided and b.expired / decided > 0.4:
        out.append("mais de 40% sem desfecho (expiraram sem evento nem resposta): a medida nao sabe o que aconteceu; "
                   "perguntar o desfecho no fechamento do dia")
    said_ignored = b.ignored - b.expired
    if said_ignored and decided and said_ignored / decided > 0.4:
        out.append("mais de 40% ignoradas de fato: sugestao esta chegando na hora ou no canal errado")
    return out


@router.get("/api/metrics", response_model=MetricsOut)
def metrics(person: str | None = None, project: str | None = None, since: datetime | None = None,
            db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    expire_pending(db)
    q = _visible(db, ident)
    if person:
        if person.lower() != ident.email and not ident.is_leadership and person.lower() not in ident.reports:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "metricas de outra pessoa so para lideranca")
        q = q.filter(Suggestion.person.has(Person.email == person.lower()))
    if project:
        q = q.filter(Suggestion.project.has(slug=project))
    if since:
        q = q.filter(Suggestion.made_at >= since)
    items = q.all()
    by_kind, by_person = defaultdict(list), defaultdict(list)
    for s in items:
        by_kind[s.kind].append(s)
        by_person[s.person.email].append(s)
    overall = _bucket(db, items)
    return MetricsOut(since=since, person=person, project=project, overall=overall,
                      by_kind={k: _bucket(db, v) for k, v in sorted(by_kind.items())},
                      by_person={k: _bucket(db, v) for k, v in sorted(by_person.items())} if ident.is_leadership else {},
                      reading=_reading(overall))
