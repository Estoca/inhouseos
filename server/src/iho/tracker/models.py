"""Modelo de dados. Ver DESIGN.md.

Regras que o modelo carrega:
- waiting_on e UMA pessoa. Pendencia difusa nao e cobrada.
- espera de terceiro (fornecedor, cliente, plataforma) continua com waiting_on = a
  pessoa da Estoca dona do acompanhamento; waiting_external diz de quem se espera e
  tira o item do SLA. review_at e quando reavaliar. Nada de bump falso.
- acao so fecha com closed_evidence.
- events e append-only: e o "feito por quem e quando" e tambem onde fica
  registrado que a LLM cobrou e a pessoa nao agiu.
- papel/cargo NAO vive aqui. Vem do Feedz pelo MCP interno, em tempo de chamada.
"""
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, false, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Person(Base):
    __tablename__ = "people"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    slack_handle: Mapped[str | None] = mapped_column(String(100))
    active: Mapped[bool] = mapped_column(default=True)
    # fora da meta do pacote do dia (ex.: supervisor de operacao); continua no tracker
    adoption_exempt: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    priority: Mapped[int] = mapped_column(Integer, default=2)  # 1 alta, 2 media, 3 baixa. So C-level edita.
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | paused | done
    # kickoff (0.11.0): pagina do projeto na Estoca brain, inicio e termino previsto
    kickoff_ref: Mapped[str | None] = mapped_column(Text)
    # resumo do kickoff (0.12.0) para a pagina do projeto no tracker; o kickoff inteiro fica na Estoca brain
    objective: Mapped[str | None] = mapped_column(Text)
    goals: Mapped[list | None] = mapped_column(JSONType)  # metas impactadas: Receita, Custo/Margem, Retencao, EBITDA
    expected_results: Mapped[str | None] = mapped_column(Text)
    area: Mapped[str | None] = mapped_column(String(60))
    # planos do Radar ligados ao projeto (0.13.0): o update do projeto vira FUP neles, com o mesmo OK
    radar_plan_ids: Mapped[list | None] = mapped_column(JSONType)
    started_at: Mapped[date | None] = mapped_column(Date)
    target_end_at: Mapped[date | None] = mapped_column(Date)
    # cadencia de update (0.11.0): sem frequencia, o projeto nao cobra update. O prazo de cada ciclo e
    # update_weekday + update_time em America/Sao_Paulo; update_since ancora os ciclos (quinzenal) e
    # marca de quando a cadencia vale: ciclo anterior a ela nao conta como atrasado.
    update_frequency: Mapped[str | None] = mapped_column(String(20))  # weekly | biweekly | monthly
    update_weekday: Mapped[str | None] = mapped_column(String(3))  # seg | ter | qua | qui | sex | sab | dom
    update_time: Mapped[str | None] = mapped_column(String(5))  # HH:MM
    update_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    owner: Mapped[Person | None] = relationship()
    members: Mapped[list["ProjectMember"]] = relationship(back_populates="project", cascade="all, delete-orphan")


class ProjectUpdate(Base):
    """Update periodico do projeto (a "foto" do ciclo). Append-only: corrigir e mandar outro.

    Cobra-se o lider do projeto, nao a tarefa: o update e do projeto, e o lembrete sai do
    calculo da cadencia (app/project_updates.py), nao de uma pendencia por ciclo."""

    __tablename__ = "project_updates"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    farol: Mapped[str] = mapped_column(String(20))  # on_track | at_risk | blocked | done
    summary: Mapped[str] = mapped_column(Text)  # o que mudou de material desde o ultimo
    help_needed: Mapped[str | None] = mapped_column(Text)  # decisao ou ajuda da lideranca; vazio = nada
    next_focus: Mapped[str | None] = mapped_column(Text)  # foco ate o proximo update
    target_end_at: Mapped[date | None] = mapped_column(Date)  # termino previsto informado neste update
    source: Mapped[str] = mapped_column(String(20), default="manual")  # agent | manual | notion
    source_ref: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship()
    author: Mapped[Person] = relationship(foreign_keys=[author_id])


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "person_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    role: Mapped[str | None] = mapped_column(String(50))

    project: Mapped[Project] = relationship(back_populates="members")
    person: Mapped[Person] = relationship()


