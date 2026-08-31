---
name: comandos
description: Catálogo oficial dos comandos e ferramentas deste projeto (analista-bi / Power BI / DRE / Balanço / Fluxo de Caixa / indicadores / dashboard financeiro / DuckDB / testes). Use SEMPRE antes de escrever DAX na mão, criar script novo, rodar python ou inventar qualquer comando dentro desta pasta — só pense num comando novo se nada aqui atender.
---

# Comandos do projeto

**Regra de ouro:** procure aqui primeiro. Se existe um comando/ferramenta pronta
para o pedido, use-a **sem reescrever DAX, sem criar script e sem improvisar**.
Só monte algo novo se nenhuma linha deste arquivo atender — e, nesse caso, diga
ao usuário que está saindo do catálogo.

---

## 1. Python — sempre o do venv

O `python` do PATH no Windows é o **stub da Microsoft Store** (abre a loja / erro
de módulo ausente). Nunca use `python` puro. Use sempre:

```bash
.venv/Scripts/python.exe <script>
```

| Objetivo | Comando |
|---|---|
| Validar token/dataset/consulta | `.venv/Scripts/python.exe scripts/validar_setup.py` |
| (Re)gerar `dictionary/modelo_semantico.md` | `.venv/Scripts/python.exe scripts/gerar_dicionario.py` |
| Briefing do dia em `reports/` | `.venv/Scripts/python.exe analysis/briefing_diario.py` |
| Ingerir planilhas no DuckDB | `.venv/Scripts/python.exe local_data/ingest.py <pasta>` |
| Rodar os testes | `.venv/Scripts/python.exe -m pytest -q` |
| Atualizar os dados do painel financeiro | Skill `atualizar-paineis` (checklist completo — **não** rode `atualizar_dados.py`, está obsoleto) |
| **Planilha financeira** (visão tabular, mês a mês) de uma empresa | `.venv/Scripts/python.exe "Dashboard financeiro/gerar_planilha.py" royal` |
| Planilha da KOBE **com filtro por revenda** | `.venv/Scripts/python.exe "Dashboard financeiro/gerar_planilha.py" kobe --por-revenda` |
| Auditoria diária de caixa em `reports/` | `.venv/Scripts/python.exe analysis/auditoria_diaria.py` |
| Snapshot diário de saldo no DuckDB | `.venv/Scripts/python.exe local_data/snapshots.py` |
| **Conciliação de caixa** (financeiro x contábil) em `reports/` | `.venv/Scripts/python.exe analysis/conciliacao_caixa.py 07/2026` |
| Conciliação de uma empresa só | `.venv/Scripts/python.exe analysis/conciliacao_caixa.py 07/2026 --empresa "ROYAL ENFIELD"` |
| **COAF — detectar recebimentos em espécie** (modo revisão, não envia e-mail) | `.venv/Scripts/python.exe analysis/coaf_especie.py` |
| COAF — rodar **enviando** os e-mails | `.venv/Scripts/python.exe analysis/coaf_especie.py --enviar` |
| COAF — só regerar o histórico (sem consultar o Power BI) | `.venv/Scripts/python.exe analysis/coaf_especie.py --historico --csv` |
| COAF — reenviar **todos** os casos (após corrigir os responsáveis) | `.venv/Scripts/python.exe analysis/coaf_especie.py --enviar --forcar-envio` |

Rodar sempre a partir da raiz do projeto (`C:\Users\Controladoria\.claude\projects\iaempresarial`).

---

## 2. Pedido → comando (use esta tabela primeiro)

