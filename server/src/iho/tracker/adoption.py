"""Adocao do pacote do dia (/bomdia): quem abriu, em quantos dos seus dias uteis.

O tracker registra a abertura quando a LLM da pessoa chama o digest dela mesma pelo MCP
interno (via mcp/service). Abrir o quadro no navegador nao conta: o combinado e o pacote,
nao a tela. Dias uteis = calendario nacional (app.workdays) menos as ausencias registradas
da pessoa (ferias, folga). Quem esta inativo ou com adoption_exempt (supervisor de operacao)
sai das listas e nao recebe o sinal no digest. Janela: os ultimos ADOPTION_WINDOW_DAYS dias uteis, comecando
no primeiro dia em que a pessoa abriu (quem entrou ontem nao e cobrado por 20 dias).
O dia de hoje so entra na janela se ja foi aberto; senao a janela termina ontem.
Meta: ADOPTION_TARGET (0.8 = 80% dos dias uteis). A mesma conta vale para a pessoa
(no digest e no quadro) e para a lideranca (tracker_adoption): ninguem ve um numero
que a pessoa nao ve.
"""
from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from iho.tracker.config import settings
from iho.tracker.models import Absence, DigestOpen, Event, Person, utcnow
from iho.tracker.schemas import AdoptionOut, PersonOut
from iho.tracker.workdays import SP, is_business_day, last_business_days


def today_sp() -> date:
    return datetime.now(SP).date()


def record_open(db: Session, person_id: int, now: datetime | None = None) -> DigestOpen:
    now = now or utcnow()
    day = now.astimezone(SP).date()
    row = db.query(DigestOpen).filter(DigestOpen.person_id == person_id, DigestOpen.day == day).one_or_none()
    if row is None:
        row = DigestOpen(person_id=person_id, day=day, first_at=now, count=1)
        db.add(row)
    else:
        row.count = (row.count or 0) + 1
    db.flush()
    return row


def compute(db: Session, person: Person, as_of: date | None = None, days: int | None = None) -> AdoptionOut:
    as_of = as_of or today_sp()
    days = days or settings.adoption_window_days
    target = settings.adoption_target

    opens = {r.day: r for r in db.query(DigestOpen).filter(DigestOpen.person_id == person.id).all()}
    first_open = min(opens) if opens else None
    last_open = max(opens) if opens else None

    # so o dia de HOJE fica de fora enquanto nao foi aberto (o dia nao acabou); as_of no passado conta como falta
    end = None if (as_of >= today_sp() and is_business_day(as_of) and as_of not in opens) else as_of
    if end is None:
        prev = [d for d in last_business_days(as_of, 2) if d < as_of]
        end = prev[-1] if prev else as_of
    window = last_business_days(end, days)
    if first_open:
        window = [d for d in window if d >= first_open]
    else:
        window = []

    absent = {a.day for a in db.query(Absence).filter(Absence.person_id == person.id).all()}
    expected_days = [d for d in window if d not in absent]
    opened = [d for d in expected_days if d in opens]
    missed = [d for d in expected_days if d not in opens]
    rate = round(len(opened) / len(expected_days), 3) if expected_days else None

    reasons = []
    if window:
        evs = db.query(Event).filter(Event.kind == "digest_missed_reason", Event.entity_type == "person",
                                     Event.entity_id == person.id).order_by(Event.at.desc()).limit(50).all()
        for e in evs:
            p = e.payload or {}
            day = p.get("day")
            if day and window and window[0].isoformat() <= day <= window[-1].isoformat():
                reasons.append({"day": day, "reason": str(p.get("reason", ""))[:200]})

    return AdoptionOut(
        person=PersonOut.model_validate(person), as_of=as_of,
        window_start=window[0] if window else None, window_end=window[-1] if window else None,
        business_days=len(window), absences=len(window) - len(expected_days), expected_days=len(expected_days),
        opened_days=len(opened), rate=rate, target=target,
        on_track=(rate is None and first_open is not None and len(expected_days) < 5) or (rate is not None and rate >= target),
        enough_data=len(expected_days) >= 5,
        first_open=first_open, last_open=last_open,
        missed=sorted(missed, reverse=True)[:10], reasons=reasons[:10],
    )


def summary_line(a: AdoptionOut) -> str | None:
    if a.person.adoption_exempt:
        return None
    if a.first_open is None:
        return "Pacote do dia nunca aberto por esta pessoa."
    if not a.enough_data or a.rate is None:
        return None
    pct = round(a.rate * 100)
    tgt = round(a.target * 100)
    if a.on_track:
        return None
    return f"Pacote do dia aberto em {a.opened_days} de {a.expected_days} dias uteis ({pct}%): abaixo do combinado de {tgt}%"


def people_for(db: Session, ident, person_email: str | None) -> list[Person]:
    """Quem a pessoa que chama pode ver: ela mesma sempre; reportes se lideranca; todos se ve tudo."""
    if person_email:
        email = person_email.strip().lower()
        if email != ident.email and not ident.sees_everything and email not in ident.reports:
            return []
        p = db.query(Person).filter(Person.email == email).one_or_none()
        return [p] if p else []
    if ident.sees_everything:
        return (db.query(Person).filter(Person.active.is_(True), Person.adoption_exempt.is_(False))
                .order_by(Person.email).all())
    emails = {ident.email, *ident.reports}
    people = db.query(Person).filter(Person.email.in_(emails)).order_by(Person.email).all()
    # reporte desativado ou fora da meta sai da lista; a propria pessoa sempre se ve
    return [p for p in people if p.email == ident.email or (p.active and not p.adoption_exempt)]
