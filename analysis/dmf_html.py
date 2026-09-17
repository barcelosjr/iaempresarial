"""Geração da DMF e do relatório consolidado do COAF em HTML → PDF.

Segue **literalmente** o design system em `design_system/coaf-alerta-30-mil/`
(arquivos `00 - BASE`, `01 - COAF Relatorio Consolidado`, `02 - DMF CNPJ`,
`03 - DMF CPF`) — é a "regra" definida pelo usuário em 21/08/2026 para estes
três documentos, e substitui o gerador anterior em reportlab
(``analysis/dmf_pdf.py``, mantido no repositório mas não mais chamado por
``analysis/coaf_especie.py``).

Por que HTML + Chrome headless, e não reportlab
-------------------------------------------------

O design system é definido em CSS (tokens de cor, tipografia, componentes com
grid/flex) — reproduzir isso em reportlab seria traduzir CSS para Platypus à
mão, com alto risco de divergir do spec. Em vez disso, o HTML é montado com
os mesmos tokens do spec e impresso para PDF via Chrome headless
(``--print-to-pdf``), já instalado na máquina do usuário. A fonte Montserrat
é **embutida como ``@font-face`` local** (não via Google Fonts): um job em
lote que dispara e-mails reais não pode depender de a impressão headless
esperar corretamente o carregamento de uma webfont pela rede — testado e
confirmado que o Chrome headless não sincroniza esse carregamento de forma
confiável. Só há TTF real para os pesos 400 e 700 (extraídos do
``.docx`` do papel timbrado); os pesos 500/600 do spec caem no mais próximo
disponível.

Cada função pública devolve **o caminho do PDF gerado** — o HTML intermediário
é escrito em arquivo temporário e apagado depois da impressão.

Interface pública compatível com ``analysis/dmf_pdf.py``
----------------------------------------------------------

``analysis/coaf_especie.py`` importa deste módulo (ou do antigo) só três
nomes: :func:`gerar_dmf`, :func:`gerar_dmf_complementar`,
:func:`gerar_relatorio_consolidado` — mesma assinatura, mesmo comportamento
de retorno (``Path`` ou, no caso da complementar, ``None`` quando não há
nada novo a declarar).

**Não existe "DMF complementar" neste design.** O spec novo define só três
documentos (consolidado, DMF CNPJ, DMF CPF); o que é novo já aparece marcado
na própria coluna "Situação" do demonstrativo. Por isso
:func:`gerar_dmf_complementar` aqui **sempre devolve `None`** — mantida só
para a interface não quebrar quem a chama.
"""

from __future__ import annotations

import base64
import re
import subprocess
import sys
import tempfile
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.coaf_especie import PESSOA_FISICA, PESSOA_JURIDICA, rotulos_do_declarante  # noqa: E402

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
RAIZ_ASSETS = RAIZ_PROJETO / "assets"
CAMINHO_LOGO = RAIZ_ASSETS / "logo_grupo_mult.png"
CAMINHO_FONTE_REGULAR = RAIZ_ASSETS / "fontes" / "Montserrat-regular.ttf"
CAMINHO_FONTE_BOLD = RAIZ_ASSETS / "fontes" / "Montserrat-bold.ttf"

#: Candidatos de instalação do Chrome nesta máquina (Windows).
CANDIDATOS_CHROME = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)

#: Perfil dedicado do Chrome para a impressão headless, FORA do perfil padrão
#: do usuário e reaproveitado entre execuções.
#:
#: Sem ``--user-data-dir`` próprio, o headless usa o perfil padrão e trava
#: esperando o lock quando o usuário está com o Chrome aberto. Mas um perfil
#: NOVO a cada impressão é pior ainda: força o setup de primeira execução
#: toda vez (e o antivírus varre a pasta nova), o que estourou o timeout em
#: produção (31/08/2026). Um perfil fixo e reutilizado resolve os dois.
PERFIL_CHROME = RAIZ_PROJETO / ".chrome_perfil_dmf"

