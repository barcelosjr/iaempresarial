"""Testes da biblioteca de relatórios financeiros (DRE, Balanço, Fluxo de Caixa).

Validam a montagem das strings DAX e as regras de período — sem chamar a API.
"""

from __future__ import annotations

import pytest

from powerbi import dax_financeiro as fin


# --------------------------------------------------------------------------- #
# Helpers de período
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("periodo", "esperado"),
    [
        ("12/2024", 202412),
        ("01/2024", 202401),
        ("1/2024", 202401),
        (" 07/2026 ", 202607),
    ],
)
def test_chave_periodo_converte_para_aaaamm(periodo, esperado):
    assert fin.chave_periodo(periodo) == esperado


@pytest.mark.parametrize("invalido", ["2024-12", "13/2024", "abc", "12", "00/2024"])
def test_chave_periodo_rejeita_formato_invalido(invalido):
    with pytest.raises(ValueError):
        fin.chave_periodo(invalido)


@pytest.mark.parametrize(
    ("periodo", "esperado"),
    [
        ("12/2024", "11/2024"),
        ("01/2025", "12/2024"),
        ("10/2025", "09/2025"),
    ],
)
def test_periodo_anterior(periodo, esperado):
    assert fin.periodo_anterior(periodo) == esperado


# --------------------------------------------------------------------------- #
# Regras estruturais comuns às três consultas
# --------------------------------------------------------------------------- #
@pytest.fixture(params=["dre", "balanco", "fluxo_caixa"])
def consulta(request):
    """Devolve a consulta DAX de cada relatório para o mesmo período."""
    return getattr(fin, request.param)("12/2024")


def test_consulta_e_somente_leitura(consulta):
    assert consulta.lstrip().startswith("EVALUATE")


def test_usa_trim_nas_colunas_de_classificacao(consulta):
    """Sem TRIM os filtros retornam vazio — a base tem espaços extras."""
    assert "TRIM(" in consulta


def test_usa_valor_ajustado_e_nunca_valor_cru(consulta):
    """VALOR_AJUSTADO já traz o sinal; VALOR cru é sempre positivo e enganaria."""
    assert "'lancamentos'[VALOR_AJUSTADO]" in consulta
    assert "'lancamentos'[VALOR]" not in consulta


def test_nao_deriva_sinal_da_natureza(consulta):
    """O sinal não acompanha NATUREZA (há crédito positivo e negativo)."""
    assert "IF('lancamentos'[NATUREZA]" not in consulta


def test_nao_usa_tabela_saldo_inicial(consulta):
    """saldo_inicial_2024 duplica as linhas 01/01/2024 — não pode ser somada."""
    assert "saldo_inicial_2024" not in consulta


def test_periodo_invalido_propaga_erro():
    for func in (fin.dre, fin.balanco, fin.fluxo_caixa):
        with pytest.raises(ValueError):
            func("2024/12")


# --------------------------------------------------------------------------- #
# DRE
# --------------------------------------------------------------------------- #
def test_dre_filtra_apenas_o_periodo():
    """A DRE não é cumulativa: compara a chave com '=', nunca '<='."""
    assert "= 202412" in fin.dre("12/2024")
    assert "<= 202412" not in fin.dre("12/2024")


def test_dre_inclui_todas_as_contas_da_estrutura():
    query = fin.dre("12/2024")
    contas = (
        fin.DRE_G1_RECEITA
        + fin.DRE_G2_CUSTOS
        + fin.DRE_G3_DESPESAS
        + fin.DRE_G4_OUTRAS
        + fin.DRE_G5_DEPRECIACAO
        + fin.DRE_G6_FINANCEIRO
        + fin.DRE_G7_IMPOSTOS
    )
    assert len(contas) == 34, (
        "31 linhas do documento original + 3 de receita da CORRETORA "
        "(Comissão sobre Seguros/Consórcios/Intermediação)"
    )
    for conta in contas:
        assert conta in query


def test_dre_traz_os_subtotais_e_indicadores():
    query = fin.dre("12/2024")
    for rotulo in (
        "= RECEITA LÍQUIDA",
        "= LUCRO BRUTO",
        "= EBITDA",
        "= EBIT (Resultado Operacional)",
        "= LAIR (Resultado antes do IR)",
        "= LUCRO LÍQUIDO DO EXERCÍCIO",
        "% Margem Bruta",
        "% EBITDA/RL",
        "% Margem Líquida",
    ):
        assert rotulo in query


