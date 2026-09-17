"""Testes da conciliação de caixa (financeiro x contábil), sem chamar a API.

Cobrem as três coisas que este conciliador pode errar em silêncio:

1. **Mês sem movimento.** Uma empresa que não movimentou o caixa não tem linha
   no resultado DAX — mas tem saldo. Sem o ``ffill`` de :func:`preparar_lado`,
   o mês vira uma divergência inventada.
2. **Separar abertura de divergência.** O resíduo de saldo inicial se arrasta
   constante; ele não pode contaminar ``diferenca_do_mes``, senão todo mês
   aparece como divergente.
3. **Mapa de empresas.** ``ROYAL ENFIELD`` (financeiro) e ``ROYAL`` (contábil)
   são a mesma empresa; uma empresa fora do mapa não pode sumir calada.

Os números de referência são os medidos em 20/08/2026 contra a base real —
ver ``dictionary/regras_negocio.md``, seção "Conciliação de Caixa".
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from analysis import conciliacao_caixa as conc
from powerbi import dax_conciliacao as dxc

CONFIG = {
    "contas_caixa": ["11101010001", "11111001"],
    "empresas": {
        "ROYAL ENFIELD": "ROYAL",
        "KOBE": "KOBE",
        "MULT CORRETORA": "CORRETORA",
    },
    "primeiro_mes": 202501,
    "mes_abertura": 202412,
    "tolerancia_reais": 0.01,
}


def _lado(nome_tabela: str, linhas: list[tuple[str, int, float]]) -> pd.DataFrame:
    """Simula o retorno da API: colunas DAX qualificadas + aliases."""
    return pd.DataFrame(
        [
            {
                f"{nome_tabela}[EMPRESA]": e,
                "[CHAVE]": float(k),
                "[MOVIMENTO]": 0.0,
                "[SALDO]": s,
            }
            for e, k, s in linhas
        ]
    )


# --------------------------------------------------------------------------- #
# Helpers de período
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("periodo", "esperado"),
    [("07/2026", 202607), ("1/2025", 202501), (" 12/2024 ", 202412)],
)
def test_periodo_para_chave(periodo, esperado):
    assert conc.periodo_para_chave(periodo) == esperado


@pytest.mark.parametrize("invalido", ["2026-07", "13/2026", "abc", "07"])
def test_periodo_para_chave_rejeita_formato_invalido(invalido):
    with pytest.raises(ValueError):
        conc.periodo_para_chave(invalido)


def test_ultimo_dia_respeita_meses_de_tamanhos_diferentes():
    assert conc.ultimo_dia(202602) == date(2026, 2, 28)
    assert conc.ultimo_dia(202607) == date(2026, 7, 31)
    assert conc.ultimo_dia(202404) == date(2024, 4, 30)


def test_meses_atravessa_a_virada_do_ano():
    assert conc._meses(202511, 202602) == [202511, 202512, 202601, 202602]


# --------------------------------------------------------------------------- #
# preparar_lado
# --------------------------------------------------------------------------- #
def test_mes_sem_movimento_herda_o_saldo_do_mes_anterior():
    """Sem linha no DAX ≠ sem saldo. É o falso-positivo mais fácil de criar."""
    bruto = _lado("lancamentos", [("CORRETORA", 202501, 59133.92), ("CORRETORA", 202503, 62133.92)])
    pronto = conc.preparar_lado(bruto, [202501, 202502, 202503])
    saldos = pronto.set_index("chave")["saldo"].to_dict()
    assert saldos[202502] == pytest.approx(59133.92)
    assert saldos[202503] == pytest.approx(62133.92)


def test_mes_anterior_ao_primeiro_movimento_fica_zerado():
    bruto = _lado("CAIXAS", [("OMODA", 202606, 6130.51)])
    pronto = conc.preparar_lado(bruto, [202605, 202606])
    saldos = pronto.set_index("chave")["saldo"].to_dict()
    assert saldos[202605] == pytest.approx(0.0)
    assert saldos[202606] == pytest.approx(6130.51)


def test_preparar_lado_aceita_dataframe_vazio():
    assert conc.preparar_lado(pd.DataFrame(), [202501]).empty


# --------------------------------------------------------------------------- #
# conciliar
# --------------------------------------------------------------------------- #
def test_royal_fecha_centavo_a_centavo():
    """Números reais medidos em 20/08/2026: ROYAL bate em todos os meses."""
    meses = [202501, 202502, 202503]
    saldos = [9830.15, 20660.76, 4576.72]
    contabil = conc.preparar_lado(
        _lado("lancamentos", [("ROYAL", k, s) for k, s in zip(meses, saldos)]), meses
    )
    financeiro = conc.preparar_lado(
        _lado("CAIXAS", [("ROYAL ENFIELD", k, s) for k, s in zip(meses, saldos)]), meses
    )
    linhas, _ = conc.conciliar(contabil, financeiro, CONFIG, 202503)
    assert set(linhas["status"]) == {"OK"}
    assert linhas["diferenca"].abs().max() == pytest.approx(0.0)


def test_diferenca_de_abertura_constante_nao_marca_os_meses_como_divergentes():
    """O resíduo de saldo inicial se arrasta, mas o movimento do mês bate.

    Caso real da CORRETORA: R$ 57.633,92 de abertura nunca lançados na
    planilha. Todo mês tem diferença acumulada, e nenhum mês tem divergência
    de movimento — que é exatamente o que o controller precisa enxergar.
    """
    meses = [202501, 202502, 202503]
    contabil = conc.preparar_lado(
        _lado("lancamentos", [("CORRETORA", k, s) for k, s in zip(meses, [59133.92, 62133.92, 62133.92])]),
        meses,
    )
    financeiro = conc.preparar_lado(
        _lado("CAIXAS", [("MULT CORRETORA", k, s) for k, s in zip(meses, [1500.00, 4500.00, 4500.00])]),
        meses,
    )
    linhas, _ = conc.conciliar(
        contabil, financeiro, CONFIG, 202503, {"CORRETORA": -57633.92}
    )

    assert linhas["diferenca"].round(2).tolist() == [-57633.92] * 3
    # A abertura é descontada do primeiro mês: nenhum mês tem movimento
    # descasado, e a diferença acumulada continua visível na coluna própria.
    assert linhas["diferenca_do_mes"].round(2).tolist() == [0.0, 0.0, 0.0]
    assert linhas["status"].tolist() == ["OK", "OK", "OK"]


def test_sem_residuo_a_abertura_apareceria_como_divergencia_do_primeiro_mes():
    """Guarda o contrato do parâmetro: sem ele, o saldo inicial contamina 01/2025."""
    meses = [202501, 202502]
    contabil = conc.preparar_lado(
        _lado("lancamentos", [("CORRETORA", k, s) for k, s in zip(meses, [59133.92, 62133.92])]),
        meses,
    )
    financeiro = conc.preparar_lado(
        _lado("CAIXAS", [("MULT CORRETORA", k, s) for k, s in zip(meses, [1500.00, 4500.00])]),
        meses,
    )
    linhas, _ = conc.conciliar(contabil, financeiro, CONFIG, 202502)
    assert linhas["status"].tolist() == ["DIVERGENTE", "OK"]


def test_divergencia_de_um_mes_aparece_so_no_mes_em_que_nasce_e_no_da_reversao():
    """Caso real KOBE: R$ 1,00 de corte em 03/2026, revertido em 04/2026.

    Um recebimento de R$ 1,00 (NF 22121, KOBE NISSAN IP) entrou no livro-caixa
    em 25/03 e foi cancelado em 07/04; a contabilidade registrou os dois no
    mesmo período. A diferença acumulada aparece em março e some em abril.
    """
    meses = [202602, 202603, 202604]
    contabil = conc.preparar_lado(
        _lado("lancamentos", [("KOBE", k, s) for k, s in zip(meses, [755981.58, 313018.72, 360126.52])]),
        meses,
    )
    financeiro = conc.preparar_lado(
        _lado("CAIXAS", [("KOBE", k, s) for k, s in zip(meses, [755981.58, 313019.72, 360126.52])]),
        meses,
    )
    linhas, _ = conc.conciliar(contabil, financeiro, CONFIG, 202604)

    assert linhas["diferenca_do_mes"].round(2).tolist() == [0.0, 1.0, -1.0]
    assert linhas["status"].tolist() == ["OK", "DIVERGENTE", "DIVERGENTE"]


def test_empresa_fora_do_mapa_e_reportada_em_vez_de_sumir():
    meses = [202501]
    contabil = conc.preparar_lado(_lado("lancamentos", [("KOBE", 202501, 100.0)]), meses)
    financeiro = conc.preparar_lado(
        _lado("CAIXAS", [("KOBE", 202501, 100.0), ("MARCA NOVA", 202501, 50.0)]), meses
    )
    linhas, sem_contrapartida = conc.conciliar(contabil, financeiro, CONFIG, 202501)

    assert sem_contrapartida["financeiro_sem_mapa"] == ["MARCA NOVA"]
    assert linhas["empresa"].tolist() == ["KOBE"]


def test_empresa_so_no_contabil_e_reportada():
    meses = [202501]
    contabil = conc.preparar_lado(
        _lado("lancamentos", [("KOBE", 202501, 100.0), ("CORRETORA", 202501, 500.0)]), meses
    )
    financeiro = conc.preparar_lado(_lado("CAIXAS", [("KOBE", 202501, 100.0)]), meses)
    _, sem_contrapartida = conc.conciliar(contabil, financeiro, CONFIG, 202501)
    assert sem_contrapartida["so_no_contabil"] == ["CORRETORA"]


# --------------------------------------------------------------------------- #
# Quadro de abertura
# --------------------------------------------------------------------------- #
def test_abertura_marca_empresa_sem_saldo_inicial_lancado():
    """CORRETORA nunca teve 'SALDO INICIAL DA PLANILHA' — não pode passar batido."""
    contabil_bruto = _lado(
        "lancamentos",
        [("CORRETORA", 202412, 57633.92), ("ROYAL", 202412, 6377.71), ("ROYAL", 202501, 9830.15)],
    )
    abertura_fin = pd.DataFrame(
        [{"CAIXAS[EMPRESA]": "ROYAL ENFIELD", "[ABERTURA]": 6377.71}]
    )
    quadro = conc._preparar_abertura(abertura_fin, contabil_bruto, CONFIG).set_index("empresa")

    assert quadro.loc["ROYAL", "status"] == "OK"
    assert quadro.loc["CORRETORA", "status"] == "DIVERGENTE"
    assert quadro.loc["CORRETORA", "diferenca"] == pytest.approx(-57633.92)


def test_abertura_usa_o_ultimo_mes_ate_o_fechamento_e_ignora_2025():
    """O saldo de fechamento é o de 12/2024 — meses de 2025 não podem vazar."""
    contabil_bruto = _lado(
        "lancamentos", [("KOBE", 202412, 188392.24), ("KOBE", 202501, 276996.29)]
    )
    abertura_fin = pd.DataFrame([{"CAIXAS[EMPRESA]": "KOBE", "[ABERTURA]": 188392.24}])
    quadro = conc._preparar_abertura(abertura_fin, contabil_bruto, CONFIG).set_index("empresa")
    assert quadro.loc["KOBE", "contabil_fechamento"] == pytest.approx(188392.24)
    assert quadro.loc["KOBE", "status"] == "OK"


# --------------------------------------------------------------------------- #
# Transferências internas
# --------------------------------------------------------------------------- #
def test_transferencia_liquida_zero_nao_vira_aviso():
    """Transferência entre revendas da MESMA empresa se anula — é o caso normal."""
    bruto = pd.DataFrame(
        [{"CAIXAS[EMPRESA]": "KOBE", "[CHAVE]": 202603.0, "[LIQUIDO_TRANSF]": 0.0}]
    )
    assert conc._preparar_transferencias(bruto, CONFIG).empty


def test_transferencia_liquida_nao_zero_vira_aviso():
    bruto = pd.DataFrame(
        [{"CAIXAS[EMPRESA]": "KOBE", "[CHAVE]": 202603.0, "[LIQUIDO_TRANSF]": -5000.0}]
    )
    avisos = conc._preparar_transferencias(bruto, CONFIG)
    assert len(avisos) == 1
    assert avisos.iloc[0]["liquido"] == pytest.approx(-5000.0)


# --------------------------------------------------------------------------- #
# Montagem do DAX
# --------------------------------------------------------------------------- #
def test_dax_contabil_usa_valor_ajustado_e_nao_valor_cru():
    query = dxc.saldos_contabeis_mensais(["11101010001"], 202607, 202501)
    assert "VALOR_AJUSTADO" in query
    assert "'lancamentos'[VALOR]" not in query


def test_dax_financeiro_nao_exclui_caixas_nem_a_abertura():
    """Toda regra de auditoria exclui 9/99/4 e a abertura. A conciliação, não."""
    query = dxc.saldos_financeiros_mensais(date(2026, 7, 31), 202501)
    assert "SALDO INICIAL DA PLANILHA" not in query
    for caixa in ('"9"', '"99"', '"4"'):
        assert caixa not in query


def test_dax_financeiro_corta_na_data_informada():
    query = dxc.saldos_financeiros_mensais(date(2026, 7, 31), 202501)
    assert "DATE(2026,7,31)" in query


def test_dax_filtra_por_empresa_quando_pedido():
    query = dxc.saldos_contabeis_mensais(["11101010001"], 202607, 202501, empresa="ROYAL")
    assert '\'lancamentos\'[EMPRESA] = "ROYAL"' in query


def test_dax_escapa_aspas_no_nome_da_empresa():
    query = dxc.saldos_financeiros_mensais(date(2026, 7, 31), 202501, empresa='A"B')
    assert 'A""B' in query


def test_dax_search_sempre_tem_o_quarto_argumento():
    """SEARCH sem fallback devolve 400 genérico nesta API — armadilha conhecida."""
    for query in (
        dxc.contas_de_caixa_candidatas(),
        dxc.transferencias_por_empresa(date(2026, 7, 31), 202501),
    ):
        assert ", 1, 0)" in query


def test_transferencia_so_olha_caixa_a_caixa_e_nao_caixa_para_banco():
    """O filtro largo por "TRANSF" pegava `TRANSF. CAIXA P/ SANTANDER` & cia.

    Essas têm contrapartida em conta bancária e SÃO contabilizadas. Com elas no
    filtro, KOBE — que concilia centavo a centavo — aparecia com líquido
    diferente de zero nos 18 meses do período. O padrão tem que ser o do saldo
    de caixa, não o "TRANSF" solto.
    """
    query = dxc.transferencias_por_empresa(date(2026, 7, 31), 202501)
    assert '"SALDO CAIXA"' in query
    assert '"SALDO DE CAIXA"' in query
    assert 'SEARCH("TRANSF",' not in query


def test_transferencia_sem_padroes_e_rejeitada():
    with pytest.raises(ValueError):
        dxc.transferencias_por_empresa(date(2026, 7, 31), 202501, [])


def test_lista_de_contas_vazia_e_rejeitada():
    with pytest.raises(ValueError):
        dxc.saldos_contabeis_mensais([], 202607, 202501)


def test_abertura_respeita_o_filtro_de_empresa():
    """Sem o filtro, `--empresa ROYAL` trazia a abertura de todas as marcas.

    O quadro comparava a abertura das outras contra saldo contábil zero (elas
    estavam fora do recorte contábil) e inventava divergências de centenas de
    milhares de reais em empresas que nem estavam sendo conciliadas.
    """
    query = dxc.abertura_financeira("ROYAL ENFIELD")
    assert '\'CAIXAS\'[EMPRESA] = "ROYAL ENFIELD"' in query
    assert dxc.HISTORICO_ABERTURA in query


def test_abertura_sem_empresa_nao_filtra():
    query = dxc.abertura_financeira()
    assert "[EMPRESA] =" not in query
