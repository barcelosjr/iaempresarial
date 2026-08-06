"""Script de migração única: reestrutura painel_financeiro_corretora.html para
suportar o filtro de Ano (2025/2026). Não é para reuso — depois de rodar, os
dados por ano viram literais no HTML como qualquer outro bloco do painel.
"""
from __future__ import annotations

import re
from pathlib import Path

BUILD = Path(__file__).resolve().parent / "build"
HTML = BUILD / "painel_financeiro_corretora.html"
SCRATCH = Path(
    r"C:\Users\CONTRO~1\AppData\Local\Temp\claude\C--Users-Controladoria--claude-projects-iaempresarial"
    r"\0fccc12d-ca8a-4a2a-b657-10656c7cf6d5\scratchpad"
)


def remover_bloco(html: str, nome: str) -> str:
    inicio = f"  var {nome} = {{"
    i = html.index(inicio)
    j = html.index("\n  };", i) + len("\n  };\n")
    return html[:i] + html[j:]


def main() -> None:
    html = HTML.read_text(encoding="utf-8")

    for nome in (
        "DRE_EMP_2025",
        "DRE_DET_ANT",
        "DRE_DET",
        "DRE_DESC",
        "BAL_DET",
        "MOV_ANT",
        "MOV",
        "NAT",
        "FC_CONT",
    ):
        html = remover_bloco(html, nome)

    # SALDO_INI usa chaves { ... } numa linha só, não bate o padrão "\n  };".
    html = re.sub(r"  var SALDO_INI = \{.*?\};\n", "", html, flags=re.S)

    ano_2026 = (SCRATCH / "ano_2026.js").read_text(encoding="utf-8")
    ano_2025 = (SCRATCH / "ano_2025.js").read_text(encoding="utf-8")

    meses_2026 = "['Jan','Fev','Mar','Abr','Mai','Jun']"
    meses_2025 = "['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez']"

    bloco = (
        "  // ---- Dados por ano (filtro de Ano na sidebar) ----\n"
        "  // Cada entrada tem os mesmos blocos que o painel sempre teve, só que\n"
        "  // exclusivos da CORRETORA (para não pesar) e trocados via aplicarAno().\n"
        "  // Gerado por gerar_dados_corretora_ano.py --ano <ano> --mes-final <n>.\n"
        "  // 2026 é o ano corrente, em andamento (Jan-Jun); 2025 é ano fechado (Jan-Dez).\n"
        "  var DADOS_ANO = {\n"
        "    '2026': {\n"
        f"    meses: {meses_2026},\n"
        + ano_2026.rstrip("\n")
        + "\n    },\n"
        "    '2025': {\n"
        f"    meses: {meses_2025},\n"
        + ano_2025.rstrip("\n")
        + "\n    }\n"
        "  };\n\n"
        "  //: Anos disponíveis no seletor, mais recente primeiro.\n"
        "  var ANOS_DISPONIVEIS = ['2026','2025'];\n\n"
        "  var MESES, DRE_DET, DRE_DET_ANT, BAL_DET, MOV, MOV_ANT, NAT, FC_CONT, SALDO_INI, DRE_DESC;\n"
        "  function aplicarAno(ano){\n"
        "    var d = DADOS_ANO[ano];\n"
        "    MESES = d.meses; DRE_DET = d.dreDet; DRE_DET_ANT = d.dreDetAnt; BAL_DET = d.balDet;\n"
        "    MOV = d.mov; MOV_ANT = d.movAnt; NAT = d.nat; FC_CONT = d.fcCont;\n"
        "    SALDO_INI = d.saldoIni; DRE_DESC = d.dreDesc;\n"
        "  }\n"
        "  function anoAtual(){ return state.ano; }\n"
        "  function anoAnterior(){ return String(Number(state.ano) - 1); }\n"
        "  function mesFinalRotulo(){ return MESES[MESES.length - 1]; }\n"
        "  function mesFinalNum(){ return (MESES.length < 10 ? '0' : '') + MESES.length; }\n"
        "  function periodoRef(){ return mesFinalNum() + '/' + anoAtual(); }\n"
        "  function periodoRefAnt(){ return mesFinalNum() + '/' + anoAnterior(); }\n"
        "  function janAte(ano){ return 'Jan\\u2013' + mesFinalRotulo() + '/' + ano; }\n"
    )

    marcador_meses = "  var MESES = ['Jan','Fev','Mar','Abr','Mai','Jun'];\n"
    assert html.count(marcador_meses) == 1, "marcador de MESES não encontrado (ou duplicado)"
    html = html.replace(marcador_meses, bloco, 1)

    HTML.write_text(html, encoding="utf-8")
    print("ok — bytes finais:", len(html))


if __name__ == "__main__":
    main()