# --------------------------------------------------------------------------- #
# Balanço
# --------------------------------------------------------------------------- #
def test_balanco_e_cumulativo():
    """O saldo acumula desde o início do modelo até o período."""
    assert "<= 202412" in fin.balanco("12/2024")


def test_balanco_inclui_check():
    assert "CHECK: Ativo - (Passivo + PL)" in fin.balanco("12/2024")


def test_balanco_mantem_conta_sem_lancamento():
    """'Reservas de Capital' não tem lançamento, mas segue na estrutura."""
    assert "Reservas de Capital" in fin.balanco("12/2024")


def test_balanco_soma_direta_sem_inverter_passivo():
    """Com VALOR_AJUSTADO, Ativo e Passivo/PL já saem positivos."""
    query = fin.balanco("12/2024")
    assert "_TotalAtivo - _TotalPassivoPL" in query


# --------------------------------------------------------------------------- #
# Fluxo de Caixa
# --------------------------------------------------------------------------- #
def test_fluxo_compara_com_o_periodo_anterior():
    """Movimento do mês + acumulado anterior (para o saldo inicial de caixa)."""
    query = fin.fluxo_caixa("12/2024")
    assert "= 202412" in query
    assert "<= 202411" in query


def test_fluxo_tem_as_tres_secoes_e_o_check():
    query = fin.fluxo_caixa("12/2024")
    for secao in (
        "I. ATIVIDADES OPERACIONAIS",
        "II. ATIVIDADES DE INVESTIMENTO",
        "III. ATIVIDADES DE FINANCIAMENTO",
        "VARIAÇÃO LÍQUIDA DE CAIXA DO PERÍODO",
    ):
        assert secao in query
    assert "CHECK: Saldo Final - DISPONIBILIDADES" in query


def test_fluxo_vira_o_ano_no_periodo_anterior():
    """Janeiro deve comparar com dezembro do ano anterior."""
    assert "<= 202412" in fin.fluxo_caixa("01/2025")


def test_fluxo_usa_natureza_bruta_nas_linhas_de_imobilizado():
    """Linhas tipo NATUREZA somam lançamentos brutos por C/D no período."""
    query = fin.fluxo_caixa("12/2024")
    assert "[@Nat]" in query


# --------------------------------------------------------------------------- #
# Filtros de entidade
# --------------------------------------------------------------------------- #
def test_filtro_por_empresa():
    query = fin.dre("12/2024", empresa="KOBE")
    assert 'TRIM(\'lancamentos\'[EMPRESA]) = "KOBE"' in query


def test_sem_filtro_nao_adiciona_condicao_de_entidade():
    assert "[EMPRESA]" not in fin.dre("12/2024")


def test_relatorios_nao_usam_revenda():
    """O recorte é por EMPRESA; REVENDA não entra nos relatórios."""
    for func in (fin.dre, fin.balanco, fin.fluxo_caixa):
        assert "[REVENDA]" not in func("12/2024")


def test_escapa_aspas_no_filtro():
    """Aspas no valor não podem quebrar/injetar na string DAX."""
    query = fin.dre("12/2024", empresa='ACME "X"')
    assert 'ACME ""X""' in query


# --------------------------------------------------------------------------- #
# Modos do Fluxo de Caixa
# --------------------------------------------------------------------------- #
def test_fluxo_modo_invalido():
    with pytest.raises(ValueError):
        fin.fluxo_caixa("12/2024", modo="anual")


def test_fluxo_trimestral_exige_fim_de_trimestre():
    for mes in ("01", "02", "04", "11"):
        with pytest.raises(ValueError, match="fim de trimestre"):
            fin.fluxo_caixa(f"{mes}/2025", modo="trimestral")
    for mes in ("03", "06", "09", "12"):
        assert fin.fluxo_caixa(f"{mes}/2025", modo="trimestral")


def test_fluxo_trimestral_soma_os_tres_meses_e_compara_com_trimestre_anterior():
    query = fin.fluxo_caixa("12/2024", modo="trimestral")
    assert ">= 202410" in query and "<= 202412" in query  # intervalo do trimestre
    assert "<= 202409" in query  # ponta de comparação


def test_fluxo_trimestral_vira_o_ano():
    """Q1 compara com o fechamento de dezembro do ano anterior."""
    query = fin.fluxo_caixa("03/2025", modo="trimestral")
    assert ">= 202501" in query
    assert "<= 202412" in query


