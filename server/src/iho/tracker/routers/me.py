from fastapi import APIRouter, Depends

from iho.tracker.auth import Identity, current_identity
from iho.tracker.schemas import MeOut, PersonOut

router = APIRouter()


@router.get("/api/me", response_model=MeOut)
def me(ident: Identity = Depends(current_identity)) -> MeOut:
    return MeOut(
        person=PersonOut.model_validate(ident.person),
        via=ident.via,
        roles=sorted(ident.roles),
        is_admin=ident.is_admin,
        sees_everything=ident.sees_everything,
    )
