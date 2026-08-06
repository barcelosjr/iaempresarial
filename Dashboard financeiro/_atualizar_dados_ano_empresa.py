"""Atualiza o bloco ``DADOS_ANO`` de um painel de marca única com dados frescos,
gerados por gerar_dados_empresa_ano.py --empresa <MARCA> --ano 2026/2025.

Versão genérica de ``_atualizar_dados_ano_corretora.py``/``_atualizar_dados_ano_royal.py``.

Uso (a partir da raiz do projeto), depois de gerar os dois arquivos .js::

    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dados_empresa_ano.py" --empresa KOBE --ano 2026 --mes-final 6 > <scratch>/ano_2026.js
    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dados_empresa_ano.py" --empresa KOBE --ano 2025 --mes-final 12 > <scratch>/ano_2025.js
    .venv\\Scripts\\python.exe "Dashboard financeiro/_atualizar_dados_ano_empresa.py" --html painel_financeiro_kobe.html
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

BUILD = Path(__file__).resolve().parent / "build"
SCRATCH = Path(
    r"C:\Users\CONTRO~1\AppData\Local\Temp\claude\C--Users-Controladoria--claude-projects-iaempresarial"
    r"\798130a2-252e-48de-9f4e-ad9b8cb58e9e\scratchpad"
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--html", required=True, help="Nome do arquivo em build/, ex.: painel_financeiro_kobe.html")
    args = ap.parse_args()

    html_path = BUILD / args.html
    html = html_path.read_text(encoding="utf-8")

    ano_2026 = (SCRATCH / "ano_2026.js").read_text(encoding="utf-8")
    ano_2025 = (SCRATCH / "ano_2025.js").read_text(encoding="utf-8")

    meses_2026 = "['Jan','Fev','Mar','Abr','Mai','Jun']"
    meses_2025 = "['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']"

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

    html_path.write_text(html, encoding="utf-8")
    print("ok — bytes finais:", len(html))


if __name__ == "__main__":
    main()
