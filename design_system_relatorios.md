# DESIGN SYSTEM — Relatórios Financeiros Grupo Mult

**Documento normativo. Cumprimento obrigatório e integral em toda entrega de relatório financeiro (DRE, Balanço Patrimonial, Fluxo de Caixa).** Não é sugestão, não é referência opcional. Se uma entrega conflitar com este documento, a entrega está errada.

## 0. Precedência e escopo

1. **O QUE calcular/exibir** (linhas, ordem, fórmulas, sinais, CHECKs): `estrutura_financeira_completa.md` + `powerbi/dax_financeiro.py`. Este documento **não** redefine estrutura — apenas referencia. Nunca duplicar essas regras aqui nem na entrega.
2. **COMO apresentar**: este documento. Vale para os 3 relatórios e para os 2 formatos de saída:
   - **PDF** → padrão institucional (companhia de capital aberto): sóbrio, grafite + azul corporativo.
   - **Artefato HTML** → padrão moderno (Claude/Apple): fundo branco, limpo, dinâmico.
3. **Proibido perguntar ao usuário** sobre qualquer item já decidido aqui (cores, fontes, formatação de número, cabeçalho, nomes de arquivo). Perguntar apenas: período, empresa/consolidado, modo (mensal/trimestral/anual) e formato (PDF ou artefato) — e somente se não estiverem no pedido.

## 1. Identidade — obrigatório em toda entrega

| Elemento | Regra fixa |
|---|---|
| Título do emissor | `GRUPO MULT — [Empresa]`. Consolidado: `GRUPO MULT — Consolidado`. Nunca só "Grupo Mult", nunca logo de montadora. |
| Nome do relatório | `Demonstração do Resultado do Exercício (DRE)` / `Balanço Patrimonial` / `Demonstração do Fluxo de Caixa — Método Indireto` |
| Subtítulo obrigatório | `Período: MM/AAAA · Modo: [mensal|trimestral|anual|acumulado até MM/AAAA] · Valores em R$` |
| Rodapé obrigatório | `Fonte: lançamentos contábeis (Power BI · VALOR_AJUSTADO) · Gerado em DD/MM/AAAA · Uso gerencial interno — não auditado` + paginação `Página X de Y` (PDF) |
| Marcas do grupo | Citar apenas se o relatório for segmentado por empresa/marca: Multicar (Multimarcas/Megastore), Kobe Nissan, Multicar Renault, Multicar Mitsubishi, Royal Enfield, Yamaha Náutica (Mult Boats), Omoda & Jaecoo. **Nunca inserir logos de montadoras** (uso de marca de terceiros); só texto. Logo do grupo somente se houver arquivo fornecido pelo usuário em `assets/`. |
| Idioma | pt-BR em 100% do conteúdo, inclusive rótulos técnicos. |

## 2. Formatação de números — regra única, sem exceção

| Caso | Formato | Exemplo |
|---|---|---|
| Valor monetário | Milhar `.`, sem centavos (arredondar), sem "R$" repetido nas células (o "Valores em R$" fica no subtítulo/cabeçalho da coluna) | `16.777.905` |
| Valor negativo | Entre parênteses, nunca sinal `-` | `(675.000)` |
| Zero / sem movimento | Travessão `–` | `–` |
| Percentual (indicadores) | 1 casa decimal, vírgula | `13,3%` |
| CHECK | Valor + selo `✓ OK` (verde) ou `✗ DIVERGÊNCIA` (vermelho). Tolerâncias: Balanço = 0 (fora de 03/06/09/12 reportar divergência esperada da apuração trimestral, nunca esconder); Fluxo ≤ R$ 5,00 | `0 ✓ OK` |
| Alinhamento | Números sempre à direita, com fonte tabular; texto à esquerda | — |
| Sinal na DRE | Na **apresentação**, linhas subtrativas (custos, despesas, deduções) saem **entre parênteses**, como nos Layouts de exemplo. Atenção: a consulta de `dax_financeiro.py` devolve essas linhas com exibição positiva — converter para parênteses na montagem do relatório. Subtotais não mudam (já vêm corretos). | `(4.200.000)` |

> Em conflito de exibição de sinal, o **Layout de exemplo** de `estrutura_financeira_completa.md` é a verdade final.

