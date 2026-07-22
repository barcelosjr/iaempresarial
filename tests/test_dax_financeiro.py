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
    assert len(contas) == 31, "a DRE do documento tem 31 linhas de detalhe"
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
def test_fluxo_tem_linha_de_ajuste_explicita():
    """O resíduo aparece nomeado, nunca embutido em outra linha."""
    assert "AJUSTE DE CONCILIAÇÃO" in fin.fluxo_caixa("12/2024")


def test_fluxo_fecha_por_construcao():
    """Variação líquida = seções + ajuste ⇒ CHECK zero em qualquer mês."""
    query = fin.fluxo_caixa("02/2025")
    assert "VAR _Ajuste = _DeltaCaixa - _SomaSecoes" in query
    assert "VAR _VariacaoLiquida = _SomaSecoes + _Ajuste" in query


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
        "(+) Receitas Diversas",
        "(+) Receitas Financeiras",
    ],
)
def test_operacao_dre_aditiva(conta):
    assert fin.operacao_dre(conta) == 1


def test_todas_as_31_linhas_tem_operacao_definida():
    contas = (
        fin.DRE_G1_RECEITA
        + fin.DRE_G2_CUSTOS
        + fin.DRE_G3_DESPESAS
        + fin.DRE_G4_OUTRAS
        + fin.DRE_G5_DEPRECIACAO
        + fin.DRE_G6_FINANCEIRO
        + fin.DRE_G7_IMPOSTOS
    )
    assert len(contas) == 31
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
