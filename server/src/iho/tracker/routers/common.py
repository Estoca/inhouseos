import unicodedata
from datetime import date, datetime, timezone

from fastapi import HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from iho.tracker.auth import get_or_create_person
from iho.tracker.config import settings
from iho.tracker.models import Action, Decision, Event, Person, Project, ProjectUpdate
from iho.tracker.schemas import ActionOut, DecisionOut, NoteOut, PersonOut, ProjectOut, ProjectUpdateOut, UpdateStatusOut
from iho.tracker.workdays import SP

NOTES_PER_ACTION = 3


def resolve_person(db: Session, email: str | None, fallback: Person) -> Person:
    return get_or_create_person(db, email) if email else fallback


def resolve_project(db: Session, slug: str | None) -> Project | None:
    if not slug:
        return None
    project = db.query(Project).filter(Project.slug == slug).one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"projeto {slug!r} nao existe")
    return project


def sent_fields(body: BaseModel, required: tuple[str, ...] = ()) -> dict:
    """Campos que vieram no PATCH (inclusive null explicito). Campo obrigatorio nao aceita null."""
    data = {k: getattr(body, k) for k in body.model_fields_set}
    for k in required:
        if k in data and data[k] is None:
            raise HTTPException(422, f"{k} nao pode ser null")
    return data


def change(changes: dict, field: str, old, new) -> bool:
    """Anota {campo: {from, to}} para o evento `updated`. Devolve se mudou."""
    if old == new:
        return False
    changes[field] = {"from": old.isoformat() if isinstance(old, date) else old,
                      "to": new.isoformat() if isinstance(new, date) else new}
    return True


