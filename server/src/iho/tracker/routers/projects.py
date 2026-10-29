from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session, joinedload

from iho.tracker.auth import Identity, current_identity, get_or_create_person
from iho.tracker.db import get_db
from iho.tracker.events import record
from iho.tracker.models import Project, ProjectMember, ProjectUpdate, utcnow
from iho.tracker.project_updates import DEFAULT_TIME, as_utc, latest_updates, status_for
from iho.tracker.routers.common import change, project_out, project_update_out, sent_fields
from iho.tracker.routers.events import history
from iho.tracker.schemas import (
    EventOut,
    ProjectIn,
    ProjectOut,
    ProjectPatch,
    ProjectReportItem,
    ProjectReportOut,
    ProjectUpdateIn,
    ProjectUpdateOut,
)

router = APIRouter(prefix="/api/projects")

CADENCE = ("update_frequency", "update_weekday", "update_time")
KICKOFF = ("kickoff_ref", "objective", "goals", "expected_results", "area", "radar_plan_ids", "started_at", "target_end_at")
STATE_ORDER = {"late": 0, "due": 1, "pending": 2, "ok": 3, "off": 4}


def _get(db: Session, slug: str) -> Project:
    project = db.query(Project).filter(Project.slug == slug).one_or_none()
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "projeto nao existe")
    return project


def _check_cadence(p: Project) -> None:
    if p.update_frequency and not p.update_weekday:
        raise HTTPException(422, "update_frequency exige update_weekday (seg..dom)")


def with_status(db: Session, rows: list[Project], now: datetime | None = None) -> list[ProjectOut]:
    latest = latest_updates(db, [p.id for p in rows], until=now)
    out = []
    for p in rows:
        u = latest.get(p.id)
        out.append(project_out(p, status_for(p, u.posted_at if u else None, u.farol if u else None, now)))
    return out


@router.get("", response_model=list[ProjectOut])
def list_projects(status_: str | None = None, db: Session = Depends(get_db), _: Identity = Depends(current_identity)):
    q = db.query(Project)
    if status_:
        q = q.filter(Project.status == status_)
    return with_status(db, q.order_by(Project.priority, Project.slug).all())


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    if db.query(Project).filter(Project.slug == body.slug).one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "slug ja existe")
    if body.priority != 2 and not ident.can_set_priority:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "prioridade de projeto so C-level ou admin define")
    owner = get_or_create_person(db, body.owner_email) if body.owner_email else ident.person
    project = Project(slug=body.slug, name=body.name, owner=owner, priority=body.priority, status=body.status,
                      kickoff_ref=body.kickoff_ref, objective=body.objective, goals=body.goals,
                      expected_results=body.expected_results, area=body.area, radar_plan_ids=body.radar_plan_ids,
                      started_at=body.started_at, target_end_at=body.target_end_at,
                      update_frequency=body.update_frequency,
                      update_weekday=body.update_weekday if body.update_frequency else None,
                      update_time=(body.update_time or DEFAULT_TIME) if body.update_frequency else None,
                      update_since=utcnow() if body.update_frequency else None)
    _check_cadence(project)
    db.add(project)
    db.flush()
    for email in {owner.email, *[e.lower() for e in body.members]}:
        db.add(ProjectMember(project_id=project.id, person_id=get_or_create_person(db, email).id))
    record(db, actor_id=ident.person.id, entity_type="project", entity_id=project.id, kind="created",
           payload={"slug": project.slug, "update_frequency": project.update_frequency,
                    "update_weekday": project.update_weekday, "update_time": project.update_time})
    db.commit()
    db.refresh(project)
    return with_status(db, [project])[0]


@router.patch("/{slug}", response_model=ProjectOut)
def patch_project(slug: str, body: ProjectPatch, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    project = _get(db, slug)
    is_owner = project.owner_id == ident.person.id
    if not (is_owner or ident.is_admin or ident.is_leadership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "so dono, lideranca ou admin")
    sent = sent_fields(body)
    # cadencia e kickoff aceitam null explicito (update_frequency null = deixa de cobrar update)
    nullable = {k: sent.pop(k) for k in (*CADENCE, *KICKOFF) if k in sent}
    data = {k: v for k, v in sent.items() if v is not None}
    if "priority" in data:
        if not ident.can_set_priority:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "prioridade de projeto so C-level ou admin define")
        if data["priority"] != project.priority:
            record(db, actor_id=ident.person.id, entity_type="project", entity_id=project.id, kind="priority_changed",
                   payload={"from": project.priority, "to": data["priority"]})
    if "owner_email" in data:
        project.owner = get_or_create_person(db, data.pop("owner_email"))
    for k, v in data.items():
        setattr(project, k, v)
    for k in KICKOFF:
        if k in nullable:
            setattr(project, k, nullable[k])
    cadence_changes: dict = {}
    if any(k in nullable for k in CADENCE):
        freq = nullable.get("update_frequency", project.update_frequency)
        wd = nullable.get("update_weekday", project.update_weekday) if freq else None
        hhmm = (nullable.get("update_time") or project.update_time or DEFAULT_TIME) if freq else None
        for k, v in (("update_frequency", freq), ("update_weekday", wd), ("update_time", hhmm)):
            if change(cadence_changes, k, getattr(project, k), v):
                setattr(project, k, v)
        _check_cadence(project)
        if cadence_changes:
            # cadencia nova vale daqui para frente: ciclo anterior a ela nao vira atraso
            project.update_since = utcnow() if freq else None
            record(db, actor_id=ident.person.id, entity_type="project", entity_id=project.id, kind="cadence_changed",
                   payload={"changes": cadence_changes})
    db.commit()
    db.refresh(project)
    return with_status(db, [project])[0]


