---
name: dashboard-corretora-arquitetura
description: Como o painel exclusivo da CORRETORA guarda dados de dois anos (2026/2025) e o drill-down por DESCRICAO_CONTA — os scripts geradores e como rodá-los de novo
metadata:
  type: project
---

**O painel `painel_financeiro_corretora.html` é uma cópia do painel consolidado travada na empresa CORRETORA** (seletor de empresa removido, `state.brand` fixo), com dados só dessa empresa embutidos — não das outras 8 — para não pesar o arquivo. Criado nesta sessão (a partir de 2026-08-04/05).

## Filtro de Ano (2026 em curso / 2025 fechado)

Os dados de cada ano ficam num objeto `DADOS_ANO = { '2026': {...}, '2025': {...} }` no topo do `<script>`. A função `aplicarAno(ano)` reatribui as variáveis globais que o resto do código já usava (`MESES`, `DRE_DET`, `DRE_DET_ANT`, `BAL_DET`, `MOV`, `MOV_ANT`, `NAT`, `FC_CONT`, `SALDO_INI`, `DRE_DESC`) — por isso quase nenhuma função de render precisou mudar, só os textos que citavam "2026"/"06/2026" na cara (foram trocados por `anoAtual()`, `anoAnterior()`, `periodoRef()`, `mesFinalRotulo()`, `janAte()`, helpers definidos logo depois de `aplicarAno`).

**Cuidado ao adicionar um 3º ano ou trocar o ano corrente**: `MES_FINAL` varia (6 para 2026 em curso, 12 para 2025 fechado) — qualquer código com índice de mês fixo tipo `detalheMeses(brand)[5]` quebra silenciosamente pro ano de 12 meses (já aconteceu uma vez na página de Eficiência; o fix foi trocar para `[MESES.length - 1]`). Sempre teste os dois anos, não só o novo.

Scripts geradores (companheiros de `atualizar_dados.py`, que só mexe no painel consolidado):

- `Dashboard financeiro/gerar_dados_corretora_ano.py --ano 2025 --mes-final 12` — busca um ano inteiro (DRE, Balanço, Fluxo, drill-down) só da CORRETORA via DAX, reaproveitando os construtores de consulta de `atualizar_dados.py`. Imprime o literal JS de UMA entrada do `DADOS_ANO`.
- `Dashboard financeiro/gerar_drilldown_dre.py --empresa CORRETORA` — drill-down por `DESCRICAO_CONTA`, formato raso (sem essa flag, gera o formato aninhado por empresa usado no painel consolidado).
- `Dashboard financeiro/_atualizar_dados_ano_corretora.py` — cola a saída dos dois arquivos `.js` (gerados manualmente antes) no bloco `DADOS_ANO` do HTML, substituindo por regex `re.S` entre `  var DADOS_ANO = {` e o primeiro `\n  };\n` — funciona porque nenhum conteúdo interno tem uma linha exatamente `  };` (2 espaços); confirme isso com um grep antes de rodar se a estrutura interna mudar.
- `Dashboard financeiro/_migrar_ano_corretora.py` — script de migração única (já rodado, não precisa rodar de novo) que criou essa arquitetura a partir do painel de ano único que existia antes.

## Drill-down por DESCRICAO_CONTA (só na página da DRE)

Contas com detalhe disponível ganham um `▸`/`▾` clicável (`state.dreExpandido[contaKey]`) que abre sub-linhas por `DESCRICAO_CONTA`, respeitando o filtro de período (Mensal/Trimestral/Anual) via a função `agruparDesc()` (mesmo padrão de agrupamento de `agruparDre`+`comAcumulado`). As colunas de "Ano Anterior" e "Dif. %" mostram "–" nas sub-linhas — não há detalhamento por DESCRICAO_CONTA do ano anterior nesse painel.

No painel consolidado (não travado numa empresa), a função equivalente é `descsDe(brand, contaKey)`, que soma a mesma descrição entre as empresas de `empresasDe(brand)` — duas empresas com rótulos diferentes pra mesma conta viram linhas separadas, nunca são somadas por engano.
