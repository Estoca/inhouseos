---
title: Second brain no servidor
---

# Second brain

O second brain de cada pessoa é um repo git no servidor do InHouseOS de {{company}}
({{server}}). O repo vem do login: as ferramentas `brain_*` só alcançam o brain de quem
chama, e ninguém lê o de outra pessoa. Toda escrita pelo servidor já é um commit; não há
backup a fazer depois.

## Antes de tudo

`brain_status`. Se o brain não existe, diga em uma linha e ofereça criá-lo agora
(`brain_bootstrap`, a partir do modelo; o "pode" da pessoa é o ok). Sem brain, a skill
segue com o que não depende dele (agenda, chat, e-mail, tracker), a janela é de 24h e
nada é gravado no brain até ele existir.

Depois, leia o `CLAUDE.md` do brain (`brain_read(path="CLAUDE.md")`): é o schema dele, com
a tabela de classificação e as regras pessoais da pessoa. Regra pessoal vale mais que o
padrão da skill.

## Qual caminho

| Onde a sessão roda | Caminho |
|---|---|
| Chat do claude.ai, Cowork, sem shell | **pelo servidor**, trecho a trecho (tabela abaixo) |
| Claude Code com a pasta do brain aberta | arquivos no disco, com `grep` e leitura por linha; no fim, o backup por `brain_upload_link` |

Nunca traga o brain inteiro para a conversa: ele cresce toda semana e passa de centenas de
milhares de tokens. `brain_pull` é só para um arquivo pequeno que você sabe que precisa inteiro.

## Pelo servidor

| No disco | Pelo servidor |
|---|---|
| `ls`, `find` | `brain_list(prefix, depth)`; comece por `depth=2` |
| `grep -rn` | `brain_search(query, prefix, context)`; ignora caixa e acento; `files_only=true` para só saber onde |
| ler, `head`, `tail` | `brain_read(path, offset, limit)`; `offset` negativo lê o fim |
| `>>` no fim de um arquivo | `brain_append(path, text, message)` |
| editar um trecho | `brain_edit(path, old, new, message)`, com `old` lido antes por `brain_read` |
| criar arquivo novo (daily, página) | `brain_push(files=[{path, content}], message)` só com esse arquivo |

Caminho de leitura: `wiki/index.md` por `brain_read` para achar a página; `brain_search` para
nome, `OL-NNNN` ou tema; `brain_read` só no trecho achado. A última linha do log:
`brain_read(path="wiki/log.md", offset=-10)`.

`brain_edit` e `brain_push` aceitam `base_head`: o `head` que você leu. Se outra sessão
gravou no meio, nada é escrito e a resposta diz o que mudou; releia e refaça a edição.

## Arquivos que as skills usam

| Arquivo | O que é |
|---|---|
| `CLAUDE.md` | schema do brain e regras pessoais |
| `wiki/log.md` | uma linha por operação, só cresce: `## [AAAA-MM-DD] <operação> \| <resumo>` |
| `wiki/daily/AAAA-MM-DD.md` | o pacote do dia e o fechamento; derivado, a skill escreve direto |
| `wiki/people/<e-mail>.md` | a página da própria pessoa: canais e fontes em `## Fontes` |
| `wiki/meetings/`, `wiki/people/`, `wiki/projects/`, `wiki/threads/` | páginas da wiki |
| `raw/<fonte>/AAAA-MM-DD-<slug>.md` | cópia imutável de cada fonte ingerida; nunca se edita |

Página nova leva frontmatter com `title`, `visibility: private` e, se for 1:1, RH,
remuneração, saúde ou vida pessoal, `sensitive: true`.

## Com a pasta no disco (Claude Code)

Leia e escreva os arquivos direto. Para restaurar numa máquina nova, `brain_download_link` e o
comando `curl` que ele devolve. No fim de toda skill que escreveu, backup: `brain_status` para
o `head`, depois `brain_upload_link(message, base_head=<head lido no início>)` e o `curl` que
ele devolve, na raiz do brain, um `-F` por arquivo mudado (`-F 'delete=<caminho>'` para apagar).
Se o servidor andou desde o início da sessão, nada é gravado: baixe de novo, junte e suba.
