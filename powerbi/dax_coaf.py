"""Consulta DAX dos recebimentos em espécie para o monitoramento do COAF.

Dataset ``controlador`` (apelido em ``config/datasets.yaml`` para o dataset
Power BI ``lancamentos_financeiros``), tabela ``CAIXAS``. Ver
``dictionary/regras_negocio.md`` — seção "COAF / Recebimentos em espécie" —
para a definição de negócio adotada e o risco registrado.

Como em ``dax_auditoria.py`` e ``dax_financeiro.py``, cada função devolve **a
string DAX pronta** — nada é executado aqui. A execução fica com
:class:`~powerbi.client.PowerBIClient` e a análise com
``analysis/coaf_especie.py``.

Por que este módulo é curto (e assimétrico em relação a ``dax_auditoria.py``)
-----------------------------------------------------------------------------

A detecção do COAF **não é uma agregação no servidor**. Três razões obrigam a
trazer os lançamentos linha a linha e agregar em Python:

1. **A chave de identidade não é uma coluna pronta.** É ``CAIXAS[CLIENTE]``
   (o código — ver :func:`analysis.coaf_especie.chave_do_cliente`), mas o
   nome de exibição precisa de ``NOME_CLIENTE``/``HISTORICO`` combinados e de
   agregação por código, que o DAX não faz de forma prática aqui. O
   agrupamento e a resolução do nome só são possíveis depois, em Python.
2. **A janela de 6 meses é móvel.** O limiar precisa ser testado em toda janela
   de 6 meses que termine em uma data de recebimento, não só na que termina
   hoje — senão fracionamento que cruza a borda do semestre passa batido.
3. **O volume é pequeno.** ~1.700 recebimentos em 6 meses, ~3.500 em 12. Trazer
   tudo custa uma requisição e alguns milissegundos de pandas.

Particularidades do modelo respeitadas aqui
-------------------------------------------

- ``VALOR`` já vem com sinal (``R`` positivo). Nunca inverter.
- ``DATA`` é Date nativo — recorte com ``DATE(...)``, sem chave ``AAAAMM``.
- ``SEARCH`` exige o 4º argumento (fallback ``0``), senão a query erra.
- As 28 linhas de ``"SALDO INICIAL DA PLANILHA"`` não têm ``NOME_USUARIO`` e
  são removidas por :func:`_excluir_abertura`, reaproveitada de
  ``dax_auditoria.py``.
- **Os caixas 9/99/4 (e 8/14 na Multicar Mits) NÃO são excluídos aqui.** Ao
  contrário de toda regra de auditoria, o COAF olha o dinheiro que entrou, não
  a validade do saldo — esses caixas concentram 46% do volume movimentado e
  vários recebimentos acima do limiar. Eles são *sinalizados* em Python, não
  filtrados. Por isso este módulo usa :func:`_excluir_abertura` sozinha, e
  nunca ``_filtro_escopo()``.
"""

from __future__ import annotations

from datetime import date

from .dax_auditoria import (
    COL_CAIXA,
    COL_CLIENTE,
    COL_DATA,
    COL_EMPRESA,
    COL_HISTORICO,
    COL_NOME_USUARIO,
    COL_ORIGEM,
    COL_PR,
    COL_REVENDA,
    COL_TITULO,
    COL_VALOR,
    TABELA,
    _col,
    _data_dax,
    _excluir_abertura,
)
from .dax_lib import escapar_texto

#: Colunas acrescentadas ao modelo em 19/08/2026 pelo setor de COAF.
#: ``RAZAO_SOCIAL`` é a razão social da **empresa do grupo** (com prefixo de
#: filial, ex.: ``"6 - MULTI COMERCIO DE VEICULOS LTDA"``); ``Fisjur`` e
#: ``cpf_cnpj`` são do **cliente**. Confirmado nos dados: a mesma
#: ``RAZAO_SOCIAL`` aparece com ``cpf_cnpj`` diferentes conforme o cliente.
COL_RAZAO_SOCIAL = "RAZAO_SOCIAL"
COL_FISJUR = "Fisjur"
COL_CPF_CNPJ = "cpf_cnpj"

