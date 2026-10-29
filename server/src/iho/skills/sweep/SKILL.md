---
name: sweep
description: Varre as fontes (chat, e-mail, agenda, documentos) desde o último sweep, classifica cada item e propõe ações, decisões, fechamentos e páginas da wiki para a pessoa aprovar.
when: a pessoa pede sweep, varredura, "o que ficou aberto", ou digita /sweep
aliases: varredura
docs: brain.md, tracker.md, compass.md, armadilhas.md
---

# /sweep

Responda na língua da pessoa. Leia os `docs` que vieram com esta skill. Prepare como no
`/bomdia` (`brain_status`, `CLAUDE.md`, e-mail do login). Conectores esperados em
{{company}}: {{connectors}}; fonte sem conector sai em uma linha.

**Janela**: da última linha `## [` com `sweep` em `wiki/log.md` até agora. A pessoa pode dar
outra ("últimos 30 dias", "desde sexta"). **Fontes**: as de `## Fontes` em
`wiki/people/<e-mail>.md`; sem a página, pergunte quais canais e use e-mail e agenda inteiros.

## 1. Coletar

- **Chat**: em cada canal da lista, as mensagens da pessoa na janela. Para cada pedido ou
  pergunta, leia a thread e veja se quem foi pedido respondeu. Também DMs com pedidos para
  ou da pessoa.
- **E-mail**: threads em que ela mandou algo e não teve resposta, ou recebeu pedido e não
  respondeu.
- **Agenda**: reuniões da janela sem página em `wiki/meetings/`, e as notas de cada uma
  ({{meeting_notes}}).
- **Tracker**: `tracker_list_actions(requester=<eu>, status=open)`. Para cada ação, confira na
  fonte se houve resposta depois de `asked_at`. Sem tracker, diga em uma linha que não deu
  para conferir.

## 2. Classificar

Tabela de classificação do `CLAUDE.md` do brain. Para cada item: tipo, pessoas, projeto
(slug, se der), sev ou prioridade, e uma linha de descrição.

`open-loop` e `commitment` só com pedido explícito a uma pessoa nomeada (ou promessa a
alguém), ainda sem resposta (`tracker.md` → Regras). Conversa resolvida na hora, pedido
difuso a um canal, item de plano e pendência deduzida são `info` ou `noise`. Antes de propor,
procure a mesma pendência no tracker (`tracker_list_actions(waiting_on=<quem deve>)`): se já
existe, é nota ou update, não ação nova.

## 3. Apresentar e esperar

- **Fechar**: ações com evidência de resposta, citando a mensagem que fecha (o `evidence`).
- **Abrir**: ações e compromissos novos, com os campos do `tracker_create_action` (título,
  e-mail de quem deve, sev, fonte, prazo, projeto). Mais de uma entrega: uma ação por entrega.
  Quem trava é de fora: `waiting_external` e `review_at`. Só mudou de dono: update.
- **Decidir**: decisões novas, com `decider_email`, prazo e prioridade.
- **Técnico**: itens `technical`, com título sugerido para o tracker técnico da pessoa.

Mais: reuniões a ingerir e páginas de pessoa ou projeto que vão nascer ou mudar.
**Pare aqui e espere o ok.** A pessoa pode cortar, mudar sev, corrigir quem deve.

## 4. Escrever

Só o aprovado, depois de `armadilhas.md`:

1. `raw/<fonte>/AAAA-MM-DD-<slug>.md` com a cópia de cada thread ou e-mail novo.
2. Tracker: `tracker_create_action`, `tracker_close_action`, `tracker_bump_action`,
   `tracker_create_decision` (cite o `D-NNNN` na página de origem). Sem tracker:
   `## Para o tracker` no `wiki/daily/` do dia.
3. Cada item proposto e aprovado, mudado ou cortado: `tracker_create_suggestion` e
   `tracker_suggestion_outcome` (followed, deviated, ignored).
4. Páginas em `wiki/threads/`, `wiki/meetings/`, `wiki/people/`, `wiki/projects/`, e o
   `wiki/index.md`.
5. `wiki/log.md`: `## [AAAA-MM-DD] sweep | fontes desde DATA: N itens, N loops novos, N
   fechados, N decisões`.
6. Pasta no disco: o backup do fim de `brain.md`.