| O usuário pede | Use |
|---|---|
| "DRE de 03/2026", "resultado do mês/trimestre/ano" | `relatorio_dre` |
| "Balanço", "posição patrimonial", "ativo/passivo/PL" | `relatorio_balanco` |
| "Fluxo de caixa", "geração de caixa" | `relatorio_fluxo_caixa` |
| "Indicadores", "KPIs", "margem", "liquidez", "endividamento", "giro", "PMR/PMP", "ciclo financeiro" | `relatorio_indicadores` |
| "Que períodos existem?", "até quando tem dado?" | `periodos_financeiros` |
| "Compramos X?", "tem o item Y?" | `buscar_item` (tente sinônimos) |
| "Quais tabelas/medidas existem?" | `esquema_modelo` |
| Agregação por medida oficial (faturamento por loja etc.) | `resumo_kpis` |
| Dados de planilha avulsa (fora do Power BI) | `consultar_duckdb` |
| Qualquer coisa que **nenhuma** das anteriores cobre | `consultar_dax` (última opção) |
| "Atualiza o painel/dashboard", "atualize os dados dos painéis" | Skill `atualizar-paineis` |
| "Quero ver em formato de planilha/tabela", "mês a mês numa tabela" | `gerar_planilha.py <slug>` (seção 4) |
| "DRE da KOBE por loja/revenda", "comparar revendas", "só a KOBE GV" | `gerar_planilha.py kobe --por-revenda` |
| "O caixa bate com a contabilidade?", "conciliar caixa", "saldo contábil x financeiro", "por que o caixa não fecha" | `relatorio_conciliacao_caixa` |
| "Quem passou de 30 mil em espécie?", "situação do COAF", "clientes acima do limiar" | `relatorio_coaf` |
| "Esse cliente já foi detectado antes?", "histórico do COAF", "quem já foi notificado" | `historico_coaf` |
| "Rodar o COAF agora", "gerar as DMFs" | `.venv/Scripts/python.exe analysis/coaf_especie.py` |

---

## 3. Ferramentas MCP (`mcp__analista-bi__*`)

Somente leitura. Todas aceitam `dataset` (apelido de `config/datasets.yaml` ou
GUID); `None` = dataset padrão. Todas devolvem a query executada para auditoria.

### Relatórios financeiros

- **`relatorio_dre(periodo, empresa=None, modo="mensal", visao="gerencial")`**
  - `periodo`: `"MM/AAAA"`. `empresa`: ex. `"KOBE"`; `None` = consolidado.
  - `modo`: `"mensal"` | `"trimestral"` (exige 03/06/09/12) | `"anual"` (exige 12).
    **Nunca some meses em várias chamadas — use o `modo`.**
  - `visao`: `"gerencial"` (todos os lançamentos) | `"contabil"` (só `TIPO_LANÇAMENTO = "CONTÁBIL"`).
    Sempre informe qual visão foi usada — os números diferem.
  - Subtotais (RL, Lucro Bruto, EBITDA, EBIT, LAIR, Lucro Líquido) e margens já vêm prontos.
- **`relatorio_balanco(periodo, empresa=None)`** — acumulado desde 01/2024. Traz o
  CHECK `Ativo - (Passivo + PL)`; só fecha em 03/06/09/12 (apuração trimestral).
- **`relatorio_fluxo_caixa(periodo, empresa=None, modo="mensal")`** — método indireto.
  `modo`: `"mensal"` | `"trimestral"` (exige 03/06/09/12). Traz CHECK contra DISPONIBILIDADES.
- **`relatorio_indicadores(periodo, empresa=None, modo="mensal")`** — KPIs com
  explicação e "melhor se…". Reaproveita DRE + Balanço; **não recalcule KPI na mão**.
  Grupos: Rentabilidade (Margem Bruta, EBITDA, EBIT, EBIT/Lucro Bruto, Líquida),
  Liquidez (Corrente, Seca, Imediata), Endividamento (Dív. Líq. c/ e s/ Floor Plan
  / EBITDA, Endividamento Geral, Cobertura de Juros), Eficiência (giro VN, VU,
  peças, PMR, PMP, Ciclo Financeiro, Custo de Pessoal/RL, Desp. Operac./RL).
- **`periodos_financeiros()`** — períodos disponíveis. Rode antes se houver dúvida
  se o período existe.

### Conciliação de caixa

- **`relatorio_conciliacao_caixa(ate, empresa=None)`** — cruza o saldo do livro-caixa
  (`CAIXAS`, dataset `controlador`) com o da conta contábil de CAIXA GERAL
  (`lancamentos`, dataset padrão), mês a mês. `ate` é `"MM/AAAA"`; `empresa` aceita o
  nome do financeiro (`"ROYAL ENFIELD"`) ou do contábil (`"ROYAL"`).
- **A chave é EMPRESA, nunca REVENDA** — transferência de saldo entre caixas de revendas
  diferentes não tem lançamento contábil e só se anula no total da empresa.
- **A granularidade é MENSAL.** `lancamentos` não tem coluna de data, só `PERIODO`
  (`MM/AAAA`) — **não existe conciliação diária**. Se pedirem "saldo do dia bate?",
  explique isso antes de tentar.
- **Diferença de abertura ≠ divergência do mês.** A primeira é saldo inicial que a
  planilha não trouxe em 01/01/2025 e se arrasta constante; a segunda é movimento
  descasado. O relatório separa as duas — não some as duas num número só.
