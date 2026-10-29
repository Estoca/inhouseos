from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

from iho.tracker.names import clean_person_name


class PersonOut(BaseModel):
    id: int
    email: str
    name: str | None = None
    slack_handle: str | None = None
    active: bool = True
    adoption_exempt: bool = False

    model_config = {"from_attributes": True}

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str | None) -> str | None:
        return clean_person_name(v)


class PersonPatch(BaseModel):
    name: str | None = None
    slack_handle: str | None = None
    active: bool | None = None
    adoption_exempt: bool | None = None


class MeOut(BaseModel):
    person: PersonOut
    via: str
    roles: list[str]
    is_admin: bool
    sees_everything: bool


WEEKDAY = r"^(seg|ter|qua|qui|sex|sab|dom)$"
HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
FREQUENCY = r"^(weekly|biweekly|monthly)$"
FAROL = r"^(on_track|at_risk|blocked|done)$"


class ProjectCadence(BaseModel):
    """Kickoff e cadencia de update. Frequencia exige dia; hora padrao 18:00 (America/Sao_Paulo)."""
    kickoff_ref: str | None = Field(default=None, description="link da pagina do projeto na Estoca brain (kickoff)")
    objective: str | None = Field(default=None, description="objetivo em 1 ou 2 linhas: o que muda quando o projeto acabar")
    goals: list[str] | None = Field(default=None, description="metas impactadas, ex.: Receita, Custo/Margem, Retencao, EBITDA")
    expected_results: str | None = Field(default=None, description="resultados esperados, curtos e mensuraveis")
    area: str | None = Field(default=None, max_length=60, description="area responsavel")
    radar_plan_ids: list[str] | None = Field(default=None, description="ids dos planos do Radar ligados ao projeto (ex.: PLANO-049-54D1); o update do projeto vira FUP neles")
    started_at: date | None = None
    target_end_at: date | None = Field(default=None, description="termino previsto")
    update_frequency: str | None = Field(default=None, pattern=FREQUENCY,
                                         description="weekly, biweekly (a cada 2 semanas) ou monthly (primeiro dia da semana escolhido no mes); null = sem update cobrado")
    update_weekday: str | None = Field(default=None, pattern=WEEKDAY, description="dia limite do update: seg, ter, qua, qui, sex, sab ou dom")
    update_time: str | None = Field(default=None, pattern=HHMM, description="hora limite HH:MM em America/Sao_Paulo; padrao 18:00")


class ProjectIn(ProjectCadence):
    """Projeto novo nasce com update semanal, sexta 18:00. update_frequency null: sem update cobrado."""
    update_frequency: str | None = Field(default="weekly", pattern=FREQUENCY,
                                         description="padrao weekly; biweekly, monthly, ou null para nao cobrar update")
    update_weekday: str | None = Field(default="sex", pattern=WEEKDAY, description="dia limite do update; padrao sex")
    update_time: str | None = Field(default="18:00", pattern=HHMM, description="hora limite HH:MM em America/Sao_Paulo; padrao 18:00")
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    owner_email: EmailStr | None = None
    priority: int = Field(default=2, ge=1, le=3)
    status: str = "active"
    members: list[EmailStr] = []


class ProjectPatch(ProjectCadence):
    name: str | None = None
    owner_email: EmailStr | None = None
    priority: int | None = Field(default=None, ge=1, le=3)
    status: str | None = None


class ProjectUpdateIn(BaseModel):
    farol: str = Field(pattern=FAROL, description="on_track (dentro do prazo), at_risk (em risco), blocked (travado/comprometido), done (concluido)")
    summary: str = Field(min_length=1, description="o que mudou de material desde o ultimo update")
    help_needed: str | None = Field(default=None, description="decisao ou ajuda que precisa da lideranca; vazio se nada")
    next_focus: str | None = Field(default=None, description="foco ate o proximo update")
    target_end_at: date | None = Field(default=None, description="termino previsto, se mudou; atualiza o do projeto")
    source: str = Field(default="agent", pattern=r"^(agent|manual|notion)$",
                        description="agent: rascunho do agente confirmado pelo dono; manual: escrito pela pessoa; notion: importado")
    source_ref: str | None = None
    # importacao (so admin ou C-level): data original e autor do update
    posted_at: datetime | None = None
    author_email: EmailStr | None = None


class ProjectUpdateOut(BaseModel):
    id: int
    project: str
    author: PersonOut
    posted_at: datetime
    farol: str
    summary: str
    help_needed: str | None = None
    next_focus: str | None = None
    target_end_at: date | None = None
    source: str
    source_ref: str | None = None


