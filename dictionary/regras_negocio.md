# Regras de negócio da empresa

> **Este arquivo é mantido manualmente por você (gestor).** Diferente do
> `modelo_semantico.md` (gerado automaticamente), aqui ficam as regras,
> definições e nomenclaturas internas que o Claude precisa conhecer para
> interpretar os dados corretamente ao responder a diretoria.
>
> Preencha as seções abaixo. Elas começam vazias/comentadas — remova os
> comentários (`<!-- -->`) e escreva conforme a realidade da empresa.

---

## Definições de indicadores

<!--
Explique como a empresa define cada indicador-chave. Exemplos:

- **Margem bruta**: (Faturamento - CMV) / Faturamento. A medida oficial no
  modelo é [Margem Bruta %].
- **Ticket médio**: Faturamento / Nº de pedidos no período.
- **Inadimplência**: títulos vencidos há mais de 30 dias sobre o total a receber.
-->

---

## Metas

<!--
Registre as metas vigentes para o Claude comparar com o realizado. Exemplos:

- Meta de faturamento mensal: R$ ___.
- Meta de margem: __%.
- Meta de novos clientes/mês: ___.
-->

---

## Sazonalidades

<!--
Descreva padrões sazonais que afetam a leitura dos números. Exemplos:

- Dezembro concentra ~20% do faturamento anual.
- Janeiro/fevereiro são historicamente fracos (comparar sempre com o mesmo
  período do ano anterior, não com o mês anterior).
-->

---

## Nomenclaturas internas e sinônimos

<!--
Liste termos internos e sinônimos de produtos/itens para as buscas textuais
funcionarem bem. Exemplos:

- "cloro" pode aparecer como: hipoclorito, tricloro, cloro granulado.
- "frete" pode aparecer como: transporte, logística, entrega.
- Nome interno da filial matriz nos relatórios: "Filial 01" / "Matriz".
-->

---

## Modelo de Lançamentos de Caixa (dataset `controlador`)

Dataset Power BI: `lancamentos_financeiros` (apelido `controlador` em
`config/datasets.yaml`). Contém os lançamentos de caixa das revendas.

- **Tabela `CAIXAS`**: um lançamento por linha. Colunas principais:
  `REVENDA`, `EMPRESA` (grupo/marca — ex.: KOBE, ROYAL ENFIELD, RENAULT, MIT,
  MULT BOATS, MEGA STORE), `CAIXA` (código do caixa dentro da revenda),
  `VALOR`, `PAGAR_RECEBER` (`"R"` = recebimento, `"P"` = pagamento),
  `OPERACAO`, `HISTORICO`, `ORIGEM`, `DATA`, `CLIENTE`, `TITULO`.
- **`VALOR` já vem com sinal aplicado**: recebimentos (`R`) positivos,
  pagamentos (`P`) negativos. Para saldo, basta `SUM('CAIXAS'[VALOR])` — não
  inverta o sinal com base em `PAGAR_RECEBER`, já está correto.
- **Regra confirmada com o gestor (04/08/2026): os códigos de `CAIXA` = 9, 99
  e 4 não representam saldos de caixa reais** — sempre excluir esses códigos
  ao calcular ou apresentar saldo por caixa/revenda/empresa.
- **Regra confirmada com o gestor (04/08/2026): dentro do grupo Multicar Mits
  (revendas `MULTICAR MITS MATRIZ` e `MULTICAR MITS VV`), os caixas 8 e 14
  também não são saldos válidos** — excluir sempre, nas duas revendas do
  grupo (não só onde apareceram originalmente: caixa 8 estava zerado só na
  Matriz, caixa 14 só na VV, mas a exclusão vale para o grupo inteiro).
  Filtro DAX consolidado:
  ```
  FILTER(
      'CAIXAS',
      'CAIXAS'[CAIXA] <> "9" && 'CAIXAS'[CAIXA] <> "99" && 'CAIXAS'[CAIXA] <> "4"
      && NOT(
          'CAIXAS'[REVENDA] IN {"MULTICAR MITS MATRIZ", "MULTICAR MITS VV"}
          && ('CAIXAS'[CAIXA] = "8" || 'CAIXAS'[CAIXA] = "14")
      )
  )
  ```
- **Não há medidas oficiais cadastradas neste dataset** (`INFO.VIEW.MEASURES()`
  vazio) — qualquer soma/cálculo aqui é ad-hoc, sempre avisar que não é
  medida oficial.
- **Base é ao vivo/refresh contínuo** (`isRefreshable: true`) — números podem
  mudar entre consultas em momentos diferentes (lançamentos reclassificados
  entre caixas, por exemplo). O total geral tende a ficar estável mesmo
  quando a distribuição por caixa individual muda.
