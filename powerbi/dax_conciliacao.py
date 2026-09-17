"""Consultas DAX da conciliação de caixa: financeiro (CAIXAS) x contábil.

A conciliação atravessa **dois datasets diferentes** do Power BI, e por isso
este módulo é o único do projeto com consultas para os dois lados:

* **Financeiro** — dataset ``controlador`` (``lancamentos_financeiros``),
  tabela ``CAIXAS``, um lançamento de caixa por linha, com ``DATA`` diária.
* **Contábil** — dataset padrão (``lancamentos_contabeis``), tabela
  ``lancamentos``, coluna de valor ``VALOR_AJUSTADO`` e ``PERIODO`` textual
  ``MM/AAAA``.

Como em ``dax_financeiro.py``, ``dax_auditoria.py`` e ``dax_coaf.py``, cada
função devolve **a string DAX pronta** — nada é executado aqui. A execução fica
com :class:`~powerbi.client.PowerBIClient` e a conciliação com
``analysis/conciliacao_caixa.py``.

Decisões de modelagem (verificadas contra os dados, não presumidas)
-------------------------------------------------------------------

1. **A granularidade máxima é o MÊS, não o dia.** A tabela ``lancamentos`` não
   tem coluna de data: o único marcador temporal é ``PERIODO``, texto
   ``MM/AAAA``. Não existe saldo contábil "do dia 15" para comparar. Toda
   consulta daqui sai por chave ``AAAAMM``, e o corte do lado financeiro é
   sempre no **último dia do mês**.

2. **A chave de conciliação é ``EMPRESA``, nunca ``REVENDA``.** As
   transferências de saldo entre caixas de revendas diferentes da mesma
   empresa (``ORIGEM`` contendo ``TRANSF``) movimentam o livro-caixa nas duas
   pontas e não têm lançamento contábil correspondente — por revenda os dois
   lados nunca fecham; por empresa elas se anulam. Confirmado nos dados em
   03/2026: KOBE VV mostrou 66.555,98 no contábil contra 17.343,93 no
   financeiro, enquanto o total KOBE do mês bateu com R$ 1,00 de diferença.

3. **Os caixas 9/99/4 (e 8/14 na Multicar Mits) ENTRAM na conciliação.** Ao
   contrário das regras de auditoria e dos painéis de saldo, aqui eles são
   obrigatórios: a contabilidade registra tudo em CAIXA GERAL, e excluí-los
   quebraria a igualdade. Verificado: com eles, ROYAL fecha centavo a centavo
   nos 19 meses de 01/2025 a 07/2026; sem eles, não fecha em nenhum.

4. **As 28 linhas de "SALDO INICIAL DA PLANILHA" também ENTRAM.** Elas são o
   saldo de fechamento de 2024 trazido para o livro-caixa — exatamente o que
   torna os dois acumulados comparáveis. Removê-las (como fazem auditoria e
   COAF) deslocaria o financeiro para baixo em todo o período.

5. **``VALOR`` (financeiro) e ``VALOR_AJUSTADO`` (contábil) já vêm com sinal.**
   Soma direta dos dois lados, sem ABS e sem inverter por ``PAGAR_RECEBER`` ou
   por ``NATUREZA``.

6. **Sem ``TIPO_LANÇAMENTO``.** O recorte contábil/gerencial existe só na DRE.
   O saldo de uma conta patrimonial soma todo lançamento que a tocou.
"""

from __future__ import annotations

from datetime import date

from .dax_lib import escapar_texto

# --------------------------------------------------------------------------- #
# Lado contábil — dataset padrão (lancamentos_contabeis), tabela lancamentos
# --------------------------------------------------------------------------- #
TABELA_CONTABIL = "lancamentos"

CTB_CONTA = "CONTA"
CTB_DESCRICAO_CONTA = "DESCRICAO_CONTA"
CTB_PERIODO = "PERIODO"
CTB_EMPRESA = "EMPRESA"
CTB_REVENDA = "REVENDA"
#: Valor com o sinal já corrigido — use sempre esta, nunca ``VALOR``.
CTB_VALOR = "VALOR_AJUSTADO"

