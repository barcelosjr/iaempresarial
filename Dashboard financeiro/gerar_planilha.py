"""Gera a Planilha Financeira (visão tabular) a partir de um painel oficial.

O painel oficial é a fonte da verdade: este script apenas LÊ o `SNAPSHOT` e o
bloco `var DADOS_ANO = {...}` de `build/painel_financeiro_<slug>.html` e injeta
em `_template_planilha.html`, gravando `build/planilha_<slug>.html`.

Nada é recalculado aqui, e nenhum painel oficial é modificado.

Modo KOBE (`--por-revenda`): a DRE é aberta pelas 10 revendas, com filtro de
seleção na planilha. Os dados por revenda são consultados **ao vivo** no Power
BI, reaproveitando `gerar_dre_revendas_kobe.gerar()` — a mesma query dos
artefatos oficiais. Isso evita herdar o `painel_financeiro_kobe_por_revenda.html`,
que costuma estar mais velho que o painel agregado.

Balanço, Fluxo de Caixa e os indicadores que dependem deles continuam vindo do
painel agregado, numa chave só (a marca inteira): ~73% do valor do Balanço da
KOBE não tem REVENDA atribuída, então não existe Balanço por loja. A planilha
esconde essas linhas quando a seleção não é a marca inteira.

Uso:
    .venv/Scripts/python.exe "Dashboard financeiro/gerar_planilha.py" royal
    .venv/Scripts/python.exe "Dashboard financeiro/gerar_planilha.py" kobe --por-revenda
"""

from __future__ import annotations

import argparse
import datetime as _dt
import importlib.util
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
BUILD = BASE / "build"
TEMPLATE = BASE / "_template_planilha.html"
RAIZ = BASE.parent

# slug do arquivo -> (nome exibido, id da empresa dentro de DADOS_ANO)
EMPRESAS = {
    "royal": ("ROYAL", "ROYAL"),
    "kobe": ("KOBE", "KOBE"),
    "mit": ("MIT", "MIT"),
    "megastore": ("MEGA STORE", "MEGA STORE"),
    "multboats": ("MULT BOATS", "MULT BOATS"),
    "omoda": ("OMODA", "OMODA"),
    "multsolucoes": ("MULT SOLUÇÕES", "MULT SOLUÇÕES"),
    "corretora": ("CORRETORA", "CORRETORA"),
}


# --------------------------------------------------------------------------
# Leitura do painel oficial
# --------------------------------------------------------------------------
def extrair_snapshot(html: str) -> str:
    m = re.search(r"var\s+SNAPSHOT\s*=\s*'([^']+)'", html)
    if not m:
        raise SystemExit("Não achei `var SNAPSHOT = '...'` no painel oficial.")
    return m.group(1)


def extrair_dados_ano(html: str) -> str:
    """Recorta `var DADOS_ANO = {...};` por contagem de chaves.

    Contagem simples de `{`/`}` basta: o bloco é gerado por script e só contém
    números, arrays e chaves com aspas simples — nunca chave dentro de string.
    """
    ini = html.find("var DADOS_ANO")
    if ini == -1:
        raise SystemExit("Não achei `var DADOS_ANO` no painel oficial.")
    abre = html.find("{", ini)
    nivel, i = 0, abre
    while i < len(html):
        if html[i] == "{":
            nivel += 1
        elif html[i] == "}":
            nivel -= 1
            if nivel == 0:
                break
        i += 1
    else:
        raise SystemExit("Bloco DADOS_ANO não fecha — painel oficial corrompido?")
    fim = html.find(";", i)
    return html[ini : fim + 1]


def _corpo_do_ano(bloco: str, ano: str) -> str | None:
    """Texto de dentro de `'<ano>': { ... }` no bloco DADOS_ANO."""
    m = re.search(r"'%s'\s*:\s*\{" % re.escape(ano), bloco)
    if not m:
        return None
    i = m.end() - 1
    nivel, j = 0, i
    while j < len(bloco):
        if bloco[j] == "{":
            nivel += 1
        elif bloco[j] == "}":
            nivel -= 1
            if nivel == 0:
                return bloco[i + 1 : j]
        j += 1
    return None


def _valor_de(corpo: str, chave: str) -> str | None:
    """Texto cru do valor de `chave:` dentro do corpo de um ano.

    Recorte textual (e não parse) de propósito: os blocos que interessam aqui
    (balDet, mov, nat, fcCont, saldoIni, meses) são só números e chaves simples,
    então contar delimitadores é seguro e imune a apóstrofo em descrição.
    """
    m = re.search(r"(?m)^\s*%s\s*:\s*" % re.escape(chave), corpo)
    if not m:
        return None
    i = m.end()
    if corpo[i] in "{[":
        abre = corpo[i]
        fecha = "}" if abre == "{" else "]"
        nivel, j = 0, i
        while j < len(corpo):
            if corpo[j] == abre:
                nivel += 1
            elif corpo[j] == fecha:
                nivel -= 1
                if nivel == 0:
                    return corpo[i : j + 1]
            j += 1
        return None
    j = corpo.find(",", i)
    return corpo[i : j if j != -1 else len(corpo)]


