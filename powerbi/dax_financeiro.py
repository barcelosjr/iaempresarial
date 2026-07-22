"""Consultas DAX dos relatórios financeiros: DRE, Balanço e Fluxo de Caixa.

Implementa a estrutura definida em ``estrutura_financeira_completa.md`` contra o
modelo semântico real (dataset ``lancamentos_contabeis``, tabela ``lancamentos``).

Cada função devolve **a string DAX pronta** — nada é executado aqui. A execução
fica a cargo do :class:`~powerbi.client.PowerBIClient`.

Particularidades do modelo real (verificadas contra os dados, não presumidas)
-----------------------------------------------------------------------------

1. **Usa-se ``VALOR_AJUSTADO``, nunca ``VALOR``.** ``VALOR_AJUSTADO`` é o mesmo
   número com o sinal já corrigido (``|VALOR_AJUSTADO| = VALOR`` em 100% das
   linhas; 202.437 delas ficam negativas). Com ele, **soma direta** resolve o
   cálculo dos três relatórios — sem ABS:

   * DRE     → receitas somam positivo, custos/despesas somam negativo.
   * Balanço → Ativo e Passivo/PL ambos positivos, e o CHECK
     ``Ativo - (Passivo + PL)`` fecha em zero.

   O sinal **não** acompanha ``NATUREZA`` (há crédito positivo e negativo), então
   não tente derivá-lo — use a coluna. ``NATUREZA`` continua necessária apenas
   para as linhas do Fluxo de Caixa que separam entradas de saídas.

   **Exibição da DRE (atenção ao ler os números).** Seguindo a regra de sinal do
   documento, as linhas de detalhe subtrativas (custos, despesas e deduções) são
   **mostradas positivas** — "Custo de Veículos Novos: 16.777.905,30" —, mas
   **subtraem** nos subtotais. Ou seja, na DRE o valor exibido de uma linha
   subtrativa é o **oposto** da contribuição dela ao resultado; um custo grande e
   positivo reduz o lucro. Veja :func:`operacao_dre`. Balanço e Fluxo de Caixa
   não usam essa inversão: neles o valor exibido é o próprio valor.

2. **``TRIM`` é obrigatório.** Todos os 31 valores da coluna ``DRE`` e 53 dos 54
   da coluna ``Balanço`` têm espaços extras. Filtro por igualdade simples
   (``[DRE] = "Serviços Oficina"``) retorna **vazio**.

3. **``PERIODO`` é texto ``MM/AAAA``**, não data — ordenação alfabética não é
   cronológica. Usa-se a chave inteira ``AAAAMM`` para comparar/acumular.

4. **Saldo de abertura**: existem 463 linhas com ``PERIODO = "01/01/2024"``
   (R$ 407.110.872,20) — é a abertura de 2024, já dentro de ``lancamentos``. A
   chave ``AAAAMM`` a mapeia para ``202401``, então ela entra naturalmente no
   acumulado. A tabela ``saldo_inicial_2024`` é cópia dessas linhas e **não é
   usada** (somá-la duplicaria o saldo).

5. **O modelo não tem medidas oficiais** (zero medidas). Todos os cálculos são
   construídos do zero nestas consultas.

6. **A apuração de resultado é lançada por trimestre.** O Balanço só fecha em
   03, 06, 09 e 12; nos demais meses o CHECK traz o resultado ainda não apurado.
   O Fluxo de Caixa neutraliza esse efeito (ver :func:`fluxo_caixa`) e concilia
   em qualquer mês.

7. **Recorte por ``EMPRESA``.** ``REVENDA`` não é usada nos relatórios.
"""

from __future__ import annotations

from .dax_lib import escapar_texto

# --------------------------------------------------------------------------- #
# Modelo: tabela e colunas
# --------------------------------------------------------------------------- #
TABELA = "lancamentos"

COL_PERIODO = "PERIODO"
COL_NATUREZA = "NATUREZA"
#: Coluna de valor já com o sinal corrigido — use sempre esta, nunca ``VALOR``.
COL_VALOR = "VALOR_AJUSTADO"
COL_DRE = "DRE"
COL_BALANCO = "Balanço"
COL_EMPRESA = "EMPRESA"

# Período mais antigo do modelo (usado como início do acumulado do Balanço).
CHAVE_INICIO = 202401

# --------------------------------------------------------------------------- #
# Estrutura da DRE (ordem e agrupamento conforme o documento)
# --------------------------------------------------------------------------- #
DRE_G1_RECEITA = [
    "Venda de Veículos Novos",
    "Venda de Veículos Usados",
    "Peças e Acessórios",
    "Serviços Oficina",
    "Comissões Diversas",
    "(-) Devoluções",
    "(-) Impostos sobre a Venda",
]

DRE_G2_CUSTOS = [
    "Custo de Veículos Novos",
    "Custo de Veículos Usados",
    "Custo de Peças e Acessórios",
    "Custo de Serviços Oficina",
    "Custo de Serviço de Terceiros",
]

DRE_G3_DESPESAS = [
    "Folha de Pagamento",
    "Despesas Comerciais",
    "Despesas Gerais",
    "Manutenção de Bens",
    "Serviços Profissionais",
    "Taxas e Impostos Diversos",
    "Despesas de Funcionamento",
    "Alugueis e Condomínios",
    "Despesas Gerais e Rateio do Grupo",
    "Outras Despesas Operacionais",
    "Gastos Diversos com Funcionários",
]

DRE_G4_OUTRAS = [
    "(+) Receitas Diversas",
    "(+) Receitas Não Operacionais",
    "(-) Despesas Não Dedutíveis",
    "(-) Despesas Não Operacionais",
]

DRE_G5_DEPRECIACAO = ["Depreciação e Amortização de Ativos"]
DRE_G6_FINANCEIRO = ["(+) Receitas Financeiras", "(-) Despesas Financeiras"]
DRE_G7_IMPOSTOS = ["(-) IR e CSLL"]

#: Linhas cuja **Operação** no documento é ``-`` (deduções, custos e despesas).
#:
#: Elas são **exibidas como valor positivo** na DRE e **subtraídas** nos
#: subtotais — é a "regra de sinal — DRE" de ``estrutura_financeira_completa.md``.
#: Em ``VALOR_AJUSTADO`` esses lançamentos já vêm negativos, então a exibição
#: inverte o sinal e os subtotais continuam somando o valor original.
DRE_LINHAS_SUBTRATIVAS = frozenset(
    [
        "(-) Devoluções",
        "(-) Impostos sobre a Venda",
        *DRE_G2_CUSTOS,
        *DRE_G3_DESPESAS,
        "(-) Despesas Não Dedutíveis",
        "(-) Despesas Não Operacionais",
        *DRE_G5_DEPRECIACAO,
        "(-) Despesas Financeiras",
        *DRE_G7_IMPOSTOS,
    ]
)


