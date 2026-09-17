"""Servidor MCP local que expõe as ferramentas do analista-bi ao Claude.

Transporte: stdio. Ferramentas expostas (todas SOMENTE LEITURA):

* ``consultar_dax``       — executa DAX arbitrário e devolve até N linhas.
* ``buscar_item``         — atalho de busca textual (estilo "compramos cloro?").
* ``esquema_modelo``      — devolve o dicionário de dados do modelo.
* ``resumo_kpis``         — atalho para agregações com medidas oficiais.
* ``consultar_duckdb``    — consulta SELECT no banco local (complemento).
* ``relatorio_auditoria`` — regras de auditoria de lançamentos de caixa (R1–R14).
* ``relatorio_coaf``      — clientes acima do limiar de recebimento em espécie.
* ``historico_coaf``      — histórico permanente de clientes já detectados.
* ``relatorio_conciliacao_caixa`` — saldo de caixa financeiro x contábil, por empresa.

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

from config.settings import RAIZ_PROJETO, ErroConfiguracao, carregar_configuracao  # noqa: E402
from local_data.ingest import ErroDuckDB, consultar_select, listar_tabelas  # noqa: E402
from powerbi import dax_auditoria, dax_coaf, dax_financeiro, dax_kpis, dax_lib  # noqa: E402
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


def _titulo(
    nome: str,
    periodo: str,
    empresa: str | None,
    modo: str = "mensal",
    visao: str | None = None,
) -> str:
    """Monta o cabeçalho do relatório com período, modo e filtros aplicados."""
    rotulo_modo = {
        "mensal": periodo,
        "trimestral": f"trimestre encerrado em {periodo}",
        "anual": f"ano encerrado em {periodo}",
    }.get(modo, periodo)
    sufixo = f"EMPRESA={empresa}" if empresa else "consolidado (todas as empresas)"
    # A visão só existe na DRE (TIPO_LANÇAMENTO) — nos outros relatórios sai None.
    rotulo_visao = {
        "contabil": "visão CONTÁBIL (só TIPO_LANÇAMENTO=CONTÁBIL)",
        "gerencial": "visão GERENCIAL (todos os lançamentos)",
    }.get(str(visao).strip().lower()) if visao else None
    partes = [f"período {rotulo_modo}", sufixo]
    if rotulo_visao:
        partes.append(rotulo_visao)
    return f"# {nome} — " + " | ".join(partes)


def _executar_relatorio(
    nome: str,
    query: str,
    periodo: str,
    empresa: str | None,
    dataset: str | None,
    modo: str = "mensal",
    visao: str | None = None,
) -> str:
    """Executa e formata um relatório financeiro, traduzindo erros."""
    try:
        cliente = _obter_cliente()
        df = cliente.execute_dax(query, dataset_id=dataset)
    except ErroPowerBI as exc:
        return f"❌ Erro ao gerar {nome}:\n{exc}"
    return _formatar_relatorio(df, _titulo(nome, periodo, empresa, modo, visao), query)


@mcp.tool()
def relatorio_dre(
    periodo: str,
    empresa: str | None = None,
    modo: str = "mensal",
    visao: str = "gerencial",
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

    VISÃO CONTÁBIL x GERENCIAL (coluna TIPO_LANÇAMENTO) — exclusiva da DRE; o
    Balanço e o Fluxo de Caixa não têm esse recorte:

    * ``"gerencial"`` (padrão) — traz **todos** os lançamentos, sem filtro
      (contábeis + extracontábeis).
    * ``"contabil"`` — traz **apenas** os lançamentos com
      TIPO_LANÇAMENTO = "CONTÁBIL".

    Ao reportar, diga sempre qual visão foi usada: o mesmo período fecha em
    resultados diferentes nas duas.

    Args:
        periodo: Período no formato "MM/AAAA" (ex.: "12/2024").
        empresa: Filtro opcional por EMPRESA (ex.: "KOBE"). None = consolidado.
        modo: "mensal" (padrão), "trimestral" ou "anual".
        visao: "gerencial" (padrão, todos os lançamentos) ou "contabil"
            (só os lançamentos contábeis).
        dataset: Apelido ou GUID do dataset. ``None`` = padrão.

    Returns:
        A DRE formatada por blocos, com a query executada para auditoria.
    """
    try:
        query = dax_financeiro.dre(periodo, empresa=empresa, modo=modo, visao=visao)
    except ValueError as exc:
        return f"❌ {exc}"
    return _executar_relatorio("DRE", query, periodo, empresa, dataset, modo, visao)


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

    Convenções fixas (definidas com o gestor): Dívida Líquida / EBITDA usa o
    EBITDA do próprio período (não anualizado); indicadores em dias usam saldo
    final + 30 dias/mês; giro de peças divide por custo de peças + custo da
    oficina; Custo de Pessoal = Folha + Gastos Diversos com Funcionários; Margem
    EBIT sai como EBIT/RL e também EBIT/Lucro Bruto.

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