- **Limitação técnica**: `INFO.TABLES()` / `INFO.COLUMNS()` / `INFO.MEASURES()`
  puros retornam erro 400 (`DatasetExecuteQueriesError`) neste dataset — use
  as variantes `INFO.VIEW.TABLES()`, `INFO.VIEW.COLUMNS()`,
  `INFO.VIEW.MEASURES()` para extrair o esquema.
- **Armadilha de DAX (07/08/2026, descoberta construindo `powerbi/dax_auditoria.py`):
  depois de `SELECTCOLUMNS`, `TOPN` precisa ordenar pelo *alias* novo
  (`[VALOR]`), nunca pela coluna qualificada original (`'CAIXAS'[VALOR]`) —
  ela deixa de existir naquele contexto e a API só devolve 400 genérico, sem
  detalhe.** Além disso, o argumento de ordem do `TOPN` é **0 = descendente,
  1 = ascendente** (contraintuitivo) — e, mesmo com o dígito certo, o `TOPN`
  garante o **conjunto** certo de linhas mas não a **ordem** delas no
  resultado; sempre feche a consulta com `ORDER BY [alias] ASC|DESC` no nível
  do `EVALUATE` (mesmo padrão já usado em `periodos_disponiveis()` de
  `dax_financeiro.py`).
- **Armadilha de DAX**: `SUMX(CURRENTGROUP(), ...)` dentro de
  `SUMMARIZECOLUMNS` retorna 400 nesta API — use `SUM(...)` direto (o
  contexto de grupo já é implícito nas expressões de agregação do
  `SUMMARIZECOLUMNS`, `CURRENTGROUP()` é coisa de `GROUPBY`).
