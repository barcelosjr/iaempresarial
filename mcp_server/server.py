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
from powerbi import dax_financeiro, dax_kpis, dax_lib  # noqa: E402
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


# --------------------------------------------------------------------------- #
# Relatórios financeiros (DRE, Balanço, Fluxo de Caixa)
# --------------------------------------------------------------------------- #
def _formatar_relatorio(df: pd.DataFrame, titulo: str, query: str) -> str:
    """Formata um relatório financeiro por completo (sem truncar).

    Diferente de :func:`_formatar_resultado`, aqui não há truncamento: os
    relatórios têm tamanho fixo e pequeno (dezenas de linhas), e cortá-los
    inutilizaria a leitura. Os valores saem no padrão brasileiro.

    Args:
        df: Resultado da consulta, com Ordem/Bloco/Linha/Tipo/Valor.
        titulo: Cabeçalho do relatório (inclui período e filtros).
        query: A consulta executada (para auditoria).

    Returns:
        O relatório em texto, agrupado por bloco.
    """
    if df.empty:
        return f"{titulo}\n\n(nenhuma linha retornada)"

    df = df.rename(columns=lambda c: c.strip("[]"))
    df = df.sort_values("Ordem")

    def moeda(valor: float) -> str:
        texto = f"{abs(valor):,.2f}".replace(",", "@").replace(".", ",")
        texto = texto.replace("@", ".")
        return f"({texto})" if valor < 0 else texto

    linhas: list[str] = [titulo, ""]
    bloco_atual = None
    for _, r in df.iterrows():
        if r["Bloco"] != bloco_atual:
            bloco_atual = r["Bloco"]
            linhas.append(f"\n**{bloco_atual}**")
        tipo = str(r["Tipo"])
        rotulo = str(r["Linha"])
        valor = float(r["Valor"] or 0)
        if tipo == "INDICADOR":
            texto = f"{valor * 100:,.1f}%".replace(",", ".")
        else:
            texto = moeda(valor)
        marcador = "**" if tipo in ("SUBTOTAL", "CHECK") else ""
        linhas.append(f"  {marcador}{rotulo}{marcador}: {texto}")

    linhas.append("\n— Query executada (auditoria) —")
    linhas.append(query.strip())
    return "\n".join(linhas)


def _titulo(nome: str, periodo: str, empresa: str | None, modo: str = "mensal") -> str:
    """Monta o cabeçalho do relatório com período, modo e filtro aplicado."""
    rotulo_modo = {
        "mensal": periodo,
        "trimestral": f"trimestre encerrado em {periodo}",
        "anual": f"ano encerrado em {periodo}",
    }.get(modo, periodo)
    sufixo = f"EMPRESA={empresa}" if empresa else "consolidado (todas as empresas)"
    return f"# {nome} — período {rotulo_modo} | {sufixo}"


def _executar_relatorio(
    nome: str,
    query: str,
    periodo: str,
    empresa: str | None,
    dataset: str | None,
    modo: str = "mensal",
) -> str:
    """Executa e formata um relatório financeiro, traduzindo erros."""
    try:
        cliente = _obter_cliente()
        df = cliente.execute_dax(query, dataset_id=dataset)
    except ErroPowerBI as exc:
        return f"❌ Erro ao gerar {nome}:\n{exc}"
    return _formatar_relatorio(df, _titulo(nome, periodo, empresa, modo), query)


