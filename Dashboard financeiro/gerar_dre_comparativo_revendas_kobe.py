"""Gera uma tabela comparativa (HTML estático) da DRE das 10 revendas da KOBE
lado a lado — as revendas como colunas, a estrutura oficial da DRE como
linhas, Jan-Jun/2026 acumulado, com coluna de total KOBE, Acum./25 e Dif. %.

Segue o padrão visual de painel_rateio_grupo.html (topbar, page-head, card,
table-scroll) — mas para um valor único por revenda (Rateio do Grupo) aquele
painel usa gráfico + kpis + tabela; aqui, com ~32 contas da DRE, o pedido foi
só a tabela (mais densa, sem gráfico/kpi).

Lê os dados de dre_revendas_kobe.xml (gerado por
gerar_xml_dre_revendas_kobe.py) — mesmos números dos 10 painéis
painel_financeiro_kobe_*.html, sem reconsultar o Power BI.

Uso (a partir da raiz do projeto, depois de gerar/atualizar o XML)::

    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dre_comparativo_revendas_kobe.py"

Gera Dashboard financeiro/dre_comparativo_revendas_kobe.html
"""

from __future__ import annotations

import datetime as _dt
import xml.etree.ElementTree as ET
from pathlib import Path

PASTA = Path(__file__).resolve().parent
XML_SRC = PASTA / "dre_revendas_kobe.xml"
DESTINO = PASTA / "dre_comparativo_revendas_kobe.html"

PERIODO_ROTULO = "Jan-Jun/2026"
ANT_ROTULO = "Acum./25"


def det(label: str, k: str, receita: bool = False) -> dict:
    return {"label": label, "kind": "normal", "k": k, "receita": receita}


# Mesma estrutura de dreEstrutura() em _template_dre_revenda.html (corretora=false,
# sempre concessionária — igual às 10 revendas da KOBE).
LINHAS = [
    {"label": "1. RECEITA BRUTA DE VENDAS E SERVIÇOS", "kind": "group"},
    det("Venda de Veículos Novos", "vendaVN", True),
    det("Venda de Veículos Usados", "vendaVU", True),
    det("Peças e Acessórios", "pecas", True),
    det("Serviços Oficina", "oficina", True),
    det("Comissões Diversas", "comissoes", True),
    det("(-) Devoluções", "devolucoes"),
    det("(-) Impostos sobre a Venda", "impostosVenda"),
    {"label": "= RECEITA LÍQUIDA", "kind": "subtotal", "k": "rl"},

    {"label": "2. CUSTOS DAS MERCADORIAS E SERVIÇOS", "kind": "group"},
    det("Custo de Veículos Novos", "custoVN"),
    det("Custo de Veículos Usados", "custoVU"),
    det("Custo de Peças e Acessórios", "custoPecas"),
    det("Custo de Serviços Oficina", "custoOficina"),
    det("Custo de Serviço de Terceiros", "custoTerceiros"),
    {"label": "= LUCRO BRUTO", "kind": "subtotal", "k": "lucroBruto"},
    {"label": "% Margem Bruta", "kind": "pct", "k": "margemBruta"},

    {"label": "3. DESPESAS OPERACIONAIS", "kind": "group"},
    det("Folha de Pagamento", "folha"),
    det("Despesas Comerciais", "despComercial"),
    det("Despesas Gerais", "despGerais"),
    det("Manutenção de Bens", "manutencao"),
    det("Serviços Profissionais", "servProf"),
    det("Taxas e Impostos Diversos", "taxasImpostos"),
    det("Despesas de Funcionamento", "despFuncionamento"),
    det("Alugueis e Condomínios", "alugueis"),
    det("Despesas Gerais de Funcionamento", "despGeraisFunc"),
    det("Outras Despesas Operacionais", "outrasDesp"),
    det("Gastos Diversos com Funcionários", "gastosFunc"),
    det("Rateio do Grupo", "rateioGrupo"),

    {"label": "4. OUTRAS RECEITAS/DESPESAS", "kind": "group"},
    det("(+) Receitas Diversas", "receitasDiversas", True),
    det("(+) Receitas Não Operacionais", "receitasNaoOper", True),
    det("(-) Despesas Não Dedutíveis", "despNaoDedutiveis"),
    det("(-) Despesas Não Operacionais", "despNaoOper"),
    {"label": "= EBITDA", "kind": "subtotal", "k": "ebitda"},
    {"label": "% EBITDA/RL", "kind": "pct", "k": "margemEbitda"},

    {"label": "5. DEPRECIAÇÃO E AMORTIZAÇÃO", "kind": "group"},
    det("Depreciação e Amortização de Ativos", "da"),
    {"label": "= EBIT (Resultado Operacional)", "kind": "subtotal", "k": "ebit"},

    {"label": "6. RESULTADO FINANCEIRO", "kind": "group"},
    det("(+) Receitas Financeiras", "recFin", True),
    det("(-) Despesas Financeiras", "despFin"),
    {"label": "= LAIR (Resultado antes do IR)", "kind": "subtotal", "k": "lair"},

    {"label": "7. IMPOSTOS SOBRE O LUCRO", "kind": "group"},
    det("(-) IR e CSLL", "irCsll"),
    {"label": "= LUCRO LÍQUIDO DO EXERCÍCIO", "kind": "total", "k": "lucro"},
    {"label": "% Margem Líquida", "kind": "pct", "k": "margemLiq"},
]