@pytest.mark.parametrize(
    ("chave", "delta", "esperado"),
    [
        (202501, -1, 202412),
        (202412, -3, 202409),
        (202501, -3, 202410),
        (202403, -2, 202401),
        (202412, 1, 202501),
    ],
)
def test_somar_meses(chave, delta, esperado):
    assert fin.somar_meses(chave, delta) == esperado


# --------------------------------------------------------------------------- #
# Conciliação do Fluxo de Caixa
# --------------------------------------------------------------------------- #
def test_fluxo_nunca_tem_ajuste_de_conciliacao():
    """Proibido tampão: nenhuma linha ou variável de ajuste de conciliação."""
    query = fin.fluxo_caixa("02/2025")
    assert "AJUSTE DE CONCILIAÇÃO" not in query
    assert "_Ajuste" not in query


def test_fluxo_variacao_liquida_e_soma_honesta_das_secoes():
    """Variação líquida = soma das 3 seções, sem forçar o CHECK a zero."""
    query = fin.fluxo_caixa("02/2025")
    assert (
        "VAR _VariacaoLiquida = _CaixaOperacional + _CaixaInvestimento"
        " + _CaixaFinanciamento" in query
    )
    assert "_SaldoFinal - _DispBalanco" in query


def test_depreciacao_add_back_so_natureza_d():
    """O add-back de depreciação usa só lançamentos com NATUREZA = D."""
    query = fin.fluxo_caixa("12/2024")
    assert "_AggDreNat" in query
    assert "VAR _DeprecAdd = -(" in query


def test_dividendos_ficam_fora_do_subtotal():
    """Já contidos na variação de Lucros a Pagar — somar duplicaria."""
    query = fin.fluxo_caixa("12/2024")
    assert "_Dividendos" in query
    assert "_VarAFAC + _Dividendos" not in query


def test_fluxo_dispensa_acumulado_para_variacoes():
    """Variação = soma do próprio período (o saldo é acumulado)."""
    query = fin.fluxo_caixa("12/2024")
    assert query.count("<=") == 1  # só o acumulado do saldo inicial


# --------------------------------------------------------------------------- #
# Regra de sinal da DRE (exibe positivo, subtrai no subtotal)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "conta",
    [
        "(-) Devoluções",
        "(-) Impostos sobre a Venda",
        "Custo de Veículos Novos",
        "Folha de Pagamento",
        "(-) Despesas Não Dedutíveis",
        "Depreciação e Amortização de Ativos",
        "(-) Despesas Financeiras",
        "(-) IR e CSLL",
    ],
)
def test_operacao_dre_subtrativa(conta):
    assert fin.operacao_dre(conta) == -1


@pytest.mark.parametrize(
    "conta",
    [
        "Venda de Veículos Novos",
        "Peças e Acessórios",
        "Serviços Oficina",
        "Comissões Diversas",
        "Comissão sobre Seguros",
        "Comissão sobre Consórcios",
        "Comissão sobre Intermediação",
        "(+) Receitas Diversas",
        "(+) Receitas Financeiras",
    ],
)
def test_operacao_dre_aditiva(conta):
    assert fin.operacao_dre(conta) == 1


def test_todas_as_linhas_tem_operacao_definida():
    contas = (
        fin.DRE_G1_RECEITA
        + fin.DRE_G2_CUSTOS
        + fin.DRE_G3_DESPESAS
        + fin.DRE_G4_OUTRAS
        + fin.DRE_G5_DEPRECIACAO
        + fin.DRE_G6_FINANCEIRO
        + fin.DRE_G7_IMPOSTOS
    )
    assert len(contas) == 34
    assert {fin.operacao_dre(c) for c in contas} == {1, -1}
    # 20 linhas subtrativas (5 custos + 11 despesas + 4 deduções/outras) + demais
    assert sum(1 for c in contas if fin.operacao_dre(c) == -1) == len(
        fin.DRE_LINHAS_SUBTRATIVAS
    )


def test_dre_exibe_linha_subtrativa_positiva():
    """Custo aparece positivo: a expressão de exibição inverte o sinal."""
    query = fin.dre("12/2024")
    alvo = fin._lookup("_Agg", "Custo de Veículos Novos")
    assert f"-({alvo})" in query


def test_dre_nao_inverte_linha_aditiva():
    """Receita já vem positiva — não pode ser negada."""
    query = fin.dre("12/2024")
    alvo = fin._lookup("_Agg", "Venda de Veículos Novos")
    assert f"-({alvo})" not in query
    assert alvo in query