- **Regra confirmada com o gestor (04/08/2026): em rankings de "maiores
  despesas" (lançamentos com `PAGAR_RECEBER` = "P"), excluir sempre as
  origens cujo texto contém `"TRANSF"`** (ex.: "TRANSF. SALDO CAIXA",
  "TRANSFERENCIA SALDO DE CAIXA", "TRANSF. CAIXA P/ SICOOB/SANTANDER/
  BRADESCO/ITAU/CEF") — são transferências internas entre caixas/bancos do
  próprio grupo, não despesas reais. Sem essa exclusão elas dominam o
  ranking (ex.: "TRANSF. SALDO CAIXA" sozinha somava ~R$ 5,9 milhões,
  maior que qualquer despesa operacional real).

---

## Auditoria de Lançamentos de Caixa (dataset `controlador`)

Planejamento completo em `C:\Users\Controladoria\.claude\plans\crie-um-planejamento-para-sprightly-glade.md`.
Esta seção é a referência semântica que o código de auditoria (`powerbi/dax_auditoria.py`) e o
painel de exceções devem seguir — se este texto e o código divergirem, este texto é a verdade.

### Colunas de identidade (adicionadas em 07/08/2026)

- **`USUARIO`** (Integer) e **`NOME_USUARIO`** (Text) identificam quem lançou cada linha. Usar
  `NOME_USUARIO` para exibição; `USUARIO` é o ID interno do Linx Apollo.
- 150 usuários distintos na base (medição de 07/08/2026).

### As 28 linhas de "SALDO INICIAL DA PLANILHA"

Em 01/01/2025, `HISTORICO = "SALDO INICIAL DA PLANILHA"`, uma linha por caixa (R$ 489.416,50 no
total). **Registram o saldo de fechamento de 2024** para iniciar 2025 — não são lançamentos
operacionais. Por isso, **não têm `NOME_USUARIO`, `ORIGEM` nem `TITULO`** (são as únicas 28 linhas
da base sem usuário). Isso é esperado, não é falha de digitação.

**Toda regra de auditoria deve excluir essas 28 linhas** (via `PAGAR_RECEBER = "R"` + `DATA =
DATE(2025,1,1)` + `HISTORICO = "SALDO INICIAL DA PLANILHA"`, ou de forma mais simples,
`NOT(ISBLANK('CAIXAS'[NOME_USUARIO]))`), senão elas geram falso-positivo recorrente em qualquer
regra que dependa de usuário, origem ou título.

### Escopo de caixas auditados

A auditoria roda sobre os **mesmos caixas operacionais do painel de saldos** — exclusão de 9, 99, 4
e (no grupo Multicar Mits) 8 e 14, conforme filtro já documentado acima.

**Risco residual aceito e registrado (decisão do gestor, 07/08/2026):** os caixas excluídos
concentram **46,3% de todo o volume movimentado** (caixa 9 sozinho: R$ 18,6 milhões movimentados,
R$ 1,14 milhão de saldo — medição de 07/08/2026). Os dois estornos de maior valor encontrados na
varredura inicial (R$ 100.000,00 e R$ 96.050,74, ambos em 30/06/2026) caíram no caixa 9 e ficam fora
do escopo da auditoria automática. Se precisar investigar o caixa 9 especificamente, rode as
consultas de auditoria manualmente sem o filtro de escopo.

### Segregação de funções — regra de desenho, não só de dado

O usuário `JÚLIO CÉSAR BARCELOS DE BARROS JÚNIOR` concentra o maior volume e alcance da base (1.942
lançamentos, R$ 13,1 milhões, 15 de 19 revendas, 111 dos 228 estornos — medição de 07/08/2026) e é
quem normalmente vai rodar/revisar esta auditoria. Isso é esperado do papel de controller, **mas**:

- Nenhuma regra de auditoria abre exceção para ninguém, inclusive para esse usuário.
- Toda exceção cujo `USUARIO` seja o do próprio revisor **deve ser marcada e segregada** num bloco
  separado "Requer revisão independente" no relatório — não pode ficar misturada nem ser
  autorrevisada. Vai para um segundo par de olhos (diretoria/sócios).
- Quando o mesmo usuário lança **e** estorna a mesma operação (título), isso é sinalizado
  explicitamente (regra R12), mesmo que o valor seja pequeno.

### Catálogo de regras (R1–R14)

Cada regra é uma consulta DAX independente que devolve linhas de exceção (nunca um score/nota).
Todas nascem ativas (as colunas de usuário já existem). Thresholds abaixo são o ponto de partida —
ajustar com o gestor conforme a taxa de falso-positivo da calibragem inicial.

| ID | Regra | Threshold inicial | Lógica |
|---|---|---|---|
| R1 | Recebimento estornado no mesmo dia | valor ≥ R$ 5.000 | agrupar por `REVENDA`+`CLIENTE`+`DATA`: soma de `R` e soma de `P` com "ESTORNO" no `HISTORICO` se cancelam (`\|ΣR+ΣP\| < 0,01`) |
| R2 | Estorno com valor positivo | valor > 0 | `HISTORICO` contém "ESTORNO" e `VALOR > 0` |
| R3 | Estorno sem origem classificada | todos | `HISTORICO` contém "ESTORNO" e `ORIGEM = " -"` |
| R4 | Fracionamento | N ≥ 4 lançamentos idênticos | agrupar por `CLIENTE` + `ORIGEM` + `DATA` + `VALOR`, contar linhas |
| R5 | Lançamento em fim de semana | todos | `WEEKDAY('CAIXAS'[DATA]) IN {1,7}` |
| R6 | Cobertura de título por revenda — **informativo, não é exceção** | — | ver nota abaixo — a hipótese original de "lacuna de sequência" não se sustentou |
| R7 | Saldo do caixa negativo | saldo < 0 em qualquer data | saldo acumulado por `REVENDA`+`CAIXA` ao longo do tempo |
| R8 | Transferência interna sem contraparte | descasamento ≠ 0 | soma de `ORIGEM` contendo "TRANSF" por `REVENDA`, entradas vs. saídas |
| R9 | Data fora da janela plausível | `DATA` < 01/01/2025 ou > hoje + 1 dia | — |
| R10 | Concentração atípica por cliente/origem | desvio > 3σ da média própria de 90 dias | primeira versão usa a estatística da própria janela, sem baseline persistido (Fase 4 refina) |
| R11 | Valor redondo alto | múltiplo de 1.000 e ≥ R$ 10.000 | `MOD(ABS(VALOR), 1000) = 0` |
| R12 | Mesmo usuário lança e estorna | valor ≥ R$ 5.000 | mesma lógica de R1, restrita a `NOME_USUARIO` igual nas duas pernas |
| R13 | Usuário fora do padrão de revendas | revenda com < 5% dos lançamentos do usuário | comparar distribuição de `REVENDA` por `NOME_USUARIO` |
| R14 | Autoconcessão | todos | `ORIGEM` contém "ADIANTAMENTO", `NOME_USUARIO` aparece dentro de `HISTORICO` (`SEARCH`) |

**Nota sobre R1/R12 — por que não é "mesmo TITULO":** `CAIXAS[TITULO]` é o número
sequencial do próprio lançamento no caixa (ex.: `184786`), **não** o título financeiro
externo citado em `HISTORICO` (ex.: "Titulo(CR)27128-01"). Um recebimento e seu estorno
têm `TITULO` diferentes — a chave de pareamento real é `REVENDA`+`CLIENTE`+`DATA` com os
valores se cancelando. Confirmado nos dados: título `184786` (R$ 96.050,74, recebimento)
e título `184985` (-R$ 96.050,74, estorno) são linhas distintas do mesmo cliente no mesmo dia.

**Nota sobre R6 — por que virou informativo:** a premissa de que `TITULO` é um contador
privado por revenda é **falsa**. Medido em 07/08/2026: toda revenda tem `TITULO` no mesmo
intervalo global `1–186758`, com densidade entre 0,05% (Mult Motors Omoda) e 1,5% (Kobe
Nissan GV) — é um ID compartilhado por um sistema maior que `CAIXAS` (o Linx Apollo
inteiro), não um contador exclusivo de lançamentos de caixa. A versão original da regra
("gap = (máximo-mínimo+1) - distintos") chegou a apontar 186.749 números "faltando" numa
revenda de baixo volume — ruído puro, não lançamento excluído. R6 hoje só reporta
mínimo/máximo/distintos/densidade por revenda, sem alegar lacuna.

### Achados de referência (medição de 07/08/2026 — usar para validar o código)

Se a implementação das regras não reproduzir estes números, a regra está com bug:

- R1/R12: título 56090-01 (R$ 100.000,00) e título 27128-01 (R$ 96.050,74), KOBE NISSAN GV, ambos
  recebidos e estornados em 30/06/2026 pelo mesmo usuário (caixa 9 — fora do escopo padrão).
- R2: MULT BOATS teve um estorno de +R$ 64.000,00; MULTICAR MITS VV +R$ 47.848,50; MULTICAR ROYAL -
  VI +R$ 25.465,02. 228 estornos no total na base.
- R4: cliente 141331, origem "137 - ADIANTAMENTO CHEQUE", 30/06/2026 — 6 lançamentos de
  -R$ 4.490,00 (total R$ 26.940,00).
- R5: exatamente 6 lançamentos em sábado, 0 em domingo (base toda).
- R8: descasamento total de transferências internas no grupo = R$ 647.759,00.
- R9: um lançamento datado de 05/07/2041 (MULTICAR MITS MATRIZ, -R$ 30,00) — claramente erro de
  digitação de data.
- R14: 16 casos de autoconcessão em 1.499 lançamentos de adiantamento.
- **Teste negativo obrigatório**: as 28 linhas de "SALDO INICIAL DA PLANILHA" não podem aparecer em
  nenhuma regra.

---

## Conciliação de Caixa (financeiro x contábil)

Implementada por `powerbi/dax_conciliacao.py` (consultas), `analysis/conciliacao_caixa.py`
(motor + relatório) e a tool MCP `relatorio_conciliacao_caixa`. Parâmetros em
`config/conciliacao_caixa.yaml`. **Se esta seção e o código divergirem, corrija os dois juntos.**

### A pergunta

O saldo de caixa do livro-caixa financeiro (`CAIXAS`, dataset `controlador`) bate com o
saldo da conta contábil de CAIXA GERAL (`lancamentos`, dataset padrão)?

### As três decisões que fazem a conciliação funcionar

**1. A chave é `EMPRESA`, nunca `REVENDA`.** Transferência de saldo de caixa para caixa
gera duas linhas no livro-caixa e **nenhum lançamento contábil** — o dinheiro não saiu da
conta CAIXA GERAL. Se as pernas estão em revendas diferentes da mesma empresa, por revenda
os dois lados nunca fecham e por empresa fecham. Medido em 03/2026: KOBE VV mostrou
66.555,98 no contábil contra 17.343,93 no financeiro, e o total KOBE do mês fechou com
R$ 1,00 de diferença.

**2. A granularidade é MENSAL — não existe conciliação diária.** A tabela `lancamentos`
**não tem coluna de data**: o único marcador temporal é `PERIODO`, texto `MM/AAAA`. Não há
saldo contábil "do dia 15" para comparar com o fechamento do dia. O lado financeiro é
sempre cortado no **último dia do mês**. Conciliar por dia exigiria uma data de lançamento
no modelo contábil, que hoje não existe.

**3. Nada é excluído do lado financeiro.** Os caixas 9/99/4 e os 8/14 da Multicar Mits
**entram**, e as 28 linhas de `"SALDO INICIAL DA PLANILHA"` também. É o oposto das regras
de auditoria e dos painéis de saldo, e é obrigatório: a contabilidade registra tudo em
CAIXA GERAL. Verificado — com esses caixas, ROYAL fecha centavo a centavo nos 19 meses de
01/2025 a 07/2026; sem eles, não fecha em nenhum.

### Duas contas de CAIXA GERAL, dois planos de contas

| Conta | Descrição | Empresas |
|---|---|---|
| `11101010001` | CAIXA GERAL | KOBE, MULT BOATS, MULT SOLUÇÕES, OMODA, RENAULT, ROYAL |
| `11111001` | CAIXA GERAL | CORRETORA, MEGA STORE, MIT |

Contas de banco (`11102*`, `1112*`) **não entram**: o livro-caixa só controla espécie.

### Mapa de empresas (o nome muda entre os dois modelos)

`MULT CORRETORA` → `CORRETORA` e `ROYAL ENFIELD` → `ROYAL`; as demais são iguais. O mapa
está por extenso em `config/conciliacao_caixa.yaml` de propósito: empresa nova que não
esteja lá aparece no relatório como "sem contrapartida", em vez de sumir em silêncio.

### Diferença de abertura ≠ divergência do mês

A diferença total é decomposta em duas parcelas, com providências diferentes:

- **Abertura** — constante, nasce em 01/01/2025: o `"SALDO INICIAL DA PLANILHA"` que a
  planilha trouxe é menor que o saldo contábil fechado em 12/2024. Não é erro de
  lançamento do período; só sai com ajuste de saldo inicial. É descontada do primeiro mês
  antes de classificar, senão toda empresa com abertura errada apareceria como divergente
  em 01/2025.
- **Divergência do mês** — variação da diferença acumulada de um mês para o outro. Zero
  significa que os dois livros registraram exatamente o mesmo movimento naquele mês, por
  maior que seja o resíduo de abertura arrastado.

### Transferências: só caixa↔caixa entram no diagnóstico

Das 9 origens com `TRANSF` (medição de 20/08/2026), só duas são caixa↔caixa —
`200 - TRANSFERENCIA SALDO DE CAIXA` e `707 - TRANSF. SALDO CAIXA`. As outras
(`TRANSF. CAIXA P/ SANTANDER/BRADESCO/ITAU/CEF/SICOOB` e `TRANSF. SANTANDER P/ CAIXA`)
têm contrapartida em **conta bancária** e **são contabilizadas**. Filtrar por `"TRANSF"`
solto fazia toda empresa aparecer com líquido diferente de zero todo mês — inclusive KOBE,
que concilia centavo a centavo. O padrão correto está em
`config/conciliacao_caixa.yaml` (`origens_transferencia_interna`).

Um líquido caixa↔caixa diferente de zero **não é exceção por si** — a contrapartida pode
estar classificada em outra origem e devidamente contabilizada. O relatório só mostra essa
pista cruzada com um mês já apontado como divergente.

### Medição de referência (20/08/2026, corte em 31/07/2026)

Se a implementação não reproduzir estes números, há bug:

| Empresa | Saldo contábil | Saldo financeiro | Diferença | Origem |
|---|---:|---:|---:|---|
| KOBE | 497.960,64 | 497.960,64 | 0,00 | 2 meses com R$ 1,00 de corte |
| MEGA STORE | 83.680,35 | 83.680,35 | 0,00 | — |
| MULT BOATS | 251.552,34 | 251.552,34 | 0,00 | — |
| MULT SOLUÇÕES | 70,00 | 70,00 | 0,00 | — |
| OMODA | 6.946,33 | 6.946,33 | 0,00 | — |
| ROYAL | 147.008,84 | 147.008,84 | 0,00 | — |
| CORRETORA | 75.546,72 | 17.912,80 | (57.633,92) | abertura |
| MIT | 142.865,03 | 77.045,90 | (65.819,13) | abertura |
| RENAULT | 173.249,56 | 146.003,18 | (27.246,38) | abertura |
| **TOTAL** | **1.378.879,81** | **1.228.180,38** | **(150.699,43)** | |

- **Movimento do período: bate em 100% dos meses de todas as empresas**, exceto os R$ 1,00
  da KOBE em 03/2026.
- Os R$ 150.699,43 são **integralmente** saldo de abertura de CORRETORA, MIT e RENAULT — a
  CORRETORA nunca teve linha de `"SALDO INICIAL DA PLANILHA"`.
- O R$ 1,00 da KOBE é **corte de período**, não erro de valor: NF 22121 (KOBE NISSAN IP,
  cliente JOSE SILVEIRA DOS REIS JUNIOR) entrou no livro-caixa em 25/03/2026 e foi
  cancelada em 07/04/2026; a contabilidade registrou entrada e cancelamento no mesmo
  período. Reverte sozinho em 04/2026.
- **Nenhum desses números é medida oficial**: os dois modelos estão sem medidas
  cadastradas. Tudo é soma direta de `CAIXAS[VALOR]` e `lancamentos[VALOR_AJUSTADO]`.

---

## COAF / Recebimentos em espécie (dataset `controlador`)

Implementado por `powerbi/dax_coaf.py` (consulta), `analysis/coaf_especie.py` (detecção),
`analysis/dmf_pdf.py` (DMF em PDF), `notify/email_zoho.py` (envio) e
`local_data/coaf_estado.py` (histórico). Parâmetros editáveis em `config/coaf.yaml`;
destinatários em `config/responsaveis_caixa.yaml`. **Se esta seção e o código divergirem,
corrija os dois juntos.**

### A obrigação

O setor de COAF precisa comunicar quando um cliente paga **R$ 30 mil ou mais em espécie
dentro de 6 meses**. Ao cruzar o limiar, o responsável pelo caixa é acionado para preencher
e assinar a **DMF (Declaração de Movimentação Financeira)**.

### O que conta como "espécie" — e o risco assumido

**A tabela `CAIXAS` não tem coluna de forma de pagamento.** Não existe `FORMA_PAGAMENTO`,
`MOEDA` nem nada equivalente; o que mais se aproxima é `ORIGEM`, que mistura meio de
pagamento com classificação de despesa.

**Regra adotada (decisão do gestor, 19/08/2026):** todo recebimento (`PAGAR_RECEBER = "R"`)
conta como espécie, **exceto** transferências internas — `ORIGEM` contendo `TRANSF`,
`DEPOSITO` ou `SAQUE`. São movimentação do próprio grupo, não dinheiro de cliente.

⚠️ **Risco registrado, aceito conscientemente pelo gestor:** com essa regra, **contam como
espécie** origens que declaram outro instrumento de pagamento e origens que nem são
pagamento de cliente. Medição de 19/08/2026, recebimentos dos últimos 12 meses:

| ORIGEM | Natureza real | Valor |
|---|---|---|
| `417 - VENDA CARTAO DEB/CRED` | cartão | R$ 949.762,59 |
| `349 - ADIANTAMENTO FORNECEDOR` | fornecedor, não cliente | R$ 848.789,74 |
| `203 - ADIANTAMENTO DESPESA VIAGEM` | funcionário, não cliente | R$ 257.692,97 |
| `346 - TED / DOC / PIX` | eletrônico | R$ 222.370,19 |
| `3001 - CHEQUE CAIXA` | cheque | R$ 113.000,00 |
| `1042 - BOLETO - FATURAMENTO` | boleto | R$ 11.973,23 |

Mitigação: a exclusão é uma linha em `config/coaf.yaml` (`exclusoes_origem.padroes` ou
`.exatas`), e a coluna `ORIGEM` aparece no alerta e no PDF da DMF, para o compliance
revisar. Para conferir o que existe hoje, use `dax_coaf.origens_de_recebimento()` — ela
lista **todas** as origens do período, inclusive as atualmente excluídas.

### Identidade do cliente — a chave é o código, não o nome

**A chave de agregação e de identidade é `CAIXAS[CLIENTE]`** (o código) — decisão final do
gestor (26/08/2026), depois de duas versões anteriores terem usado o nome como chave e causado
reenvio indevido em produção (ver histórico abaixo). Confirmado em 25/08/2026 contra 8.382
recebimentos: nenhum `CAIXAS[CLIENTE]` aparece com mais de um nome distinto — o código é
identidade estável, o nome não é.

**Como o nome ainda entra:** é só informação de **exibição** (DMF, e-mail), sem afetar mais a
chave nem o controle de notificação. Fonte primária: `CAIXAS[NOME_CLIENTE]` (cadastro do Power
BI, cobertura de 100% confirmada em 25/08/2026). Fallback: o parser de `HISTORICO`
(`extrair_nome_cliente`), usado só quando `NOME_CLIENTE` vem em branco. Duas variações reais do
texto de `HISTORICO`:

```
Ref. Adiantamento: 4 Cliente:VANDERLEY FRANCISCO BARBOSA RAMOS     (sem espaço)
Ref. Nota(s) Fiscal(is): 68391 30608 Cliente: ALICE PEREIRA COSTA  (com espaço)
```

Quando nenhuma das duas fontes traz nome para NENHUM lançamento do código, o caso fica com
`nome_identificado = false` e o texto `(sem nome no histórico — código <código>)` — **a DMF sai
com o campo 1 em branco**, sinalizado no alerta, no PDF, e roteado só para o e-mail do COAF
(rede de segurança), nunca para um responsável externo. Se só ALGUNS lançamentos do código têm
nome (ex.: um SAQUE sem "Cliente:" ao lado de uma nota fiscal que tem), o caso usa o primeiro
nome encontrado no grupo — não precisa mais de backfill manual, porque agrupar por código já
une esses lançamentos automaticamente.

**Por que não é mais o nome — histórico do problema:** até 25/08/2026 a chave era o nome
extraído do `HISTORICO`. Em 26/08/2026 o nome passou a vir de `NOME_CLIENTE` (mais completo,
cobre casos como transferência entre caixas que o `HISTORICO` não identifica), mas por ser
cadastro (master data) ele pode ser reformatado com o tempo — diferente do texto do
`HISTORICO`, imutável. Isso se confirmou na hora: o código 225456 tinha "AGNALDO CEZAR BATISTA
DE SOUZA" no histórico (chave de 3 notificações reais entre 19/08 e 24/08) e `NOME_CLIENTE`
resolveu como "AGNALDO CEZAR SOUZA" — chave diferente, cliente já notificado tratado como novo,
DMF de "estreia" reenviada a destinatários reais no mesmo dia. Uma migração pontual (reavaliação
do histórico do DuckDB para a janela de 19/02 a 24/08/2026, marcando tudo que fosse encontrado
como já notificado — `scripts/coaf_migrar_nome_cliente.py`) resolveu o caso concreto, mas o
risco de o mesmo tipo de reenvio se repetir a cada correção de cadastro continuava — por isso o
gestor decidiu, ainda em 26/08/2026, tirar o nome da equação por completo e usar o código como
chave.

### Janela móvel, não janela fixa

O limiar é testado em **toda janela de 6 meses que termina numa data de recebimento**, não
só na que termina hoje. Sem isso, fracionamento que cruza a borda do semestre escapa:
4 × R$ 8.000 entre janeiro e junho somam R$ 32.000, mas uma janela fixa a partir de 19/08
começaria em 19/02 e veria só R$ 24.000. A janela reportada na DMF é a de **maior
acumulado** — a exposição máxima do período.

### Escopo e caixas

- **Escopo do alerta: grupo inteiro.** O acumulado soma todas as revendas e empresas, senão
  fracionamento entre lojas passa batido. O relatório sempre mostra a **quebra por empresa**.
- **O caixa 9, em qualquer revenda, é EXCLUÍDO da apuração** (decisão do gestor,
  25/08/2026) — nem chega a ser consultado no DAX (`config/coaf.yaml`, `caixas_excluidos`).
- **Os caixas 99 e 4 (e 8/14 na Multicar Mits) ENTRAM na apuração** — ao contrário de toda
  regra de auditoria e dos painéis de saldo. O COAF olha o dinheiro que entrou, não a
  validade do saldo, e esses caixas concentram volume movimentado relevante e recebimentos
  acima do limiar. Eles são **sinalizados** (marcador `*` no PDF, ⚑ no relatório), não
  filtrados — diferente do caixa 9.
- As 28 linhas de `"SALDO INICIAL DA PLANILHA"` continuam excluídas, via
  `NOT(ISBLANK('CAIXAS'[NOME_USUARIO]))`.
- Datas futuras são descartadas: a base tem lançamentos com `DATA` até 2041.

### Histórico permanente ≠ deduplicação

Requisito explícito do setor de COAF: **o histórico de clientes detectados nunca pode ser
perdido.** Como o job roda de 30 em 30 minutos, é preciso deduplicar — mas a deduplicação
decide **apenas se dispara e-mail**.

| Tabela (DuckDB local) | Papel |
|---|---|
| `coaf_deteccao` | Registro permanente, **append-only**. Nunca sofre `DELETE` nem `UPDATE`. |
| `coaf_deteccao_lancamento` | Recebimentos de cada detecção. Sem esta cópia a DMF enviada não pode ser reconstruída — a base é de refresh contínuo e lançamentos migram de caixa. |
| `coaf_notificacao` | Quem já foi avisado. **Única** tabela que a deduplicação consulta. |

Regras: identidade do lançamento é `sha1(REVENDA|CAIXA|DATA|TITULO|VALOR|ORIGEM)` — a
tabela não tem chave primária e `TITULO` sozinho não serve (é ID global do Linx Apollo).
Grava-se no máximo uma linha por cliente por dia enquanto o conjunto de lançamentos não
muda; qualquer alteração grava na hora. Reenvio de e-mail só depois de `reenvio_dias`
(padrão 30) **e** havendo lançamento novo.

### Medição de referência (19/08/2026)

Consulta de 12 meses (19/08/2025 a 19/08/2026), janela móvel de 6 meses, limiar R$ 30 mil:

- 3.421 recebimentos após higiene
- **44 clientes acima do limiar** no escopo de grupo
- 3 casos sem nome identificado no histórico

Recorte fixo de 6 meses (19/02 a 19/08/2026), para comparação: 1.678 recebimentos, 1.111
clientes distintos, 26 acima do limiar. A diferença para 44 é esperada — a janela móvel
sobre 12 meses de base avalia janelas que terminaram no passado.

**Nenhum desses números é medida oficial**: o dataset `lancamentos_financeiros` não tem
medidas (`INFO.VIEW.MEASURES()` vazio). Tudo é cálculo próprio sobre `CAIXAS[VALOR]` e deve
ser apresentado como tal.

### Quem recebe a cobrança, e o que vai anexado

A apuração é sempre do **grupo inteiro** — é assim que fracionamento entre lojas é
pego. A cobrança, porém, tem **um dono só**.

| Destinatário | O que recebe |
|---|---|
| Responsável pelo **caixa do lançamento-gatilho** | Uma DMF **por empresa** do grupo em que houve recebimento |
| Setor de COAF (`email_coaf`) | As mesmas DMFs **mais** o relatório consolidado do grupo |

**Lançamento-gatilho** é aquele em que o acumulado do cliente, ordenado por data,
alcança ou ultrapassa o limiar. O destino sai de `REVENDA` + `CAIXA` desse lançamento,
mapeados em `config/responsaveis_caixa.yaml`. Um cliente que comprou em cinco lojas
gera **uma** cobrança, não cinco. O `NOME_USUARIO` do lançamento é registrado no
relatório apenas para rastreabilidade — não é usado no roteamento.

**Não é o lançamento mais recente do período** — é o que cruzou o limiar. A distinção
foi decidida explicitamente pelo gestor (19/08/2026) e só aparece quando o cliente
continua comprando depois de já ter estourado os R$ 30 mil:

| Data | Revenda / caixa | Valor | Acumulado | |
|---|---|---|---|---|
| 10/05 | KOBE NISSAN GV / 2 | 12.000 | 12.000 | |
| 20/05 | KOBE NISSAN VV / 1 | 12.000 | 24.000 | |
| 01/06 | KOBE NISSAN MH / 7 | 12.000 | **36.000** | ← **gatilho** (cruzou aqui) |
| 15/06 | KOBE NISSAN IP / 1 | 5.000 | 41.000 | mais recente, mas irrelevante |

A cobrança vai para **KOBE NISSAN MH / caixa 7**. Razão: quem recebeu o dinheiro que
estourou o limite é quem responde; quem recebeu os R$ 5 mil seguintes não teve nada a
ver com a obrigação. Travado por `test_gatilho_e_quem_cruzou_nao_quem_lancou_por_ultimo`
em `tests/test_coaf_especie.py` — **não troque a regra sem falar com o gestor.**

Nos casos de lançamento único (27 dos 44 detectados em 19/08/2026) as duas leituras
coincidem; a diferença só existe para quem continua movimentando depois de cruzar.

O **relatório consolidado** (`COAF-CONSOLIDADO_*.pdf`) é exclusivo do compliance: traz
a soma do grupo, a quebra por empresa, a identificação do lançamento-gatilho e todos os
recebimentos. Não vai para o responsável pelo caixa, que só precisa das DMFs que tem de
colher assinatura.

### Reenvio: incremento isolado, sem carência por tempo

Depois que um cliente é notificado, o que conta para uma nova DMF é **só o dinheiro
novo** — os valores já declarados não voltam para a conta (decisão do gestor,
19/08/2026). Um cliente notificado com R$ 31 mil que recebe mais R$ 35 mil tem
incremento de R$ 35 mil, não R$ 66 mil, e como esse valor sozinho atinge o limiar, sai
nova cobrança na hora.

Só há dois motivos para notificar:

1. **Estreia** — o cliente nunca recebeu DMF e está acima do limiar.
2. **Novo cruzamento** — o incremento desde a última DMF enviada atinge o limiar
   sozinho. Nesse caso o gatilho é recalculado sobre os lançamentos novos, e a cobrança
   vai para o caixa daquele lançamento.

⚠️ **Não existe mais carência por tempo.** A primeira versão tinha `reenvio_dias: 30` e
ela barrava o caso legítimo junto com o ruído: um cliente notificado que recebesse mais
R$ 35 mil dez dias depois ficava sem aviso. O que segura o ruído hoje é o próprio limiar
do incremento — pingado de R$ 200 não dispara nada até somar R$ 30 mil por conta
própria. O rastreamento é por hash de lançamento (`coaf_deteccao_lancamento` cruzado com
`coaf_notificacao` de status `enviado`), não por data.

A DMF continua **cumulativa** (a janela de 6 meses inteira, como exige a declaração),
com as linhas ainda não declaradas marcadas como **NOVO** no demonstrativo, e um anexo
**complementar** só com elas.

A flag `--forcar-envio` ignora essa regra e notifica todos os casos acima do limiar;
serve para redisparar depois de corrigir `config/responsaveis_caixa.yaml`, e **não** deve
entrar na tarefa agendada. Não altera o histórico.

⚠️ **`config/responsaveis_caixa.yaml` está em configuração de TESTE** (19/08/2026):
todas as 48 combinações revenda + caixa apontam para o mesmo destinatário, usado para
validar o fluxo de envio ponta a ponta. **Trocar pelos responsáveis reais antes de
entrar em produção.**

### Modo de operação

O job roda em **modo revisão por padrão**: gera alertas, histórico e PDFs, mas **não envia
e-mail**. O envio real exige a flag `--enviar`. Agendamento local por Agendador de Tarefas
do Windows (`scripts/coaf_agendar.ps1`), seg–sex 07h–19h e sáb 07h–12h, a cada 30 minutos,
na sessão do usuário logado — exigência do cache de token do `device_code`.


---

## Observações gerais

<!--
Qualquer contexto adicional relevante: estrutura societária, principais
fornecedores, política de descontos, etc.
-->