REVENDAS_ORDEM = [
    "KOBE GV", "KOBE SH", "KOBE CI", "KOBE IP", "KOBE LI",
    "KOBE VI", "KOBE VV", "KOBE MH", "KOBE BH", "KOBE CT",
]


def _somar_contas(atual_el: ET.Element) -> dict[str, float]:
    out: dict[str, float] = {}
    for conta_el in atual_el.findall("conta"):
        chave = conta_el.get("chave")
        soma = sum(float(m.text) for m in conta_el.findall("mes"))
        out[chave] = soma
    return out


def carregar_dados() -> dict[str, tuple[dict, dict]]:
    root = ET.parse(XML_SRC).getroot()
    por_revenda: dict[str, tuple[dict, dict]] = {}
    for revenda_el in root.findall("revenda"):
        rid = revenda_el.get("id")
        periodo = next(p for p in revenda_el.findall("periodo") if p.get("rotulo") == PERIODO_ROTULO)
        atual = _somar_contas(periodo.find("atual"))
        ant = _somar_contas(periodo.find("anoAnterior"))
        por_revenda[rid] = (atual, ant)
    return por_revenda


def calc_subtotais(o: dict[str, float]) -> dict[str, float]:
    g = lambda k: o.get(k, 0.0)  # noqa: E731
    rl = (g("vendaVN") + g("vendaVU") + g("pecas") + g("oficina") + g("comissoes") +
          g("comSeguros") + g("comConsorcios") + g("comIntermediacao") + g("devolucoes") + g("impostosVenda"))
    custoTotal = g("custoVN") + g("custoVU") + g("custoPecas") + g("custoOficina") + g("custoTerceiros")
    lucroBruto = rl + custoTotal
    despTotal = (g("folha") + g("despComercial") + g("despGerais") + g("manutencao") + g("servProf") +
                 g("taxasImpostos") + g("despFuncionamento") + g("alugueis") + g("despGeraisFunc") +
                 g("outrasDesp") + g("gastosFunc") + g("rateioGrupo"))
    outrasTotal = g("receitasDiversas") + g("receitasNaoOper") + g("despNaoDedutiveis") + g("despNaoOper")
    ebitda = lucroBruto + despTotal + outrasTotal
    ebit = ebitda + g("da")
    lair = ebit + g("recFin") + g("despFin")
    lucro = lair + g("irCsll")
    out = dict(o)
    out["rl"] = rl
    out["custoTotal"] = custoTotal
    out["lucroBruto"] = lucroBruto
    out["despTotal"] = despTotal
    out["outrasTotal"] = outrasTotal
    out["ebitda"] = ebitda
    out["ebit"] = ebit
    out["lair"] = lair
    out["lucro"] = lucro
    out["margemBruta"] = lucroBruto / rl if rl else 0.0
    out["margemEbitda"] = ebitda / rl if rl else 0.0
    out["margemLiq"] = lucro / rl if rl else 0.0
    return out


def soma_dicts(dicts: list[dict[str, float]]) -> dict[str, float]:
    out: dict[str, float] = {}
    for d in dicts:
        for k, v in d.items():
            out[k] = out.get(k, 0.0) + v
    return out


def fmt_brl(v: float) -> str:
    sinal = "-" if v < -0.5 else ""
    return f"{sinal}R$ {abs(round(v)):,.0f}".replace(",", ".")


def fmt_pct(v: float) -> str:
    return f"{round(v * 100):,.0f}%".replace(",", ".")


def fmt_delta_pct(atual: float, anterior: float) -> str:
    if not anterior:
        return "–"
    d = (atual - anterior) / abs(anterior) * 100
    sinal = "+" if d >= 0 else ""
    return f"{sinal}{d:.1f}".replace(".", ",") + "%"


def titulo_revenda(rid: str) -> str:
    return rid.replace("KOBE ", "")


