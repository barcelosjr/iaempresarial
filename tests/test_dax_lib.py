"""Testes da montagem de consultas DAX (sem chamar a API)."""

from __future__ import annotations

from datetime import date

import pytest

from powerbi import dax_lib


def test_escapar_texto_dobra_aspas() -> None:
    """Aspas duplas são dobradas para virar literal DAX válido."""
    assert dax_lib.escapar_texto('disse "oi"') == 'disse ""oi""'


def test_ref_coluna_escapa_colchete() -> None:
    """Colchete de fechamento na coluna é escapado como ]]."""
    assert dax_lib.ref_coluna("Vendas", "Total[R$]") == "'Vendas'[Total[R$]]]"


def test_formatar_valor_tipos() -> None:
    """Valores são formatados conforme o tipo em DAX."""
    assert dax_lib.formatar_valor(10) == "10"
    assert dax_lib.formatar_valor(3.5) == "3.5"
    assert dax_lib.formatar_valor(True) == "TRUE()"
    assert dax_lib.formatar_valor(False) == "FALSE()"
    assert dax_lib.formatar_valor(None) == "BLANK()"
    assert dax_lib.formatar_valor("cloro") == '"cloro"'
    assert dax_lib.formatar_valor(date(2026, 7, 21)) == "DATE(2026, 7, 21)"


def test_buscar_texto_sem_data() -> None:
    """Busca textual usa SEARCH case-insensitive e TOPN, sem ORDER BY."""
    dax = dax_lib.buscar_texto("Compras", "Descricao", "cloro", limite=15)
    assert "EVALUATE" in dax
    assert "TOPN(15" in dax
    assert 'SEARCH("cloro", \'Compras\'[Descricao], 1, 0) > 0' in dax
    assert "ORDER BY" not in dax


def test_buscar_texto_com_data_ordena_desc() -> None:
    """Com coluna_data, ordena por data desc (mais recentes primeiro)."""
    dax = dax_lib.buscar_texto(
        "Compras", "Descricao", "cloro", limite=20, coluna_data="Data"
    )
    assert "ORDER BY 'Compras'[Data] DESC" in dax
    assert "TOPN(20" in dax


def test_buscar_texto_escapa_termo_perigoso() -> None:
    """Termo com aspas é escapado, evitando quebrar a string DAX."""
    dax = dax_lib.buscar_texto("T", "C", 'a"b')
    assert 'SEARCH("a""b"' in dax


def test_ultimas_ocorrencias_com_filtros() -> None:
    """Filtros viram condições de igualdade combinadas com &&."""
    dax = dax_lib.ultimas_ocorrencias(
        "Titulos",
        "Vencimento",
        filtros={"Titulos[Status]": "Aberto", "Titulos[Filial]": 3},
        limite=10,
    )
    assert "TOPN(10" in dax
    assert "'Titulos'[Status] = \"Aberto\"" in dax
    assert "'Titulos'[Filial] = 3" in dax
    assert "&&" in dax
    assert "ORDER BY 'Titulos'[Vencimento] DESC" in dax


def test_ultimas_ocorrencias_sem_filtros() -> None:
    """Sem filtros, usa a tabela inteira como fonte do TOPN."""
    dax = dax_lib.ultimas_ocorrencias("Pedidos", "Data")
    assert "TOPN(20, 'Pedidos', 'Pedidos'[Data], DESC)" in dax


def test_resumo_medidas_monta_summarizecolumns() -> None:
    """resumo_medidas monta SUMMARIZECOLUMNS com dimensões, filtros e medidas."""
    dax = dax_lib.resumo_medidas(
        medidas=["Faturamento", "Margem"],
        dimensoes=["Produto[Linha]"],
        filtros={"Calendario[Ano]": 2026},
    )
    assert "SUMMARIZECOLUMNS(" in dax
    assert "'Produto'[Linha]" in dax
    assert '"Faturamento", [Faturamento]' in dax
    assert '"Margem", [Margem]' in dax
    assert "KEEPFILTERS(FILTER(ALL('Calendario'[Ano]), 'Calendario'[Ano] = 2026))" in dax


def test_resumo_medidas_exige_medida() -> None:
    """Sem medidas, levanta ValueError."""
    with pytest.raises(ValueError):
        dax_lib.resumo_medidas(medidas=[])


def test_topn_por_medida() -> None:
    """topn_por_medida monta ranking com ORDER BY na medida."""
    dax = dax_lib.topn_por_medida(5, "Cliente", "Nome", "Faturamento", ordem="DESC")
    assert "TOPN(5" in dax
    assert "'Cliente'[Nome]" in dax
    assert '"Faturamento", [Faturamento]' in dax
    assert "ORDER BY [Faturamento] DESC" in dax


def test_topn_ordem_invalida() -> None:
    """Ordem diferente de ASC/DESC levanta ValueError."""
    with pytest.raises(ValueError):
        dax_lib.topn_por_medida(5, "Cliente", "Nome", "Faturamento", ordem="cima")