# --------------------------------------------------------------------------- #
# Lado financeiro — dataset controlador (lancamentos_financeiros), tabela CAIXAS
# --------------------------------------------------------------------------- #
TABELA_FINANCEIRA = "CAIXAS"

FIN_EMPRESA = "EMPRESA"
FIN_REVENDA = "REVENDA"
FIN_CAIXA = "CAIXA"
FIN_DATA = "DATA"
FIN_VALOR = "VALOR"
FIN_ORIGEM = "ORIGEM"
FIN_HISTORICO = "HISTORICO"
FIN_TITULO = "TITULO"
FIN_CLIENTE = "CLIENTE"
FIN_NOME_USUARIO = "NOME_USUARIO"

#: Apelido do dataset financeiro em ``config/datasets.yaml``.
DATASET_FINANCEIRO = "controlador"

#: ``HISTORICO`` das 28 linhas de abertura do livro-caixa (01/01/2025).
HISTORICO_ABERTURA = "SALDO INICIAL DA PLANILHA"

#: Trechos de ``ORIGEM`` que marcam transferência **de caixa para caixa**.
#:
#: Nem toda origem com ``TRANSF`` serve aqui, e a distinção é o que separa
#: diagnóstico de ruído. Medido em 20/08/2026, as 9 origens com ``TRANSF``
#: se dividem em dois grupos:
#:
#: * **Caixa ↔ caixa** — ``200 - TRANSFERENCIA SALDO DE CAIXA`` e
#:   ``707 - TRANSF. SALDO CAIXA``. As duas pernas ficam dentro de ``CAIXAS``
#:   e, quando são da mesma empresa, **não há lançamento contábil nenhum** (o
#:   dinheiro não saiu da conta CAIXA GERAL). São estas que interessam.
#: * **Caixa ↔ banco** — ``701/702/711/731/737 - TRANSF. CAIXA P/ <banco>`` e
#:   ``703 - TRANSF. SANTANDER P/ CAIXA``. Só uma perna existe no livro-caixa;
#:   a contrapartida é conta bancária e **tem** lançamento contábil. Se
#:   entrassem no diagnóstico, toda empresa apareceria com líquido diferente
#:   de zero todo mês — inclusive as que conciliam centavo a centavo.
PADROES_TRANSFERENCIA_INTERNA = ("SALDO CAIXA", "SALDO DE CAIXA")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _ctb(coluna: str) -> str:
    """Referência segura de coluna da tabela contábil."""
    return f"'{TABELA_CONTABIL}'[{coluna}]"


def _fin(coluna: str) -> str:
    """Referência segura de coluna da tabela financeira."""
    return f"'{TABELA_FINANCEIRA}'[{coluna}]"


def _data_dax(d: date) -> str:
    """Literal DAX ``DATE(ano,mes,dia)`` para uma data Python."""
    return f"DATE({d.year},{d.month},{d.day})"


def _texto(valor: str) -> str:
    """Literal de texto DAX com escape de aspas."""
    return f'"{escapar_texto(valor)}"'


def _ou_igual(expr: str, valores: tuple[str, ...] | list[str]) -> str:
    """Condição ``expr = a || expr = b || ...``.

    Escrita com ``||`` em vez de ``IN {...}``: o operador ``IN`` sobre lista
    literal já devolveu 400 genérico nesta API em consultas com ``FILTER(ALL(
    ...))`` aninhado, e a forma expandida é aceita sempre.
    """
    if not valores:
        raise ValueError("Lista de valores vazia.")
    return "(" + " || ".join(f"{expr} = {_texto(v)}" for v in valores) + ")"


