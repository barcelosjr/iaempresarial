"""Indicadores (KPIs) de análise financeira — DAX padronizado.

Monta **uma única** consulta DAX que devolve todos os KPIs de análise, agrupados
em Rentabilidade, Liquidez, Endividamento/Alavancagem e Eficiência Operacional.

Reaproveita integralmente os componentes já calculados pela DRE e pelo Balanço
(:mod:`powerbi.dax_financeiro`) — nada é recalculado do zero. Os KPIs misturam:

* **fluxos da DRE** somados no período (Receita, Lucro Bruto, EBITDA, EBIT,
  custos, folha…), respeitando o modo (mensal/trimestral/anual); e
* **posições do Balanço** acumuladas até o fim do período (Ativo/Passivo
  Circulante, Estoques, Disponibilidades, dívida…).

Convenções (decididas com o gestor — mudam o número, não são "padrão universal"):

1. **Dívida Líquida / EBITDA**: o EBITDA do período é **anualizado**
   (``× 12/nº de meses``) antes de dividir a dívida. Assim o múltiplo fica em
   base anual comparável, independentemente do recorte.
2. **Indicadores em dias** (giro de estoque, PMR, PMP, ciclo): usam o **saldo
   final** do Balanço e **30 dias por mês** do período (mês=30, tri=90, ano=360).
3. **Margem EBIT**: duas linhas distintas — ``EBIT / Receita Líquida`` (margem
   operacional) e ``EBIT / Lucro Bruto``.
4. **Custo de Pessoal**: ``Folha de Pagamento + Gastos Diversos com Funcionários``.

Cada KPI carrega uma explicação curta e um "melhor se…" (direção/benchmark), que
o servidor MCP anexa na formatação (:func:`metadados`).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import dax_financeiro as fin

# --------------------------------------------------------------------------- #
# Grupos de contas específicos dos KPIs (além dos que já existem em dax_financeiro)
# --------------------------------------------------------------------------- #
#: Floor plan (financiamento de estoque) — tratado como dívida nos KPIs.
FLOOR_PLAN = [
    "Floor Plan Veículos Novos",
    "Floor Plan Veículos Usados",
    "Floor Plan Peças e Acessórios",
]
#: Dívida financeira "estrutural" (empréstimos e financiamentos, curto + longo prazo).
DIVIDA_FINANCEIRA = [
    "Empréstimos Bancários",
    "Empréstimos de Terceiros",
    "Conta Garantida",
    "Financiamentos",
    "Notas Comerciais",
    "Empréstimos e Financiamentos LP",
]

ATIVO_CIRCULANTE = (
    fin.BAL_DISPONIBILIDADES + fin.BAL_VALORES_RECEBER + fin.BAL_ESTOQUES
)
ATIVO_NAO_CIRCULANTE = (
    fin.BAL_REALIZAVEL_LP + fin.BAL_INVESTIMENTOS + fin.BAL_IMOBILIZADO
    + fin.BAL_INTANGIVEL
)
PASSIVO_CIRCULANTE = (
    fin.BAL_FORNECEDORES + fin.BAL_EMPRESTIMOS + fin.BAL_OUTRAS_OBRIGACOES
)

#: Meses cobertos por cada modo (base para anualizar e para os dias).
MESES_POR_MODO = {"mensal": 1, "trimestral": 3, "anual": 12}


@dataclass(frozen=True)
class KPI:
    """Definição de um indicador: como calcular, exibir e interpretar."""

    grupo: str
    nome: str
    unidade: str  # "%", "x", "dias" ou "num"
    expr: str  # expressão DAX referenciando os VARs da consulta
    explicacao: str  # o que o número significa, em uma frase
    melhor_se: str  # direção/benchmark ideal


# --------------------------------------------------------------------------- #
# Registro dos KPIs — a ordem é a de exibição
# --------------------------------------------------------------------------- #
def _kpis() -> list[KPI]:
    """Lista de KPIs. As expressões usam os VARs montados em :func:`indicadores`."""
    return [
        # ---- Rentabilidade -------------------------------------------------- #
        KPI("Rentabilidade", "Margem Bruta Total", "%", "DIVIDE(_LucroBruto, _RL)",
            "Quanto sobra da receita depois do custo direto (CMV).",
            "melhor quanto maior"),
        KPI("Rentabilidade", "Margem EBITDA", "%", "DIVIDE(_Ebitda, _RL)",
            "Geração de caixa operacional antes de juros, impostos e depreciação.",
            "melhor quanto maior"),
        KPI("Rentabilidade", "Margem EBIT", "%", "DIVIDE(_Ebit, _RL)",
            "Resultado operacional (já com depreciação) sobre a receita.",
            "melhor quanto maior"),
        KPI("Rentabilidade", "EBIT / Lucro Bruto", "%", "DIVIDE(_Ebit, _LucroBruto)",
            "Quanto do lucro bruto sobrevive às despesas e vira resultado operacional.",
            "melhor quanto maior (menos consumido por despesas)"),
        KPI("Rentabilidade", "Margem Líquida", "%", "DIVIDE(_LucroLiquido, _RL)",
            "Lucro final sobre a receita, depois de tudo.",
            "melhor quanto maior"),
        # ---- Liquidez ------------------------------------------------------- #
        KPI("Liquidez", "Liquidez Corrente", "num", "DIVIDE(_AC, _PC)",
            "Ativo circulante dividido pelo passivo circulante.",
            "melhor se > 1 (cobre as obrigações de curto prazo)"),
        KPI("Liquidez", "Liquidez Seca", "num", "DIVIDE(_AC - _Estoques, _PC)",
            "Idem, tirando os estoques (o ativo menos líquido).",
            "melhor se ≥ 1 (visão conservadora)"),
        KPI("Liquidez", "Liquidez Imediata", "num", "DIVIDE(_Disp, _PC)",
            "Só caixa e aplicações cobrindo o passivo circulante.",
            "melhor moderado — muito alto indica caixa ocioso"),
        # ---- Endividamento e alavancagem ----------------------------------- #
        KPI("Endividamento", "Dívida Líquida c/ Floor Plan / EBITDA", "x",
            "DIVIDE(_DivLiqCom, _EbitdaAnual)",
            "Anos de EBITDA para quitar a dívida líquida, incluindo o floor plan.",
            "melhor quanto menor (o floor plan naturalmente infla)"),
        KPI("Endividamento", "Dívida Líquida s/ Floor Plan / EBITDA", "x",
            "DIVIDE(_DivLiqSem, _EbitdaAnual)",
            "Idem, sem o floor plan — a dívida estrutural da empresa.",
            "melhor quanto menor (< 3 costuma ser confortável)"),
        KPI("Endividamento", "Endividamento Geral (PT/AT)", "%",
            "DIVIDE(_PassivoTotal, _AtivoTotal)",
            "Quanto do ativo é financiado por capital de terceiros.",
            "melhor quanto menor (menos alavancado)"),
        KPI("Endividamento", "Cobertura de Juros (EBIT/Desp. Fin.)", "x",
            "DIVIDE(_Ebit, _DespFin)",
            "Quantas vezes o resultado operacional cobre as despesas financeiras.",
            "melhor quanto maior (> 1 já paga os juros)"),
        # ---- Eficiência operacional ---------------------------------------- #
        KPI("Eficiência", "Giro de Estoque VN", "dias",
            "DIVIDE(_EstVN, _CustoVN) * _Dias",
            "Dias que o estoque de veículos novos leva para girar.",
            "melhor quanto menor (gira mais rápido)"),
        KPI("Eficiência", "Giro de Estoque VU", "dias",
            "DIVIDE(_EstVU, _CustoVU) * _Dias",
            "Dias que o estoque de veículos usados leva para girar.",
            "melhor quanto menor"),
        KPI("Eficiência", "Giro de Estoque de Peças", "dias",
            "DIVIDE(_EstPecas, _CustoPecas) * _Dias",
            "Dias que o estoque de peças leva para girar.",
            "melhor quanto menor"),
        KPI("Eficiência", "PMR — Prazo Médio de Recebimento", "dias",
            "DIVIDE(_ContasReceber, _RL) * _Dias",
            "Dias médios para receber dos clientes.",
            "melhor quanto menor"),
        KPI("Eficiência", "PMP — Prazo Médio de Pagamento", "dias",
            "DIVIDE(_FornecDiversos, _CustoTotal) * _Dias",
            "Dias médios para pagar fornecedores.",
            "melhor um pouco maior — financia o giro, mas sem esticar demais"),
        KPI("Eficiência", "Ciclo Financeiro", "dias",
            "(DIVIDE(_ContasReceber, _RL) + DIVIDE(_Estoques, _CustoTotal)"
            " - DIVIDE(_FornecDiversos, _CustoTotal)) * _Dias",
            "PMR + giro de estoque − PMP: dias de capital de giro presos.",
            "melhor quanto menor (idealmente negativo)"),
        KPI("Eficiência", "Custo de Pessoal / Receita Líquida", "%",
            "DIVIDE(_CustoPessoal, _RL)",
            "Peso da folha + gastos com funcionários sobre a receita.",
            "melhor quanto menor"),
        KPI("Eficiência", "Total Despesas Operac. / Receita Líquida", "%",
            "DIVIDE(_DespOper, _RL)",
            "Peso das despesas operacionais sobre a receita.",
            "melhor quanto menor"),
    ]


def metadados() -> dict[str, dict[str, str]]:
    """Mapa ``nome -> {unidade, explicacao, melhor_se, grupo}`` para a formatação."""
    return {
        k.nome: {
            "unidade": k.unidade,
            "explicacao": k.explicacao,
            "melhor_se": k.melhor_se,
            "grupo": k.grupo,
        }
        for k in _kpis()
    }


# --------------------------------------------------------------------------- #
# Consulta DAX
# --------------------------------------------------------------------------- #
def _mag(agg: str, contas: list[str]) -> str:
    """Magnitude positiva de contas subtrativas (custos/despesas negativos)."""
    return f"-({fin._soma_lookup(agg, contas)})"


def indicadores(
    periodo: str, empresa: str | None = None, modo: str = "mensal"
) -> str:
    """Monta a consulta DAX com todos os KPIs de análise.

    Args:
        periodo: Período de referência ``"MM/AAAA"`` (ex.: ``"03/2026"``).
        empresa: Filtro opcional por ``EMPRESA``. ``None`` = consolidado.
        modo: ``"mensal"`` (padrão), ``"trimestral"`` ou ``"anual"`` — define o
            intervalo dos fluxos da DRE e a base de dias/anualização.

    Returns:
        A consulta DAX que devolve as linhas ``Ordem``, ``Grupo``, ``Indicador``,
        ``Valor`` e ``Unidade``.

    Raises:
        ValueError: Se ``modo`` for inválido ou incompatível com o período.
    """
    chave_de, chave_ate = fin.intervalo_do_modo(periodo, modo)
    n_meses = MESES_POR_MODO[str(modo).strip().lower()]
    ent = fin._filtro_entidade(empresa)

    dre = "_AggDre"
    bal = "_AggBal"

    partes: list[str] = [
        "EVALUATE",
        # Fluxos da DRE somados no intervalo do modo.
        fin._var_base_intervalo("_Per", chave_de, chave_ate, ent),
        fin._var_agregado(dre, "_Per", fin.COL_DRE),
        # Posições do Balanço acumuladas até o fim do período.
        fin._var_base("_Ate", "<=", chave_ate, ent),
        fin._var_agregado(bal, "_Ate", fin.COL_BALANCO),
        # Constantes do modo.
        f"VAR _Dias = {n_meses * 30}",
        f"VAR _FatorAnual = DIVIDE(12, {n_meses})",
        # --- Base: DRE (fluxos do período) ---------------------------------- #
        f"VAR _RL = {fin._soma_lookup(dre, fin.DRE_G1_RECEITA)}",
        f"VAR _Custos = {fin._soma_lookup(dre, fin.DRE_G2_CUSTOS)}",
        "VAR _LucroBruto = _RL + _Custos",
        f"VAR _Desp = {fin._soma_lookup(dre, fin.DRE_G3_DESPESAS)}",
        f"VAR _Outras = {fin._soma_lookup(dre, fin.DRE_G4_OUTRAS)}",
        "VAR _Ebitda = _LucroBruto + _Desp + _Outras",
        f"VAR _Deprec = {fin._soma_lookup(dre, fin.DRE_G5_DEPRECIACAO)}",
        "VAR _Ebit = _Ebitda + _Deprec",
        f"VAR _ResFin = {fin._soma_lookup(dre, fin.DRE_G6_FINANCEIRO)}",
        "VAR _Lair = _Ebit + _ResFin",
        f"VAR _Impostos = {fin._soma_lookup(dre, fin.DRE_G7_IMPOSTOS)}",
        "VAR _LucroLiquido = _Lair + _Impostos",
        "VAR _EbitdaAnual = _Ebitda * _FatorAnual",
        # magnitudes positivas
        f'VAR _DespFin = -({fin._lookup(dre, "(-) Despesas Financeiras")})',
        "VAR _CustoTotal = -_Custos",
        f'VAR _CustoVN = -({fin._lookup(dre, "Custo de Veículos Novos")})',
        f'VAR _CustoVU = -({fin._lookup(dre, "Custo de Veículos Usados")})',
        f'VAR _CustoPecas = -({fin._lookup(dre, "Custo de Peças e Acessórios")})',
        f'VAR _CustoPessoal = {_mag(dre, ["Folha de Pagamento", "Gastos Diversos com Funcionários"])}',
        "VAR _DespOper = -_Desp",
        # --- Base: Balanço (posições acumuladas) ---------------------------- #
        f"VAR _AC = {fin._soma_lookup(bal, ATIVO_CIRCULANTE)}",
        f"VAR _ANC = {fin._soma_lookup(bal, ATIVO_NAO_CIRCULANTE)}",
        "VAR _AtivoTotal = _AC + _ANC",
        f"VAR _PC = {fin._soma_lookup(bal, PASSIVO_CIRCULANTE)}",
        f"VAR _PNC = {fin._soma_lookup(bal, fin.BAL_PASSIVO_NAO_CIRC)}",
        "VAR _PassivoTotal = _PC + _PNC",
        f"VAR _Disp = {fin._soma_lookup(bal, fin.BAL_DISPONIBILIDADES)}",
        f"VAR _Estoques = {fin._soma_lookup(bal, fin.BAL_ESTOQUES)}",
        f'VAR _EstVN = {fin._lookup(bal, "Estoque de Veículos Novos")}',
        f'VAR _EstVU = {fin._lookup(bal, "Estoque de Veículos Usados")}',
        f'VAR _EstPecas = {fin._lookup(bal, "Estoque de Peças")}',
        f'VAR _ContasReceber = {fin._lookup(bal, "Contas a Receber")}',
        f'VAR _FornecDiversos = {fin._lookup(bal, "Fornecedores Diversos")}',
        f"VAR _FloorPlan = {fin._soma_lookup(bal, FLOOR_PLAN)}",
        f"VAR _DivFin = {fin._soma_lookup(bal, DIVIDA_FINANCEIRA)}",
        "VAR _DivLiqCom = _DivFin + _FloorPlan - _Disp",
        "VAR _DivLiqSem = _DivFin - _Disp",
    ]

    linhas: list[str] = []
    for ordem, k in enumerate(_kpis(), start=1):
        linhas.append(
            f'    ROW("Ordem", {ordem}, "Grupo", "{fin.escapar_texto(k.grupo)}", '
            f'"Indicador", "{fin.escapar_texto(k.nome)}", '
            f'"Valor", {k.expr}, "Unidade", "{k.unidade}")'
        )

    partes.append("RETURN UNION(\n" + ",\n".join(linhas) + "\n)")
    return "\n".join(partes)