# --------------------------------------------------------------------------
# Emissão
# --------------------------------------------------------------------------
def _num(v: float) -> str:
    return "0" if abs(v) < 0.005 else f"{v:.2f}"


def _lista(vals) -> str:
    return "[" + ",".join(_num(float(v)) for v in vals) + "]"


def _js_str(s: str) -> str:
    return "'" + s.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _emit_dre(por_entidade: dict, ind: str = "      ") -> str:
    partes = []
    for ent in sorted(por_entidade):
        itens = [f"{k}:{_lista(v)}" for k, v in sorted(por_entidade[ent].items())]
        partes.append(
            f"{ind}{_js_str(ent)}: {{\n"
            + ",\n".join(f"{ind}  {it}" for it in itens)
            + f"\n{ind}}}"
        )
    return "{\n" + ",\n".join(partes) + f"\n{ind[:-2]}}}"


def _emit_desc(por_entidade: dict, ind: str = "      ") -> str:
    blocos_ent = []
    for ent in sorted(por_entidade):
        contas = []
        for conta in sorted(por_entidade[ent]):
            descs = por_entidade[ent][conta]
            linhas = [f"{_js_str(d)}:{_lista(descs[d])}" for d in sorted(descs)]
            contas.append(
                f"{ind}  {conta}: {{\n"
                + ",\n".join(f"{ind}    {it}" for it in linhas)
                + f"\n{ind}  }}"
            )
        blocos_ent.append(f"{ind}{_js_str(ent)}: {{\n" + ",\n".join(contas) + f"\n{ind}}}")
    return "{\n" + ",\n".join(blocos_ent) + f"\n{ind[:-2]}}}"


# --------------------------------------------------------------------------
# Modo por revenda (KOBE)
# --------------------------------------------------------------------------
def _carregar_modulo(nome_arquivo: str, nome_modulo: str):
    spec = importlib.util.spec_from_file_location(nome_modulo, BASE / nome_arquivo)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _dados_por_revenda(mes_final: int):
    """Consulta a DRE por revenda ao vivo, com a query oficial (somente leitura)."""
    sys.path.insert(0, str(RAIZ))
    from powerbi.client import PowerBIClient  # noqa: E402

    ger = _carregar_modulo("gerar_dre_revendas_kobe.py", "_ger_dre_revendas")
    cliente = PowerBIClient()
    print("// Consultando a DRE das 10 revendas da KOBE no Power BI...", file=sys.stderr)
    return ger.gerar(cliente, mes_final_2026=mes_final), list(ger.REVENDAS)


def _montar_kobe_por_revenda(bloco_agregado: str, anos: list[str]) -> tuple[str, list[str], dict]:
    """DADOS_ANO com a DRE por revenda e o Balanço/Fluxo da marca inteira."""
    corpo26 = _corpo_do_ano(bloco_agregado, "2026")
    meses26 = _valor_de(corpo26, "meses")
    mes_final = meses26.count("'") // 2

    dados, revendas = _dados_por_revenda(mes_final)

    conferencia = {}
    partes_ano = []
    for ano in anos:
        corpo = _corpo_do_ano(bloco_agregado, ano)
        if corpo is None:
            continue
        meses = _valor_de(corpo, "meses")

        dre_det = {r: dados[r][ano][0] for r in revendas}
        dre_det_ant = {r: dados[r][ano][1] for r in revendas}
        dre_desc = {r: dados[r][ano][2] for r in revendas}

        # Confere a soma das revendas contra a DRE da marca no painel agregado.
        # Diferença aqui significa lançamento de KOBE sem REVENDA atribuída, ou
        # defasagem entre a consulta de agora e a data do painel — nos dois casos
        # o usuário precisa saber, não descobrir depois numa reunião.
        agregado = _valor_de(corpo, "dreDet")
        conferencia[ano] = _conferir(dre_det, agregado)

        blocos = [f"    meses: {meses},"]
        blocos.append("    dreDet: " + _emit_dre(dre_det) + ",")
        blocos.append("    dreDetAnt: " + _emit_dre(dre_det_ant) + ",")
        for chave in ("balDet", "mov", "movAnt", "nat", "fcCont", "saldoIni"):
            blocos.append(f"    {chave}: {_valor_de(corpo, chave)},")
        blocos.append("    dreDesc: " + _emit_desc(dre_desc))
        partes_ano.append(f"    '{ano}': {{\n" + "\n".join(blocos) + "\n    }")

    return "var DADOS_ANO = {\n" + ",\n".join(partes_ano) + "\n  };", revendas, conferencia