def fold(text: str) -> str:
    """Caixa e acento nao importam: 'Migração' casa com 'migracao'. Espaco repetido vira um."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    bare = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join(bare.casefold().split())


def check_expect(expected: str | None, actual: str, *, kind: str, entity_id: int, field: str) -> None:
    """Barreira contra id errado (WMS-284): quem chama diz um trecho do que acha que esta
    fechando; se o item daquele id nao contem o trecho, nada e gravado e a mensagem mostra
    o texto real, para a LLM reler em vez de repetir. Sem expected, nao checa (compativel)."""
    if expected is None:
        return
    if not fold(expected):
        raise HTTPException(422, f"expect_{field}_contains vazio")
    if fold(expected) not in fold(actual):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{kind} {entity_id} nao e o item esperado: {field} real e {actual!r}, "
            f"nao contem {expected!r}. Nada foi gravado; confira o id.",
        )


def action_url(action_id: int) -> str:
    """Link permanente da acao na interface (OL-NNNN): {PUBLIC_BASE_URL}/ol/{id}.
    /a/{id} (0.7.0) redireciona com 301 para ca."""
    return f"{settings.public_base_url.rstrip('/')}/ol/{action_id}"


def decision_url(decision_id: int) -> str:
    """Link permanente da decisao na interface (D-NNNN): {PUBLIC_BASE_URL}/d/{id}."""
    return f"{settings.public_base_url.rstrip('/')}/d/{decision_id}"


def registered_on(action: Action) -> date:
    """Dia (America/Sao_Paulo) em que a acao entrou no tracker."""
    created = action.created_at or datetime.now(timezone.utc)
    if created.tzinfo is None:  # SQLite devolve sem fuso; gravamos em UTC
        created = created.replace(tzinfo=timezone.utc)
    return created.astimezone(SP).date()


def overdue_by(action: Action, as_of: date) -> int:
    """Dias alem do combinado. Sem prazo: SLA da sev desde o ultimo bump ou desde o registro no
    tracker, o que for mais recente (0.10.0): pedido antigo registrado hoje nao nasce vencido, porque
    ate hoje ninguem tinha como cobrar pelo tracker; a idade (age_days) continua contando do pedido.
    Com prazo (due_at): ate o prazo nao vence (negativo = dias que faltam); passou, vence no dia
    seguinte; quem cobra depois do prazo (bump real, depois da abertura e do prazo) reinicia a
    contagem pelo SLA da sev."""
    if action.status != "open" or action.waiting_external:
        return 0  # espera de terceiro nao tem SLA: nao ha ninguem da Estoca a cobrar
    sla = settings.sla.get(action.sev, 7)
    if action.due_at:
        if action.last_bump_at > action.due_at and action.last_bump_at > action.asked_at:
            return (as_of - action.last_bump_at).days - sla
        return (as_of - action.due_at).days
    return (as_of - max(action.last_bump_at, registered_on(action))).days - sla


def _note_out(e: Event) -> NoteOut:
    p = e.payload if isinstance(e.payload, dict) else {}
    text = p.get("text") or p.get("entregue") or p.get("note")
    evidence = p.get("evidence") or p.get("evidencia")
    return NoteOut(at=e.at, by=e.actor.email if e.actor else None,
                   text=str(text) if text is not None else None,
                   evidence=str(evidence) if evidence is not None else None, payload=p)


def notes_by_action(db: Session, ids: list[int]) -> dict[int, list[NoteOut]]:
    """Ultimas NOTES_PER_ACTION notas de cada acao, numa consulta so. Quem chama ja filtrou
    as acoes pela visibilidade: ver a acao e ver as notas dela, como o historico."""
    if not ids:
        return {}
    rows = (db.query(Event).options(joinedload(Event.actor))
            .filter(Event.entity_type == "action", Event.kind == "note", Event.entity_id.in_(ids))
            .order_by(Event.at.desc(), Event.id.desc()).all())
    out: dict[int, list[NoteOut]] = {}
    for e in rows:
        lst = out.setdefault(e.entity_id, [])
        if len(lst) < NOTES_PER_ACTION:
            lst.append(_note_out(e))
    return out


def actions_out(db: Session, rows: list[Action], as_of: date) -> list[ActionOut]:
    notes = notes_by_action(db, [a.id for a in rows])
    return [action_out(a, as_of, notes.get(a.id)) for a in rows]


def action_out(a: Action, as_of: date, notes: list[NoteOut] | None = None) -> ActionOut:
    return ActionOut(
        id=a.id,
        url=action_url(a.id),
        type=a.type,
        project=a.project.slug if a.project else None,
        requester=PersonOut.model_validate(a.requester),
        waiting_on=PersonOut.model_validate(a.waiting_on),
        title=a.title,
        source=a.source,
        source_ref=a.source_ref,
        asked_at=a.asked_at,
        last_bump_at=a.last_bump_at,
        sev=a.sev,
        status=a.status,
        closed_at=a.closed_at,
        closed_evidence=a.closed_evidence,
        age_days=(as_of - a.asked_at).days,
        overdue_by=overdue_by(a, as_of),
        waiting_external=a.waiting_external,
        review_at=a.review_at,
        review_due=bool(a.waiting_external and a.review_at and a.review_at <= as_of),
        due_at=a.due_at,
        days_to_due=(a.due_at - as_of).days if a.due_at else None,
        notes=notes or [],
        registered_on=registered_on(a),
        duplicate_of=a.duplicate_of_id,
    )


def decision_out(d: Decision, as_of: date) -> DecisionOut:
    return DecisionOut(
        id=d.id,
        url=decision_url(d.id),
        project=d.project.slug if d.project else None,
        question=d.question,
        decider=PersonOut.model_validate(d.decider),
        requester=PersonOut.model_validate(d.requester),
        opened_at=d.opened_at,
        deadline=d.deadline,
        priority=d.priority,
        status=d.status,
        decided_at=d.decided_at,
        outcome=d.outcome,
        visibility=d.visibility,
        days_to_deadline=(d.deadline - as_of).days if d.deadline else None,
    )


def project_out(p: Project, update_status: UpdateStatusOut | None = None) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        slug=p.slug,
        name=p.name,
        owner=PersonOut.model_validate(p.owner) if p.owner else None,
        priority=p.priority,
        status=p.status,
        members=[PersonOut.model_validate(m.person) for m in p.members],
        updated_at=p.updated_at,
        kickoff_ref=p.kickoff_ref,
        objective=p.objective,
        goals=p.goals,
        expected_results=p.expected_results,
        area=p.area,
        radar_plan_ids=p.radar_plan_ids,
        started_at=p.started_at,
        target_end_at=p.target_end_at,
        update_frequency=p.update_frequency,
        update_weekday=p.update_weekday,
        update_time=p.update_time,
        update_status=update_status,
    )


def project_update_out(u: ProjectUpdate) -> ProjectUpdateOut:
    return ProjectUpdateOut(
        id=u.id,
        project=u.project.slug,
        author=PersonOut.model_validate(u.author),
        posted_at=u.posted_at,
        farol=u.farol,
        summary=u.summary,
        help_needed=u.help_needed,
        next_focus=u.next_focus,
        target_end_at=u.target_end_at,
        source=u.source,
        source_ref=u.source_ref,
    )