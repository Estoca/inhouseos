"""Organograma (0.16.0, LAB-9): quem responde para quem, para a visao do time.

Fonte oficial: o escritorio. GET OFFICE_ORG_URL devolve {"people": [{email, name, area,
manager_email, c_level}]}, so ativos. Autenticacao sem segredo proprio: o tracker repassa o actor
JWT que recebeu do MCP interno na mesma chamada (60s de validade; o escritorio aceita a audience do
tracker nessa rota). Por isso so renova numa chamada pelo MCP (o pacote de cada um, toda manha);
a tela, que so tem o e-mail do Authentik, le o cache. O tracker guarda em org_people e renova quando
o cache passa de ORG_CACHE_SECONDS (sem cron). Falhou: segue com o que tem.

Sem o escritorio configurado, ou sem sync ha mais de um dia, o cache aprende com o token do MCP: cada
chamada traz os reportes diretos de quem chama (o escritorio monta isso em /api/internal/mcp/v1/actor),
e eles ganham manager_email = quem chamou (source=mcp). Token sem a claim `reports` nao ensina nada.

Direto = manager_email e o gestor. Arvore = todo mundo abaixo dele, por qualquer caminho.
"""
from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from iho.tracker.config import settings
from iho.tracker.models import OrgPerson, utcnow
from iho.tracker.version import app_version

logger = logging.getLogger(__name__)
OFFICE_TRUST = timedelta(days=1)  # sync do escritorio mais novo que isso: o token nao reescreve
RETRY_AFTER = timedelta(minutes=5)  # escritorio fora: nao tenta de novo a cada leitura
_last_failure: datetime | None = None
_last_error: str | None = None  # ultimo erro do sync (HTTP 403, URLError...), para aparecer na resposta


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:  # SQLite devolve sem fuso; gravamos em UTC
        return dt.replace(tzinfo=timezone.utc)
    return dt


def office_configured() -> bool:
    return bool(settings.office_org_url)


def last_office_sync(db: Session) -> datetime | None:
    return _aware(db.query(func.max(OrgPerson.seen_at)).filter(OrgPerson.source == "office").scalar())


def _fetch_office(token: str) -> list[dict]:
    # User-Agent proprio: o Cloudflare na frente do escritorio barra o "Python-urllib" (erro 1010, 20-10)
    req = urllib.request.Request(settings.office_org_url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/json",
        "User-Agent": f"estoca-project-tracker/{app_version()}"})
    with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310 (URL da configuracao)
        data = json.load(r)
    people = data.get("people") if isinstance(data, dict) else None
    return [p for p in people or [] if isinstance(p, dict)]


def _email(v) -> str | None:
    v = str(v or "").strip().lower()
    return v if "@" in v else None


def sync_from_office(db: Session, token: str | None, now: datetime | None = None, force: bool = False) -> bool:
    """Renova o cache pelo escritorio se ele esta configurado, ha actor JWT para repassar e o cache
    passou da idade. Devolve se ha cache do escritorio. Resposta vazia ou erro nao apagam nada."""
    if not office_configured():
        return False
    if not token:  # tela (Authentik) ou service token: le o cache
        return last_office_sync(db) is not None
    now = now or utcnow()
    last = last_office_sync(db)
    global _last_failure, _last_error
    if not force and last and now - last < timedelta(seconds=settings.org_cache_seconds):
        return True
    if not force and _last_failure and now - _last_failure < RETRY_AFTER:
        return last is not None
    try:
        people = _fetch_office(token)
    except Exception as exc:  # rede, HTTP, JSON: o cache antigo segue valendo
        code = getattr(exc, "code", None)
        _last_error = f"HTTP {code}" if isinstance(code, int) else type(exc).__name__
        logger.warning("org sync do escritorio falhou: %s", _last_error)
        _last_failure = now
        return last is not None
    if not people:
        logger.warning("org sync do escritorio veio vazio; cache mantido")
        _last_error = "resposta vazia"
        _last_failure = now
        return last is not None
    _last_failure = _last_error = None
    rows = {r.email: r for r in db.query(OrgPerson).all()}
    seen: set[str] = set()
    for p in people:
        email = _email(p.get("email"))
        if not email or email in seen:
            continue
        seen.add(email)
        r = rows.get(email)
        if r is None:
            r = OrgPerson(email=email)
            db.add(r)
        r.name = (str(p.get("name")).strip() or None) if p.get("name") else None
        r.area = (str(p.get("area")).strip() or None) if p.get("area") else None
        r.manager_email = _email(p.get("manager_email"))
        r.c_level = bool(p.get("c_level"))
        r.source, r.seen_at = "office", now
    for email, r in rows.items():
        if email not in seen:  # saiu do organograma (desligado ou oculto)
            db.delete(r)
    db.commit()
    return True


