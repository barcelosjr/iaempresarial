"""Ingestão de arquivos avulsos (CSV/XLSX) para o DuckDB local.

Dados que não existem no Power BI (planilhas soltas, textos de pós-venda,
listas manuais) entram num banco DuckDB local. Cada arquivo vira uma tabela
com o nome normalizado do arquivo.

Também oferece a leitura SOMENTE-SELECT usada pela ferramenta MCP
``consultar_duckdb``: a conexão é aberta em modo *read only* e o SQL é
validado para recusar qualquer comando que não seja uma consulta.

Uso (CLI):
    python local_data/ingest.py <pasta_com_arquivos>
    python local_data/ingest.py arquivo1.csv arquivo2.xlsx
"""

from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

import duckdb
import pandas as pd

# Permite rodar como script (`python local_data/ingest.py ...`).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import RAIZ_PROJETO  # noqa: E402

# Caminho padrão do banco local (gitignored).
CAMINHO_BANCO: Path = RAIZ_PROJETO / "local_data" / "warehouse.duckdb"

# Extensões de arquivo suportadas na ingestão.
EXTENSOES_SUPORTADAS: tuple[str, ...] = (".csv", ".xlsx", ".xls")

# Palavras-chave proibidas em consultas de leitura (defesa em profundidade).
_PALAVRAS_PROIBIDAS = (
    "insert", "update", "delete", "drop", "create", "alter", "attach",
    "detach", "copy", "pragma", "install", "load", "export", "import",
    "call", "set", "reset", "vacuum", "truncate", "replace", "merge",
)


class ErroDuckDB(Exception):
    """Erro na ingestão ou consulta ao DuckDB local."""


def normalizar_nome_tabela(nome_arquivo: str) -> str:
    """Normaliza o nome de um arquivo para um nome de tabela SQL válido.

    Remove acentos, troca separadores por ``_`` e minúsculas. Ex.:
    ``"Pós-Venda 2026.xlsx"`` -> ``"pos_venda_2026"``.

    Args:
        nome_arquivo: Nome do arquivo (com ou sem extensão).

    Returns:
        Nome de tabela normalizado.
    """
    base = Path(nome_arquivo).stem
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", base) if not unicodedata.combining(c)
    )
    limpo = re.sub(r"[^0-9a-zA-Z]+", "_", sem_acento).strip("_").lower()
    if not limpo:
        limpo = "tabela"
    if limpo[0].isdigit():
        limpo = f"t_{limpo}"
    return limpo


def conectar(somente_leitura: bool = False) -> duckdb.DuckDBPyConnection:
    """Abre uma conexão com o banco DuckDB local.

    Args:
        somente_leitura: Se ``True``, abre em modo *read only* (nenhuma
            gravação é possível no nível do engine).

    Returns:
        Conexão DuckDB.
    """
    CAMINHO_BANCO.parent.mkdir(parents=True, exist_ok=True)
    if somente_leitura and not CAMINHO_BANCO.exists():
        raise ErroDuckDB(
            f"Banco local ainda não existe em {CAMINHO_BANCO}. "
            "Rode a ingestão antes: python local_data/ingest.py <pasta>."
        )
    return duckdb.connect(str(CAMINHO_BANCO), read_only=somente_leitura)


def _ler_arquivo(caminho: Path) -> pd.DataFrame:
    """Lê um CSV/XLSX em um DataFrame."""
    if caminho.suffix.lower() == ".csv":
        return pd.read_csv(caminho)
    return pd.read_excel(caminho)  # requer openpyxl


def ingerir_arquivo(caminho: Path | str, con: duckdb.DuckDBPyConnection | None = None) -> str:
    """Ingere um único arquivo CSV/XLSX no DuckDB.

    Args:
        caminho: Caminho do arquivo.
        con: Conexão existente (opcional). Se omitida, abre e fecha uma nova.

    Returns:
        O nome da tabela criada.

    Raises:
        ErroDuckDB: Se o arquivo não existir ou o formato não for suportado.
    """
    caminho = Path(caminho)
    if not caminho.exists():
        raise ErroDuckDB(f"Arquivo não encontrado: {caminho}")
    if caminho.suffix.lower() not in EXTENSOES_SUPORTADAS:
        raise ErroDuckDB(
            f"Formato não suportado: {caminho.suffix}. "
            f"Use um destes: {', '.join(EXTENSOES_SUPORTADAS)}."
        )

    fechar = con is None
    con = con or conectar()
    try:
        df = _ler_arquivo(caminho)  # noqa: F841  (usado via SQL abaixo)
        tabela = normalizar_nome_tabela(caminho.name)
        con.execute(f'CREATE OR REPLACE TABLE "{tabela}" AS SELECT * FROM df')
        return tabela
    finally:
        if fechar:
            con.close()