def operacao_dre(conta: str) -> int:
    """Devolve o multiplicador de direção da linha na DRE.

    Args:
        conta: Valor da coluna ``DRE`` (ex.: ``"Custo de Veículos Novos"``).

    Returns:
        ``+1`` para linhas que somam no resultado (receitas) e ``-1`` para as
        que subtraem (custos, despesas e deduções).
    """
    return -1 if conta in DRE_LINHAS_SUBTRATIVAS else 1


# --------------------------------------------------------------------------- #
# Estrutura do Balanço (subgrupo -> contas), na ordem de exibição
# --------------------------------------------------------------------------- #
BAL_DISPONIBILIDADES = ["Caixa e Bancos", "Aplicações Financeiras"]
BAL_VALORES_RECEBER = [
    "Contas a Receber",
    "Cartões de Crédito a Receber",
    "Financiamentos a Receber",
    "Adiantamentos a Fornecedores",
    "Outros Adiantamentos",
    "Outros Créditos a Receber",
    "Impostos a Recuperar",
]
BAL_ESTOQUES = [
    "Estoque de Veículos Novos",
    "Estoque de Veículos Usados",
    "Estoque de Peças",
]
BAL_REALIZAVEL_LP = ["Investimentos a Longo Prazo - FVN"]
BAL_INVESTIMENTOS = ["Investimentos a Longo Prazo", "Investimentos Permanentes"]
BAL_IMOBILIZADO = [
    "Terrenos",
    "Edifícios",
    "Instalações",
    "Veículos",
    "Máquinas e Equipamentos",
    "Computadores e Periféricos",
    "Móveis e Utensílios",
    "Construções em Andamento",
    "Benfeitorias em Bens de Terceiros",
    "Consórcios",
    "Aeronaves",
    "(-) Depreciação Acumulada",
]
BAL_INTANGIVEL = ["Direitos de Concessão", "(-) Amortização Acumulada"]

BAL_FORNECEDORES = [
    "Floor Plan Veículos Novos",
    "Floor Plan Veículos Usados",
    "Floor Plan Peças e Acessórios",
    "Fornecedores Diversos",
]
BAL_EMPRESTIMOS = [
    "Empréstimos Bancários",
    "Empréstimos de Terceiros",
    "Conta Garantida",
    "Financiamentos",
    "Notas Comerciais",
]
BAL_OUTRAS_OBRIGACOES = [
    "Obrigações Sociais e Trabalhistas",
    "Obrigações Tributárias e Diversas",
    "Adiantamento de Clientes",
    "Provisões",
    "Outras Contas a Pagar",
    "Lucros a Pagar",
]
BAL_PASSIVO_NAO_CIRC = [
    "Empréstimos e Financiamentos LP",
    "Outros Credores",
    "Parcelamentos LP",
    "Adiantamento Futura Integralização",
]
BAL_PATRIMONIO_LIQUIDO = [
    "Capital Social Integralizado",
    "Reservas de Capital",  # sem lançamento na base — sai como 0
    "Reservas de Lucros",
    "Reservas de Incentivos Fiscais",
    "Prejuízos Acumulados",
    "Ajustes de Exercícios Anteriores",
]

#: Contas classificadas como Ativo (exibidas com o sinal débito-positivo).
CONTAS_ATIVO = (
    BAL_DISPONIBILIDADES
    + BAL_VALORES_RECEBER
    + BAL_ESTOQUES
    + BAL_REALIZAVEL_LP
    + BAL_INVESTIMENTOS
    + BAL_IMOBILIZADO
    + BAL_INTANGIVEL
)

# --------------------------------------------------------------------------- #
# Mapeamento do Fluxo de Caixa
# --------------------------------------------------------------------------- #
FC_VALORES_RECEBER = BAL_VALORES_RECEBER
FC_ESTOQUE = BAL_ESTOQUES
FC_VALORES_PAGAR = [
    "Fornecedores Diversos",
    "Obrigações Sociais e Trabalhistas",
    "Obrigações Tributárias e Diversas",
    "Adiantamento de Clientes",
    "Provisões",
    "Outras Contas a Pagar",
    "Lucros a Pagar",
    "Outros Credores",
    "Parcelamentos LP",
]
FC_INVESTIMENTOS_LP = [
    "Investimentos a Longo Prazo - FVN",
    "Investimentos a Longo Prazo",
    "Investimentos Permanentes",
]
#: Contas de imobilizado/intangível usadas nas linhas do tipo NATUREZA.
FC_IMOBILIZADO = [
    "Terrenos",
    "Edifícios",
    "Instalações",
    "Veículos",
    "Máquinas e Equipamentos",
    "Computadores e Periféricos",
    "Móveis e Utensílios",
    "Construções em Andamento",
    "Benfeitorias em Bens de Terceiros",
    "Consórcios",
    "Aeronaves",
    "Direitos de Concessão",
]
FC_DEPRECIACAO_ACUM = ["(-) Depreciação Acumulada", "(-) Amortização Acumulada"]
FC_EMPRESTIMOS = [
    "Empréstimos Bancários",
    "Empréstimos de Terceiros",
    "Conta Garantida",
    "Financiamentos",
    "Notas Comerciais",
    "Empréstimos e Financiamentos LP",
]
FC_CAPITAL = ["Capital Social Integralizado", "Reservas de Capital"]


# --------------------------------------------------------------------------- #
# Helpers de período
# --------------------------------------------------------------------------- #
def chave_periodo(periodo: str) -> int:
    """Converte um período ``"MM/AAAA"`` na chave inteira ``AAAAMM``.

    Args:
        periodo: Período no formato ``"MM/AAAA"`` (ex.: ``"12/2024"``).

    Returns:
        A chave ordenável, ex.: ``202412``.

    Raises:
        ValueError: Se o formato não for ``MM/AAAA`` com mês entre 1 e 12.
    """
    texto = str(periodo).strip()
    partes = texto.split("/")
    if len(partes) != 2:
        raise ValueError(
            f"Período inválido: {periodo!r}. Use o formato MM/AAAA (ex.: 12/2024)."
        )
    try:
        mes, ano = int(partes[0]), int(partes[1])
    except ValueError as exc:
        raise ValueError(
            f"Período inválido: {periodo!r}. Use o formato MM/AAAA (ex.: 12/2024)."
        ) from exc
    if not 1 <= mes <= 12:
        raise ValueError(f"Mês inválido em {periodo!r}: deve estar entre 01 e 12.")
    if ano < 1900:
        raise ValueError(f"Ano inválido em {periodo!r}.")
    return ano * 100 + mes


