"""Biblioteca de consultas DAX parametrizadas e seguras.

Monta strings DAX a partir de parâmetros, escapando corretamente valores de
texto (aspas duplas viram ``""``) e referências de tabela/coluna. Todas as
consultas geradas são somente leitura (``EVALUATE``) e limitadas por ``TOPN``
para proteger o contexto do Claude.

As funções aqui **não** chamam a API — apenas devolvem a string DAX. A execução
fica a cargo do :class:`~powerbi.client.PowerBIClient`.
"""

from __future__ import annotations

import numbers
from datetime import date, datetime


def escapar_texto(valor: str) -> str:
    """Escapa um valor de texto para uso dentro de um literal DAX.

    Em DAX, uma aspa dupla dentro de uma string é escrita como duas aspas
    duplas. Ex.: ``ele disse "oi"`` -> ``ele disse ""oi""``.

    Args:
        valor: Texto a escapar (sem as aspas externas).

    Returns:
        O texto com aspas duplas escapadas.
    """
    return str(valor).replace('"', '""')


def ref_tabela(tabela: str) -> str:
    """Devolve uma referência de tabela DAX segura (entre aspas simples).

    Args:
        tabela: Nome da tabela.

    Returns:
        A tabela no formato ``'Nome Da Tabela'`` (aspas simples escapadas).
    """
    seguro = str(tabela).replace("'", "''")
    return f"'{seguro}'"


def ref_coluna(tabela: str, coluna: str) -> str:
    """Devolve uma referência de coluna DAX segura (``'Tabela'[Coluna]``).

    Args:
        tabela: Nome da tabela.
        coluna: Nome da coluna.

    Returns:
        A referência qualificada, com ``]`` escapado na coluna.
    """
    coluna_segura = str(coluna).replace("]", "]]")
    return f"{ref_tabela(tabela)}[{coluna_segura}]"


def _parse_ref(ref: str) -> str:
    """Normaliza uma referência ``Tabela[Coluna]`` para forma segura.

    Aceita ``Tabela[Coluna]`` ou ``'Tabela'[Coluna]`` e devolve a forma
    canônica com aspas simples e escapes. Se não houver ``[``, devolve o texto
    original (assumindo que já é uma referência válida).

    Args:
        ref: Referência de coluna no formato ``Tabela[Coluna]``.

    Returns:
        Referência de coluna segura.
    """
    if "[" not in ref:
        return ref
    tabela, _, resto = ref.partition("[")
    coluna = resto.rstrip("]")
    tabela = tabela.strip().strip("'")
    return ref_coluna(tabela, coluna)


def formatar_valor(valor) -> str:
    """Formata um valor Python como literal DAX.

    Args:
        valor: Valor a formatar (texto, número, booleano, data ou ``None``).

    Returns:
        A representação DAX do valor (texto entre aspas, número puro,
        ``TRUE()``/``FALSE()``, data via ``DATE(a,m,d)`` ou ``BLANK()``).
    """
    if valor is None:
        return "BLANK()"
    if isinstance(valor, bool):
        return "TRUE()" if valor else "FALSE()"
    if isinstance(valor, numbers.Number):
        return str(valor)
    if isinstance(valor, (date, datetime)):
        return f"DATE({valor.year}, {valor.month}, {valor.day})"
    return f'"{escapar_texto(str(valor))}"'


def _condicoes_filtro(filtros: dict) -> list[str]:
    """Transforma um dict de filtros em condições DAX de igualdade.

    Args:
        filtros: Mapa ``{"Tabela[Coluna]": valor}``.

    Returns:
        Lista de condições, ex.: ``["'Tabela'[Coluna] = \"v\""]``.
    """
    condicoes = []
    for ref, valor in filtros.items():
        condicoes.append(f"{_parse_ref(ref)} = {formatar_valor(valor)}")
    return condicoes