def test_dre_subtotais_usam_o_valor_original():
    """Subtotais somam o valor bruto (negativo), não o exibido."""
    query = fin.dre("12/2024")
    assert "VAR _LucroBruto = _RL + _Custos" in query
    assert "VAR _Ebitda = _LucroBruto + _Desp + _Outras" in query
    assert "VAR _LucroLiquido = _Lair + _Impostos" in query


def test_balanco_e_fluxo_nao_aplicam_inversao_da_dre():
    """A inversão é exclusiva da exibição da DRE."""
    for query in (fin.balanco("12/2024"), fin.fluxo_caixa("12/2024")):
        alvo = fin._lookup("_Agg", "Custo de Veículos Novos")
        assert f"-({alvo})" not in query


# --------------------------------------------------------------------------- #
# Modos de período da DRE (mensal / trimestral / anual)
# --------------------------------------------------------------------------- #
def test_intervalo_do_modo_mensal():
    assert fin.intervalo_do_modo("03/2026", "mensal") == (202603, 202603)


def test_intervalo_do_modo_trimestral():
    assert fin.intervalo_do_modo("03/2026", "trimestral") == (202601, 202603)
    assert fin.intervalo_do_modo("12/2024", "trimestral") == (202410, 202412)


def test_intervalo_do_modo_anual():
    assert fin.intervalo_do_modo("12/2025", "anual") == (202501, 202512)


def test_intervalo_do_modo_invalido():
    with pytest.raises(ValueError):
        fin.intervalo_do_modo("12/2024", "semestral")


def test_intervalo_do_modo_trimestral_exige_fim_de_trimestre():
    with pytest.raises(ValueError, match="fim de trimestre"):
        fin.intervalo_do_modo("02/2026", "trimestral")


def test_intervalo_do_modo_anual_exige_dezembro():
    with pytest.raises(ValueError, match="fim de ano"):
        fin.intervalo_do_modo("06/2025", "anual")


def test_dre_modo_mensal_e_igual_ao_padrao_anterior():
    assert fin.dre("12/2024") == fin.dre("12/2024", modo="mensal")


def test_dre_trimestral_soma_os_tres_meses():
    query = fin.dre("03/2026", modo="trimestral")
    assert ">= 202601" in query and "<= 202603" in query


def test_dre_anual_soma_o_ano_inteiro():
    query = fin.dre("12/2025", modo="anual")
    assert ">= 202501" in query and "<= 202512" in query


def test_dre_modo_invalido_propaga_erro():
    with pytest.raises(ValueError):
        fin.dre("12/2024", modo="semestral")


def test_dre_trimestral_periodo_invalido_propaga_erro():
    with pytest.raises(ValueError):
        fin.dre("02/2026", modo="trimestral")


# --------------------------------------------------------------------------- #
# Linhas inaplicáveis por ramo de atividade (ex.: CORRETORA)
# --------------------------------------------------------------------------- #
def test_corretora_omite_linhas_de_concessionaria():
    """A conta some da EXIBIÇÃO (ROW), mas segue existindo no cálculo da VAR."""
    query = fin.dre("01/2026", empresa="CORRETORA")
    secao_exibicao = query.split("RETURN UNION")[1]
    for conta in fin.LINHAS_INAPLICAVEIS_POR_EMPRESA["CORRETORA"]:
        assert f'"Linha", "{conta}"' not in secao_exibicao


def _linhas_exibidas(query):
    """Rótulos que a consulta realmente imprime (seção RETURN UNION)."""
    import re as _re
    return _re.findall(r'"Linha", "([^"]+)"', query.split("RETURN UNION")[1])


def test_outras_empresas_mantem_linhas_de_concessionaria():
    exibidas = _linhas_exibidas(fin.dre("01/2026", empresa="KOBE"))
    for conta in fin.LINHAS_INAPLICAVEIS_POR_EMPRESA["CORRETORA"]:
        assert conta in exibidas


def test_outras_empresas_nao_mostram_comissoes_de_corretora():
    """Comissões de Seguros/Consórcios/Intermediação são exclusivas da CORRETORA."""
    exibidas = _linhas_exibidas(fin.dre("01/2026", empresa="KOBE"))
    for conta in fin.LINHAS_EXCLUSIVAS_DE_EMPRESA:
        assert conta not in exibidas


def test_corretora_agrega_custos_em_linha_unica():
    exibidas = _linhas_exibidas(fin.dre("01/2026", empresa="CORRETORA"))
    assert "Custo de Mercado e Serviço" in exibidas
    for conta in fin.DRE_G2_CUSTOS:
        assert conta not in exibidas