#: Coluna acrescentada ao modelo entre 19/08/2026 e 25/08/2026: nome do
#: cliente já resolvido pelo Power BI, sem precisar extrair de ``HISTORICO``.
#: Conferido em 25/08/2026 contra 8.382 recebimentos: cobertura de 100%
#: (nenhuma linha em branco) e cada ``CAIXAS[CLIENTE]`` mapeia para exatamente
#: um ``NOME_CLIENTE`` (nenhum código compartilhado por nomes diferentes).
#: Fonte primária do nome em ``analysis/coaf_especie.py`` (decisão do gestor,
#: 26/08/2026); o parser de ``HISTORICO``
#: (:func:`analysis.coaf_especie.extrair_nome_cliente`) fica como fallback.
#:
#: É cadastro (master data) e pode ser reformatado com o tempo — diferente do
#: texto de ``HISTORICO``, imutável. Uma correção assim já causou um reenvio
#: indevido em produção (26/08/2026, código 225456), porque naquele momento o
#: nome ERA a chave de agregação. Desde então a chave é
#: ``CAIXAS[CLIENTE]`` (ver :func:`analysis.coaf_especie.chave_do_cliente`),
#: então ``NOME_CLIENTE`` só afeta o texto exibido na DMF e no e-mail — não
#: mais a identidade do cliente nem o controle de notificação.
COL_NOME_CLIENTE = "NOME_CLIENTE"

#: Valor de ``PAGAR_RECEBER`` que identifica um recebimento (entrada).
RECEBIMENTO = "R"

#: Exclusões padrão de ``ORIGEM``, casadas por ``SEARCH`` (case-insensitive).
#: São movimentações internas do próprio grupo, não dinheiro de cliente.
#: Sobrepostas por ``config/coaf.yaml`` — este valor é só o fallback.
PADROES_EXCLUSAO_PADRAO: tuple[str, ...] = ("TRANSF", "DEPOSITO", "SAQUE")


def _nao_contem(coluna: str, termo: str) -> str:
    """Condição DAX "``coluna`` não contém ``termo``" (case-insensitive).

    ``SEARCH`` devolve a posição da ocorrência; o 4º argumento é o valor de
    retorno quando não encontra. **Ele é obrigatório**: sem ele, a função gera
    erro em vez de devolver o fallback, e a API responde 400 sem detalhe útil.

    Args:
        coluna: Nome da coluna de ``CAIXAS`` a inspecionar.
        termo: Substring procurada.

    Returns:
        A condição booleana DAX, pronta para concatenar com ``&&``.
    """
    return f'SEARCH("{escapar_texto(termo)}", {_col(coluna)}, 1, 0) = 0'


def _filtro_especie(
    padroes: tuple[str, ...] | list[str] | None = None,
    exatas: tuple[str, ...] | list[str] | None = None,
) -> str:
    """Condição que restringe aos recebimentos considerados "em espécie".

    Regra de negócio (decisão do gestor em 19/08/2026): todo recebimento conta,
    exceto transferência interna entre caixas, depósito e saque. Cartão,
    PIX/TED, cheque e boleto **contam** — ver o risco registrado em
    ``config/coaf.yaml`` e em ``dictionary/regras_negocio.md``.

    Args:
        padroes: Substrings que, se presentes em ``ORIGEM``, excluem a linha.
            ``None`` usa :data:`PADROES_EXCLUSAO_PADRAO`.
        exatas: Valores de ``ORIGEM`` excluídos por igualdade exata.

    Returns:
        A condição booleana DAX, pronta para concatenar com ``&&``.
    """
    if padroes is None:
        padroes = PADROES_EXCLUSAO_PADRAO
    condicoes = [f'{_col(COL_PR)} = "{RECEBIMENTO}"']
    condicoes.extend(_nao_contem(COL_ORIGEM, termo) for termo in padroes)
    for valor in exatas or ():
        condicoes.append(f'{_col(COL_ORIGEM)} <> "{escapar_texto(valor)}"')
    return " && ".join(condicoes)


def _filtro_caixas_excluidos(caixas: tuple[str, ...] | list[str] | None) -> str | None:
    """Condição que retira certos números de caixa **de toda revenda**.

    Diferente de ``caixas_sinalizados`` (que entra na apuração e só sai
    marcado), este filtro remove a linha da consulta — o COAF nem chega a
    ver o lançamento. Decisão do gestor (25/08/2026): caixa "9", em
    qualquer revenda, não deve ser verificado.

    Args:
        caixas: Números de caixa a excluir (ex.: ``["9"]``). ``None`` ou
            vazio não filtra nada.

    Returns:
        A condição booleana DAX, ou ``None`` se não há nada a excluir.
    """
    if not caixas:
        return None
    valores = ", ".join(f'"{escapar_texto(str(c))}"' for c in caixas)
    return f"NOT({_col(COL_CAIXA)} IN {{{valores}}})"