def buscar_texto(
    tabela: str,
    coluna: str,
    termo: str,
    limite: int = 20,
    coluna_data: str | None = None,
) -> str:
    """Monta uma busca textual case-insensitive (estilo "compramos cloro?").

    Usa ``SEARCH`` (case-insensitive, sem erro quando não encontra) e limita o
    resultado com ``TOPN``. Se ``coluna_data`` for informada, ordena por ela em
    ordem decrescente (mais recentes primeiro).

    Args:
        tabela: Tabela onde buscar.
        coluna: Coluna de texto a pesquisar.
        termo: Termo procurado.
        limite: Máximo de linhas (``TOPN``).
        coluna_data: Coluna de data para ordenar (opcional).

    Returns:
        A consulta DAX pronta para execução.
    """
    tab = ref_tabela(tabela)
    col = ref_coluna(tabela, coluna)
    termo_esc = escapar_texto(termo)
    filtro = f'FILTER({tab}, SEARCH("{termo_esc}", {col}, 1, 0) > 0)'

    if coluna_data:
        col_data = ref_coluna(tabela, coluna_data)
        return (
            "EVALUATE\n"
            f"TOPN({int(limite)}, {filtro}, {col_data}, DESC)\n"
            f"ORDER BY {col_data} DESC"
        )
    return f"EVALUATE\nTOPN({int(limite)}, {filtro})"


def ultimas_ocorrencias(
    tabela: str,
    coluna_data: str,
    filtros: dict | None = None,
    limite: int = 20,
) -> str:
    """Monta uma consulta das últimas ocorrências (mais recentes primeiro).

    Args:
        tabela: Tabela a consultar.
        coluna_data: Coluna de data usada para ordenar (desc).
        filtros: Filtros de igualdade ``{"Tabela[Coluna]": valor}`` (opcional).
        limite: Máximo de linhas (``TOPN``).

    Returns:
        A consulta DAX pronta para execução.
    """
    tab = ref_tabela(tabela)
    col_data = ref_coluna(tabela, coluna_data)
    if filtros:
        condicoes = " && ".join(_condicoes_filtro(filtros))
        fonte = f"FILTER({tab}, {condicoes})"
    else:
        fonte = tab
    return (
        "EVALUATE\n"
        f"TOPN({int(limite)}, {fonte}, {col_data}, DESC)\n"
        f"ORDER BY {col_data} DESC"
    )


def resumo_medidas(
    medidas: list[str],
    dimensoes: list[str] | None = None,
    filtros: dict | None = None,
) -> str:
    """Monta um ``SUMMARIZECOLUMNS`` com medidas oficiais do modelo.

    Args:
        medidas: Nomes de medidas oficiais (ex.: ``["Faturamento"]``).
        dimensoes: Colunas de agrupamento no formato ``"Tabela[Coluna]"``.
        filtros: Filtros de igualdade ``{"Tabela[Coluna]": valor}``.

    Returns:
        A consulta DAX pronta para execução.

    Raises:
        ValueError: Se ``medidas`` estiver vazia.
    """
    if not medidas:
        raise ValueError("Informe ao menos uma medida em 'medidas'.")

    partes: list[str] = []
    for dim in dimensoes or []:
        partes.append("    " + _parse_ref(dim))

    for ref, valor in (filtros or {}).items():
        col = _parse_ref(ref)
        partes.append(
            f"    KEEPFILTERS(FILTER(ALL({col}), {col} = {formatar_valor(valor)}))"
        )

    for medida in medidas:
        nome_esc = escapar_texto(medida)
        partes.append(f'    "{nome_esc}", [{medida}]')

    corpo = ",\n".join(partes)
    return f"EVALUATE\nSUMMARIZECOLUMNS(\n{corpo}\n)"


def topn_por_medida(
    n: int,
    tabela_dim: str,
    coluna_dim: str,
    medida: str,
    ordem: str = "DESC",
) -> str:
    """Monta um ranking (Top N) de uma dimensão por uma medida.

    Args:
        n: Quantidade de itens no ranking.
        tabela_dim: Tabela da dimensão.
        coluna_dim: Coluna da dimensão (ex.: nome do produto/cliente).
        medida: Medida oficial usada para ordenar.
        ordem: ``"DESC"`` (maiores primeiro) ou ``"ASC"``.

    Returns:
        A consulta DAX pronta para execução.

    Raises:
        ValueError: Se ``ordem`` não for ``"ASC"`` nem ``"DESC"``.
    """
    ordem = ordem.upper()
    if ordem not in ("ASC", "DESC"):
        raise ValueError("O parâmetro 'ordem' deve ser 'ASC' ou 'DESC'.")

    col_dim = ref_coluna(tabela_dim, coluna_dim)
    nome_esc = escapar_texto(medida)
    tabela_base = (
        f"SUMMARIZECOLUMNS({col_dim}, \"{nome_esc}\", [{medida}])"
    )
    return (
        "EVALUATE\n"
        f"TOPN({int(n)}, {tabela_base}, [{medida}], {ordem})\n"
        f"ORDER BY [{medida}] {ordem}"
    )