## 3. Hierarquia visual das linhas (os 3 relatórios, os 2 formatos)

4 níveis, sempre distinguíveis à primeira vista:

1. **Cabeçalho de bloco** (`1. RECEITA BRUTA...`, `ATIVO CIRCULANTE`, `I. ATIVIDADES OPERACIONAIS`): caixa alta, negrito, com preenchimento de fundo.
2. **Detalhe**: peso normal, sem fundo.
3. **Subtotal de grupo** (`DISPONIBILIDADES`, `VALORES A RECEBER`): negrito, fundo cinza-claro, filete superior fino.
4. **Total-chave** (`= RECEITA LÍQUIDA`, `= EBITDA`, `= LUCRO LÍQUIDO`, `= TOTAL DO ATIVO`, `= CAIXA GERADO...`, saldos de caixa): negrito, fundo destacado, filete duplo ou barra lateral de destaque.
5. Indicadores (`% Margem...`): itálico, cor secundária, logo abaixo do total a que se referem.

Ordem, agrupamento e nomes de linha: **exatamente** os dos arquivos-fonte. Proibido renomear, reordenar, omitir linha zerada (exibir com `–`) ou criar linha nova.

## 4. PDF — padrão institucional (grafite + azul corporativo)

### 4.1 Tokens

| Token | Valor | Uso |
|---|---|---|
| `grafite-900` | `#23272E` | Faixa do cabeçalho de página, título do emissor, texto de totais-chave |
| `grafite-700` | `#3D434C` | Cabeçalhos de bloco (fundo), texto principal secundário |
| `cinza-500` | `#8A9099` | Rodapé, notas, indicadores (%) |
| `cinza-300` | `#D9DCE0` | Filetes de linha (0,5 pt) |
| `cinza-100` | `#F4F5F7` | Fundo de subtotais e zebra leve (opcional, só em tabelas longas) |
| `azul-800` | `#1F4E79` | Cor de destaque única: barra lateral/fundo dos totais-chave, título do relatório, número de página |
| `azul-100` | `#DCE6F1` | Fundo dos totais-chave |
| `verde-check` | `#1E7E34` | Selo ✓ OK |
| `vermelho-check` | `#B02A37` | Selo ✗ e única outra cor permitida |

**Nenhuma outra cor.** Sem gradientes, sem ícones decorativos, sem clipart, sem gráficos coloridos por padrão (gráfico só se pedido, e na mesma paleta).

### 4.2 Página e tipografia

- A4 retrato; margens 18 mm (sup/inf) × 15 mm (lat).
- Fonte: Helvetica/Arial (embutida). Título do relatório 16 pt; emissor 11 pt; cabeçalho de bloco 9,5 pt; corpo de tabela 9 pt; rodapé 7,5 pt. Entrelinha de tabela ~1,35.
- Cabeçalho de página: faixa `grafite-900` com `GRUPO MULT — [Empresa]` à esquerda (branco) e nome do relatório + período à direita; filete `azul-800` de 2 pt sob a faixa. Repetir em toda página.
- Rodapé: filete fino + texto do rodapé obrigatório (Seção 1).

### 4.3 Tabelas

- Sem grades verticais. Só filetes horizontais `cinza-300`; filete duplo sob totais-chave.
- Cabeçalho de colunas (`Linha`, `Valor (R$)` e colunas comparativas) repete a cada quebra de página; **nunca** quebrar página no meio de um bloco — quebrar antes do cabeçalho do bloco.
- 1 demonstração por seção; no combinado, ordem fixa DRE → Balanço → Fluxo de Caixa, cada uma iniciando em página nova.
- CHECKs sempre ao final da demonstração, em caixa discreta com selo colorido.
- Colunas comparativas (se pedidas): período anterior e `Δ%` — mesmo padrão numérico; nunca mais de 4 colunas de valor.

### 4.4 Produção

- Gerar via skill `pdf` (ler a SKILL.md **depois** de já ter os dados).
- Nome do arquivo: `[DRE|Balanco|FluxoCaixa|Financeiro]_GrupoMult_[Empresa|Consolidado]_MM-AAAA.pdf` (`Financeiro` = combinado).

## 5. Artefato HTML — padrão dashboard moderno (referências: Wink/Orbix + shadcn `dashboard-4`, sempre em claro)

