"""Consultas DAX de auditoria de lançamentos de caixa.

Dataset ``controlador`` (apelido em ``config/datasets.yaml`` para o dataset
Power BI ``lancamentos_financeiros``), tabela ``CAIXAS``. Ver
``dictionary/regras_negocio.md`` — seção "Auditoria de Lançamentos de Caixa" —
para o catálogo de regras (R1–R14), os achados de referência usados para
validar este módulo e a justificativa de cada threshold. Este módulo **é a
implementação** dessa seção; se os dois divergirem, corrija aqui e lá juntos.

Cada função devolve **a string DAX pronta** — nada é executado aqui. A
execução e a formatação do resultado ficam a cargo de
:class:`~powerbi.client.PowerBIClient` e do servidor MCP
(``mcp_server/server.py``), mesma separação de responsabilidade usada em
``dax_financeiro.py``.

Particularidades do modelo real (verificadas contra os dados, não presumidas)
-----------------------------------------------------------------------------

1. **Duas condições universais, obrigatórias em toda regra:**
   :func:`_filtro_caixas_operacionais` (exclui os caixas de concentração 9,
   99, 4 e, no grupo Multicar Mits, também 8 e 14) e :func:`_excluir_abertura`
   (remove as 28 linhas de ``"SALDO INICIAL DA PLANILHA"`` de 01/01/2025, que
   não têm ``NOME_USUARIO``/``ORIGEM``/``TITULO`` por construção). Ambas são
   combinadas por :func:`_filtro_escopo`, a única função que as demais devem
   chamar — nunca reescrever a condição.
2. **O par que se cancela é identificado por CLIENTE, não por TITULO.**
   ``CAIXAS[TITULO]`` é o número sequencial do lançamento no caixa (ex.:
   ``184786``), não o título financeiro externo mencionado em ``HISTORICO``
   (ex.: "Titulo(CR)27128-01"). Um recebimento e seu estorno têm ``TITULO``
   diferentes; a chave de pareamento real é ``REVENDA`` + ``CLIENTE`` + a
   mesma ``DATA``, com os valores se cancelando (:func:`regra_r1_estorno_mesmo_dia`).
3. **A sentinela de origem em branco é o texto ``" -"``** (traço com espaço à
   esquerda), não uma célula vazia — comparar com igualdade de texto, não com
   ``ISBLANK``.
4. **``TITULO`` é um ID global compartilhado, não um contador por revenda.**
   Testado contra os dados reais: toda revenda cai no mesmo intervalo
   ``1–186758``, com densidade de 0,05% a 1,5% — é ID de um sistema maior que
   ``CAIXAS`` (Linx Apollo inteiro). A hipótese original de "lacuna de
   sequência por revenda" (R6) não se sustentou e foi rebaixada a
   diagnóstico informativo — ver :func:`regra_r6_cobertura_titulo`. Também é
   texto; nem toda linha tem valor numérico (as 28 de abertura, por exemplo),
   por isso sempre filtrado por ``_filtro_escopo`` antes de converter com
   ``VALUE``.
5. **``DATA`` é um tipo Date nativo** (diferente do modelo contábil, onde
   ``PERIODO`` é texto ``MM/AAAA``) — o recorte de período usa ``DATE(...)``
   diretamente, sem chave ``AAAAMM``.
6. **Correspondência de nome em R14 não normaliza acento.** ``SEARCH`` do DAX
   é case-insensitive mas não remove diacríticos — nomes com acento podem
   escapar da regra. Documentado como limitação conhecida.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta

from .dax_lib import escapar_texto

# --------------------------------------------------------------------------- #
# Modelo: tabela e colunas
# --------------------------------------------------------------------------- #
TABELA = "CAIXAS"

COL_REVENDA = "REVENDA"
COL_CAIXA = "CAIXA"
COL_VALOR = "VALOR"
COL_CLIENTE = "CLIENTE"
COL_TITULO = "TITULO"
COL_HISTORICO = "HISTORICO"
COL_ORIGEM = "ORIGEM"
COL_DATA = "DATA"
COL_PR = "PAGAR_RECEBER"
COL_EMPRESA = "EMPRESA"
COL_NOME_USUARIO = "NOME_USUARIO"

#: Códigos de CAIXA que não representam saldo real em nenhuma revenda
#: (contas de concentração/transferência). Ver regras_negocio.md.
CAIXAS_EXCLUIDOS_GLOBAL = ("9", "99", "4")
#: No grupo Multicar Mits, esses dois códigos também são excluídos.
REVENDAS_MITS = ("MULTICAR MITS MATRIZ", "MULTICAR MITS VV")
CAIXAS_EXCLUIDOS_MITS = ("8", "14")

#: Sentinela de origem não classificada usada nos lançamentos de estorno.
ORIGEM_EM_BRANCO = " -"
#: Substring (case-insensitive) que identifica um estorno em HISTORICO.
MARCADOR_ESTORNO = "ESTORNO"
#: Substring que identifica transferência interna em ORIGEM.
MARCADOR_TRANSFERENCIA = "TRANSF"
#: Substring que identifica adiantamento em ORIGEM (usada por R14).
MARCADOR_ADIANTAMENTO = "ADIANTAMENTO"

#: Primeiro dia coberto pela base — lançamentos antes disso são exceção (R9).
DATA_INICIO_BASE = date(2025, 1, 1)

#: Máximo de linhas devolvidas por regra de listagem (protege o contexto).
LIMITE_PADRAO = 100

MODOS_PERIODO = ("mensal", "trimestral", "anual")


# --------------------------------------------------------------------------- #
# Helpers de período (DATA é Date nativo — sem chave AAAAMM)
# --------------------------------------------------------------------------- #
def intervalo_do_modo(periodo: str, modo: str = "mensal") -> tuple[date, date]:
    """Resolve o intervalo fechado de datas coberto pelo modo.

    Args:
        periodo: Período de referência no formato ``"MM/AAAA"``.
        modo: ``"mensal"`` (só o mês), ``"trimestral"`` (os 3 meses do
            trimestre que termina em ``periodo``) ou ``"anual"`` (janeiro a
            dezembro do ano de ``periodo``).

    Returns:
        Tupla ``(data_de, data_ate)``, ambas inclusive.

    Raises:
        ValueError: Se ``periodo`` não estiver em ``MM/AAAA``, ou ``modo`` for
            inválido, ou incompatível com ``periodo`` (trimestral exige fim de
            trimestre; anual exige dezembro — mesma convenção do modelo
            contábil, só que aqui em cima de datas reais).
    """
    texto = str(periodo).strip()
    partes = texto.split("/")
    if len(partes) != 2:
        raise ValueError(
            f"Período inválido: {periodo!r}. Use o formato MM/AAAA (ex.: 12/2024)."
        )
    try:
        mes, ano = int(partes[0]), int(partes[1])
    except ValueError as exc:
        raise ValueError(
            f"Período inválido: {periodo!r}. Use o formato MM/AAAA (ex.: 12/2024)."
        ) from exc
    if not 1 <= mes <= 12:
        raise ValueError(f"Mês inválido em {periodo!r}: deve estar entre 01 e 12.")

    modo_norm = str(modo).strip().lower()
    if modo_norm == "mensal":
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        return date(ano, mes, 1), date(ano, mes, ultimo_dia)
    if modo_norm == "trimestral":
        if mes not in (3, 6, 9, 12):
            raise ValueError(
                f"Período {periodo!r} não é fim de trimestre. No modo "
                "trimestral use 03, 06, 09 ou 12."
            )
        mes_inicio = mes - 2
        ultimo_dia = calendar.monthrange(ano, mes)[1]
        return date(ano, mes_inicio, 1), date(ano, mes, ultimo_dia)
    if modo_norm == "anual":
        if mes != 12:
            raise ValueError(
                f"Período {periodo!r} não é fim de ano. No modo anual use 12 "
                "(dezembro) do ano desejado."
            )
        return date(ano, 1, 1), date(ano, 12, 31)
    raise ValueError(
        f"Modo inválido: {modo!r}. Use um de: {', '.join(MODOS_PERIODO)}."
    )


def _data_dax(d: date) -> str:
    """Literal DAX ``DATE(ano,mes,dia)`` para uma data Python."""
    return f"DATE({d.year},{d.month},{d.day})"


# --------------------------------------------------------------------------- #
# Helpers de montagem DAX
# --------------------------------------------------------------------------- #
def _col(coluna: str) -> str:
    """Referência segura de coluna da tabela CAIXAS."""
    return f"'{TABELA}'[{coluna}]"


def _conjunto_dax(valores: tuple[str, ...]) -> str:
    """Monta um literal de conjunto DAX ``{"a","b",...}`` com escape."""
    itens = ", ".join(f'"{escapar_texto(v)}"' for v in valores)
    return "{" + itens + "}"


def _filtro_caixas_operacionais() -> str:
    """Condição booleana que restringe aos caixas operacionais.

    Fonte única de verdade da exclusão documentada em
    ``dictionary/regras_negocio.md``: caixas 9/99/4 (todas as revendas) e,
    no grupo Multicar Mits, também 8/14. Toda regra de auditoria deve usar
    esta função — nunca reescrever a condição.
    """
    caixas_excl = _conjunto_dax(CAIXAS_EXCLUIDOS_GLOBAL)
    revendas_mits = _conjunto_dax(REVENDAS_MITS)
    caixas_mits = _conjunto_dax(CAIXAS_EXCLUIDOS_MITS)
    return (
        f"NOT({_col(COL_CAIXA)} IN {caixas_excl}) "
        f"&& NOT({_col(COL_REVENDA)} IN {revendas_mits} "
        f"&& {_col(COL_CAIXA)} IN {caixas_mits})"
    )


def _excluir_abertura() -> str:
    """Condição booleana que remove as 28 linhas de saldo inicial.

    As linhas com ``HISTORICO = "SALDO INICIAL DA PLANILHA"`` (01/01/2025)
    não têm ``NOME_USUARIO`` por construção — são as únicas 28 linhas da base
    nessa condição (ver regras_negocio.md). Sem esta exclusão, elas geram
    falso-positivo recorrente em qualquer regra que dependa de usuário,
    origem ou título.
    """
    return f"NOT(ISBLANK({_col(COL_NOME_USUARIO)}))"


def _filtro_escopo() -> str:
    """Combina as duas condições universais de auditoria.

    Toda função ``regra_*`` deste módulo constrói seu ``FILTER`` a partir
    desta função — é o predicado obrigatório do plano de auditoria.
    """
    return f"{_filtro_caixas_operacionais()} && {_excluir_abertura()}"


def _filtro_entidade(empresa: str | None) -> str:
    """Condição opcional de ``EMPRESA``, pronta para concatenar com ``&&``."""
    if not empresa:
        return ""
    return f' && {_col(COL_EMPRESA)} = "{escapar_texto(empresa)}"'


def _filtro_periodo(periodo: str | None, modo: str) -> str:
    """Condição opcional de intervalo de ``DATA``, pronta para concatenar."""
    if not periodo:
        return ""
    data_de, data_ate = intervalo_do_modo(periodo, modo)
    return f" && {_col(COL_DATA)} >= {_data_dax(data_de)} && {_col(COL_DATA)} <= {_data_dax(data_ate)}"


def _base(
    empresa: str | None = None, periodo: str | None = None, modo: str = "mensal"
) -> str:
    """Monta ``FILTER('CAIXAS', <escopo> && <empresa> && <período>)``."""
    condicao = _filtro_escopo() + _filtro_entidade(empresa) + _filtro_periodo(periodo, modo)
    return f"FILTER('{TABELA}', {condicao})"


def _colunas_exame() -> str:
    """Lista de argumentos ``SELECTCOLUMNS`` com as colunas padrão de exceção."""
    pares = [
        ("REVENDA", _col(COL_REVENDA)),
        ("CAIXA", _col(COL_CAIXA)),
        ("DATA", _col(COL_DATA)),
        ("USUARIO", _col(COL_NOME_USUARIO)),
        ("CLIENTE", _col(COL_CLIENTE)),
        ("TITULO", _col(COL_TITULO)),
        ("VALOR", _col(COL_VALOR)),
        ("ORIGEM", _col(COL_ORIGEM)),
        ("HISTORICO", _col(COL_HISTORICO)),
    ]
    return ", ".join(f'"{nome}", {expr}' for nome, expr in pares)


def _listar(
    filtro_extra: str,
    ordenar_por: str = "[VALOR]",
    ordem: str = "ASC",
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Monta ``EVALUATE TOPN(...)`` listando linhas de exceção com colunas padrão.

    Args:
        filtro_extra: Condição booleana adicional da regra (já pronta,
            referenciando colunas de ``CAIXAS`` sem prefixo de ``&&``).
        ordenar_por: Coluna/expressão de ordenação. **Atenção:** como isso é
            aplicado depois do ``SELECTCOLUMNS``, precisa referenciar o
            *alias* (ex.: ``"[VALOR]"``), nunca a coluna qualificada original
            (``'CAIXAS'[VALOR]``) — ela deixa de existir naquele contexto e a
            API devolve 400 sem detalhe útil.
        ordem: ``"ASC"`` ou ``"DESC"``.
        empresa, periodo, modo: Filtros opcionais (ver :func:`_base`).
        limite: Máximo de linhas devolvidas.

    Returns:
        A consulta DAX pronta para ``PowerBIClient.execute_dax``.
    """
    base = _base(empresa, periodo, modo)
    ordem_norm = ordem.upper()
    return (
        "EVALUATE\n"
        f"TOPN(\n    {limite},\n"
        f"    SELECTCOLUMNS(\n"
        f"        FILTER({base}, {filtro_extra}),\n"
        f"        {_colunas_exame()}\n"
        f"    ),\n"
        # TOPN escolhe o CONJUNTO certo de linhas (0 = maiores, 1 = menores —
        # confirmado contra a API, o nome sugere o oposto), mas **não
        # garante a ordem de exibição** do resultado — por isso o ORDER BY
        # explícito abaixo, mesmo padrão de periodos_disponiveis() em
        # dax_financeiro.py.
        f"    {ordenar_por}, {'1' if ordem_norm == 'ASC' else '0'}\n"
        f")\n"
        f"ORDER BY {ordenar_por} {ordem_norm}"
    )