def _chave_contabil() -> str:
    """Expressão que converte ``PERIODO`` (``MM/AAAA``) na chave ``AAAAMM``.

    ``PERIODO`` é texto e ordena alfabeticamente — ``"02/2024"`` viria antes de
    ``"01/2025"``. A chave inteira resolve comparação e acumulado. Funciona
    também para as linhas de abertura gravadas como ``"01/01/2024"``, porque
    ``LEFT``/``RIGHT`` pegam mês e ano nas mesmas posições.
    """
    return (
        f"VALUE(RIGHT({_ctb(CTB_PERIODO)}, 4)) * 100 "
        f"+ VALUE(LEFT({_ctb(CTB_PERIODO)}, 2))"
    )


def _chave_financeira() -> str:
    """Expressão que converte ``DATA`` (Date) na chave ``AAAAMM``."""
    return f"YEAR({_fin(FIN_DATA)}) * 100 + MONTH({_fin(FIN_DATA)})"


# --------------------------------------------------------------------------- #
# Consultas — saldos mensais dos dois lados
# --------------------------------------------------------------------------- #
def saldos_contabeis_mensais(
    contas: tuple[str, ...] | list[str],
    ate_chave: int,
    desde_chave: int,
    empresa: str | None = None,
) -> str:
    """Saldo contábil acumulado das contas de caixa, por empresa e mês.

    O saldo de uma conta patrimonial é **cumulativo desde o início da base**
    (01/2024): a coluna ``SALDO`` soma tudo até o mês da linha, inclusive, e
    não apenas o mês. ``MOVIMENTO`` traz o movimento isolado do mês, usado no
    relatório para explicar onde a diferença nasceu.

    Args:
        contas: Contas contábeis de caixa (ex.: ``("11101010001",)``).
        ate_chave: Última chave ``AAAAMM`` retornada (inclusive).
        desde_chave: Primeira chave ``AAAAMM`` retornada (inclusive). O
            acumulado continua somando o que veio antes dela.
        empresa: Nome da ``EMPRESA`` **no contábil**. ``None`` = todas.

    Returns:
        A consulta DAX com ``EMPRESA``, ``CHAVE``, ``MOVIMENTO`` e ``SALDO``.
    """
    filtros = [_ou_igual(_ctb(CTB_CONTA), contas)]
    if empresa:
        filtros.append(f"{_ctb(CTB_EMPRESA)} = {_texto(empresa)}")
    condicao = " && ".join(filtros)

    return f"""
DEFINE
    VAR Base = FILTER(ALL('{TABELA_CONTABIL}'), {condicao})
    VAR ComChave = ADDCOLUMNS(Base, "CHAVE", {_chave_contabil()})
    VAR Grupos = SUMMARIZE(ComChave, {_ctb(CTB_EMPRESA)}, [CHAVE])
EVALUATE
FILTER(
    ADDCOLUMNS(
        Grupos,
        "MOVIMENTO",
            VAR E = {_ctb(CTB_EMPRESA)}
            VAR K = [CHAVE]
            RETURN SUMX(
                FILTER(ComChave, {_ctb(CTB_EMPRESA)} = E && [CHAVE] = K),
                {_ctb(CTB_VALOR)}
            ),
        "SALDO",
            VAR E = {_ctb(CTB_EMPRESA)}
            VAR K = [CHAVE]
            RETURN SUMX(
                FILTER(ComChave, {_ctb(CTB_EMPRESA)} = E && [CHAVE] <= K),
                {_ctb(CTB_VALOR)}
            )
    ),
    [CHAVE] >= {int(desde_chave)} && [CHAVE] <= {int(ate_chave)}
)
ORDER BY [{CTB_EMPRESA}] ASC, [CHAVE] ASC
""".strip()