class Action(Base):
    __tablename__ = "actions"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(20), default="loop")  # loop | commitment
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    waiting_on_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    title: Mapped[str] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(100))  # slack:#canal | dm | email | meet | manual
    source_ref: Mapped[str | None] = mapped_column(Text)  # url
    asked_at: Mapped[date] = mapped_column(Date)
    last_bump_at: Mapped[date] = mapped_column(Date)
    sev: Mapped[int] = mapped_column(Integer, default=2)
    # espera de terceiro: preenchido = fora do SLA (ninguem da Estoca a cobrar). Ex: "TikTok — aprovacao da conta"
    waiting_external: Mapped[str | None] = mapped_column(Text)
    review_at: Mapped[date | None] = mapped_column(Date)  # quando reavaliar a espera de terceiro
    # prazo de entrega combinado. Com prazo, so vence depois dele; o SLA da sev volta a contar
    # quando alguem cobra depois do prazo (bump real > due_at). Sem prazo, so o SLA, como antes.
    due_at: Mapped[date | None] = mapped_column(Date)
    # open | done | wontfix | moved | duplicate (duplicate_of_id aponta a que fica) | not_mine (quem deve
    # nao reconhece; volta para quem pediu no digest, em `bounced`)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("actions.id"))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_evidence: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project | None] = relationship()
    requester: Mapped[Person] = relationship(foreign_keys=[requester_id])
    waiting_on: Mapped[Person] = relationship(foreign_keys=[waiting_on_id])


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    decider_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    requester_id: Mapped[int] = mapped_column(ForeignKey("people.id"))
    opened_at: Mapped[date] = mapped_column(Date)
    deadline: Mapped[date | None] = mapped_column(Date)
    priority: Mapped[str] = mapped_column(String(10), default="media")  # alta | media | baixa
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)  # open | decided | dropped
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(String(20), default="project")  # project | leadership | private
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project | None] = relationship()
    decider: Mapped[Person] = relationship(foreign_keys=[decider_id])
    requester: Mapped[Person] = relationship(foreign_keys=[requester_id])


class Suggestion(Base):
    """O que a LLM sugeriu a uma pessoa, e o que ela fez com isso.

    E a base da eficacia: adesao baixa com resultado bom = a LLM sugere mal
    (problema de Compass/plugin); adesao baixa com resultado ruim = a regua de
    delegacao pode subir para aquele tipo de acao.
    """

    __tablename__ = "suggestions"
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)  # para quem
    kind: Mapped[str] = mapped_column(String(30), index=True)
    # nudge | close | escalate | decide | create_issue | schedule_1on1 | promote | other
    entity_type: Mapped[str | None] = mapped_column(String(20))  # action | decision | project | person
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), index=True)
    text: Mapped[str] = mapped_column(Text)
    rule: Mapped[str | None] = mapped_column(String(80))  # regra do Compass que motivou, ex: "sla:sev2", "sinal:1on1"
    made_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    outcome: Mapped[str] = mapped_column(String(20), default="pending", index=True)  # pending | followed | deviated | ignored
    outcome_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome_note: Mapped[str | None] = mapped_column(Text)  # o que a pessoa fez em vez disso
    created_by_id: Mapped[int] = mapped_column(ForeignKey("people.id"))

    person: Mapped[Person] = relationship(foreign_keys=[person_id])
    project: Mapped[Project | None] = relationship()


class Event(Base):
    """Append-only. Nunca UPDATE, nunca DELETE."""

    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"), index=True)
    entity_type: Mapped[str] = mapped_column(String(20), index=True)  # action | decision | project | person
    entity_id: Mapped[int | None] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    # created | updated (payload.changes = {campo: {from, to}}) | bumped | closed
    # reopened (payload: previous_status, previous_outcome|previous_evidence, reason)
    # decided | dropped | priority_changed
    # nudged | nudge_ignored | process_deviation | decision_kept_private
    # suggested | suggestion_followed | suggestion_deviated | suggestion_ignored
    payload: Mapped[dict | None] = mapped_column(JSONType)

    actor: Mapped[Person | None] = relationship()


class DigestOpen(Base):
    """Uma linha por pessoa e dia (America/Sao_Paulo) em que a LLM dela abriu o digest pelo MCP.
    E o dado de adocao do pacote do dia. Abrir o quadro no navegador nao grava aqui."""

    __tablename__ = "digest_opens"
    __table_args__ = (UniqueConstraint("person_id", "day", name="uq_digest_open_person_day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    first_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    count: Mapped[int] = mapped_column(Integer, default=1)
    person = relationship("Person", foreign_keys=[person_id])


class Absence(Base):
    """Dia util em que a pessoa nao e cobrada pelo pacote (ferias, folga, licenca).
    Manual ate o escritorio expor ferias e feriados por pessoa."""

    __tablename__ = "absences"
    __table_args__ = (UniqueConstraint("person_id", "day", name="uq_absence_person_day"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int] = mapped_column(ForeignKey("people.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)
    reason: Mapped[str | None] = mapped_column(String(120))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("people.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    person = relationship("Person", foreign_keys=[person_id])


class OrgPerson(Base):
    """Cache do organograma (0.16.0): quem responde para quem. Fonte oficial: o escritorio
    (app/org.py, sync_from_office). Sem o escritorio configurado, o cache aprende com o token
    do MCP: cada chamada traz os reportes diretos de quem chama (source=mcp). Serve a visao
    do time (LAB-9), inclusive na tela, onde o Authentik so traz o e-mail."""

    __tablename__ = "org_people"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    area: Mapped[str | None] = mapped_column(String(120))
    manager_email: Mapped[str | None] = mapped_column(String(255), index=True)
    c_level: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    source: Mapped[str] = mapped_column(String(10), default="mcp")  # office | mcp
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
