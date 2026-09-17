"""Exporta a DRE completa das 10 revendas da KOBE para um XML estruturado —
os mesmos dados que já estão embutidos nos 10 painéis
``painel_financeiro_kobe_*.html`` (gerados por ``gerar_dre_revendas_kobe.py``),
só que em formato de dado bruto (blueprint), não dentro de um bloco JS de HTML.

Reaproveita ``gerar()`` de ``gerar_dre_revendas_kobe.py`` — mesma consulta,
mesmos números; só muda o formato de saída.

Por que só DRE (sem Balanço/Fluxo de Caixa) — ver o mesmo aviso de
``gerar_dre_revendas_kobe.py``: ~73% do valor do Balanço da KOBE não tem
REVENDA atribuída (fica centralizado no grupo). A DRE tem 100% de cobertura,
por isso só ela foi exportada por revenda.

Uso (a partir da raiz do projeto)::

    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_xml_dre_revendas_kobe.py"

Gera ``Dashboard financeiro/dre_revendas_kobe.xml``.
"""

from __future__ import annotations

import datetime as _dt
import importlib.util
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:
    from powerbi.client import PowerBIClient  # noqa: E402
except ModuleNotFoundError as _exc:  # pragma: no cover - erro de ambiente
    raise SystemExit(
        f"Dependência ausente ({_exc.name}). Rode com o Python do venv:\n"
        '  .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_xml_dre_revendas_kobe.py"'
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
DRE_CHAVES = _gerador.DRE_CHAVES
CHAVE_PARA_CONTA = {chave: conta for conta, chave in DRE_CHAVES.items()}

PASTA = Path(__file__).resolve().parent
DESTINO = PASTA / "dre_revendas_kobe.xml"


def _add_contas(parent_el: ET.Element, dre_det: dict[str, list[float]]) -> None:
    for chave in sorted(dre_det):
        conta_el = ET.SubElement(
            parent_el, "conta", chave=chave, nome=CHAVE_PARA_CONTA.get(chave, chave)
        )
        for i, v in enumerate(dre_det[chave], start=1):
            m = ET.SubElement(conta_el, "mes", n=str(i))
            m.text = f"{v:.2f}"


def _add_drilldown(parent_el: ET.Element, dre_desc: dict[str, dict[str, list[float]]]) -> None:
    for chave in sorted(dre_desc):
        conta_el = ET.SubElement(
            parent_el, "conta", chave=chave, nome=CHAVE_PARA_CONTA.get(chave, chave)
        )
        for desc in sorted(dre_desc[chave]):
            d_el = ET.SubElement(conta_el, "descricao", nome=desc)
            for i, v in enumerate(dre_desc[chave][desc], start=1):
                m = ET.SubElement(d_el, "mes", n=str(i))
                m.text = f"{v:.2f}"


def _add_periodo(
    revenda_el: ET.Element,
    rotulo: str,
    ano: int,
    mes_inicial: int,
    mes_final: int,
    dre_det: dict,
    dre_det_ant: dict,
    dre_desc: dict,
    dre_desc_ant: dict,
) -> None:
    periodo_el = ET.SubElement(
        revenda_el,
        "periodo",
        ano=str(ano),
        mesInicial=str(mes_inicial),
        mesFinal=str(mes_final),
        rotulo=rotulo,
    )
    atual_el = ET.SubElement(periodo_el, "atual")
    _add_contas(atual_el, dre_det)

    ant_el = ET.SubElement(periodo_el, "anoAnterior", rotulo=f"mesmos meses de {ano - 1}")
    _add_contas(ant_el, dre_det_ant)

    drill_el = ET.SubElement(periodo_el, "drilldown", descricao="detalhe por DESCRICAO_CONTA, ano atual")
    _add_drilldown(drill_el, dre_desc)

    drill_ant_el = ET.SubElement(
        periodo_el, "drilldownAnoAnterior", descricao=f"detalhe por DESCRICAO_CONTA, mesmos meses de {ano - 1}"
    )
    _add_drilldown(drill_ant_el, dre_desc_ant)


def montar_xml(dados_por_revenda: dict[str, dict], gerado_em: str) -> bytes:
    root = ET.Element("dreRevendasKobe", geradoEm=gerado_em)

    fonte = ET.SubElement(root, "fonte")
    ET.SubElement(fonte, "tabela").text = "lancamentos"
    ET.SubElement(fonte, "medida").text = "VALOR_AJUSTADO"
    ET.SubElement(fonte, "filtro").text = 'EMPRESA = "KOBE"'
    ET.SubElement(fonte, "visao").text = "gerencial"
    ET.SubElement(fonte, "observacao").text = (
        "Corte por REVENDA — não é uma medida oficial exposta pelo MCP "
        "(relatorio_dre só filtra por EMPRESA; ver a nota \"Recorte por "
        "EMPRESA. REVENDA não é usada nos relatórios.\" em "
        "powerbi/dax_financeiro.py). Usa a mesma DRE_CHAVES e VALOR_AJUSTADO "
        "do motor oficial da DRE, só com REVENDA como filtro extra. A DRE "
        "tem 100% dos lançamentos da KOBE com revenda atribuída — diferente "
        "do Balanço (só ~27%), por isso só a DRE foi aberta por revenda "
        "(ver painéis painel_financeiro_kobe_*.html)."
    )
    ET.SubElement(fonte, "sinal").text = (
        "Valores aqui são a soma bruta de VALOR_AJUSTADO: receitas somam "
        "positivo; custos, despesas e deduções somam negativo. Os "
        "subtotais oficiais (Receita Líquida, Lucro Bruto, EBITDA, EBIT, "
        "LAIR, Lucro Líquido) são a SOMA DIRETA das contas deste arquivo, "
        "sem inverter sinal. Isso é diferente da tela dos painéis HTML, que "
        "exibe custo/despesa como número positivo com o rótulo \"(-)\" na "
        "frente — para bater com a tela, inverta o sinal das linhas "
        "não-receita."
    )

    for chave_revenda, sufixo in REVENDAS.items():
        revenda_el = ET.SubElement(
            root, "revenda", id=chave_revenda, arquivoHtml=f"painel_financeiro_{sufixo}.html"
        )
        d = dados_por_revenda[chave_revenda]
        dre_2026, dre_2025_comp, desc_2026, desc_2025_comp = d["2026"]
        dre_2025, dre_2024_comp, desc_2025, desc_2024_comp = d["2025"]
        _add_periodo(revenda_el, "Jan-Jun/2026", 2026, 1, 6, dre_2026, dre_2025_comp, desc_2026, desc_2025_comp)
        _add_periodo(revenda_el, "Jan-Dez/2025", 2025, 1, 12, dre_2025, dre_2024_comp, desc_2025, desc_2024_comp)

    bruto = ET.tostring(root, encoding="utf-8")
    bonito = minidom.parseString(bruto).toprettyxml(indent="  ", encoding="utf-8")
    linhas = [linha for linha in bonito.decode("utf-8").split("\n") if linha.strip()]
    return ("\n".join(linhas) + "\n").encode("utf-8")


def main() -> None:
    cliente = PowerBIClient()
    dados_por_revenda = _gerador.gerar(cliente)

    gerado_em = _dt.date.today().strftime("%d/%m/%Y")
    xml_bytes = montar_xml(dados_por_revenda, gerado_em)
    DESTINO.write_bytes(xml_bytes)
    print(f"ok — {DESTINO.name}: {len(xml_bytes)} bytes", file=sys.stderr)


if __name__ == "__main__":
    main()