- Regra completa, mapa de empresas e medição de referência:
  `dictionary/regras_negocio.md`, seção "Conciliação de Caixa". Parâmetros em
  `config/conciliacao_caixa.yaml` — **não mude no código**.

### COAF — recebimentos em espécie

- **`relatorio_coaf(meses=None, limiar=None)`** — clientes que atingiram o limiar de
  R$ 30 mil em espécie numa janela **móvel** de 6 meses. Consulta ao vivo, **não grava
  nada** (sem histórico, sem PDF, sem e-mail). Para gravar e gerar as DMFs, rode o job
  `analysis/coaf_especie.py`.
- **`historico_coaf(cliente=None, desde=None, apenas_notificados=None)`** — histórico
  **permanente** de quem já foi detectado. Lê o banco local, não o Power BI. Cliente
  notificado **continua aqui** — a deduplicação tira da fila de e-mail, nunca do histórico.
- Regra, risco assumido e armadilhas: `dictionary/regras_negocio.md`, seção
  "COAF / Recebimentos em espécie". **Leia antes de mexer no cálculo.**
- Parâmetros (limiar, janela, exclusões de `ORIGEM`) ficam em `config/coaf.yaml`;
  destinatários em `config/responsaveis_caixa.yaml`. **Não mude no código** — o compliance
  edita o YAML.

### Consulta geral

- **`buscar_item(termo, tabela, coluna, dataset=None, coluna_data=None, limite=None)`**
  — busca textual case-insensitive. Se vier vazio, **tente sinônimos** antes de
  concluir que não existe (`cloro` → `hipoclorito`, `tricloro`, `cloro granulado`);
  veja nomenclaturas em `dictionary/regras_negocio.md`.
- **`esquema_modelo(dataset=None, forcar_extracao=False)`** — dicionário do modelo.
- **`resumo_kpis(medidas, dimensoes=None, filtros=None)`** — `SUMMARIZECOLUMNS` com
  **medidas oficiais**. `dimensoes`: `["Tabela[Coluna]"]`; `filtros`: `{"Tabela[Coluna]": valor}`.
- **`consultar_duckdb(sql, limite=100)`** — **só SELECT** (ou `WITH ... SELECT`),
  base local de planilhas ingeridas.
- **`consultar_dax(query, dataset=None)`** — DAX cru, `EVALUATE`/`DEFINE`. Último
  recurso: antes de usar, leia `dictionary/modelo_semantico.md` e
  `dictionary/regras_negocio.md`, e avise que o número **não é medida oficial**.

---

## 4. Dashboard financeiro

9 painéis estáticos em `Dashboard financeiro/build/` (8 por marca +
`painel_financeiro.html` consolidado), publicados como Claude Artifacts. Os
números vivem num bloco `var DADOS_ANO = {...}` no `<script>`, com seletor de
Ano na sidebar (arquitetura por `DADOS_ANO`/`aplicarAno()`).

- Para **atualizar os números e/ou republicar**: use a skill `atualizar-paineis`
  — ela tem o checklist completo (quais scripts rodar, em que ordem, como
  validar antes de publicar, e as URLs de cada artifact). Não improvise o
  processo nem rode `atualizar_dados.py` (obsoleto, de antes da arquitetura
  `DADOS_ANO` — incompatível com os painéis atuais).
- **Não edite os blocos de dados na mão** — regenere via script.
- Layout/textos/gráficos: aí sim edite o HTML diretamente.

### Planilha financeira (visão tabular)

`build/planilha_<slug>.html` é uma **leitura tabular** dos mesmos números do painel
oficial — abas Resumo / DRE / Balanço / Fluxo de Caixa / Indicadores, colunas por
período (mensal, trimestral ou anual), Δ vs. ano anterior, análise vertical, escala
R$ / R$ mil, filtro de linhas e cópia em TSV pro Excel.

- Gere com `gerar_planilha.py <slug>` (ex.: `royal`). O script **lê** o `SNAPSHOT` e o
  bloco `DADOS_ANO` do painel oficial e injeta em `_template_planilha.html`. Ele nunca
  escreve no painel oficial.
- Depois de rodar a skill `atualizar-paineis`, rode `gerar_planilha.py` de novo para as
  planilhas herdarem os dados novos.
- Mudou fórmula/estrutura no painel oficial? Reflita em `_template_planilha.html` — as
  funções de cálculo são portadas de lá e precisam continuar idênticas.
- A linha de CHECK (Balanço e Fluxo) é sempre exibida em R$ cheios, mesmo na escala
  R$ mil, para não sumir por arredondamento.