class UpdateStatusOut(BaseModel):
    """Onde o projeto esta no ciclo de update. state: off (sem cadencia ou projeto nao ativo),
    ok (update do ciclo feito), pending (falta, mas ainda nao e hora de lembrar), due (falta e
    ja e hora de lembrar o dono), late (o prazo do ciclo anterior passou sem update)."""
    state: str
    due_at: datetime | None = None  # prazo do ciclo atual
    remind_from: datetime | None = None  # a partir de quando o dono e lembrado
    late_since: datetime | None = None  # prazo perdido mais antigo sem update depois
    cycles_missed: int = 0
    hours_left: float | None = None  # ate due_at; negativo quando late (desde late_since)
    last_update_at: datetime | None = None
    last_farol: str | None = None


class ProjectOut(BaseModel):
    id: int
    slug: str
    name: str
    owner: PersonOut | None = None
    priority: int
    status: str
    members: list[PersonOut] = []
    updated_at: datetime
    kickoff_ref: str | None = None
    objective: str | None = None
    goals: list[str] | None = None
    expected_results: str | None = None
    area: str | None = None
    radar_plan_ids: list[str] | None = None
    started_at: date | None = None
    target_end_at: date | None = None
    update_frequency: str | None = None
    update_weekday: str | None = None
    update_time: str | None = None
    update_status: UpdateStatusOut | None = None


class ProjectUpdateDueOut(BaseModel):
    """Projeto do qual a pessoa e dona com update a fazer (digest)."""
    slug: str
    name: str
    priority: int
    update_frequency: str
    status: UpdateStatusOut
    last_update: ProjectUpdateOut | None = None


class ProjectReportItem(BaseModel):
    slug: str
    name: str
    priority: int
    owner: PersonOut | None = None
    target_end_at: date | None = None
    update_frequency: str | None = None
    status: UpdateStatusOut
    latest: ProjectUpdateOut | None = None  # ultimo update ate as_of
    previous_farol: str | None = None  # farol do update anterior ao ultimo
    farol_changed: bool = False
    end_moved: bool = False  # termino previsto mudou em relacao ao update anterior


class ProjectReportOut(BaseModel):
    as_of: datetime
    since: datetime  # updates desde (janela do report)
    projects: list[ProjectReportItem]
    missing: list[str]  # slugs sem update no ciclo (due ou late), prioridade primeiro
    late: list[str]
    help_needed: list[ProjectReportItem]  # updates da janela pedindo ajuda/decisao
    counts: dict[str, int]


class ActionIn(BaseModel):
    type: str = Field(default="loop", pattern=r"^(loop|commitment)$")
    project: str | None = None  # slug
    requester_email: EmailStr | None = None  # default: quem chama
    waiting_on_email: EmailStr
    title: str
    source: str | None = None
    source_ref: str | None = None
    asked_at: date | None = None
    sev: int = Field(default=2, ge=1, le=3)
    waiting_external: str | None = Field(default=None, description="de quem de fora se espera (fornecedor, cliente, plataforma); tira o item do SLA")
    review_at: date | None = Field(default=None, description="quando reavaliar a espera de terceiro; so com waiting_external")
    due_at: date | None = Field(default=None, description="prazo de entrega combinado (YYYY-MM-DD). Com prazo, o item so vence depois dele, nao pelo SLA da sev")
    allow_duplicate: bool = Field(default=False, description="true cria mesmo com pendencia aberta parecida para a mesma pessoa. "
                                  "So depois de conferir que e outro pedido: sem isso, a parecida volta como conflito e nada e gravado")


class ActionPatch(BaseModel):
    """So os campos enviados mudam; o id nunca muda. Reatribuir e update, nunca close+create.
    null so e aceito nos campos opcionais (project, source, source_ref, waiting_external, review_at, due_at)."""

    project: str | None = Field(default=None, description="slug do projeto: troca ou inclui a pendencia no projeto; null tira do projeto")
    waiting_on_email: EmailStr | None = None
    requester_email: EmailStr | None = None
    sev: int | None = Field(default=None, ge=1, le=3)
    title: str | None = Field(default=None, min_length=1)
    source: str | None = None
    source_ref: str | None = None
    waiting_external: str | None = Field(default=None, description="preencher tira do SLA; null ou vazio volta a espera interna com SLA desde hoje")
    review_at: date | None = None
    due_at: date | None = Field(default=None, description="prazo de entrega combinado; null tira o prazo e volta ao SLA da sev")


