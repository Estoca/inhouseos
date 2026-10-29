"""Cadencia de update de projeto (0.11.0): em que ponto do ciclo cada projeto esta.

Nada roda sozinho. O estado e calculado na leitura (digest, lista de projetos, report), a
partir da cadencia do projeto e da data do ultimo update. Nao existe pendencia por ciclo: o
lembrete aparece no pacote do dono e some quando o update entra.

Ciclo: prazos em update_weekday + update_time (America/Sao_Paulo), a partir de update_since.
- weekly: toda semana; biweekly: a cada 2 semanas, contando do primeiro prazo depois de
  update_since; monthly: a primeira ocorrencia do dia da semana em cada mes.
- ok: ha update depois do prazo anterior (ou, no primeiro ciclo, depois de update_since).
- late: o prazo anterior passou sem update no ciclo dele. Continua late ate entrar um update.
- due: falta o update do ciclo atual e ja estamos na janela de lembrete, que depende da
  prioridade do projeto (UPDATE_REMIND_DAYS, dias uteis antes do prazo: P1 2, P2 1, P3 0).
- pending: falta, mas ainda nao e hora de lembrar.
- off: sem frequencia ou projeto que nao esta active.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from iho.tracker.config import settings
from iho.tracker.models import Project, ProjectUpdate, utcnow
from iho.tracker.schemas import UpdateStatusOut
from iho.tracker.workdays import SP, is_business_day

WEEKDAYS = {"seg": 0, "ter": 1, "qua": 2, "qui": 3, "sex": 4, "sab": 5, "dom": 6}
DEFAULT_TIME = "18:00"


def as_utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _at(d: date, hhmm: str) -> datetime:
    h, m = (int(x) for x in hhmm.split(":"))
    return datetime.combine(d, time(h, m), tzinfo=SP).astimezone(timezone.utc)


def _first_weekday_of_month(year: int, month: int, wd: int) -> date:
    d = date(year, month, 1)
    return d + timedelta(days=(wd - d.weekday()) % 7)


def deadlines(p: Project, until: datetime) -> list[datetime]:
    """Prazos do projeto depois de update_since, em ordem, ate o primeiro >= until (inclusive)."""
    if not (p.update_frequency and p.update_weekday and p.update_since):
        return []
    wd, hhmm, anchor = WEEKDAYS[p.update_weekday], p.update_time or DEFAULT_TIME, as_utc(p.update_since)
    until = as_utc(until)
    out: list[datetime] = []
    if p.update_frequency == "monthly":
        local = anchor.astimezone(SP).date()
        y, m = local.year, local.month
        while True:
            dl = _at(_first_weekday_of_month(y, m, wd), hhmm)
            if dl > anchor:
                out.append(dl)
                if dl >= until:
                    return out
            y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    step = timedelta(days=14 if p.update_frequency == "biweekly" else 7)
    local = anchor.astimezone(SP).date()
    d = local + timedelta(days=(wd - local.weekday()) % 7)
    dl = _at(d, hhmm)
    if dl <= anchor:
        d += timedelta(days=7)
    while True:
        dl = _at(d, hhmm)
        out.append(dl)
        if dl >= until:
            return out
        d += step


def remind_days(priority: int) -> int:
    return settings.update_remind.get(priority, 0)


def remind_from(due: datetime, priority: int) -> datetime:
    """Inicio do dia (SP) que fica `n` dias uteis antes do dia do prazo; n=0 e o proprio dia."""
    d, n = due.astimezone(SP).date(), remind_days(priority)
    while n > 0:
        d -= timedelta(days=1)
        if is_business_day(d):
            n -= 1
    return datetime.combine(d, time.min, tzinfo=SP).astimezone(timezone.utc)


def status_for(p: Project, last_update_at: datetime | None, last_farol: str | None = None,
               now: datetime | None = None) -> UpdateStatusOut:
    now = as_utc(now or utcnow())
    last = as_utc(last_update_at) if last_update_at else None
    base = dict(last_update_at=last, last_farol=last_farol)
    if p.status != "active" or not p.update_frequency or not p.update_since:
        return UpdateStatusOut(state="off", **base)
    dls = deadlines(p, now)
    due = dls[-1]
    passed = [d for d in dls if d < now]  # prazos que ja venceram
    anchor = as_utc(p.update_since)
    prev = passed[-1] if passed else None
    rf = remind_from(due, p.priority)
    hours_left = round((due - now).total_seconds() / 3600, 1)
    common = dict(due_at=due, remind_from=rf, **base)
    if last and last > (prev or anchor):
        return UpdateStatusOut(state="ok", hours_left=hours_left, **common)
    # ciclos perdidos: os que comecaram depois do ultimo update e cujo prazo ja passou. Ciclo
    # anterior ao ultimo update fica perdoado: o update novo poe o projeto em dia.
    starts = [anchor, *passed[:-1]]
    missed = [d for s, d in zip(starts, passed) if last is None or last <= s]
    if missed:
        first = missed[0]
        return UpdateStatusOut(state="late", late_since=first, cycles_missed=len(missed),
                               hours_left=round((first - now).total_seconds() / 3600, 1), **common)
    state = "due" if now >= rf else "pending"
    return UpdateStatusOut(state=state, hours_left=hours_left, **common)


def latest_updates(db: Session, project_ids: list[int], until: datetime | None = None) -> dict[int, ProjectUpdate]:
    """Ultimo update de cada projeto (ate `until`), numa consulta."""
    if not project_ids:
        return {}
    q = db.query(ProjectUpdate.project_id, func.max(ProjectUpdate.posted_at)).filter(ProjectUpdate.project_id.in_(project_ids))
    if until is not None:
        q = q.filter(ProjectUpdate.posted_at <= until)
    pairs = q.group_by(ProjectUpdate.project_id).all()
    out: dict[int, ProjectUpdate] = {}
    for pid, at in pairs:
        row = (db.query(ProjectUpdate).filter(ProjectUpdate.project_id == pid, ProjectUpdate.posted_at == at)
               .order_by(ProjectUpdate.id.desc()).first())
        if row is not None:
            out[pid] = row
    return out