@router.post("/{slug}/members/{email}", response_model=ProjectOut, status_code=201)
def add_member(slug: str, email: str, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    project = _get(db, slug)
    person = get_or_create_person(db, email)
    if not any(m.person_id == person.id for m in project.members):
        db.add(ProjectMember(project_id=project.id, person_id=person.id))
        record(db, actor_id=ident.person.id, entity_type="project", entity_id=project.id, kind="member_added", payload={"email": person.email})
        db.commit()
        db.refresh(project)
    return project_out(project)


@router.delete("/{slug}/members/{email}", response_model=ProjectOut)
def remove_member(slug: str, email: str, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    project = _get(db, slug)
    email = email.strip().lower()
    is_self = email == ident.email
    if not (is_self or project.owner_id == ident.person.id or ident.is_admin or ident.is_leadership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "so a propria pessoa, o dono, lideranca ou admin")
    if project.owner is not None and project.owner.email == email:
        raise HTTPException(status.HTTP_409_CONFLICT, "o dono nao sai do projeto: troque o dono antes")
    member = next((m for m in project.members if m.person and m.person.email == email), None)
    if member is not None:
        db.delete(member)
        record(db, actor_id=ident.person.id, entity_type="project", entity_id=project.id, kind="member_removed", payload={"email": email})
        db.commit()
        db.refresh(project)
    return project_out(project)


# ---------------------------------------------------------------- updates (0.11.0)
@router.post("/{slug}/updates", response_model=ProjectUpdateOut, status_code=201)
def post_update(slug: str, body: ProjectUpdateIn, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    """Update do ciclo. Dono, membro, lideranca ou admin. Append-only: corrigir e mandar outro.
    posted_at no passado, author_email de outra pessoa e source=notion so admin ou C-level (importacao)."""
    project = _get(db, slug)
    is_member = project.owner_id == ident.person.id or any(m.person_id == ident.person.id for m in project.members)
    if not (is_member or ident.is_admin or ident.is_leadership):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "so dono, membro do projeto, lideranca ou admin")
    importing = body.posted_at is not None or body.source == "notion" or (
        body.author_email is not None and body.author_email.lower() != ident.email)
    if importing and not ident.sees_everything:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "posted_at, author_email e source=notion: so admin ou C-level (importacao)")
    now = utcnow()
    posted_at = as_utc(body.posted_at) if body.posted_at else now
    if posted_at > now + timedelta(minutes=5):
        raise HTTPException(422, "posted_at no futuro")
    author = get_or_create_person(db, body.author_email) if body.author_email else ident.person
    # idempotente (0.12.1): o append-only nao apaga, entao repetir a chamada (importacao que caiu no
    # meio e rodou de novo, retry depois de timeout) nao pode gravar o mesmo update duas vezes.
    # Importacao: mesmo projeto, data e texto. Update do dia: mesmo projeto, autor e texto em 15 min.
    summary = body.summary.strip()
    same = db.query(ProjectUpdate).filter(ProjectUpdate.project_id == project.id, ProjectUpdate.summary == summary).all()
    for old in same:
        at = as_utc(old.posted_at)
        if (body.posted_at is not None and at == posted_at) or (
                body.posted_at is None and old.author_id == author.id and now - at <= timedelta(minutes=15)):
            return project_update_out(old)
    u = ProjectUpdate(project_id=project.id, author_id=author.id, posted_at=posted_at, farol=body.farol,
                      summary=summary, help_needed=(body.help_needed or "").strip() or None,
                      next_focus=(body.next_focus or "").strip() or None, target_end_at=body.target_end_at,
                      source=body.source, source_ref=body.source_ref, created_by_id=ident.person.id)
    db.add(u)
    db.flush()
    payload = {"update_id": u.id, "farol": u.farol, "source": u.source}
    # termino previsto informado num update recente move o do projeto (importacao antiga nao mexe)
    if body.target_end_at and body.target_end_at != project.target_end_at and posted_at >= now - timedelta(days=1):
        payload["target_end_at"] = {"from": project.target_end_at.isoformat() if project.target_end_at else None,
                                    "to": body.target_end_at.isoformat()}
        project.target_end_at = body.target_end_at
    record(db, actor_id=ident.person.id, entity_type="project", entity_id=project.id, kind="update_posted", payload=payload)
    db.commit()
    db.refresh(u)
    return project_update_out(u)


@router.get("/{slug}/updates", response_model=list[ProjectUpdateOut])
def list_updates(slug: str, limit: int = 10, since: datetime | None = None, db: Session = Depends(get_db),
                 _: Identity = Depends(current_identity)):
    """Historico de updates, mais novo primeiro. Visivel para todo mundo, como o dono do projeto:
    o update e o status do projeto para a empresa. Conteudo sensivel nao entra em update."""
    project = _get(db, slug)
    q = db.query(ProjectUpdate).options(joinedload(ProjectUpdate.author), joinedload(ProjectUpdate.project)).filter(
        ProjectUpdate.project_id == project.id)
    if since:
        q = q.filter(ProjectUpdate.posted_at >= as_utc(since))
    rows = q.order_by(ProjectUpdate.posted_at.desc(), ProjectUpdate.id.desc()).limit(max(1, min(limit, 200))).all()
    return [project_update_out(u) for u in rows]


def build_report(db: Session, as_of: datetime | None, since: datetime | None, max_priority: int | None,
                 include_off: bool) -> ProjectReportOut:
    now = as_utc(as_of) if as_of else utcnow()
    since_ = as_utc(since) if since else now - timedelta(days=7)
    q = db.query(Project).filter(Project.status == "active")
    if max_priority:
        q = q.filter(Project.priority <= max_priority)
    projects = q.order_by(Project.priority, Project.slug).all()
    items: list[ProjectReportItem] = []
    for p in projects:
        rows = (db.query(ProjectUpdate).options(joinedload(ProjectUpdate.author), joinedload(ProjectUpdate.project))
                .filter(ProjectUpdate.project_id == p.id, ProjectUpdate.posted_at <= now)
                .order_by(ProjectUpdate.posted_at.desc(), ProjectUpdate.id.desc()).limit(2).all())
        latest, prev = (rows + [None, None])[:2]
        st = status_for(p, latest.posted_at if latest else None, latest.farol if latest else None, now)
        if st.state == "off" and not include_off:
            continue
        items.append(ProjectReportItem(
            slug=p.slug, name=p.name, priority=p.priority,
            owner=project_out(p).owner, target_end_at=p.target_end_at, update_frequency=p.update_frequency,
            status=st, latest=project_update_out(latest) if latest else None,
            previous_farol=prev.farol if prev else None,
            farol_changed=bool(latest and prev and latest.farol != prev.farol),
            end_moved=bool(latest and prev and latest.target_end_at and prev.target_end_at
                           and latest.target_end_at != prev.target_end_at),
        ))
    items.sort(key=lambda i: (STATE_ORDER.get(i.status.state, 9), i.priority, i.slug))
    missing = [i.slug for i in items if i.status.state in ("due", "late")]
    late = [i.slug for i in items if i.status.state == "late"]
    help_ = [i for i in items if i.latest and i.latest.help_needed and as_utc(i.latest.posted_at) >= since_]
    counts: dict[str, int] = {}
    for i in items:
        counts[i.status.state] = counts.get(i.status.state, 0) + 1
        if i.latest:
            counts[f"farol:{i.latest.farol}"] = counts.get(f"farol:{i.latest.farol}", 0) + 1
    return ProjectReportOut(as_of=now, since=since_, projects=items, missing=missing, late=late, help_needed=help_, counts=counts)


@router.get("/-/report", response_model=ProjectReportOut)
def report(as_of: datetime | None = None, since: datetime | None = None, max_priority: int | None = None,
           include_off: bool = False, db: Session = Depends(get_db), _: Identity = Depends(current_identity)):
    """Report dos updates para a reuniao: estado de cada projeto ativo no ciclo, ultimo update,
    mudanca de farol e de termino, quem nao mandou e quem pede ajuda desde `since` (padrao 7 dias)."""
    return build_report(db, as_of, since, max_priority, include_off)


@router.get("/{slug}", response_model=ProjectOut)
def get_project(slug: str, db: Session = Depends(get_db), _: Identity = Depends(current_identity)):
    """Um projeto, com o estado do ciclo de update. E o link que a Estoca brain usa."""
    return with_status(db, [_get(db, slug)])[0]


@router.get("/{slug}/events", response_model=list[EventOut])
def project_events(slug: str, db: Session = Depends(get_db), _: Identity = Depends(current_identity)):
    """Historico do projeto (criado, dono, prioridade, cadencia, updates, membros), do mais antigo ao mais novo.
    Visivel para todo mundo, como o projeto e seus updates."""
    return history(db, "project", _get(db, slug).id)
