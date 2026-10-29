---
name: bomdia
description: Pacote do dia. Agenda de hoje, sua fila em ordem de prioridade, o que o agente pode fazer por você agora, o que chegou desde o último pacote, quem cobrar, decisões paradas e reuniões a preparar e a ingerir.
when: a pessoa diz "bom dia", "abrir pacote", "abre o pacote", pede o resumo do dia, ou digita /bomdia ou /abrir-pacote
aliases: abrir-pacote, bom-dia
docs: brain.md, tracker.md, compass.md, armadilhas.md
---

# /bomdia — Pacote do dia

O ritual da manhã: lido em dois minutos, resolvido em dez. Responda na língua da pessoa.
Título: **Pacote do dia — DATA**.

Os documentos de apoio vieram junto (`docs` do `os_get_skill`): `brain.md` (como ler e
gravar o brain), `tracker.md` (o protocolo do tracker), `compass.md` (critérios de ordem,
régua de delegação, sinais) e `armadilhas.md`. Leia antes de começar.

**Conectores.** Os esperados em {{company}}: {{connectors}}. Confira quais estão nesta
sessão. Fonte sem conector sai do pacote em uma linha ("sem e-mail nesta sessão"), sem
travar o resto. Nunca peça senha ou token.

## Preparar

1. `brain_status` (`brain.md` → Antes de tudo). Sem brain: ofereça criar e siga sem ele.
2. `brain_read(path="CLAUDE.md")`: schema, tabela de classificação e regras pessoais.
3. **Janela**: a última linha `## [` com `bomdia` ou `sweep` em `wiki/log.md`
   (`brain_read(path="wiki/log.md", offset=-10)`), até agora. Sem linha, as últimas 24h.
4. **Quem é a pessoa**: o e-mail do login (`iho_whoami`). As fontes e canais dela em
   `## Fontes` de `wiki/people/<e-mail>.md`; sem a página, use menções, DMs, e-mail e agenda
   inteiros na janela, e no fim ofereça criar a página com os canais que ela disser.

## Coletar (só leitura, em paralelo quando der)

1. **Agenda**: eventos de hoje, com participantes. Para cada um, se há página de edição
   anterior em `wiki/meetings/` (`brain_search` pelo nome da reunião) e se há loop aberto
   com algum participante. Também as reuniões que a pessoa **organiza** daqui a 2 dias úteis,
   e se cada uma já tem `## Pré-leitura` na página dela.
2. **Chat**: menções à pessoa, DMs e mensagens dela sem resposta, desde a janela, nos canais
   de `## Fontes`. E as **mensagens da própria pessoa** na janela: promessa com prazo ou com
   destinatário ("te passo na quinta", "faço amanhã") é candidata a `commitment`; pedido ou
   pergunta dela sem resposta é candidato a `open-loop`.
3. **E-mail**: threads não lidas ou com resposta desde a janela, sem newsletter nem
   notificação automática.
4. **Tracker**:
   - Antes, se algum `wiki/daily/` dos últimos 7 dias tem `- [ ]` em `## Para o tracker`,
     reproduza (`tracker.md` → Sem tracker).
   - `tracker_digest(since=<início da janela>)`: vencidos que a pessoa deve
     (`overdue_waiting_on_me`), vencidos que ela espera (`overdue_i_am_waiting`),
     compromissos (`my_commitments`), decisões dela e paradas, `waiting_external`,
     `moved_away`, `assigned_to_me`, `bounced`, `project_updates_due`, `adoption` e, para quem
     lidera, `team_stuck`. É esta chamada que conta o dia como pacote aberto.
   - `tracker_list_decisions(status=decided)`: as que a pessoa pediu ou decide e foram
     decididas na janela.
   - `tracker_adoption(person=<e-mail>, days=5)`, para a régua da semana.
   - `tracker_list_projects`: os com `updated_at` na janela.
   - Tracker fora: `tracker.md` → Sem tracker; o pacote sai sem esta parte, dito em uma linha.
5. **Reuniões com notas e sem página**: toda reunião dos últimos 7 dias (não só da janela)
   que tem notas e ainda não tem página em `wiki/meetings/`. Fonte oficial de notas em
   {{company}}: {{meeting_notes}}.

Antes de propor qualquer item novo, confira se ele já está no tracker
(`tracker_list_actions(waiting_on=<quem deve>)`) ou no `wiki/daily/` recente.

## Classificar