def ingerir_pasta(pasta: Path | str) -> list[tuple[str, str, int]]:
    """Ingere todos os arquivos suportados de uma pasta.

    Args:
        pasta: Caminho da pasta com os arquivos.

    Returns:
        Lista de tuplas ``(arquivo, tabela, n_linhas)`` do que foi carregado.

    Raises:
        ErroDuckDB: Se a pasta não existir.
    """
    pasta = Path(pasta)
    if not pasta.is_dir():
        raise ErroDuckDB(f"Pasta não encontrada: {pasta}")

    carregados: list[tuple[str, str, int]] = []
    con = conectar()
    try:
        for arquivo in sorted(pasta.iterdir()):
            if arquivo.suffix.lower() not in EXTENSOES_SUPORTADAS:
                continue
            tabela = ingerir_arquivo(arquivo, con=con)
            n = con.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0]
            carregados.append((arquivo.name, tabela, int(n)))
    finally:
        con.close()
    return carregados


def validar_select(sql: str) -> None:
    """Valida que o SQL é uma única consulta de leitura (SELECT/WITH).

    Args:
        sql: Comando SQL a validar.

    Raises:
        ErroDuckDB: Se o comando não for uma consulta de leitura única.
    """
    if not sql or not sql.strip():
        raise ErroDuckDB("Consulta vazia.")

    # Remove comentários de linha e de bloco antes de analisar.
    sem_comentarios = re.sub(r"--[^\n]*", " ", sql)
    sem_comentarios = re.sub(r"/\*.*?\*/", " ", sem_comentarios, flags=re.DOTALL)
    limpo = sem_comentarios.strip().rstrip(";").strip()

    if ";" in limpo:
        raise ErroDuckDB("Apenas uma consulta por vez é permitida (sem ';').")

    primeira = limpo.split(None, 1)[0].lower() if limpo else ""
    if primeira not in ("select", "with"):
        raise ErroDuckDB(
            "Somente consultas SELECT (ou WITH ... SELECT) são permitidas no "
            "DuckDB local. Comando recusado."
        )

    tokens = set(re.findall(r"[a-zA-Z_]+", limpo.lower()))
    proibidas = tokens & set(_PALAVRAS_PROIBIDAS)
    if proibidas:
        raise ErroDuckDB(
            f"Comando não permitido em consulta de leitura: {', '.join(sorted(proibidas))}."
        )


def consultar_select(sql: str, limite: int = 100) -> pd.DataFrame:
    """Executa uma consulta SELECT no DuckDB local (somente leitura).

    Args:
        sql: Consulta SELECT/WITH.
        limite: Limite de linhas aplicado por segurança (envolve a consulta).

    Returns:
        DataFrame com o resultado.

    Raises:
        ErroDuckDB: Se o SQL não for uma leitura válida.
    """
    validar_select(sql)
    con = conectar(somente_leitura=True)
    try:
        interna = sql.strip().rstrip(";")
        envolvida = f"SELECT * FROM (\n{interna}\n) AS _sub LIMIT {int(limite)}"
        return con.execute(envolvida).fetchdf()
    finally:
        con.close()


def listar_tabelas() -> list[str]:
    """Lista as tabelas existentes no DuckDB local.

    Returns:
        Lista de nomes de tabela (vazia se o banco ainda não existir).
    """
    if not CAMINHO_BANCO.exists():
        return []
    con = conectar(somente_leitura=True)
    try:
        linhas = con.execute("SHOW TABLES").fetchall()
        return [linha[0] for linha in linhas]
    finally:
        con.close()


def main() -> int:
    """CLI de ingestão. Devolve 0 em sucesso, 1 em falha."""
    if len(sys.argv) < 2:
        print("Uso: python local_data/ingest.py <pasta_ou_arquivos...>")
        return 1

    alvos = sys.argv[1:]
    total = 0
    try:
        if len(alvos) == 1 and Path(alvos[0]).is_dir():
            carregados = ingerir_pasta(alvos[0])
            for arquivo, tabela, n in carregados:
                print(f"  ✅ {arquivo} -> tabela '{tabela}' ({n} linhas)")
                total += 1
        else:
            con = conectar()
            try:
                for alvo in alvos:
                    tabela = ingerir_arquivo(alvo, con=con)
                    n = con.execute(f'SELECT COUNT(*) FROM "{tabela}"').fetchone()[0]
                    print(f"  ✅ {alvo} -> tabela '{tabela}' ({n} linhas)")
                    total += 1
            finally:
                con.close()
    except ErroDuckDB as exc:
        print(f"❌ {exc}")
        return 1

    print(f"\nConcluído: {total} arquivo(s) carregado(s) em {CAMINHO_BANCO}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