@mcp.tool()
def relatorio_dre(
    periodo: str,
    empresa: str | None = None,
    modo: str = "mensal",
    dataset: str | None = None,
) -> str:
    """Gera a DRE completa de um período (estrutura oficial da empresa).

    Os subtotais (Receita Líquida, Lucro Bruto, EBITDA, EBIT, LAIR, Lucro
    Líquido) e as margens já vêm calculados.

    Escolha do modo (evita somar meses manualmente/em várias chamadas):

    * ``"mensal"`` (padrão) — só o mês de ``periodo``.
    * ``"trimestral"`` — soma os 3 meses do trimestre encerrado em ``periodo``.
      Exige período 03, 06, 09 ou 12 (ex.: "03/2026" = jan+fev+mar/2026).
    * ``"anual"`` — soma janeiro a dezembro do ano de ``periodo``. Exige
      período 12 (ex.: "12/2025" = ano inteiro de 2025).

    COMO LER OS SINAIS — importante para não inverter a interpretação:
    custos, despesas e deduções aparecem como **número positivo** nas linhas de
    detalhe (ex.: "Custo de Veículos Novos: 16.777.905,30"), seguindo o padrão
    de relatório contábil da empresa, mas **subtraem** nos subtotais. Portanto:

    * Uma linha de custo/despesa alta e positiva **reduz** o lucro.
    * Só os subtotais e indicadores trazem o sinal econômico real — um LAIR ou
      Lucro Líquido negativo significa prejuízo.
    * Nunca some linhas de detalhe direto para "conferir" um subtotal: as
      subtrativas entrariam com o sinal trocado. Use o subtotal já calculado.

    Args:
        periodo: Período no formato "MM/AAAA" (ex.: "12/2024").
        empresa: Filtro opcional por EMPRESA (ex.: "KOBE"). None = consolidado.
        modo: "mensal" (padrão), "trimestral" ou "anual".
        dataset: Apelido ou GUID do dataset. ``None`` = padrão.

    Returns:
        A DRE formatada por blocos, com a query executada para auditoria.
    """
    try:
        query = dax_financeiro.dre(periodo, empresa=empresa, modo=modo)
    except ValueError as exc:
        return f"❌ {exc}"
    return _executar_relatorio("DRE", query, periodo, empresa, dataset, modo)


@mcp.tool()
def relatorio_balanco(
    periodo: str,
    empresa: str | None = None,
    dataset: str | None = None,
) -> str:
    """Gera o Balanço Patrimonial acumulado até o período informado.

    O saldo acumula desde 01/2024 (início do modelo, já com o saldo de
    abertura) até o período pedido. Inclui a linha de CHECK
    ``Ativo - (Passivo + PL)``, que deve ser zero.

    ATENÇÃO: na base atual a apuração de resultado é lançada **por trimestre**,
    então o CHECK só fecha em 03, 06, 09 e 12. Em outros meses o CHECK traz o
    resultado ainda não apurado — reporte a divergência, não a esconda.

    Args:
        periodo: Período no formato "MM/AAAA" (ex.: "12/2024").
        empresa: Filtro opcional por EMPRESA.
        dataset: Apelido ou GUID do dataset. ``None`` = padrão.

    Returns:
        O Balanço formatado por blocos, com o CHECK e a query executada.
    """
    try:
        query = dax_financeiro.balanco(periodo, empresa=empresa)
    except ValueError as exc:
        return f"❌ {exc}"
    return _executar_relatorio("Balanço Patrimonial", query, periodo, empresa, dataset)


@mcp.tool()
def relatorio_fluxo_caixa(
    periodo: str,
    empresa: str | None = None,
    modo: str = "mensal",
    dataset: str | None = None,
) -> str:
    """Gera o Fluxo de Caixa (método indireto) do período.

    Combina o resultado da DRE, variações de saldo do Balanço e somas por
    NATUREZA. Traz o CHECK final comparando o Saldo de Caixa Final com a linha
    DISPONIBILIDADES do Balanço.

    Escolha do modo:

    * ``"mensal"`` — mês contra mês anterior. Aceita qualquer período.
    * ``"trimestral"`` — fim de trimestre contra fim de trimestre (ex.: 12/2024
      vs 09/2024), somando os três meses. Exige período 03, 06, 09 ou 12.

    CHECK sem tampão: a Variação Líquida é a soma honesta das três seções e o
    Saldo Final = Saldo Inicial + Variação Líquida. O CHECK compara esse saldo
    com a variação real de caixa do Balanço — **nunca é forçado a zero e não há
    ajuste de conciliação**. Na maioria dos meses fecha (≈ 0); em alguns meses
    fora de fim de trimestre pode sobrar um resíduo real (a base apura o
    resultado por trimestre). **Sempre reporte o valor do CHECK — nunca o
    esconda nem tente compensá-lo.**

    Args:
        periodo: Período no formato "MM/AAAA" (ex.: "12/2024").
        empresa: Filtro opcional por EMPRESA.
        modo: "mensal" (padrão) ou "trimestral".
        dataset: Apelido ou GUID do dataset. ``None`` = padrão.

    Returns:
        O Fluxo de Caixa formatado por seções, com o CHECK e a query executada.
    """
    try:
        query = dax_financeiro.fluxo_caixa(periodo, empresa=empresa, modo=modo)
    except ValueError as exc:
        return f"❌ {exc}"
    nome = f"Fluxo de Caixa ({modo})"
    return _executar_relatorio(nome, query, periodo, empresa, dataset)