def _colunas_recebimento() -> str:
    """Argumentos de ``SELECTCOLUMNS`` com tudo que a detecção precisa.

    ``NOME_CLIENTE`` é a fonte primária do nome (ver :data:`COL_NOME_CLIENTE`,
    inclusive o risco registrado ali). ``HISTORICO`` continua sendo trazido
    como *fallback*.
    """
    pares = [
        ("EMPRESA", _col(COL_EMPRESA)),
        ("RAZAO_SOCIAL", _col(COL_RAZAO_SOCIAL)),
        ("REVENDA", _col(COL_REVENDA)),
        ("CAIXA", _col(COL_CAIXA)),
        ("DATA", _col(COL_DATA)),
        ("CLIENTE", _col(COL_CLIENTE)),
        ("NOME_CLIENTE", _col(COL_NOME_CLIENTE)),
        ("FISJUR", _col(COL_FISJUR)),
        ("CPF_CNPJ", _col(COL_CPF_CNPJ)),
        ("TITULO", _col(COL_TITULO)),
        ("VALOR", _col(COL_VALOR)),
        ("ORIGEM", _col(COL_ORIGEM)),
        ("HISTORICO", _col(COL_HISTORICO)),
        ("NOME_USUARIO", _col(COL_NOME_USUARIO)),
    ]
    return ", ".join(f'"{nome}", {expr}' for nome, expr in pares)


def recebimentos_especie(
    data_inicio: date,
    data_fim: date,
    padroes_exclusao: tuple[str, ...] | list[str] | None = None,
    origens_exatas: tuple[str, ...] | list[str] | None = None,
    caixas_excluidos: tuple[str, ...] | list[str] | None = None,
) -> str:
    """Lista os recebimentos em espécie de um intervalo, linha a linha.

    Sem ``TOPN``: o corte truncaria a janela de acumulação e produziria um
    total menor que o real — exatamente o erro que o COAF não pode ter. O
    volume justifica (cerca de 3.500 linhas em 12 meses, muito abaixo do limite
    da API de ``executeQueries``).

    Args:
        data_inicio: Primeiro dia do intervalo (inclusive).
        data_fim: Último dia do intervalo (inclusive).
        padroes_exclusao: Substrings de ``ORIGEM`` que excluem a linha.
            ``None`` usa :data:`PADROES_EXCLUSAO_PADRAO`.
        origens_exatas: Valores de ``ORIGEM`` excluídos por igualdade.
        caixas_excluidos: Números de caixa retirados da apuração em **toda**
            revenda (ex.: ``["9"]``). Diferente dos caixas sinalizados, estes
            nem entram na consulta.

    Returns:
        A consulta DAX pronta para ``PowerBIClient.execute_dax``.

    Raises:
        ValueError: Se ``data_inicio`` for posterior a ``data_fim``.
    """
    if data_inicio > data_fim:
        raise ValueError(
            f"Intervalo inválido: data_inicio ({data_inicio}) é posterior a "
            f"data_fim ({data_fim})."
        )
    condicao = (
        f"{_filtro_especie(padroes_exclusao, origens_exatas)}\n"
        f"        && {_col(COL_DATA)} >= {_data_dax(data_inicio)}\n"
        f"        && {_col(COL_DATA)} <= {_data_dax(data_fim)}\n"
        f"        && {_excluir_abertura()}"
    )
    filtro_caixas = _filtro_caixas_excluidos(caixas_excluidos)
    if filtro_caixas:
        condicao += f"\n        && {filtro_caixas}"
    base = f"FILTER(\n        {_tabela()},\n        {condicao}\n    )"
    return (
        "EVALUATE\n"
        "SELECTCOLUMNS(\n"
        f"    {base},\n"
        f"    {_colunas_recebimento()}\n"
        ")\n"
        "ORDER BY [DATA] ASC"
    )


def origens_de_recebimento(data_inicio: date, data_fim: date) -> str:
    """Distribui os recebimentos por ``ORIGEM``, sem aplicar exclusão nenhuma.

    Serve para o compliance revisar a lista de exclusões de
    ``config/coaf.yaml``: mostra toda origem que existe no período, com
    contagem e valor, inclusive as que hoje estão sendo excluídas.

    Args:
        data_inicio: Primeiro dia do intervalo (inclusive).
        data_fim: Último dia do intervalo (inclusive).

    Returns:
        A consulta DAX pronta para ``PowerBIClient.execute_dax``.
    """
    condicao = (
        f'{_col(COL_PR)} = "{RECEBIMENTO}"'
        f" && {_col(COL_DATA)} >= {_data_dax(data_inicio)}"
        f" && {_col(COL_DATA)} <= {_data_dax(data_fim)}"
        f" && {_excluir_abertura()}"
    )
    tabela = _tabela()
    return (
        "EVALUATE\n"
        "SUMMARIZECOLUMNS(\n"
        f"    {_col(COL_ORIGEM)},\n"
        f"    FILTER({tabela}, {condicao}),\n"
        f'    "Lancamentos", COUNTROWS({tabela}),\n'
        f'    "Valor", SUM({_col(COL_VALOR)})\n'
        ")\n"
        "ORDER BY [Valor] DESC"
    )


def _tabela() -> str:
    """Referência DAX da tabela ``CAIXAS``, com as aspas simples exigidas."""
    return f"'{TABELA}'"