Cada item novo recebe um tipo da tabela de classificação do `CLAUDE.md` do brain
(`open-loop`, `commitment`, `decision`, `technical`, `info`, `noise`), com pessoas, projeto
(slug, se der para inferir) e sev. `open-loop` e `commitment` só com pedido explícito a uma
pessoa nomeada (`tracker.md` → Regras). Não escreva nada ainda: é lista para a pessoa decidir.

## Apresentar

Nesta ordem, curto. Seção vazia some sem comentário. Todo item do tracker citado leva o id e
o título (`tracker.md` → Item citado leva título).

1. **Hoje**: reuniões com hora, e uma linha de contexto para as que têm histórico ou loop
   aberto com participante. Depois, **Preparar**: reuniões que a pessoa organiza em 2 dias
   úteis sem pré-leitura, uma linha cada.
2. **Sua fila** (abaixo).
3. **Posso fazer** (abaixo).
4. **Cobrar**: os vencidos que a pessoa espera (`overdue_i_am_waiting`), na ordem da fila,
   um por linha: id e título, quem cobrar, há quantos dias venceu, qual cobrança é (1ª, 2ª,
   3ª) e onde (a thread original, com link). **Sem mensagem redigida** (`armadilhas.md`): o
   texto só se ela pedir, e aí 1ª neutra, 2ª com prazo, 3ª propõe tirar do chat.
5. **Decidir**: decisões dela com prazo perto ou vencido. Depois, as decididas na janela: uma
   linha cada, com o desfecho, quem decidiu e a página que cita o `D-NNNN`, onde o desfecho
   vai entrar em `## Decisões`.
6. **Seu time** (só se o digest trouxe `team_stuck`): a linha de totais e até 5 itens de
   `team_stuck.top`, cada um com quem espera quem, há quanto tempo e quem destrava. É para
   ajudar a destravar, nunca para cobrar: sem texto de cobrança e sem comparar pessoas.
7. **Aguardando terceiro**: `waiting_external`, uma linha cada: de quem se espera, título,
   idade e `review_at`. Os com `review_due` vêm primeiro, marcados **reavaliar**: segue
   esperando (nova `review_at`), muda o plano, ou a bola voltou para alguém de dentro.
8. **Saiu do seu radar**: `moved_away`, uma linha cada (título, com quem está agora, quem
   mudou e quando). Só informa.
9. **Atribuídas a você**: `assigned_to_me`, uma linha cada com quem pediu, a fonte e "é seu?".
   É dela: nada a fazer. É de outra pessoa que ela sabe: `tracker_update_action
   (waiting_on_email=...)`. Não reconhece: `tracker_close_action(status=not_mine, evidence=...)`.
   **Voltaram para você**: `bounced`, com a evidência; ela reatribui ou desiste.
10. **Chegou**: itens novos classificados, agrupados por tipo. Para cada `open-loop`,
    `commitment` ou `decision`, a linha proposta com os campos do tracker. Para `technical`,
    a issue sugerida no tracker técnico da pessoa.
11. **Reuniões sem página**: para cada reunião com notas, uma proposta curta (takeaways,
    decisões, compromissos com dono) e um ok para o lote. Sem notas ainda: uma linha com a
    reunião e de quem depende a gravação.
12. **Novidades**: projetos do tracker novos ou alterados na janela, com dono. Uma linha:
    direção do período não servida, peso 1 para todos (`compass.md`).
13. **Saúde do brain** (só achados): linha `- [ ]` antiga em `## Para o tracker` que não foi
    reproduzida; loop aberto há mais de 30 dias (fora espera de terceiro com `review_at` no
    futuro); decisão vencida há mais de 7 dias.