def montar_linha(row: dict, dados_atual: dict[str, dict], dados_ant: dict[str, dict],
                  total_atual: dict, total_ant: dict) -> str:
    kind = row["kind"]
    if kind == "group":
        colspan = len(REVENDAS_ORDEM) + 3
        return f'<tr class="row-group"><td colspan="{colspan}">{row["label"]}</td></tr>'

    label_html = row["label"]
    recuo = "padding-left:26px" if kind in ("normal",) else ""
    cells = f'<td style="{recuo}">{label_html}</td>' if recuo else f"<td>{label_html}</td>"

    k = row["k"]
    receita = row.get("receita", False)

    def valor_exibido(o: dict) -> float:
        v = o.get(k, 0.0)
        if kind == "normal" and not receita:
            return -v
        return v

    for rid in REVENDAS_ORDEM:
        o = dados_atual[rid]
        if kind == "pct":
            cells += f"<td>{fmt_pct(o.get(k, 0.0))}</td>"
        else:
            cells += f"<td>{fmt_brl(valor_exibido(o))}</td>"

    # Coluna KOBE (total das 10 revendas)
    if kind == "pct":
        cells += f'<td class="tot-col">{fmt_pct(total_atual.get(k, 0.0))}</td>'
    else:
        cells += f'<td class="tot-col">{fmt_brl(valor_exibido(total_atual))}</td>'

    # Acum./25 (só o total KOBE) e Dif. %
    if kind == "pct":
        pp = (total_atual.get(k, 0.0) - total_ant.get(k, 0.0)) * 100
        sinal = "+" if pp >= 0 else ""
        cells += f'<td class="ano-ant">{fmt_pct(total_ant.get(k, 0.0))}</td>'
        cells += f'<td class="ano-ant">{sinal}{pp:.1f}'.replace(".", ",") + " p.p.</td>"
    else:
        cells += f'<td class="ano-ant">{fmt_brl(valor_exibido(total_ant))}</td>'
        a, b = valor_exibido(total_atual), valor_exibido(total_ant)
        cells += f'<td class="ano-ant">{fmt_delta_pct(a, b)}</td>'

    return f'<tr class="row-{kind}">{cells}</tr>'


def montar_html(dados_por_revenda: dict[str, tuple[dict, dict]], gerado_em: str) -> str:
    dados_atual = {rid: calc_subtotais(a) for rid, (a, _) in dados_por_revenda.items()}
    dados_ant = {rid: calc_subtotais(b) for rid, (_, b) in dados_por_revenda.items()}

    total_atual_raw = soma_dicts([dados_por_revenda[rid][0] for rid in REVENDAS_ORDEM])
    total_ant_raw = soma_dicts([dados_por_revenda[rid][1] for rid in REVENDAS_ORDEM])
    total_atual = calc_subtotais(total_atual_raw)
    total_ant = calc_subtotais(total_ant_raw)

    linhas_html = "\n".join(
        montar_linha(row, dados_atual, dados_ant, total_atual, total_ant) for row in LINHAS
    )

    thead = (
        "<thead><tr><th>Conta</th>"
        + "".join(f"<th>{titulo_revenda(r)}</th>" for r in REVENDAS_ORDEM)
        + '<th class="tot-col">KOBE</th>'
        + '<th class="ano-ant">Acum./25</th><th class="ano-ant">Dif. %</th></tr></thead>'
    )

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DRE por Revenda — KOBE</title>
<style>
:root{{
  --bg:#F7F7F8; --card:#FFFFFF; --ink:#1D1D1F; --muted:#6E6E73; --muted-2:#9A9A9A;
  --border:#E8E8ED; --surface:#F5F5F7;
  --accent:#C3002F; --accent-dark:#8C0026;
  --total-bg:#FBE4E7; --total-ink:#8C0026;
  --group-bg:#1D1D1F;
  --serif: Georgia, 'Iowan Old Style', 'Palatino Linotype', 'Times New Roman', serif;
  --sans: -apple-system, 'SF Pro Text', Inter, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
  --shadow:0 1px 3px rgba(0,0,0,.06);
}}
*{{box-sizing:border-box}}
html,body{{margin:0;padding:0}}
body{{background:var(--bg);color:var(--ink);font-family:var(--sans);-webkit-font-smoothing:antialiased}}
.num{{font-variant-numeric:tabular-nums}}

