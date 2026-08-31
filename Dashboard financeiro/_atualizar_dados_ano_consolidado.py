"""Atualiza o bloco ``DADOS_ANO`` do painel consolidado (``painel_financeiro.html``)
com dados frescos gerados por ``gerar_dados_consolidado_ano.py --ano 2026/2025``.

Versão consolidada de ``_atualizar_dados_ano_empresa.py`` — mesmo padrão, mas
sem ``dreDescAnt`` por ano (o painel consolidado reconstrói o ano anterior do
drill-down direto de ``DADOS_ANO[ano-1].dreDesc`` dentro de ``aplicarAno()``).

Uso (a partir da raiz do projeto), depois de gerar os dois arquivos .js na pasta
de scratch (por padrão ``Dashboard financeiro/_scratch/``, fixa e independente
de sessão)::

    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dados_consolidado_ano.py" --ano 2026 --mes-final 8 > "Dashboard financeiro/_scratch/consol_2026.js"
    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dados_consolidado_ano.py" --ano 2025 --mes-final 12 > "Dashboard financeiro/_scratch/consol_2025.js"
    .venv\\Scripts\\python.exe "Dashboard financeiro/_atualizar_dados_ano_consolidado.py" --mes-final-2026 8

Também reescreve ``var SNAPSHOT`` para a data de hoje automaticamente.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
from pathlib import Path

PASTA = Path(__file__).resolve().parent
BUILD = PASTA / "build"
HTML = BUILD / "painel_financeiro.html"
SCRATCH_PADRAO = PASTA / "_scratch"

MESES_ROTULO = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']


def _meses_js(mes_final: int) -> str:
    return "[" + ",".join(f"'{m}'" for m in MESES_ROTULO[:mes_final]) + "]"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mes-final-2026", type=int, default=6)
    ap.add_argument("--mes-final-2025", type=int, default=12)
    ap.add_argument("--scratch", type=Path, default=SCRATCH_PADRAO, help="Pasta com consol_2026.js/consol_2025.js (padrão: Dashboard financeiro/_scratch)")
    args = ap.parse_args()

    html = HTML.read_text(encoding="utf-8")

    consol_2026 = (args.scratch / "consol_2026.js").read_text(encoding="utf-8")
    consol_2025 = (args.scratch / "consol_2025.js").read_text(encoding="utf-8")

    meses_2026 = _meses_js(args.mes_final_2026)
    meses_2025 = _meses_js(args.mes_final_2025)

    novo_bloco = (
        "  var DADOS_ANO = {\n"
        "    '2026': {\n"
        f"    meses: {meses_2026},\n"
        + consol_2026.rstrip("\n")
        + "\n    },\n"
        "    '2025': {\n"
        f"    meses: {meses_2025},\n"
        + consol_2025.rstrip("\n")
        + "\n    }\n"
        "  };\n"
    )

    padrao = re.compile(r"  var DADOS_ANO = \{.*?\n  \};\n", re.S)
    m = padrao.search(html)
    if not m:
        raise SystemExit("bloco DADOS_ANO não encontrado")
    html = html[: m.start()] + novo_bloco + html[m.end() :]

    hoje = _dt.date.today().strftime("%d/%m/%Y")
    html, n_snap = re.subn(r"var SNAPSHOT = '\d{2}/\d{2}/\d{4}';", f"var SNAPSHOT = '{hoje}';", html)
    if n_snap == 0:
        raise SystemExit("var SNAPSHOT não encontrado — não deu para atualizar a data")

    HTML.write_text(html, encoding="utf-8")
    print(f"ok — bytes finais: {len(html)} — SNAPSHOT = {hoje}")


if __name__ == "__main__":
    main()