def saldos_financeiros_mensais(
    ate: date,
    desde_chave: int,
    empresa: str | None = None,
) -> str:
    """Saldo do livro-caixa acumulado, por empresa e mês.

    Nada é excluído: caixas 9/99/4, 8/14 da Multicar Mits e as 28 linhas de
    abertura entram todos. Ver o item 3 do docstring do módulo — a conciliação
    é o único uso do projeto em que a exclusão de caixas seria errada.

    Args:
        ate: Data de corte (inclusive). Deve ser o **último dia do mês**, para
            casar com o fechamento contábil.
        desde_chave: Primeira chave ``AAAAMM`` retornada (inclusive). O
            acumulado continua somando o que veio antes dela.
        empresa: Nome da ``EMPRESA`` **no financeiro**. ``None`` = todas.

    Returns:
        A consulta DAX com ``EMPRESA``, ``CHAVE``, ``MOVIMENTO`` e ``SALDO``.
    """
    filtros = [f"{_fin(FIN_DATA)} <= {_data_dax(ate)}"]
    if empresa:
        filtros.append(f"{_fin(FIN_EMPRESA)} = {_texto(empresa)}")
    condicao = " && ".join(filtros)

    return f"""
DEFINE
    VAR Base = FILTER(ALL('{TABELA_FINANCEIRA}'), {condicao})
    VAR ComChave = ADDCOLUMNS(Base, "CHAVE", {_chave_financeira()})
    VAR Grupos = SUMMARIZE(ComChave, {_fin(FIN_EMPRESA)}, [CHAVE])
EVALUATE
FILTER(
    ADDCOLUMNS(
        Grupos,
        "MOVIMENTO",
            VAR E = {_fin(FIN_EMPRESA)}
            VAR K = [CHAVE]
            RETURN SUMX(
                FILTER(ComChave, {_fin(FIN_EMPRESA)} = E && [CHAVE] = K),
                {_fin(FIN_VALOR)}
            ),
        "SALDO",
            VAR E = {_fin(FIN_EMPRESA)}
            VAR K = [CHAVE]
            RETURN SUMX(
                FILTER(ComChave, {_fin(FIN_EMPRESA)} = E && [CHAVE] <= K),
                {_fin(FIN_VALOR)}
            )
    ),
    [CHAVE] >= {int(desde_chave)}
)
ORDER BY [{FIN_EMPRESA}] ASC, [CHAVE] ASC
""".strip()


def abertura_financeira(empresa: str | None = None) -> str:
    """As 28 linhas de ``"SALDO INICIAL DA PLANILHA"``, somadas por empresa.

    É o saldo de fechamento de 2024 que a planilha trouxe para o livro-caixa.
    Comparado ao saldo contábil acumulado até 12/2024, revela a diferença de
    abertura — a que se arrasta constante por todos os meses seguintes.

    Args:
        empresa: Nome da ``EMPRESA`` **no financeiro**. ``None`` = todas.
            Precisa acompanhar o filtro das consultas de saldo: uma abertura
            que volta com empresas fora do recorte é comparada contra saldo
            contábil zero e vira divergência inventada.
    """
    filtro_empresa = ""
    if empresa:
        filtro_empresa = (
            f"\n    FILTER(ALL({_fin(FIN_EMPRESA)}), "
            f"{_fin(FIN_EMPRESA)} = {_texto(empresa)}),"
        )
    return f"""
EVALUATE
SUMMARIZECOLUMNS(
    {_fin(FIN_EMPRESA)},{filtro_empresa}
    FILTER(
        ALL({_fin(FIN_HISTORICO)}),
        {_fin(FIN_HISTORICO)} = {_texto(HISTORICO_ABERTURA)}
    ),
    "ABERTURA", SUM({_fin(FIN_VALOR)})
)
ORDER BY [{FIN_EMPRESA}] ASC
""".strip()


