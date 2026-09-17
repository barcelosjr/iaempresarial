"""Gera UM painel HTML com a DRE das 10 revendas da KOBE, no modelo do
Consolidado (painel_financeiro.html): seletor de revenda na sidebar (mais
"Consolidado KOBE" somando as 10), em vez de 10 arquivos separados ou de uma
tabela lado a lado.

Reaproveita gerar() de gerar_dre_revendas_kobe.py — mesma consulta, mesmos
números dos 10 painéis painel_financeiro_kobe_*.html e do
dre_comparativo_revendas_kobe.html.

Por que só DRE — mesmo motivo dos outros artefatos desta leva: ~73% do valor
do Balanço da KOBE não tem REVENDA atribuída (fica centralizado no grupo), e
a DRE tem 100% de cobertura.

Uso (a partir da raiz do projeto)::

    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_painel_kobe_por_revenda.py"

Gera Dashboard financeiro/build/painel_financeiro_kobe_por_revenda.html, a
partir de _template_dre_kobe_por_revenda.html.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:
    from powerbi.client import PowerBIClient  # noqa: E402
except ModuleNotFoundError as _exc:  # pragma: no cover - erro de ambiente
    raise SystemExit(
        f"Dependência ausente ({_exc.name}). Rode com o Python do venv:\n"
        '  .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_painel_kobe_por_revenda.py"'
    ) from _exc


def _carregar(nome_arquivo: str, nome_modulo: str):
    spec = importlib.util.spec_from_file_location(
        nome_modulo, Path(__file__).resolve().parent / nome_arquivo
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_gerador = _carregar("gerar_dre_revendas_kobe.py", "gerar_dre_revendas_kobe")
REVENDAS = _gerador.REVENDAS

PASTA = Path(__file__).resolve().parent
BUILD = PASTA / "build"
TEMPLATE = PASTA / "_template_dre_kobe_por_revenda.html"
DESTINO = BUILD / "painel_financeiro_kobe_por_revenda.html"


def _num(v: float) -> str:
    return "0" if abs(v) < 0.005 else f"{v:.2f}"


def _lista(vals: list[float]) -> str:
    return "[" + ",".join(_num(v) for v in vals) + "]"


def _emit_flat_multi(nome: str, por_revenda: dict[str, dict[str, list[float]]], indent: str) -> list[str]:
    """dreDet/dreDetAnt — {revenda: {chave: [mensal]}}."""
    linhas = [f"{indent}{nome}: {{"]
    revendas = sorted(por_revenda)
    for i, revenda in enumerate(revendas):
        itens = [f"{k}:{_lista(v)}" for k, v in por_revenda[revenda].items()]
        linhas.append(f"{indent}  '{revenda}': {{")
        linhas.append(",\n".join(f"{indent}    {it}" for it in itens))
        linhas.append(f"{indent}  }}{',' if i < len(revendas)-1 else ''}")
    linhas.append(f"{indent}}},")
    return linhas


def _emit_desc_multi(nome: str, por_revenda: dict[str, dict[str, dict[str, list[float]]]], indent: str, ultimo: bool) -> list[str]:
    """dreDesc/dreDescAnt — {revenda: {chave: {descricao: [mensal]}}}."""
    linhas = [f"{indent}{nome}: {{"]
    revendas = sorted(por_revenda)
    for i, revenda in enumerate(revendas):
        chaves = sorted(por_revenda[revenda])
        linhas.append(f"{indent}  '{revenda}': {{")
        for j, chave in enumerate(chaves):
            descs = sorted(por_revenda[revenda][chave])
            linhas_desc = [f"'{d}':{_lista(por_revenda[revenda][chave][d])}" for d in descs]
            linhas.append(f"{indent}    {chave}: {{")
            linhas.append(",\n".join(f"{indent}      {it}" for it in linhas_desc))
            linhas.append(f"{indent}    }}{',' if j < len(chaves)-1 else ''}")
        linhas.append(f"{indent}  }}{',' if i < len(revendas)-1 else ''}")
    linhas.append(f"{indent}}}" + ("" if ultimo else ","))
    return linhas


def _emit_bloco_ano(meses_js: str, dre_det: dict, dre_det_ant: dict, dre_desc: dict, dre_desc_ant: dict) -> str:
    ind = "    "
    linhas = [f"{ind}meses: {meses_js},"]
    linhas += _emit_flat_multi("dreDet", dre_det, ind)
    linhas += _emit_flat_multi("dreDetAnt", dre_det_ant, ind)
    linhas.append(f"{ind}balDet: {{}},")
    linhas.append(f"{ind}mov: {{}},")
    linhas.append(f"{ind}movAnt: {{}},")
    linhas.append(f"{ind}nat: {{}},")
    linhas.append(f"{ind}fcCont: {{}},")
    linhas.append(f"{ind}saldoIni: {{}},")
    linhas += _emit_desc_multi("dreDesc", dre_desc, ind, ultimo=False)
    linhas += _emit_desc_multi("dreDescAnt", dre_desc_ant, ind, ultimo=True)
    return "\n".join(linhas)


def montar_html(template: str, dados_por_revenda: dict[str, dict], snapshot: str) -> str:
    meses_2026 = "['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago']"
    meses_2025 = "['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']"

    dre_2026 = {r: dados_por_revenda[r]["2026"][0] for r in REVENDAS}
    dre_2025_comp = {r: dados_por_revenda[r]["2026"][1] for r in REVENDAS}
    desc_2026 = {r: dados_por_revenda[r]["2026"][2] for r in REVENDAS}
    desc_2025_comp = {r: dados_por_revenda[r]["2026"][3] for r in REVENDAS}

    dre_2025 = {r: dados_por_revenda[r]["2025"][0] for r in REVENDAS}
    dre_2024_comp = {r: dados_por_revenda[r]["2025"][1] for r in REVENDAS}
    desc_2025 = {r: dados_por_revenda[r]["2025"][2] for r in REVENDAS}
    desc_2024_comp = {r: dados_por_revenda[r]["2025"][3] for r in REVENDAS}

    bloco_2026 = _emit_bloco_ano(meses_2026, dre_2026, dre_2025_comp, desc_2026, desc_2025_comp)
    bloco_2025 = _emit_bloco_ano(meses_2025, dre_2025, dre_2024_comp, desc_2025, desc_2024_comp)

    novo_bloco = (
        "  var DADOS_ANO = {\n"
        "    '2026': {\n" + bloco_2026 + "\n    },\n"
        "    '2025': {\n" + bloco_2025 + "\n    }\n"
        "  };\n"
    )

    html = template.replace("__TITLE__", "Painel Financeiro — KOBE (por Revenda)")
    html = html.replace("__BRAND_SUB__", "KOBE")
    html = html.replace("__SNAPSHOT__", snapshot)

    padrao = re.compile(r"  var DADOS_ANO = \{.*?\n  \};\n", re.S)
    m = padrao.search(html)
    if not m:
        raise SystemExit("bloco DADOS_ANO não encontrado no template")
    html = html[: m.start()] + novo_bloco + html[m.end() :]
    return html


def main() -> None:
    cliente = PowerBIClient()
    dados_por_revenda = _gerador.gerar(cliente)

    template = TEMPLATE.read_text(encoding="utf-8")
    snapshot = _dt.date.today().strftime("%d/%m/%Y")
    html = montar_html(template, dados_por_revenda, snapshot)

    DESTINO.write_text(html, encoding="utf-8")
    print(f"ok — {DESTINO.name}: {len(html)} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
