# Estrutura Financeira — DRE, Balanço Patrimonial e Fluxo de Caixa

## Como usar este documento

Este arquivo é a referência única (skill) para montar consultas DAX contra o modelo
semântico do Power BI (via API REST) e retornar, de forma estruturada:
- a **DRE**,
- o **Balanço Patrimonial**, e/ou
- o **Fluxo de Caixa (método indireto)**.

Quando o usuário pedir uma **"DRE atualizada"** ou um **artefato contendo DRE +
Balanço + Fluxo de Caixa**, a consulta deve seguir exatamente a hierarquia, ordem,
tipo de linha e fórmula definidas abaixo para cada uma das três estruturas, filtrando
pelo período (e revenda/empresa, quando aplicável) solicitado. O resultado deve ser
apresentado seguindo os **layouts de exemplo** incluídos ao final de cada seção.

Fonte dos dados: base única de lançamentos contábeis, com (entre outras) as colunas:
`CONTA`, `DESCRICAO_CONTA`, `NATUREZA` (C = crédito / D = débito), `VALOR`, `EMPRESA`,
`DRE` (classificação para a DRE) e `Balanço` (classificação para o Balanço). O Fluxo
de Caixa não tem coluna própria — é derivado combinando valores da DRE e variações de
saldo do Balanço (mais alguns casos que filtram diretamente por `NATUREZA`).

---

## REGRAS GERAIS DE AGREGAÇÃO (resumo comparativo)

| | DRE | Balanço | Fluxo de Caixa |
|---|---|---|---|
| **Natureza da conta** | Fluxo (movimento do período) | Estoque/Saldo (posição em um ponto no tempo) | Combinação de DRE (fluxo) + variações de saldo do Balanço |
| **Período somado** | Somente o período selecionado | Acumulado desde 01/2024 (período mais antigo do modelo) até o período selecionado | Depende da linha (ver regras específicas abaixo) |
| **Sinal do valor** | Mantido como vem na base (sem ABS); aplica-se um **multiplicador de direção** por linha (`+1`/`-1`) | Mantido como vem na base (sem ABS, sem multiplicador) | Depende do tipo de linha (DRE / VARIAÇÃO / NATUREZA) |

### Regra de sinal — DRE
- **Nunca aplicar ABS/módulo** no valor do lançamento.
- Cada linha de detalhe tem um multiplicador de direção definido pela estrutura
  (`+1` para receitas e itens que aumentam o resultado, `-1` para custos, despesas e
  deduções).
- Fórmula: `Contribuição = valor_original × multiplicador_da_linha`
- Motivo: um lançamento de estorno/cancelamento pode vir com o sinal já invertido na
  base (ex.: um custo lançado como negativo para anular parte de um custo anterior).
  Aplicar ABS destruiria essa informação; usando o valor original, o estorno se
  compensa corretamente dentro do grupo.

### Regra de sinal — Balanço
- **Soma direta, sem ABS e sem multiplicador.** O valor já vem com o sinal correto
  conforme a natureza da conta (inclusive contas redutoras como `(-) Depreciação
  Acumulada` e `(-) Amortização Acumulada` já vêm negativas na base).
- A única subtração da estrutura é a linha de **CHECK final**: `Ativo − (Passivo + PL)`.

### Regra de período — DRE (não cumulativo)
- Soma **apenas os lançamentos dentro do período selecionado** (ex.: só o mês
  filtrado). Não acumula meses/períodos anteriores.

### Regra de período — Balanço (cumulativo)
- Soma **todos os lançamentos desde o período mais antigo disponível no modelo
  semântico até o período selecionado**, inclusive.
- **Período mais antigo disponível: 01/2024.**
  Exemplo: se o filtro for 12/2024, soma tudo de 01/2024 até 12/2024.
- Nunca soma apenas o mês/período isolado — o saldo patrimonial é o resultado
  acumulado de todo o histórico até a data de referência.

### Regras gerais válidas para as três estruturas
- Linhas de **subtotal** (`=`) e **indicador (%)** nunca existem nas colunas `DRE`/
  `Balanço` da base — são sempre calculadas somando/dividindo os grupos de detalhe.
- Agregação por Revenda/Empresa é feita na consulta (filtro por `EMPRESA`); a
  hierarquia e ordem abaixo são as mesmas para todas as revendas.
- **Reservas de Capital** (Balanço/PL) atualmente não possui lançamento na base
  (saldo zero) — mantida na estrutura para o caso de vir a ter movimento futuramente.

## Legenda de tipos (todas as estruturas)

| Tipo      | Significado                                                       |
|-----------|--------------------------------------------------------------------|
| DETALHE   | Vem direto do valor da coluna `DRE` ou `Balanço` da base            |
| SUBTOTAL  | Calculado (soma de um subgrupo ou grupo)                            |
| INDICADOR | Calculado (percentual sobre outra linha)                            |
| DRE       | (Fluxo de Caixa) valor vem da DRE, período selecionado              |
| VARIAÇÃO  | (Fluxo de Caixa) vem da variação de saldo de uma conta do Balanço   |
| NATUREZA  | (Fluxo de Caixa) soma lançamentos filtrados por `NATUREZA` (C/D), só período selecionado |
| MANUAL    | Lançamento manual, fora da base (não calculado por fórmula)         |
| SALDO     | (Fluxo de Caixa) saldo de caixa inicial/final, recursivo entre períodos |

---
---

# 1. DRE — ESTRUTURA COMPLETA

## 1. RECEITA BRUTA DE VENDAS E SERVIÇOS

| # | Valor coluna DRE (base)     | Tipo     | Operação |
|---|------------------------------|----------|----------|
| 1 | Venda de Veículos Novos       | DETALHE  | +        |
| 2 | Venda de Veículos Usados      | DETALHE  | +        |
| 3 | Peças e Acessórios             | DETALHE  | +        |
| 4 | Serviços Oficina                | DETALHE  | +        |
| 5 | Comissões Diversas             | DETALHE  | +        |
| 6 | Comissão sobre Seguros          | DETALHE  | +        |
| 7 | Comissão sobre Consórcios       | DETALHE  | +        |
| 8 | Comissão sobre Intermediação    | DETALHE  | +        |
| 9 | (-) Devoluções                  | DETALHE  | -        |
| 10 | (-) Impostos sobre a Venda      | DETALHE  | -        |