def somar_meses(chave: int, delta: int) -> int:
    """Soma (ou subtrai) meses a uma chave ``AAAAMM``, virando o ano corretamente.

    Args:
        chave: Chave no formato ``AAAAMM`` (ex.: ``202501``).
        delta: Meses a somar (negativo para subtrair).

    Returns:
        A nova chave ``AAAAMM``, ex.: ``(202501, -1)`` -> ``202412``.
    """
    ano, mes = divmod(chave, 100)
    total = ano * 12 + (mes - 1) + delta
    novo_ano, novo_mes = divmod(total, 12)
    return novo_ano * 100 + novo_mes + 1


def periodo_anterior(periodo: str) -> str:
    """Devolve o período imediatamente anterior no formato ``"MM/AAAA"``.

    Args:
        periodo: Período no formato ``"MM/AAAA"``.

    Returns:
        O mês anterior, ex.: ``"01/2025"`` -> ``"12/2024"``.
    """
    chave = somar_meses(chave_periodo(periodo), -1)
    ano, mes = divmod(chave, 100)
    return f"{mes:02d}/{ano}"


#: Meses em que a apuração de resultado é lançada na base (fim de trimestre).
MESES_FECHAMENTO = (3, 6, 9, 12)


def validar_fim_de_trimestre(periodo: str) -> int:
    """Valida que o período é um fim de trimestre e devolve sua chave.

    A base lança a apuração de resultado por trimestre: o Balanço só fecha
    (``Ativo - (Passivo + PL) = 0``) em 03, 06, 09 e 12. O Fluxo de Caixa no
    modo trimestral exige essas datas nas duas pontas da comparação.

    Args:
        periodo: Período no formato ``"MM/AAAA"``.

    Returns:
        A chave ``AAAAMM`` do período.

    Raises:
        ValueError: Se o mês não for 03, 06, 09 nem 12.
    """
    chave = chave_periodo(periodo)
    mes = chave % 100
    if mes not in MESES_FECHAMENTO:
        raise ValueError(
            f"Período {periodo!r} não é fim de trimestre. No modo trimestral use "
            "03, 06, 09 ou 12 — a base só fecha o Balanço nesses meses "
            "(apuração de resultado trimestral)."
        )
    return chave


def validar_fim_de_ano(periodo: str) -> int:
    """Valida que o período é dezembro e devolve sua chave.

    Args:
        periodo: Período no formato ``"MM/AAAA"``.

    Returns:
        A chave ``AAAAMM`` do período (sempre terminando em ``12``).

    Raises:
        ValueError: Se o mês não for 12.
    """
    chave = chave_periodo(periodo)
    if chave % 100 != 12:
        raise ValueError(
            f"Período {periodo!r} não é fim de ano. No modo anual use 12 "
            "(dezembro) do ano desejado — o intervalo somado é janeiro a "
            "dezembro desse ano."
        )
    return chave


#: Modos de agregação de período aceitos por :func:`dre`.
MODOS_PERIODO = ("mensal", "trimestral", "anual")


