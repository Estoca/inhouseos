"""Tracker tools: catalog and dispatch, from estoca-project-tracker 0.16.2 (app/internal_mcp.py).

In iho-server the tools are served by the server's own /mcp endpoint (iho.tracker.service), with the
caller from the server login. The HTTP routes, the actor JWT check and tracker_snapshot_link (only
the old local views used it) stay out.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from iho.tracker.auth import Identity
from iho.tracker.routers import actions, adoption, decisions, digest, events, people, projects, suggestions, team
from iho.tracker.schemas import (
    AbsenceIn,
    ActionClose,
    ActionIn,
    ActionPatch,
    ActionReopen,
    DecisionDecide,
    DecisionIn,
    DecisionPatch,
    DecisionReopen,
    EventIn,
    PersonOut,
    PersonPatch,
    ProjectIn,
    ProjectPatch,
    ProjectUpdateIn,
    SuggestionIn,
    SuggestionOutcome,
)

logger = logging.getLogger(__name__)


class ProviderError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(status_code, {"code": code, "message": message})


# ---------------------------------------------------------------- catalog
def _schema(model: type[BaseModel] | None, extra: dict[str, Any] | None = None,
            required: tuple[str, ...] = ()) -> dict[str, Any]:
    """`required`: campos de `extra` que o dispatch exige (ids, slug). Entram em `required`
    do schema para o cliente saber antes de chamar; o dispatch continua validando."""
    if model is None:
        base: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}
    else:
        base = model.model_json_schema()
        base.pop("$defs", None)
        base.pop("title", None)
        base["additionalProperties"] = False
    if extra:
        base["properties"] = {**base.get("properties", {}), **extra}
    if required:
        base["required"] = [*required, *(r for r in base.get("required", []) if r not in required)]
    return base


def _tool(name: str, description: str, schema: dict[str, Any], *, read_only: bool) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": schema,
        "annotations": {"readOnlyHint": read_only, "destructiveHint": False},
    }


DATE = {"type": "string", "format": "date", "description": "YYYY-MM-DD"}
OPT_STR = {"type": "string"}
CATALOG: list[dict[str, Any]] = [
    _tool("tracker_digest", "Tudo que o abrir-pacote precisa para uma pessoa: vencidos, compromissos, espera de terceiro (waiting_external, fora do SLA), decisoes, sinais, "
          "e moved_away: acoes reatribuidas para outra pessoa desde `since` (so informar, nunca cobrar). "
          "assigned_to_me: abertas por outra pessoa para voce desde `since` (confirmar, ou fechar como not_mine se nao reconhece); "
          "bounced: as que voce abriu e quem devia fechou como not_mine desde `since`. "
          "project_updates_due: projetos de que a pessoa e dona com update a fazer (state due) ou atrasado (late), "
          "com prazo e ultimo update: entra na fila do dia; ofereca montar o rascunho e postar com tracker_post_project_update.",
          _schema(None, {"person": {**OPT_STR, "description": "e-mail; default: quem chama (lideranca pode ver reportes)"}, "as_of": DATE,
                         "since": {"type": "string", "format": "date-time", "description": "inicio da janela do moved_away (horario do ultimo bomdia); default: 24h antes"}}), read_only=True),
    _tool("tracker_list_actions", "Lista pendencias visiveis para quem chama. Cada uma traz `notes`: as ultimas notas de andamento (entrega parcial, contexto). "
          "Antes de cobrar, fechar ou perguntar sobre uma pendencia, leia `notes` e, se a pessoa tem second brain, o wiki/daily e o wiki/weekly mais recentes: o titulo pode estar atrasado. formerly=me lista as que ja tiveram voce como requester/waiting_on e nao tem mais, com o dono atual (consulta).",
          _schema(None, {"waiting_on": OPT_STR, "requester": OPT_STR, "project": OPT_STR, "status": {"type": "string", "enum": ["open", "done", "wontfix", "moved", "duplicate", "not_mine", "all"]}, "overdue": {"type": "boolean"}, "as_of": DATE,
                         "formerly": {**OPT_STR, "description": "me ou e-mail (de outra pessoa so lideranca)"}}), read_only=True),
    _tool("tracker_create_action", "Abre uma pendencia (loop) ou compromisso. waiting_on_email e UMA pessoa da empresa, dona do acompanhamento. "
          "Se a espera e de terceiro (fornecedor, cliente, plataforma), preencha waiting_external (e review_at): o item sai do SLA. "
          "Prazo de entrega combinado (\"ate sexta\") vai em due_at, nao no titulo: com prazo, o item so vence depois dele. "
          "So abra com pedido explicito e destinatario claro; conversa resolvida na hora nao vira pendencia. "
          "Se ja existe pendencia aberta parecida para a mesma pessoa, nada e gravado e o erro lista as parecidas: "
          "use a existente, ou repita com allow_duplicate=true se for outro pedido.", _schema(ActionIn), read_only=False),
    _tool("tracker_update_action", "Edita uma pendencia aberta no lugar (id preservado): reatribuir, mudar sev, titulo, fonte ou projeto. "
          "Reatribuir e sempre update, nunca close+create. So os campos enviados mudam. "
          "waiting_external marca espera de terceiro (sem SLA); null volta a espera interna com SLA contando de hoje. "
          "due_at muda o prazo de entrega; null tira o prazo e volta ao SLA da sev. "
          "project (slug) troca ou inclui a pendencia num projeto; null tira do projeto. Mudar de projeto e update, nunca close+create.",
          _schema(ActionPatch, {"action_id": {"type": "integer"}}, required=("action_id",)), read_only=False),
    _tool("tracker_bump_action", "Registra que a pendencia foi cobrada hoje.", _schema(None, {"action_id": {"type": "integer"}}, required=("action_id",)), read_only=False),
    _tool("tracker_close_action", "Fecha uma pendencia com evidencia (link ou citacao da resposta). "
          "Evidencia que cobre so parte da pendencia nao fecha: troque o titulo para o que falta (tracker_update_action) e registre a parte entregue com tracker_record_event kind=note. "
          "Passe sempre expect_title_contains com um trecho distintivo do titulo: se o id nao for aquele item, nada e gravado e o erro mostra o titulo real. "
          "status duplicate (com duplicate_of = a que fica) para o mesmo pedido registrado duas vezes, nunca moved nem wontfix. "
          "status not_mine: so a propria pessoa que deve, quando nao reconhece a pendencia; volta para quem pediu (bounced no digest dela).",
          _schema(ActionClose, {"action_id": {"type": "integer"}}, required=("action_id",)), read_only=False),
    _tool("tracker_reopen_action", "Reabre uma pendencia fechada (por engano ou que voltou). O fechamento anterior e o motivo ficam no historico.",
          _schema(ActionReopen, {"action_id": {"type": "integer"}}, required=("action_id",)), read_only=False),
    _tool("tracker_list_decisions", "Lista decisoes pendentes visiveis para quem chama.",
          _schema(None, {"decider": OPT_STR, "project": OPT_STR, "status": {"type": "string", "enum": ["open", "decided", "dropped", "all"]}, "as_of": DATE}), read_only=True),
    _tool("tracker_create_decision", "Registra uma decisao pendente com quem decide e prazo.", _schema(DecisionIn), read_only=False),
    _tool("tracker_update_decision", "Edita uma decisao aberta no lugar (id preservado): quem decide, quem pediu, prazo, prioridade, pergunta, visibilidade, projeto. "
          "So os campos enviados mudam; deadline null tira o prazo; project (slug) troca ou inclui no projeto, null tira.",
          _schema(DecisionPatch, {"decision_id": {"type": "integer"}}, required=("decision_id",)), read_only=False),
    _tool("tracker_decide", "Registra a decisao tomada (ou descartada). "
          "Passe sempre expect_question_contains com um trecho distintivo da pergunta: se o id nao for aquela decisao, nada e gravado e o erro mostra a pergunta real.",
          _schema(DecisionDecide, {"decision_id": {"type": "integer"}}, required=("decision_id",)), read_only=False),
    _tool("tracker_reopen_decision", "Desfaz uma decisao registrada (decidida no id errado, ou que voltou a ficar em aberto): volta a pendente. "
          "O desfecho anterior e o motivo ficam no historico. Use em vez de recriar a decisao.",
          _schema(DecisionReopen, {"decision_id": {"type": "integer"}}, required=("decision_id",)), read_only=False),
    _tool("tracker_list_projects", "Lista projetos, donos e membros.", _schema(None, {"status": OPT_STR}), read_only=True),
    _tool("tracker_create_project", "Cria um projeto (slug igual ao do company brain e do Compass). Prioridade so C-level ou admin. "
          "Todo projeto nasce com update semanal, sexta 18:00 (America/Sao_Paulo); mude update_frequency/update_weekday/update_time "
          "no kickoff, ou update_frequency null para nao cobrar update. kickoff_ref e o link da pagina do projeto no company brain.",
          _schema(ProjectIn), read_only=False),
    _tool("tracker_update_project", "Atualiza nome, dono, status, prioridade (so C-level ou admin), kickoff (kickoff_ref, started_at, target_end_at) "
          "ou cadencia de update (update_frequency weekly|biweekly|monthly ou null, update_weekday seg..dom, update_time HH:MM). "
          "Cadencia nova vale a partir de agora: ciclo anterior nao vira atraso.",
          _schema(ProjectPatch, {"slug": {"type": "string"}}, required=("slug",)), read_only=False),
    _tool("tracker_post_project_update", "Registra o update do ciclo de um projeto: farol (on_track, at_risk, blocked, done), o que mudou de material, "
          "ajuda/decisao que precisa da lideranca, foco ate o proximo e termino previsto se mudou. Dono, membro, lideranca ou admin. "
          "So poste depois que o dono confirmou o texto. Append-only: para corrigir, poste outro. "
          "posted_at, author_email e source=notion sao para importacao (admin ou C-level).",
          _schema(ProjectUpdateIn, {"slug": {"type": "string"}}, required=("slug",)), read_only=False),
    _tool("tracker_list_project_updates", "Historico de updates de um projeto, mais novo primeiro.",
          _schema(None, {"slug": {"type": "string"}, "limit": {"type": "integer", "minimum": 1, "maximum": 200, "description": "padrao 10"},
                         "since": {"type": "string", "format": "date-time"}}, required=("slug",)), read_only=True),
    _tool("tracker_project_report", "Report dos updates para a reuniao de projetos: cada projeto ativo com o estado do ciclo "
          "(ok, pending, due, late), o ultimo update, mudanca de farol e de termino, quem nao mandou (missing, late) e quem pede ajuda desde `since`.",
          _schema(None, {"as_of": {"type": "string", "format": "date-time", "description": "padrao agora"},
                         "since": {"type": "string", "format": "date-time", "description": "inicio da janela dos pedidos de ajuda; padrao 7 dias antes"},
                         "max_priority": {"type": "integer", "minimum": 1, "maximum": 3, "description": "1 = so P1; 2 = P1 e P2"},
                         "include_off": {"type": "boolean", "description": "inclui projetos sem cadencia"}}), read_only=True),
    _tool("tracker_add_project_member", "Adiciona uma pessoa a um projeto.", _schema(None, {"slug": {"type": "string"}, "email": {"type": "string", "format": "email"}}, required=("slug", "email")), read_only=False),
    _tool("tracker_remove_project_member", "Tira uma pessoa de um projeto (a propria pessoa, o dono, lideranca ou admin). O dono nao sai: troque o dono antes.", _schema(None, {"slug": {"type": "string"}, "email": {"type": "string", "format": "email"}}, required=("slug", "email")), read_only=False),
    _tool("tracker_record_event", "Registra evento da LLM: nudged, nudge_ignored, process_deviation, decision_kept_private, "
          "note (em acao: entity_type=action, entity_id, payload {text, evidence}; aparece em `notes` da pendencia para todo mundo que a ve), "
          "digest_missed_reason (entity_type=person, entity_id=id da pessoa, payload {day, reason}: por que o pacote nao foi aberto naquele dia).", _schema(EventIn), read_only=False),
    _tool("tracker_adoption", "Adocao do pacote do dia: em quantos dos seus dias uteis (menos ausencias) cada pessoa abriu o digest pelo MCP. "
          "Sem person: voce (e seus reportes, se lideranca; todo mundo, se C-level/admin). Meta em target (0.8). "
          "O mesmo numero aparece no digest da pessoa (adoption) e no quadro dela: ninguem ve o que ela nao ve.",
          _schema(None, {"person": {**OPT_STR, "description": "e-mail; default: quem chama (+ reportes)"}, "as_of": DATE,
                         "days": {"type": "integer", "minimum": 5, "maximum": 120, "description": "janela em dias uteis; default 20"}}), read_only=True),
    _tool("tracker_team_stuck", "Para quem lidera: ha quanto tempo cada pendencia aberta do time esta travada, para ajudar a destravar, nunca para cobrar. "
          "Cada item traz o lado da pessoa do time (side: deve | espera), age_days, faixa (band: ate_7, de_8_a_30, mais_30), "
          "days_without_bump, se esta vencida (overdue, overdue_reason: sla ou due_at) e quem destrava (unblocker = quem deve). "
          "Espera de terceiro vem a parte em `external` e nao conta como travado. `people` traz os totais por pessoa em ordem alfabetica: "
          "nao ordene nem apresente como ranking. scope: arvore (padrao, todo mundo abaixo do gestor) ou direto. "
          "gestor: outro gestor abaixo de voce (C-level/admin: qualquer um); all=true: todo mundo (so C-level/admin). "
          "O digest de quem lidera ja traz o resumo em team_stuck.",
          _schema(None, {"gestor": {**OPT_STR, "description": "e-mail do gestor; default: quem chama"},
                         "scope": {"type": "string", "enum": ["arvore", "direto"]},
                         "all": {"type": "boolean", "description": "todo mundo (so C-level/admin)"},
                         "as_of": DATE,
                         "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "description": "itens travados; padrao 50"}}), read_only=True),
    _tool("tracker_add_absence", "Registra ferias, folga ou licenca (dias uteis de start a end saem da conta de adocao). "
          "A propria pessoa, a lideranca dela ou C-level/admin.",
          _schema(AbsenceIn), read_only=False),
    _tool("tracker_update_person", "Desativa ou reativa uma pessoa (active=false: saiu da empresa) e tira ou poe na meta do "
          "pacote do dia (adoption_exempt: ex. supervisor de operacao). Inativo ou isento sai do tracker_adoption e nao "
          "recebe o sinal de adocao no digest; acoes e historico ficam. So admin.",
          _schema(PersonPatch, {"email": {"type": "string", "description": "e-mail da pessoa"}}, required=("email",)), read_only=False),
    _tool("tracker_create_suggestion", "Registra o que a LLM sugeriu a uma pessoa e por qual regra do Compass. "
          "Use o kind especifico (pre_read, external_review, adoption, pr, confirm_assignment...); other so quando nenhum cabe. "
          "Com entity_type action ou decision, o desfecho de nudge, close, confirm_assignment, external_review e decide e "
          "inferido pelos eventos da propria pessoa na entidade (cobrou, fechou, editou). Sem evento nem resposta em 2 dias "
          "uteis, vira ignored (expirada).", _schema(SuggestionIn), read_only=False),
    _tool("tracker_suggestion_outcome", "Registra o desfecho de uma sugestao: followed, deviated ou ignored. Pode corrigir um desfecho inferido.", _schema(SuggestionOutcome, {"suggestion_id": {"type": "integer"}}, required=("suggestion_id",)), read_only=False),
    _tool("tracker_metrics", "Eficacia: adesao por tipo e pessoa, cruzada com resultado. expired = ignored sem evento nem resposta; inferred = desfecho tirado dos eventos.",
          _schema(None, {"person": OPT_STR, "project": OPT_STR, "since": {"type": "string", "format": "date-time"}}), read_only=True),
]


# ---------------------------------------------------------------- execute
def _date(v: Any) -> date | None:
    return date.fromisoformat(v) if isinstance(v, str) and v else None


def _dt(v: Any) -> datetime | None:
    return datetime.fromisoformat(v) if isinstance(v, str) and v else None


def _model(cls: type[BaseModel], args: dict[str, Any], drop: tuple[str, ...] = ()) -> BaseModel:
    try:
        return cls.model_validate({k: v for k, v in args.items() if k not in drop})
    except ValidationError as exc:
        raise ProviderError(400, "invalid_arguments", str(exc.errors()[0].get("msg", "argumentos invalidos"))) from exc


def _int(args: dict[str, Any], key: str) -> int:
    # Cliente com o schema da tool sem tipos manda o id como texto ("53"): aceita so digitos.
    v = args.get(key)
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v.strip())
    if not isinstance(v, int) or isinstance(v, bool):
        raise ProviderError(400, "invalid_arguments", f"{key} e obrigatorio e inteiro")
    return v


def _slug(args: dict[str, Any]) -> str:
    slug = args.get("slug")
    if not isinstance(slug, str) or not slug:
        raise ProviderError(400, "invalid_arguments", "slug e obrigatorio")
    return slug


def _dump(obj: Any) -> Any:
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, list):
        return [_dump(o) for o in obj]
    return obj


def _dispatch(name: str, a: dict[str, Any], db: Session, ident: Identity) -> Any:
    if name == "tracker_digest":
        return digest.digest(person=a.get("person"), as_of=_date(a.get("as_of")), since=_dt(a.get("since")), db=db, ident=ident)
    if name == "tracker_list_actions":
        return actions.list_actions(waiting_on=a.get("waiting_on"), requester=a.get("requester"), project=a.get("project"),
                                    status_=a.get("status", "open"), overdue=bool(a.get("overdue", False)),
                                    as_of=_date(a.get("as_of")), formerly=a.get("formerly"), db=db, ident=ident)
    if name == "tracker_create_action":
        return actions.create_action(_model(ActionIn, a), db=db, ident=ident)
    if name == "tracker_update_action":
        return actions.update_action(_int(a, "action_id"), _model(ActionPatch, a, drop=("action_id",)), db=db, ident=ident)
    if name == "tracker_bump_action":
        return actions.bump(_int(a, "action_id"), db=db, ident=ident)
    if name == "tracker_close_action":
        return actions.close(_int(a, "action_id"), _model(ActionClose, a, drop=("action_id",)), db=db, ident=ident)
    if name == "tracker_reopen_action":
        return actions.reopen(_int(a, "action_id"), _model(ActionReopen, a, drop=("action_id",)), db=db, ident=ident)
    if name == "tracker_list_decisions":
        return decisions.list_decisions(decider=a.get("decider"), project=a.get("project"), status_=a.get("status", "open"),
                                        as_of=_date(a.get("as_of")), db=db, ident=ident)
    if name == "tracker_create_decision":
        return decisions.create_decision(_model(DecisionIn, a), db=db, ident=ident)
    if name == "tracker_update_decision":
        return decisions.update_decision(_int(a, "decision_id"), _model(DecisionPatch, a, drop=("decision_id",)), db=db, ident=ident)
    if name == "tracker_decide":
        return decisions.decide(_int(a, "decision_id"), _model(DecisionDecide, a, drop=("decision_id",)), db=db, ident=ident)
    if name == "tracker_reopen_decision":
        return decisions.reopen(_int(a, "decision_id"), _model(DecisionReopen, a, drop=("decision_id",)), db=db, ident=ident)
    if name == "tracker_list_projects":
        return projects.list_projects(status_=a.get("status"), db=db, _=ident)
    if name == "tracker_create_project":
        return projects.create_project(_model(ProjectIn, a), db=db, ident=ident)
    if name == "tracker_update_project":
        slug = a.get("slug")
        if not isinstance(slug, str) or not slug:
            raise ProviderError(400, "invalid_arguments", "slug e obrigatorio")
        return projects.patch_project(slug, _model(ProjectPatch, a, drop=("slug",)), db=db, ident=ident)
    if name == "tracker_post_project_update":
        return projects.post_update(_slug(a), _model(ProjectUpdateIn, a, drop=("slug",)), db=db, ident=ident)
    if name == "tracker_list_project_updates":
        limit = a.get("limit", 10)
        if isinstance(limit, str) and limit.strip().isdigit():
            limit = int(limit)
        return projects.list_updates(_slug(a), limit=limit if isinstance(limit, int) else 10, since=_dt(a.get("since")), db=db, _=ident)
    if name == "tracker_project_report":
        mp = a.get("max_priority")
        mp = int(mp) if isinstance(mp, str) and mp.isdigit() else mp
        return projects.build_report(db, _dt(a.get("as_of")), _dt(a.get("since")), mp if isinstance(mp, int) else None,
                                     bool(a.get("include_off", False)))
    if name == "tracker_add_project_member":
        slug, email = a.get("slug"), a.get("email")
        if not isinstance(slug, str) or not isinstance(email, str) or "@" not in email:
            raise ProviderError(400, "invalid_arguments", "slug e email sao obrigatorios")
        return projects.add_member(slug, email, db=db, ident=ident)
    if name == "tracker_remove_project_member":
        slug, email = a.get("slug"), a.get("email")
        if not isinstance(slug, str) or not isinstance(email, str) or "@" not in email:
            raise ProviderError(400, "invalid_arguments", "slug e email sao obrigatorios")
        return projects.remove_member(slug, email, db=db, ident=ident)
    if name == "tracker_record_event":
        return events.create_event(_model(EventIn, a), db=db, ident=ident)
    if name == "tracker_create_suggestion":
        return suggestions.create_suggestion(_model(SuggestionIn, a), db=db, ident=ident)
    if name == "tracker_suggestion_outcome":
        return suggestions.set_outcome(_int(a, "suggestion_id"), _model(SuggestionOutcome, a, drop=("suggestion_id",)), db=db, ident=ident)
    if name == "tracker_metrics":
        return suggestions.metrics(person=a.get("person"), project=a.get("project"), since=_dt(a.get("since")), db=db, ident=ident)
    if name == "tracker_adoption":
        return adoption.get_adoption(person=a.get("person"), as_of=_date(a.get("as_of")), days=a.get("days"), db=db, ident=ident)
    if name == "tracker_team_stuck":
        limit = a.get("limit", 50)
        limit = int(limit) if isinstance(limit, str) and limit.strip().isdigit() else limit
        scope = a.get("scope") or "arvore"
        if scope not in ("arvore", "direto"):
            raise ProviderError(400, "invalid_arguments", "scope e arvore ou direto")
        return team.build(db, ident, a.get("gestor"), scope, a.get("all") in (True, "true", "1"), _date(a.get("as_of")),
                          max(1, min(limit, 1000)) if isinstance(limit, int) and not isinstance(limit, bool) else 50)
    if name == "tracker_add_absence":
        return adoption.add_absence(_model(AbsenceIn, a), db=db, ident=ident)
    if name == "tracker_update_person":
        email = a.get("email")
        if not isinstance(email, str) or "@" not in email:
            raise ProviderError(400, "invalid_arguments", "email e obrigatorio")
        return PersonOut.model_validate(people.patch_person(email, _model(PersonPatch, a, drop=("email",)), db=db, ident=ident))
    raise ProviderError(404, "tool_not_found", "A ferramenta solicitada nao esta disponivel.")