- **Não tem exportação**: sem botão de copiar e com `user-select:none` na tabela, por
  pedido do usuário. No lugar, arrastar sobre as células mostra contagem, soma e
  média da seleção (lê o valor cru de `data-v`, nunca o texto formatado).
- O drill-down da DRE abre **uma conta por vez** (`state.expandido[conta]`); o
  checkbox "detalhar todas as contas" é só o atalho de abrir/fechar tudo.

#### Modo `--por-revenda` (só KOBE)

Abre a DRE pelas 10 revendas, com chips de seleção (uma, várias ou todas;
Alt+clique isola uma). Duas regras que **não** devem ser "melhoradas" depois:

- **A DRE por revenda é consultada ao vivo**, reaproveitando
  `gerar_dre_revendas_kobe.gerar()` — a mesma query dos artefatos oficiais. Não
  herde de `painel_financeiro_kobe_por_revenda.html`: esse painel costuma ficar
  semanas atrás do agregado (em 31/08/2026 estava 11 dias defasado, R$ 8,2 M só
  em Venda de VN). O gerador imprime a conferência "soma das revendas x DRE da
  marca no painel agregado" — leia a saída.
- **Balanço e Fluxo de Caixa não existem por revenda** e são sempre da marca
  inteira: ~73% do valor do Balanço da KOBE não tem REVENDA atribuída (fica
  centralizado no grupo), enquanto a DRE tem 100% de cobertura. Por isso as
  linhas da planilha são classificadas por `fonte`:
  - sem `fonte` = só DRE → acompanha o filtro (margens, Custo Pessoal/RL,
    Cobertura de Juros);
  - `fonte:'bal'` = só Balanço → sempre da marca inteira, marcada com `†`
    quando a seleção é parcial (liquidez, dívida em R$, composição, endividamento);
  - `fonte:'misto'` = DRE ÷ Balanço → **oculta** com seleção parcial (ROE, ROA,
    Dívida/EBITDA, Floor Plan/EBITDA, giros, PMR, PMP, Ciclo). Mostrar essas
    cruzaria o resultado de N lojas com o patrimônio de todas.

---

## 5. Leitura obrigatória antes de DAX próprio

1. `dictionary/modelo_semantico.md` (se não existir: `gerar_dicionario.py`).
2. `dictionary/regras_negocio.md`.
3. `estrutura_financeira_completa.md` (estrutura contábil) e
   `design_system_relatorios.md` (formato dos relatórios em `reports/`).

---

## 6. Nunca

- Rodar `python` sem ser o do `.venv` (erro do stub da Microsoft Store).
- Escrever/gravar no Power BI — **somente leitura**.
- Exportar dados brutos ou pedir dezenas de milhares de linhas — agregue no servidor.
- Recalcular DRE/Balanço/KPI com DAX próprio quando existe a ferramenta pronta.
- Somar linhas de detalhe da DRE para "conferir" subtotal: custos/despesas vêm
  positivos e **subtraem** nos subtotais. Use o subtotal calculado.
- Esconder ou "ajustar" o CHECK do Balanço / Fluxo de Caixa — sempre reporte.
- Conciliar caixa por REVENDA, ou excluir os caixas 9/99/4 da conciliação — as duas
  coisas quebram a igualdade com o contábil, que registra tudo em CAIXA GERAL.
- Prometer conciliação de caixa por DIA: o modelo contábil não tem data, só `PERIODO`.
- Rodar o COAF com `--enviar` sem o usuário ter conferido os PDFs — o padrão é
  modo revisão, de propósito: o e-mail vai para gerente de loja.
- Usar `--forcar-envio` na rotina agendada. Ele ignora a regra de incremento e
  redispara TUDO; é para uso pontual, sob pedido explícito do usuário.
- Rotear a DMF por usuário (`NOME_USUARIO`) ou para todos os caixas do cliente —
  o destino é o responsável pelo caixa do **lançamento-gatilho**, só ele.
- Mandar o relatório consolidado para quem não é do COAF.
- Agrupar cliente por `CAIXAS[CLIENTE]` no COAF — o código `30184` é genérico e
  aparece com clientes diferentes. A chave é o nome extraído de `HISTORICO`.
- Apagar ou reescrever `coaf_deteccao` — é append-only por requisito do COAF.
- Expor segredos: credenciais só no `.env`.

## 7. Ao responder a diretoria

Cite sempre **período**, **filtro (empresa/visão)** e **medida/ferramenta usada**.
Análises formais vão para `reports/` em Markdown.
