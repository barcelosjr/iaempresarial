---
name: dashboard-corretora-contexto
description: Estado atual do painel exclusivo da CORRETORA (painel_financeiro_corretora.html) — o que está pendente de publicar, URLs dos artefatos, e onde fica a arquitetura de dados por ano/drill-down
metadata:
  type: project
---

**O usuário está numa sessão contínua de ajustes no painel exclusivo da CORRETORA** (`Dashboard financeiro/build/painel_financeiro_corretora.html`) e pretende continuar numa conversa nova sem perder o fio. Registrado em 2026-08-05.

## Artefatos publicados (claude.ai)

- **Painel consolidado (Grupo Mult)**: https://claude.ai/code/artifact/9d744310-af88-4c3f-9f9b-8add93084791 — fonte local `Dashboard financeiro/build/painel_financeiro.html`.
- **Painel exclusivo da CORRETORA**: https://claude.ai/code/artifact/ac0b0833-7995-4119-ba69-f9015164fdd1 — fonte local `Dashboard financeiro/build/painel_financeiro_corretora.html`.

Para atualizar mantendo o mesmo link: chamar a ferramenta de Artifact passando o `url` acima — sem isso, uma conversa nova cria um link novo em vez de atualizar o existente.

## Estado de publicação

Publicado e no ar em 2026-08-05, com tudo que foi feito na sessão até essa data:

- Filtro de Ano (2026/2025) — ver [[dashboard-corretora-arquitetura]].
- Drill-down por `DESCRICAO_CONTA` na DRE.
- Tabelas de DRE/Fluxo/Balanço mais largas (removido o teto `max-width:1360px` do `.main`).
- "Composição (Curto Prazo)" mostrando "–" em vez de "NaN%" quando a empresa não tem dívida financeira (mesmo fix aplicado ao gráfico de composição da dívida, que também quebrava).
- Selos "CÁLCULO PRÓPRIO" removidos de todos os cards.
- Glossário padronizado (explicação simples + fórmula + expectativa do resultado) no fim das páginas de Rentabilidade/Liquidez e Endividamento/Alavancagem — ver [[feedback-explicacoes-diretoria]].
- Todos os rodapés técnicos curtos (".footnote" com texto tipo "Fonte: Power BI..." / "Cálculo próprio...") removidos das 6 páginas — o usuário não quer esse tipo de nota, prefira o glossário ou nada.

**Padrão de workflow desta sessão**: depois de qualquer edição, mostrar o HTML pro usuário (`SendUserFile`) e **não publicar** até ele pedir explicitamente — geralmente com a frase "publique do jeito que está". Isso já aconteceu várias vezes seguidas antes da publicação de 2026-08-05, então não assuma autorização implícita de uma vez pra próxima.

## Correção no modelo semântico (2026-08-05)

O usuário corrigiu algo na base do Power BI que resolveu duas anomalias que este agente tinha sinalizado: o CHECK do Balanço não fechava em 06/2026 para a CORRETORA (R$ -188.160), e dezembro/2025 tinha lançamentos de reversão enormes que zeravam a receita do ano inteiro. Depois da correção, ambos os valores passaram a bater com os relatórios oficiais (`relatorio_balanco`/`relatorio_dre`). Os dados do painel foram regenerados e conferidos contra esses relatórios oficiais após a correção — não é preciso reabrir essa investigação a menos que uma nova anomalia apareça.

## Como validar antes de publicar (padrão desta sessão)

Sempre conferir os números do painel contra `relatorio_dre` / `relatorio_balanco` / `relatorio_fluxo_caixa` oficiais (ferramentas MCP `analista-bi`) antes de reportar como corretos — já aconteceu mais de uma vez de um número "bater consigo mesmo" mas estar errado porque os dois lados (painel e conferência) usavam a mesma lógica desatualizada. Ver também [[dre-estrutura-oficial]] sobre esse risco especificamente com mudanças de estrutura.
