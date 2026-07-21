"""Servidor MCP local que expõe as ferramentas do analista-bi ao Claude.

Transporte: stdio. Ferramentas expostas (todas SOMENTE LEITURA):

* ``consultar_dax``     — executa DAX arbitrário e devolve até N linhas.
* ``buscar_item``       — atalho de busca textual (estilo "compramos cloro?").
* ``esquema_modelo``    — devolve o dicionário de dados do modelo.
* ``resumo_kpis``       — atalho para agregações com medidas oficiais.
* ``consultar_duckdb``  — consulta SELECT no banco local (complemento).

Cada resposta inclui, para auditoria: a query executada, o número de linhas
retornadas e se houve truncamento.

Registro (ver README):
    claude mcp add analista-bi -- python /caminho/para/mcp_server/server.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# Permite rodar como script (`python mcp_server/server.py`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp.server.fastmcp import FastMCP  # noqa: E402

from config.settings import RAIZ_PROJETO, carregar_configuracao  # noqa: E402
from local_data.ingest import ErroDuckDB, consultar_select, listar_tabelas  # noqa: E402
from powerbi import dax_lib  # noqa: E402
from powerbi.client import ErroPowerBI, PowerBIClient  # noqa: E402
from powerbi.schema import extrair_esquema  # noqa: E402

mcp = FastMCP("analista-bi")

# Cliente compartilhado, criado sob demanda (evita exigir credenciais só para importar).
_cliente: PowerBIClient | None = None
_limite_padrao: int | None = None


def _obter_cliente() -> PowerBIClient:
    """Devolve o :class:`PowerBIClient` compartilhado (criando-o na 1ª chamada)."""
    global _cliente, _limite_padrao
    if _cliente is None:
        config = carregar_configuracao()
        _cliente = PowerBIClient(config=config)
        _limite_padrao = config.limite_linhas_padrao
    return _cliente


def _limite() -> int:
    """Limite padrão de linhas (do ``.env``), com fallback conservador."""
    return _limite_padrao or 20


def _formatar_resultado(df: pd.DataFrame, query: str, limite: int) -> str:
    """Formata um DataFrame como texto auditável para o Claude.

    Args:
        df: Resultado da consulta.
        query: A consulta executada (para auditoria).
        limite: Limite de linhas aplicado.

    Returns:
        Texto com metadados (linhas, truncamento, query) e a tabela.
    """
    total = len(df)
    truncado = total > limite
    visao = df.head(limite)

    if visao.empty:
        corpo = "(nenhuma linha retornada)"
    else:
        corpo = visao.to_string(index=False)

    partes = [
        f"Linhas retornadas: {len(visao)}" + (f" (de {total}, TRUNCADO)" if truncado else ""),
        "",
        corpo,
        "",
        "— Query executada (auditoria) —",
        query.strip(),
    ]
    return "\n".join(partes)


@mcp.tool()
def consultar_dax(query: str, dataset: str | None = None) -> str:
    """Executa uma consulta DAX (somente leitura) e devolve até N linhas.

    Args:
        query: Consulta DAX iniciando com ``EVALUATE`` (ou ``DEFINE``).
        dataset: Apelido (ex.: "vendas") ou GUID do dataset. ``None`` = padrão.

    Returns:
        Texto com o resultado, número de linhas e a query (auditoria).
    """
    try:
        cliente = _obter_cliente()
        df = cliente.execute_dax(query, dataset_id=dataset)
        return _formatar_resultado(df, query, _limite())
    except ErroPowerBI as exc:
        return f"❌ Erro ao executar DAX:\n{exc}"


@mcp.tool()
def buscar_item(
    termo: str,
    tabela: str,
    coluna: str,
    dataset: str | None = None,
    coluna_data: str | None = None,
    limite: int | None = None,
) -> str:
    """Busca textual case-insensitive (estilo "compramos cloro?").

    Args:
        termo: Termo a procurar (ex.: "cloro").
        tabela: Tabela onde buscar (ex.: "Compras").
        coluna: Coluna de texto a pesquisar (ex.: "Descricao").
        dataset: Apelido ou GUID do dataset. ``None`` = padrão.
        coluna_data: Coluna de data para ordenar (mais recentes primeiro).
        limite: Máximo de linhas. ``None`` usa o padrão do projeto.

    Returns:
        Texto com as ocorrências encontradas e a query executada.
    """
    lim = limite or _limite()
    query = dax_lib.buscar_texto(tabela, coluna, termo, limite=lim, coluna_data=coluna_data)
    try:
        cliente = _obter_cliente()
        df = cliente.execute_dax(query, dataset_id=dataset)
        if df.empty:
            return (
                f"Nenhuma ocorrência de '{termo}' em {tabela}[{coluna}].\n"
                "Dica: tente sinônimos/variações (ex.: cloro → hipoclorito, tricloro).\n\n"
                f"— Query executada (auditoria) —\n{query}"
            )
        return _formatar_resultado(df, query, lim)
    except ErroPowerBI as exc:
        return f"❌ Erro na busca:\n{exc}"


@mcp.tool()
def esquema_modelo(dataset: str | None = None, forcar_extracao: bool = False) -> str:
    """Devolve o dicionário de dados do modelo (tabelas, colunas, medidas).

    Prefere o arquivo ``dictionary/modelo_semantico.md`` (gerado por
    ``gerar_dicionario.py``). Se ausente — ou se ``forcar_extracao`` for
    ``True`` — extrai o esquema ao vivo via consultas ``INFO.*``.

    Args:
        dataset: Apelido ou GUID do dataset. ``None`` = padrão.
        forcar_extracao: Ignora o arquivo e extrai o esquema ao vivo.

    Returns:
        O dicionário de dados em Markdown.
    """
    arquivo = RAIZ_PROJETO / "dictionary" / "modelo_semantico.md"
    if arquivo.exists() and not forcar_extracao:
        return arquivo.read_text(encoding="utf-8")

    try:
        cliente = _obter_cliente()
        esquema = extrair_esquema(cliente, dataset_id=dataset)
    except ErroPowerBI as exc:
        return f"❌ Erro ao extrair o esquema:\n{exc}"

    linhas = ["# Esquema (extraído ao vivo)", ""]
    if esquema.limitacoes:
        linhas.append("⚠️ Limitações: " + "; ".join(esquema.limitacoes))
        linhas.append("")
    if not esquema.tabelas.empty:
        linhas.append("## Tabelas")
        linhas.append(", ".join(esquema.tabelas["nome"].astype(str)))
        linhas.append("")
    if not esquema.medidas.empty:
        linhas.append("## Medidas")
        linhas.append(", ".join(esquema.medidas["nome"].astype(str)))
        linhas.append("")
    linhas.append("Gere o dicionário completo com: python scripts/gerar_dicionario.py")
    return "\n".join(linhas)


@mcp.tool()
def resumo_kpis(
    medidas: list[str],
    dimensoes: list[str] | None = None,
    filtros: dict | None = None,
    dataset: str | None = None,
) -> str:
    """Atalho para agregações usando medidas oficiais (SUMMARIZECOLUMNS).

    Args:
        medidas: Nomes de medidas oficiais (ex.: ["Faturamento", "Margem"]).
        dimensoes: Colunas de agrupamento no formato "Tabela[Coluna]".
        filtros: Filtros de igualdade {"Tabela[Coluna]": valor}.
        dataset: Apelido ou GUID do dataset. ``None`` = padrão.

    Returns:
        Texto com o resultado agregado e a query executada.
    """
    try:
        query = dax_lib.resumo_medidas(medidas, dimensoes, filtros)
    except ValueError as exc:
        return f"❌ {exc}"
    try:
        cliente = _obter_cliente()
        df = cliente.execute_dax(query, dataset_id=dataset)
        return _formatar_resultado(df, query, _limite())
    except ErroPowerBI as exc:
        return f"❌ Erro no resumo de KPIs:\n{exc}"


@mcp.tool()
def consultar_duckdb(sql: str, limite: int = 100) -> str:
    """Consulta o banco local DuckDB (SOMENTE SELECT).

    Use para dados que não existem no Power BI (planilhas avulsas, textos de
    pós-venda) previamente ingeridos com ``local_data/ingest.py``.

    Args:
        sql: Consulta SELECT (ou WITH ... SELECT). Qualquer outro comando é recusado.
        limite: Máximo de linhas retornadas.

    Returns:
        Texto com o resultado e a query, ou a lista de tabelas se o SQL falhar.
    """
    try:
        df = consultar_select(sql, limite=limite)
        return _formatar_resultado(df, sql, limite)
    except ErroDuckDB as exc:
        tabelas = listar_tabelas()
        disp = ", ".join(tabelas) if tabelas else "(nenhuma — rode a ingestão primeiro)"
        return f"❌ {exc}\n\nTabelas disponíveis no banco local: {disp}"


def main() -> None:
    """Inicia o servidor MCP no transporte stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
