"""Gera a auditoria diária de lançamentos de caixa em ``reports/``.

Roda as 14 regras de ``powerbi/dax_auditoria.py`` — o mesmo motor da tool MCP
``relatorio_auditoria`` — e reaproveita seu formatador
(``mcp_server.server._formatar_auditoria``) para não duplicar a lógica de
agrupamento por severidade e de segregação de funções. Diferente da tool MCP
(sob demanda, com filtros), esta rotina sempre roda a base inteira,
consolidado, sem período — pensada para rodar todo dia e comparar.

Também grava o snapshot de saldo do dia no DuckDB local
(``local_data/snapshots.py``), para dar histórico real a R10/R13 ao longo do
tempo. Uma falha ao gravar o snapshot não invalida o relatório — é anotada
no rodapé e a auditoria é salva do mesmo jeito.

Uso:
    python analysis/auditoria_diaria.py [nome_do_revisor]

``nome_do_revisor`` deve bater exatamente com o valor de ``NOME_USUARIO`` no
Power BI — é o que ativa a segregação de funções (bloco "Requer revisão
independente" quando esse usuário aparece nas próprias exceções).
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import RAIZ_PROJETO, ErroConfiguracao, carregar_configuracao  # noqa: E402
from local_data.snapshots import DATASET_PADRAO, salvar_snapshot_caixa  # noqa: E402
from mcp_server.server import _formatar_auditoria, _titulo  # noqa: E402
from powerbi import dax_auditoria as aud  # noqa: E402
from powerbi.client import ErroPowerBI, PowerBIClient  # noqa: E402

PASTA_REPORTS = RAIZ_PROJETO / "reports"


def _rodar_todas_as_regras(
    cliente: PowerBIClient, dataset: str | None
) -> tuple[dict[str, tuple], dict[str, str]]:
    """Executa as 14 regras de auditoria na base inteira, sem período/empresa.

    Returns:
        Tupla ``(resultados, erros)`` no formato esperado por
        :func:`mcp_server.server._formatar_auditoria`.
    """
    resultados: dict[str, tuple] = {}
    erros: dict[str, str] = {}
    for rid, regra in aud.REGRAS.items():
        kwargs: dict[str, object] = {"empresa": None}
        if regra.aceita_periodo:
            kwargs["periodo"] = None
            kwargs["modo"] = "mensal"
        try:
            query = regra.construtor(**kwargs)
            df = cliente.execute_dax(query, dataset_id=dataset)
        except ErroPowerBI as exc:
            erros[rid] = str(exc)
            continue
        resultados[rid] = (df, query)
    return resultados, erros


def gerar_auditoria_diaria(
    usuario_revisor: str | None = None, dataset: str | None = DATASET_PADRAO
) -> Path:
    """Gera o relatório de auditoria do dia e devolve o caminho salvo.

    Args:
        usuario_revisor: Nome exato de ``NOME_USUARIO`` de quem vai revisar
            este relatório — ativa a segregação de funções.
        dataset: Apelido ou GUID do dataset de lançamentos de caixa.

    Returns:
        Caminho do relatório gerado em ``reports/``.

    Raises:
        ErroConfiguracao: Se as credenciais não estiverem configuradas.
    """
    config = carregar_configuracao()
    cliente = PowerBIClient(config=config)

    resultados, erros = _rodar_todas_as_regras(cliente, dataset)
    hoje = date.today().isoformat()
    titulo = _titulo("Auditoria de Lançamentos de Caixa", "toda a base (consolidado)", None)
    corpo = _formatar_auditoria(resultados, erros, titulo, usuario_revisor)

    try:
        n_snapshot = salvar_snapshot_caixa(cliente=cliente, dataset=dataset)
        nota = f"\n\n_Snapshot de saldo do dia gravado no DuckDB local ({n_snapshot} caixa(s))._"
    except Exception as exc:  # noqa: BLE001 — snapshot não pode derrubar a auditoria
        nota = f"\n\n_⚠️ Snapshot de saldo não pôde ser gravado: {exc}_"

    PASTA_REPORTS.mkdir(parents=True, exist_ok=True)
    destino = PASTA_REPORTS / f"auditoria_caixa_{hoje}.md"
    destino.write_text(corpo + nota, encoding="utf-8")
    return destino


def main() -> int:
    """CLI da auditoria diária. Devolve 0 em sucesso, 1 em falha de configuração."""
    usuario_revisor = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        destino = gerar_auditoria_diaria(usuario_revisor)
    except ErroConfiguracao as exc:
        print(f"❌ Configuração incompleta:\n{exc}")
        return 1

    print(f"✅ Auditoria de caixa gerada em: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
