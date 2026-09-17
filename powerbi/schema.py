"""Descoberta do modelo semântico via consultas DAX ``INFO.*``.

Extrai tabelas, colunas, medidas e relacionamentos usando as funções de
metadados do DAX (``INFO.TABLES()``, ``INFO.COLUMNS()``, ``INFO.MEASURES()``,
``INFO.RELATIONSHIPS()``). A API REST ``executeQueries`` rejeita a família
``INFO.*`` em alguns datasets (400) mas aceita ``INFO.VIEW.*``, que devolve
nomes de tabela e tipos de dado como texto em vez de IDs/códigos — por isso
cada consulta tenta a forma clássica e cai para a ``VIEW``, e o parser aceita
os dois formatos. Se nenhuma estiver disponível, a extração degrada
graciosamente e a limitação é registrada no resultado.

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

# Mesmos rótulos para os nomes textuais devolvidos por ``INFO.VIEW.COLUMNS()``.
_TIPOS_DADOS_TEXTO: dict[str, str] = {
    "automatic": "Automático",
    "string": "Texto",
    "text": "Texto",
    "number": "Número",
    "integer": "Número inteiro",
    "int64": "Número inteiro",
    "double": "Número decimal",
    "datetime": "Data/hora",
    "decimal": "Decimal fixo (moeda)",
    "boolean": "Booleano",
    "binary": "Binário",
    "variant": "Variante",
}

# Cardinalidade: código numérico (``INFO.RELATIONSHIPS``) ou texto (``VIEW``).
_CARDINALIDADES: dict[str, str] = {"1": "1", "one": "1", "2": "N", "many": "N"}


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


def _texto(valor) -> str:
    """Valor como texto, com ``None``/NaN virando string vazia."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return ""
    return str(valor)


def _bool(valor) -> bool:
    """Interpreta booleanos nativos ou textuais (``"True"``/``"False"``)."""
    if isinstance(valor, str):
        return valor.strip().lower() in {"true", "1"}
    try:
        return bool(valor) if pd.notna(valor) else False
    except (TypeError, ValueError):
        return False