# --------------------------------------------------------------------------- #
# Auditoria de lançamentos de caixa (R1–R14)
# --------------------------------------------------------------------------- #
_SELO_SEVERIDADE = {"alta": "🔴", "media": "🟡", "baixa": "⚪", "informativo": "ℹ️"}
_ORDEM_SEVERIDADE = {"alta": 0, "media": 1, "baixa": 2, "informativo": 3}
#: Colunas mostradas por linha de exceção, na ordem, quando presentes no resultado.
_COLUNAS_RESUMO = (
    "REVENDA", "CAIXA", "DATA", "USUARIO", "NOME_USUARIO", "CLIENTE", "VALOR",
    "ORIGEM", "SomaR", "SomaP", "N", "Total", "Descasamento", "Faltando",
    "Distintos", "Densidade", "Percentual", "SaldoAcumulado", "Saidas", "Entradas", "TotalDia",
)
#: Máximo de linhas de exceção detalhadas por regra no texto (o resto só é contado).
_MAX_LINHAS_DETALHE = 20


def _normalizar_coluna(nome: str) -> str:
    """Extrai o nome "puro" de uma coluna DAX devolvida pela API.

    As regras de auditoria devolvem nomes em dois formatos, conforme o tipo
    de consulta: ``"CAIXAS[REVENDA]"`` (saída de ``SUMMARIZECOLUMNS``,
    coluna qualificada) ou ``"[VALOR]"`` (saída de ``SELECTCOLUMNS``, alias).
    Um simples ``.strip("[]")`` só remove colchete nas pontas — em
    ``"CAIXAS[REVENDA]"`` sobra ``"CAIXAS[REVENDA"``, sem casar com nada.
    """
    texto = str(nome)
    if "[" in texto and texto.endswith("]"):
        return texto[texto.index("[") + 1 : -1]
    return texto.strip("[]")


def _formatar_linha_excecao(row: pd.Series) -> str:
    """Formata uma linha de exceção como ``chave=valor · chave=valor``."""
    partes = []
    for col in _COLUNAS_RESUMO:
        if col not in row.index or pd.isna(row[col]):
            continue
        valor = row[col]
        if isinstance(valor, float):
            valor = f"{valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
        partes.append(f"{col}={valor}")
    return "- " + " · ".join(partes)