def test_consolidado_mantem_todas_as_linhas():
    """Sem filtro de empresa (visão consolidada), nada é omitido."""
    exibidas = _linhas_exibidas(fin.dre("01/2026"))
    for conta in fin.LINHAS_INAPLICAVEIS_POR_EMPRESA["CORRETORA"]:
        assert conta in exibidas
    for conta in fin.LINHAS_EXCLUSIVAS_DE_EMPRESA:
        assert conta in exibidas
    assert "Custo de Mercado e Serviço" not in exibidas


@pytest.mark.parametrize(
    ("conta", "empresa", "esperado"),
    [
        ("Comissão sobre Seguros", "CORRETORA", True),
        ("Comissão sobre Seguros", "KOBE", False),
        ("Comissão sobre Seguros", None, True),
        ("Venda de Veículos Novos", "CORRETORA", False),
        ("Venda de Veículos Novos", "KOBE", True),
        ("Custo de Veículos Novos", "CORRETORA", False),
        ("Folha de Pagamento", "CORRETORA", True),
    ],
)
def test_linha_visivel(conta, empresa, esperado):
    assert fin.linha_visivel(conta, empresa) is esperado


def test_corretora_mantem_linhas_proprias_de_comissao():
    """As linhas de comissão da corretora continuam aparecendo normalmente."""
    query = fin.dre("01/2026", empresa="CORRETORA")
    for conta in ("Comissão sobre Seguros", "Comissão sobre Consórcios", "Comissão sobre Intermediação"):
        assert conta in query


def test_omissao_nao_afeta_calculo_da_receita_liquida():
    """RECEITA LÍQUIDA soma DRE_G1_RECEITA inteiro, independente da omissão de exibição."""
    query = fin.dre("01/2026", empresa="CORRETORA")
    assert "VAR _RL = " in query
    for conta in fin.DRE_G1_RECEITA:
        assert conta in query.split("RETURN UNION")[0]  # aparece no calculo (VARs), so nao na exibicao


# --------------------------------------------------------------------------- #
# KPIs de análise (dax_kpis)
# --------------------------------------------------------------------------- #
from powerbi import dax_kpis as kpi  # noqa: E402


def test_kpis_consulta_e_somente_leitura():
    assert kpi.indicadores("03/2026", modo="trimestral").lstrip().startswith("EVALUATE")


def test_kpis_usa_valor_ajustado():
    q = kpi.indicadores("03/2026", empresa="KOBE", modo="trimestral")
    assert "'lancamentos'[VALOR_AJUSTADO]" in q
    assert "'lancamentos'[VALOR]" not in q


def test_kpis_todos_os_grupos_presentes():
    q = kpi.indicadores("03/2026", modo="trimestral")
    for grupo in ("Rentabilidade", "Liquidez", "Endividamento", "Eficiência"):
        assert grupo in q


def test_kpis_ebitda_anualizado_por_modo():
    """O fator de anualização vem do nº de meses do modo."""
    assert "DIVIDE(12, 1)" in kpi.indicadores("02/2026", modo="mensal")
    assert "DIVIDE(12, 3)" in kpi.indicadores("03/2026", modo="trimestral")
    assert "DIVIDE(12, 12)" in kpi.indicadores("12/2026", modo="anual")


def test_kpis_dias_base_por_modo():
    assert "VAR _Dias = 30" in kpi.indicadores("02/2026", modo="mensal")
    assert "VAR _Dias = 90" in kpi.indicadores("03/2026", modo="trimestral")
    assert "VAR _Dias = 360" in kpi.indicadores("12/2026", modo="anual")


def test_kpis_margem_ebit_em_duas_linhas():
    nomes = {k.nome for k in kpi._kpis()}
    assert "Margem EBIT" in nomes
    assert "EBIT / Lucro Bruto" in nomes


def test_kpis_metadados_cobre_todos():
    meta = kpi.metadados()
    for k in kpi._kpis():
        assert k.nome in meta
        assert meta[k.nome]["explicacao"]
        assert meta[k.nome]["melhor_se"]


def test_kpis_custo_pessoal_inclui_gastos_funcionarios():
    q = kpi.indicadores("03/2026", empresa="KOBE", modo="trimestral")
    assert "Folha de Pagamento" in q
    assert "Gastos Diversos com Funcionários" in q


def test_kpis_modo_invalido():
    with pytest.raises(ValueError):
        kpi.indicadores("03/2026", modo="semestral")