# --------------------------------------------------------------------------- #
# Consultas — diagnóstico
# --------------------------------------------------------------------------- #
def contas_de_caixa_candidatas() -> str:
    """Contas contábeis cuja descrição contém "CAIXA", com saldo e volume.

    Serve de checagem contra o ``contas_caixa`` de
    ``config/conciliacao_caixa.yaml``: se o plano de contas ganhar uma conta de
    caixa nova e ninguém atualizar o YAML, ela aparece aqui e o relatório
    avisa. ``SEARCH`` exige o 4º argumento (fallback ``0``), senão a query erra.
    """
    return f"""
EVALUATE
SUMMARIZECOLUMNS(
    {_ctb(CTB_CONTA)},
    {_ctb(CTB_DESCRICAO_CONTA)},
    {_ctb(CTB_EMPRESA)},
    FILTER(
        ALL({_ctb(CTB_DESCRICAO_CONTA)}),
        SEARCH("CAIXA", {_ctb(CTB_DESCRICAO_CONTA)}, 1, 0) > 0
    ),
    "LINHAS", COUNTROWS('{TABELA_CONTABIL}'),
    "SALDO", SUM({_ctb(CTB_VALOR)})
)
ORDER BY [{CTB_CONTA}] ASC, [{CTB_EMPRESA}] ASC
""".strip()


def transferencias_por_empresa(
    ate: date,
    desde_chave: int,
    padroes: tuple[str, ...] | list[str] = PADROES_TRANSFERENCIA_INTERNA,
) -> str:
    """Saldo líquido das transferências **caixa a caixa**, por empresa e mês.

    Uma transferência de saldo entre caixas gera duas linhas no livro-caixa
    (saída e entrada) e nenhum lançamento contábil. Se as duas pernas estão na
    mesma empresa, o líquido é zero e a conciliação por empresa não sente. Um
    líquido **diferente de zero** é candidato a explicar uma divergência do mês
    — transferência atravessando a fronteira da empresa, ou perna faltando.

    Só transferências caixa↔caixa entram; ver
    :data:`PADROES_TRANSFERENCIA_INTERNA` para o porquê de as origens
    ``TRANSF. CAIXA P/ <banco>`` ficarem de fora.

    Args:
        ate: Data de corte (inclusive), último dia do mês.
        desde_chave: Primeira chave ``AAAAMM`` retornada.
        padroes: Trechos de ``ORIGEM`` que marcam transferência caixa↔caixa.

    Returns:
        A consulta DAX com ``EMPRESA``, ``CHAVE`` e ``LIQUIDO_TRANSF``.

    Raises:
        ValueError: Se ``padroes`` vier vazio.
    """
    if not padroes:
        raise ValueError(
            "Sem padrões de ORIGEM não há como isolar transferência caixa a caixa."
        )
    busca = " || ".join(
        f"SEARCH({_texto(p)}, {_fin(FIN_ORIGEM)}, 1, 0) > 0" for p in padroes
    )
    return f"""
DEFINE
    VAR Base =
        FILTER(
            ALL('{TABELA_FINANCEIRA}'),
            {_fin(FIN_DATA)} <= {_data_dax(ate)}
                && ({busca})
        )
    VAR ComChave = ADDCOLUMNS(Base, "CHAVE", {_chave_financeira()})
    VAR Grupos = SUMMARIZE(ComChave, {_fin(FIN_EMPRESA)}, [CHAVE])
EVALUATE
FILTER(
    ADDCOLUMNS(
        Grupos,
        "LIQUIDO_TRANSF",
            VAR E = {_fin(FIN_EMPRESA)}
            VAR K = [CHAVE]
            RETURN SUMX(
                FILTER(ComChave, {_fin(FIN_EMPRESA)} = E && [CHAVE] = K),
                {_fin(FIN_VALOR)}
            )
    ),
    [CHAVE] >= {int(desde_chave)}
)
ORDER BY [{FIN_EMPRESA}] ASC, [CHAVE] ASC
""".strip()


