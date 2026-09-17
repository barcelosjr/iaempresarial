"""Estado persistente do monitoramento COAF, no DuckDB local.

Este módulo existe por causa de um requisito explícito do setor de COAF:
**o histórico de clientes detectados nunca pode ser perdido.** A deduplicação
— necessária porque o job roda de 30 em 30 minutos — só decide *se dispara
e-mail*; ela não apaga, não sobrescreve e não esconde nada do histórico.

Por isso as responsabilidades ficam em tabelas separadas:

``coaf_deteccao``
    Registro permanente, **append-only**. Uma linha por cliente por detecção.
    Nunca sofre ``DELETE`` nem ``UPDATE``.

``coaf_deteccao_lancamento``
    Os recebimentos que compuseram cada detecção, também append-only. Sem esta
    cópia a DMF enviada não pode ser reconstruída depois: a base do Power BI é
    de refresh contínuo (``isRefreshable: true``) e lançamentos são
    reclassificados entre caixas com o tempo.

``coaf_notificacao``
    Quem já foi avisado, quando e com qual PDF. É a **única** tabela que a
    deduplicação consulta.

Contraste com ``local_data/snapshots.py``: lá o padrão é idempotente por dia
(``DELETE`` do dia + ``INSERT``), porque um snapshot de saldo só interessa na
versão mais recente. Aqui é o oposto — o valor está justamente em acumular.
"""

from __future__ import annotations

import hashlib
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from local_data.ingest import conectar  # noqa: E402

TABELA_DETECCAO = "coaf_deteccao"
TABELA_DETECCAO_LANCAMENTO = "coaf_deteccao_lancamento"
TABELA_NOTIFICACAO = "coaf_notificacao"

#: Status possíveis em ``coaf_notificacao``.
STATUS_ENVIADO = "enviado"
STATUS_SUPRIMIDO = "suprimido_modo_revisao"
STATUS_FALHA = "falha"
STATUS_SEM_DESTINATARIO = "sem_destinatario"


def hash_lancamento(
    revenda: str, caixa: str, data: Any, titulo: str, valor: float, origem: str
) -> str:
    """Identidade estável de um lançamento de caixa.

    A tabela ``CAIXAS`` não tem chave primária, e ``TITULO`` sozinho não serve:
    é um ID global do Linx Apollo, compartilhado com outros sistemas, e se
    repete entre revendas. A composição abaixo é o que distingue um lançamento
    de outro na prática.

    Args:
        revenda: Valor de ``CAIXAS[REVENDA]``.
        caixa: Valor de ``CAIXAS[CAIXA]``.
        data: Data do lançamento (``date``, ``datetime`` ou texto).
        titulo: Valor de ``CAIXAS[TITULO]``.
        valor: Valor do lançamento.
        origem: Valor de ``CAIXAS[ORIGEM]``.

    Returns:
        Hash SHA-1 hexadecimal do lançamento.
    """
    if isinstance(data, (date, datetime)):
        data_txt = data.strftime("%Y-%m-%d")
    else:
        data_txt = str(data)[:10]
    bruto = f"{revenda}|{caixa}|{data_txt}|{titulo}|{valor:.2f}|{origem}"
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()


def hash_conjunto(hashes: Iterable[str]) -> str:
    """Hash do conjunto de lançamentos que compõe uma detecção.

    Ordena antes de concatenar para que a identidade não dependa da ordem em
    que o Power BI devolveu as linhas.

    Args:
        hashes: Hashes individuais dos lançamentos.

    Returns:
        Hash SHA-1 hexadecimal do conjunto.
    """
    concatenado = "|".join(sorted(hashes))
    return hashlib.sha1(concatenado.encode("utf-8")).hexdigest()


def id_deteccao(chave_cliente: str, escopo: str, hash_lancamentos: str) -> str:
    """Identidade de uma detecção: cliente + escopo + conjunto de lançamentos."""
    bruto = f"{chave_cliente}|{escopo}|{hash_lancamentos}"
    return hashlib.sha1(bruto.encode("utf-8")).hexdigest()