def _conferir(dre_det: dict, agregado_js: str | None) -> dict:
    """Soma das revendas x DRE da marca no painel agregado, por campo."""
    if not agregado_js:
        return {}
    campos_agg: dict[str, float] = {}
    for k, lista in re.findall(r"([A-Za-z]+):\[([-0-9.,e]*)\]", agregado_js):
        campos_agg[k] = sum(float(x) for x in lista.split(",") if x)
    campos_rev: dict[str, float] = {}
    for por_conta in dre_det.values():
        for k, v in por_conta.items():
            campos_rev[k] = campos_rev.get(k, 0.0) + sum(v)
    difs = {}
    for k in set(campos_agg) | set(campos_rev):
        d = campos_rev.get(k, 0.0) - campos_agg.get(k, 0.0)
        if abs(d) > 1:
            difs[k] = d
    return difs


# --------------------------------------------------------------------------
def gerar(slug: str, empresa: str | None, empresa_id: str | None, por_revenda: bool) -> Path:
    origem = BUILD / f"painel_financeiro_{slug}.html"
    if not origem.exists():
        raise SystemExit(f"Painel oficial não encontrado: {origem}")

    padrao_nome, padrao_id = EMPRESAS.get(slug, (slug.upper(), slug.upper()))
    nome = empresa or padrao_nome
    ident = empresa_id or padrao_id

    html = origem.read_text(encoding="utf-8")
    snapshot_painel = extrair_snapshot(html)
    dados = extrair_dados_ano(html)
    anos = sorted(set(re.findall(r"'(20\d{2})':\s*\{", dados)), reverse=True)

    conferencia: dict = {}
    if por_revenda:
        dados, entidades, conferencia = _montar_kobe_por_revenda(dados, anos)
        lista_ent = [{"id": r, "nome": r} for r in entidades]
        rotulo = "Revenda"
        desc_por_entidade = "true"
        # A DRE saiu de uma consulta feita agora; o Balanço/Fluxo veio do painel.
        snapshot_dre = _dt.date.today().strftime("%d/%m/%Y")
        snapshot_bal = snapshot_painel
    else:
        if f"'{ident}'" not in dados:
            raise SystemExit(
                f"A empresa '{ident}' não aparece no DADOS_ANO de {origem.name}. "
                "Confira o --empresa-id."
            )
        lista_ent = [{"id": ident, "nome": nome}]
        rotulo = "Empresa"
        desc_por_entidade = "false"
        snapshot_dre = snapshot_painel
        snapshot_bal = snapshot_painel

    saida_html = (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("/*__DADOS_ANO__*/", "  " + dados)
        .replace("__ENTIDADES__", json.dumps(lista_ent, ensure_ascii=False))
        .replace("__ROTULO_ENTIDADE__", rotulo)
        .replace("__ENTIDADE_BALANCO__", ident)
        .replace("__DESC_POR_ENTIDADE__", desc_por_entidade)
        .replace("__SNAPSHOT_BALANCO__", snapshot_bal)
        .replace("__SNAPSHOT__", snapshot_dre)
        .replace("__EMPRESA__", nome)
        .replace("__ARQUIVO_FONTE__", origem.name)
        .replace("__SLUG__", slug)
    )

    sufixo = "_por_revenda" if por_revenda else ""
    destino = BUILD / f"planilha_{slug}{sufixo}.html"
    destino.write_text(saida_html, encoding="utf-8")

    print(f"OK  {destino}")
    print(f"    {nome}  snapshot DRE={snapshot_dre}  Balanço/Fluxo={snapshot_bal}  anos={', '.join(anos)}")
    print(f"    entidades: {len(lista_ent)} ({rotulo.lower()})  fonte={origem.name} (não modificado)")
    for ano, difs in conferencia.items():
        if not difs:
            print(f"    CONFERE {ano}: soma das revendas == DRE da marca no painel agregado")
        else:
            total = sum(abs(v) for v in difs.values())
            print(f"    ATENÇÃO {ano}: soma das revendas difere do painel agregado em {len(difs)} campo(s), "
                  f"|dif| total R$ {total:,.2f}")
            for k, v in sorted(difs.items(), key=lambda x: -abs(x[1]))[:5]:
                print(f"      {k:<20} {v:+15.2f}")
    return destino


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("slug", help="slug do painel oficial, ex.: royal")
    p.add_argument("--empresa", help="nome exibido (default: pelo slug)")
    p.add_argument("--empresa-id", help="chave da empresa dentro de DADOS_ANO")
    p.add_argument("--por-revenda", action="store_true",
                   help="KOBE: abre a DRE pelas 10 revendas (consulta ao vivo)")
    a = p.parse_args(argv)
    gerar(a.slug, a.empresa, a.empresa_id, a.por_revenda)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
