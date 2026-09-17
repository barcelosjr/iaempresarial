"""Testes da montagem do DAX do monitoramento COAF.

Validam a string da consulta — sem chamar a API. O que garantem é que as
armadilhas já pagas com debug real não voltem: o 4º argumento do ``SEARCH``,
a exclusão das linhas de abertura, a ausência de ``TOPN`` (que truncaria a
janela de acumulação) e o fato de os caixas de concentração **não** serem
filtrados aqui — no COAF eles entram e são sinalizados depois, em Python.
"""

from __future__ import annotations

from datetime import date

import pytest

from powerbi import dax_coaf


PERIODO = (date(2026, 2, 19), date(2026, 8, 19))


def test_filtra_apenas_recebimentos():
    query = dax_coaf.recebimentos_especie(*PERIODO)
    assert "'CAIXAS'[PAGAR_RECEBER] = \"R\"" in query


def test_search_sempre_tem_o_quarto_argumento():
    """Sem o fallback ``0``, ``SEARCH`` gera erro e a API devolve 400 sem detalhe."""
    query = dax_coaf.recebimentos_especie(*PERIODO)
    assert query.count(", 1, 0) = 0") == len(dax_coaf.PADROES_EXCLUSAO_PADRAO)
    assert "SEARCH(\"TRANSF\", 'CAIXAS'[ORIGEM], 1, 0) = 0" in query


def test_exclui_as_linhas_de_abertura():
    """As 28 linhas de SALDO INICIAL DA PLANILHA não têm NOME_USUARIO."""
    query = dax_coaf.recebimentos_especie(*PERIODO)
    assert "NOT(ISBLANK('CAIXAS'[NOME_USUARIO]))" in query


def test_nao_usa_topn():
    """TOPN truncaria a janela e produziria um total MENOR que o real."""
    query = dax_coaf.recebimentos_especie(*PERIODO)
    assert "TOPN" not in query


def test_nao_exclui_caixas_de_concentracao():
    """Ao contrário da auditoria, o COAF inclui os caixas 9/99/4 e sinaliza depois."""
    query = dax_coaf.recebimentos_especie(*PERIODO)
    assert "[CAIXA]" not in query.split("SELECTCOLUMNS")[0]
    assert '"9"' not in query and '"99"' not in query


def test_intervalo_de_datas_interpolado():
    query = dax_coaf.recebimentos_especie(*PERIODO)
    assert "'CAIXAS'[DATA] >= DATE(2026,2,19)" in query
    assert "'CAIXAS'[DATA] <= DATE(2026,8,19)" in query


def test_traz_historico_e_cliente():
    """HISTORICO é obrigatório: é de onde sai o nome do cliente."""
    query = dax_coaf.recebimentos_especie(*PERIODO)
    for coluna in ("HISTORICO", "CLIENTE", "EMPRESA", "REVENDA", "CAIXA", "VALOR", "ORIGEM"):
        assert f'"{coluna}", \'CAIXAS\'[{coluna}]' in query


def test_traz_nome_cliente():
    """NOME_CLIENTE (confirmado em produção 25/08/2026) é a fonte primária do
    nome — HISTORICO continua sendo trazido só como fallback."""
    query = dax_coaf.recebimentos_especie(*PERIODO)
    assert '"NOME_CLIENTE", \'CAIXAS\'[NOME_CLIENTE]' in query


def test_exclusoes_customizadas_substituem_o_padrao():
    query = dax_coaf.recebimentos_especie(*PERIODO, padroes_exclusao=["CARTAO"])
    assert "SEARCH(\"CARTAO\"" in query
    assert "SEARCH(\"TRANSF\"" not in query


def test_origens_exatas_viram_desigualdade():
    query = dax_coaf.recebimentos_especie(
        *PERIODO, origens_exatas=["417 - VENDA CARTAO DEB/CRED"]
    )
    assert "'CAIXAS'[ORIGEM] <> \"417 - VENDA CARTAO DEB/CRED\"" in query


def test_aspas_no_valor_sao_escapadas():
    query = dax_coaf.recebimentos_especie(*PERIODO, origens_exatas=['DIZ "OI"'])
    assert 'DIZ ""OI""' in query


def test_intervalo_invertido_e_rejeitado():
    with pytest.raises(ValueError, match="posterior"):
        dax_coaf.recebimentos_especie(date(2026, 8, 19), date(2026, 2, 19))


def test_origens_de_recebimento_nao_aplica_exclusao():
    """A consulta de revisão precisa mostrar TODAS as origens, inclusive as excluídas."""
    query = dax_coaf.origens_de_recebimento(*PERIODO)
    assert "SEARCH" not in query
    assert "SUMMARIZECOLUMNS" in query
    assert "'CAIXAS'[ORIGEM]" in query