Linhas 6–8 são receita **exclusiva** de empresas do tipo corretora (remuneradas
por comissão, sem venda de veículos/peças — ex.: CORRETORA). Ver a regra de
adaptação por ramo de atividade abaixo.

**= RECEITA LÍQUIDA** (SUBTOTAL) = soma das linhas 1 a 10 (respeitando a operação de cada uma)

## 2. CUSTOS DAS MERCADORIAS E SERVIÇOS

| # | Valor coluna DRE (base)         | Tipo     | Operação |
|---|-----------------------------------|----------|----------|
| 11 | Custo de Veículos Novos            | DETALHE  | -        |
| 12 | Custo de Veículos Usados           | DETALHE  | -        |
| 13 | Custo de Peças e Acessórios        | DETALHE  | -        |
| 14 | Custo de Serviços Oficina          | DETALHE  | -        |
| 15 | Custo de Serviço de Terceiros      | DETALHE  | -        |

**= LUCRO BRUTO** (SUBTOTAL) = RECEITA LÍQUIDA + soma das linhas 11 a 15
**% Margem Bruta** (INDICADOR) = LUCRO BRUTO / RECEITA LÍQUIDA

### Adaptação por ramo de atividade (grupos 1 e 2)

A estrutura acima é a da **concessionária**. Quando a DRE é filtrada por uma
empresa de outro ramo, as linhas que não existem naquele negócio **não são
exibidas** (em vez de saírem sempre `–`, o que poluiria o relatório). Isso é
só apresentação: **nenhum subtotal muda**, pois conta sem lançamento
contribuiria zero de qualquer forma. Na visão **consolidada** (sem filtro de
empresa) nada é omitido.

Regras vigentes (implementadas em `powerbi/dax_financeiro.py`):

| Empresa | Grupo 1 (Receita) | Grupo 2 (Custos) |
|---|---|---|
| Concessionárias (KOBE, RENAULT, ROYAL, OMODA, MEGA STORE, MIT, MULT BOATS) | Linhas 1–5, 9, 10. **Sem** as comissões 6–8 | Linhas 11–15, detalhadas |
| **CORRETORA** | Linhas 6–10. **Sem** venda de veículos/peças/oficina (1–5) | Linha única **"Custo de Mercado e Serviço"** (= soma do grupo), no lugar de 11–15 |
| Consolidado (todas) | Todas as 10 | Linhas 11–15, detalhadas |

## 3. DESPESAS OPERACIONAIS

| #  | Valor coluna DRE (base)                | Tipo     | Operação |
|----|-------------------------------------------|----------|----------|
| 16 | Folha de Pagamento                         | DETALHE  | -        |
| 17 | Despesas Comerciais                        | DETALHE  | -        |
| 18 | Despesas Gerais                            | DETALHE  | -        |
| 19 | Manutenção de Bens                         | DETALHE  | -        |
| 20 | Serviços Profissionais                     | DETALHE  | -        |
| 21 | Taxas e Impostos Diversos                  | DETALHE  | -        |
| 22 | Despesas de Funcionamento                  | DETALHE  | -        |
| 23 | Alugueis e Condomínios                     | DETALHE  | -        |
| 24 | Despesas Gerais e Rateio do Grupo          | DETALHE  | -        |
| 25 | Outras Despesas Operacionais               | DETALHE  | -        |
| 26 | Gastos Diversos com Funcionários           | DETALHE  | -        |