class ActionClose(BaseModel):
    evidence: str = Field(min_length=3, description="URL ou citacao da resposta que fecha")
    status: str = Field(default="done", pattern=r"^(done|wontfix|moved|duplicate|not_mine)$",
                        description="done feito; wontfix desistiu; moved virou issue ou outra coisa; duplicate e o mesmo pedido de "
                        "outra acao (duplicate_of obrigatorio); not_mine: quem deve nao reconhece a pendencia (so a propria pessoa); "
                        "volta para quem pediu")
    duplicate_of: int | None = Field(default=None, description="id da acao que fica, quando status=duplicate")
    expect_title_contains: str | None = Field(
        default=None,
        description="trecho distintivo do titulo que voce espera fechar; se o titulo da acao nao contem (sem caixa nem acento), nada e gravado",
    )


class ActionReopen(BaseModel):
    reason: str | None = Field(default=None, description="por que reabrir; fica no evento reopened")


class NoteOut(BaseModel):
    """Nota de andamento (evento `note` da acao): entrega parcial, contexto que o titulo ainda nao tem."""

    at: datetime
    by: str | None = None  # e-mail de quem registrou
    text: str | None = None
    evidence: str | None = None
    payload: dict = {}


class ActionOut(BaseModel):
    id: int
    url: str  # link permanente na interface: {PUBLIC_BASE_URL}/ol/{id}
    type: str
    project: str | None = None
    requester: PersonOut
    waiting_on: PersonOut
    title: str
    source: str | None
    source_ref: str | None
    asked_at: date
    last_bump_at: date
    sev: int
    status: str
    closed_at: datetime | None
    closed_evidence: str | None
    age_days: int
    overdue_by: int  # dias alem do prazo (due_at) ou do SLA desde o ultimo bump; <=0 dentro; 0 se espera de terceiro
    due_at: date | None = None  # prazo de entrega combinado
    days_to_due: int | None = None  # due_at - hoje; negativo = prazo passou
    waiting_external: str | None = None
    review_at: date | None = None
    review_due: bool = False  # review_at <= hoje: hora de reavaliar a espera de terceiro
    notes: list[NoteOut] = []  # ultimas notas (evento `note`), da mais nova para a mais antiga
    registered_on: date | None = None  # dia em que entrou no tracker; o SLA sem prazo conta daqui ou do ultimo bump
    duplicate_of: int | None = None  # status=duplicate: a acao que fica


class DecisionIn(BaseModel):
    project: str | None = None
    question: str
    decider_email: EmailStr
    requester_email: EmailStr | None = None
    opened_at: date | None = None
    deadline: date | None = None
    priority: str = Field(default="media", pattern=r"^(alta|media|baixa)$")
    visibility: str = Field(default="project", pattern=r"^(project|leadership|private)$")


class DecisionPatch(BaseModel):
    """So os campos enviados mudam; o id nunca muda. deadline e project aceitam null (tira o prazo, tira do projeto)."""

    project: str | None = Field(default=None, description="slug do projeto: troca ou inclui a decisao no projeto; null tira do projeto")
    decider_email: EmailStr | None = None
    requester_email: EmailStr | None = None
    deadline: date | None = None
    priority: str | None = Field(default=None, pattern=r"^(alta|media|baixa)$")
    question: str | None = Field(default=None, min_length=1)
    visibility: str | None = Field(default=None, pattern=r"^(project|leadership|private)$")


class DecisionDecide(BaseModel):
    outcome: str = Field(min_length=3)
    status: str = Field(default="decided", pattern=r"^(decided|dropped)$")
    expect_question_contains: str | None = Field(
        default=None,
        description="trecho distintivo da pergunta que voce espera decidir; se a pergunta nao contem (sem caixa nem acento), nada e gravado",
    )


class DecisionReopen(BaseModel):
    reason: str = Field(min_length=3, description="por que reabrir (ex.: decidida no id errado); fica no evento reopened com o desfecho anterior")


class DecisionOut(BaseModel):
    id: int
    url: str  # link permanente na interface: {PUBLIC_BASE_URL}/d/{id}
    project: str | None
    question: str
    decider: PersonOut
    requester: PersonOut
    opened_at: date
    deadline: date | None
    priority: str
    status: str
    decided_at: datetime | None
    outcome: str | None
    visibility: str
    days_to_deadline: int | None