# --------------------------------------------------------------------------- #
# Consultas — drill-down de um mês divergente
# --------------------------------------------------------------------------- #
def movimento_contabil_por_revenda(
    contas: tuple[str, ...] | list[str],
    empresa: str,
    periodo: str,
) -> str:
    """Movimento contábil do mês, quebrado por revenda.

    Só para investigar um mês já apontado como divergente. **A quebra por
    revenda não concilia** (ver item 2 do docstring do módulo) — ela serve
    para estreitar a busca, não para fechar número.

    Args:
        contas: Contas contábeis de caixa.
        empresa: Nome da ``EMPRESA`` no contábil.
        periodo: ``"MM/AAAA"``.
    """
    return f"""
EVALUATE
SUMMARIZECOLUMNS(
    {_ctb(CTB_REVENDA)},
    FILTER(ALL({_ctb(CTB_CONTA)}), {_ou_igual(_ctb(CTB_CONTA), contas)}),
    FILTER(ALL({_ctb(CTB_EMPRESA)}), {_ctb(CTB_EMPRESA)} = {_texto(empresa)}),
    FILTER(ALL({_ctb(CTB_PERIODO)}), {_ctb(CTB_PERIODO)} = {_texto(periodo)}),
    "MOVIMENTO", SUM({_ctb(CTB_VALOR)})
)
ORDER BY [{CTB_REVENDA}] ASC
""".strip()


def movimento_financeiro_por_revenda(
    empresa: str,
    inicio: date,
    fim: date,
) -> str:
    """Movimento do livro-caixa no intervalo, quebrado por revenda e caixa.

    Contrapartida de :func:`movimento_contabil_por_revenda` no drill-down.

    Args:
        empresa: Nome da ``EMPRESA`` no financeiro.
        inicio: Primeiro dia do mês investigado.
        fim: Último dia do mês investigado.
    """
    return f"""
EVALUATE
SUMMARIZECOLUMNS(
    {_fin(FIN_REVENDA)},
    {_fin(FIN_CAIXA)},
    FILTER(ALL({_fin(FIN_EMPRESA)}), {_fin(FIN_EMPRESA)} = {_texto(empresa)}),
    FILTER(
        ALL({_fin(FIN_DATA)}),
        {_fin(FIN_DATA)} >= {_data_dax(inicio)} && {_fin(FIN_DATA)} <= {_data_dax(fim)}
    ),
    "MOVIMENTO", SUM({_fin(FIN_VALOR)})
)
ORDER BY [{FIN_REVENDA}] ASC, [{FIN_CAIXA}] ASC
""".strip()


def lancamentos_financeiros_do_mes(
    empresa: str,
    inicio: date,
    fim: date,
    valor_maximo: float | None = None,
) -> str:
    """Lançamentos do livro-caixa de um mês, linha a linha.

    Último passo do drill-down, quando a diferença do mês é pequena e vale
    procurar o lançamento exato. ``valor_maximo`` filtra por ``ABS(VALOR)`` —
    passe o tamanho da diferença para reduzir a lista.

    Args:
        empresa: Nome da ``EMPRESA`` no financeiro.
        inicio: Primeiro dia do mês investigado.
        fim: Último dia do mês investigado.
        valor_maximo: Se informado, só lançamentos com ``ABS(VALOR)`` até esse
            teto. ``None`` traz todos (pode ser muita linha).
    """
    filtros = [
        f"{_fin(FIN_EMPRESA)} = {_texto(empresa)}",
        f"{_fin(FIN_DATA)} >= {_data_dax(inicio)}",
        f"{_fin(FIN_DATA)} <= {_data_dax(fim)}",
    ]
    if valor_maximo is not None:
        filtros.append(f"ABS({_fin(FIN_VALOR)}) <= {float(valor_maximo)}")
    condicao = "\n        && ".join(filtros)

    return f"""
EVALUATE
SELECTCOLUMNS(
    FILTER(
        ALL('{TABELA_FINANCEIRA}'),
        {condicao}
    ),
    "DATA", {_fin(FIN_DATA)},
    "REVENDA", {_fin(FIN_REVENDA)},
    "CAIXA", {_fin(FIN_CAIXA)},
    "TITULO", {_fin(FIN_TITULO)},
    "VALOR", {_fin(FIN_VALOR)},
    "ORIGEM", {_fin(FIN_ORIGEM)},
    "HISTORICO", {_fin(FIN_HISTORICO)},
    "USUARIO", {_fin(FIN_NOME_USUARIO)}
)
ORDER BY [DATA] ASC, [VALOR] DESC
""".strip()