# --------------------------------------------------------------------------- #
# R1 — Recebimento estornado no mesmo dia
# --------------------------------------------------------------------------- #
def regra_r1_estorno_mesmo_dia(
    limiar: float = 5000.0,
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Recebimento e estorno do mesmo cliente, na mesma revenda, no mesmo dia.

    Agrupa por REVENDA+CLIENTE+DATA: se a soma dos recebimentos (``R``) e a
    soma dos pagamentos com "ESTORNO" no histórico (``P``) se cancelam
    (``|SomaR + SomaP| < 0,01``) e ``SomaR >= limiar``, é exceção — dinheiro
    que entrou e saiu no mesmo dia sem deixar saldo. Reproduz o achado de
    referência (KOBE NISSAN GV, 30/06/2026, R$ 100.000,00 e R$ 96.050,74 —
    caiu no caixa 9 e só aparece rodando sem :func:`_filtro_caixas_operacionais`).

    Args:
        limiar: Valor mínimo do recebimento estornado para virar exceção.
        empresa, periodo, modo: Filtros opcionais.
        limite: Máximo de linhas devolvidas.
    """
    base = _base(empresa, periodo, modo)
    return (
        "EVALUATE\n"
        f"VAR _Agrupado =\n"
        f"    SUMMARIZECOLUMNS(\n"
        f"        {_col(COL_REVENDA)}, {_col(COL_CLIENTE)}, {_col(COL_DATA)},\n"
        f"        {base},\n"
        f'        "SomaR", CALCULATE(SUM({_col(COL_VALOR)}), {_col(COL_PR)} = "R"),\n'
        f'        "SomaP", CALCULATE(SUM({_col(COL_VALOR)}), {_col(COL_PR)} = "P" '
        f'&& SEARCH("{MARCADOR_ESTORNO}", {_col(COL_HISTORICO)}, 1, 0) > 0)\n'
        "    )\n"
        f"RETURN\n"
        f"TOPN(\n    {limite},\n"
        f"    FILTER(_Agrupado, [SomaR] >= {limiar} && ABS([SomaR] + [SomaP]) < 0.01),\n"
        f"    [SomaR], 0\n"
        ")\n"
        "ORDER BY [SomaR] DESC"
    )


# --------------------------------------------------------------------------- #
# R2 — Estorno com valor positivo (aumenta o caixa)
# --------------------------------------------------------------------------- #
def regra_r2_estorno_positivo(
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Lançamentos de estorno cujo valor é positivo — aumentam o caixa.

    Estorno deveria desfazer uma entrada (valor negativo). Um estorno
    positivo é contraintuitivo e merece explicação. Reproduz o achado de
    referência (MULT BOATS +R$ 64.000,00, entre outros).
    """
    filtro = (
        f'SEARCH("{MARCADOR_ESTORNO}", {_col(COL_HISTORICO)}, 1, 0) > 0 '
        f"&& {_col(COL_VALOR)} > 0"
    )
    return _listar(
        filtro, ordenar_por="[VALOR]", ordem="DESC",
        empresa=empresa, periodo=periodo, modo=modo, limite=limite,
    )


# --------------------------------------------------------------------------- #
# R3 — Estorno sem origem classificada
# --------------------------------------------------------------------------- #
def regra_r3_estorno_sem_origem(
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Estornos com ``ORIGEM`` na sentinela em branco (``" -"``).

    Esses lançamentos somem de qualquer análise agrupada por origem — é
    assim que o ranking de despesas escondia R$ 120 mil sob o rótulo "-".
    """
    filtro = (
        f'SEARCH("{MARCADOR_ESTORNO}", {_col(COL_HISTORICO)}, 1, 0) > 0 '
        f'&& {_col(COL_ORIGEM)} = "{ORIGEM_EM_BRANCO}"'
    )
    return _listar(
        filtro, ordenar_por="[VALOR]", ordem="ASC",
        empresa=empresa, periodo=periodo, modo=modo, limite=limite,
    )


# --------------------------------------------------------------------------- #
# R4 — Fracionamento
# --------------------------------------------------------------------------- #
def regra_r4_fracionamento(
    minimo_ocorrencias: int = 4,
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Mesmo cliente, mesma origem, mesmo dia, mesmo valor, N vezes.

    Agrupamento que se repete pode ser rateio legítimo — mas também é a
    forma clássica de fatiar um valor para escapar de alçada de aprovação.
    Reproduz o achado de referência (cliente 141331, 6× R$ 4.490,00 em
    30/06/2026).

    Args:
        minimo_ocorrencias: Quantas repetições idênticas viram exceção.
    """
    base = _base(empresa, periodo, modo)
    return (
        "EVALUATE\n"
        f"VAR _Agrupado =\n"
        f"    SUMMARIZECOLUMNS(\n"
        f"        {_col(COL_REVENDA)}, {_col(COL_CLIENTE)}, {_col(COL_ORIGEM)}, "
        f"{_col(COL_DATA)}, {_col(COL_VALOR)},\n"
        f"        {base},\n"
        f'        "N", COUNTROWS(\'{TABELA}\'),\n'
        f'        "Total", SUM({_col(COL_VALOR)})\n'
        "    )\n"
        f"RETURN\n"
        f"TOPN(\n    {limite},\n"
        f"    FILTER(_Agrupado, [N] >= {minimo_ocorrencias}),\n"
        f"    ABS([Total]), 0\n"
        ")\n"
        "ORDER BY ABS([Total]) DESC"
    )


# --------------------------------------------------------------------------- #
# R5 — Lançamento em fim de semana
# --------------------------------------------------------------------------- #
def regra_r5_fim_de_semana(
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Lançamentos em sábado ou domingo — raros no negócio (baseline: 6 no total).

    ``WEEKDAY`` do DAX: 1 = domingo, 7 = sábado (convenção padrão, tipo 1).
    """
    filtro = f"WEEKDAY({_col(COL_DATA)}) = 1 || WEEKDAY({_col(COL_DATA)}) = 7"
    return _listar(
        filtro, ordenar_por="[DATA]", ordem="ASC",
        empresa=empresa, periodo=periodo, modo=modo, limite=limite,
    )


# --------------------------------------------------------------------------- #
# R6 — Lacuna na sequência de TITULO por revenda
# --------------------------------------------------------------------------- #
def regra_r6_cobertura_titulo(
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """**Informativa, não é regra de exceção** — ver ``severidade`` em :data:`REGRAS`.

    A concepção original de R6 ("lacuna de sequência") assumia ``TITULO``
    como um contador privado por revenda. Testada contra os dados reais, essa
    premissa é **falsa**: toda revenda tem ``TITULO`` no mesmo intervalo
    global ``1–186758`` (medição de 07/08/2026), com densidade entre 0,05% e
    1,5% — ``TITULO`` é um ID compartilhado por um sistema bem maior que
    ``CAIXAS`` (o Linx Apollo inteiro, não só lançamentos de caixa). Sob essa
    premissa, "números faltando" numa revenda não significa lançamento
    excluído — é ID de outro tipo de documento, esperado e inofensivo. A
    versão anterior desta regra chegava a apontar 186.749 números "faltando"
    numa revenda de baixíssimo volume — puro ruído, removido daqui.

    Esta versão devolve o diagnóstico honesto (mínimo, máximo, contagem
    distinta e densidade de ``TITULO`` por revenda), **sem** alegar lacuna.
    Detectar lacunas de verdade exigiria comparar saltos consecutivos dentro
    da própria série de cada revenda contra o padrão dela mesma — engenharia
    futura, registrada como pendência em vez de entregue quebrada.
    """
    base = _base(empresa, periodo, modo)
    filtro_numerico = f"NOT(ISBLANK(VALUE({_col(COL_TITULO)})))"
    return (
        "EVALUATE\n"
        f"VAR _Numerico = FILTER({base}, {filtro_numerico})\n"
        f"VAR _Agrupado =\n"
        f"    SUMMARIZECOLUMNS(\n"
        f"        {_col(COL_REVENDA)},\n"
        f"        _Numerico,\n"
        f'        "Minimo", MINX(_Numerico, VALUE({_col(COL_TITULO)})),\n'
        f'        "Maximo", MAXX(_Numerico, VALUE({_col(COL_TITULO)})),\n'
        f'        "Distintos", DISTINCTCOUNT({_col(COL_TITULO)})\n'
        "    )\n"
        f"VAR _ComDensidade = ADDCOLUMNS(_Agrupado, "
        f'"Densidade", DIVIDE([Distintos], [Maximo] - [Minimo] + 1))\n'
        f"RETURN\n"
        f"TOPN(\n    {limite},\n"
        f"    _ComDensidade,\n"
        f"    [Distintos], 0\n"
        f")\n"
        f"ORDER BY [Distintos] DESC"
    )


# --------------------------------------------------------------------------- #
# R7 — Saldo do caixa fica negativo em alguma data
# --------------------------------------------------------------------------- #
def regra_r7_saldo_negativo(
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Datas em que o saldo acumulado de um REVENDA+CAIXA fica negativo.

    Fisicamente impossível para um caixa em espécie — indica saída não
    registrada ou entrada omitida. Calcula o saldo acumulado por dia
    (transição de contexto de linha para filtro dentro de ``ADDCOLUMNS``) e
    devolve só as datas em que ele é negativo.

    Atenção: quando ``periodo`` é informado, o saldo acumulado considera
    **todo o histórico até a data** (não reinicia no início do período) —
    senão um saldo real e positivo pareceria negativo por corte artificial.
    """
    base_periodo = _base(empresa, periodo, modo)
    # Acumulado sempre correto: recorte de escopo/empresa sem o filtro de
    # período, para o saldo não "recomeçar do zero" a cada consulta mensal.
    base_completa = _base(empresa, periodo=None)
    return (
        "EVALUATE\n"
        f"VAR _Diario =\n"
        f"    SUMMARIZECOLUMNS(\n"
        f"        {_col(COL_REVENDA)}, {_col(COL_CAIXA)}, {_col(COL_DATA)},\n"
        f"        {base_periodo}\n"
        "    )\n"
        f"VAR _ComSaldo =\n"
        f"    ADDCOLUMNS(\n"
        f"        _Diario,\n"
        f'        "SaldoAcumulado",\n'
        f"        VAR _R = {_col(COL_REVENDA)}\n"
        f"        VAR _C = {_col(COL_CAIXA)}\n"
        f"        VAR _D = {_col(COL_DATA)}\n"
        f"        RETURN CALCULATE(\n"
        f"            SUM({_col(COL_VALOR)}),\n"
        f"            FILTER(\n"
        f"                {base_completa},\n"
        f"                {_col(COL_REVENDA)} = _R && {_col(COL_CAIXA)} = _C "
        f"&& {_col(COL_DATA)} <= _D\n"
        "            )\n"
        "        )\n"
        "    )\n"
        f"RETURN\n"
        f"TOPN(\n    {limite},\n"
        f"    FILTER(_ComSaldo, [SaldoAcumulado] < 0),\n"
        f"    [SaldoAcumulado], 1\n"
        ")\n"
        "ORDER BY [SaldoAcumulado] ASC"
    )


# --------------------------------------------------------------------------- #
# R8 — Transferência interna sem contraparte
# --------------------------------------------------------------------------- #
def regra_r8_transferencia_sem_contraparte(
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Descasamento entre saídas e entradas de transferência interna, por revenda.

    Toda transferência entre caixas/bancos deveria ter uma perna de saída e
    uma de entrada que se cancelam. Soma ``VALOR`` das linhas com ``ORIGEM``
    contendo "TRANSF" por revenda: o resultado deveria ser perto de zero
    (algumas transferências para banco são legitimamente "perna única" — o
    resíduo grande é o que importa, não qualquer descasamento). Baseline de
    referência: R$ 647.759,00 de descasamento total no grupo.
    """
    base = _base(empresa, periodo, modo)
    filtro = f'SEARCH("{MARCADOR_TRANSFERENCIA}", {_col(COL_ORIGEM)}, 1, 0) > 0'
    return (
        "EVALUATE\n"
        f"VAR _Agrupado =\n"
        f"    SUMMARIZECOLUMNS(\n"
        f"        {_col(COL_REVENDA)},\n"
        f"        FILTER({base}, {filtro}),\n"
        f'        "Saidas", CALCULATE(SUM({_col(COL_VALOR)}), {_col(COL_PR)} = "P"),\n'
        f'        "Entradas", CALCULATE(SUM({_col(COL_VALOR)}), {_col(COL_PR)} = "R"),\n'
        f'        "Descasamento", SUM({_col(COL_VALOR)})\n'
        "    )\n"
        f"RETURN\n"
        f"TOPN(\n    {limite},\n"
        f"    _Agrupado,\n"
        f"    ABS([Descasamento]), 0\n"
        ")\n"
        "ORDER BY ABS([Descasamento]) DESC"
    )


# --------------------------------------------------------------------------- #
# R9 — Data fora da janela plausível
# --------------------------------------------------------------------------- #
def regra_r9_data_implausivel(
    empresa: str | None = None,
    limite: int = LIMITE_PADRAO,
) -> str:
    """Lançamentos com ``DATA`` antes do início da base ou no futuro.

    Não aceita ``periodo``/``modo`` — por definição varre a base toda (é
    exatamente o corte de período que a regra audita). Reproduz o achado de
    referência (05/07/2041, MULTICAR MITS MATRIZ, -R$ 30,00).
    """
    filtro = (
        f"{_col(COL_DATA)} < {_data_dax(DATA_INICIO_BASE)} "
        f"|| {_col(COL_DATA)} > TODAY() + 1"
    )
    return _listar(
        filtro, ordenar_por="[DATA]", ordem="DESC",
        empresa=empresa, periodo=None, limite=limite,
    )


# --------------------------------------------------------------------------- #
# R10 — Concentração atípica por cliente/origem (janela própria de 90 dias)
# --------------------------------------------------------------------------- #
def regra_r10_concentracao_atipica(
    dias_janela: int = 90,
    minimo_dias_distintos: int = 5,
    desvios: float = 3.0,
    empresa: str | None = None,
    limite: int = LIMITE_PADRAO,
) -> str:
    """Dias em que o total diário de um CLIENTE+ORIGEM foge do padrão recente.

    Primeira versão: calcula média e desvio-padrão do total diário do próprio
    CLIENTE+ORIGEM dentro da janela (não usa baseline histórico persistido —
    isso é o refinamento da Fase 4/DuckDB). Exige pelo menos
    ``minimo_dias_distintos`` dias com movimento no CLIENTE+ORIGEM, para não
    disparar em pares com pouquíssima ocorrência (onde desvio-padrão não diz
    nada).

    Args:
        dias_janela: Tamanho da janela retroativa a partir de hoje.
        minimo_dias_distintos: Mínimo de dias distintos com lançamento no
            par CLIENTE+ORIGEM para a estatística ser considerada.
        desvios: Quantos desvios-padrão acima da média disparam a exceção.
    """
    data_de = date.today() - timedelta(days=dias_janela)
    base = _base(empresa, periodo=None)
    base_janela = f"FILTER({base}, {_col(COL_DATA)} >= {_data_dax(data_de)})"
    return (
        "EVALUATE\n"
        f"VAR _Diario =\n"
        f"    SUMMARIZECOLUMNS(\n"
        f"        {_col(COL_CLIENTE)}, {_col(COL_ORIGEM)}, {_col(COL_DATA)},\n"
        f"        {base_janela},\n"
        f'        "TotalDia", SUM({_col(COL_VALOR)})\n'
        "    )\n"
        f"VAR _Estatisticas =\n"
        f"    SUMMARIZECOLUMNS(\n"
        f"        {_col(COL_CLIENTE)}, {_col(COL_ORIGEM)},\n"
        f"        _Diario,\n"
        f'        "DiasDistintos", COUNTROWS(_Diario),\n'
        f'        "Media", AVERAGEX(_Diario, [TotalDia]),\n'
        f'        "DesvioPadrao", STDEVX.P(_Diario, [TotalDia])\n'
        "    )\n"
        f"VAR _Elegivel = FILTER(_Estatisticas, "
        f"[DiasDistintos] >= {minimo_dias_distintos} && [DesvioPadrao] > 0)\n"
        f"VAR _ComLimite = ADDCOLUMNS(_Elegivel, "
        f'"Limite", [Media] + {desvios} * [DesvioPadrao])\n'
        f"VAR _Excecoes =\n"
        f"    FILTER(\n"
        f"        NATURALINNERJOIN(_Diario, _ComLimite),\n"
        f"        ABS([TotalDia]) > [Limite]\n"
        "    )\n"
        f"RETURN\n"
        f"TOPN(\n    {limite},\n"
        f"    _Excecoes,\n"
        f"    ABS([TotalDia]) - [Limite], 0\n"
        ")\n"
        "ORDER BY ABS([TotalDia]) - [Limite] DESC"
    )


# --------------------------------------------------------------------------- #
# R11 — Valor redondo alto
# --------------------------------------------------------------------------- #
def regra_r11_valor_redondo(
    limiar: float = 10000.0,
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Lançamentos com valor múltiplo de R$ 1.000 e acima do limiar.

    Valor redondo alto é raro numa transação real (vendas, adiantamentos e
    despesas quase sempre têm centavos ou dezenas) — mais comum em valor
    fabricado ou estimado de cabeça.

    Args:
        limiar: Valor absoluto mínimo (em R$) para virar exceção.
    """
    filtro = (
        f"MOD(ABS({_col(COL_VALOR)}), 1000) = 0 && ABS({_col(COL_VALOR)}) >= {limiar}"
    )
    return _listar(
        filtro, ordenar_por="ABS([VALOR])", ordem="DESC",
        empresa=empresa, periodo=periodo, modo=modo, limite=limite,
    )


# --------------------------------------------------------------------------- #
# R12 — Mesmo usuário lança e estorna a mesma operação
# --------------------------------------------------------------------------- #
def regra_r12_autorrevisao_estorno(
    limiar: float = 5000.0,
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Recebimento e estorno do mesmo dia (R1) restrito ao mesmo usuário.

    Subconjunto de :func:`regra_r1_estorno_mesmo_dia` em que quem lançou o
    recebimento é a mesma pessoa que o estornou — ciclo fechado sem revisão
    de terceiro. **Toda linha aqui é candidata a "requer revisão
    independente"** (ver regras_negocio.md, seção "Segregação de funções") —
    quem consome este relatório nunca deve ser o único revisor das próprias
    linhas.
    """
    base = _base(empresa, periodo, modo)
    return (
        "EVALUATE\n"
        f"VAR _Agrupado =\n"
        f"    SUMMARIZECOLUMNS(\n"
        f"        {_col(COL_REVENDA)}, {_col(COL_CLIENTE)}, {_col(COL_DATA)}, "
        f"{_col(COL_NOME_USUARIO)},\n"
        f"        {base},\n"
        f'        "SomaR", CALCULATE(SUM({_col(COL_VALOR)}), {_col(COL_PR)} = "R"),\n'
        f'        "SomaP", CALCULATE(SUM({_col(COL_VALOR)}), {_col(COL_PR)} = "P" '
        f'&& SEARCH("{MARCADOR_ESTORNO}", {_col(COL_HISTORICO)}, 1, 0) > 0),\n'
        f'        "LinhasR", CALCULATE(COUNTROWS(\'{TABELA}\'), {_col(COL_PR)} = "R"),\n'
        f'        "LinhasEstornoMesmoUsuario", CALCULATE(\n'
        f"            COUNTROWS('{TABELA}'),\n"
        f'            {_col(COL_PR)} = "P",\n'
        f'            SEARCH("{MARCADOR_ESTORNO}", {_col(COL_HISTORICO)}, 1, 0) > 0\n'
        "        )\n"
        "    )\n"
        f"RETURN\n"
        f"TOPN(\n    {limite},\n"
        f"    FILTER(\n"
        f"        _Agrupado,\n"
        f"        [SomaR] >= {limiar} && ABS([SomaR] + [SomaP]) < 0.01\n"
        f"        && [LinhasR] > 0 && [LinhasEstornoMesmoUsuario] > 0\n"
        "    ),\n"
        f"    [SomaR], 0\n"
        ")\n"
        "ORDER BY [SomaR] DESC"
    )


# --------------------------------------------------------------------------- #
# R13 — Usuário atuando fora do seu conjunto habitual de revendas
# --------------------------------------------------------------------------- #
def regra_r13_usuario_fora_do_padrao(
    percentual_minimo: float = 0.05,
    minimo_lancamentos_usuario: int = 20,
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Revendas onde um usuário tem participação marginal no próprio volume.

    Para cada usuário com pelo menos ``minimo_lancamentos_usuario``
    lançamentos no total, lista as revendas em que ele aparece com menos de
    ``percentual_minimo`` dos próprios lançamentos — sinal de acesso
    esporádico/atípico (credencial compartilhada, cobertura de férias, ou
    acesso indevido), a investigar caso a caso.

    Args:
        percentual_minimo: Abaixo disso, a revenda é "atípica" para o usuário.
        minimo_lancamentos_usuario: Volume mínimo do usuário para entrar na
            análise (evita ruído de quem lança pouco em geral).
    """
    base = _base(empresa, periodo, modo)
    return (
        "EVALUATE\n"
        f"VAR _PorUsuarioRevenda =\n"
        f"    SUMMARIZECOLUMNS(\n"
        f"        {_col(COL_NOME_USUARIO)}, {_col(COL_REVENDA)},\n"
        f"        {base},\n"
        f'        "N", COUNTROWS(\'{TABELA}\')\n'
        "    )\n"
        f"VAR _PorUsuario =\n"
        f"    SUMMARIZECOLUMNS(\n"
        f"        {_col(COL_NOME_USUARIO)},\n"
        f"        {base},\n"
        f'        "NTotal", COUNTROWS(\'{TABELA}\')\n'
        "    )\n"
        f"VAR _Combinado = NATURALINNERJOIN(_PorUsuarioRevenda, _PorUsuario)\n"
        f"VAR _ComPercentual = ADDCOLUMNS(_Combinado, "
        f'"Percentual", DIVIDE([N], [NTotal]))\n'
        f"RETURN\n"
        f"TOPN(\n    {limite},\n"
        f"    FILTER(\n"
        f"        _ComPercentual,\n"
        f"        [NTotal] >= {minimo_lancamentos_usuario} "
        f"&& [Percentual] < {percentual_minimo}\n"
        "    ),\n"
        f"    [Percentual], 1\n"
        ")\n"
        "ORDER BY [Percentual] ASC"
    )


# --------------------------------------------------------------------------- #
# R14 — Autoconcessão (usuário = beneficiário do adiantamento)
# --------------------------------------------------------------------------- #
def regra_r14_autoconcessao(
    empresa: str | None = None,
    periodo: str | None = None,
    modo: str = "mensal",
    limite: int = LIMITE_PADRAO,
) -> str:
    """Adiantamentos em que o nome de quem lançou aparece no próprio histórico.

    Restrito a ``ORIGEM`` contendo "ADIANTAMENTO". Usa ``SEARCH`` do DAX
    (case-insensitive, mas **sem** normalizar acento) para testar se
    ``NOME_USUARIO`` aparece dentro de ``HISTORICO`` — sinal de conflito de
    interesse direto. É triagem, não prova: nomes com acento podem escapar
    (ver limitação no docstring do módulo), e homônimos geram falso-positivo.
    Baseline de referência: 16 casos em 1.499 lançamentos de adiantamento.
    """
    filtro = (
        f'SEARCH("{MARCADOR_ADIANTAMENTO}", {_col(COL_ORIGEM)}, 1, 0) > 0 '
        f"&& NOT(ISBLANK({_col(COL_NOME_USUARIO)})) "
        f"&& SEARCH({_col(COL_NOME_USUARIO)}, {_col(COL_HISTORICO)}, 1, 0) > 0"
    )
    return _listar(
        filtro, ordenar_por="ABS([VALOR])", ordem="DESC",
        empresa=empresa, periodo=periodo, modo=modo, limite=limite,
    )


# --------------------------------------------------------------------------- #
# Registro das regras (usado pelo servidor MCP para orquestrar a execução)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Regra:
    """Metadados de uma regra de auditoria, para o orquestrador do servidor."""

    id: str
    titulo: str
    severidade: str  # "alta" | "media" | "baixa" | "informativo" (não é exceção — ver R6)
    construtor: object  # Callable[..., str] — assinatura varia por regra
    aceita_periodo: bool = True


REGRAS: dict[str, Regra] = {
    "R1": Regra("R1", "Recebimento estornado no mesmo dia", "alta", regra_r1_estorno_mesmo_dia),
    "R2": Regra("R2", "Estorno com valor positivo", "alta", regra_r2_estorno_positivo),
    "R3": Regra("R3", "Estorno sem origem classificada", "media", regra_r3_estorno_sem_origem),
    "R4": Regra("R4", "Fracionamento de lançamentos", "alta", regra_r4_fracionamento),
    "R5": Regra("R5", "Lançamento em fim de semana", "baixa", regra_r5_fim_de_semana),
    # R6 é informativa (não lista exceções) — a hipótese original de "lacuna
    # de sequência" não se sustentou contra os dados reais (ver docstring de
    # regra_r6_cobertura_titulo). Excluir do bloco de exceções do relatório;
    # incluir só sob pedido explícito.
    "R6": Regra("R6", "Cobertura de título por revenda (informativo)", "informativo", regra_r6_cobertura_titulo),
    "R7": Regra("R7", "Saldo do caixa negativo", "alta", regra_r7_saldo_negativo),
    "R8": Regra("R8", "Transferência interna sem contraparte", "media", regra_r8_transferencia_sem_contraparte),
    "R9": Regra("R9", "Data fora da janela plausível", "media", regra_r9_data_implausivel, aceita_periodo=False),
    "R10": Regra("R10", "Concentração atípica por cliente/origem", "media", regra_r10_concentracao_atipica, aceita_periodo=False),
    "R11": Regra("R11", "Valor redondo acima do limiar", "baixa", regra_r11_valor_redondo),
    "R12": Regra("R12", "Mesmo usuário lança e estorna", "alta", regra_r12_autorrevisao_estorno),
    "R13": Regra("R13", "Usuário fora do padrão de revendas", "media", regra_r13_usuario_fora_do_padrao),
    "R14": Regra("R14", "Autoconcessão de adiantamento", "alta", regra_r14_autoconcessao),
}