class EventIn(BaseModel):
    """Eventos que a LLM registra por fora do fluxo normal."""

    entity_type: str = Field(pattern=r"^(action|decision|project|person|suggestion)$")
    entity_id: int | None = None
    kind: str = Field(pattern=r"^(nudged|nudge_ignored|process_deviation|decision_kept_private|note|digest_missed_reason)$")
    # digest_missed_reason: entity_type=person, entity_id=id da pessoa, payload {day: AAAA-MM-DD, reason}
    # note em acao: payload {text, evidence}; volta em `notes` da acao (list, digest, snapshot)
    payload: dict | None = None


class EventOut(BaseModel):
    id: int
    at: datetime
    actor: PersonOut | None
    entity_type: str
    entity_id: int | None
    kind: str
    payload: dict | None


class MovedAwayOut(BaseModel):
    """Acao que saiu do radar da pessoa: ela deixou de ser requester/waiting_on. So informa;
    nao e pendencia dela, por isso nao traz sev, SLA nem overdue."""

    id: int
    url: str
    title: str
    project: str | None
    lost_roles: list[str]  # requester | waiting_on: o papel que a pessoa tinha
    requester: PersonOut  # dono atual
    waiting_on: PersonOut  # dono atual
    changed_by: PersonOut | None
    changed_at: datetime


class TeamMemberOut(BaseModel):
    email: str
    name: str | None = None


class TeamItemOut(BaseModel):
    """Pendencia aberta de alguem do time, vista por quem lidera (0.16.0, LAB-9). Sem notas,
    fonte nem evidencia: o titulo (neutro para item sensivel, pelo protocolo) basta para ajudar."""

    id: int
    url: str
    title: str
    type: str
    sev: int
    project: str | None = None
    side: str  # deve (waiting_on e do time) | espera (requester e do time e espera alguem de fora dele)
    member: PersonOut  # quem do time
    via: TeamMemberOut | None = None  # reporte direto do gestor por onde a pessoa entra (ela mesma, se direta)
    requester: PersonOut
    waiting_on: PersonOut
    unblocker: PersonOut  # quem destrava: quem deve (waiting_on)
    unblocker_in_team: bool
    both_in_team: bool = False  # quem pede e quem deve sao do time
    self_note: bool = False  # a pessoa anotou para si (requester = waiting_on)
    asked_at: date
    age_days: int
    band: str  # ate_7 | de_8_a_30 | mais_30 (pela idade)
    last_bump_at: date
    bumped: bool  # ja foi cobrada alguma vez
    days_without_bump: int  # desde a ultima cobranca, ou desde o pedido se nunca cobrada
    overdue: bool
    overdue_by: int
    overdue_reason: str | None = None  # due_at | sla
    due_at: date | None = None
    waiting_external: str | None = None
    review_at: date | None = None
    review_due: bool = False


class TeamBandsOut(BaseModel):
    ate_7: int = 0
    de_8_a_30: int = 0
    mais_30: int = 0


class TeamCountsOut(BaseModel):
    open: int = 0  # abertas sem espera de terceiro (cada pendencia uma vez)
    owes: int = 0  # alguem do time deve
    waits: int = 0  # alguem do time espera de outra pessoa
    overdue: int = 0
    self_notes: int = 0
    bands: TeamBandsOut = TeamBandsOut()
    external: int = 0  # espera de terceiro: a parte, nao conta como travado


class TeamPersonOut(BaseModel):
    person: TeamMemberOut
    direct: bool  # reporte direto do gestor
    via: TeamMemberOut | None = None
    counts: TeamCountsOut


class OrgInfoOut(BaseModel):
    source: str | None = None  # office | mcp | None (sem organograma)
    synced_at: datetime | None = None
    last_error: str | None = None  # ultimo sync do escritorio que falhou (HTTP 403, URLError...)


class TeamStuckOut(BaseModel):
    gestor: TeamMemberOut | None = None  # None com all=true
    scope: str  # direto | arvore | todos
    as_of: date
    org: OrgInfoOut
    members: int
    totals: TeamCountsOut
    items: list[TeamItemOut]  # vencidas primeiro, depois a mais velha
    items_total: int
    external: list[TeamItemOut]
    people: list[TeamPersonOut]  # ordem alfabetica, nunca por volume: nao e ranking
    gestores: list[TeamMemberOut] = []  # outros gestores que quem chama pode abrir
    can_see_all: bool = False  # quem chama pode pedir all=true (C-level, admin)
    url: str  # a mesma visao na tela


class TeamSummaryOut(BaseModel):
    """Bloco `team_stuck` do digest de quem lidera: a arvore inteira, totais e os mais travados."""

    scope: str
    members: int
    totals: TeamCountsOut
    top: list[TeamItemOut]
    items_total: int
    org: OrgInfoOut
    url: str