def _rotulo_tipo(valor) -> str:
    """Rótulo do tipo de dado a partir do código TOM ou do nome textual."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "—"
    try:
        return _TIPOS_DADOS.get(int(valor), "—")
    except (TypeError, ValueError):
        return _TIPOS_DADOS_TEXTO.get(str(valor).strip().lower(), str(valor))


def _consultar_info(cliente: PowerBIClient, funcao: str, dataset_id: str | None) -> pd.DataFrame:
    """Executa ``EVALUATE INFO.X()`` — ou ``INFO.VIEW.X()`` se a primeira for
    rejeitada — e normaliza as colunas.

    Args:
        cliente: Cliente Power BI já autenticado.
        funcao: Nome da função sem prefixo (``"TABLES"``, ``"COLUMNS"``...).
        dataset_id: Apelido, GUID do dataset ou ``None`` para o padrão.
    """
    try:
        df = cliente.execute_dax(f"EVALUATE INFO.{funcao}()", dataset_id=dataset_id)
    except ErroPowerBI:
        df = cliente.execute_dax(f"EVALUATE INFO.VIEW.{funcao}()", dataset_id=dataset_id)
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
        bruto = _consultar_info(cliente, "TABLES", dataset_id)
        ids = _coluna(bruto, "ID")
        nomes = _coluna(bruto, "Name")
        descr = _coluna(bruto, "Description")
        ocultas = _coluna(bruto, "IsHidden")
        registros = []
        for i in range(len(bruto)):
            nome = _texto(nomes.iloc[i]) if nomes is not None else ""
            # Ignora tabelas ocultas e internas de data/hora automáticas.
            oculta = _bool(ocultas.iloc[i]) if ocultas is not None else False
            if oculta or nome.startswith("LocalDateTable_") or nome.startswith("DateTableTemplate_"):
                if ids is not None:
                    mapa_tabelas[ids.iloc[i]] = nome
                continue
            if ids is not None:
                mapa_tabelas[ids.iloc[i]] = nome
            registros.append(
                {
                    "nome": nome,
                    "descricao": _texto(descr.iloc[i]) if descr is not None else "",
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
        bruto = _consultar_info(cliente, "COLUMNS", dataset_id)
        ids = _coluna(bruto, "ID")
        tabela_id = _coluna(bruto, "TableID")
        tabela_nome = _coluna(bruto, "Table")  # só na forma VIEW
        expl = _coluna(bruto, "ExplicitName", "Name")
        infer = _coluna(bruto, "InferredName")
        tipo = _coluna(bruto, "ExplicitDataType", "DataType")
        descr = _coluna(bruto, "Description")
        ocultas = _coluna(bruto, "IsHidden")
        registros = []
        for i in range(len(bruto)):
            nome = _texto(expl.iloc[i]) if expl is not None else ""
            if not nome and infer is not None:
                nome = _texto(infer.iloc[i])
            if not nome or nome.startswith("RowNumber"):
                if ids is not None:
                    mapa_colunas[ids.iloc[i]] = nome
                continue
            if tabela_nome is not None:
                tab = _texto(tabela_nome.iloc[i])
            elif tabela_id is not None:
                tab = mapa_tabelas.get(tabela_id.iloc[i])
            else:
                tab = ""
            if ids is not None:
                mapa_colunas[ids.iloc[i]] = f"{tab}[{nome}]" if tab else nome
            oculta = _bool(ocultas.iloc[i]) if ocultas is not None else False
            if oculta or tab is None:
                continue
            registros.append(
                {
                    "tabela": tab or "",
                    "nome": nome,
                    "tipo": _rotulo_tipo(tipo.iloc[i]) if tipo is not None else "—",
                    "descricao": _texto(descr.iloc[i]) if descr is not None else "",
                }
            )
        esquema.colunas = pd.DataFrame(registros)
    except ErroPowerBI as exc:
        esquema.limitacoes.append(f"Não foi possível listar colunas (INFO.COLUMNS): {exc}")

    # ------------------------------------------------------------------ #
    # Medidas
    # ------------------------------------------------------------------ #
    try:
        bruto = _consultar_info(cliente, "MEASURES", dataset_id)
        tabela_id = _coluna(bruto, "TableID")
        tabela_nome = _coluna(bruto, "Table")  # só na forma VIEW
        nomes = _coluna(bruto, "Name")
        expr = _coluna(bruto, "Expression")
        fmt = _coluna(bruto, "FormatString")
        descr = _coluna(bruto, "Description")
        ocultas = _coluna(bruto, "IsHidden")
        registros = []
        for i in range(len(bruto)):
            oculta = _bool(ocultas.iloc[i]) if ocultas is not None else False
            if oculta:
                continue
            if tabela_nome is not None:
                tab = _texto(tabela_nome.iloc[i])
            elif tabela_id is not None:
                tab = mapa_tabelas.get(tabela_id.iloc[i], "")
            else:
                tab = ""
            registros.append(
                {
                    "tabela": tab or "",
                    "nome": _texto(nomes.iloc[i]) if nomes is not None else "",
                    "expressao": _texto(expr.iloc[i]).strip() if expr is not None else "",
                    "formato": _texto(fmt.iloc[i]) if fmt is not None else "",
                    "descricao": _texto(descr.iloc[i]) if descr is not None else "",
                }
            )
        esquema.medidas = pd.DataFrame(registros)
    except ErroPowerBI as exc:
        esquema.limitacoes.append(f"Não foi possível listar medidas (INFO.MEASURES): {exc}")

    # ------------------------------------------------------------------ #
    # Relacionamentos
    # ------------------------------------------------------------------ #
    try:
        bruto = _consultar_info(cliente, "RELATIONSHIPS", dataset_id)
        de_col = _coluna(bruto, "FromColumnID")
        para_col = _coluna(bruto, "ToColumnID")
        # Forma VIEW: tabela e coluna já vêm por nome.
        de_tab, de_nome = _coluna(bruto, "FromTable"), _coluna(bruto, "FromColumn")
        para_tab, para_nome = _coluna(bruto, "ToTable"), _coluna(bruto, "ToColumn")
        ativa = _coluna(bruto, "IsActive")
        from_card = _coluna(bruto, "FromCardinality")
        to_card = _coluna(bruto, "ToCardinality")
        registros = []
        for i in range(len(bruto)):
            if de_tab is not None and de_nome is not None:
                de = f"{_texto(de_tab.iloc[i])}[{_texto(de_nome.iloc[i])}]"
            else:
                de = mapa_colunas.get(de_col.iloc[i], "?") if de_col is not None else "?"
            if para_tab is not None and para_nome is not None:
                para = f"{_texto(para_tab.iloc[i])}[{_texto(para_nome.iloc[i])}]"
            else:
                para = mapa_colunas.get(para_col.iloc[i], "?") if para_col is not None else "?"
            card = _descrever_cardinalidade(
                from_card.iloc[i] if from_card is not None else None,
                to_card.iloc[i] if to_card is not None else None,
            )
            registros.append(
                {
                    "de": de,
                    "para": para,
                    "ativa": _bool(ativa.iloc[i]) if ativa is not None else True,
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
    """Descreve a cardinalidade de um relacionamento (ex.: '1:N').

    Aceita o código numérico de ``INFO.RELATIONSHIPS`` (1/2) ou o texto de
    ``INFO.VIEW.RELATIONSHIPS`` (``One``/``Many``).
    """
    d = _CARDINALIDADES.get(_texto(de_card).strip().lower())
    p = _CARDINALIDADES.get(_texto(para_card).strip().lower())
    if d is None and p is None:
        return "—"
    return f"{d or '?'}:{p or '?'}"