Estética-alvo: dashboard SaaS premium **claro** — quase monocromático, muito espaço em branco, cards com borda sutil, dados como protagonista. **Fundo escuro é proibido em qualquer hipótese**, mesmo que a inspiração original seja dark: transpor sempre para claro.

**Implementação**: single-file HTML+CSS+JS. **Não usar** shadcn/React/npm/build — reproduzir o padrão visual do shadcn com CSS puro. Gráficos em SVG inline ou Chart.js via CDN.

### 5.1 Tokens

| Token | Valor | Uso |
|---|---|---|
| Fundo da página | `#F7F7F8` | Fundo geral (cinza quase branco) |
| Fundo de card | `#FFFFFF` | Cards, tabelas, painéis — com borda `borda`, raio 12–16 px |
| `texto-900` | `#1D1D1F` | Texto principal e valores |
| `texto-500` | `#6E6E73` | Rótulos, legendas, "vs. mês anterior" |
| `borda` | `#E8E8ED` | Bordas de card e divisores (1 px) |
| `superficie` | `#F5F5F7` | Linha de cabeçalho de bloco, chips neutros, hover |
| `accent` | `#D97757` | Único acento decorativo: tab/seletor ativo, barra do total-chave, ponto de destaque em gráfico. Uso mínimo |
| `positivo` | texto `#1E7E34` sobre chip `#E7F4EB` | Chips de variação ↑, CHECK ✓, metas atingidas |
| `negativo` | texto `#B02A37` sobre chip `#FBEAEC` | Chips de variação ↓, CHECK ✗, alertas |

- Fonte: `-apple-system, "SF Pro Text", Inter, "Segoe UI", sans-serif`; números com `font-variant-numeric: tabular-nums`.
- Sombra máxima `0 1px 3px rgba(0,0,0,.06)`; grid de 8 pt; sem emojis; sem ícones decorativos coloridos (ícones lineares monocromáticos permitidos).

### 5.2 Layout — grid de 4 colunas (padrão `dashboard-4`)

- Grid responsivo: `1 col` (mobile) → `2 cols` (≥768 px) → `4 cols` (≥1024 px); gap 16 px.
- Ocupação: KPI cards = 1 coluna cada; gráfico principal = **largura total** (4 cols); gráfico/painel secundário = 2 cols; tabelas = largura total.
- Card: fundo `#FFFFFF`, borda 1 px `borda`, raio 12–16 px, padding 20–24 px, estrutura interna header → conteúdo → footer.

### 5.3 Estrutura obrigatória (ordem fixa)

1. **Header**: `GRUPO MULT — [Empresa]` + nome do relatório à esquerda; à direita, **seletor de período em chips** (Mensal | Trimestral | Anual — ativo em `texto-900`/pill branca, estilo Day/Week/Month do Wink; sem dado para o modo, desabilitar o chip) e chip com `MM/AAAA`.
2. **Faixa de KPI cards** (4 cards). Anatomia fixa (padrão shadcn stats):
   - Topo: rótulo em `texto-500`, 12 px, peso normal.
   - Meio: **valor** 24–32 px, semibold, `tabular-nums`, tracking apertado.
   - Rodapé (12 px): **Delta** + legenda `vs. MM/AAAA` em `texto-500` (só quando houver comparativo).
   - **Mini-sparkline** monocromática quando houver série de meses disponível.
   - DRE → Receita Líquida, Lucro Bruto, EBITDA, Lucro Líquido (margens % na legenda do card).
   - Balanço → Total do Ativo, Passivo Circulante, Patrimônio Líquido, CHECK.
   - Fluxo → Caixa Operacional, Investimento, Financiamento, Saldo Final.
