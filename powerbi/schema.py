"""Descoberta do modelo semântico via consultas DAX ``INFO.*``.

Extrai tabelas, colunas, medidas e relacionamentos usando as funções de
metadados do DAX (``INFO.TABLES()``, ``INFO.COLUMNS()``, ``INFO.MEASURES()``,
``INFO.RELATIONSHIPS()``). Se essas funções não estiverem disponíveis no
dataset, a extração degrada graciosamente e a limitação é registrada no
resultado.

Todo o processamento é somente leitura.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pandas as pd

from powerbi.client import ErroPowerBI, PowerBIClient

# Mapa dos códigos de tipo de dado (TOM DataType) para rótulos em português.
_TIPOS_DADOS: dict[int, str] = {
    1: "Automático",
    2: "Texto",
    6: "Número inteiro",
    8: "Número decimal",
    9: "Data/hora",
    10: "Decimal fixo (moeda)",
    11: "Booleano",
    17: "Binário",
    19: "Variante",
}


@dataclass
class EsquemaModelo:
    """Esquema extraído de um modelo semântico do Power BI.

    Attributes:
        tabelas: DataFrame com colunas ``nome`` e ``descricao``.
        colunas: DataFrame com ``tabela``, ``nome``, ``tipo``, ``descricao``.
        medidas: DataFrame com ``tabela``, ``nome``, ``expressao``,
            ``formato``, ``descricao``.
        relacionamentos: DataFrame com ``de``, ``para``, ``ativa``,
            ``cardinalidade``.
        limitacoes: Lista de avisos sobre partes não extraídas.
    """

    tabelas: pd.DataFrame = field(default_factory=pd.DataFrame)
    colunas: pd.DataFrame = field(default_factory=pd.DataFrame)
    medidas: pd.DataFrame = field(default_factory=pd.DataFrame)
    relacionamentos: pd.DataFrame = field(default_factory=pd.DataFrame)
    limitacoes: list[str] = field(default_factory=list)


def _normalizar_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """Remove prefixos de tabela e colchetes dos nomes de colunas do DAX.

    Ex.: ``"Tabela[Nome]"`` ou ``"[Nome]"`` viram ``"Nome"``.

    Args:
        df: DataFrame retornado por uma consulta ``INFO.*``.

    Returns:
        DataFrame com colunas renomeadas.
    """
    novo = {}
    for coluna in df.columns:
        m = re.search(r"\[([^\]]+)\]\s*$", str(coluna))
        novo[coluna] = m.group(1) if m else str(coluna)
    return df.rename(columns=novo)


def _coluna(df: pd.DataFrame, *nomes: str) -> pd.Series | None:
    """Retorna a primeira coluna existente entre ``nomes`` (case-insensitive)."""
    minusculas = {str(c).lower(): c for c in df.columns}
    for nome in nomes:
        real = minusculas.get(nome.lower())
        if real is not None:
            return df[real]
    return None


def _consultar_info(cliente: PowerBIClient, funcao: str, dataset_id: str | None) -> pd.DataFrame:
    """Executa uma consulta ``EVALUATE INFO.X()`` e normaliza as colunas."""
    df = cliente.execute_dax(f"EVALUATE {funcao}", dataset_id=dataset_id)
    return _normalizar_colunas(df)


def extrair_esquema(
    cliente: PowerBIClient, dataset_id: str | None = None
) -> EsquemaModelo:
    """Extrai o esquema completo de um modelo semântico.

    Args:
        cliente: Cliente Power BI já autenticado.
        dataset_id: Apelido, GUID do dataset ou ``None`` para o padrão.

    Returns:
        :class:`EsquemaModelo` com tabelas, colunas, medidas e relacionamentos.
        Partes que não puderem ser extraídas ficam vazias e são registradas em
        ``limitacoes``.
    """
    esquema = EsquemaModelo()

    # ------------------------------------------------------------------ #
    # Tabelas
    # ------------------------------------------------------------------ #
    mapa_tabelas: dict = {}
    try:
        bruto = _consultar_info(cliente, "INFO.TABLES()", dataset_id)
        ids = _coluna(bruto, "ID")
        nomes = _coluna(bruto, "Name")
        descr = _coluna(bruto, "Description")
        ocultas = _coluna(bruto, "IsHidden")
        registros = []
        for i in range(len(bruto)):
            nome = str(nomes.iloc[i]) if nomes is not None else ""
            # Ignora tabelas ocultas e internas de data/hora automáticas.
            oculta = bool(ocultas.iloc[i]) if ocultas is not None else False
            if oculta or nome.startswith("LocalDateTable_") or nome.startswith("DateTableTemplate_"):
                if ids is not None:
                    mapa_tabelas[ids.iloc[i]] = nome
                continue
            if ids is not None:
                mapa_tabelas[ids.iloc[i]] = nome
            registros.append(
                {
                    "nome": nome,
                    "descricao": str(descr.iloc[i]) if descr is not None and pd.notna(descr.iloc[i]) else "",
                }
            )
        esquema.tabelas = pd.DataFrame(registros)
    except ErroPowerBI as exc:
        esquema.limitacoes.append(f"Não foi possível listar tabelas (INFO.TABLES): {exc}")

    # ------------------------------------------------------------------ #
    # Colunas
    # ------------------------------------------------------------------ #
    mapa_colunas: dict = {}
    try:
        bruto = _consultar_info(cliente, "INFO.COLUMNS()", dataset_id)
        ids = _coluna(bruto, "ID")
        tabela_id = _coluna(bruto, "TableID")
        expl = _coluna(bruto, "ExplicitName")
        infer = _coluna(bruto, "InferredName")
        tipo = _coluna(bruto, "ExplicitDataType", "DataType")
        descr = _coluna(bruto, "Description")
        ocultas = _coluna(bruto, "IsHidden")
        registros = []
        for i in range(len(bruto)):
            nome = ""
            if expl is not None and pd.notna(expl.iloc[i]) and str(expl.iloc[i]):
                nome = str(expl.iloc[i])
            elif infer is not None and pd.notna(infer.iloc[i]):
                nome = str(infer.iloc[i])
            if not nome or nome.startswith("RowNumber"):
                if ids is not None:
                    mapa_colunas[ids.iloc[i]] = nome
                continue
            tab = mapa_tabelas.get(tabela_id.iloc[i]) if tabela_id is not None else ""
            if ids is not None:
                mapa_colunas[ids.iloc[i]] = f"{tab}[{nome}]" if tab else nome
            oculta = bool(ocultas.iloc[i]) if ocultas is not None else False
            if oculta or tab is None:
                continue
            cod_tipo = None
            if tipo is not None and pd.notna(tipo.iloc[i]):
                try:
                    cod_tipo = int(tipo.iloc[i])
                except (TypeError, ValueError):
                    cod_tipo = None
            registros.append(
                {
                    "tabela": tab or "",
                    "nome": nome,
                    "tipo": _TIPOS_DADOS.get(cod_tipo, "—") if cod_tipo is not None else "—",
                    "descricao": str(descr.iloc[i]) if descr is not None and pd.notna(descr.iloc[i]) else "",
                }
            )
        esquema.colunas = pd.DataFrame(registros)
    except ErroPowerBI as exc:
        esquema.limitacoes.append(f"Não foi possível listar colunas (INFO.COLUMNS): {exc}")

    # ------------------------------------------------------------------ #
    # Medidas
    # ------------------------------------------------------------------ #
    try:
        bruto = _consultar_info(cliente, "INFO.MEASURES()", dataset_id)
        tabela_id = _coluna(bruto, "TableID")
        nomes = _coluna(bruto, "Name")
        expr = _coluna(bruto, "Expression")
        fmt = _coluna(bruto, "FormatString")
        descr = _coluna(bruto, "Description")
        ocultas = _coluna(bruto, "IsHidden")
        registros = []
        for i in range(len(bruto)):
            oculta = bool(ocultas.iloc[i]) if ocultas is not None else False
            if oculta:
                continue
            tab = mapa_tabelas.get(tabela_id.iloc[i], "") if tabela_id is not None else ""
            registros.append(
                {
                    "tabela": tab or "",
                    "nome": str(nomes.iloc[i]) if nomes is not None else "",
                    "expressao": (str(expr.iloc[i]).strip() if expr is not None and pd.notna(expr.iloc[i]) else ""),
                    "formato": str(fmt.iloc[i]) if fmt is not None and pd.notna(fmt.iloc[i]) else "",
                    "descricao": str(descr.iloc[i]) if descr is not None and pd.notna(descr.iloc[i]) else "",
                }
            )
        esquema.medidas = pd.DataFrame(registros)
    except ErroPowerBI as exc:
        esquema.limitacoes.append(f"Não foi possível listar medidas (INFO.MEASURES): {exc}")

    # ------------------------------------------------------------------ #
    # Relacionamentos
    # ------------------------------------------------------------------ #
    try:
        bruto = _consultar_info(cliente, "INFO.RELATIONSHIPS()", dataset_id)
        de_col = _coluna(bruto, "FromColumnID")
        para_col = _coluna(bruto, "ToColumnID")
        ativa = _coluna(bruto, "IsActive")
        from_card = _coluna(bruto, "FromCardinality")
        to_card = _coluna(bruto, "ToCardinality")
        registros = []
        for i in range(len(bruto)):
            de = mapa_colunas.get(de_col.iloc[i], "?") if de_col is not None else "?"
            para = mapa_colunas.get(para_col.iloc[i], "?") if para_col is not None else "?"
            card = _descrever_cardinalidade(
                from_card.iloc[i] if from_card is not None else None,
                to_card.iloc[i] if to_card is not None else None,
            )
            registros.append(
                {
                    "de": de,
                    "para": para,
                    "ativa": bool(ativa.iloc[i]) if ativa is not None else True,
                    "cardinalidade": card,
                }
            )
        esquema.relacionamentos = pd.DataFrame(registros)
    except ErroPowerBI as exc:
        esquema.limitacoes.append(
            f"Não foi possível listar relacionamentos (INFO.RELATIONSHIPS): {exc}"
        )

    if esquema.limitacoes and esquema.tabelas.empty and esquema.medidas.empty:
        esquema.limitacoes.append(
            "As funções INFO.* podem não estar disponíveis neste dataset "
            "(compatibilidade antiga). Verifique o nível de compatibilidade do modelo."
        )

    return esquema


def _descrever_cardinalidade(de_card, para_card) -> str:
    """Descreve a cardinalidade de um relacionamento (ex.: '1:N')."""
    mapa = {1: "1", 2: "N"}
    try:
        d = mapa.get(int(de_card), "?")
        p = mapa.get(int(para_card), "?")
        return f"{d}:{p}"
    except (TypeError, ValueError):
        return "—"
