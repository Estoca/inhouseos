"""Identidade.

Tres caminhos, nesta ordem:
1. Service token (MCP interno): Authorization: Bearer <token> + X-Acting-User: <email>.
   Opcionais: X-Acting-Roles: c_level,leadership  e  X-Acting-Reports: a@x,b@x
   (quem responde para essa pessoa, resolvido pelo MCP interno a partir do Feedz).
2. Authentik (browser/REST atras do proxy): X-authentik-email, X-authentik-name.
3. Local: LOCAL_AUTH_MOCK_EMAIL, so fora de producao.

Papel/cargo nao vive no tracker. Chega por chamada e serve so para visibilidade.
"""
from dataclasses import dataclass, field

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from iho.tracker.names import clean_person_name
from iho.tracker.config import settings
from iho.tracker.db import get_db
from iho.tracker.models import Person


@dataclass
class Identity:
    email: str
    name: str | None = None
    roles: set[str] = field(default_factory=set)  # c_level | leadership
    reports: set[str] = field(default_factory=set)  # e-mails de quem responde para ela
    via: str = "authentik"  # service | authentik | mock
    person: Person | None = None
    # actor JWT do MCP interno (so via mcp): o tracker repassa ao escritorio na mesma chamada para
    # ler o organograma (app/org.py). Vale 60s e nunca e gravado.
    token: str | None = field(default=None, repr=False)

    @property
    def is_admin(self) -> bool:
        return self.email in settings.admin_email_set

    @property
    def sees_everything(self) -> bool:
        return self.is_admin or "c_level" in self.roles

    @property
    def is_leadership(self) -> bool:
        return self.sees_everything or "leadership" in self.roles

    @property
    def can_set_priority(self) -> bool:
        return self.is_admin or "c_level" in self.roles


def _split(value: str | None) -> set[str]:
    return {v.strip().lower() for v in (value or "").split(",") if v.strip()}


def get_or_create_person(db: Session, email: str, name: str | None = None) -> Person:
    email = email.strip().lower()
    name = clean_person_name(name)
    person = db.query(Person).filter(Person.email == email).one_or_none()
    if person is None:
        person = Person(email=email, name=name)
        db.add(person)
        db.flush()
    elif clean_person_name(person.name) != person.name:
        # nome gravado sujo (admin padrao do Authentik, mojibake): troca pelo limpo, ou None
        person.name = name or clean_person_name(person.name)
    elif name and not person.name:
        person.name = name
    return person


def current_identity(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
    x_acting_user: str | None = Header(default=None),
    x_acting_roles: str | None = Header(default=None),
    x_acting_reports: str | None = Header(default=None),
    x_authentik_email: str | None = Header(default=None),
    x_authentik_name: str | None = Header(default=None),
) -> Identity:
    ident: Identity | None = None

    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
        if token not in settings.service_token_set:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "service token invalido")
        if not x_acting_user:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Acting-User obrigatorio com service token")
        ident = Identity(
            email=x_acting_user.strip().lower(),
            roles=_split(x_acting_roles),
            reports=_split(x_acting_reports),
            via="service",
        )
    elif x_authentik_email:
        ident = Identity(email=x_authentik_email.strip().lower(), name=x_authentik_name, via="authentik")
    elif settings.local_auth_mock_email and not settings.is_production:
        ident = Identity(
            email=settings.local_auth_mock_email.lower(), name=settings.local_auth_mock_name, via="mock"
        )

    if ident is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "sem identidade")

    ident.person = get_or_create_person(db, ident.email, ident.name)
    db.commit()
    return ident
