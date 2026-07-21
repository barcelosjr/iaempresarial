"""Gera o briefing diário para a diretoria em ``reports/``.

Lê os KPIs definidos em ``analysis/templates/briefing.yaml``, executa cada
consulta DAX (somente leitura) no Power BI e monta um relatório Markdown em
``reports/briefing_YYYY-MM-DD.md``.

Erros por bloco (ex.: nome de medida inexistente) não interrompem o briefing —
são registrados na seção correspondente, para você ajustar o template.

Uso:
    python analysis/briefing_diario.py [caminho_do_template.yaml]
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (  # noqa: E402
    RAIZ_PROJETO,
    ErroConfiguracao,
    carregar_configuracao,
)
from powerbi.client import ErroPowerBI, PowerBIClient  # noqa: E402

TEMPLATE_PADRAO = RAIZ_PROJETO / "analysis" / "templates" / "briefing.yaml"
PASTA_REPORTS = RAIZ_PROJETO / "reports"


def _carregar_template(caminho: Path) -> dict:
    """Carrega e valida o template YAML do briefing.

    Args:
        caminho: Caminho do arquivo de template.

    Returns:
        Dicionário do template.

    Raises:
        FileNotFoundError: Se o template não existir.
        ValueError: Se o template não tiver blocos.
    """
    if not caminho.exists():
        raise FileNotFoundError(f"Template não encontrado: {caminho}")
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    if not dados.get("blocos"):
        raise ValueError("O template não contém a lista 'blocos'.")
    return dados


def _executar_bloco(cliente: PowerBIClient, bloco: dict, dataset_padrao: str | None) -> str:
    """Executa um bloco do briefing e devolve sua seção em Markdown.

    Args:
        cliente: Cliente Power BI.
        bloco: Dicionário do bloco (nome, dax, dataset opcional).
        dataset_padrao: Apelido de dataset padrão do template.

    Returns:
        A seção Markdown do bloco (com resultado ou erro).
    """
    nome = bloco.get("nome", "(sem nome)")
    dax = bloco.get("dax", "").strip()
    dataset = bloco.get("dataset", dataset_padrao)

    linhas = [f"## {nome}", ""]
    if not dax:
        linhas.append("_Bloco sem consulta DAX definida._\n")
        return "\n".join(linhas)

    try:
        df = cliente.execute_dax(dax, dataset_id=dataset)
        if df.empty:
            linhas.append("_Sem dados para o período._")
        else:
            linhas.append("```")
            linhas.append(df.to_string(index=False))
            linhas.append("```")
    except ErroPowerBI as exc:
        linhas.append(f"> ⚠️ **Não foi possível calcular este bloco.**\n>\n> {exc}")
        linhas.append("")
        linhas.append(
            "_Ajuste os nomes de medidas/tabelas em "
            "`analysis/templates/briefing.yaml` conforme o dicionário do modelo._"
        )
    linhas.append("")
    return "\n".join(linhas)


def gerar_briefing(caminho_template: Path | None = None) -> Path:
    """Gera o briefing diário e devolve o caminho do arquivo criado.

    Args:
        caminho_template: Template YAML alternativo (opcional).

    Returns:
        Caminho do relatório gerado em ``reports/``.

    Raises:
        ErroConfiguracao: Se as credenciais não estiverem configuradas.
        FileNotFoundError | ValueError: Se o template for inválido.
    """
    template = _carregar_template(caminho_template or TEMPLATE_PADRAO)
    config = carregar_configuracao()
    cliente = PowerBIClient(config=config)

    hoje = date.today().isoformat()
    titulo = template.get("titulo", "Briefing diário")
    dataset_padrao = template.get("dataset")

    partes = [
        f"# {titulo}",
        "",
        f"**Data:** {hoje}",
        "",
        "> Relatório gerado automaticamente por `analysis/briefing_diario.py`. "
        "Valores vêm das medidas oficiais do modelo semântico do Power BI.",
        "",
        "---",
        "",
    ]
    for bloco in template["blocos"]:
        partes.append(_executar_bloco(cliente, bloco, dataset_padrao))

    PASTA_REPORTS.mkdir(parents=True, exist_ok=True)
    destino = PASTA_REPORTS / f"briefing_{hoje}.md"
    destino.write_text("\n".join(partes), encoding="utf-8")
    return destino


def main() -> int:
    """CLI do briefing. Devolve 0 em sucesso, 1 em falha de configuração."""
    caminho = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    try:
        destino = gerar_briefing(caminho)
    except ErroConfiguracao as exc:
        print(f"❌ Configuração incompleta:\n{exc}")
        return 1
    except (FileNotFoundError, ValueError) as exc:
        print(f"❌ {exc}")
        return 1

    print(f"✅ Briefing gerado em: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
