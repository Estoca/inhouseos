---
title: Armadilhas
---

# Armadilhas

Coisas que já fizeram um agente errar, e a regra que cada uma virou. Toda skill que escreve
no brain ou no tracker manda ler esta página antes de escrever.

## Arquivo do brain: releia antes de editar

A pessoa edita o brain durante a sessão (outro agente, outra máquina, o editor dela). Edição
montada sobre a leitura do começo da sessão sobrescreve o que ela mudou, ou vira um no-op
quando o trecho já não existe. Antes de editar `CLAUDE.md`, `wiki/people/<eu>.md` ou
qualquer página de regra: releia o trecho agora (`brain_read`), monte a edição sobre essa
leitura e passe o `base_head`. `brain_edit` que não achou o trecho não é sucesso: diga.
Se a pessoa mudou a mesma seção, mostre as duas versões e pergunte. Não escolha.

## Inferência gravada como fato

Um agente escreveu, no brain e no conhecimento compartilhado, que alguém "retirou a linha do
contrato antes da assinatura". Não havia fonte: era dedução de uma promessa numa thread. O
contrato, lido no dia seguinte, ainda tinha a linha. Regra: **fato só com fonte**. "Porque
alguém disse que faria" se escreve assim ("disse em 01-09 que ajustaria; a conferir"). Dedução
sua leva `(inferido)`.

## Lista de ações fora do tracker

Uma cópia das ações escrita à mão no brain inventou campo, perdeu bump e trocou quem devia.
Não monte lista de ações ou decisões no brain para servir de referência: cite o `OL-NNNN` /
`D-NNNN` com o título e leia o estado no tracker. Dado errado se corrige no tracker.

## Entrega parcial anotada só na wiki

O fechamento do dia anotou que metade de uma entrega tinha saído; a ação juntava as duas
metades e ficou como estava. Na segunda o agente perguntou de novo o que já tinha sido feito.
Uma entrega por ação, e entrega parcial muda o título ou divide (`tracker.md` → Regras).

## Id errado fecha o item errado em silêncio

Um agente quis decidir uma decisão e chamou o id vizinho; o tracker gravou o desfecho sem
relação e respondeu sucesso. Todo `tracker_decide` e `tracker_close_action` leva o `expect_*`.
Se errou, desfaça com `tracker_reopen_*`, nunca recriando.

## Schema antigo numa conversa aberta

O cliente guarda a lista de ferramentas por conversa. Ferramenta nova pode aparecer, mas uma
que mudou de parâmetros segue com o schema antigo mesmo depois de reconectar o conector. Se um
parâmetro que este protocolo usa não está no schema (o `expect_*`, por exemplo), peça uma
conversa nova; até lá, leia o item antes e confirme o título pelo id.

## Cobrança redigida pelo agente

Medido na empresa de origem: em uma semana, a cobrança com texto pronto do agente teve 12% de
adesão e resolveu 5 itens; quem cobrou do próprio jeito resolveu 28. A pessoa sabe cobrar; o
que ajuda é saber quem, há quanto tempo e onde. O texto só vem se ela pedir.

## 204 não é confirmação

Escrita em qualquer API pode responder sucesso sem ter feito o que você pediu. Depois de
escrever, leia o estado e só então diga que foi feito.
