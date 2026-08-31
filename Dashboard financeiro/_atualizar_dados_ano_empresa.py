"""Atualiza o bloco ``DADOS_ANO`` de um painel de marca única com dados frescos,
gerados por gerar_dados_empresa_ano.py --empresa <MARCA> --ano 2026/2025.

Versão genérica de ``_atualizar_dados_ano_corretora.py``/``_atualizar_dados_ano_royal.py``.

Uso (a partir da raiz do projeto), depois de gerar os dois arquivos .js na pasta
de scratch (por padrão ``Dashboard financeiro/_scratch/``, fixa e independente
de sessão — nunca a scratchpad temporária da sessão, que some quando a sessão
termina)::

    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dados_empresa_ano.py" --empresa KOBE --ano 2026 --mes-final 8 > "Dashboard financeiro/_scratch/ano_2026.js"
    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dados_empresa_ano.py" --empresa KOBE --ano 2025 --mes-final 12 > "Dashboard financeiro/_scratch/ano_2025.js"
    .venv\\Scripts\\python.exe "Dashboard financeiro/_atualizar_dados_ano_empresa.py" --html painel_financeiro_kobe.html --mes-final-2026 8

Também reescreve ``var SNAPSHOT`` para a data de hoje automaticamente — nunca
precisa (nem deve) ser setado à mão numa chamada separada.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import re
from pathlib import Path

PASTA = Path(__file__).resolve().parent
BUILD = PASTA / "build"
SCRATCH_PADRAO = PASTA / "_scratch"


MESES_ROTULO = ['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']


def _meses_js(mes_final: int) -> str:
    return "[" + ",".join(f"'{m}'" for m in MESES_ROTULO[:mes_final]) + "]"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="Nome do arquivo em build/, ex.: painel_financeiro_kobe.html")
    ap.add_argument("--mes-final-2026", type=int, default=6, help="Quantos meses de 2026 foram extraídos (padrão 6, Jan-Jun)")
    ap.add_argument("--mes-final-2025", type=int, default=12, help="Quantos meses de 2025 foram extraídos (padrão 12, ano fechado)")
    ap.add_argument("--scratch", type=Path, default=SCRATCH_PADRAO, help="Pasta com ano_2026.js/ano_2025.js (padrão: Dashboard financeiro/_scratch)")
    args = ap.parse_args()

    html_path = BUILD / args.html
    html = html_path.read_text(encoding="utf-8")

    ano_2026 = (args.scratch / "ano_2026.js").read_text(encoding="utf-8")
    ano_2025 = (args.scratch / "ano_2025.js").read_text(encoding="utf-8")

    meses_2026 = _meses_js(args.mes_final_2026)
    meses_2025 = _meses_js(args.mes_final_2025)

    novo_bloco = (
        "  var DADOS_ANO = {\n"
        "    '2026': {\n"
        f"    meses: {meses_2026},\n"
        + ano_2026.rstrip("\n")
        + "\n    },\n"
        "    '2025': {\n"
        f"    meses: {meses_2025},\n"
        + ano_2025.rstrip("\n")
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

    html_path.write_text(html, encoding="utf-8")
    print(f"ok — bytes finais: {len(html)} — SNAPSHOT = {hoje}")


if __name__ == "__main__":
    main()
