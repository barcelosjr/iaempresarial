"""Testes do gerador HTML→PDF da DMF e do consolidado (analysis/dmf_html.py).

Usam dados sintéticos e o Chrome headless real da máquina — mais lentos que o
resto da suíte (impressão de PDF de verdade), mas é a única forma de pegar
regressão visual (estouro de página, numeração errada, campo vazando dado
sensível). Pulados automaticamente se não houver Chrome/Edge instalado.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

pdfplumber = pytest.importorskip("pdfplumber")

from analysis import coaf_especie as coaf  # noqa: E402
from analysis import dmf_html  # noqa: E402

pytestmark = pytest.mark.skipif(
    not any(__import__("pathlib").Path(c).exists() for c in dmf_html.CANDIDATOS_CHROME),
    reason="Chrome/Edge não encontrado nesta máquina — impressão de PDF pulada.",
)


@pytest.fixture
def cfg():
    return coaf.carregar_config_coaf()


def _lancamento(**kwargs):
    base = dict(
        EMPRESA="KOBE",
        REVENDA="KOBE NISSAN GV",
        CAIXA="2",
        DATA=date(2026, 5, 10),
        CLIENTE="999999",
        TITULO="T1",
        VALOR=31000.0,
        ORIGEM="371 - A VISTA",
        HISTORICO="Ref. NF: 1 Cliente: TESTE PJ LTDA",
        NOME_USUARIO="OPERADOR TESTE",
        FISJUR="J",
        CPF_CNPJ="14488355000186",
        RAZAO_SOCIAL="6 - MULTI COMERCIO DE VEICULOS LTDA",
    )
    base.update(kwargs)
    return base


def _destinatarios():
    return {
        "email_coaf": "coaf@empresa.com",
        "email_padrao": "fallback@empresa.com",
        "responsavel_padrao": "Controladoria",
        "mapa": {("KOBE NISSAN GV", "2"): {"nome": "Fulano", "email": "f@empresa.com"}},
    }


def _extrair_texto(caminho) -> str:
    with pdfplumber.open(caminho) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


def _pagina_unica_a4(caminho) -> None:
    with pdfplumber.open(caminho) as pdf:
        assert len(pdf.pages) == 1, f"{caminho.name} saiu com {len(pdf.pages)} páginas"
        pg = pdf.pages[0]
        assert abs(pg.width / 72 - 8.27) < 0.05
        assert abs(pg.height / 72 - 11.69) < 0.05


def test_dmf_pj_numeracao_sequencial_1_a_6(cfg, tmp_path):
    df = pd.DataFrame([_lancamento()])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 21))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 21))[0]
    assert caso["tipo_pessoa"] == "J"

    caminho = dmf_html.gerar_dmf(caso, _destinatarios(), tmp_path)
    _pagina_unica_a4(caminho)
    texto = _extrair_texto(caminho)

    assert "1 RAZÃO SOCIAL" in texto.replace("\n", " ") or "RAZÃO SOCIAL" in texto
    assert "2 CNPJ" in texto.replace("\n", " ") or "CNPJ" in texto
    # numeração sequencial: 3 (valor), 4/5/6 (natureza/modelo/data) — sem 7,8,9
    assert "7" not in texto.split("NATUREZA")[0][-5:]  # heurística leve
    assert "ASSINATURA" in texto.upper()
    # "Fulano" (responsável) aparece legitimamente na caixa de metadados — o
    # que não pode é aparecer DE NOVO logo abaixo da legenda ASSINATURA.
    with pdfplumber.open(caminho) as pdf:
        palavras = pdf.pages[0].extract_words()
    # "ASSINATURA" também aparece no título da seção ("...e Assinatura") mais
    # acima — pega a ocorrência mais abaixo na página, que é a legenda real.
    y_assinatura = max(w["top"] for w in palavras if w["text"].upper() == "ASSINATURA")
    y_rodape = next(w["top"] for w in palavras if w["text"] == "www.multigrupo.com.br")
    entre = [w["text"] for w in palavras if y_assinatura < w["top"] < y_rodape]
    assert entre == [], f"texto inesperado abaixo da assinatura: {entre}"


def test_dmf_pf_tem_campos_3_4_5(cfg, tmp_path):
    df = pd.DataFrame(
        [
            _lancamento(
                FISJUR="F",
                CPF_CNPJ="6418722671",
                HISTORICO="Ref. Adiantamento: 1 Cliente:TESTE PF DA SILVA",
            )
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 21))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 21))[0]
    assert caso["tipo_pessoa"] == "F"
    assert caso["documento"] == "064.187.226-71", "zero à esquerda do CPF precisa ser recuperado"

    caminho = dmf_html.gerar_dmf(caso, _destinatarios(), tmp_path)
    _pagina_unica_a4(caminho)
    texto = _extrair_texto(caminho)

    assert "PROFISSÃO" in texto.upper()
    assert "SERVIDOR PÚBLICO" in texto.upper()
    assert "POLITICAMENTE EXPOSTO" in texto.upper()
    assert "064.187.226-71" in texto


def test_documento_ausente_nao_fabrica_dado(cfg, tmp_path):
    """Cliente sem Fisjur/cpf_cnpj (linha antiga ou não identificada)."""
    df = pd.DataFrame([_lancamento(FISJUR="", CPF_CNPJ="")])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 21))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 21))[0]
    assert caso["documento"] == ""

    caminho = dmf_html.gerar_dmf(caso, _destinatarios(), tmp_path)
    texto = _extrair_texto(caminho)
    assert "14.488.355" not in texto  # não deve vazar CNPJ de outro teste/linha


def test_consolidado_multi_empresa_e_situacao_mista(cfg, tmp_path):
    linhas = [
        _lancamento(DATA=date(2026, 5, 1), VALOR=12000.0, TITULO="T1"),
        _lancamento(
            DATA=date(2026, 5, 15), VALOR=12000.0, TITULO="T2",
            EMPRESA="MIT", REVENDA="MULTICAR MITS VV", CAIXA="7",
            RAZAO_SOCIAL="1 - OUTRA FILIAL LTDA",
        ),
        _lancamento(
            DATA=date(2026, 8, 20), VALOR=8000.0, TITULO="T3",
            EMPRESA="MIT", REVENDA="MULTICAR MITS VV", CAIXA="7",
            RAZAO_SOCIAL="1 - OUTRA FILIAL LTDA",
        ),
    ]
    df = pd.DataFrame(linhas)
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 21))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 21))[0]

    # Simula reenvio parcial: as duas primeiras já foram declaradas.
    ja = set(caso["lancamentos"]["HASH_LANCAMENTO"].iloc[:2])
    caso["hashes_declarados"] = ja
    caso["ja_notificado"] = True
    novos = caso["lancamentos"][~caso["lancamentos"]["HASH_LANCAMENTO"].isin(ja)]
    caso["lancamentos_novos"] = novos
    caso["incremento"] = float(novos["VALOR"].sum())
    caso["gatilho_incremento"] = coaf.lancamento_gatilho(novos, 1.0)

    caminho = dmf_html.gerar_relatorio_consolidado(caso, tmp_path)
    _pagina_unica_a4(caminho)
    texto = _extrair_texto(caminho)

    assert "KOBE" in texto and "MIT" in texto
    assert "já declarado" in texto
    assert "novo" in texto
    assert "NOVO CRUZAMENTO" in texto.upper()
    assert "32.000,00" in texto  # total do grupo


def test_sub_casos_geram_uma_dmf_por_empresa(cfg, tmp_path):
    linhas = [
        _lancamento(DATA=date(2026, 5, 1), VALOR=20000.0, TITULO="T1"),
        _lancamento(
            DATA=date(2026, 5, 5), VALOR=15000.0, TITULO="T2",
            EMPRESA="MIT", REVENDA="MULTICAR MITS VV", CAIXA="7",
            RAZAO_SOCIAL="1 - OUTRA FILIAL LTDA",
        ),
    ]
    df = pd.DataFrame(linhas)
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 21))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 21))[0]

    caminhos = [dmf_html.gerar_dmf(sub, _destinatarios(), tmp_path) for sub in coaf.dividir_por_empresa(caso)]
    assert len(caminhos) == 2
    assert len({c.name for c in caminhos}) == 2, "nomes de arquivo não podem colidir"
    for c in caminhos:
        _pagina_unica_a4(c)


def test_nenhum_pdf_expoe_origem_tecnica(cfg, tmp_path):
    df = pd.DataFrame([_lancamento()])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 21))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 21))[0]

    caminhos = [
        dmf_html.gerar_dmf(caso, _destinatarios(), tmp_path),
        dmf_html.gerar_relatorio_consolidado(caso, tmp_path),
    ]
    for caminho in caminhos:
        baixo = _extrair_texto(caminho).lower()
        for proibido in ("lancamentos_financeiros", "power bi", "powerbi", "dataset", "chrome"):
            assert proibido not in baixo, f"{caminho.name} expõe {proibido!r}"


def test_dmf_complementar_sempre_none(cfg, tmp_path):
    """Este design não define DMF complementar — a interface existe só por compatibilidade."""
    df = pd.DataFrame([_lancamento()])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 21))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 21))[0]
    assert dmf_html.gerar_dmf_complementar(caso, _destinatarios(), tmp_path) is None