def learn_from_token(db: Session, email: str, roles: set[str], reports: set[str], now: datetime | None = None) -> None:
    """Chamada pelo MCP com a claim `reports`: guarda os reportes diretos de quem chama e se e C-level.
    Nao mexe no cache se o escritorio sincronizou ha menos de OFFICE_TRUST."""
    now = now or utcnow()
    last = last_office_sync(db)
    if last and now - last < OFFICE_TRUST:
        return
    rows = {r.email: r for r in db.query(OrgPerson).filter(
        or_(OrgPerson.email.in_([email, *reports]), OrgPerson.manager_email == email)).all()}
    touched: list[OrgPerson] = []

    def row(e: str) -> OrgPerson:
        r = rows.get(e)
        if r is None:
            r = rows[e] = OrgPerson(email=e, manager_email=None, c_level=False)
            db.add(r)
            touched.append(r)
        return r

    me = row(email)
    if me.c_level != ("c_level" in roles):
        me.c_level = "c_level" in roles
        touched.append(me)
    for e in reports:
        r = row(e)
        if r.manager_email != email:
            r.manager_email = email
            touched.append(r)
    for r in list(rows.values()):
        if r.manager_email == email and r.email not in reports:  # mudou de gestor ou saiu
            r.manager_email = None
            touched.append(r)
    if touched:
        for r in touched:
            r.source, r.seen_at = "mcp", now
        db.commit()


def children(db: Session) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for email, manager in db.query(OrgPerson.email, OrgPerson.manager_email).filter(OrgPerson.manager_email.isnot(None)):
        if email != manager:
            out.setdefault(manager, []).append(email)
    return out


def direct(db: Session, email: str, kids: dict[str, list[str]] | None = None) -> list[str]:
    kids = children(db) if kids is None else kids
    return sorted(kids.get(email, []))


def tree(db: Session, email: str, kids: dict[str, list[str]] | None = None) -> dict[str, str]:
    """Todo mundo abaixo de `email` -> o reporte direto por onde a pessoa entra (ela mesma, se direta)."""
    kids = children(db) if kids is None else kids
    out: dict[str, str] = {}
    queue = [(e, e) for e in kids.get(email, [])]
    while queue:
        e, via = queue.pop(0)
        if e in out or e == email:  # ciclo no organograma nao trava
            continue
        out[e] = via
        queue.extend((c, via) for c in kids.get(e, []))
    return out


def is_c_level(db: Session, email: str) -> bool:
    return bool(db.query(OrgPerson.c_level).filter(OrgPerson.email == email).scalar())


def info(db: Session) -> dict:
    office = last_office_sync(db)
    if office:
        return {"source": "office", "synced_at": office, "last_error": _last_error}
    seen = _aware(db.query(func.max(OrgPerson.seen_at)).scalar())
    return {"source": "mcp" if seen else None, "synced_at": seen, "last_error": _last_error}


def names(db: Session, emails: list[str]) -> dict[str, str | None]:
    return dict(db.query(OrgPerson.email, OrgPerson.name).filter(OrgPerson.email.in_(emails or ["-"])).all())