3. **Gráfico de evolução** (card de largura total, se houver ≥ 3 períodos): **área com gradiente vertical** — stroke 2 px na cor da série, preenchimento do stroke a 20% de opacidade desvanecendo a 0% (padrão `dashboard-4`); grid **vertical tracejado** em `borda`; eixo X sem linha e sem tick marks, só rótulos em `texto-500`; tooltip com data + valor formatado. DRE: Receita Líquida × Lucro Líquido; Fluxo: barras de variação líquida por mês nas cores de chip. Footer do card com Delta primeiro→último período + legenda. Seletor de intervalo no header do card (ex.: 6/12 meses) se houver série longa.
4. **Painel "Indicadores de saúde"** (card de 2 cols): % Margem Bruta, % EBITDA/RL, % Margem Líquida (DRE) ou CHECKs (Balanço/Fluxo), cada um com valor + selo ✓/✗ em chip. Sem "metas" inventadas — só as definidas em `regras_negocio.md`, se existirem.
5. **Composição (donut)** — só se pedido (ex.: receita por linha de negócio): regra `dashboard-4` — **máx. 5 fatias** (top 4 + "Outros" agregando o resto), rótulo `%` dentro da fatia, separação entre fatias com stroke branco 3–4 px, cantos levemente arredondados, legenda abaixo. Tons dessaturados coerentes com a paleta clara.
6. **Tabelas** por bloco, hierarquia da Seção 3: cabeçalho de bloco em `superficie`; total-chave em negrito com barra lateral `accent` de 3 px; coluna Δ% com Deltas quando houver comparativo.
7. Combinado: **tabs** (DRE / Balanço / Fluxo de Caixa) sob o header — nunca as três em rolagem única.
8. CHECKs ao final da demonstração, com selo.

### 5.4 Componente Delta (variação) — regra única

Adaptação do `Delta` do shadcn; usar em KPI cards, footers de gráfico e colunas Δ%:

- Formato: ícone de direção + valor **absoluto** com 1 casa decimal + `%` (a direção fica no ícone/cor, nunca sinal `-`). Ex.: `↑ 8,2%` · `↓ 1,3%` · `— 0,0%`.
- Cores: positivo `#1E7E34`, negativo `#B02A37`, zero `texto-500`. Duas variantes: **inline** (texto colorido, padrão) e **badge** (chip com fundo `#E7F4EB`/`#FBEAEC`, para KPI cards e tabelas).
- Semântica contábil: a cor segue o **efeito no resultado**, não o sinal aritmético (queda de despesa = verde).

### 5.5 Comportamento

- Single-file (HTML+CSS+JS juntos). Sem `localStorage`.
- Interações permitidas: tabs, seletor de período (se os dados dos modos estiverem embutidos), colapsar/expandir blocos (abertos por padrão), sticky no cabeçalho da tabela, hover sutil, tooltip de gráfico, transições ≤ 200 ms.
- **Opcional** (permitido, não obrigatório): fade-in de entrada dos cards ao carregar — opacidade + leve translateY (≤ 8 px), duração ≤ 400 ms, escalonado ≤ 80 ms entre cards, uma única vez no load. Respeitar `prefers-reduced-motion` (desativar se ativo).
- Proibido: fundo/tema escuro, gradientes de fundo, glow/neon, mascotes/ilustrações, contadores animados, parallax, dados fictícios para "preencher" gráfico (sem série suficiente → omitir o gráfico).
- Responsivo (mín. 360 px); KPI cards empilham em 2×2; tabelas com rolagem horizontal se preciso.

## 6. Checklist de entrega (validar antes de entregar — reprovou, refaz)

1. Estrutura, ordem e nomes de linha idênticos a `estrutura_financeira_completa.md`; nenhuma linha criada/omitida.
2. Totais recalculados na consulta (nunca lidos da base) e **CHECKs exibidos** com selo, mesmo em relatório isolado.
3. Cabeçalho `GRUPO MULT — [Empresa]`, subtítulo com período/modo, rodapé com fonte + "não auditado".
4. Números 100% no padrão da Seção 2 (parênteses, `–`, `13,3%`, alinhados à direita, tabulares).
5. Paleta e tipografia exatas do formato entregue (Seção 4 PDF / Seção 5 artefato); nenhuma cor fora dos tokens.
6. PDF: blocos sem quebra interna, cabeçalhos repetidos, nome de arquivo no padrão 4.4.
7. Período, filtro de empresa e medida/fonte citados (regra do CLAUDE.md).

## 7. Proibições (resumo)

Sem ABS em valores · sem logos de montadoras · sem cores fora dos tokens · sem emojis · sem inventar/renomear/reordenar linhas · sem omitir CHECKs · sem centavos · sem sinal `-` (usar parênteses) · sem fundo escuro/glow/mascotes no artefato · sem dados fictícios em gráficos · sem metas não definidas em `regras_negocio.md` · sem perguntar o que já está decidido aqui.