def _formatar_auditoria(
    resultados: dict[str, tuple[pd.DataFrame, str]],
    erros: dict[str, str],
    titulo: str,
    usuario_revisor: str | None,
) -> str:
    """Consolida os resultados de todas as regras num único relatório.

    Args:
        resultados: Mapa ``{id_regra: (dataframe, query_executada)}``.
        erros: Mapa ``{id_regra: mensagem_de_erro}`` das regras que falharam.
        titulo: Cabeçalho do relatório.
        usuario_revisor: Se informado, linhas de qualquer regra cujo
            ``USUARIO`` bata com este nome também entram no bloco de revisão
            independente (além das linhas de R12, que entram sempre).

    Returns:
        O relatório completo em Markdown.
    """
    linhas: list[str] = [titulo, ""]
    total_excecoes = 0
    revisao_independente: list[str] = []

    ordem = sorted(
        resultados, key=lambda r: (_ORDEM_SEVERIDADE.get(dax_auditoria.REGRAS[r].severidade, 9), r)
    )
    for rid in ordem:
        df, query = resultados[rid]
        regra = dax_auditoria.REGRAS[rid]
        df = df.rename(columns=_normalizar_coluna)
        n = len(df)
        eh_excecao = regra.severidade != "informativo"
        if eh_excecao:
            total_excecoes += n

        selo = _SELO_SEVERIDADE.get(regra.severidade, "•")
        linhas.append(f"\n## {selo} {rid} — {regra.titulo} ({n} linha{'s' if n != 1 else ''})")
        if df.empty:
            linhas.append("_Nenhuma exceção encontrada neste recorte._")
            continue
        for _, row in df.head(_MAX_LINHAS_DETALHE).iterrows():
            linhas.append(_formatar_linha_excecao(row))
        if n > _MAX_LINHAS_DETALHE:
            linhas.append(f"  _...e mais {n - _MAX_LINHAS_DETALHE} linha(s) — refine o filtro para ver o restante._")

        if rid == "R12" and n > 0:
            revisao_independente.append(
                f"**{rid}** ({n}): mesmo usuário lançou e estornou — nunca autorrevisar."
            )
        col_usuario = "USUARIO" if "USUARIO" in df.columns else "NOME_USUARIO" if "NOME_USUARIO" in df.columns else None
        if usuario_revisor and col_usuario:
            marcadas = df[df[col_usuario].astype(str) == str(usuario_revisor)]
            if len(marcadas):
                revisao_independente.append(
                    f"**{rid}** ({len(marcadas)}): linha(s) do usuário informado ({usuario_revisor})."
                )

    if erros:
        linhas.append("\n## ⚠️ Regras que falharam ao executar")
        for rid, msg in erros.items():
            linhas.append(f"- **{rid}**: {msg}")

    if revisao_independente:
        bloco = ["\n## 🔒 Requer revisão independente", *[f"- {x}" for x in revisao_independente]]
        linhas[2:2] = bloco  # logo após o título/linha em branco

    linhas.append(f"\n---\n**Total de exceções (excl. informativas): {total_excecoes}**")
    linhas.append(
        "\nToda exceção é hipótese a investigar, não acusação — confirme com a origem do "
        "lançamento antes de qualquer conclusão. Consulte as queries com `consultar_dax` "
        "usando o mesmo filtro para auditar este próprio relatório."
    )
    return "\n".join(linhas)


@mcp.tool()
def relatorio_auditoria(
    regras: list[str] | None = None,
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    usuario_revisor: str | None = None,
    dataset: str | None = None,
) -> str:
    """Roda as regras de auditoria de lançamentos de caixa (R1–R14) e lista exceções.

    Cada regra é uma consulta DAX independente sobre a tabela ``CAIXAS`` — ver
    ``dictionary/regras_negocio.md`` (seção "Auditoria de Lançamentos de
    Caixa") para o catálogo completo, os thresholds e os achados de
    referência usados para validar cada uma. Todas as regras já aplicam o
    escopo padrão (exclui caixas 9/99/4/8/14 e as 28 linhas de saldo
    inicial) — não é preciso (nem deve) repetir esse filtro na pergunta.

    R6 é informativa (cobertura de título por revenda) — não conta como
    exceção nem entra no total. R12 (mesmo usuário lança e estorna) sempre
    aparece também no bloco "Requer revisão independente", que agrega ainda
    qualquer outra exceção do ``usuario_revisor`` informado — quem roda esta
    auditoria nunca deve ser o único a revisar as próprias linhas.

    Args:
        regras: Lista de IDs a rodar (ex.: ``["R1","R12"]``). ``None`` roda
            todas as 14.
        empresa: Filtro opcional por EMPRESA. ``None`` = consolidado.
        periodo: Período "MM/AAAA". ``None`` = toda a base (recomendado na
            primeira execução — várias regras comparam com o histórico
            completo). Ignorado por R9 e R10, que sempre olham a base toda
            ou uma janela própria.
        modo: "mensal" (padrão), "trimestral" ou "anual" — só usado se
            ``periodo`` for informado.
        usuario_revisor: Nome (``NOME_USUARIO``) de quem está rodando/vai
            revisar este relatório. Linhas desse usuário em qualquer regra
            são realçadas em "Requer revisão independente".
        dataset: Apelido ou GUID do dataset. ``None`` = padrão (``controlador``).

    Returns:
        O relatório consolidado, agrupado por regra em ordem de severidade,
        com o bloco de revisão independente e o total de exceções.
    """
    alvo = regras or list(dax_auditoria.REGRAS.keys())
    invalidas = [r for r in alvo if r not in dax_auditoria.REGRAS]
    if invalidas:
        return (
            f"❌ Regra(s) inválida(s): {', '.join(invalidas)}. "
            f"Use uma ou mais de: {', '.join(dax_auditoria.REGRAS)}."
        )

    try:
        cliente = _obter_cliente()
    except Exception as exc:  # noqa: BLE001 — erro de configuração/autenticação
        return f"❌ Erro ao preparar a auditoria:\n{exc}"

    resultados: dict[str, tuple[pd.DataFrame, str]] = {}
    erros: dict[str, str] = {}
    for rid in alvo:
        regra = dax_auditoria.REGRAS[rid]
        kwargs: dict[str, object] = {"empresa": empresa}
        if regra.aceita_periodo:
            kwargs["periodo"] = periodo
            kwargs["modo"] = modo
        try:
            query = regra.construtor(**kwargs)
        except ValueError as exc:
            erros[rid] = str(exc)
            continue
        try:
            df = cliente.execute_dax(query, dataset_id=dataset)
        except ErroPowerBI as exc:
            erros[rid] = str(exc)
            continue
        resultados[rid] = (df, query)

    if not resultados and erros:
        detalhe = "\n".join(f"- {r}: {m}" for r, m in erros.items())
        return f"❌ Todas as regras falharam:\n{detalhe}"

    titulo = _titulo("Auditoria de Lançamentos de Caixa", periodo or "toda a base", empresa, modo)
    return _formatar_auditoria(resultados, erros, titulo, usuario_revisor)


