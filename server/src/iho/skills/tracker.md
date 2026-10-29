---
title: Protocolo do tracker compartilhado
---

# Tracker compartilhado

O tracker de {{company}} é a **única fonte** das ações e decisões de todo mundo. O second
brain não guarda cópia: toda leitura e toda escrita vão direto às ferramentas `tracker_*`
deste servidor, com e sem pasta local. Quem chama é identificado pelo login; toda escrita
fica atribuída a essa pessoa. Sem isso, a ação de uma pessoa fica presa no brain dela e o
agente de mais ninguém enxerga.

## Regras

- **Ação é compartilhada sempre.** Veem quem pediu, quem deve, membros do projeto e a
  liderança. Conteúdo sensível (1:1, RH, remuneração, saúde, vida pessoal) entra com título
  neutro, **mas único**: área, data do pedido e um número (`Pessoas: pendência de 08-10 (2 de 5)`).
  Cinco ações com o mesmo título neutro ninguém distingue, nem a checagem de duplicata.
- **Item citado leva título.** `OL-NNNN` (ação) e `D-NNNN` (decisão), sempre seguidos do
  título curto; nunca só o número. Com link quando o campo `url` do item for um endereço
  completo (`https://…`); sem isso, só o id e o título.
- **Só com pedido explícito e destinatário claro.** Abra pendência quando alguém pediu algo a
  uma pessoa nomeada (ou prometeu a alguém) e a resposta não veio. Não abra: conversa
  resolvida na hora, pedido difuso a um canal, item de plano ou planilha, pendência que você
  deduziu. Nunca ponha alguém como `waiting_on` sem que o pedido tenha sido feito a ele. Na
  dúvida, pergunte.
- **A mesma já existe?** O tracker recusa duplicata provável (erro `conflict`, nada gravado) e
  lista as parecidas. Mostre à pessoa: é o mesmo pedido, use a existente (nota ou update); é
  outro, crie com `allow_duplicate: true` e um título que diferencie. Nunca passe
  `allow_duplicate` sem olhar.
- **Uma pessoa por ação, uma entrega por ação.** "B2C até 01-10 e B2B até 02-10" são duas.
- **Entrega parcial não fecha nem fica parada.** Troque o título para o que falta ou divida, e
  registre a parte entregue: `tracker_record_event(entity_type=action, entity_id=<id>,
  kind=note, payload={"text": "...", "evidence": "<link>"})`.
- **Antes de mexer numa ação, leia o brain.** As `notes` da ação, o `wiki/daily/` mais recente
  e uma busca pelo `OL-NNNN`. O título pode estar atrasado em relação ao que já foi entregue.
- **O SLA conta do registro.** Sem prazo, vence pelo SLA da sev desde o último bump ou o dia
  em que entrou no tracker. Não ajuste `asked_at` para fugir do SLA.
- **Espera de terceiro não é vencido.** Quem trava é de fora (fornecedor, cliente,
  plataforma): `waiting_on_email` é a pessoa de {{company}} que acompanha, `waiting_external`
  diz de quem se espera e `review_at` quando reavaliar. **Nunca registre bump falso** para
  zerar o relógio. A bola voltou para alguém de dentro: `waiting_external: null`.
- **Prazo combinado vai em `due_at`**, não no título nem na sev.
- **Reatribuir é update, nunca fechar e recriar**: `tracker_update_action` /
  `tracker_update_decision`. O id fica, e o `OL-NNNN` citado na wiki continua valendo.
- **E-mail, não handle.** O tracker identifica por e-mail. Resolva `@handle` pelo perfil do
  chat. Nunca invente: sem saber quem é, anote no `wiki/daily/` com "quem deve: ?" e pergunte.
- **Projeto pelo slug**, conferido em `tracker_list_projects`. Sem projeto claro, sem projeto.
- **Fechar exige evidência**: link ou citação da resposta. Sumir do radar não fecha.
- **Fechar e decidir dizem o que se fecha.** Todo `tracker_close_action` leva
  `expect_title_contains` e todo `tracker_decide` leva `expect_question_contains`, com um
  termo distintivo do item. Id errado com expect é erro sem gravar nada; sem expect, fecha o
  item errado em silêncio. Se o expect falhar, releia, ache o id certo e chame de novo.

## Campos da ação (`tracker_create_action`)

| Campo | O que é |
|---|---|
| `title` | uma linha |
| `waiting_on_email` | quem deve, uma pessoa |
| `requester_email` | quem pediu |
| `type` | `loop` (a pessoa pediu) ou `commitment` (a pessoa prometeu) |
| `sev` | 1 bloqueia produção · 2 bloqueia alguém · 3 pode esperar |
| `source`, `source_ref` | `chat:#canal`, `dm:@x`, `email`, `meet`, `drive`; e o link ou `[[pagina]]` |
| `asked_at` | data do pedido original |
| `due_at` | prazo de entrega combinado |
| `waiting_external`, `review_at` | espera de terceiro, fora do SLA |
| `project` | slug |

