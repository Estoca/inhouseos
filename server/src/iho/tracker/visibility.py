"""Quem ve o que. Ver DESIGN.md.

- membro do projeto: acoes e decisoes do projeto (menos decisao private)
- pessoa: tudo em que e requester ou waiting_on / decider
- lideranca: tudo dos seus reports; c_level e admins: 100%
- todos: quem e dono de qual projeto
"""
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from iho.tracker.auth import Identity
from iho.tracker.models import Action, Decision, Person, ProjectMember


def _member_project_ids(db: Session, person_id: int) -> list[int]:
    return list(db.scalars(select(ProjectMember.project_id).where(ProjectMember.person_id == person_id)))


def _report_ids(db: Session, ident: Identity) -> list[int]:
    if not ident.reports:
        return []
    return list(db.scalars(select(Person.id).where(Person.email.in_(ident.reports))))


def action_filter(db: Session, ident: Identity):
    if ident.sees_everything:
        return None
    me = ident.person.id
    people = [me, *_report_ids(db, ident)]
    projects = _member_project_ids(db, me)
    clauses = [Action.requester_id.in_(people), Action.waiting_on_id.in_(people), Action.created_by_id == me]
    if projects:
        clauses.append(Action.project_id.in_(projects))
    return or_(*clauses)


def decision_filter(db: Session, ident: Identity):
    if ident.sees_everything:
        return None
    me = ident.person.id
    people = [me, *_report_ids(db, ident)]
    projects = _member_project_ids(db, me)
    mine = or_(Decision.decider_id.in_(people), Decision.requester_id.in_(people))
    if not projects:
        return mine
    in_project = Decision.project_id.in_(projects) & (Decision.visibility != "private")
    if ident.is_leadership:
        return or_(mine, in_project)
    return or_(mine, in_project & (Decision.visibility != "leadership"))