14. **Pacote do dia**: uma linha com o número dela, se `adoption.enough_data` ("Seu pacote:
    14 de 20 dias úteis (70%), meta 80%"), e a régua da semana ("Semana: 1 dia sem pacote
    (14-10), o máximo"). Abaixo da meta, sem sermão. Dia sem pacote sem motivo: a pergunta de
    uma linha (`tracker.md` → Adoção).

### Sua fila

Uma lista numerada única com **tudo o que depende da própria pessoa hoje**, para ela não ter
que montar a ordem de cabeça. Entra:

- compromissos dela (`overdue_waiting_on_me`, `my_commitments`);
- decisões em que ela decide, vencidas ou com prazo na semana;
- cada cobrança de **Cobrar** (a ação é cobrar, do jeito dela);
- `commitment` ou pedido direto novo de **Chegou**, mesmo antes de virar ação;
- reunião para preparar;
- atribuída a confirmar, e a que voltou para ela;
- update de projeto de que ela é dona (`project_updates_due`): `late` conta como vencido,
  `due` entra pelo prazo.

Fica fora: espera de terceiro, o que ela só acompanha, informação.

**Ordem**: os critérios de `compass.md`, na ordem deles; dentro do mesmo critério, o prazo
mais perto antes da idade. Item novo que ainda não está no tracker entra pela sev proposta.

**Formato**: até 10 itens; passou disso, "mais N". Um por linha:

`N. OL-0042 título curto — por quê ("sev2, prazo amanhã, a Rayane espera") — o que fazer agora ("mandar o valor", "responder a Ana na thread")`

Item que o agente consegue fazer ou adiantar ganha no fim a letra da oferta: `(posso: B)`.
Nada que dependa dela: "Nada na sua fila hoje."

### Posso fazer

O pacote não só lista: oferece executar. Para cada item da fila, e depois para Chegou e
Decidir: o agente consegue entregar isso **nesta conversa**, com as ferramentas que tem,
**sem decidir pela pessoa**? Se sim, é oferta. Tipos:

- **documento**: pré-leitura, resumo para circular, página da wiki, rascunho no Drive
  (criado privado; quem compartilha é a pessoa);
- **investigação**: ler a thread ou o e-mail citado e trazer o que está pendente, com fonte;
- **tracker**: fechar com a evidência que o pacote já achou, reatribuir, mudar prazo,
  registrar ausência (nível 2: o "pode" é a confirmação);
- **reunião**: ingerir as notas de uma reunião sem página;
- **update de projeto**: montar o rascunho do update; a pessoa confirma e o agente posta
  (`tracker_post_project_update`);
- **mensagem**: redigir pronta para colar, quando o item pede uma (nível 1: a pessoa envia).
  Cobrança não é oferta.

**Nunca é oferta**: decidir no lugar da pessoa; aprovar o que só ela aprova; senha,
credencial ou pagamento; **enviar** mensagem, e-mail ou convite.

**Formato**: até 5, com letra, na ordem da fila. Uma por linha: o que o agente faz, a que
item serve, o que a pessoa recebe. Feche com "Responda `pode A, C` ou `pode tudo`." Não
invente oferta para preencher a seção.

**Executar**: com "pode X", faça nesta conversa pela regra que cobre aquilo, e diga em uma
linha o que foi feito, com link. O que chega a outra pessoa continua pedindo o ok daquela
ação.

## Escrever

Antes de escrever no brain: `armadilhas.md`.

- **`wiki/daily/AAAA-MM-DD.md`**: o pacote, com frontmatter (`title`, `visibility:
  private`), incluindo `## Posso fazer` com as ofertas e o que foi feito. Escreva direto, é
  derivado (`brain_push` para criar; `brain_append` ou `brain_edit` se já existe).
- **Tracker, só depois do ok** (item a item ou em bloco): `tracker_create_action`,
  `tracker_create_decision`, `tracker_bump_action` para cada cobrança que a pessoa disse que
  mandou, `tracker_close_action` com evidência e expect. Duplicata provável: mostre as
  parecidas e pergunte.
- **Sugestões**: cada item de Cobrar, Decidir, Chegou, Preparar, Atribuídas, Aguardando
  terceiro e Posso fazer que propõe uma ação vira `tracker_create_suggestion` com
  `entity_type` e `entity_id` quando é item do tracker. `rule`: o critério do Compass ou
  `posso:<tipo>` para as ofertas. **No máximo 10 por pacote**, pela ordem da fila; o resto
  aparece numa linha, sem sugestão. Não repita sugestão ignorada se o item não mudou
  (confira no `wiki/daily/` anterior). O que a pessoa responder nesta conversa vira
  `tracker_suggestion_outcome`.
- **Reuniões sem página**, com o ok: `wiki/meetings/AAAA-MM-DD-<slug>.md` (participantes,
  takeaways, `## Decisões` com data e quem decidiu), a cópia das notas em `raw/meet/`, e as
  ações e decisões no tracker.
- **Decididas na janela**, com o ok: o desfecho em `## Decisões` da página que cita o
  `D-NNNN`, com data e quem decidiu.
- **Tracker fora**: o aprovado vai para `## Para o tracker` do `wiki/daily/` do dia.
- **`wiki/log.md`** (`brain_append`), sempre: `## [AAAA-MM-DD] bomdia | N reuniões, N
  vencidos, N novos itens`.
- Pasta no disco: o backup do fim de `brain.md`. Pelo servidor, cada escrita já é um commit.