@mcp.tool()
def periodos_financeiros(dataset: str | None = None) -> str:
    """Lista os períodos disponíveis na base contábil, em ordem cronológica.

    Útil antes de pedir um relatório, para saber o intervalo coberto e evitar
    pedir um período inexistente.

    Args:
        dataset: Apelido ou GUID do dataset. ``None`` = padrão.

    Returns:
        Os períodos disponíveis (formato MM/AAAA) e a chave AAAAMM.
    """
    query = dax_financeiro.periodos_disponiveis()
    try:
        cliente = _obter_cliente()
        df = cliente.execute_dax(query, dataset_id=dataset)
    except ErroPowerBI as exc:
        return f"❌ Erro ao listar períodos:\n{exc}"
    return _formatar_resultado(df, query, 100)


def _formatar_indicadores(
    df: pd.DataFrame, titulo: str, query: str
) -> str:
    """Formata os KPIs agrupados, com explicação e o 'melhor se…' de cada um."""
    if df.empty:
        return f"{titulo}\n\n(nenhuma linha retornada)"

    df = df.rename(columns=lambda c: c.strip("[]")).sort_values("Ordem")
    meta = dax_kpis.metadados()

    def formatar_valor(unidade: str, valor: float) -> str:
        if valor is None:
            return "–"
        v = float(valor)
        if unidade == "%":
            return f"{v * 100:,.1f}%".replace(",", ".")
        if unidade == "x":
            return f"{v:,.2f}x".replace(".", ",")
        if unidade == "dias":
            return f"{v:,.0f} dias".replace(",", ".")
        return f"{v:,.2f}".replace(".", ",")

    linhas: list[str] = [titulo, ""]
    grupo_atual = None
    for _, r in df.iterrows():
        if r["Grupo"] != grupo_atual:
            grupo_atual = r["Grupo"]
            linhas.append(f"\n## {grupo_atual}")
        nome = str(r["Indicador"])
        info = meta.get(nome, {})
        valor = formatar_valor(str(r["Unidade"]), r["Valor"])
        linhas.append(f"- **{nome}: {valor}**")
        if info:
            linhas.append(
                f"  {info['explicacao']} · _melhor: {info['melhor_se']}_"
            )

    linhas.append("\n— Query executada (auditoria) —")
    linhas.append(query.strip())
    return "\n".join(linhas)


@mcp.tool()
def relatorio_indicadores(
    periodo: str,
    empresa: str | None = None,
    modo: str = "mensal",
    dataset: str | None = None,
) -> str:
    """Gera os KPIs de análise financeira (rentabilidade, liquidez, endividamento,
    eficiência) de um período, com explicação e benchmark de cada indicador.

    Reaproveita os componentes da DRE e do Balanço — não recalcula nada. Cada
    indicador vem com uma explicação curta e um "melhor se…" (direção ideal).

    Convenções fixas (definidas com o gestor): EBITDA anualizado no múltiplo de
    dívida; indicadores em dias usam saldo final + 30 dias/mês; Custo de Pessoal
    = Folha + Gastos Diversos com Funcionários; Margem EBIT sai como EBIT/RL e
    também EBIT/Lucro Bruto.

    Args:
        periodo: Período no formato "MM/AAAA" (ex.: "03/2026").
        empresa: Filtro opcional por EMPRESA. None = consolidado.
        modo: "mensal" (padrão), "trimestral" ou "anual".
        dataset: Apelido ou GUID do dataset. ``None`` = padrão.

    Returns:
        Os indicadores agrupados, com valor, explicação e benchmark, e a query.
    """
    try:
        query = dax_kpis.indicadores(periodo, empresa=empresa, modo=modo)
    except ValueError as exc:
        return f"❌ {exc}"
    try:
        cliente = _obter_cliente()
        df = cliente.execute_dax(query, dataset_id=dataset)
    except ErroPowerBI as exc:
        return f"❌ Erro ao gerar os indicadores:\n{exc}"
    titulo = _titulo("Indicadores de Análise", periodo, empresa, modo)
    return _formatar_indicadores(df, titulo, query)


def main() -> None:
    """Inicia o servidor MCP no transporte stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
