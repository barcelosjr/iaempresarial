"""Geração da DMF (Declaração de Movimentação Financeira) em PDF.

Reproduz o formulário oficial da empresa (``docs/modelo_dmf.pdf``) — os 9
campos numerados, a linha de assinatura e as duas observações — em versão
institucional, seguindo ``design_system_relatorios.md`` §4: A4 retrato,
margens 18 mm × 15 mm, Helvetica, faixa de cabeçalho ``grafite-900`` com filete
``azul-800``, tabelas sem grade vertical e rodapé com paginação.

Duas coisas mudam em relação ao modelo original, ambas a pedido do gestor:

1. **Fica mais formal** — o modelo original é uma tabela sem identidade visual.
2. **Ganha o demonstrativo** — uma tabela com todos os recebimentos em espécie
   da janela de 6 meses (data, revenda/caixa, origem, título, valor) fechando
   com o total, que precisa bater com o campo 6.

O que é preenchido automaticamente e o que não é
------------------------------------------------

Só os campos **1 (nome)** e **6 (valor)** saem preenchidos, mais o cabeçalho de
identificação. O campo **2 (CNPJ/CPF) fica obrigatoriamente em branco**: esse
dado não existe no modelo semântico — ``CAIXAS`` não tem CPF nem CNPJ, e o nome
do cliente já vem de texto livre. Os campos 3 a 5 e 7 a 9 são de conhecimento
do responsável pelo caixa, não da base.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Any

from analysis.coaf_especie import rotulos_do_declarante
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image as ImagemFlow,
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

# Identidade visual extraída do papel timbrado oficial
# (``docs/MODELO DOC — GRUPO MULT.docx``). Ele tem precedência sobre a paleta
# azul de ``design_system_relatorios.md`` §4.1: a DMF é um documento que sai da
# empresa e vai à assinatura do cliente, então usa a marca real, não a paleta
# genérica dos relatórios gerenciais internos.
VERMELHO_MARCA = colors.HexColor("#C23C37")   # extraído do logo
VERMELHO_CLARO = colors.HexColor("#F7E9E8")   # fundo de destaque
GRAFITE_900 = colors.HexColor("#23272E")
GRAFITE_700 = colors.HexColor("#434343")      # cor do título no timbrado
CINZA_500 = colors.HexColor("#8A9099")
CINZA_300 = colors.HexColor("#D9DCE0")
CINZA_100 = colors.HexColor("#F4F5F7")

# Compatibilidade: o corpo do documento ainda referencia estes nomes.
AZUL_800 = VERMELHO_MARCA
AZUL_100 = VERMELHO_CLARO

# Margens do timbrado: 2,0 cm laterais, cabeçalho a 1,25 cm do topo.
MARGEM_LATERAL = 20 * mm
MARGEM_SUPERIOR = 12.5 * mm
MARGEM_INFERIOR = 18 * mm
ALTURA_FAIXA = 16 * mm

RAIZ_ASSETS = Path(__file__).resolve().parent.parent / "assets"
CAMINHO_LOGO = RAIZ_ASSETS / "logo_grupo_mult.png"
LARGURA_LOGO = 28.7 * mm   # 1,13 pol, como no timbrado
ALTURA_LOGO = 12.2 * mm    # 0,48 pol

SITE_INSTITUCIONAL = "www.multigrupo.com.br"

#: Largura útil da página: A4 (210 mm) menos as duas margens do timbrado.
#: Toda tabela tem de somar exatamente isto — passar disso faz o texto quebrar
#: em lugares errados, e a Montserrat é mais larga que a Helvetica.
LARGURA_UTIL = 170 * mm

NOME_EMISSOR = "GRUPO MULT"
NOME_DOCUMENTO = "Declaração de Movimentação Financeira (DMF)"


def _registrar_montserrat() -> tuple[str, str]:
    """Registra a Montserrat do timbrado, com Helvetica como reserva.

    As fontes vêm embutidas no ``.docx`` como TTF legítimo (não ofuscado), e
    foram extraídas para ``assets/fontes/``. Se sumirem, o documento continua
    sendo gerado em Helvetica em vez de quebrar — um PDF com a fonte errada é
    muito melhor que nenhum PDF.

    Returns:
        Tupla ``(fonte_regular, fonte_negrito)``.
    """
    pasta = RAIZ_ASSETS / "fontes"
    try:
        for nome, arquivo in (
            ("Montserrat", "Montserrat-regular.ttf"),
            ("Montserrat-Bold", "Montserrat-bold.ttf"),
        ):
            caminho = pasta / arquivo
            if not caminho.exists():
                raise FileNotFoundError(caminho)
            if nome not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(nome, str(caminho)))
        registerFontFamily(
            "Montserrat", normal="Montserrat", bold="Montserrat-Bold",
            italic="Montserrat", boldItalic="Montserrat-Bold",
        )
        return "Montserrat", "Montserrat-Bold"
    except Exception:  # fonte ausente ou corrompida
        return "Helvetica", "Helvetica-Bold"


FONTE, FONTE_BOLD = _registrar_montserrat()

#: Linha em branco para o responsável preencher à mão.
LINHA_VAZIA = "_" * 62

_ESTILO_CAMPO = ParagraphStyle(
    "campo", fontName=FONTE, fontSize=9, leading=12.5, textColor=GRAFITE_900
)
_ESTILO_CAMPO_PREENCHIDO = ParagraphStyle(
    "campo_preenchido",
    parent=_ESTILO_CAMPO,
    fontName=FONTE_BOLD,
)
_ESTILO_BLOCO = ParagraphStyle(
    "bloco",
    fontName=FONTE_BOLD,
    fontSize=9.5,
    leading=12,
    textColor=colors.white,
)
_ESTILO_NOTA = ParagraphStyle(
    "nota", fontName=FONTE, fontSize=7.5, leading=10, textColor=CINZA_500
)
_ESTILO_TABELA = ParagraphStyle(
    "tabela", fontName=FONTE, fontSize=7.5, leading=9.5, textColor=GRAFITE_900
)
_ESTILO_ASSINATURA = ParagraphStyle(
    "assinatura",
    fontName=FONTE,
    fontSize=8.5,
    leading=11,
    alignment=TA_CENTER,
    textColor=GRAFITE_700,
)


def _fmt_moeda(valor: float) -> str:
    """``1234567.8`` -> ``"1.234.567,80"``.

    A DMF declara valores específicos recebidos: diferente dos relatórios
    gerenciais (``design_system_relatorios.md`` §2, que arredonda para o real),
    aqui o centavo é mantido.
    """
    return f"{valor:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _fmt_data(valor: Any) -> str:
    """Formata uma data como ``DD/MM/AAAA``."""
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%d/%m/%Y")
    return str(valor)


def _rotulo_emissor(caso: dict[str, Any]) -> str:
    """Rótulo da faixa de cabeçalho, conforme design_system_relatorios.md §1.

    Um cliente pode ter recebimentos em várias marcas do grupo (há casos com
    oito). Concatenar todas estoura a faixa e colide com o nome do documento à
    direita — o design system já prevê a saída: quando não é uma empresa só, o
    emissor é "Consolidado". A lista completa fica no bloco de identificação,
    que quebra linha.
    """
    empresas = [e.strip() for e in str(caso["empresa"]).split("/") if e.strip()]
    return empresas[0] if len(empresas) == 1 else "Consolidado"


def nome_arquivo_dmf(caso: dict[str, Any], complementar: bool = False) -> str:
    """Nome do PDF, no padrão de ``design_system_relatorios.md`` §4.4.

    Args:
        caso: Caso detectado.
        complementar: Se ``True``, nomeia a DMF complementar (só o incremento),
            para não sobrescrever a cumulativa na mesma pasta.
    """
    def limpar(texto: str) -> str:
        # ASCII puro: "ó".isalnum() é True em Python, e acento no nome de
        # arquivo vira mojibake ao trafegar por console/anexo de e-mail.
        sem_acento = "".join(
            c
            for c in unicodedata.normalize("NFKD", str(texto))
            if not unicodedata.combining(c)
        )
        seguro = "".join(c if c.isalnum() or c in " -" else "" for c in sem_acento)
        seguro = seguro.encode("ascii", "ignore").decode("ascii")
        return "-".join(seguro.split())[:40] or "SEM-NOME"

    # A DMF é um documento POR EMPRESA — o nome tem que dizer qual, senão dois
    # anexos do mesmo cliente ficam indistinguíveis na caixa de entrada.
    entidade = limpar(caso.get("empresa") or caso["revenda_principal"])
    cliente = limpar(caso["nome_cliente"])
    prefixo = "DMF-COMPLEMENTAR" if complementar else "DMF"
    return f"{prefixo}_{entidade}_{cliente}_{date.today():%Y-%m-%d}.pdf"


class _DocumentoDMF(BaseDocTemplate):
    """Documento com faixa de cabeçalho e rodapé repetidos em toda página."""

    def __init__(
        self,
        caminho: Path,
        empresa: str,
        rotulo_documento: str = NOME_DOCUMENTO,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            str(caminho),
            pagesize=A4,
            leftMargin=MARGEM_LATERAL,
            rightMargin=MARGEM_LATERAL,
            topMargin=MARGEM_SUPERIOR + ALTURA_FAIXA + ALTURA_LOGO,
            bottomMargin=MARGEM_INFERIOR,
            title="Declaração de Movimentação Financeira",
            author=NOME_EMISSOR,
            **kwargs,
        )
        self.empresa = empresa
        self.rotulo_documento = rotulo_documento
        quadro = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="corpo",
        )
        self.addPageTemplates(
            [PageTemplate(id="padrao", frames=[quadro], onPage=self._decorar)]
        )

    def _decorar(self, canvas, doc) -> None:
        """Desenha o papel timbrado do Grupo Mult em toda página.

        Reproduz ``docs/MODELO DOC — GRUPO MULT.docx``: logo à esquerda, nome
        do documento à direita em cinza, filete na cor da marca, e rodapé com o
        site institucional e a paginação.
        """
        canvas.saveState()
        largura, altura = A4
        base_cabecalho = altura - MARGEM_SUPERIOR - ALTURA_LOGO

        if CAMINHO_LOGO.exists():
            canvas.drawImage(
                str(CAMINHO_LOGO),
                MARGEM_LATERAL,
                base_cabecalho,
                width=LARGURA_LOGO,
                height=ALTURA_LOGO,
                mask="auto",          # respeita a transparência do PNG
                preserveAspectRatio=True,
                anchor="sw",
            )
        else:
            canvas.setFillColor(GRAFITE_900)
            canvas.setFont(FONTE_BOLD, 13)
            canvas.drawString(MARGEM_LATERAL, base_cabecalho + 3, NOME_EMISSOR)

        canvas.setFillColor(GRAFITE_700)
        canvas.setFont(FONTE, 9)
        canvas.drawRightString(
            largura - MARGEM_LATERAL, base_cabecalho + 4, self.rotulo_documento
        )
        canvas.setFont(FONTE, 7.5)
        canvas.setFillColor(CINZA_500)
        canvas.drawRightString(
            largura - MARGEM_LATERAL, base_cabecalho - 5, self.empresa
        )

        # Filete na cor da marca, separando o timbrado do conteúdo.
        canvas.setStrokeColor(VERMELHO_MARCA)
        canvas.setLineWidth(1.2)
        canvas.line(
            MARGEM_LATERAL,
            base_cabecalho - 11,
            largura - MARGEM_LATERAL,
            base_cabecalho - 11,
        )

        # Rodapé: filete fino, site institucional, origem e paginação.
        y_rodape = MARGEM_INFERIOR - 6 * mm
        canvas.setStrokeColor(CINZA_300)
        canvas.setLineWidth(0.5)
        canvas.line(
            MARGEM_LATERAL, y_rodape + 5 * mm, largura - MARGEM_LATERAL, y_rodape + 5 * mm
        )
        canvas.setFont(FONTE, 7.5)
        canvas.setFillColor(VERMELHO_MARCA)
        canvas.drawString(MARGEM_LATERAL, y_rodape, SITE_INSTITUCIONAL)
        canvas.setFillColor(CINZA_500)
        canvas.drawCentredString(
            largura / 2,
            y_rodape,
            f"Gerado em {datetime.now():%d/%m/%Y %H:%M} · Uso interno",
        )
        canvas.setFillColor(VERMELHO_MARCA)
        canvas.drawRightString(largura - MARGEM_LATERAL, y_rodape, f"Página {doc.page}")
        canvas.restoreState()


def _titulo_bloco(texto: str) -> Table:
    """Faixa de cabeçalho de bloco, em ``grafite-700``."""
    tabela = Table([[Paragraph(texto, _ESTILO_BLOCO)]], colWidths=[LARGURA_UTIL])
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), GRAFITE_700),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return tabela


def _tabela_identificacao(caso: dict[str, Any], responsavel: str) -> Table:
    """Bloco de identificação — não existe no modelo original, foi acrescentado."""
    revendas = caso["revendas"]
    revenda_txt = (
        revendas[0]
        if len(revendas) == 1
        else f"{len(revendas)} revendas (ver demonstrativo)"
    )
    empresa_txt = caso.get("razao_social") or caso["empresa"]
    linhas = [
        ["Empresa:", empresa_txt, "Revenda:", revenda_txt],
        [
            "Caixa(s):",
            "; ".join(caso["caixas"]),
            "Responsável pelo caixa:",
            responsavel or "—",
        ],
        [
            "Período apurado:",
            f"{_fmt_data(caso['janela_inicio'])} a {_fmt_data(caso['janela_fim'])}",
            "Recebimentos:",
            str(caso["qtd_lancamentos"]),
        ],
    ]
    dados = [[Paragraph(str(c), _ESTILO_TABELA) for c in linha] for linha in linhas]
    tabela = Table(dados, colWidths=[26 * mm, 55 * mm, 40 * mm, 49 * mm])
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CINZA_100),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, CINZA_300),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return tabela


def _tabela_campos(numerados: list[tuple[str, str, bool]]) -> Table:
    """Monta a tabela de campos numerados do formulário.

    Args:
        numerados: Tuplas ``(número, conteúdo, preenchido)``. ``preenchido``
            controla o destaque em negrito dos campos que o sistema completa.

    Returns:
        Tabela sem grade vertical, com filetes horizontais entre campos.
    """
    dados = []
    for numero, conteudo, preenchido in numerados:
        estilo = _ESTILO_CAMPO_PREENCHIDO if preenchido else _ESTILO_CAMPO
        dados.append(
            [
                Paragraph(f"<b>{numero}</b>", _ESTILO_CAMPO),
                Paragraph(conteudo, estilo),
            ]
        )
    tabela = Table(dados, colWidths=[8 * mm, 162 * mm])
    estilo = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, CINZA_300),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    for i, (_, _, preenchido) in enumerate(numerados):
        if preenchido:
            estilo.append(("BACKGROUND", (0, i), (-1, i), AZUL_100))
    tabela.setStyle(TableStyle(estilo))
    return tabela


def _tabela_demonstrativo(caso: dict[str, Any], apenas_novos: bool = False) -> Table:
    """Tabela dos recebimentos da janela, com total — o bloco novo pedido.

    Cabeçalho repete a cada quebra de página (``repeatRows=1``), conforme
    ``design_system_relatorios.md`` §4.3.
    """
    linhas = caso["lancamentos_novos"] if apenas_novos else caso["lancamentos"]
    total = caso["incremento"] if apenas_novos else caso["total"]
    declarados = caso.get("hashes_declarados") or set()
    # Só vale destacar o que é novo quando o documento mistura as duas coisas.
    destacar_novos = not apenas_novos and bool(declarados)

    titulos = ["Data", "Revenda / Caixa", "Origem", "Título", "Valor (R$)"]
    if destacar_novos:
        titulos.insert(4, "Situação")
    cabecalho = [Paragraph(f"<b>{t}</b>", _ESTILO_TABELA) for t in titulos]

    dados = [cabecalho]
    indices_novos: list[int] = []
    for i, (_, linha) in enumerate(linhas.iterrows(), start=1):
        marca = " *" if linha["CAIXA_SINALIZADO"] else ""
        e_novo = linha["HASH_LANCAMENTO"] not in declarados
        celulas = [
            Paragraph(_fmt_data(linha["DATA"]), _ESTILO_TABELA),
            Paragraph(f"{linha['REVENDA']} / {linha['CAIXA']}{marca}", _ESTILO_TABELA),
            Paragraph(str(linha["ORIGEM"]), _ESTILO_TABELA),
            Paragraph(str(linha["TITULO"]), _ESTILO_TABELA),
            Paragraph(_fmt_moeda(float(linha["VALOR"])), _ESTILO_TABELA),
        ]
        if destacar_novos:
            rotulo = "<b>NOVO</b>" if e_novo else "já declarado"
            celulas.insert(4, Paragraph(rotulo, _ESTILO_TABELA))
            if e_novo:
                indices_novos.append(i)
        dados.append(celulas)

    rotulo_total = "<b>TOTAL NOVO</b>" if apenas_novos else "<b>TOTAL</b>"
    linha_total = [
        Paragraph(rotulo_total, _ESTILO_TABELA),
        Paragraph("", _ESTILO_TABELA),
        Paragraph("", _ESTILO_TABELA),
        Paragraph("", _ESTILO_TABELA),
        Paragraph(f"<b>{_fmt_moeda(total)}</b>", _ESTILO_TABELA),
    ]
    if destacar_novos:
        linha_total.insert(4, Paragraph("", _ESTILO_TABELA))
    dados.append(linha_total)

    larguras = [22 * mm, 42 * mm, 56 * mm, 20 * mm, 30 * mm]
    if destacar_novos:
        larguras = [20 * mm, 36 * mm, 46 * mm, 15 * mm, 23 * mm, 30 * mm]
    tabela = Table(dados, colWidths=larguras, repeatRows=1)
    coluna_valor = 5 if destacar_novos else 4
    tabela.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (coluna_valor, 0), (coluna_valor, -1), "RIGHT"),
                ("BACKGROUND", (0, 0), (-1, 0), CINZA_100),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, GRAFITE_700),
                ("LINEBELOW", (0, 1), (-1, -2), 0.5, CINZA_300),
                # Filete duplo sob o total-chave (§4.3).
                ("LINEABOVE", (0, -1), (-1, -1), 1.0, GRAFITE_900),
                ("BACKGROUND", (0, -1), (-1, -1), AZUL_100),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
            + [("BACKGROUND", (0, i), (-1, i), CINZA_100) for i in indices_novos]
        )
    )
    return tabela


def _bloco_assinatura(responsavel: str) -> Table:
    """Linha de assinatura, com o responsável pelo caixa identificado abaixo."""
    dados = [
        [Paragraph("_" * 55, _ESTILO_ASSINATURA)],
        [Paragraph("ASSINATURA", _ESTILO_ASSINATURA)],
        [Paragraph(responsavel or "Responsável pelo caixa", _ESTILO_ASSINATURA)],
    ]
    tabela = Table(dados, colWidths=[LARGURA_UTIL])
    tabela.setStyle(
        TableStyle(
            [
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]
        )
    )
    return tabela


def gerar_dmf_complementar(
    caso: dict[str, Any],
    responsaveis: dict[str, Any],
    pasta_destino: Path,
) -> Path | None:
    """Gera a DMF **complementar**: só os recebimentos ainda não declarados.

    Acompanha a DMF cumulativa quando o cliente volta a cruzar o limiar. A
    cumulativa é o retrato legal do período de 6 meses; esta isola o que
    motivou a nova cobrança, para o responsável não precisar comparar dois
    documentos linha a linha.

    Args:
        caso: Caso já passado por
            ``analysis.coaf_especie.enriquecer_com_incremento``.
        responsaveis: Mapa de ``config/responsaveis_caixa.yaml``.
        pasta_destino: Pasta onde gravar o PDF.

    Returns:
        Caminho do arquivo, ou ``None`` se não há nada novo a declarar.
    """
    novos = caso.get("lancamentos_novos")
    if novos is None or novos.empty:
        return None
    return gerar_dmf(caso, responsaveis, pasta_destino, apenas_novos=True)


def gerar_dmf(
    caso: dict[str, Any],
    responsaveis: dict[str, Any],
    pasta_destino: Path,
    apenas_novos: bool = False,
) -> Path:
    """Gera o PDF da DMF de um cliente detectado.

    Args:
        caso: Caso devolvido por ``analysis.coaf_especie.detectar``.
        responsaveis: Mapa carregado de ``config/responsaveis_caixa.yaml``.
        pasta_destino: Pasta onde gravar o PDF.
        apenas_novos: Se ``True``, produz a versão **complementar** — só os
            recebimentos ainda não cobertos por uma DMF enviada, com o campo 6
            trazendo o valor do incremento. Use
            :func:`gerar_dmf_complementar`, que já trata o caso sem novidade.

    Returns:
        Caminho do arquivo gerado.
    """
    pasta_destino.mkdir(parents=True, exist_ok=True)
    caminho = pasta_destino / nome_arquivo_dmf(caso, complementar=apenas_novos)

    # O responsável exibido é o do caixa que disparou a cobrança — o mesmo que
    # recebe o e-mail. Cai no caixa de maior valor da empresa quando o gatilho
    # não pertence a ela (a DMF é por empresa, o gatilho é do grupo).
    mapa = responsaveis.get("mapa", {})
    gatilho = caso.get("gatilho_incremento") or caso.get("gatilho") or {}
    candidatos = [(str(gatilho.get("revenda", "")), str(gatilho.get("caixa", "")))]
    candidatos += [(caso["revenda_principal"], str(c)) for c in caso["caixas"]]
    responsavel = ""
    for chave in candidatos:
        dados = mapa.get(chave)
        if dados and dados.get("nome"):
            responsavel = dados["nome"]
            break
    if not responsavel:
        responsavel = responsaveis.get("responsavel_padrao", "")

    nome_cliente = caso["nome_cliente"] if caso["nome_identificado"] else LINHA_VAZIA

    # Campos 1 e 2 mudam de rótulo conforme pessoa física ou jurídica, e o
    # documento já vem preenchido quando a base o tem (colunas Fisjur e
    # cpf_cnpj, acrescentadas em 19/08/2026).
    rotulo_nome, rotulo_doc = rotulos_do_declarante(caso.get("tipo_pessoa", ""))
    documento = caso.get("documento") or ""
    documento_preenchido = bool(documento)
    campo_documento = (
        f"{rotulo_doc}: <b>{documento}</b>"
        if documento_preenchido
        else f"{rotulo_doc}: {LINHA_VAZIA}"
    )

    if apenas_novos:
        valor_declarado = caso["incremento"]
        titulo_documento = "DECLARAÇÃO DE MOVIMENTAÇÃO FINANCEIRA — COMPLEMENTAR"
        titulo_demonstrativo = (
            "DEMONSTRATIVO DOS RECEBIMENTOS AINDA NÃO DECLARADOS"
        )
    else:
        valor_declarado = caso["total"]
        titulo_documento = "DECLARAÇÃO DE MOVIMENTAÇÃO FINANCEIRA"
        titulo_demonstrativo = (
            "DEMONSTRATIVO DOS RECEBIMENTOS EM ESPÉCIE — ÚLTIMOS 6 MESES"
        )

    estilo_titulo = ParagraphStyle(
        "titulo",
        fontName=FONTE_BOLD,
        fontSize=16,
        leading=19,
        textColor=AZUL_800,
        alignment=TA_CENTER,
        spaceAfter=2,
    )

    historia: list[Any] = [
        Paragraph(titulo_documento, estilo_titulo),
        Spacer(1, 6),
        _tabela_identificacao(caso, responsavel),
        Spacer(1, 10),
        _titulo_bloco("IDENTIFICAÇÃO DO DECLARANTE"),
        _tabela_campos(
            [
                ("1", f"{rotulo_nome}: <b>{nome_cliente}</b>", True),
                ("2", campo_documento, documento_preenchido),
                ("3", f"PROFISSÃO: {LINHA_VAZIA}", False),
                (
                    "4",
                    "SERVIDOR PÚBLICO: &nbsp;( ) SIM &nbsp;( ) NÃO &nbsp;&nbsp;&nbsp;"
                    "( ) FEDERAL &nbsp;( ) ESTADUAL &nbsp;( ) MUNICIPAL",
                    False,
                ),
                ("5", "POLITICAMENTE EXPOSTO: &nbsp;( ) SIM &nbsp;( ) NÃO", False),
            ]
        ),
        Spacer(1, 10),
        _titulo_bloco("VALOR DECLARADO"),
        _tabela_campos(
            [
                (
                    "6",
                    f"VALOR RECEBIDO EM ESPÉCIE: &nbsp;R$ <b>{_fmt_moeda(valor_declarado)}</b>"
                    + ("  <i>(complemento)</i>" if apenas_novos else ""),
                    True,
                )
            ]
        ),
        Spacer(1, 10),
        _titulo_bloco(titulo_demonstrativo),
        Spacer(1, 4),
        _tabela_demonstrativo(caso, apenas_novos=apenas_novos),
    ]

    if caso["tem_caixa_sinalizado"]:
        historia += [
            Spacer(1, 3),
            Paragraph(
                "* Lançamento registrado em caixa que não representa saldo real "
                "(códigos 9, 99 e 4; e 8 e 14 na Multicar Mits). Incluído na "
                "apuração por decisão da gestão, sinalizado para conferência.",
                _ESTILO_NOTA,
            ),
        ]

    historia += [
        Spacer(1, 12),
        KeepTogether(
            [
                _titulo_bloco("NATUREZA DA OPERAÇÃO E ASSINATURA"),
                _tabela_campos(
                    [
                        (
                            "7",
                            "NATUREZA COMPRA: &nbsp;( ) ESTOQUE &nbsp;( ) VENDA DIRETA",
                            False,
                        ),
                        ("8", f"MODELO DO BEM: {LINHA_VAZIA}", False),
                        ("9", "DATA: &nbsp;____ / ____ / ________", False),
                    ]
                ),
                Spacer(1, 16),
                _bloco_assinatura(responsavel),
                Spacer(1, 10),
                Paragraph(
                    "<b>Obs. 1:</b> Preenchimento obrigatório para valores iguais "
                    "ou superiores a 30 mil reais.",
                    _ESTILO_NOTA,
                ),
                Paragraph(
                    "<b>Obs. 2:</b> Se PJ, NÃO preencher as linhas 3, 4 e 5.",
                    _ESTILO_NOTA,
                ),
            ]
        ),
    ]

    if not caso["nome_identificado"]:
        historia += [
            Spacer(1, 6),
            Paragraph(
                "<b>Atenção:</b> o histórico do lançamento não identificou o nome "
                f"do cliente (código {caso['codigo_cliente']}). O campo 1 precisa "
                "ser preenchido manualmente antes da assinatura.",
                _ESTILO_NOTA,
            ),
        ]

    documento = _DocumentoDMF(caminho, empresa=_rotulo_emissor(caso))
    documento.build(historia)
    return caminho


def nome_arquivo_consolidado(caso: dict[str, Any]) -> str:
    """Nome do relatório consolidado do grupo, exclusivo do setor de COAF."""

    def limpar(texto: str) -> str:
        sem_acento = "".join(
            c
            for c in unicodedata.normalize("NFKD", str(texto))
            if not unicodedata.combining(c)
        )
        seguro = "".join(c if c.isalnum() or c in " -" else "" for c in sem_acento)
        seguro = seguro.encode("ascii", "ignore").decode("ascii")
        return "-".join(seguro.split())[:40] or "SEM-NOME"

    return f"COAF-CONSOLIDADO_{limpar(caso['nome_cliente'])}_{date.today():%Y-%m-%d}.pdf"


def _tabela_resumo_grupo(caso: dict[str, Any]) -> Table:
    """Quebra por empresa do acumulado do cliente, com o total do grupo."""
    cabecalho = [
        Paragraph(f"<b>{t}</b>", _ESTILO_TABELA)
        for t in ("Empresa / marca", "Recebimentos", "Valor (R$)", "% do total")
    ]
    dados = [cabecalho]
    total = caso["total"] or 1.0
    contagem = caso["lancamentos"].groupby("EMPRESA")["VALOR"].count().to_dict()
    for empresa, valor in sorted(
        caso["por_empresa"].items(), key=lambda kv: kv[1], reverse=True
    ):
        dados.append(
            [
                Paragraph(str(empresa), _ESTILO_TABELA),
                Paragraph(str(contagem.get(empresa, 0)), _ESTILO_TABELA),
                Paragraph(_fmt_moeda(float(valor)), _ESTILO_TABELA),
                Paragraph(f"{100.0 * float(valor) / total:.1f}%", _ESTILO_TABELA),
            ]
        )
    dados.append(
        [
            Paragraph("<b>TOTAL DO GRUPO</b>", _ESTILO_TABELA),
            Paragraph(f"<b>{caso['qtd_lancamentos']}</b>", _ESTILO_TABELA),
            Paragraph(f"<b>{_fmt_moeda(caso['total'])}</b>", _ESTILO_TABELA),
            Paragraph("<b>100,0%</b>", _ESTILO_TABELA),
        ]
    )
    tabela = Table(dados, colWidths=[74 * mm, 28 * mm, 38 * mm, 30 * mm], repeatRows=1)
    tabela.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("BACKGROUND", (0, 0), (-1, 0), CINZA_100),
                ("LINEBELOW", (0, 0), (-1, 0), 0.75, GRAFITE_700),
                ("LINEBELOW", (0, 1), (-1, -2), 0.5, CINZA_300),
                ("LINEABOVE", (0, -1), (-1, -1), 1.0, GRAFITE_900),
                ("BACKGROUND", (0, -1), (-1, -1), AZUL_100),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tabela


def _tabela_gatilho(gatilho: dict[str, Any], rotulo: str) -> Table:
    """Identifica o lançamento que disparou a cobrança e quem o registrou."""
    linhas = [
        ("Revenda / caixa:", f"{gatilho['revenda']} / caixa {gatilho['caixa']}"),
        ("Data do lançamento:", _fmt_data(gatilho["data"])),
        ("Usuário do sistema:", gatilho["usuario"]),
        ("Origem:", gatilho["origem"]),
        ("Título:", gatilho["titulo"]),
        ("Valor do lançamento:", f"R$ {_fmt_moeda(gatilho['valor'])}"),
        (rotulo, f"R$ {_fmt_moeda(gatilho['acumulado_no_gatilho'])}"),
    ]
    dados = [
        [
            Paragraph(f"<b>{rot}</b>", _ESTILO_TABELA),
            Paragraph(str(valor), _ESTILO_TABELA),
        ]
        for rot, valor in linhas
    ]
    tabela = Table(dados, colWidths=[52 * mm, 118 * mm])
    tabela.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CINZA_100),
                ("LINEBELOW", (0, 0), (-1, -2), 0.5, CINZA_300),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        )
    )
    return tabela


def gerar_relatorio_consolidado(caso: dict[str, Any], pasta_destino: Path) -> Path:
    """Relatório consolidado do grupo, enviado APENAS ao setor de COAF.

    As DMFs por empresa mostram cada pessoa jurídica isoladamente. Este
    documento é a visão que só o compliance precisa ter: o acumulado do cliente
    somando todas as empresas do grupo, a quebra entre elas, a identificação do
    lançamento que disparou a cobrança e a lista completa dos recebimentos.

    É um relatório, não um formulário: não tem campos a preencher nem linha de
    assinatura.

    Args:
        caso: Caso consolidado do grupo, devolvido por
            ``analysis.coaf_especie.detectar``.
        pasta_destino: Pasta onde gravar o PDF.

    Returns:
        Caminho do arquivo gerado.
    """
    pasta_destino.mkdir(parents=True, exist_ok=True)
    caminho = pasta_destino / nome_arquivo_consolidado(caso)

    estilo_titulo = ParagraphStyle(
        "titulo_rel",
        fontName=FONTE_BOLD,
        fontSize=16,
        leading=19,
        textColor=AZUL_800,
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    estilo_sub = ParagraphStyle(
        "sub_rel",
        fontName=FONTE,
        fontSize=8.5,
        leading=11,
        textColor=CINZA_500,
        alignment=TA_CENTER,
    )

    nome = (
        caso["nome_cliente"]
        if caso["nome_identificado"]
        else f"(sem nome no histórico — código {caso['codigo_cliente']})"
    )
    historia: list[Any] = [
        Paragraph("RELATÓRIO CONSOLIDADO — RECEBIMENTOS EM ESPÉCIE", estilo_titulo),
        Paragraph(
            f"Cliente: {nome} &nbsp;·&nbsp; Período: "
            f"{_fmt_data(caso['janela_inicio'])} a {_fmt_data(caso['janela_fim'])}"
            " &nbsp;·&nbsp; Valores em R$",
            estilo_sub,
        ),
        Spacer(1, 12),
        _titulo_bloco("ACUMULADO POR EMPRESA DO GRUPO"),
        Spacer(1, 4),
        _tabela_resumo_grupo(caso),
        Spacer(1, 12),
    ]

    gatilho = caso.get("gatilho_incremento") or caso.get("gatilho")
    if gatilho:
        e_incremento = bool(caso.get("gatilho_incremento"))
        historia += [
            _titulo_bloco(
                "LANÇAMENTO QUE DISPAROU A COBRANÇA"
                + (" — NOVO CRUZAMENTO" if e_incremento else "")
            ),
            Spacer(1, 4),
            _tabela_gatilho(
                gatilho,
                "Acumulado novo no gatilho:"
                if e_incremento
                else "Acumulado no gatilho:",
            ),
            Spacer(1, 4),
            Paragraph(
                "A cobrança da DMF foi endereçada ao responsável pelo caixa "
                "acima — é onde foi feito o lançamento que levou o acumulado do "
                "cliente a atingir o limiar. O usuário do sistema é informado "
                "apenas para rastreabilidade.",
                _ESTILO_NOTA,
            ),
            Spacer(1, 12),
        ]

    if caso.get("ja_notificado") and caso.get("incremento", 0.0) > 0:
        historia += [
            Paragraph(
                "<b>Cliente já declarado anteriormente.</b> Recebeu mais "
                f"R$ {_fmt_moeda(caso['incremento'])} desde a última DMF enviada — "
                "valor que sozinho atinge o limiar. Os recebimentos já declarados "
                "não entram nessa conta.",
                _ESTILO_NOTA,
            ),
            Spacer(1, 10),
        ]

    historia += [
        _titulo_bloco("TODOS OS RECEBIMENTOS DO PERÍODO — GRUPO CONSOLIDADO"),
        Spacer(1, 4),
        _tabela_demonstrativo(caso),
    ]

    if caso["tem_caixa_sinalizado"]:
        historia += [
            Spacer(1, 3),
            Paragraph(
                "* Lançamento registrado em caixa que não representa saldo real "
                "(códigos 9, 99 e 4; e 8 e 14 na Multicar Mits). Incluído na "
                "apuração por decisão da gestão, sinalizado para conferência.",
                _ESTILO_NOTA,
            ),
        ]

    historia += [
        Spacer(1, 12),
        Paragraph(
            "Documento de uso interno do setor de compliance. Os valores são "
            "apurados a partir dos lançamentos de caixa e conferem com os "
            "registros do período; não substituem a escrituração contábil.",
            _ESTILO_NOTA,
        ),
    ]

    documento = _DocumentoDMF(
        caminho,
        empresa="Consolidado",
        rotulo_documento="Relatório consolidado COAF — uso interno de compliance",
    )
    documento.build(historia)
    return caminho
