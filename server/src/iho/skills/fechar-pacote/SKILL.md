---
name: fechar-pacote
description: Fecha o dia. O que aconteceu desde o pacote da manhã, cobranças enviadas, o que fechar com evidência, desfecho das sugestões do dia, reuniões a ingerir e o que vence amanhã; grava o fechamento em wiki/daily/.
when: a pessoa diz "fechar pacote", "fechar o dia", "boa noite", "tchau", "encerrar", ou digita /fechar-pacote ou /boanoite
aliases: boanoite, boa-noite, fechar-o-dia
docs: brain.md, tracker.md, compass.md, armadilhas.md
---

# /fechar-pacote

O par do `/bomdia`: fecha as pontas do dia para o pacote de amanhã começar limpo. Só roda
quando a pessoa pede. Responda na língua dela. Leia os `docs` que vieram com esta skill.

Prepare como no `/bomdia` (`brain_status`, `CLAUDE.md`, e-mail do login). **Janela**: desde
a linha `## [HOJE] bomdia` de `wiki/log.md`. Sem pacote hoje, as últimas 24h, dito em uma
linha (não abra o pacote agora).

## Coletar (só leitura)

1. **Tracker**: `tracker_list_actions(requester=<eu>, status=open)`,
   `tracker_list_actions(waiting_on=<eu>, status=open)` e `tracker_list_decisions(decider=<eu>)`.
   **Não chame `tracker_digest`**: ele conta como pacote aberto.
2. **O que a pessoa mandou hoje**: chat (mensagens dela na janela) e e-mails enviados. Para
   cada ação aberta, se ela cobrou (mensagem dela na thread do item depois do pacote) e se
   houve resposta que fecha o item.
3. **O que chegou depois do pacote**: menções, DMs e e-mails com pedido direto, na janela.
4. **Reuniões com notas e sem página**: as de hoje já terminadas e as dos últimos 7 dias cujas
   notas chegaram depois do pacote. Fonte oficial de notas: {{meeting_notes}}.
5. **Sugestões do dia sem desfecho**: as do `## Posso fazer` e as demais registradas no
   `wiki/daily/` de hoje. Não pergunte pelas de `nudge`, `close`, `confirm_assignment`,
   `external_review` e `decide` cujo item a pessoa já mexeu no tracker: o desfecho é inferido.
6. **Amanhã**: compromissos e decisões dela que vencem amanhã; reuniões de amanhã que ela
   organiza sem pré-leitura.
7. **Update de projeto**: `tracker_list_projects(status="active")`, os que ela é dona com
   update `due` ou `late`, ou com prazo até amanhã. O dia acabou de acontecer: é a melhor hora
   do rascunho.
8. **Brain**: linhas `- [ ]` em `## Para o tracker` do `wiki/daily/`; reproduza as que puder.

## Apresentar

Curto, cada item do tracker com id e título:

1. **Fechado hoje**: o que saiu do tracker e da wiki no dia.
2. **Cobranças enviadas**: as que ela mandou; proponha o `tracker_bump_action` de cada uma.
3. **Para fechar**: itens com evidência de resposta, com o `tracker_close_action` proposto e a
   evidência (link ou citação). Evidência que cobre só parte: trocar o título ou dividir
   (`tracker.md` → Entrega parcial), nunca fechar o item inteiro.
4. **Chegou depois do pacote**: classificado como no `/sweep`, com a linha proposta.
5. **Reuniões sem página**: uma proposta curta por reunião e um ok para o lote. Sem notas
   ainda: de quem depende; o pacote de amanhã tenta de novo.
6. **Sugestões sem desfecho**: uma linha cada, para ela responder.
7. **Update de projeto**: o rascunho pronto (o que mudou, o que trava, próximo passo),
   atrasado primeiro. Ela confirma ou ajusta e o agente posta.
8. **Amanhã**: o que vence e o que precisa de pré-leitura.

**Discuta antes de escrever.** Nada entra no tracker sem o ok, item a item ou em bloco.
"Sumiu do radar" não fecha nada.

## Escrever

Com o ok, e depois de `armadilhas.md`:

- Tracker: `tracker_bump_action`, `tracker_close_action` (com `expect_title_contains`),
  `tracker_create_action` para o que chegou, `tracker_suggestion_outcome` para cada desfecho
  respondido, `tracker_post_project_update` para o update confirmado. Reatribuir é update.
- Reuniões: página em `wiki/meetings/`, notas em `raw/meet/`, ações e decisões no tracker.
- Tracker fora: o aprovado vai para `## Para o tracker` do `wiki/daily/` de hoje.
- `wiki/daily/AAAA-MM-DD.md`: acrescente `## Fechamento` com três blocos curtos, **Fechou**,
  **Ficou aberto** (com de quem depende) e **Amanhã**. É o primeiro insumo do pacote seguinte.
  Sem página do dia, crie uma só com essa seção.
- `wiki/log.md`: `## [AAAA-MM-DD] fechamento | N fechados, N cobranças registradas, N novos,
  N sugestões respondidas; pendente: <o mais importante>`.
- Pasta no disco: o backup do fim de `brain.md`.