def intervalo_do_modo(periodo: str, modo: str) -> tuple[int, int]:
    """Resolve o intervalo fechado de chaves ``AAAAMM`` coberto pelo modo.

    Args:
        periodo: Período de referência no formato ``"MM/AAAA"``.
        modo: ``"mensal"`` (só o mês), ``"trimestral"`` (os 3 meses do
            trimestre que termina em ``periodo``) ou ``"anual"`` (janeiro a
            dezembro do ano de ``periodo``).

    Returns:
        Tupla ``(chave_de, chave_ate)``, ambas inclusive.

    Raises:
        ValueError: Se ``modo`` for inválido, ou se ``periodo`` não for
            compatível com o modo (trimestral exige fim de trimestre; anual
            exige dezembro).
    """
    modo = str(modo).strip().lower()
    if modo == "mensal":
        chave = chave_periodo(periodo)
        return chave, chave
    if modo == "trimestral":
        chave = validar_fim_de_trimestre(periodo)
        return somar_meses(chave, -2), chave
    if modo == "anual":
        chave = validar_fim_de_ano(periodo)
        return (chave // 100) * 100 + 1, chave
    raise ValueError(
        f"Modo inválido: {modo!r}. Use um de: {', '.join(MODOS_PERIODO)}."
    )


# --------------------------------------------------------------------------- #
# Helpers de montagem DAX
# --------------------------------------------------------------------------- #
def _col(coluna: str) -> str:
    """Referência segura de coluna da tabela de lançamentos."""
    return f"'{TABELA}'[{coluna}]"


def _expr_chave() -> str:
    """Expressão DAX que converte ``PERIODO`` (texto) na chave ``AAAAMM``."""
    p = _col(COL_PERIODO)
    return f"VALUE(RIGHT({p}, 4)) * 100 + VALUE(LEFT({p}, 2))"


def _filtro_entidade(empresa: str | None) -> str:
    """Monta a condição opcional de ``EMPRESA`` (com ``TRIM``).

    Args:
        empresa: Nome da empresa (ex.: ``"KOBE"``) ou ``None`` para consolidado.

    Returns:
        A condição DAX pronta para concatenar, ou string vazia.
    """
    if not empresa:
        return ""
    return f' && TRIM({_col(COL_EMPRESA)}) = "{escapar_texto(empresa)}"'


def _var_base(nome: str, comparador: str, chave: int, entidade: str) -> str:
    """Monta um ``VAR`` com o recorte de linhas do período.

    Args:
        nome: Nome da variável DAX.
        comparador: ``"="`` (só o período) ou ``"<="`` (acumulado).
        chave: Chave ``AAAAMM`` de referência.
        entidade: Condições extras já formatadas (EMPRESA/REVENDA).

    Returns:
        A linha ``VAR ... = FILTER(...)``.
    """
    return (
        f"VAR {nome} = FILTER('{TABELA}', {_expr_chave()} {comparador} {chave}{entidade})"
    )


def _var_base_intervalo(
    nome: str, chave_de: int, chave_ate: int, entidade: str
) -> str:
    """Monta um ``VAR`` com o recorte de um intervalo fechado de períodos.

    Args:
        nome: Nome da variável DAX.
        chave_de: Chave ``AAAAMM`` inicial (inclusive).
        chave_ate: Chave ``AAAAMM`` final (inclusive).
        entidade: Condições extras já formatadas (EMPRESA/REVENDA).

    Returns:
        A linha ``VAR ... = FILTER(...)``.
    """
    expr = _expr_chave()
    if chave_de == chave_ate:
        condicao = f"{expr} = {chave_ate}"
    else:
        condicao = f"{expr} >= {chave_de} && {expr} <= {chave_ate}"
    return f"VAR {nome} = FILTER('{TABELA}', {condicao}{entidade})"


def _var_agregado(nome: str, base: str, coluna_cat: str) -> str:
    """Monta o ``VAR`` que pré-agrega ``VALOR_AJUSTADO`` por categoria.

    Agrega uma única vez (``GROUPBY``) em vez de varrer a base por linha do
    relatório — o que mantém a consulta rápida mesmo com centenas de milhares
    de lançamentos.

    Args:
        nome: Nome da variável de saída.
        base: Nome da variável com o recorte de linhas.
        coluna_cat: Coluna de classificação (``DRE`` ou ``Balanço``).

    Returns:
        As linhas ``VAR`` de preparação e agregação.
    """
    prep = f"{nome}Prep"
    return (
        f'VAR {prep} = ADDCOLUMNS({base}, "@Cat", TRIM({_col(coluna_cat)}), '
        f'"@Sinal", {_col(COL_VALOR)})\n'
        f'VAR {nome} = GROUPBY({prep}, [@Cat], "@Valor", SUMX(CURRENTGROUP(), [@Sinal]))'
    )


def _lookup(agregado: str, categoria: str) -> str:
    """Expressão que lê o valor de uma categoria no agregado (0 se ausente)."""
    return (
        f'COALESCE(MAXX(FILTER({agregado}, [@Cat] = "{escapar_texto(categoria)}"), '
        f"[@Valor]), 0)"
    )


def _soma_lookup(agregado: str, categorias: list[str]) -> str:
    """Soma das categorias informadas dentro do agregado."""
    if not categorias:
        return "0"
    return " + ".join(_lookup(agregado, c) for c in categorias)


def _linha(ordem: int, bloco: str, linha: str, tipo: str, expr: str) -> str:
    """Monta um ``ROW`` do relatório."""
    return (
        f'    ROW("Ordem", {ordem}, "Bloco", "{escapar_texto(bloco)}", '
        f'"Linha", "{escapar_texto(linha)}", "Tipo", "{tipo}", "Valor", {expr})'
    )


# --------------------------------------------------------------------------- #
# DRE
# --------------------------------------------------------------------------- #
def dre(periodo: str, empresa: str | None = None, modo: str = "mensal") -> str:
    """Monta a DRE completa do intervalo pedido (soma de lançamentos, não cumulativa).

    Segue a estrutura, ordem e agrupamento de ``estrutura_financeira_completa.md``,
    inclusive a **regra de sinal** do documento:

    * **Linhas de detalhe saem sempre positivas.** Custos, despesas e deduções
      (operação ``-``) têm o sinal invertido na exibição, já que em
      ``VALOR_AJUSTADO`` chegam negativos. Assim a DRE é lida como um relatório
      contábil: "Custo de Veículos Novos: 16.777.905,30", não com sinal negativo.
    * **Os subtotais subtraem essas linhas**, somando o valor original (negativo).
      Por isso ``Lucro Bruto = Receita Líquida + Custos`` continua correto, mesmo
      com os custos aparecendo positivos acima.

    Ou seja: o valor exibido de uma linha subtrativa é o oposto da contribuição
    dela ao resultado. Use :func:`operacao_dre` para saber a direção de cada linha.

    Modos de período (evita ter que somar meses manualmente/em várias chamadas):

    * ``"mensal"`` (padrão) — só o mês de ``periodo``.
    * ``"trimestral"`` — os 3 meses do trimestre que termina em ``periodo``.
      Exige período 03, 06, 09 ou 12 (ex.: ``"03/2026"`` soma jan+fev+mar/2026).
    * ``"anual"`` — janeiro a dezembro do ano de ``periodo``. Exige período 12
      (ex.: ``"12/2025"`` soma o ano inteiro de 2025).

    Em qualquer modo o resultado é uma soma de lançamentos do intervalo — não há
    acumulado entre anos nem comparação com período anterior (isso é exclusivo
    do Balanço e do Fluxo de Caixa).

    Args:
        periodo: Período de referência no formato ``"MM/AAAA"`` (ex.: ``"12/2024"``).
        empresa: Filtro opcional por ``EMPRESA`` (ex.: ``"KOBE"``).
            ``None`` devolve o consolidado do grupo.
        modo: ``"mensal"`` (padrão), ``"trimestral"`` ou ``"anual"``.

    Returns:
        A consulta DAX que devolve as linhas da DRE com
        ``Ordem``, ``Bloco``, ``Linha``, ``Tipo`` e ``Valor``.

    Raises:
        ValueError: Se ``modo`` for inválido, ou se ``periodo`` não for
            compatível com o modo (ver :func:`intervalo_do_modo`).
    """
    chave_de, chave_ate = intervalo_do_modo(periodo, modo)
    ent = _filtro_entidade(empresa)

    partes = [
        "EVALUATE",
        _var_base_intervalo("_Base", chave_de, chave_ate, ent),
        _var_agregado("_Agg", "_Base", COL_DRE),
    ]

    def detalhe(conta: str) -> str:
        """Expressão de exibição da linha: subtrativas aparecem positivas."""
        expr = _lookup("_Agg", conta)
        return f"-({expr})" if operacao_dre(conta) == -1 else expr

    # Subtotais como variáveis, para reuso nos indicadores.
    partes.append(f"VAR _RL = {_soma_lookup('_Agg', DRE_G1_RECEITA)}")
    partes.append(f"VAR _Custos = {_soma_lookup('_Agg', DRE_G2_CUSTOS)}")
    partes.append("VAR _LucroBruto = _RL + _Custos")
    partes.append(f"VAR _Desp = {_soma_lookup('_Agg', DRE_G3_DESPESAS)}")
    partes.append(f"VAR _Outras = {_soma_lookup('_Agg', DRE_G4_OUTRAS)}")
    partes.append("VAR _Ebitda = _LucroBruto + _Desp + _Outras")
    partes.append(f"VAR _Deprec = {_soma_lookup('_Agg', DRE_G5_DEPRECIACAO)}")
    partes.append("VAR _Ebit = _Ebitda + _Deprec")
    partes.append(f"VAR _ResFin = {_soma_lookup('_Agg', DRE_G6_FINANCEIRO)}")
    partes.append("VAR _Lair = _Ebit + _ResFin")
    partes.append(f"VAR _Impostos = {_soma_lookup('_Agg', DRE_G7_IMPOSTOS)}")
    partes.append("VAR _LucroLiquido = _Lair + _Impostos")

    linhas: list[str] = []
    ordem = 1

    b1 = "1. RECEITA BRUTA DE VENDAS E SERVIÇOS"
    for conta in DRE_G1_RECEITA:
        linhas.append(_linha(ordem, b1, conta, "DETALHE", detalhe(conta)))
        ordem += 1
    linhas.append(_linha(ordem, b1, "= RECEITA LÍQUIDA", "SUBTOTAL", "_RL"))
    ordem += 1

    b2 = "2. CUSTOS DAS MERCADORIAS E SERVIÇOS"
    for conta in DRE_G2_CUSTOS:
        linhas.append(_linha(ordem, b2, conta, "DETALHE", detalhe(conta)))
        ordem += 1
    linhas.append(_linha(ordem, b2, "= LUCRO BRUTO", "SUBTOTAL", "_LucroBruto"))
    ordem += 1
    linhas.append(
        _linha(ordem, b2, "% Margem Bruta", "INDICADOR", "DIVIDE(_LucroBruto, _RL)")
    )
    ordem += 1

    b3 = "3. DESPESAS OPERACIONAIS"
    linhas.append(
        _linha(ordem, b3, "(subtotal de exibição do bloco)", "SUBTOTAL", "-_Desp")
    )
    ordem += 1
    for conta in DRE_G3_DESPESAS:
        linhas.append(_linha(ordem, b3, conta, "DETALHE", detalhe(conta)))
        ordem += 1

    b4 = "4. OUTRAS RECEITAS/DESPESAS"
    for conta in DRE_G4_OUTRAS:
        linhas.append(_linha(ordem, b4, conta, "DETALHE", detalhe(conta)))
        ordem += 1
    linhas.append(_linha(ordem, b4, "= EBITDA", "SUBTOTAL", "_Ebitda"))
    ordem += 1
    linhas.append(
        _linha(ordem, b4, "% EBITDA/RL", "INDICADOR", "DIVIDE(_Ebitda, _RL)")
    )
    ordem += 1

    b5 = "5. DEPRECIAÇÃO E AMORTIZAÇÃO"
    for conta in DRE_G5_DEPRECIACAO:
        linhas.append(_linha(ordem, b5, conta, "DETALHE", detalhe(conta)))
        ordem += 1
    linhas.append(
        _linha(ordem, b5, "= EBIT (Resultado Operacional)", "SUBTOTAL", "_Ebit")
    )
    ordem += 1

    b6 = "6. RESULTADO FINANCEIRO"
    for conta in DRE_G6_FINANCEIRO:
        linhas.append(_linha(ordem, b6, conta, "DETALHE", detalhe(conta)))
        ordem += 1
    linhas.append(
        _linha(ordem, b6, "= LAIR (Resultado antes do IR)", "SUBTOTAL", "_Lair")
    )
    ordem += 1

    b7 = "7. IMPOSTOS SOBRE O LUCRO"
    for conta in DRE_G7_IMPOSTOS:
        linhas.append(_linha(ordem, b7, conta, "DETALHE", detalhe(conta)))
        ordem += 1
    linhas.append(
        _linha(ordem, b7, "= LUCRO LÍQUIDO DO EXERCÍCIO", "SUBTOTAL", "_LucroLiquido")
    )
    ordem += 1
    linhas.append(
        _linha(
            ordem, b7, "% Margem Líquida", "INDICADOR", "DIVIDE(_LucroLiquido, _RL)"
        )
    )

    partes.append("RETURN UNION(\n" + ",\n".join(linhas) + "\n)")
    return "\n".join(partes)


# --------------------------------------------------------------------------- #
# Balanço Patrimonial
# --------------------------------------------------------------------------- #
def balanco(periodo: str, empresa: str | None = None) -> str:
    """Monta o Balanço Patrimonial acumulado até o período.

    O saldo é cumulativo desde ``01/2024`` (período mais antigo do modelo,
    incluindo o saldo de abertura) até o período informado, conforme a regra do
    documento. Com ``VALOR_AJUSTADO`` a soma é direta: Ativo e Passivo/PL saem
    ambos positivos e o CHECK ``Ativo - (Passivo + PL)`` fecha em zero.

    Atenção: a apuração de resultado é lançada por trimestre, então o CHECK só
    zera em 03, 06, 09 e 12. Nos demais meses ele traz o resultado ainda não
    apurado — reporte a divergência, não a esconda.

    Args:
        periodo: Período no formato ``"MM/AAAA"`` (ex.: ``"12/2024"``).
        empresa: Filtro opcional por ``EMPRESA``. ``None`` = consolidado.

    Returns:
        A consulta DAX que devolve as linhas do Balanço com
        ``Ordem``, ``Bloco``, ``Linha``, ``Tipo`` e ``Valor``.
    """
    chave = chave_periodo(periodo)
    ent = _filtro_entidade(empresa)

    partes = [
        "EVALUATE",
        _var_base("_Base", "<=", chave, ent),
        _var_agregado("_Agg", "_Base", COL_BALANCO),
    ]

    def soma(contas: list[str]) -> str:
        return _soma_lookup("_Agg", contas)

    partes.append(f"VAR _Disp = {soma(BAL_DISPONIBILIDADES)}")
    partes.append(f"VAR _Receber = {soma(BAL_VALORES_RECEBER)}")
    partes.append(f"VAR _Estoques = {soma(BAL_ESTOQUES)}")
    partes.append("VAR _AtivoCirc = _Disp + _Receber + _Estoques")
    partes.append(f"VAR _RealizavelLP = {soma(BAL_REALIZAVEL_LP)}")
    partes.append(f"VAR _Investimentos = {soma(BAL_INVESTIMENTOS)}")
    partes.append(f"VAR _Imobilizado = {soma(BAL_IMOBILIZADO)}")
    partes.append(f"VAR _Intangivel = {soma(BAL_INTANGIVEL)}")
    partes.append(
        "VAR _AtivoNaoCirc = _RealizavelLP + _Investimentos + _Imobilizado + _Intangivel"
    )
    partes.append("VAR _TotalAtivo = _AtivoCirc + _AtivoNaoCirc")

    partes.append(f"VAR _Fornecedores = {soma(BAL_FORNECEDORES)}")
    partes.append(f"VAR _Emprestimos = {soma(BAL_EMPRESTIMOS)}")
    partes.append(f"VAR _OutrasObrig = {soma(BAL_OUTRAS_OBRIGACOES)}")
    partes.append("VAR _PassivoCirc = _Fornecedores + _Emprestimos + _OutrasObrig")
    partes.append(f"VAR _PassivoNaoCirc = {soma(BAL_PASSIVO_NAO_CIRC)}")
    partes.append(f"VAR _PL = {soma(BAL_PATRIMONIO_LIQUIDO)}")
    partes.append("VAR _TotalPassivoPL = _PassivoCirc + _PassivoNaoCirc + _PL")

    linhas: list[str] = []
    ordem = 1

    def bloco_detalhe(bloco: str, contas: list[str]) -> None:
        nonlocal ordem
        for conta in contas:
            linhas.append(
                _linha(ordem, bloco, conta, "DETALHE", _lookup("_Agg", conta))
            )
            ordem += 1

    def subtotal(bloco: str, rotulo: str, var: str) -> None:
        nonlocal ordem
        linhas.append(_linha(ordem, bloco, rotulo, "SUBTOTAL", var))
        ordem += 1

    bA = "ATIVO CIRCULANTE"
    bloco_detalhe(bA, BAL_DISPONIBILIDADES)
    subtotal(bA, "DISPONIBILIDADES", "_Disp")
    bloco_detalhe(bA, BAL_VALORES_RECEBER)
    subtotal(bA, "VALORES A RECEBER", "_Receber")
    bloco_detalhe(bA, BAL_ESTOQUES)
    subtotal(bA, "ESTOQUES", "_Estoques")
    subtotal(bA, "= TOTAL ATIVO CIRCULANTE", "_AtivoCirc")

    bB = "ATIVO NÃO CIRCULANTE"
    bloco_detalhe(bB, BAL_REALIZAVEL_LP)
    subtotal(bB, "REALIZÁVEL A LONGO PRAZO", "_RealizavelLP")
    bloco_detalhe(bB, BAL_INVESTIMENTOS)
    subtotal(bB, "INVESTIMENTOS", "_Investimentos")
    bloco_detalhe(bB, BAL_IMOBILIZADO)
    subtotal(bB, "IMOBILIZADO DE USO", "_Imobilizado")
    bloco_detalhe(bB, BAL_INTANGIVEL)
    subtotal(bB, "INTANGÍVEL", "_Intangivel")
    subtotal(bB, "= TOTAL ATIVO NÃO CIRCULANTE", "_AtivoNaoCirc")
    subtotal(bB, "= TOTAL DO ATIVO", "_TotalAtivo")

    bC = "PASSIVO CIRCULANTE"
    bloco_detalhe(bC, BAL_FORNECEDORES)
    subtotal(bC, "FORNECEDORES", "_Fornecedores")
    bloco_detalhe(bC, BAL_EMPRESTIMOS)
    subtotal(bC, "EMPRÉSTIMOS E FINANCIAMENTOS", "_Emprestimos")
    bloco_detalhe(bC, BAL_OUTRAS_OBRIGACOES)
    subtotal(bC, "OUTRAS OBRIGAÇÕES", "_OutrasObrig")
    subtotal(bC, "= TOTAL PASSIVO CIRCULANTE", "_PassivoCirc")

    bD = "PASSIVO NÃO CIRCULANTE"
    bloco_detalhe(bD, BAL_PASSIVO_NAO_CIRC)
    subtotal(bD, "= TOTAL PASSIVO NÃO CIRCULANTE", "_PassivoNaoCirc")

    bE = "PATRIMÔNIO LÍQUIDO"
    bloco_detalhe(bE, BAL_PATRIMONIO_LIQUIDO)
    subtotal(bE, "= TOTAL PATRIMÔNIO LÍQUIDO", "_PL")
    subtotal(bE, "= TOTAL PASSIVO + PL", "_TotalPassivoPL")

    linhas.append(
        _linha(
            ordem,
            "CHECK",
            "CHECK: Ativo - (Passivo + PL)",
            "CHECK",
            "_TotalAtivo - _TotalPassivoPL",
        )
    )

    partes.append("RETURN UNION(\n" + ",\n".join(linhas) + "\n)")
    return "\n".join(partes)


# --------------------------------------------------------------------------- #
# Fluxo de Caixa (método indireto)
# --------------------------------------------------------------------------- #
def fluxo_caixa(
    periodo: str,
    empresa: str | None = None,
    modo: str = "mensal",
) -> str:
    """Monta o Fluxo de Caixa (método indireto) e **concilia sempre**.

    Como ``VALOR_AJUSTADO`` traz o sinal correto e o saldo do Balanço é a soma
    acumulada, a variação de uma conta no período é simplesmente a soma dos
    lançamentos **daquele período** — não é preciso comparar dois acumulados.
    O sinal de caixa segue a natureza da conta:

    * **Ativo** (ex.: Contas a Receber, Estoque): ``Variação = -Σ(período)``
      — crescer o ativo consome caixa.
    * **Passivo/PL** (ex.: Fornecedores, Empréstimos): ``Variação = +Σ(período)``
      — crescer o passivo gera caixa.

    Conciliação
    -----------
    Vale a identidade ``ΔCaixa = Σ(variações das demais contas do Balanço)``.
    Duas escolhas do documento, porém, não são exatas: as linhas de imobilizado
    usam somas brutas por ``NATUREZA`` no lugar da variação, e três contas de PL
    (Reservas de Lucros, Reservas de Incentivos Fiscais e Prejuízos Acumulados)
    ficam de fora, substituídas pelo Lucro Líquido da DRE. Some-se a isso a
    apuração de resultado trimestral da base.

    Para que o relatório **feche em qualquer mês**, as linhas de imobilizado são
    calculadas como a decomposição exata da variação (parte credora = vendas,
    parte devedora = adições) e o que restar aparece numa linha explícita de
    ``AJUSTE DE CONCILIAÇÃO`` — visível, nunca embutida em outra linha. Com
    isso o CHECK final fecha em zero por construção.

    Args:
        periodo: Período no formato ``"MM/AAAA"`` (ex.: ``"12/2024"``).
        empresa: Filtro opcional por ``EMPRESA``. ``None`` = consolidado.
        modo: ``"mensal"`` (padrão) compara o mês com o anterior;
            ``"trimestral"`` soma os três meses do trimestre e compara com o
            fechamento anterior (exige período 03, 06, 09 ou 12).

    Returns:
        A consulta DAX que devolve as linhas do Fluxo de Caixa com
        ``Ordem``, ``Bloco``, ``Linha``, ``Tipo`` e ``Valor``.

    Raises:
        ValueError: Se ``modo`` for inválido, ou se no modo trimestral o
            período não for fim de trimestre.
    """
    modo = str(modo).strip().lower()
    if modo not in ("mensal", "trimestral"):
        raise ValueError(f"Modo inválido: {modo!r}. Use 'mensal' ou 'trimestral'.")

    if modo == "trimestral":
        chave = validar_fim_de_trimestre(periodo)
        chave_de = somar_meses(chave, -2)
        chave_ant = somar_meses(chave, -3)
    else:
        chave = chave_periodo(periodo)
        chave_de = chave
        chave_ant = somar_meses(chave, -1)

    ent = _filtro_entidade(empresa)
    natureza = _col(COL_NATUREZA)

    partes = [
        "EVALUATE",
        # Movimento do intervalo: serve para DRE, variações e linhas por NATUREZA.
        _var_base_intervalo("_Per", chave_de, chave, ent),
        # Acumulado até o período anterior: usado só para o saldo inicial de caixa.
        _var_base("_AteAnt", "<=", chave_ant, ent),
        _var_agregado("_AggDre", "_Per", COL_DRE),
        _var_agregado("_AggBal", "_Per", COL_BALANCO),
        _var_agregado("_AggAnt", "_AteAnt", COL_BALANCO),
        # Movimento por conta e natureza, para separar entradas de saídas.
        f'VAR _NatPrep = ADDCOLUMNS(_Per, "@Cat", TRIM({_col(COL_BALANCO)}), '
        f'"@Nat", {natureza}, "@V", {_col(COL_VALOR)})',
        'VAR _AggNat = GROUPBY(_NatPrep, [@Cat], [@Nat], "@Valor", '
        "SUMX(CURRENTGROUP(), [@V]))",
    ]

    # --- Resultado da DRE no intervalo --------------------------------------- #
    partes.append(f"VAR _RL = {_soma_lookup('_AggDre', DRE_G1_RECEITA)}")
    partes.append(f"VAR _Custos = {_soma_lookup('_AggDre', DRE_G2_CUSTOS)}")
    partes.append(f"VAR _Desp = {_soma_lookup('_AggDre', DRE_G3_DESPESAS)}")
    partes.append(f"VAR _Outras = {_soma_lookup('_AggDre', DRE_G4_OUTRAS)}")
    partes.append(f"VAR _Deprec = {_soma_lookup('_AggDre', DRE_G5_DEPRECIACAO)}")
    partes.append(f"VAR _ResFin = {_soma_lookup('_AggDre', DRE_G6_FINANCEIRO)}")
    partes.append(f"VAR _Impostos = {_soma_lookup('_AggDre', DRE_G7_IMPOSTOS)}")
    partes.append(
        "VAR _LucroLiquido = _RL + _Custos + _Desp + _Outras + _Deprec + _ResFin"
        " + _Impostos"
    )
    # Depreciação é despesa sem saída de caixa: volta somando.
    partes.append("VAR _DeprecAdd = -_Deprec")

    def variacao(contas: list[str]) -> str:
        """Efeito de caixa da variação das contas (ativo consome, passivo gera)."""
        termos = []
        for conta in contas:
            sinal = "-" if conta in CONTAS_ATIVO else "+"
            termos.append(f"{sinal}({_lookup('_AggBal', conta)})")
        return " ".join(termos).lstrip("+").strip() or "0"

    partes.append(f"VAR _VarAjustes = {variacao(['Ajustes de Exercícios Anteriores'])}")
    for i, conta in enumerate(FC_VALORES_RECEBER):
        partes.append(f"VAR _VR{i} = {variacao([conta])}")
    partes.append(
        "VAR _ValoresReceber = "
        + " + ".join(f"_VR{i}" for i in range(len(FC_VALORES_RECEBER)))
    )
    for i, conta in enumerate(FC_ESTOQUE):
        partes.append(f"VAR _VE{i} = {variacao([conta])}")
    partes.append(
        "VAR _Estoque = " + " + ".join(f"_VE{i}" for i in range(len(FC_ESTOQUE)))
    )
    for i, conta in enumerate(FC_VALORES_PAGAR):
        partes.append(f"VAR _VP{i} = {variacao([conta])}")
    partes.append(
        "VAR _ValoresPagar = "
        + " + ".join(f"_VP{i}" for i in range(len(FC_VALORES_PAGAR)))
    )
    partes.append(
        "VAR _CaixaOperacional = _LucroLiquido + _DeprecAdd + _VarAjustes"
        " + _ValoresReceber + _Estoque + _ValoresPagar"
    )

    # --- Investimento -------------------------------------------------------- #
    partes.append(f"VAR _InvLP = {variacao(FC_INVESTIMENTOS_LP)}")

    def por_natureza(contas: list[str], nat: str) -> str:
        """Movimento das contas restrito a uma natureza (C ou D)."""
        termos = [
            f'COALESCE(MAXX(FILTER(_AggNat, [@Cat] = "{escapar_texto(c)}"'
            f' && [@Nat] = "{nat}"), [@Valor]), 0)'
            for c in contas
        ]
        return " + ".join(termos) if termos else "0"

    # Imobilizado + intangível: a soma das duas linhas equivale exatamente à
    # variação do bloco, mantendo a apresentação do documento (venda / adições).
    imob_todas = FC_IMOBILIZADO + FC_DEPRECIACAO_ACUM
    partes.append(f"VAR _VendaAtivos = -({por_natureza(imob_todas, 'C')})")
    partes.append(f"VAR _AdicoesAtivo = -({por_natureza(imob_todas, 'D')})")
    partes.append("VAR _CaixaInvestimento = _InvLP + _VendaAtivos + _AdicoesAtivo")

    # --- Financiamento ------------------------------------------------------- #
    partes.append(f"VAR _VarEmprestimos = {variacao(FC_EMPRESTIMOS)}")
    partes.append(f"VAR _VarFPNovos = {variacao(['Floor Plan Veículos Novos'])}")
    partes.append(f"VAR _VarFPUsados = {variacao(['Floor Plan Veículos Usados'])}")
    partes.append(f"VAR _VarFPPecas = {variacao(['Floor Plan Peças e Acessórios'])}")
    partes.append(f"VAR _VarCapital = {variacao(FC_CAPITAL)}")
    partes.append(f"VAR _VarAFAC = {variacao(['Adiantamento Futura Integralização'])}")
    # Memo: o efeito de caixa dos dividendos já está na variação de Lucros a
    # Pagar (seção I). Exibido para leitura, mas fora do subtotal, para não
    # contar duas vezes.
    partes.append(f"VAR _Dividendos = -({por_natureza(['Lucros a Pagar'], 'C')})")
    partes.append(
        "VAR _CaixaFinanciamento = _VarEmprestimos + _VarFPNovos + _VarFPUsados"
        " + _VarFPPecas + _VarCapital + _VarAFAC"
    )

    # --- Conciliação --------------------------------------------------------- #
    partes.append(
        f"VAR _DeltaCaixa = {_soma_lookup('_AggBal', BAL_DISPONIBILIDADES)}"
    )
    partes.append(
        "VAR _SomaSecoes = _CaixaOperacional + _CaixaInvestimento"
        " + _CaixaFinanciamento"
    )
    partes.append("VAR _Ajuste = _DeltaCaixa - _SomaSecoes")
    partes.append("VAR _VariacaoLiquida = _SomaSecoes + _Ajuste")
    partes.append(
        f"VAR _SaldoInicial = {_soma_lookup('_AggAnt', BAL_DISPONIBILIDADES)}"
    )
    partes.append("VAR _SaldoFinal = _SaldoInicial + _VariacaoLiquida")
    partes.append("VAR _DispBalanco = _SaldoInicial + _DeltaCaixa")

    # --- Montagem das linhas ------------------------------------------------- #
    linhas: list[str] = []
    ordem = 1

    def add(bloco: str, rotulo: str, tipo: str, expr: str) -> None:
        nonlocal ordem
        linhas.append(_linha(ordem, bloco, rotulo, tipo, expr))
        ordem += 1

    b1 = "I. ATIVIDADES OPERACIONAIS"
    add(b1, "Lucro Líquido do Exercício", "DRE", "_LucroLiquido")
    add(b1, "Depreciação e Amortização de Ativos", "DRE", "_DeprecAdd")
    add(b1, "Ajustes de Exercícios Anteriores", "VARIAÇÃO", "_VarAjustes")
    add(b1, "Outros Ajustes", "MANUAL", "0")
    for i, conta in enumerate(FC_VALORES_RECEBER):
        add(b1, f"(+/-) Variação em {conta}", "VARIAÇÃO", f"_VR{i}")
    add(b1, "VALORES A RECEBER", "SUBTOTAL", "_ValoresReceber")
    for i, conta in enumerate(FC_ESTOQUE):
        add(b1, f"(+/-) Variação em {conta}", "VARIAÇÃO", f"_VE{i}")
    add(b1, "ESTOQUE", "SUBTOTAL", "_Estoque")
    for i, conta in enumerate(FC_VALORES_PAGAR):
        add(b1, f"(+/-) Variação em {conta}", "VARIAÇÃO", f"_VP{i}")
    add(b1, "VALORES A PAGAR", "SUBTOTAL", "_ValoresPagar")
    add(b1, "= CAIXA GERADO NAS ATIVIDADES OPERACIONAIS", "SUBTOTAL", "_CaixaOperacional")

    b2 = "II. ATIVIDADES DE INVESTIMENTO"
    add(b2, "(+/-) Investimentos a Longo Prazo", "VARIAÇÃO", "_InvLP")
    add(b2, "(+) Venda de Ativos Imobilizados", "VARIAÇÃO", "_VendaAtivos")
    add(b2, "(-) Adições ao Ativo Imobilizado", "VARIAÇÃO", "_AdicoesAtivo")
    add(b2, "= CAIXA NAS ATIVIDADES DE INVESTIMENTO", "SUBTOTAL", "_CaixaInvestimento")

    b3 = "III. ATIVIDADES DE FINANCIAMENTO"
    add(b3, "(+/-) Empréstimos e Financiamentos", "VARIAÇÃO", "_VarEmprestimos")
    add(b3, "(+/-) Variação em Floor Plan de Veículos Novos", "VARIAÇÃO", "_VarFPNovos")
    add(b3, "(+/-) Variação em Floor Plan de Veículos Usados", "VARIAÇÃO", "_VarFPUsados")
    add(b3, "(+/-) Variação em Floor Plan de Peças", "VARIAÇÃO", "_VarFPPecas")
    add(b3, "(+/-) Variação de Capital", "VARIAÇÃO", "_VarCapital")
    add(b3, "(+/-) Adiantamentos para Futuro Aumento de Capital", "VARIAÇÃO", "_VarAFAC")
    add(b3, "= CAIXA NAS ATIVIDADES DE FINANCIAMENTO", "SUBTOTAL", "_CaixaFinanciamento")
    add(
        b3,
        "(memo) Dividendos Distribuídos — já contidos na variação de Lucros a Pagar",
        "MEMO",
        "_Dividendos",
    )

    b4 = "SALDO DE CAIXA"
    add(
        b4,
        "AJUSTE DE CONCILIAÇÃO (apuração trimestral e contas de PL fora da estrutura)",
        "AJUSTE",
        "_Ajuste",
    )
    add(b4, "VARIAÇÃO LÍQUIDA DE CAIXA DO PERÍODO", "SUBTOTAL", "_VariacaoLiquida")
    add(b4, "(+) Saldo de Caixa Inicial do Período", "SALDO", "_SaldoInicial")
    add(b4, "(=) Saldo de Caixa Final do Período", "SALDO", "_SaldoFinal")
    add(b4, "DISPONIBILIDADES no Balanço (referência)", "CHECK", "_DispBalanco")
    add(
        b4,
        "CHECK: Saldo Final - DISPONIBILIDADES (tolerância R$ 5,00)",
        "CHECK",
        "_SaldoFinal - _DispBalanco",
    )

    partes.append("RETURN UNION(\n" + ",\n".join(linhas) + "\n)")
    return "\n".join(partes)


# --------------------------------------------------------------------------- #
# Utilitários de apoio
# --------------------------------------------------------------------------- #
def periodos_disponiveis() -> str:
    """Monta a consulta que lista os períodos existentes na base, em ordem.

    Returns:
        A consulta DAX com ``Periodo`` e a chave ``AAAAMM`` correspondente.
    """
    return (
        "EVALUATE\n"
        f'VAR _P = ADDCOLUMNS(VALUES({_col(COL_PERIODO)}), "Chave", {_expr_chave()})\n'
        'RETURN SELECTCOLUMNS(_P, "Periodo", ' + _col(COL_PERIODO) + ', "Chave", [Chave])\n'
        "ORDER BY [Chave] ASC"
    )
