"""Gera o dicionário de dados (``dictionary/modelo_semantico.md``).

Extrai o esquema do modelo semântico real (tabelas, colunas, medidas e
relacionamentos) e escreve um arquivo Markdown legível. Este arquivo é o
"mapa" que o Claude lê antes de escrever consultas DAX.

Uso:
    python scripts/gerar_dicionario.py [apelido_ou_id_do_dataset]
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import RAIZ_PROJETO, ErroConfiguracao, carregar_configuracao  # noqa: E402
from powerbi.client import ErroPowerBI, PowerBIClient  # noqa: E402
from powerbi.schema import EsquemaModelo, extrair_esquema  # noqa: E402

SAIDA = RAIZ_PROJETO / "dictionary" / "modelo_semantico.md"


def _secao_tabelas(esquema: EsquemaModelo) -> list[str]:
    """Monta a seção de tabelas e colunas do dicionário."""
    linhas = ["## Tabelas e colunas", ""]
    if esquema.tabelas.empty:
        linhas.append("_Nenhuma tabela extraída._\n")
        return linhas

    for _, tab in esquema.tabelas.iterrows():
        nome = tab["nome"]
        linhas.append(f"### {nome}")
        if tab.get("descricao"):
            linhas.append(f"> {tab['descricao']}")
        linhas.append("")
        cols = (
            esquema.colunas[esquema.colunas["tabela"] == nome]
            if not esquema.colunas.empty
            else esquema.colunas
        )
        if cols.empty:
            linhas.append("_(sem colunas visíveis)_\n")
            continue
        linhas.append("| Coluna | Tipo | Descrição |")
        linhas.append("|---|---|---|")
        for _, col in cols.iterrows():
            descricao = col.get("descricao", "") or ""
            linhas.append(f"| {col['nome']} | {col['tipo']} | {descricao} |")
        linhas.append("")
    return linhas


def _secao_medidas(esquema: EsquemaModelo) -> list[str]:
    """Monta a seção de medidas (com expressões DAX) do dicionário."""
    linhas = ["## Medidas oficiais do modelo", ""]
    if esquema.medidas.empty:
        linhas.append("_Nenhuma medida extraída._\n")
        return linhas
    linhas.append(
        "> Use estas medidas **antes** de criar cálculos próprios — elas "
        "garantem consistência com os dashboards da diretoria.\n"
    )
    for _, med in esquema.medidas.iterrows():
        cabecalho = f"### {med['nome']}"
        if med.get("tabela"):
            cabecalho += f"  \n_Tabela:_ `{med['tabela']}`"
        linhas.append(cabecalho)
        if med.get("descricao"):
            linhas.append(f"> {med['descricao']}")
        if med.get("formato"):
            linhas.append(f"_Formato:_ `{med['formato']}`")
        expressao = med.get("expressao", "") or ""
        linhas.append("```dax")
        linhas.append(expressao if expressao else "-- (expressão não disponível)")
        linhas.append("```")
        linhas.append("")
    return linhas


def _secao_relacionamentos(esquema: EsquemaModelo) -> list[str]:
    """Monta a seção de relacionamentos do dicionário."""
    linhas = ["## Relacionamentos", ""]
    if esquema.relacionamentos.empty:
        linhas.append("_Nenhum relacionamento extraído._\n")
        return linhas
    linhas.append("| De | Para | Cardinalidade | Ativo |")
    linhas.append("|---|---|---|---|")
    for _, rel in esquema.relacionamentos.iterrows():
        ativo = "sim" if rel.get("ativa", True) else "não"
        linhas.append(
            f"| {rel['de']} | {rel['para']} | {rel.get('cardinalidade', '—')} | {ativo} |"
        )
    linhas.append("")
    return linhas


def gerar_markdown(esquema: EsquemaModelo, nome_dataset: str) -> str:
    """Monta o texto Markdown completo do dicionário.

    Args:
        esquema: Esquema extraído do modelo.
        nome_dataset: Nome (ou id) do dataset, para o cabeçalho.

    Returns:
        Conteúdo Markdown pronto para gravar.
    """
    agora = datetime.now().strftime("%Y-%m-%d %H:%M")
    linhas = [
        "# Dicionário de dados — modelo semântico",
        "",
        "> **Gerado automaticamente** por `scripts/gerar_dicionario.py`. "
        "Não edite à mão — rode o script novamente para atualizar.",
        "",
        f"- **Dataset:** {nome_dataset}",
        f"- **Gerado em:** {agora}",
        "",
    ]
    if esquema.limitacoes:
        linhas.append("## ⚠️ Limitações desta extração")
        for lim in esquema.limitacoes:
            linhas.append(f"- {lim}")
        linhas.append("")
    linhas += _secao_tabelas(esquema)
    linhas += _secao_medidas(esquema)
    linhas += _secao_relacionamentos(esquema)
    return "\n".join(linhas) + "\n"


def main() -> int:
    """Gera o dicionário. Devolve 0 em sucesso, 1 em falha."""
    dataset = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        config = carregar_configuracao()
    except ErroConfiguracao as exc:
        print(f"❌ {exc}")
        return 1

    cliente = PowerBIClient(config=config)
    print("Extraindo esquema do modelo semântico… (isto executa consultas INFO.* no servidor)")
    try:
        esquema = extrair_esquema(cliente, dataset_id=dataset)
    except ErroPowerBI as exc:
        print(f"❌ Falha ao extrair o esquema:\n{exc}")
        return 1

    try:
        info = cliente.get_dataset_info(dataset)
        nome_dataset = info.get("name", dataset or config.dataset_id)
    except ErroPowerBI:
        nome_dataset = dataset or config.dataset_id

    conteudo = gerar_markdown(esquema, nome_dataset)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text(conteudo, encoding="utf-8")

    n_tab = len(esquema.tabelas)
    n_med = len(esquema.medidas)
    print(f"✅ Dicionário gerado em {SAIDA} ({n_tab} tabelas, {n_med} medidas).")
    if esquema.limitacoes:
        print("⚠️  Houve limitações na extração — veja a seção correspondente no arquivo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
