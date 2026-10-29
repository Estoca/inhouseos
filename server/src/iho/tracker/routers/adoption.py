"""GET /api/adoption: adocao do pacote do dia (quem abriu, em quantos dias uteis).
/api/absences: ferias e folgas que saem da conta de dias uteis. Ver app/adoption.py."""
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from iho.tracker import adoption
from iho.tracker.auth import Identity, current_identity
from iho.tracker.db import get_db
from iho.tracker.events import record
from iho.tracker.models import Absence, Person
from iho.tracker.schemas import AbsenceIn, AbsenceOut, AdoptionOut, PersonOut
from iho.tracker.workdays import is_business_day

router = APIRouter()


@router.get("/api/adoption", response_model=list[AdoptionOut])
def get_adoption(person: str | None = None, as_of: date | None = None, days: int | None = Query(default=None, ge=5, le=120),
                 db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    people = adoption.people_for(db, ident, person)
    if person and not people:
        if db.query(Person).filter(Person.email == person.strip().lower()).one_or_none() is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "pessoa nao existe")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "adocao de outra pessoa so para lideranca")
    return [adoption.compute(db, p, as_of, days) for p in people]


def _absence_out(a: Absence) -> AbsenceOut:
    return AbsenceOut(id=a.id, person=PersonOut.model_validate(a.person), day=a.day, reason=a.reason)


@router.get("/api/absences", response_model=list[AbsenceOut])
def list_absences(person: str | None = None, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    people = adoption.people_for(db, ident, person)
    ids = [p.id for p in people] or [-1]
    rows = db.query(Absence).filter(Absence.person_id.in_(ids)).order_by(Absence.day.desc()).limit(500).all()
    return [_absence_out(a) for a in rows]


@router.post("/api/absences", response_model=list[AbsenceOut], status_code=201)
def add_absence(body: AbsenceIn, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    """Registra ferias ou folga (dias uteis de start a end saem da conta). A propria pessoa,
    a lideranca dela ou quem ve tudo. Ate o escritorio expor isso, e manual."""
    email = (body.email or ident.email).strip().lower()
    if email != ident.email and not ident.sees_everything and email not in ident.reports:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "ausencia de outra pessoa so para lideranca")
    person = db.query(Person).filter(Person.email == email).one_or_none()
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pessoa nao existe")
    end = body.end or body.start
    if end < body.start or (end - body.start).days > 120:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "intervalo invalido (ate 120 dias)")
    existing = {a.day for a in db.query(Absence).filter(Absence.person_id == person.id, Absence.day >= body.start, Absence.day <= end).all()}
    out, d = [], body.start
    while d <= end:
        if is_business_day(d) and d not in existing:
            a = Absence(person_id=person.id, day=d, reason=body.reason, created_by_id=ident.person.id)
            db.add(a)
            out.append(a)
        d += timedelta(days=1)
    db.flush()
    record(db, actor_id=ident.person.id, entity_type="person", entity_id=person.id, kind="absence_added",
           payload={"start": body.start.isoformat(), "end": end.isoformat(), "reason": body.reason, "days": len(out)})
    db.commit()
    for a in out:
        db.refresh(a)
    return [_absence_out(a) for a in out]