@mcp.tool()
def relatorio_coaf(meses: int | None = None, limiar: float | None = None) -> str:
    """Clientes que atingiram o limiar de recebimento em espécie (COAF).

    Consulta os lançamentos de caixa ao vivo e aplica a regra do COAF: soma o
    que cada cliente pagou em espécie em uma janela MÓVEL de 6 meses e lista
    quem chegou a R$ 30 mil. É a mesma lógica do job agendado
    ``analysis/coaf_especie.py``, mas sob demanda e sem gravar nada — nem
    histórico, nem PDF, nem e-mail.

    Atenção: os valores NÃO são medida oficial. O dataset
    ``lancamentos_financeiros`` não tem medidas; tudo é calculado a partir de
    ``CAIXAS[VALOR]``.

    Args:
        meses: Meses de histórico a consultar. ``None`` usa ``config/coaf.yaml``.
        limiar: Valor que dispara o alerta. ``None`` usa ``config/coaf.yaml``.

    Returns:
        Relatório em Markdown com os clientes acima do limiar.
    """
    from datetime import date

    from analysis import coaf_especie as coaf

    try:
        cfg = coaf.carregar_config_coaf()
    except Exception as exc:  # configuração ausente ou malformada
        return f"❌ Erro ao ler config/coaf.yaml: {exc}"

    if meses is not None:
        cfg["meses_consulta"] = int(meses)
    if limiar is not None:
        cfg["limiar_reais"] = float(limiar)

    hoje = date.today()
    inicio = coaf.subtrair_meses(hoje, int(cfg["meses_consulta"]))
    exc_origem = cfg["exclusoes_origem"]
    query = dax_coaf.recebimentos_especie(
        inicio, hoje, exc_origem["padroes"], exc_origem["exatas"],
        cfg["caixas_excluidos"]["global"],
    )
    try:
        bruto = _obter_cliente().execute_dax(query, dataset_id=coaf.DATASET_PADRAO)
    except ErroPowerBI as exc:
        return f"❌ Erro ao consultar os lançamentos de caixa: {exc}"

    df = coaf.preparar_lancamentos(bruto, cfg, hoje)
    casos = coaf.detectar(df, cfg)
    casos = coaf.filtrar_clientes_excluidos(casos, cfg)
    return coaf.montar_relatorio_execucao(casos, [], cfg, inicio, hoje, len(df), [])