Decisão (`tracker_create_decision`): `question`, `decider_email`, `deadline`, `priority`
(alta, media, baixa), `visibility` (`project`, `leadership`, `private`). Cite o `D-NNNN` na
página da wiki de onde ela saiu: é por ele que o desfecho volta à página.

## Operações

- **Abrir**: `tracker_create_action`, `tracker_create_decision`.
- **Editar**: `tracker_update_action`, `tracker_update_decision`. Só os campos enviados mudam;
  `null` limpa campo opcional. Ação fechada: `tracker_reopen_action` antes.
- **Cobrar**: `tracker_bump_action`, só depois que a pessoa disse que cobrou.
- **Fechar**: `tracker_close_action(action_id, evidence, status, expect_title_contains)`.
  `done`; `wontfix`; `moved` (virou issue ou outra coisa); `duplicate` com `duplicate_of`;
  `not_mine` (só quem deve, quando não reconhece; volta para quem pediu).
- **Decidir**: `tracker_decide(decision_id, outcome, expect_question_contains)`. O desfecho vai
  para `## Decisões` da página que cita o `D-NNNN`.
- **Desfazer**: `tracker_reopen_action` / `tracker_reopen_decision` com o motivo. Nunca recrie.
- **Ler**: `tracker_digest` só no pacote do dia (a chamada conta como pacote aberto);
  `tracker_list_actions(requester|waiting_on, status)`, `tracker_list_decisions(decider, status)`.
- **Eventos**: `tracker_record_event` para `note`, `nudge_ignored` (3º bump sem resposta) e
  `digest_missed_reason`.

## Sugestões, a medida de eficácia

Toda proposta de ação à pessoa (cobrar, fechar, decidir, criar issue, preparar reunião,
confirmar atribuição) é `tracker_create_suggestion(kind, text, rule, entity_type, entity_id)`.
`kind`, o mais específico: `nudge`, `close`, `escalate`, `decide`, `create_issue`,
`schedule_1on1`, `promote`, `pre_read`, `external_review`, `adoption`, `pr`,
`confirm_assignment`; `other` só se nenhum cabe. `rule`: o critério do Compass que motivou.
Item do tracker leva sempre `entity_type` e `entity_id`: o desfecho de `nudge`, `close`,
`confirm_assignment`, `external_review` e `decide` é inferido pelo que a pessoa fizer no item.
Resposta na sessão: `tracker_suggestion_outcome(followed | deviated | ignored, note)`.
**No máximo 10 sugestões por pacote**, pela ordem da fila; o resto aparece só como
informação. Sugestão sem desfecho em 2 dias úteis expira sozinha: não pergunte pelas de dias
anteriores.

## Adoção do pacote do dia

A chamada de `tracker_digest` da própria pessoa grava o dia como aberto. `digest.adoption`
traz dias abertos, esperados, taxa e a meta (`target`). Sem `enough_data`, não comente a taxa.

- **Semana**: no máximo 1 dia útil sem pacote por semana. `tracker_adoption(person=<eu>,
  days=5)`; de `missed`, só os dias desta semana.
- **Dia sem pacote** sem motivo em `adoption.reasons`: pergunte uma vez, em uma linha. Férias,
  folga ou ausência: `tracker_add_absence`, a única coisa que tira o dia da conta. Qualquer
  outra resposta: `tracker_record_event(entity_type=person, entity_id=<id>,
  kind=digest_missed_reason, payload={"day": ..., "reason": ...})`, que fica registrada mas
  não abona. Problema técnico (conector fora): diga o que fazer para não repetir.

## Sem tracker

Ferramenta ausente ou erro em qualquer chamada:

1. Diga em uma linha que o tracker não respondeu.
2. **Ler**: não há cópia. O pacote sai sem a parte do tracker; o **Ficou aberto** do último
   `## Fechamento` em `wiki/daily/` serve de lembrete, marcado "de DATA, não conferido".
3. **Escrever**: o que a pessoa aprovou vai para `## Para o tracker` no `wiki/daily/` do dia,
   uma linha por operação, com a ferramenta e os campos:
   `- [ ] tracker_create_action {"title": "...", "waiting_on_email": "...", "sev": 2}`.
4. **Reproduzir**: a próxima skill com tracker procura `- [ ]` nessas seções dos últimos 7
   dias, reproduz em ordem (as regras valem) e troca a linha por `- [x] ... → OL-NNNN`.
