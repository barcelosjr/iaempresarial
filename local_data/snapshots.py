"""Snapshot diário de saldo de caixa, persistido no DuckDB local.

Complementa a auditoria de lançamentos de caixa (``powerbi/dax_auditoria.py``):
guarda o saldo, entradas e saídas por REVENDA+CAIXA de cada dia em que a
rotina roda, formando um histórico que R10 (concentração atípica) e R13
(usuário fora do padrão) poderão usar como baseline persistido — hoje elas
calculam estatística só em cima da própria janela consultada, sem memória
entre execuções.

Reaproveita o escopo padrão de auditoria (``dax_auditoria._base()``) — o
snapshot já sai sem os caixas de concentração e sem as linhas de abertura,
sem duplicar a regra de exclusão aqui.

Uso:
    python local_data/snapshots.py [apelido_ou_id_do_dataset]
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import ErroConfiguracao, carregar_configuracao  # noqa: E402
from local_data.ingest import conectar  # noqa: E402
from powerbi import dax_auditoria as aud  # noqa: E402
from powerbi.client import ErroPowerBI, PowerBIClient  # noqa: E402

#: Dataset padrão do snapshot — o de lançamentos de caixa, não o do .env.
DATASET_PADRAO = "controlador"

TABELA_SNAPSHOT = "snapshot_caixa_diario"


def _normalizar_coluna(nome: str) -> str:
    """Extrai o nome "puro" de uma coluna DAX (``"CAIXAS[REVENDA]"`` -> ``"REVENDA"``)."""
    texto = str(nome)
    if "[" in texto and texto.endswith("]"):
        return texto[texto.index("[") + 1 : -1]
    return texto.strip("[]")


def _query_saldo_diario() -> str:
    """Consulta DAX: saldo/entradas/saídas por REVENDA+CAIXA, no escopo padrão de auditoria."""
    base = aud._base()  # sem empresa/período — snapshot é sempre da base inteira
    return (
        "EVALUATE\n"
        "SUMMARIZECOLUMNS(\n"
        f"    {aud._col(aud.COL_REVENDA)}, {aud._col(aud.COL_CAIXA)},\n"
        f"    {base},\n"
        f'    "Saldo", SUM({aud._col(aud.COL_VALOR)}),\n'
        f'    "Entradas", CALCULATE(SUM({aud._col(aud.COL_VALOR)}), {aud._col(aud.COL_PR)} = "R"),\n'
        f'    "Saidas", CALCULATE(SUM({aud._col(aud.COL_VALOR)}), {aud._col(aud.COL_PR)} = "P")\n'
        ")"
    )


def _garantir_tabela(con) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {TABELA_SNAPSHOT} (
            data_snapshot DATE,
            revenda VARCHAR,
            caixa VARCHAR,
            saldo DOUBLE,
            entradas DOUBLE,
            saidas DOUBLE
        )
        """
    )


def salvar_snapshot_caixa(
    cliente: PowerBIClient | None = None, dataset: str | None = DATASET_PADRAO
) -> int:
    """Consulta o saldo atual por REVENDA+CAIXA e grava no DuckDB local.

    Idempotente por dia: remove o snapshot de hoje antes de inserir — rodar
    a rotina duas vezes no mesmo dia não duplica linhas, só substitui pela
    leitura mais recente.

    Args:
        cliente: Cliente Power BI já autenticado. Se omitido, cria um novo
            (requer ``.env`` configurado).
        dataset: Apelido ou GUID do dataset. Padrão: ``"controlador"``.

    Returns:
        Número de linhas (combinações REVENDA+CAIXA) gravadas.

    Raises:
        ErroPowerBI: Se a consulta ao Power BI falhar.
    """
    cliente = cliente or PowerBIClient(config=carregar_configuracao())
    df = cliente.execute_dax(_query_saldo_diario(), dataset_id=dataset)
    df = df.rename(columns=_normalizar_coluna)

    hoje = date.today()
    con = conectar()
    try:
        _garantir_tabela(con)
        con.execute(f"DELETE FROM {TABELA_SNAPSHOT} WHERE data_snapshot = ?", [hoje])
        if not df.empty:
            registros = df[["REVENDA", "CAIXA", "Saldo", "Entradas", "Saidas"]].copy()
            registros.insert(0, "data_snapshot", hoje)
            con.execute(
                f"INSERT INTO {TABELA_SNAPSHOT} SELECT * FROM registros"
            )
        return len(df)
    finally:
        con.close()


def main() -> int:
    """CLI do snapshot. Devolve 0 em sucesso, 1 em falha de configuração/API."""
    dataset = sys.argv[1] if len(sys.argv) > 1 else DATASET_PADRAO
    try:
        n = salvar_snapshot_caixa(dataset=dataset)
    except ErroConfiguracao as exc:
        print(f"❌ Configuração incompleta:\n{exc}")
        return 1
    except ErroPowerBI as exc:
        print(f"❌ Erro ao consultar o Power BI:\n{exc}")
        return 1

    print(f"✅ Snapshot de {n} caixa(s) gravado em local_data/warehouse.duckdb ({TABELA_SNAPSHOT}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