@mcp.tool()
def historico_coaf(
    cliente: str | None = None,
    desde: str | None = None,
    apenas_notificados: bool | None = None,
) -> str:
    """Histórico permanente dos clientes já detectados pelo monitoramento COAF.

    Lê o banco local (``coaf_deteccao``), que é append-only: um cliente
    notificado sai da fila de e-mail mas **continua aqui**. Responde perguntas
    como "esse cliente já apareceu antes?" e "o que surgiu desde março?".

    Não consulta o Power BI — é histórico gravado, não situação ao vivo. Para a
    situação atual use ``relatorio_coaf``.

    Args:
        cliente: Filtra por trecho do nome (case-insensitive).
        desde: Só detecções a partir desta data (``"AAAA-MM-DD"``).
        apenas_notificados: ``True`` só quem já recebeu e-mail; ``False`` só
            quem ainda não recebeu; ``None`` traz todos.

    Returns:
        Relatório em Markdown do histórico filtrado.
    """
    from analysis import coaf_especie as coaf
    from local_data import coaf_estado

    try:
        cfg = coaf.carregar_config_coaf()
        escopo = str(cfg.get("escopo_alerta", "grupo")).lower()
        con = coaf_estado.abrir(somente_leitura=True)
    except Exception as exc:
        return (
            f"❌ Não foi possível abrir o histórico do COAF: {exc}"
            "\n\n"
            "Se o banco ainda não existe, rode o job uma vez: "
            "`.venv/Scripts/python.exe analysis/coaf_especie.py`"
        )
    try:
        hist = coaf_estado.carregar_historico(con, escopo)
    finally:
        con.close()

    if hist.empty:
        return "Ainda não há detecções registradas no histórico do COAF."

    if cliente:
        hist = hist[hist["nome_cliente"].str.contains(cliente, case=False, na=False)]
    if desde:
        try:
            corte = pd.to_datetime(desde)
        except (ValueError, TypeError):
            return f"❌ Data inválida em `desde`: {desde!r}. Use o formato AAAA-MM-DD."
        hist = hist[pd.to_datetime(hist["primeira_deteccao_em"]) >= corte]
    if apenas_notificados is True:
        hist = hist[hist["notificado_em"].notna()]
    elif apenas_notificados is False:
        hist = hist[hist["notificado_em"].isna()]

    if hist.empty:
        return "Nenhum registro no histórico do COAF atende aos filtros informados."
    return coaf.montar_relatorio_historico(hist)


@mcp.tool()
def relatorio_conciliacao_caixa(ate: str, empresa: str | None = None) -> str:
    """Concilia o saldo de CAIXA do financeiro com o da contabilidade, por empresa.

    Cruza o acumulado do livro-caixa (``CAIXAS[VALOR]``, dataset
    ``controlador``) com o acumulado das contas contábeis de CAIXA GERAL
    (``lancamentos[VALOR_AJUSTADO]``, dataset padrão), mês a mês, e aponta em
    que mês e em que empresa os dois deixaram de bater.

    Três coisas a saber antes de ler o resultado:

    * **A chave é EMPRESA, nunca REVENDA.** Transferência de saldo entre caixas
      de revendas diferentes não tem lançamento contábil; por revenda os dois
      lados nunca fecham, por empresa elas se anulam.
    * **A granularidade é MENSAL.** A tabela contábil não tem coluna de data,
      só ``PERIODO`` (``MM/AAAA``) — não existe saldo contábil diário. O
      financeiro é cortado no último dia do mês.
    * **Diferença de abertura ≠ divergência do mês.** A primeira é o saldo
      inicial que a planilha não trouxe em 01/01/2025 e se arrasta constante;
      a segunda é movimento realmente descasado. O relatório separa as duas.

    Atenção: os valores NÃO são medida oficial — nenhum dos dois modelos tem
    medidas cadastradas.

    Args:
        ate: Mês de corte no formato ``"MM/AAAA"`` (ex.: ``"07/2026"``).
        empresa: Concilia só uma empresa. Aceita o nome do financeiro
            (``"ROYAL ENFIELD"``) ou do contábil (``"ROYAL"``). ``None`` =
            todas as empresas.

    Returns:
        O relatório de conciliação em Markdown.
    """
    from analysis import conciliacao_caixa as conc

    try:
        resultado = conc.executar(ate=ate, empresa=empresa, cliente=_obter_cliente())
    except (ValueError, ErroConfiguracao) as exc:
        return f"❌ {exc}"
    except ErroPowerBI as exc:
        return f"❌ Erro ao consultar o Power BI:\n{exc}"
    return conc.montar_relatorio(resultado)


def main() -> None:
    """Inicia o servidor MCP no transporte stdio."""
    mcp.run()


if __name__ == "__main__":
    main()