class DigestOut(BaseModel):
    person: PersonOut
    as_of: date
    overdue_waiting_on_me: list[ActionOut]
    overdue_i_am_waiting: list[ActionOut]
    my_commitments: list[ActionOut]
    waiting_external: list[ActionOut]  # espera de terceiro: fora do SLA e dos vencidos; idade e review_at visiveis
    decisions_i_own: list[DecisionOut]
    decisions_stuck: list[DecisionOut]
    signals: list[str]
    # saiu do radar (WMS-283): reatribuidas para outra pessoa dentro da janela
    # [moved_away_since, fim de as_of]. So informa, nunca e pendencia nem vencido.
    moved_away: list[MovedAwayOut] = []
    moved_away_since: datetime | None = None
    # adocao do pacote do dia da propria pessoa (app/adoption.py): o mesmo numero que a lideranca ve
    adoption: "AdoptionOut | None" = None
    # atribuidas a voce por outra pessoa na janela (since): confirmar ou fechar como not_mine
    assigned_to_me: list[ActionOut] = []
    # voltaram para voce na janela: quem devia fechou como not_mine (nao reconhece)
    bounced: list[ActionOut] = []
    # projetos de que voce e dono com update a fazer (due) ou atrasado (late), late primeiro
    project_updates_due: list[ProjectUpdateDueOut] = []
    # quem lidera (0.16.0): pendencias abertas do time inteiro, totais e as 5 mais travadas
    team_stuck: TeamSummaryOut | None = None


class SuggestionIn(BaseModel):
    person_email: EmailStr | None = None  # default: quem chama
    kind: str = Field(pattern=r"^(nudge|close|escalate|decide|create_issue|schedule_1on1|promote|pre_read|external_review|adoption|pr|confirm_assignment|other)$",
                      description="pre_read: pre-leitura de reuniao; external_review: reavaliar espera de terceiro; adoption: pacote do dia; "
                      "pr: o que um PR seu pede de voce; confirm_assignment: confirmar pendencia atribuida por outra pessoa; other: so o que nao cabe")
    entity_type: str | None = Field(default=None, pattern=r"^(action|decision|project|person)$")
    entity_id: int | None = None
    project: str | None = None
    text: str = Field(min_length=3)
    rule: str | None = None


class SuggestionOutcome(BaseModel):
    outcome: str = Field(pattern=r"^(followed|deviated|ignored)$")
    note: str | None = None


class SuggestionOut(BaseModel):
    id: int
    person: PersonOut
    kind: str
    entity_type: str | None
    entity_id: int | None
    project: str | None
    text: str
    rule: str | None
    made_at: datetime
    outcome: str
    outcome_at: datetime | None
    outcome_note: str | None


class MetricsBucket(BaseModel):
    total: int
    followed: int
    deviated: int
    ignored: int
    pending: int
    expired: int = 0  # dos ignored, quantos expiraram sem evento nem resposta (nao foram ignorados de fato)
    inferred: int = 0  # dos followed+deviated, quantos vieram dos eventos da propria pessoa (0.15.0)
    adherence: float | None  # followed / (followed+deviated+ignored)
    resolved_when_followed: int
    resolved_when_deviated: int
    avg_days_to_resolve_followed: float | None
    avg_days_to_resolve_deviated: float | None


class MetricsOut(BaseModel):
    since: datetime | None
    person: str | None
    project: str | None
    overall: MetricsBucket
    by_kind: dict[str, MetricsBucket]
    by_person: dict[str, MetricsBucket]
    reading: list[str]


class AdoptionOut(BaseModel):
    """Adocao do pacote do dia: dias uteis da janela (menos ausencias) x dias em que a LLM da
    pessoa abriu o digest pelo MCP. rate = opened_days / expected_days; meta = target."""

    person: PersonOut
    as_of: date
    window_start: date | None
    window_end: date | None
    business_days: int
    absences: int
    expected_days: int
    opened_days: int
    rate: float | None
    target: float
    on_track: bool
    enough_data: bool  # pelo menos 5 dias uteis esperados; antes disso nao se cobra
    first_open: date | None
    last_open: date | None
    missed: list[date]  # dias uteis sem pacote, mais recente primeiro (ate 10)
    reasons: list[dict]  # {day, reason} registrados pela LLM (digest_missed_reason)


class AbsenceIn(BaseModel):
    email: EmailStr | None = None  # default: quem chama
    start: date
    end: date | None = None
    reason: str | None = Field(default=None, max_length=120)


class AbsenceOut(BaseModel):
    id: int
    person: PersonOut
    day: date
    reason: str | None