#: Tempo máximo por impressão. Com perfil reaproveitado o Chrome parte em
#: ~1-2s, mas sob antivírus/disco ocupado já foi visto passar de 45s — daí a
#: margem larga. O que realmente protege o job é gerar PDF só para quem vai
#: ser notificado (ver ``analysis/coaf_especie.py::executar``).
TIMEOUT_IMPRESSAO_S = 120


class ErroImpressaoPDF(Exception):
    """Falha ao converter o HTML em PDF (Chrome ausente ou impressão falhou)."""


def _localizar_chrome() -> str:
    """Acha o executável do Chrome/Edge nesta máquina.

    Raises:
        ErroImpressaoPDF: Se nenhum dos candidatos existir.
    """
    for caminho in CANDIDATOS_CHROME:
        if Path(caminho).exists():
            return caminho
    raise ErroImpressaoPDF(
        "Nenhum navegador Chromium encontrado para gerar o PDF (procurado em: "
        f"{', '.join(CANDIDATOS_CHROME)}). Instale o Google Chrome ou o "
        "Microsoft Edge."
    )


def _b64(caminho: Path) -> str:
    return base64.b64encode(caminho.read_bytes()).decode("ascii")


def _fmt_moeda(v: float) -> str:
    """``1234567.8`` -> ``"1.234.567,80"``."""
    return f"{v:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _fmt_pct(v: float) -> str:
    return f"{v:.1f}".replace(".", ",") + "%"


def _fmt_data(v: Any) -> str:
    if isinstance(v, (date, datetime)):
        return v.strftime("%d/%m/%Y")
    return str(v)


def _primeiro_nome(nome_completo: str) -> str:
    """``"TAMIRIS CHEILA MEIRELLES MORAIS"`` -> ``"TAMIRIS"`` (spec §01)."""
    partes = str(nome_completo or "").strip().split()
    return partes[0] if partes else ""


def _limpar_nome_arquivo(texto: str) -> str:
    """ASCII puro — acento em nome de arquivo vira mojibake em anexo de e-mail."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", str(texto)) if not unicodedata.combining(c)
    )
    seguro = "".join(c if c.isalnum() or c in " -" else "" for c in sem_acento)
    seguro = seguro.encode("ascii", "ignore").decode("ascii")
    return "-".join(seguro.split())[:40] or "SEM-NOME"


# --------------------------------------------------------------------------- #
# CSS — tokens transcritos de 00 - BASE (comum aos 3).md
# --------------------------------------------------------------------------- #
def _css_base() -> str:
    fonte_regular_b64 = _b64(CAMINHO_FONTE_REGULAR) if CAMINHO_FONTE_REGULAR.exists() else ""
    fonte_bold_b64 = _b64(CAMINHO_FONTE_BOLD) if CAMINHO_FONTE_BOLD.exists() else ""
    fontface = ""
    if fonte_regular_b64 and fonte_bold_b64:
        fontface = f"""
  @font-face{{font-family:'Montserrat';src:url(data:font/ttf;base64,{fonte_regular_b64}) format('truetype');font-weight:400;font-style:normal}}
  @font-face{{font-family:'Montserrat';src:url(data:font/ttf;base64,{fonte_bold_b64}) format('truetype');font-weight:700;font-style:normal}}
  /* Sem TTF real para 500/600 — o navegador casa com o peso disponível mais
     próximo (400 ou 700). Ver docstring do módulo. */
