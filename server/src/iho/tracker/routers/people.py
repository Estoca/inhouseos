from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from iho.tracker.auth import Identity, current_identity
from iho.tracker.db import get_db
from iho.tracker.events import record
from iho.tracker.models import Person
from iho.tracker.schemas import PersonOut, PersonPatch

router = APIRouter(prefix="/api/people")


@router.get("", response_model=list[PersonOut])
def list_people(db: Session = Depends(get_db), _: Identity = Depends(current_identity)):
    return db.query(Person).order_by(Person.email).all()


@router.patch("/{email}", response_model=PersonOut)
def patch_person(email: str, body: PersonPatch, db: Session = Depends(get_db), ident: Identity = Depends(current_identity)):
    person = db.query(Person).filter(Person.email == email.lower()).one_or_none()
    if person is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "pessoa nao existe")
    fields = body.model_dump(exclude_none=True)
    governance = {"active", "adoption_exempt"} & fields.keys()
    if governance and not ident.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "active e adoption_exempt: so admin")
    if person.id != ident.person.id and not ident.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "so a propria pessoa ou admin")
    before = {k: getattr(person, k) for k in fields}
    for k, v in fields.items():
        setattr(person, k, v)
    if governance:
        record(db, actor_id=ident.person.id, entity_type="person", entity_id=person.id, kind="person_updated",
               payload={"before": before, "after": fields})
    db.commit()
    return person