def garantir_tabelas(con) -> None:
    """Cria as tabelas do COAF se ainda não existirem.

    Args:
        con: Conexão DuckDB aberta em modo escrita.
    """
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABELA_DETECCAO} (
            id_deteccao VARCHAR,
            detectado_em TIMESTAMP,
            chave_cliente VARCHAR,
            nome_cliente VARCHAR,
            codigo_cliente VARCHAR,
            nome_identificado BOOLEAN,
            escopo VARCHAR,
            empresa VARCHAR,
            revendas VARCHAR,
            caixas VARCHAR,
            total DOUBLE,
            qtd_lancamentos INTEGER,
            janela_inicio DATE,
            janela_fim DATE,
            tem_caixa_sinalizado BOOLEAN,
            hash_lancamentos VARCHAR,
            primeira_deteccao BOOLEAN
        )
        """
    )
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABELA_DETECCAO_LANCAMENTO} (
            id_deteccao VARCHAR,
            hash_lancamento VARCHAR,
            data DATE,
            empresa VARCHAR,
            revenda VARCHAR,
            caixa VARCHAR,
            origem VARCHAR,
            titulo VARCHAR,
            valor DOUBLE,
            historico VARCHAR,
            nome_usuario VARCHAR,
            caixa_sinalizado BOOLEAN
        )
        """
    )
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABELA_NOTIFICACAO} (
            chave_cliente VARCHAR,
            escopo VARCHAR,
            destinatario VARCHAR,
            id_deteccao VARCHAR,
            caminho_pdf VARCHAR,
            notificado_em TIMESTAMP,
            status VARCHAR
        )
        """
    )


def clientes_ja_detectados(con, escopo: str) -> set[str]:
    """Chaves de cliente que já aparecem no histórico, para marcar a estreia.

    Args:
        con: Conexão DuckDB.
        escopo: ``"grupo"`` ou ``"empresa"``.

    Returns:
        Conjunto de ``chave_cliente`` já presentes em ``coaf_deteccao``.
    """
    linhas = con.execute(
        f"SELECT DISTINCT chave_cliente FROM {TABELA_DETECCAO} WHERE escopo = ?",
        [escopo],
    ).fetchall()
    return {linha[0] for linha in linhas}


def hashes_por_cliente(con, escopo: str) -> dict[str, str]:
    """Último ``hash_lancamentos`` registrado para cada cliente.

    É o que permite responder "o acumulado deste cliente cresceu desde a
    última execução?" sem reprocessar o histórico inteiro.

    Args:
        con: Conexão DuckDB.
        escopo: ``"grupo"`` ou ``"empresa"``.

    Returns:
        Mapa ``chave_cliente -> hash_lancamentos`` da detecção mais recente.
    """
    linhas = con.execute(
        f"""
        SELECT chave_cliente, hash_lancamentos
        FROM (
            SELECT chave_cliente, hash_lancamentos, detectado_em,
                   ROW_NUMBER() OVER (
                       PARTITION BY chave_cliente ORDER BY detectado_em DESC
                   ) AS rn
            FROM {TABELA_DETECCAO}
            WHERE escopo = ?
        )
        WHERE rn = 1
        """,
        [escopo],
    ).fetchall()
    return {linha[0]: linha[1] for linha in linhas}


def detectado_hoje(con, escopo: str, hoje: date | None = None) -> set[tuple[str, str]]:
    """Pares ``(chave_cliente, hash_lancamentos)`` já gravados hoje.

    Rodando de 30 em 30 minutos, um cliente estável geraria 24 linhas idênticas
    por dia. Esta consulta permite gravar **no máximo uma linha por cliente por
    dia** enquanto nada muda — qualquer alteração no conjunto de lançamentos
    gera hash diferente e é gravada na hora.

    Args:
        con: Conexão DuckDB.
        escopo: ``"grupo"`` ou ``"empresa"``.
        hoje: Data de referência. ``None`` usa a data atual.

    Returns:
        Conjunto de pares já registrados na data.
    """
    hoje = hoje or date.today()
    linhas = con.execute(
        f"""
        SELECT DISTINCT chave_cliente, hash_lancamentos
        FROM {TABELA_DETECCAO}
        WHERE escopo = ? AND CAST(detectado_em AS DATE) = ?
        """,
        [escopo, hoje],
    ).fetchall()
    return {(linha[0], linha[1]) for linha in linhas}


def gravar_deteccao(
    con,
    deteccao: dict[str, Any],
    lancamentos: Sequence[dict[str, Any]],
) -> None:
    """Grava uma detecção e seus lançamentos. Somente ``INSERT``.

    Args:
        con: Conexão DuckDB em modo escrita.
        deteccao: Campos da linha de ``coaf_deteccao``.
        lancamentos: Lançamentos que compuseram a detecção.
    """
    con.execute(
        f"""
        INSERT INTO {TABELA_DETECCAO} VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        [
            deteccao["id_deteccao"],
            deteccao["detectado_em"],
            deteccao["chave_cliente"],
            deteccao["nome_cliente"],
            deteccao["codigo_cliente"],
            deteccao["nome_identificado"],
            deteccao["escopo"],
            deteccao["empresa"],
            deteccao["revendas"],
            deteccao["caixas"],
            deteccao["total"],
            deteccao["qtd_lancamentos"],
            deteccao["janela_inicio"],
            deteccao["janela_fim"],
            deteccao["tem_caixa_sinalizado"],
            deteccao["hash_lancamentos"],
            deteccao["primeira_deteccao"],
        ],
    )
    for lanc in lancamentos:
        con.execute(
            f"""
            INSERT INTO {TABELA_DETECCAO_LANCAMENTO} VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                deteccao["id_deteccao"],
                lanc["hash_lancamento"],
                lanc["data"],
                lanc["empresa"],
                lanc["revenda"],
                lanc["caixa"],
                lanc["origem"],
                lanc["titulo"],
                lanc["valor"],
                lanc["historico"],
                lanc["nome_usuario"],
                lanc["caixa_sinalizado"],
            ],
        )


def registrar_notificacao(
    con,
    chave_cliente: str,
    escopo: str,
    destinatario: str,
    id_det: str,
    caminho_pdf: str,
    status: str,
    quando: datetime | None = None,
) -> None:
    """Registra um envio (ou a supressão dele) em ``coaf_notificacao``."""
    con.execute(
        f"INSERT INTO {TABELA_NOTIFICACAO} VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            chave_cliente,
            escopo,
            destinatario,
            id_det,
            caminho_pdf,
            quando or datetime.now(),
            status,
        ],
    )


def ultima_notificacao(con, escopo: str) -> dict[tuple[str, str], datetime]:
    """Data do último envio bem-sucedido, por ``(chave_cliente, destinatário)``.

    Só considera ``status = 'enviado'``: uma supressão em modo revisão não
    bloqueia o envio real quando o job passar a rodar com ``--enviar``.

    Args:
        con: Conexão DuckDB.
        escopo: ``"grupo"`` ou ``"empresa"``.

    Returns:
        Mapa ``(chave_cliente, destinatario) -> datetime do último envio``.
    """
    linhas = con.execute(
        f"""
        SELECT chave_cliente, destinatario, MAX(notificado_em)
        FROM {TABELA_NOTIFICACAO}
        WHERE escopo = ? AND status = ?
        GROUP BY chave_cliente, destinatario
        """,
        [escopo, STATUS_ENVIADO],
    ).fetchall()
    return {(linha[0], linha[1]): linha[2] for linha in linhas}


def hashes_notificados(con, escopo: str) -> dict[str, set[str]]:
    """Lançamentos que já foram declarados em alguma DMF efetivamente enviada.

    É a base do cálculo de incremento: quando um cliente já notificado volta a
    receber, o que importa para disparar nova DMF é **só o dinheiro novo** —
    o acumulado anterior não entra de novo na conta (decisão do gestor,
    19/08/2026).

    Só considera ``status = 'enviado'``. Uma supressão em modo revisão não
    "queima" o lançamento: quando o envio for ligado, ele ainda conta.

    Args:
        con: Conexão DuckDB.
        escopo: ``"grupo"`` ou ``"empresa"``.

    Returns:
        Mapa ``chave_cliente -> conjunto de hashes já declarados``.
    """
    linhas = con.execute(
        f"""
        SELECT n.chave_cliente, l.hash_lancamento
        FROM {TABELA_NOTIFICACAO} n
        JOIN {TABELA_DETECCAO_LANCAMENTO} l ON l.id_deteccao = n.id_deteccao
        WHERE n.escopo = ? AND n.status = ?
        """,
        [escopo, STATUS_ENVIADO],
    ).fetchall()
    mapa: dict[str, set[str]] = {}
    for chave, hash_lanc in linhas:
        mapa.setdefault(chave, set()).add(hash_lanc)
    return mapa


def clientes_notificados(con, escopo: str) -> set[str]:
    """Clientes que já receberam ao menos uma DMF por e-mail."""
    linhas = con.execute(
        f"SELECT DISTINCT chave_cliente FROM {TABELA_NOTIFICACAO} "
        f"WHERE escopo = ? AND status = ?",
        [escopo, STATUS_ENVIADO],
    ).fetchall()
    return {linha[0] for linha in linhas}


def carregar_historico(con, escopo: str | None = None) -> pd.DataFrame:
    """Histórico consolidado: uma linha por cliente, com a evolução do caso.

    Agrega ``coaf_deteccao`` por **código do cliente** (``CAIXAS[CLIENTE]``),
    não por ``chave_cliente``. Motivo: a chave de identidade já mudou de
    esquema duas vezes (nome extraído do histórico -> nome do cadastro
    ``NOME_CLIENTE`` -> código, decisão final do gestor em 26/08/2026 — ver
    ``dictionary/regras_negocio.md``), e ``coaf_deteccao`` é append-only —
    nada é apagado nem reescrito. Agrupar por ``chave_cliente`` faria o mesmo
    cliente real aparecer várias vezes no relatório, uma por esquema que ele
    já teve. O código nunca mudou (é a própria coluna de origem), por isso é
    a chave de consolidação estável para ESTE relatório específico — sem
    tocar nas tabelas de origem, que continuam intactas como registro fiel do
    que aconteceu em cada momento.

    Cada coluna "atual" (nome, chave, identificação, empresa, revenda) usa
    ``ARG_MAX(..., detectado_em)``: o valor da detecção mais recente daquele
    código, não um valor arbitrário entre os vários esquemas antigos.

    É a fonte do relatório ``reports/coaf_historico.md`` e da tool MCP
    ``historico_coaf``.

    Args:
        con: Conexão DuckDB.
        escopo: Filtra por escopo. ``None`` traz todos.

    Returns:
        DataFrame ordenado pela primeira detecção (mais recente primeiro).
        Vazio se ainda não houver histórico.
    """
    filtro = "WHERE d.escopo = ?" if escopo else ""
    parametros = [escopo] if escopo else []
    return con.execute(
        f"""
        SELECT
            d.codigo_cliente,
            ARG_MAX(d.chave_cliente, d.detectado_em)      AS chave_cliente,
            ARG_MAX(d.nome_cliente, d.detectado_em)       AS nome_cliente,
            ARG_MAX(d.nome_identificado, d.detectado_em)  AS nome_identificado,
            ARG_MAX(d.escopo, d.detectado_em)             AS escopo,
            ARG_MAX(d.empresa, d.detectado_em)            AS empresa,
            ARG_MAX(d.revendas, d.detectado_em)           AS revendas,
            MIN(d.detectado_em)                           AS primeira_deteccao_em,
            MAX(d.detectado_em)                           AS ultima_deteccao_em,
            COUNT(*)                                      AS vezes_detectado,
            MAX(d.total)                                  AS maior_total,
            MAX(d.qtd_lancamentos)                        AS qtd_lancamentos,
            BOOL_OR(d.tem_caixa_sinalizado)               AS tem_caixa_sinalizado,
            MAX(n.notificado_em)                          AS notificado_em
        FROM {TABELA_DETECCAO} d
        LEFT JOIN {TABELA_NOTIFICACAO} n
               ON n.chave_cliente = d.chave_cliente
              AND n.escopo = d.escopo
              AND n.status = '{STATUS_ENVIADO}'
        {filtro}
        GROUP BY d.codigo_cliente
        ORDER BY primeira_deteccao_em DESC
        """,
        parametros,
    ).fetchdf()


def lancamentos_da_deteccao(con, id_det: str) -> pd.DataFrame:
    """Recebimentos gravados para uma detecção específica.

    Permite reconstruir a DMF exatamente como foi enviada, mesmo que a base do
    Power BI tenha mudado depois.
    """
    return con.execute(
        f"""
        SELECT * FROM {TABELA_DETECCAO_LANCAMENTO}
        WHERE id_deteccao = ?
        ORDER BY data ASC
        """,
        [id_det],
    ).fetchdf()


def abrir(somente_leitura: bool = False):
    """Abre a conexão do warehouse já com as tabelas do COAF garantidas.

    Args:
        somente_leitura: Se ``True``, não tenta criar tabela (o engine recusa
            escrita) — use apenas para consulta de histórico.

    Returns:
        Conexão DuckDB aberta. O chamador é responsável por fechá-la.
    """
    con = conectar(somente_leitura=somente_leitura)
    if not somente_leitura:
        garantir_tabelas(con)
    return con
