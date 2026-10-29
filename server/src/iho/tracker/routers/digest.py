"""GET /api/digest: tudo que o /bomdia de uma pessoa precisa, numa chamada."""
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload

from iho.tracker import adoption as adoption_mod
from iho.tracker.auth import Identity, current_identity
from iho.tracker.db import get_db
from iho.tracker.models import Action, Decision, Event, Person, Project, utcnow
from iho.tracker.project_updates import latest_updates, status_for
from iho.tracker.radar import as_utc, moved_away
from iho.tracker.routers.common import actions_out, decision_out, overdue_by, project_update_out
from iho.tracker.routers import team as team_mod
from iho.tracker.routers.suggestions import expire_pending
from iho.tracker.schemas import DigestOut, PersonOut, ProjectUpdateDueOut

router = APIRouter()


def _window(as_of: date, since: datetime | None) -> tuple[datetime, datetime]:
    """Janela do moved_away. Fim: agora, se as_of e hoje; senao o fim do dia as_of (UTC).
    Inicio: `since` (o plugin passa o horario do ultimo bomdia, e cada item aparece uma vez);
    sem since, 24h antes do fim."""
    until = utcnow() if as_of >= date.today() else datetime.combine(as_of + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return (as_utc(since) if since else until - timedelta(hours=24)), until


@router.get("/api/digest", response_model=DigestOut)
def digest(person: str | None = None, as_of: date | None = None, since: datetime | None = None,
           db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    as_of = as_of or date.today()
    target = ident.person
    if person and person.lower() != ident.email:
        if not ident.is_leadership and person.lower() not in ident.reports:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "digest de outra pessoa so para lideranca")
        target = db.query(Person).filter(Person.email == person.lower()).one_or_none()
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "pessoa nao existe")

    opts = (joinedload(Action.requester), joinedload(Action.waiting_on), joinedload(Action.project))
    open_actions = db.query(Action).options(*opts).filter(Action.status == "open").filter(
        (Action.waiting_on_id == target.id) | (Action.requester_id == target.id)
    ).order_by(Action.sev, Action.asked_at).all()

    # espera de terceiro sai do SLA, dos vencidos e dos sinais de SLA: vai para secao propria,
    # com idade (desde asked_at) e review_at. Reavaliacao vencida primeiro.
    external = sorted((a for a in open_actions if a.waiting_external),
                      key=lambda a: (not (a.review_at and a.review_at <= as_of), a.review_at or date.max, a.asked_at))
    internal = [a for a in open_actions if not a.waiting_external]
    waiting_on_me = [a for a in internal if a.waiting_on_id == target.id and a.type == "loop"]
    i_wait = [a for a in internal if a.requester_id == target.id and a.waiting_on_id != target.id]
    commitments = [a for a in internal if a.waiting_on_id == target.id and a.type == "commitment"]

    dopts = (joinedload(Decision.decider), joinedload(Decision.requester), joinedload(Decision.project))
    decisions = db.query(Decision).options(*dopts).filter(Decision.status == "open").filter(
        (Decision.decider_id == target.id) | (Decision.requester_id == target.id)
    ).order_by(Decision.deadline.nulls_last()).all()
    i_own = [d for d in decisions if d.decider_id == target.id]
    stuck = [d for d in decisions if d.deadline and d.deadline < as_of]

    signals: list[str] = []
    old = [a for a in waiting_on_me if (as_of - a.asked_at).days > 30]
    if old:
        signals.append(f"{len(old)} pendencia(s) esperando por voce ha mais de 30 dias: provavelmente morreram ou viraram outra coisa")
    ignored = db.query(func.count(Event.id)).filter(
        Event.kind == "nudge_ignored", Event.at >= as_of - timedelta(days=14),
        Event.entity_type == "action",
        Event.entity_id.in_([a.id for a in waiting_on_me] or [-1]),
    ).scalar() or 0
    if ignored:
        signals.append(f"{ignored} cobranca(s) sem acao nos ultimos 14 dias")
    sev1 = [a for a in waiting_on_me if a.sev == 1 and overdue_by(a, as_of) > 0]
    if sev1:
        signals.append(f"{len(sev1)} item(ns) sev1 vencido(s): bloqueia producao ou deploy")
    review_due = [a for a in external if a.review_at and a.review_at <= as_of]
    if review_due:
        signals.append(f"{len(review_due)} espera(s) de terceiro com reavaliacao vencida: confirmar se segue esperando ou mudar o plano")
    late_due = [a for a in waiting_on_me + commitments if a.due_at and a.due_at < as_of]
    if late_due:
        signals.append(f"{len(late_due)} pendencia(s) sua(s) com prazo de entrega vencido")
    late_dec = [d for d in i_own if d.deadline and d.deadline < as_of]
    if late_dec:
        signals.append(f"{len(late_dec)} decisao(oes) sua(s) com prazo vencido")

    since_, until = _window(as_of, since)
    away = moved_away(db, ident, target, since_, until)

    # atribuidas a voce por outra pessoa na janela: quem deve confirma ou fecha como not_mine.
    # Em 08-10 a LLM de quem pediu registrou pendencias que a outra pessoa nao devia ("o Ian nao
    # deve respostas"); sem esta lista, so o dono descobria ao ser cobrado.
    def _in_window(dt: datetime | None) -> bool:
        return dt is not None and since_ <= as_utc(dt) <= until
    assigned = [a for a in open_actions if a.waiting_on_id == target.id and a.requester_id != target.id
                and a.created_by_id != target.id and _in_window(a.created_at)]
    bounced = db.query(Action).options(*opts).filter(
        Action.status == "not_mine",
        (Action.requester_id == target.id) | (Action.created_by_id == target.id),
    ).all()
    bounced = [a for a in bounced if _in_window(a.closed_at)]
    if bounced:
        signals.append(f"{len(bounced)} pendencia(s) que voce abriu voltaram: quem devia nao reconhece")
    expire_pending(db)

    # update de projeto (0.11.0): cobra-se o dono, nao os membros. Calculado na hora pela cadencia;
    # some quando o update entra. Atrasado primeiro, depois prioridade e prazo.
    owned = db.query(Project).filter(Project.owner_id == target.id, Project.status == "active",
                                     Project.update_frequency.isnot(None)).all()
    at = None if as_of >= date.today() else until
    latest = latest_updates(db, [p.id for p in owned], until=at)
    updates_due: list[ProjectUpdateDueOut] = []
    for p in owned:
        u = latest.get(p.id)
        st = status_for(p, u.posted_at if u else None, u.farol if u else None, at)
        if st.state in ("due", "late"):
            updates_due.append(ProjectUpdateDueOut(slug=p.slug, name=p.name, priority=p.priority,
                                                   update_frequency=p.update_frequency, status=st,
                                                   last_update=project_update_out(u) if u else None))
    updates_due.sort(key=lambda x: (x.status.state != "late", x.priority, x.status.due_at))
    late_updates = [x for x in updates_due if x.status.state == "late"]
    if late_updates:
        signals.append(f"{len(late_updates)} projeto(s) seu(s) com update atrasado: "
                       + ", ".join(x.slug for x in late_updates))

    # adocao do pacote do dia: a chamada da LLM da propria pessoa (MCP/service) conta como
    # "abriu o pacote hoje"; navegador (authentik/mock) e digest de outra pessoa nao contam
    if target.id == ident.person.id and ident.via in ("mcp", "service") and as_of >= adoption_mod.today_sp():
        adoption_mod.record_open(db, target.id)
        db.commit()
    adop = adoption_mod.compute(db, target, as_of)
    line = adoption_mod.summary_line(adop)
    if line:
        signals.append(line)

    return DigestOut(
        person=PersonOut.model_validate(target),
        as_of=as_of,
        overdue_waiting_on_me=actions_out(db, [a for a in waiting_on_me if overdue_by(a, as_of) > 0], as_of),
        overdue_i_am_waiting=actions_out(db, [a for a in i_wait if overdue_by(a, as_of) > 0], as_of),
        my_commitments=actions_out(db, commitments, as_of),
        waiting_external=actions_out(db, external, as_of),
        decisions_i_own=[decision_out(d, as_of) for d in i_own],
        decisions_stuck=[decision_out(d, as_of) for d in stuck],
        signals=signals,
        moved_away=away,
        moved_away_since=since_,
        adoption=adop,
        assigned_to_me=actions_out(db, assigned, as_of),
        bounced=actions_out(db, bounced, as_of),
        project_updates_due=updates_due,
        # so no digest da propria pessoa: o time de quem lidera (LAB-9)
        team_stuck=team_mod.summary(db, ident, as_of) if target.id == ident.person.id else None,
    )
