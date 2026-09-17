"""Gera a DRE (Jan-Jun/2026 e Jan-Dez/2025) de cada uma das 10 revendas da KOBE,
para os 10 paineis "so DRE" derivados de _template_dre_revenda.html.

Por que so DRE (nao Balanco/Fluxo de Caixa) - ver o aviso na sidebar do
template: ~73% do valor do Balanco da KOBE nao tem REVENDA atribuida (fica
centralizado no grupo), entao Balanco e Fluxo de Caixa por revenda nao fecham
com confianca. A DRE, ao contrario, tem 100% dos lancamentos com revenda
atribuida - por isso so ela entra aqui. Ver estrutura_financeira_completa.md
(REVENDA nao e usada nos relatorios oficiais - este e um recorte novo, nao
uma medida oficial do MCP, mas usa a mesma DRE_CHAVES/VALOR_AJUSTADO que o
resto do projeto).

Ao contrario de gerar_dados_empresa_ano.py (uma consulta por empresa), este
script busca as 10 revendas de uma vez so por consulta (agrupa por REVENDA
tambem), para nao multiplicar 10x o numero de chamadas ao Power BI.

Uso (a partir da raiz do projeto)::

    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dre_revendas_kobe.py"

Gera os 10 arquivos finais direto em build/, a partir de
_template_dre_revenda.html (title/brand-sub/SNAPSHOT/state.brand e o bloco
DADOS_ANO trocados por revenda).
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
    from powerbi import dax_financeiro as fin  # noqa: E402
    from powerbi.client import PowerBIClient  # noqa: E402
except ModuleNotFoundError as _exc:  # pragma: no cover - erro de ambiente
    raise SystemExit(
        f"Dependência ausente ({_exc.name}). Rode com o Python do venv:\n"
        '  .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dre_revendas_kobe.py"'
    ) from _exc


def _carregar(nome_arquivo: str, nome_modulo: str):
    spec = importlib.util.spec_from_file_location(
        nome_modulo, Path(__file__).resolve().parent / nome_arquivo
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_atualizar = _carregar("atualizar_dados.py", "atualizar_dados")
DRE_CHAVES = _atualizar.DRE_CHAVES

PASTA = Path(__file__).resolve().parent
BUILD = PASTA / "build"
TEMPLATE = PASTA / "_template_dre_revenda.html"

EMPRESA = "KOBE"

# id DAX (lancamentos[REVENDA]) -> (nome de arquivo, titulo/brand-sub exibido)
REVENDAS = {
    "KOBE GV": "kobe_gv",
    "KOBE SH": "kobe_sh",
    "KOBE CI": "kobe_ci",
    "KOBE IP": "kobe_ip",
    "KOBE LI": "kobe_li",
    "KOBE VI": "kobe_vi",
    "KOBE VV": "kobe_vv",
    "KOBE MH": "kobe_mh",
    "KOBE BH": "kobe_bh",
    "KOBE CT": "kobe_ct",
}


def _num(v: float) -> str:
    return "0" if abs(v) < 0.005 else f"{v:.2f}"


def _lista(vals: list[float]) -> str:
    return "[" + ",".join(_num(v) for v in vals) + "]"


def _q_dre_por_mes_revendas(de: int, ate: int) -> str:
    """DRE por REVENDA x conta x mes, so EMPRESA=KOBE, no intervalo [de, ate]."""
    k = fin._expr_chave()
    return (
        "EVALUATE\n"
        f"VAR _B = FILTER('lancamentos', {k} >= {de} && {k} <= {ate} && "
        'TRIM(\'lancamentos\'[EMPRESA]) = "KOBE")\n'
        "VAR _P = ADDCOLUMNS(_B, \"@R\", TRIM('lancamentos'[REVENDA]), "
        f"\"@C\", TRIM('lancamentos'[DRE]), \"@K\", {k}, "
        "\"@V\", 'lancamentos'[VALOR_AJUSTADO])\n"
        'RETURN GROUPBY(_P, [@R], [@C], [@K], "@Valor", SUMX(CURRENTGROUP(), [@V]))'
    )


def _dre_por_mes_revendas(cliente, de: int, ate: int, mes_final: int) -> dict[str, dict[str, list[float]]]:
    df = cliente.execute_dax(_q_dre_por_mes_revendas(de, ate))
    out: dict[str, dict[str, list[float]]] = {r: {} for r in REVENDAS}
    faltando = set()
    ignoradas = set()
    for _, r in df.iterrows():
        revenda = str(r["[@R]"]).strip()
        if revenda not in out:
            ignoradas.add(revenda or "(vazio)")
            continue
        conta = str(r["[@C]"]).strip()
        chave = DRE_CHAVES.get(conta)
        if chave is None:
            faltando.add(conta)
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= mes_final:
            continue
        arr = out[revenda].setdefault(chave, [0.0] * mes_final)
        arr[mes - 1] += float(r["[@Valor]"] or 0)
    if faltando:
        print(f"// AVISO (DRE): contas sem chave, ignoradas: {sorted(faltando)}", file=sys.stderr)
    if ignoradas:
        print(f"// AVISO (DRE): valores fora das 10 revendas, ignorados: {sorted(ignoradas)}", file=sys.stderr)
    for revenda in out:
        out[revenda] = {k: v for k, v in out[revenda].items() if any(abs(x) >= 0.005 for x in v)}
    return out


def _q_dre_desc_revendas(de: int, ate: int) -> str:
    k = fin._expr_chave()
    return (
        "EVALUATE\n"
        f"VAR _P = ADDCOLUMNS('lancamentos', \"@R\", TRIM('lancamentos'[REVENDA]), "
        f"\"@C\", TRIM('lancamentos'[DRE]), \"@D\", TRIM('lancamentos'[DESCRICAO_CONTA]), \"@K\", {k})\n"
        f"VAR _F = FILTER(_P, TRIM('lancamentos'[EMPRESA]) = \"KOBE\" && [@K] >= {de} && "
        f"[@K] <= {ate} && [@C] <> \"\")\n"
        'RETURN GROUPBY(_F, [@R], [@C], [@D], [@K], "@Valor", '
        "SUMX(CURRENTGROUP(), 'lancamentos'[VALOR_AJUSTADO]))"
    )


def _dre_desc_revendas(cliente, de: int, ate: int, mes_final: int) -> dict[str, dict[str, dict[str, list[float]]]]:
    df = cliente.execute_dax(_q_dre_desc_revendas(de, ate))
    out: dict[str, dict[str, dict[str, list[float]]]] = {r: {} for r in REVENDAS}
    for _, r in df.iterrows():
        revenda = str(r["[@R]"]).strip()
        if revenda not in out:
            continue
        conta = str(r["[@C]"]).strip()
        chave = DRE_CHAVES.get(conta)
        if chave is None:
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= mes_final:
            continue
        desc = str(r["[@D]"]).strip()
        arr = out[revenda].setdefault(chave, {}).setdefault(desc, [0.0] * mes_final)
        arr[mes - 1] += float(r["[@Valor]"] or 0)
    return out


def _emit_dados_ano_bloco(dre_det: dict, dre_det_ant: dict, dre_desc: dict, dre_desc_ant: dict, meses_js: str, revenda_chave: str) -> str:
    ind = "    "
    linhas = [f"{ind}meses: {meses_js},"]

    linhas.append(f"{ind}dreDet: {{'{revenda_chave}': {{")
    itens = [f"{k}:{_lista(v)}" for k, v in dre_det.items()]
    linhas.append(",\n".join(f"{ind}  {it}" for it in itens))
    linhas.append(f"{ind}}}}},")

    linhas.append(f"{ind}dreDetAnt: {{'{revenda_chave}': {{")
    itens = [f"{k}:{_lista(v)}" for k, v in dre_det_ant.items()]
    linhas.append(",\n".join(f"{ind}  {it}" for it in itens))
    linhas.append(f"{ind}}}}},")

    linhas.append(f"{ind}balDet: {{}},")
    linhas.append(f"{ind}mov: {{}},")
    linhas.append(f"{ind}movAnt: {{}},")
    linhas.append(f"{ind}nat: {{}},")
    linhas.append(f"{ind}fcCont: {{}},")
    linhas.append(f"{ind}saldoIni: {{}},")

    linhas.append(f"{ind}dreDesc: {{")
    chaves = sorted(dre_desc)
    partes = []
    for chave in chaves:
        descs = sorted(dre_desc[chave])
        linhas_desc = [f"'{d}':{_lista(dre_desc[chave][d])}" for d in descs]
        bloco = f"{ind}  {chave}: {{\n" + ",\n".join(f"{ind}    {it}" for it in linhas_desc) + f"\n{ind}  }}"
        partes.append(bloco)
    linhas.append(",\n".join(partes))
    linhas.append(f"{ind}}},")

    linhas.append(f"{ind}dreDescAnt: {{")
    chaves = sorted(dre_desc_ant)
    partes = []
    for chave in chaves:
        descs = sorted(dre_desc_ant[chave])
        linhas_desc = [f"'{d}':{_lista(dre_desc_ant[chave][d])}" for d in descs]
        bloco = f"{ind}  {chave}: {{\n" + ",\n".join(f"{ind}    {it}" for it in linhas_desc) + f"\n{ind}  }}"
        partes.append(bloco)
    linhas.append(",\n".join(partes))
    linhas.append(f"{ind}}}")

    return "\n".join(linhas)


def gerar(cliente, mes_final_2026: int = 8) -> dict[str, dict]:
    """Retorna, por revenda, os dois blocos de ano ('2026' Jan-mes_final_2026 e '2025' Jan-Dez)."""
    ate_2026 = 202600 + mes_final_2026
    ate_2025_comp = 202500 + mes_final_2026
    print(f"// Consultando DRE Jan-{mes_final_2026:02d}/2026 (10 revendas)...", file=sys.stderr)
    dre_2026 = _dre_por_mes_revendas(cliente, 202601, ate_2026, mes_final_2026)
    print(f"// Consultando DRE Jan-{mes_final_2026:02d}/2025 (comparacao)...", file=sys.stderr)
    dre_2025_comp = _dre_por_mes_revendas(cliente, 202501, ate_2025_comp, mes_final_2026)
    print("// Consultando DRE Jan-Dez/2025 (10 revendas)...", file=sys.stderr)
    dre_2025 = _dre_por_mes_revendas(cliente, 202501, 202512, 12)
    print("// Consultando DRE Jan-Dez/2024 (comparacao)...", file=sys.stderr)
    dre_2024_comp = _dre_por_mes_revendas(cliente, 202401, 202412, 12)
    print(f"// Consultando drill-down DESCRICAO_CONTA, Jan-{mes_final_2026:02d}/2026...", file=sys.stderr)
    desc_2026 = _dre_desc_revendas(cliente, 202601, ate_2026, mes_final_2026)
    print(f"// Consultando drill-down DESCRICAO_CONTA, Jan-{mes_final_2026:02d}/2025 (comparacao)...", file=sys.stderr)
    desc_2025_comp = _dre_desc_revendas(cliente, 202501, ate_2025_comp, mes_final_2026)
    print("// Consultando drill-down DESCRICAO_CONTA, Jan-Dez/2025...", file=sys.stderr)
    desc_2025 = _dre_desc_revendas(cliente, 202501, 202512, 12)
    print("// Consultando drill-down DESCRICAO_CONTA, Jan-Dez/2024 (comparacao)...", file=sys.stderr)
    desc_2024_comp = _dre_desc_revendas(cliente, 202401, 202412, 12)

    out: dict[str, dict] = {}
    for revenda in REVENDAS:
        out[revenda] = {
            "2026": (dre_2026[revenda], dre_2025_comp[revenda], desc_2026[revenda], desc_2025_comp[revenda]),
            "2025": (dre_2025[revenda], dre_2024_comp[revenda], desc_2025[revenda], desc_2024_comp[revenda]),
        }
    return out


def montar_html(template: str, revenda_chave: str, revenda_arquivo: str, dados: dict, snapshot: str) -> str:
    titulo = f"Painel Financeiro — {revenda_chave} (DRE)"
    brand_sub = revenda_chave

    meses_2026 = "['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago']"
    meses_2025 = "['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']"

    dre_2026, dre_2025_comp, desc_2026, desc_2025_comp = dados["2026"]
    dre_2025, dre_2024_comp, desc_2025, desc_2024_comp = dados["2025"]

    bloco_2026 = _emit_dados_ano_bloco(dre_2026, dre_2025_comp, desc_2026, desc_2025_comp, meses_2026, revenda_chave)
    bloco_2025 = _emit_dados_ano_bloco(dre_2025, dre_2024_comp, desc_2025, desc_2024_comp, meses_2025, revenda_chave)

    novo_bloco = (
        "  var DADOS_ANO = {\n"
        "    '2026': {\n" + bloco_2026 + "\n    },\n"
        "    '2025': {\n" + bloco_2025 + "\n    }\n"
        "  };\n"
    )

    html = template.replace("__TITLE__", titulo)
    html = html.replace("__BRAND_SUB__", brand_sub)
    html = html.replace("__SNAPSHOT__", snapshot)
    html = html.replace("__BRAND_KEY__", revenda_chave)

    padrao = re.compile(r"  var DADOS_ANO = \{.*?\n  \};\n", re.S)
    m = padrao.search(html)
    if not m:
        raise SystemExit("bloco DADOS_ANO não encontrado no template")
    html = html[: m.start()] + novo_bloco + html[m.end() :]
    return html


def main() -> None:
    cliente = PowerBIClient()
    dados_por_revenda = gerar(cliente)

    template = TEMPLATE.read_text(encoding="utf-8")
    snapshot = _dt.date.today().strftime("%d/%m/%Y")

    for revenda_chave, arquivo in REVENDAS.items():
        html = montar_html(template, revenda_chave, arquivo, dados_por_revenda[revenda_chave], snapshot)
        destino = BUILD / f"painel_financeiro_{arquivo}.html"
        destino.write_text(html, encoding="utf-8")
        print(f"ok — {destino.name}: {len(html)} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