(Este grupo não gera subtotal próprio **na fórmula** — entra direto no cálculo do
EBITDA, junto com o grupo 4. **Porém, no layout visual**, o cabeçalho do bloco
"3. DESPESAS OPERACIONAIS" exibe a soma das linhas 16 a 26 como um **subtotal de
exibição** (não é uma linha de detalhe nem é usada como input em nenhuma outra
fórmula — serve só de referência visual no cabeçalho do bloco, como no relatório de
referência do usuário).

## 4. OUTRAS RECEITAS/DESPESAS

| #  | Valor coluna DRE (base)         | Tipo     | Operação |
|----|-----------------------------------|----------|----------|
| 27 | (+) Receitas Diversas              | DETALHE  | +        |
| 28 | (+) Receitas Não Operacionais      | DETALHE  | +        |
| 29 | (-) Despesas Não Dedutíveis        | DETALHE  | -        |
| 30 | (-) Despesas Não Operacionais      | DETALHE  | -        |

**= EBITDA** (SUBTOTAL) = LUCRO BRUTO + soma do grupo 3 (linhas 16 a 26) + soma do grupo 4 (linhas 27 a 30)
**% EBITDA/RL** (INDICADOR) = EBITDA / RECEITA LÍQUIDA

## 5. DEPRECIAÇÃO E AMORTIZAÇÃO

| #  | Valor coluna DRE (base)              | Tipo     | Operação |
|----|------------------------------------------|----------|----------|
| 31 | Depreciação e Amortização de Ativos       | DETALHE  | -        |

**= EBIT (Resultado Operacional)** (SUBTOTAL) = EBITDA + linha 31

## 6. RESULTADO FINANCEIRO

| #  | Valor coluna DRE (base)         | Tipo     | Operação |
|----|-----------------------------------|----------|----------|
| 32 | (+) Receitas Financeiras           | DETALHE  | +        |
| 33 | (-) Despesas Financeiras           | DETALHE  | -        |

**= LAIR (Resultado antes do IR)** (SUBTOTAL) = EBIT + linhas 32 e 33

## 7. IMPOSTOS SOBRE O LUCRO

| #  | Valor coluna DRE (base) | Tipo     | Operação |
|----|-----------------------------|----------|----------|
| 34 | (-) IR e CSLL                 | DETALHE  | -        |

**= LUCRO LÍQUIDO DO EXERCÍCIO** (SUBTOTAL) = LAIR + linha 34
**% Margem Líquida** (INDICADOR) = LUCRO LÍQUIDO DO EXERCÍCIO / RECEITA LÍQUIDA

## Resumo dos indicadores calculados — DRE

| Indicador          | Fórmula                                      |
|--------------------|-----------------------------------------------|
| RECEITA LÍQUIDA    | Grupo 1                                        |
| LUCRO BRUTO        | RECEITA LÍQUIDA + Grupo 2                      |
| % Margem Bruta     | LUCRO BRUTO / RECEITA LÍQUIDA                  |
| EBITDA             | LUCRO BRUTO + Grupo 3 + Grupo 4                |
| % EBITDA/RL        | EBITDA / RECEITA LÍQUIDA                       |
| EBIT               | EBITDA + Grupo 5                               |
| LAIR               | EBIT + Grupo 6                                 |
| LUCRO LÍQUIDO      | LAIR + Grupo 7                                 |
| % Margem Líquida   | LUCRO LÍQUIDO / RECEITA LÍQUIDA                |

## Layout de exemplo — DRE

*(valores fictícios, apenas para ilustrar o formato final do artefato — organizado em
blocos numerados com cabeçalho, igual ao relatório de referência)*

**1. RECEITA BRUTA DE VENDAS E SERVIÇOS**
| Linha                          | Valor (R$)     |
|-----------------------------------|---------------:|
| Venda de Veículos Novos            | 5.000.000      |
| Venda de Veículos Usados           | 2.000.000      |
| Peças e Acessórios                  | 800.000        |
| Serviços Oficina                     | 400.000        |
| Comissões Diversas                  | 100.000        |
| Comissão sobre Seguros              | –              |
| Comissão sobre Consórcios           | –              |
| Comissão sobre Intermediação        | –              |
| (-) Devoluções                       | (50.000)       |
| (-) Impostos sobre a Venda           | (600.000)      |
| **= RECEITA LÍQUIDA**               | **7.650.000**  |

**2. CUSTOS DAS MERCADORIAS E SERVIÇOS**
| Linha                          | Valor (R$)     |
|-----------------------------------|---------------:|
| Custo de Veículos Novos            | (4.200.000)    |
| Custo de Veículos Usados           | (1.700.000)    |
| Custo de Peças e Acessórios        | (500.000)      |
| Custo de Serviços Oficina          | (150.000)      |
| Custo de Serviço de Terceiros      | (80.000)       |
| **= LUCRO BRUTO**                  | **1.020.000**  |
| % Margem Bruta                      | 13,3%          |

**3. DESPESAS OPERACIONAIS** *(cabeçalho exibe: (675.000) — subtotal de exibição das linhas abaixo)*
| Linha                          | Valor (R$)     |
|-----------------------------------|---------------:|
| Folha de Pagamento                 | (300.000)      |
| Despesas Comerciais                | (80.000)       |
| Despesas Gerais                    | (60.000)       |
| Manutenção de Bens                 | (20.000)       |
| Serviços Profissionais             | (30.000)       |
| Taxas e Impostos Diversos          | (25.000)       |
| Despesas de Funcionamento          | (40.000)       |
| Alugueis e Condomínios             | (35.000)       |
| Despesas Gerais e Rateio do Grupo  | (50.000)       |
| Outras Despesas Operacionais       | (20.000)       |
| Gastos Diversos com Funcionários   | (15.000)       |

**4. OUTRAS RECEITAS/DESPESAS**
| Linha                          | Valor (R$)     |
|-----------------------------------|---------------:|
| (+) Receitas Diversas               | 40.000         |
| (+) Receitas Não Operacionais       | 10.000         |
| (-) Despesas Não Dedutíveis         | (8.000)        |
| (-) Despesas Não Operacionais       | (12.000)       |
| **= EBITDA**                        | **375.000**    |
| % EBITDA/RL                          | 4,9%           |

**5. DEPRECIAÇÃO E AMORTIZAÇÃO**
| Linha                                | Valor (R$)     |
|------------------------------------------|---------------:|
| Depreciação e Amortização de Ativos        | (60.000)       |
| **= EBIT (Resultado Operacional)**         | **315.000**    |

**6. RESULTADO FINANCEIRO**
| Linha                          | Valor (R$)     |
|-----------------------------------|---------------:|
| (+) Receitas Financeiras            | 15.000         |
| (-) Despesas Financeiras            | (45.000)       |
| **= LAIR (Resultado antes do IR)**  | **285.000**    |

**7. IMPOSTOS SOBRE O LUCRO**
| Linha                                | Valor (R$)     |
|------------------------------------------|---------------:|
| (-) IR e CSLL                              | (70.000)       |
| **= LUCRO LÍQUIDO DO EXERCÍCIO**           | **215.000**    |
| % Margem Líquida                            | 2,8%           |

---
---

# 2. BALANÇO PATRIMONIAL — ESTRUTURA COMPLETA

## ATIVO

### ATIVO CIRCULANTE

**DISPONIBILIDADES** (SUBTOTAL)
| # | Valor coluna Balanço (base) | Tipo    |
|---|-------------------------------|---------|
| 1 | Caixa e Bancos                 | DETALHE |
| 2 | Aplicações Financeiras         | DETALHE |

**VALORES A RECEBER** (SUBTOTAL)
| # | Valor coluna Balanço (base)     | Tipo    |
|---|------------------------------------|---------|
| 3 | Contas a Receber                    | DETALHE |
| 4 | Cartões de Crédito a Receber        | DETALHE |
| 5 | Financiamentos a Receber            | DETALHE |
| 6 | Adiantamentos a Fornecedores        | DETALHE |
| 7 | Outros Adiantamentos                | DETALHE |
| 8 | Outros Créditos a Receber           | DETALHE |
| 9 | Impostos a Recuperar                | DETALHE |

**ESTOQUES** (SUBTOTAL)
| #  | Valor coluna Balanço (base)  | Tipo    |
|----|---------------------------------|---------|
| 10 | Estoque de Veículos Novos        | DETALHE |
| 11 | Estoque de Veículos Usados       | DETALHE |
| 12 | Estoque de Peças                 | DETALHE |

**= TOTAL ATIVO CIRCULANTE** (SUBTOTAL) = DISPONIBILIDADES + VALORES A RECEBER + ESTOQUES

### ATIVO NÃO CIRCULANTE

**REALIZÁVEL A LONGO PRAZO** (SUBTOTAL)
| #  | Valor coluna Balanço (base)                 | Tipo    |
|----|-------------------------------------------------|---------|
| 13 | Investimentos a Longo Prazo - FVN                | DETALHE |

**INVESTIMENTOS** (SUBTOTAL)
| #  | Valor coluna Balanço (base)   | Tipo    |
|----|-----------------------------------|---------|
| 14 | Investimentos a Longo Prazo        | DETALHE |
| 15 | Investimentos Permanentes          | DETALHE |

**IMOBILIZADO DE USO** (SUBTOTAL)
| #  | Valor coluna Balanço (base)          | Tipo    |
|----|------------------------------------------|---------|
| 16 | Terrenos                                  | DETALHE |
| 17 | Edifícios                                 | DETALHE |
| 18 | Instalações                               | DETALHE |
| 19 | Veículos                                  | DETALHE |
| 20 | Máquinas e Equipamentos                   | DETALHE |
| 21 | Computadores e Periféricos                | DETALHE |
| 22 | Móveis e Utensílios                       | DETALHE |
| 23 | Construções em Andamento                  | DETALHE |
| 24 | Benfeitorias em Bens de Terceiros         | DETALHE |
| 25 | Consórcios                                | DETALHE |
| 26 | Aeronaves                                 | DETALHE |
| 27 | (-) Depreciação Acumulada                 | DETALHE |

**INTANGÍVEL** (SUBTOTAL)
| #  | Valor coluna Balanço (base)     | Tipo    |
|----|-------------------------------------|---------|
| 28 | Direitos de Concessão                | DETALHE |
| 29 | (-) Amortização Acumulada            | DETALHE |

**= TOTAL ATIVO NÃO CIRCULANTE** (SUBTOTAL) = REALIZÁVEL A LP + INVESTIMENTOS + IMOBILIZADO DE USO + INTANGÍVEL

**= TOTAL DO ATIVO** (SUBTOTAL) = TOTAL ATIVO CIRCULANTE + TOTAL ATIVO NÃO CIRCULANTE

## PASSIVO E PATRIMÔNIO LÍQUIDO

### PASSIVO CIRCULANTE

**FORNECEDORES** (SUBTOTAL)
| #  | Valor coluna Balanço (base)      | Tipo    |
|----|---------------------------------------|---------|
| 30 | Floor Plan Veículos Novos               | DETALHE |
| 31 | Floor Plan Veículos Usados              | DETALHE |
| 32 | Floor Plan Peças e Acessórios           | DETALHE |
| 33 | Fornecedores Diversos                   | DETALHE |

**EMPRÉSTIMOS E FINANCIAMENTOS** (SUBTOTAL)
| #  | Valor coluna Balanço (base)  | Tipo    |
|----|----------------------------------|---------|
| 34 | Empréstimos Bancários             | DETALHE |
| 35 | Empréstimos de Terceiros          | DETALHE |
| 36 | Conta Garantida                   | DETALHE |
| 37 | Financiamentos                    | DETALHE |
| 38 | Notas Comerciais                  | DETALHE |

**OUTRAS OBRIGAÇÕES** (SUBTOTAL)
| #  | Valor coluna Balanço (base)         | Tipo    |
|----|------------------------------------------|---------|
| 39 | Obrigações Sociais e Trabalhistas         | DETALHE |
| 40 | Obrigações Tributárias e Diversas         | DETALHE |
| 41 | Adiantamento de Clientes                  | DETALHE |
| 42 | Provisões                                 | DETALHE |
| 43 | Outras Contas a Pagar                     | DETALHE |
| 44 | Lucros a Pagar                            | DETALHE |

**= TOTAL PASSIVO CIRCULANTE** (SUBTOTAL) = FORNECEDORES + EMPRÉSTIMOS E FINANCIAMENTOS + OUTRAS OBRIGAÇÕES

### PASSIVO NÃO CIRCULANTE

| #  | Valor coluna Balanço (base)          | Tipo    |
|----|-------------------------------------------|---------|
| 45 | Empréstimos e Financiamentos LP            | DETALHE |
| 46 | Outros Credores                            | DETALHE |
| 47 | Parcelamentos LP                           | DETALHE |
| 48 | Adiantamento Futura Integralização         | DETALHE |

**= TOTAL PASSIVO NÃO CIRCULANTE** (SUBTOTAL) = soma das linhas 45 a 48

### PATRIMÔNIO LÍQUIDO

| #  | Valor coluna Balanço (base)       | Tipo    |
|----|----------------------------------------|---------|
| 49 | Capital Social Integralizado             | DETALHE |
| 50 | Reservas de Capital *(sem lançamento na base atualmente)* | DETALHE |
| 51 | Reservas de Lucros                       | DETALHE |
| 52 | Reservas de Incentivos Fiscais           | DETALHE |
| 53 | Prejuízos Acumulados                     | DETALHE |
| 54 | Ajustes de Exercícios Anteriores         | DETALHE |

**= TOTAL PATRIMÔNIO LÍQUIDO** (SUBTOTAL) = soma das linhas 49 a 54

**= TOTAL PASSIVO + PL** (SUBTOTAL) = TOTAL PASSIVO CIRCULANTE + TOTAL PASSIVO NÃO CIRCULANTE + TOTAL PATRIMÔNIO LÍQUIDO

## CHECK — Balanço

**CHECK: Ativo − (Passivo + PL)** = TOTAL DO ATIVO − TOTAL PASSIVO + PL

(Resultado esperado: **zero**. Diferente de zero indica lançamento sem classificação
correta na coluna `Balanço` ou item fora da estrutura.)

## Resumo dos totais calculados — Balanço

| Total                          | Fórmula                                                      |
|---------------------------------|----------------------------------------------------------------|
| TOTAL ATIVO CIRCULANTE          | DISPONIBILIDADES + VALORES A RECEBER + ESTOQUES                |
| TOTAL ATIVO NÃO CIRCULANTE      | REALIZÁVEL A LP + INVESTIMENTOS + IMOBILIZADO DE USO + INTANGÍVEL |
| TOTAL DO ATIVO                  | TOTAL ATIVO CIRCULANTE + TOTAL ATIVO NÃO CIRCULANTE             |
| TOTAL PASSIVO CIRCULANTE        | FORNECEDORES + EMPRÉSTIMOS E FINANCIAMENTOS + OUTRAS OBRIGAÇÕES |
| TOTAL PASSIVO NÃO CIRCULANTE    | soma dos itens do grupo                                         |
| TOTAL PATRIMÔNIO LÍQUIDO        | soma dos itens do grupo                                         |
| TOTAL PASSIVO + PL              | TOTAL PASSIVO CIRC. + TOTAL PASSIVO NÃO CIRC. + TOTAL PL        |
| CHECK                           | TOTAL DO ATIVO − TOTAL PASSIVO + PL                             |

## Layout de exemplo — Balanço

*(valores fictícios, consistentes com o exemplo da DRE e do Fluxo de Caixa — organizado
em blocos por seção, igual ao padrão visual da DRE)*

**ATIVO CIRCULANTE**
| Linha                             | Valor (R$)     |
|---------------------------------------|---------------:|
| Caixa e Bancos                          | 300.000        |
| Aplicações Financeiras                  | 50.000         |
| **DISPONIBILIDADES**                    | **350.000**    |
| Contas a Receber                        | 1.200.000      |
| Cartões de Crédito a Receber            | 80.000         |
| Financiamentos a Receber                | 20.000         |
| Adiantamentos a Fornecedores            | 150.000        |
| Outros Adiantamentos                    | 40.000         |
| Outros Créditos a Receber               | 60.000         |
| Impostos a Recuperar                    | 90.000         |
| **VALORES A RECEBER**                   | **1.640.000**  |
| Estoque de Veículos Novos               | 3.000.000      |
| Estoque de Veículos Usados              | 1.500.000      |
| Estoque de Peças                        | 400.000        |
| **ESTOQUES**                            | **4.900.000**  |
| **= TOTAL ATIVO CIRCULANTE**            | **6.890.000**  |

**ATIVO NÃO CIRCULANTE**
| Linha                             | Valor (R$)     |
|---------------------------------------|---------------:|
| Investimentos a Longo Prazo - FVN       | -              |
| **REALIZÁVEL A LONGO PRAZO**            | **-**          |
| Investimentos a Longo Prazo             | 50.000         |
| Investimentos Permanentes               | 20.000         |
| **INVESTIMENTOS**                       | **70.000**     |
| Terrenos                                | 500.000        |
| Edifícios                               | 800.000        |
| Instalações                             | 100.000        |
| Veículos                                | 60.000         |
| Máquinas e Equipamentos                 | 40.000         |
| Computadores e Periféricos              | 30.000         |
| Móveis e Utensílios                     | 20.000         |
| Benfeitorias em Bens de Terceiros       | 10.000         |
| (-) Depreciação Acumulada               | (150.000)      |
| **IMOBILIZADO DE USO**                  | **1.410.000**  |
| Direitos de Concessão                   | 30.000         |
| (-) Amortização Acumulada               | (10.000)       |
| **INTANGÍVEL**                          | **20.000**     |
| **= TOTAL ATIVO NÃO CIRCULANTE**        | **1.500.000**  |

**= TOTAL DO ATIVO** = **8.390.000**

**PASSIVO CIRCULANTE**
| Linha                             | Valor (R$)     |
|---------------------------------------|---------------:|
| Floor Plan Veículos Novos               | 2.000.000      |
| Floor Plan Veículos Usados              | 800.000        |
| Floor Plan Peças e Acessórios           | 100.000        |
| Fornecedores Diversos                   | 500.000        |
| **FORNECEDORES**                        | **3.400.000**  |
| Empréstimos Bancários                   | 400.000        |
| Conta Garantida                         | 300.000        |
| Financiamentos                          | 100.000        |
| Notas Comerciais                        | 200.000        |
| **EMPRÉSTIMOS E FINANCIAMENTOS**        | **1.000.000**  |
| Obrigações Sociais e Trabalhistas       | 80.000         |
| Obrigações Tributárias e Diversas       | 60.000         |
| Adiantamento de Clientes                | 150.000        |
| Provisões                               | 40.000         |
| Outras Contas a Pagar                   | 30.000         |
| Lucros a Pagar                          | 20.000         |
| **OUTRAS OBRIGAÇÕES**                   | **380.000**    |
| **= TOTAL PASSIVO CIRCULANTE**          | **4.780.000**  |

**PASSIVO NÃO CIRCULANTE**
| Linha                             | Valor (R$)     |
|---------------------------------------|---------------:|
| Empréstimos e Financiamentos LP         | 500.000        |
| Parcelamentos LP                        | 50.000         |
| **= TOTAL PASSIVO NÃO CIRCULANTE**      | **550.000**    |

**PATRIMÔNIO LÍQUIDO**
| Linha                             | Valor (R$)     |
|---------------------------------------|---------------:|
| Capital Social Integralizado            | 3.000.000      |
| Reservas de Lucros                      | 100.000        |
| Reservas de Incentivos Fiscais          | 10.000         |
| Prejuízos Acumulados                    | (50.000)       |
| **= TOTAL PATRIMÔNIO LÍQUIDO**          | **3.060.000**  |

**= TOTAL PASSIVO + PL** = **8.390.000**
**CHECK: Ativo − (Passivo + PL)** = **0**

---
---

# 3. FLUXO DE CAIXA (MÉTODO INDIRETO) — ESTRUTURA COMPLETA

O Fluxo de Caixa **não tem uma coluna própria na base de lançamentos** — é montado
combinando:
- valores da **DRE** (resultado do período), e
- **variações de saldo** de contas do **Balanço** (saldo do período atual vs. saldo
  do período anterior), e
- em alguns casos específicos, uma soma de lançamentos filtrados pela coluna
  `NATUREZA` (C/D), apenas do período selecionado.

## Regras específicas do Fluxo de Caixa

- **Origem DRE**: valores que vêm da DRE usam a regra de período da DRE — somente o
  período selecionado (não cumulativo).
- **Origem Balanço (variação)**: os valores de "Variação em X" comparam o **saldo do
  Balanço no período selecionado contra o saldo do mês imediatamente anterior** (não
  contra o saldo de 01/2024). Cada saldo (atual e anterior) é calculado pela regra
  cumulativa do Balanço (do início 01/2024 até a respectiva data).
- **Fórmula de variação por natureza da conta**:
  - **Contas de Ativo** (ex.: Contas a Receber, Estoque): `Variação = (Saldo Atual − Saldo Anterior) × -1`
    → um aumento do saldo do ativo consome caixa, por isso o resultado fica negativo.
  - **Contas de Passivo** (ex.: Fornecedores, Obrigações): `Variação = Saldo Atual − Saldo Anterior`
    → um aumento do saldo do passivo gera caixa, por isso o resultado fica positivo.
- **Exceção — linhas do tipo NATUREZA** (Venda de Ativos Imobilizados, Adições ao
  Ativo Imobilizado, Dividendos Distribuídos): somam os **lançamentos brutos** da
  base filtrados por `NATUREZA = C` ou `NATUREZA = D`, **apenas do período
  selecionado** — mesmo sendo contas do Balanço, **não usam a regra cumulativa** nem
  a lógica de "variação de saldo" nessas linhas específicas.
- As linhas de **subtotal** (`=`) nunca existem em nenhuma base — são sempre
  calculadas somando os itens de detalhe do grupo.
- **PROIBIDO ajuste de conciliação / tampão.** A `VARIAÇÃO LÍQUIDA DE CAIXA` é a
  soma honesta das três seções (operacional + investimento + financiamento) e o
  `= Saldo de Caixa Final` = `Saldo Inicial + Variação Líquida`. O CHECK compara
  esse saldo final com a variação real de caixa do Balanço (`DISPONIBILIDADES`)
  e é uma verificação de verdade — **jamais forçado a zero, nunca com linha de
  ajuste**. Se sobrar resíduo, ele fica à mostra para investigação, não é
  escondido nem compensado.

## I. ATIVIDADES OPERACIONAIS

| # | Linha do Fluxo de Caixa                    | Tipo    | Fonte / Fórmula                                                                 |
|---|-----------------------------------------------|---------|------------------------------------------------------------------------------------|
| 1 | Lucro Líquido do Exercício                     | DRE     | = LUCRO LÍQUIDO DO EXERCÍCIO (subtotal da DRE, período selecionado)                |
| 2 | Depreciação e Amortização de Ativos            | DRE/NATUREZA | = Σ dos lançamentos da linha "Depreciação e Amortização de Ativos" (coluna DRE) **apenas com `NATUREZA = D`**, período selecionado, somado de volta (despesa não-caixa). Considera só a despesa lançada (débito), ignorando estornos a crédito. |
| 3 | Ajustes de Exercícios Anteriores               | VARIAÇÃO| = variação do saldo da conta "Ajustes de Exercícios Anteriores" (Patrimônio Líquido no Balanço) |
| 4 | Outros Ajustes                                 | MANUAL  | Lançamento manual — **ignorar por enquanto** (sem fórmula)                          |

**VALORES A RECEBER** (SUBTOTAL — soma das variações de Ativo abaixo)
| #  | Linha do Fluxo de Caixa                              | Tipo     | Conta correspondente no Balanço          |
|----|-----------------------------------------------------------|----------|--------------------------------------------|
| 5  | (+/-) Variação em Contas a Receber                          | VARIAÇÃO | Contas a Receber                           |
| 6  | (+/-) Variação em Cartões de Crédito a Receber              | VARIAÇÃO | Cartões de Crédito a Receber                |
| 7  | (+/-) Variação em Financiamentos a Receber                  | VARIAÇÃO | Financiamentos a Receber                    |
| 8  | (+/-) Variação em Adiantamentos a Fornecedores              | VARIAÇÃO | Adiantamentos a Fornecedores                |
| 9  | (+/-) Variação em Outros Adiantamentos                      | VARIAÇÃO | Outros Adiantamentos                        |
| 10 | (+/-) Variação em Outros Créditos a Receber                 | VARIAÇÃO | Outros Créditos a Receber                   |
| 11 | (+/-) Variação em Impostos a Recuperar                      | VARIAÇÃO | Impostos a Recuperar                        |

**ESTOQUE** (SUBTOTAL — soma das variações de Ativo abaixo)
| #  | Linha do Fluxo de Caixa                          | Tipo     | Conta correspondente no Balanço |
|----|---------------------------------------------------------|----------|------------------------------------|
| 12 | (+/-) Variação em Estoque de Veículos Novos               | VARIAÇÃO | Estoque de Veículos Novos          |
| 13 | (+/-) Variação em Estoque de Veículos Usados              | VARIAÇÃO | Estoque de Veículos Usados         |
| 14 | (+/-) Variação em Estoque de Peças                        | VARIAÇÃO | Estoque de Peças                   |

**VALORES A PAGAR** (SUBTOTAL — soma das variações de Passivo abaixo)
| #  | Linha do Fluxo de Caixa                              | Tipo     | Conta correspondente no Balanço              |
|----|-----------------------------------------------------------|----------|--------------------------------------------------|
| 15 | (+/-) Variação em Fornecedores Diversos                     | VARIAÇÃO | Fornecedores Diversos (Passivo Circulante)        |
| 16 | (+/-) Variação em Obrigações Sociais e Trabalhistas         | VARIAÇÃO | Obrigações Sociais e Trabalhistas (Passivo Circ.)|
| 17 | (+/-) Variação em Obrigações Tributárias e Diversas         | VARIAÇÃO | Obrigações Tributárias e Diversas (Passivo Circ.)|
| 18 | (+/-) Variação em Adiantamento de Clientes                  | VARIAÇÃO | Adiantamento de Clientes (Passivo Circulante)     |
| 19 | (+/-) Variação em Provisões                                 | VARIAÇÃO | Provisões (Passivo Circulante)                    |
| 20 | (+/-) Variação em Outras Contas a Pagar                     | VARIAÇÃO | Outras Contas a Pagar (Passivo Circulante)        |
| 21 | (+/-) Variação em Lucros a Pagar                            | VARIAÇÃO | Lucros a Pagar (Passivo Circulante)               |
| 22 | (+/-) Variação em Outros Credores                           | VARIAÇÃO | Outros Credores (Passivo Não Circulante)          |
| 23 | (+/-) Variação em Parcelamentos LP                          | VARIAÇÃO | Parcelamentos LP (Passivo Não Circulante)         |

**= CAIXA GERADO NAS ATIVIDADES OPERACIONAIS** (SUBTOTAL) =
linhas 1 + 2 + 3 + 4 + VALORES A RECEBER + ESTOQUE + VALORES A PAGAR

## II. ATIVIDADES DE INVESTIMENTO

| # | Linha do Fluxo de Caixa            | Tipo     | Fonte / Fórmula |
|---|----------------------------------------|----------|----------------------|
| 24 | (+/-) Investimentos a Longo Prazo       | VARIAÇÃO | Variação combinada (saldo atual − saldo anterior) das contas: `Investimentos a Longo Prazo - FVN` + `Investimentos a Longo Prazo` + `Investimentos Permanentes` |
| 25 | (+) Venda de Ativos Imobilizados        | NATUREZA | Σ(lançamentos de `Terrenos`, `Edifícios`, `Instalações`, `Veículos`, `Máquinas e Equipamentos`, `Computadores e Periféricos`, `Móveis e Utensílios`, `Construções em Andamento`, `Benfeitorias em Bens de Terceiros`, `Consórcios`, `Aeronaves`, `Direitos de Concessão` — apenas lançamentos com `NATUREZA = C`, só período selecionado) **menos** Σ(lançamentos de `(-) Depreciação Acumulada` e `(-) Amortização Acumulada` com `NATUREZA = D`, só período selecionado) |
| 26 | (−) Adições ao Ativo Imobilizado        | NATUREZA | Σ(lançamentos das mesmas contas de imobilizado/intangível da linha 25 — incluindo `Direitos de Concessão` —, apenas `NATUREZA = D`, só período selecionado) |

**= CAIXA NAS ATIVIDADES DE INVESTIMENTO** (SUBTOTAL) = linhas 24 + 25 + 26

## III. ATIVIDADES DE FINANCIAMENTO

> As 7 linhas abaixo estão todas no mesmo nível hierárquico (não há subgrupo/subtotal
> intermediário) — a soma vai direto para o total da seção.

| # | Linha do Fluxo de Caixa                              | Tipo     | Fonte / Fórmula |
|---|----------------------------------------------------------|----------|----------------------|
| 27 | (+/-) Empréstimos e Financiamentos                          | VARIAÇÃO | Variação combinada (saldo atual − saldo anterior) das contas: `Empréstimos Bancários` + `Empréstimos de Terceiros` + `Conta Garantida` + `Financiamentos` + `Notas Comerciais` + `Empréstimos e Financiamentos LP` |
| 28 | (+/-) Variação em Floor Plan de Veículos Novos              | VARIAÇÃO | `Floor Plan Veículos Novos` (Passivo) |
| 29 | (+/-) Variação em Floor Plan de Veículos Usados             | VARIAÇÃO | `Floor Plan Veículos Usados` (Passivo) |
| 30 | (+/-) Variação em Floor Plan de Peças                       | VARIAÇÃO | `Floor Plan Peças e Acessórios` (Passivo) |
| 31 | (+/-) Variação de Capital                                   | VARIAÇÃO | Variação combinada de `Capital Social Integralizado` + `Reservas de Capital` |
| 32 | (+/-) Adiantamentos para Futuro Aumento de Capital          | VARIAÇÃO | `Adiantamento Futura Integralização` (Passivo Não Circulante) |
| 33 | (+/-) Dividendos Distribuídos no exercício                  | NATUREZA | Σ(lançamentos de `Lucros a Pagar`, apenas `NATUREZA = C`, só período selecionado) |

**= CAIXA NAS ATIVIDADES DE FINANCIAMENTO** (SUBTOTAL) = soma das linhas 27 a 33

## VARIAÇÃO LÍQUIDA DE CAIXA DO PERÍODO

**VARIAÇÃO LÍQUIDA DE CAIXA DO PERÍODO** (SUBTOTAL) =
CAIXA GERADO NAS ATIVIDADES OPERACIONAIS + CAIXA NAS ATIVIDADES DE INVESTIMENTO + CAIXA NAS ATIVIDADES DE FINANCIAMENTO

## Saldo de Caixa

| # | Linha do Fluxo de Caixa            | Tipo     | Fonte / Fórmula |
|---|----------------------------------------|----------|----------------------|
| 34 | (+) Saldo de Caixa Inicial do Período   | SALDO    | = Saldo de Caixa Final do período **anterior** (recursivo). **Exceção 01/2024**: como este é o primeiro período do modelo, o saldo inicial é **zero** — o saldo final de 12/2023 já está embutido no saldo/lançamentos de 01/2024 (saldo de abertura somado junto aos valores do próprio mês). |
| 35 | (=) Saldo de Caixa Final do Período     | SALDO    | = Saldo de Caixa Inicial do Período (linha 34) + Variação Líquida de Caixa do Período |

### CHECK do Fluxo de Caixa
O **Saldo de Caixa Final do Período** (linha 35) deve bater com o subtotal
`DISPONIBILIDADES` (Caixa e Bancos + Aplicações Financeiras) do Balanço no período
selecionado. **Tolerância de até R$ 5,00** de diferença é aceitável (arredondamentos).

## Contas do Balanço mapeadas no Fluxo de Caixa (referência)

| Conta do Balanço | Seção do Fluxo de Caixa |
|---|---|
| Contas a Receber, Cartões de Crédito a Receber, Financiamentos a Receber, Adiantamentos a Fornecedores, Outros Adiantamentos, Outros Créditos a Receber, Impostos a Recuperar | I — Valores a Receber |
| Estoque de Veículos Novos, Estoque de Veículos Usados, Estoque de Peças | I — Estoque |
| Fornecedores Diversos, Obrigações Sociais e Trabalhistas, Obrigações Tributárias e Diversas, Adiantamento de Clientes, Provisões, Outras Contas a Pagar, Outros Credores, Parcelamentos LP | I — Valores a Pagar |
| Lucros a Pagar | I — Valores a Pagar (variação completa) **e** III — Dividendos Distribuídos (somente NATUREZA=C, período) |
| Ajustes de Exercícios Anteriores | I — linha própria |
| Investimentos a Longo Prazo - FVN, Investimentos a Longo Prazo, Investimentos Permanentes | II — Investimentos a Longo Prazo |
| Terrenos, Edifícios, Instalações, Veículos, Máquinas e Equipamentos, Computadores e Periféricos, Móveis e Utensílios, Construções em Andamento, Benfeitorias em Bens de Terceiros, Consórcios, Aeronaves, Direitos de Concessão | II — Venda de Ativos Imobilizados (NATUREZA=C) e Adições ao Ativo Imobilizado (NATUREZA=D) |
| (-) Depreciação Acumulada, (-) Amortização Acumulada | II — usadas só para reduzir a Venda de Ativos Imobilizados (NATUREZA=D) |
| Floor Plan Veículos Novos, Floor Plan Veículos Usados, Floor Plan Peças e Acessórios | III |
| Empréstimos Bancários, Empréstimos de Terceiros, Conta Garantida, Financiamentos, Notas Comerciais, Empréstimos e Financiamentos LP | III — Empréstimos e Financiamentos |
| Capital Social Integralizado, Reservas de Capital | III — Variação de Capital |
| Adiantamento Futura Integralização | III |
| Caixa e Bancos, Aplicações Financeiras | Saldo de Caixa (CHECK final) |

### Contas do Balanço que NÃO entram no Fluxo de Caixa (intencional)

- **Reservas de Lucros**, **Reservas de Incentivos Fiscais**, **Prejuízos Acumulados**
  (Patrimônio Líquido) — são apenas realocações contábeis do resultado dentro do PL
  (destinação do lucro do exercício), não representam entrada/saída de caixa.

## Layout de exemplo — Fluxo de Caixa

*(valores fictícios, consistentes com os exemplos da DRE e do Balanço acima — o
Saldo de Caixa Final bate com a linha DISPONIBILIDADES do Balanço de exemplo —
organizado em blocos por seção, igual ao padrão visual da DRE e do Balanço)*

**I. ATIVIDADES OPERACIONAIS**
| Linha                                            | Valor (R$)     |
|------------------------------------------------------|---------------:|
| Lucro Líquido do Exercício                            | 215.000        |
| Depreciação e Amortização de Ativos                   | 60.000         |
| Ajustes de Exercícios Anteriores                      | -              |
| Outros Ajustes                                        | -              |
| (+/-) Variação em Contas a Receber                    | (80.000)       |
| (+/-) Variação em Cartões de Crédito a Receber        | (5.000)        |
| (+/-) Variação em Financiamentos a Receber            | (2.000)        |
| (+/-) Variação em Adiantamentos a Fornecedores        | (10.000)       |
| (+/-) Variação em Outros Adiantamentos                | 3.000          |
| (+/-) Variação em Outros Créditos a Receber           | (4.000)        |
| (+/-) Variação em Impostos a Recuperar                | (6.000)        |
| **VALORES A RECEBER**                                 | **(104.000)**  |
| (+/-) Variação em Estoque de Veículos Novos           | (200.000)      |
| (+/-) Variação em Estoque de Veículos Usados          | 50.000         |
| (+/-) Variação em Estoque de Peças                    | (10.000)       |
| **ESTOQUE**                                           | **(160.000)**  |
| (+/-) Variação em Fornecedores Diversos               | 30.000         |
| (+/-) Variação em Obrigações Sociais e Trabalhistas   | 5.000          |
| (+/-) Variação em Obrigações Tributárias e Diversas   | (3.000)        |
| (+/-) Variação em Adiantamento de Clientes            | 20.000         |
| (+/-) Variação em Provisões                           | 4.000          |
| (+/-) Variação em Outras Contas a Pagar               | 2.000          |
| (+/-) Variação em Lucros a Pagar                      | (1.000)        |
| (+/-) Variação em Outros Credores                     | -              |
| (+/-) Variação em Parcelamentos LP                    | 5.000          |
| **VALORES A PAGAR**                                   | **62.000**     |
| **= CAIXA GERADO NAS ATIVIDADES OPERACIONAIS**        | **73.000**     |

**II. ATIVIDADES DE INVESTIMENTO**
| Linha                                            | Valor (R$)     |
|------------------------------------------------------|---------------:|
| (+/-) Investimentos a Longo Prazo                     | (10.000)       |
| (+) Venda de Ativos Imobilizados                      | 15.000         |
| (−) Adições ao Ativo Imobilizado                      | (120.000)      |
| **= CAIXA NAS ATIVIDADES DE INVESTIMENTO**            | **(115.000)**  |

**III. ATIVIDADES DE FINANCIAMENTO**
| Linha                                            | Valor (R$)     |
|------------------------------------------------------|---------------:|
| (+/-) Empréstimos e Financiamentos                    | 80.000         |
| (+/-) Variação em Floor Plan de Veículos Novos        | 150.000        |
| (+/-) Variação em Floor Plan de Veículos Usados       | (30.000)       |
| (+/-) Variação em Floor Plan de Peças                 | 10.000         |
| (+/-) Variação de Capital                             | -              |
| (+/-) Adiantamentos para Futuro Aumento de Capital    | -              |
| (+/-) Dividendos Distribuídos no exercício            | (20.000)       |
| **= CAIXA NAS ATIVIDADES DE FINANCIAMENTO**           | **190.000**    |

**VARIAÇÃO LÍQUIDA DE CAIXA DO PERÍODO** = **148.000**

**SALDO DE CAIXA**
| Linha                                            | Valor (R$)     |
|------------------------------------------------------|---------------:|
| (+) Saldo de Caixa Inicial do Período                 | 202.000        |
| **(=) Saldo de Caixa Final do Período**               | **350.000**    |

*(CHECK: bate com DISPONIBILIDADES do Balanço = 350.000 ✓ OK)*

---
---

# Notas finais para geração de artefatos

- **Os três relatórios são independentes** — o usuário pode pedir qualquer um deles
  isoladamente (só a DRE, só o Balanço, ou só o Fluxo de Caixa). Gerar apenas o que
  foi solicitado; **não gerar os três automaticamente** a menos que o pedido seja
  explicitamente pelo combinado (ex.: "me dá a DRE, o Balanço e o Fluxo de Caixa" ou
  "artefato completo").
- Ao receber um pedido de "DRE atualizada", gerar a consulta DAX seguindo a Seção 1
  (ordem, tipo de linha e operação) e devolver no formato do Layout de Exemplo — DRE.
- Ao receber um pedido de artefato combinando **DRE + Balanço + Fluxo de Caixa**,
  gerar as três consultas com os filtros de período apropriados a cada uma (DRE:
  só período selecionado; Balanço: acumulado 01/2024 até período selecionado;
  Fluxo de Caixa: combinação conforme regras específicas de cada linha) e apresentar
  as três seções no mesmo artefato, na ordem DRE → Balanço → Fluxo de Caixa.
- Sempre incluir os CHECKs (Balanço: `Ativo − (Passivo + PL) = 0`; Fluxo de Caixa:
  `Saldo Final ≈ DISPONIBILIDADES`, tolerância R$ 5,00) no artefato, para validação
  visual de consistência — mesmo quando o Balanço ou o Fluxo forem gerados
  isoladamente.
- Todos os totais/subtotais devem ser **calculados na consulta** — nunca lidos
  diretamente de uma coluna `DRE`/`Balanço` da base, pois essas linhas não existem
  na base de lançamentos.