.topbar{{background:#111111;color:#fff}}
.topbar-inner{{max-width:1400px;margin:0 auto;padding:0 24px;height:68px;display:flex;align-items:center;justify-content:space-between;gap:16px}}
.brand{{display:flex;align-items:center;gap:12px}}
.brand-icon{{width:34px;height:34px;border-radius:9px;background:var(--accent);display:flex;align-items:center;justify-content:center;flex-shrink:0}}
.brand-title{{font-family:var(--serif);font-size:17px;font-weight:600;letter-spacing:.01em}}
.brand-sub{{font-size:11.5px;color:#B8B8BD;margin-top:1px}}
.topbar-fonte{{font-size:11.5px;color:#B8B8BD;text-align:right}}
.topbar-fonte b{{color:#fff;font-weight:600}}

.wrap{{max-width:1400px;margin:0 auto;padding:28px 24px 64px}}
.page-head{{margin-bottom:18px}}
.page-title{{font-size:24px;font-weight:700;letter-spacing:-.01em}}
.page-sub{{font-size:13px;color:var(--muted);margin-top:4px}}

.callout{{background:#FFF7E6;border:1px solid #F0DBA6;color:#7A5B00;border-radius:8px;padding:10px 14px;font-size:12.5px;margin-bottom:18px;max-width:900px}}

.card{{background:var(--card);border:1px solid var(--border);border-radius:14px;box-shadow:var(--shadow)}}
.section-card{{padding:20px 22px}}
.section-title{{font-size:12.5px;font-weight:800;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:14px}}

.table-scroll{{overflow-x:auto}}
table{{width:100%;border-collapse:collapse;font-size:12.5px;min-width:1300px}}
thead th{{position:sticky;top:0;background:var(--surface);text-align:right;font-weight:700;color:var(--muted);
  padding:9px 8px;border-bottom:1px solid var(--border);white-space:nowrap;z-index:2}}
thead th:first-child{{text-align:left;position:sticky;left:0;z-index:3;min-width:210px}}
tbody td{{padding:8px 8px;text-align:right;border-bottom:1px solid var(--border);white-space:nowrap;font-variant-numeric:tabular-nums}}
tbody td:first-child{{text-align:left;position:sticky;left:0;background:var(--card);min-width:210px}}
th.tot-col, td.tot-col{{background:var(--surface);font-weight:700}}
th.ano-ant, td.ano-ant{{color:var(--muted);font-weight:400}}

tr.row-group td{{background:var(--group-bg);color:#fff;font-weight:700;font-size:11px;text-transform:uppercase;letter-spacing:.04em;padding:10px 8px}}
tr.row-group td:first-child{{background:var(--group-bg)}}
tr.row-subtotal td{{background:var(--surface);font-weight:700}}
tr.row-subtotal td:first-child{{background:var(--surface)}}
tr.row-total td{{background:var(--total-bg);color:var(--total-ink);font-weight:800}}
tr.row-total td:first-child{{background:var(--total-bg)}}
tr.row-pct td{{font-style:italic;color:var(--muted);font-size:12px;background:#FAFAFA}}
tr.row-pct td:first-child{{background:#FAFAFA}}

.footer-note{{font-size:11.5px;color:var(--muted-2);text-align:center;margin-top:22px;line-height:1.6}}
</style>
</head>
<body>

<header class="topbar">
  <div class="topbar-inner">
    <div class="brand">
      <div class="brand-icon">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3v18h18"/><path d="M7 15l4-5 3 3 5-7"/></svg>
      </div>
      <div>
        <div class="brand-title">KOBE — Consolidado</div>
        <div class="brand-sub">DRE — Comparativo por Revenda</div>
      </div>
    </div>
    <div class="topbar-fonte">
      Fonte: Lançamentos Contábeis<br>
      Gerado em <b>{gerado_em}</b> · uso gerencial interno — não auditado
    </div>
  </div>
</header>

<main class="wrap">

  <div class="page-head">
    <div class="page-title">DRE por Revenda — KOBE</div>
    <div class="page-sub">Jan–Jun/2026 (acumulado) · 10 revendas lado a lado · Visão gerencial · Valores em R$</div>
  </div>

  <div class="callout">Corte por REVENDA — não é uma medida oficial do MCP (<code>relatorio_dre</code> só filtra por EMPRESA). Usa a mesma DRE_CHAVES/VALOR_AJUSTADO do motor oficial, com REVENDA como filtro extra. A coluna <b>KOBE</b> é a soma das 10 revendas (a DRE tem 100% dos lançamentos da KOBE com revenda atribuída, então bate com o consolidado oficial).</div>

  <div class="card section-card">
    <div class="section-title">Demonstrativo de Resultado — Jan–Jun/2026 vs Acum./25 (R$)</div>
    <div class="table-scroll">
      <table>
        {thead}
        <tbody>
        {linhas_html}
        </tbody>
      </table>
    </div>
  </div>

  <div class="footer-note">
    Fonte: Lançamentos Contábeis (dataset <b>lancamentos_contabeis</b>), filtro <b>EMPRESA = "KOBE"</b>, aberto por <b>REVENDA</b> · Gerado em {gerado_em} · Uso gerencial interno — não auditado
  </div>

</main>
</body>
</html>
"""


def main() -> None:
    dados_por_revenda = carregar_dados()
    gerado_em = _dt.date.today().strftime("%d/%m/%Y")
    html = montar_html(dados_por_revenda, gerado_em)
    DESTINO.write_text(html, encoding="utf-8")
    print(f"ok — {DESTINO.name}: {len(html)} bytes")


if __name__ == "__main__":
    main()