"""
    return (
        fontface
        + """
  :root{
    --vermelho: #c0000a;
    --vermelho-hover: #8d0008;
    --vermelho-fundo: #fbf1f1;
    --texto: #1a1a1a;
    --texto-sec: #666666;
    --texto-sec2: #767676;
    --texto-nota: #5a5a5a;
    --cinza-header: #434343;
    --fundo-bloco: #fafafa;
    --fundo-th: #f4f4f4;
    --borda-bloco: #d9d9d9;
    --borda-campo: #e8e8e8;
    --borda-tabela: #ebebeb;
    --borda-thead: #c8c8c8;
    --borda-nota: #e2e2e2;
    --tracejado: #b3b3b3;
    --canvas: #e9e9e9;
  }
  *{box-sizing:border-box}
  html,body{margin:0;padding:0;background:var(--canvas)}
  body{
    font-family:'Montserrat',Helvetica,sans-serif;
    color:var(--texto);
    font-size:11.5px;
    line-height:1.5;
    -webkit-font-smoothing:antialiased;
    display:flex;
    justify-content:center;
    padding:28px 16px;
  }
  a{color:var(--vermelho)}
  a:hover{color:var(--vermelho-hover)}
  .doc-page{
    width:8.27in;
    min-height:11.69in;
    background:#ffffff;
    box-shadow:0 1px 3px rgba(0,0,0,.14), 0 10px 28px rgba(0,0,0,.10);
    padding:0.6in;
    display:flex;
    flex-direction:column;
  }
  .doc-header{padding-bottom:10px}
  .doc-header-row{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;padding-bottom:10px}
  .doc-header img{height:36px;width:auto;display:block}
  .doc-header-sub{text-align:right;font-size:11px;color:var(--cinza-header);letter-spacing:0.01em;max-width:62%}
  .doc-header-rule{height:2px;background:var(--vermelho)}
  .doc-body{flex:1;padding-top:14px}
  .doc-footer{border-top:1px solid var(--borda-bloco);padding-top:6px;margin-top:18px;display:flex;justify-content:space-between;gap:16px;font-size:9.5px;color:var(--vermelho);font-weight:500;letter-spacing:0.02em}
  .doc-footer .meta{color:var(--texto-sec2)}

  h1{font-size:20px;line-height:1.15;letter-spacing:-0.01em;font-weight:700;color:var(--texto);margin:0}
  .apoio{font-size:10px;font-weight:400;color:var(--texto-sec);margin:4px 0 0}

  h2{font-size:10px;text-transform:uppercase;letter-spacing:0.16em;font-weight:700;color:var(--vermelho);border-bottom:1px solid var(--vermelho);padding-bottom:4px;margin:14px 0 8px}
  h2:first-of-type{margin-top:12px}

  .mini-label{font-size:8.5px;text-transform:uppercase;letter-spacing:0.12em;font-weight:600;color:var(--texto-sec2)}
  .valor-campo{font-size:11.5px;font-weight:600;color:var(--texto)}

  .meta-box{display:grid;grid-template-columns:1fr 1fr;border:1px solid var(--borda-bloco);background:var(--fundo-bloco)}
  .meta-cell{padding:6px 10px;display:flex;flex-direction:column;gap:2px}
  .meta-cell:nth-child(odd){border-right:1px solid var(--borda-bloco)}
  .meta-cell:not(:nth-last-child(-n+2)){border-bottom:1px solid var(--borda-bloco)}

  .linha-num{display:grid;grid-template-columns:22px 1fr;border-bottom:1px solid var(--borda-campo);padding:5px 0;align-items:baseline}
  .linha-num .num{font-size:10px;color:var(--texto-sec2);font-weight:600}
  .linha-num .conteudo{display:flex;flex-wrap:wrap;align-items:baseline;gap:8px}
  .linha-num .rotulo{font-size:9.5px;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;color:var(--texto-sec);min-width:120px}
  .linha-num .tracejado{flex:1;min-width:120px;border-bottom:1px dotted var(--tracejado);height:1.1em}
  .linha-num .checks{font-size:11px;color:var(--texto);display:flex;gap:14px;flex-wrap:wrap}

  .valor-declarado{display:flex;justify-content:space-between;align-items:center;border:1.5px solid var(--vermelho);background:var(--vermelho-fundo);padding:9px 14px;margin-top:2px}
  .valor-declarado .rotulo{font-size:9.5px;text-transform:uppercase;letter-spacing:0.1em;font-weight:600;color:var(--texto-sec)}
  .valor-declarado .valor{font-size:19px;font-weight:600;color:var(--texto);font-variant-numeric:tabular-nums}

  table{width:100%;border-collapse:collapse;margin-top:2px;font-variant-numeric:tabular-nums}
  thead tr{background:var(--fundo-th)}
  th{font-size:8.5px;text-transform:uppercase;letter-spacing:0.1em;font-weight:700;color:#4a4a4a;text-align:left;padding:7px 8px;border-bottom:1px solid var(--borda-thead)}
  th.num,td.num{text-align:right}
  td{font-size:10.5px;font-weight:400;color:var(--texto);padding:7px 8px;border-bottom:1px solid var(--borda-tabela)}
  tfoot td{font-size:12.5px;font-weight:600;border-bottom:none;border-top:1.5px solid var(--vermelho);padding-top:9px}
  .nowrap{white-space:nowrap}

  .nota{font-size:9.5px;font-weight:400;color:var(--texto-nota);border-top:1px solid var(--borda-nota);padding-top:8px;margin-top:14px}

  /* Tabela "Todos os recebimentos" do consolidado: nowrap e fonte reduzida
     em toda célula, conforme 01 - COAF Relatorio Consolidado.md */
  .tabela-detalhe th{font-size:8px}
  .tabela-detalhe tbody td{font-size:9.5px}

  .assinatura{width:64%;margin:22px auto 0;text-align:center}
  .assinatura .linha{border-bottom:1px solid var(--cinza-header);height:34px}
  .assinatura .legenda{font-size:9px;text-transform:uppercase;letter-spacing:0.08em;color:var(--texto-sec);margin-top:6px}
  .assinatura .nome{font-size:11px;font-weight:600;color:var(--texto);margin-top:2px}

  @page{size:A4;margin:0}
  @media print{
    html,body{background:#ffffff}
    body{padding:0;display:block}
    .doc-page{box-shadow:none;margin:0;width:auto;min-height:auto}
  }
"""
    )


_LOGO_B64 = _b64(CAMINHO_LOGO) if CAMINHO_LOGO.exists() else ""


def _header_html(subtitulo: str) -> str:
    img = (
        f'<img src="data:image/png;base64,{_LOGO_B64}" alt="Grupo Mult">'
        if _LOGO_B64
        else '<div style="font-weight:700;font-size:16px">GRUPO MULT</div>'
    )
    return f"""
  <div class="doc-header">
    <div class="doc-header-row">
      {img}
      <div class="doc-header-sub">{subtitulo}</div>
    </div>
    <div class="doc-header-rule"></div>
  </div>"""


def _footer_html(data_geracao: str) -> str:
    return f"""
  <div class="doc-footer">
    <div>www.multigrupo.com.br</div>
    <div class="meta">Gerado em {data_geracao} · uso interno · Página 1</div>
  </div>"""


def _pagina(title: str, subtitulo: str, corpo: str) -> str:
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>{_css_base()}</style>
</head>
<body>
<div class="doc-page">
{_header_html(subtitulo)}
  <div class="doc-body">
{corpo}
  </div>
{_footer_html(datetime.now().strftime('%d/%m/%Y %H:%M'))}
</div>
</body>
</html>"""


def _imprimir_pdf(html: str, destino: Path) -> Path:
    """Imprime um HTML para PDF via Chrome headless.

    Args:
        html: Documento HTML completo, autocontido (fontes e logo embutidos).
        destino: Caminho do PDF a gravar.

    Returns:
        ``destino``.

    Raises:
        ErroImpressaoPDF: Se o Chrome não existir ou a impressão falhar.
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    chrome = _localizar_chrome()

    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(html)
        tmp_path = Path(tmp.name)

    PERFIL_CHROME.mkdir(parents=True, exist_ok=True)

    try:
        url = "file:///" + str(tmp_path).replace("\\", "/")
        resultado = subprocess.run(
            [
                chrome,
                "--headless=new",
                "--disable-gpu",
                "--no-sandbox",
                f"--user-data-dir={PERFIL_CHROME}",
                f"--print-to-pdf={destino}",
                "--no-pdf-header-footer",
                "--virtual-time-budget=4000",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_IMPRESSAO_S,
        )
        if resultado.returncode != 0 or not destino.exists():
            raise ErroImpressaoPDF(
                f"Chrome headless falhou ao gerar {destino.name} "
                f"(código {resultado.returncode}): {resultado.stderr[-500:]}"
            )
    except subprocess.TimeoutExpired as exc:
        raise ErroImpressaoPDF(
            f"Impressão de {destino.name} excedeu {TIMEOUT_IMPRESSAO_S}s."
        ) from exc
    finally:
        tmp_path.unlink(missing_ok=True)

    return destino


# --------------------------------------------------------------------------- #
# Nomes de arquivo
# --------------------------------------------------------------------------- #
def nome_arquivo_dmf(caso: dict[str, Any]) -> str:
    entidade = _limpar_nome_arquivo(caso.get("empresa") or caso["revenda_principal"])
    cliente = _limpar_nome_arquivo(caso["nome_cliente"])
    return f"DMF_{entidade}_{cliente}_{date.today():%Y-%m-%d}.pdf"


def nome_arquivo_consolidado(caso: dict[str, Any]) -> str:
    return f"COAF-CONSOLIDADO_{_limpar_nome_arquivo(caso['nome_cliente'])}_{date.today():%Y-%m-%d}.pdf"


# --------------------------------------------------------------------------- #
# Responsável pelo caixa (mesma regra de dmf_pdf.py: prioriza o gatilho)
# --------------------------------------------------------------------------- #
def _responsavel_pelo_caixa(caso: dict[str, Any], destinatarios: dict[str, Any]) -> str:
    mapa = destinatarios.get("mapa", {})
    gatilho = caso.get("gatilho_incremento") or caso.get("gatilho") or {}
    candidatos = [(str(gatilho.get("revenda", "")), str(gatilho.get("caixa", "")))]
    candidatos += [(caso["revenda_principal"], str(c)) for c in caso["caixas"]]
    for chave in candidatos:
        dados = mapa.get(chave)
        if dados and dados.get("nome"):
            return dados["nome"]
    return destinatarios.get("responsavel_padrao", "")


# --------------------------------------------------------------------------- #
# Tabela "Demonstrativo dos recebimentos" — comum às duas DMFs
# --------------------------------------------------------------------------- #
def _tabela_demonstrativo(caso: dict[str, Any], apenas_novos: bool) -> tuple[str, float]:
    """Monta as linhas + total da tabela de 6 colunas das DMFs.

    Returns:
        Tupla ``(html_das_linhas_e_total, valor_total)``.
    """
    declarados = caso.get("hashes_declarados") or set()
    lancamentos = caso["lancamentos_novos"] if apenas_novos else caso["lancamentos"]
    linhas = []
    for _, r in lancamentos.sort_values("DATA").iterrows():
        situacao = "novo" if r["HASH_LANCAMENTO"] not in declarados else "já declarado"
        linhas.append(
            f'      <tr><td class="nowrap">{_fmt_data(r["DATA"])}</td>'
            f'<td class="nowrap">{r["REVENDA"]} / {r["CAIXA"]}</td>'
            f'<td class="nowrap">{r["ORIGEM"]}</td>'
            f'<td class="nowrap">{r["TITULO"]}</td>'
            f'<td class="nowrap">{situacao}</td>'
            f'<td class="num nowrap">{_fmt_moeda(float(r["VALOR"]))}</td></tr>'
        )
    total = float(lancamentos["VALOR"].sum())
    html = "\n".join(linhas) + (
        f'\n      <tfoot><tr><td colspan="5">Total</td>'
        f'<td class="num">{_fmt_moeda(total)}</td></tr></tfoot>'
    )
    return html, total


# --------------------------------------------------------------------------- #
# DMF — CNPJ e CPF
# --------------------------------------------------------------------------- #
def gerar_dmf(
    caso: dict[str, Any],
    destinatarios: dict[str, Any],
    pasta_destino: Path,
    apenas_novos: bool = False,
) -> Path:
    """Gera a DMF (pessoa jurídica ou física, conforme ``caso["tipo_pessoa"]``).

    Args:
        caso: Sub-caso de uma empresa, devolvido por
            ``analysis.coaf_especie.dividir_por_empresa``.
        destinatarios: Mapa de ``config/responsaveis_caixa.yaml``.
        pasta_destino: Pasta onde gravar o PDF.
        apenas_novos: Mantido por compatibilidade de assinatura; sem uso
            real neste design (não existe DMF complementar — ver docstring
            do módulo). Se ``True``, filtra a tabela aos lançamentos novos,
            mas o nome do arquivo e o restante do documento não mudam.

    Returns:
        Caminho do PDF gerado.
    """
    responsavel = _responsavel_pelo_caixa(caso, destinatarios)
    tipo = caso.get("tipo_pessoa", "")
    linhas_tabela, total_tabela = _tabela_demonstrativo(caso, apenas_novos)

    meta = [
        ("Empresa", caso.get("razao_social") or caso["empresa"]),
        ("Revenda", caso["revenda_principal"]),
        ("Caixa(s)", ", ".join(caso["caixas"])),
        ("Responsável pelo caixa", responsavel or "—"),
        (
            "Período apurado",
            f"{_fmt_data(caso['janela_inicio'])} a {_fmt_data(caso['janela_fim'])}",
        ),
        ("Recebimentos", str(caso["qtd_lancamentos"])),
    ]
    meta_html = "\n".join(
        f'      <div class="meta-cell"><span class="mini-label">{r}</span>'
        f'<span class="valor-campo">{v}</span></div>'
        for r, v in meta
    )

    nome_declarante = caso["nome_cliente"] if caso["nome_identificado"] else "______"
    apoio = (
        "Declaração obrigatória para recebimentos em espécie iguais ou "
        "superiores a R$ 30.000,00 apurados em até 6 meses."
    )

    if tipo == PESSOA_JURIDICA:
        rotulo_doc, doc_valor = "CNPJ", (caso.get("documento") or "______")
        campos_identificacao = f"""
    <div class="linha-num"><div class="num">1</div><div class="conteudo"><span class="rotulo">Razão social</span><span class="valor-campo">{nome_declarante}</span></div></div>
    <div class="linha-num"><div class="num">2</div><div class="conteudo"><span class="rotulo">{rotulo_doc}</span><span class="valor-campo">{doc_valor}</span></div></div>"""
        num_valor, num_natureza, num_modelo, num_data = "3", "4", "5", "6"
    else:
        # Pessoa física identificada, ou tipo não identificado — este design
        # não tem uma terceira variante; PF é o padrão mais seguro quando o
        # tipo não pôde ser determinado (não fabrica CNPJ, e os campos 3-5
        # ficam em branco para o declarante completar).
        rotulo_doc = "CPF" if tipo == PESSOA_FISICA else rotulos_do_declarante(tipo)[1]
        doc_valor = caso.get("documento") or "______"
        campos_identificacao = f"""
    <div class="linha-num"><div class="num">1</div><div class="conteudo"><span class="rotulo">Razão social</span><span class="valor-campo">{nome_declarante}</span></div></div>
    <div class="linha-num"><div class="num">2</div><div class="conteudo"><span class="rotulo">{rotulo_doc}</span><span class="valor-campo">{doc_valor}</span></div></div>
    <div class="linha-num"><div class="num">3</div><div class="conteudo"><span class="rotulo">Profissão</span><span class="tracejado"></span></div></div>
    <div class="linha-num"><div class="num">4</div><div class="conteudo"><span class="rotulo">Servidor público</span><span class="checks">( ) SIM &nbsp; ( ) NÃO &nbsp;&nbsp; ( ) FEDERAL &nbsp; ( ) ESTADUAL &nbsp; ( ) MUNICIPAL</span></div></div>
    <div class="linha-num"><div class="num">5</div><div class="conteudo"><span class="rotulo">Politicamente exposto</span><span class="checks">( ) SIM &nbsp; ( ) NÃO</span></div></div>"""
        num_valor, num_natureza, num_modelo, num_data = "6", "7", "8", "9"

    rotulo_valor = "Valor recebido em espécie" if tipo == PESSOA_JURIDICA else "Valor total recebido em espécie"

    corpo = f"""
    <h1>Declaração de Movimentação Financeira</h1>
    <div class="apoio">{apoio}</div>

    <div class="meta-box" style="margin-top:14px">
{meta_html}
    </div>

    <h2>Identificação do declarante</h2>{campos_identificacao}

    <h2>Valor declarado</h2>
    <div class="linha-num" style="border:none;padding:8px 0 0"><div class="num">{num_valor}</div>
      <div class="valor-declarado" style="flex:1">
        <span class="rotulo">{rotulo_valor}</span>
        <span class="valor">R$ {_fmt_moeda(total_tabela)}</span>
      </div>
    </div>

    <h2>Demonstrativo dos recebimentos em espécie — últimos 6 meses</h2>
    <table>
      <thead><tr><th>Data</th><th>Revenda / caixa</th><th>Origem</th><th>Lançamento</th><th>Situação</th><th class="num">Valor (R$)</th></tr></thead>
      <tbody>
{linhas_tabela}
      </tbody>
    </table>

    <h2>Natureza da operação e assinatura</h2>
    <div class="linha-num"><div class="num">{num_natureza}</div><div class="conteudo"><span class="rotulo">Natureza compra</span><span class="checks">( ) ESTOQUE &nbsp; ( ) VENDA DIRETA</span></div></div>
    <div class="linha-num"><div class="num">{num_modelo}</div><div class="conteudo"><span class="rotulo">Modelo do bem</span><span class="tracejado"></span></div></div>
    <div class="linha-num" style="border-bottom:none"><div class="num">{num_data}</div><div class="conteudo"><span class="rotulo">Data</span><span class="valor-campo">____ / ____ / ________</span></div></div>

    <div class="assinatura">
      <div class="linha"></div>
      <div class="legenda">Assinatura</div>
    </div>
"""
    html = _pagina(
        f"DMF — {caso['nome_cliente']}",
        f"Declaração de Movimentação Financeira (DMF) — {caso['empresa']}",
        corpo,
    )
    destino = pasta_destino / nome_arquivo_dmf(caso)
    return _imprimir_pdf(html, destino)


def gerar_dmf_complementar(
    caso: dict[str, Any], destinatarios: dict[str, Any], pasta_destino: Path
) -> Path | None:
    """Sempre ``None`` — este design não define uma DMF complementar.

    O que é novo desde a última declaração já aparece marcado na coluna
    "Situação" da própria DMF (ver :func:`_tabela_demonstrativo`). Mantida só
    para a interface bater com ``analysis/dmf_pdf.py``.
    """
    return None


# --------------------------------------------------------------------------- #
# Relatório consolidado
# --------------------------------------------------------------------------- #
def gerar_relatorio_consolidado(caso: dict[str, Any], pasta_destino: Path) -> Path:
    """Gera o relatório consolidado do grupo, exclusivo do setor de COAF.

    Args:
        caso: Caso consolidado do grupo, devolvido por
            ``analysis.coaf_especie.detectar``.
        pasta_destino: Pasta onde gravar o PDF.

    Returns:
        Caminho do PDF gerado.
    """
    lancamentos = caso["lancamentos"]
    total = float(caso["total"]) or 1.0
    contagem_por_empresa = lancamentos.groupby("EMPRESA")["VALOR"].count().to_dict()

    linhas_empresa = []
    for empresa, valor in sorted(caso["por_empresa"].items(), key=lambda kv: kv[1], reverse=True):
        linhas_empresa.append(
            f"      <tr><td>{empresa}</td><td class=\"num\">{contagem_por_empresa.get(empresa, 0)}</td>"
            f'<td class="num">{_fmt_moeda(float(valor))}</td>'
            f'<td class="num">{_fmt_pct(100.0 * float(valor) / total)}</td></tr>'
        )
    tabela_empresa = "\n".join(linhas_empresa)

    gatilho = caso.get("gatilho_incremento") or caso.get("gatilho")
    gatilho_html = ""
    if gatilho:
        campos_gatilho = [
            ("Revenda / caixa", f"{gatilho['revenda']} / caixa {gatilho['caixa']}"),
            ("Data do lançamento", _fmt_data(gatilho["data"])),
            ("Usuário do sistema", gatilho["usuario"]),
            ("Origem", gatilho["origem"]),
            ("Lançamento", gatilho["titulo"]),
            ("Valor do lançamento", f"R$ {_fmt_moeda(float(gatilho['valor']))}"),
            ("Acumulado no período", f"R$ {_fmt_moeda(float(gatilho['acumulado_no_gatilho']))}"),
        ]
        campos_html = "\n".join(
            f'      <div class="meta-cell"><span class="mini-label">{r}</span>'
            f'<span class="valor-campo">{v}</span></div>'
            for r, v in campos_gatilho
        )
        titulo_secao = "Lançamento que disparou a obrigação de declarar"
        if caso.get("gatilho_incremento"):
            titulo_secao += " — novo cruzamento"
        gatilho_html = f"""
    <h2>{titulo_secao}</h2>
    <div class="meta-box" style="grid-template-columns:1fr 1fr">
{campos_html}
    </div>"""

    declarados = caso.get("hashes_declarados") or set()
    linhas_detalhe = []
    for _, r in lancamentos.sort_values("DATA").iterrows():
        situacao = "novo" if r["HASH_LANCAMENTO"] not in declarados else "já declarado"
        linhas_detalhe.append(
            f'      <tr><td class="nowrap">{_fmt_data(r["DATA"])}</td>'
            f'<td class="nowrap">{r["REVENDA"]} / {r["CAIXA"]}</td>'
            f'<td class="nowrap">{r["ORIGEM"]}</td>'
            f'<td class="nowrap">{r["TITULO"]}</td>'
            f'<td class="nowrap">{_primeiro_nome(r["NOME_USUARIO"]).upper()}</td>'
            f'<td class="nowrap">{situacao}</td>'
            f'<td class="num nowrap">{_fmt_moeda(float(r["VALOR"]))}</td></tr>'
        )
    tabela_detalhe = "\n".join(linhas_detalhe)

    nome_cliente = (
        caso["nome_cliente"]
        if caso["nome_identificado"]
        else f"(sem nome no histórico — código {caso['codigo_cliente']})"
    )

    corpo = f"""
    <h1>Relatório consolidado — recebimentos em espécie</h1>
    <div class="apoio">Cliente: <strong>{nome_cliente}</strong> &nbsp;·&nbsp; Período: {_fmt_data(caso['janela_inicio'])} a {_fmt_data(caso['janela_fim'])}</div>

    <h2>Acumulado por empresa do grupo</h2>
    <table>
      <thead><tr><th>Empresa / marca</th><th class="num">Recebimentos</th><th class="num">Valor (R$)</th><th class="num">% do total</th></tr></thead>
      <tbody>
{tabela_empresa}
      </tbody>
      <tfoot><tr><td>Total do grupo</td><td class="num">{caso['qtd_lancamentos']}</td><td class="num">{_fmt_moeda(float(caso['total']))}</td><td class="num">100,0%</td></tr></tfoot>
    </table>
{gatilho_html}
    <h2>Todos os recebimentos do período — grupo consolidado</h2>
    <table class="tabela-detalhe">
      <thead><tr><th>Data</th><th>Revenda / caixa</th><th>Origem</th><th>Lançamento</th><th>Usuário</th><th>Situação</th><th class="num">Valor (R$)</th></tr></thead>
      <tbody>
{tabela_detalhe}
      </tbody>
      <tfoot><tr><td colspan="6">Total</td><td class="num">{_fmt_moeda(float(caso['total']))}</td></tr></tfoot>
    </table>

    <div class="nota">Os valores são apurados a partir dos lançamentos de caixa e conferem com os registros do período.</div>
"""
    html = _pagina(
        f"Consolidado COAF — {caso['nome_cliente']}",
        "Relatório consolidado COAF — uso interno de compliance",
        corpo,
    )
    destino = pasta_destino / nome_arquivo_consolidado(caso)
    return _imprimir_pdf(html, destino)
