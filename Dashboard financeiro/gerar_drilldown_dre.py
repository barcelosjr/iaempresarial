"""Gera o bloco ``DRE_DESC`` (drill-down por DESCRICAO_CONTA) para um painel.

Companheiro de ``atualizar_dados.py``, mas escopo à parte: o drill-down da DRE
não é gerado por aquele script porque é uma feature opcional, hoje presente só
em alguns paineis. Este script imprime o literal JS pronto — cole/atualize o
bloco ``DRE_DESC`` no ``<script>`` do painel manualmente (ou redirecione a
saída e faça a troca com um editor).

Dois modos:

* ``--empresa CORRETORA`` — bloco raso ``{ contaKey: { descricao: [6 meses] } }``,
  formato usado no painel exclusivo da CORRETORA.
* sem ``--empresa`` — bloco aninhado por empresa
  ``{ empresaId: { contaKey: { descricao: [6 meses] } } }``, formato usado no
  painel consolidado (soma-se por empresa igual às outras estruturas do painel).

Uso (a partir da raiz do projeto)::

    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_drilldown_dre.py" > bloco.js
    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_drilldown_dre.py" --empresa CORRETORA > bloco.js
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:
    from powerbi.client import PowerBIClient  # noqa: E402
except ModuleNotFoundError as _exc:  # pragma: no cover - erro de ambiente
    raise SystemExit(
        f"Dependência ausente ({_exc.name}). Rode com o Python do venv:\n"
        '  .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_drilldown_dre.py"'
    ) from _exc

# Reaproveita as constantes de atualizar_dados.py (mesmo diretório, nome com espaço
# — precisa carregar por caminho, um "import atualizar_dados" comum não funciona).
_spec = importlib.util.spec_from_file_location(
    "atualizar_dados", Path(__file__).resolve().parent / "atualizar_dados.py"
)
_atualizar = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_atualizar)  # type: ignore[union-attr]

DRE_CHAVES = _atualizar.DRE_CHAVES
EMPRESAS = _atualizar.EMPRESAS
MES_FINAL = _atualizar.MES_FINAL
ANO = _atualizar.ANO


def _num(v: float) -> str:
    return "0" if abs(v) < 0.005 else f"{v:.2f}"


def _lista(vals: list[float]) -> str:
    return "[" + ",".join(_num(v) for v in vals) + "]"


def _query(filtro_empresa: str | None) -> str:
    de, ate = ANO * 100 + 1, ANO * 100 + MES_FINAL
    filtro = f' && [@E] = "{filtro_empresa}"' if filtro_empresa else ' && [@E] <> "REVENDA"'
    return (
        "EVALUATE\n"
        f"VAR _P = ADDCOLUMNS('lancamentos', \"@E\", TRIM('lancamentos'[EMPRESA]), "
        f"\"@C\", TRIM('lancamentos'[DRE]), \"@D\", TRIM('lancamentos'[DESCRICAO_CONTA]), "
        f"\"@K\", VALUE(RIGHT('lancamentos'[PERIODO],4))*100+VALUE(LEFT('lancamentos'[PERIODO],2)))\n"
        f"VAR _F = FILTER(_P, [@K] >= {de} && [@K] <= {ate} && [@C] <> \"\"{filtro})\n"
        'RETURN GROUPBY(_F, [@E], [@C], [@D], [@K], "@Valor", '
        "SUMX(CURRENTGROUP(), 'lancamentos'[VALOR_AJUSTADO]))"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--empresa",
        help="Gera o formato raso (sem empresa) para uma única empresa, "
        "ex.: CORRETORA. Sem esta flag, gera o formato aninhado por empresa.",
    )
    args = ap.parse_args()

    cliente = PowerBIClient()
    df = cliente.execute_dax(_query(args.empresa))

    # {empresa: {contaKey: {descricao: [0]*MES_FINAL}}}
    dados: dict[str, dict[str, dict[str, list[float]]]] = {}
    ignoradas: set[str] = set()
    for _, r in df.iterrows():
        emp = str(r["[@E]"]).strip()
        conta = str(r["[@C]"]).strip()
        chave = DRE_CHAVES.get(conta)
        if chave is None:
            ignoradas.add(conta)
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= MES_FINAL:
            continue
        desc = str(r["[@D]"]).strip()
        alvo = (
            dados.setdefault(emp, {})
            .setdefault(chave, {})
            .setdefault(desc, [0.0] * MES_FINAL)
        )
        alvo[mes - 1] += float(r["[@Valor]"] or 0)

    if ignoradas:
        print(
            f"// AVISO: contas DRE sem chave em DRE_CHAVES, ignoradas: {sorted(ignoradas)}",
            file=sys.stderr,
        )

    if args.empresa:
        contas = dados.get(args.empresa, {})
        print("  var DRE_DESC = {")
        chaves_ordenadas = sorted(contas)
        for i, chave in enumerate(chaves_ordenadas):
            virgula = "," if i < len(chaves_ordenadas) - 1 else ""
            print(f"    {chave}: {{")
            descs = sorted(contas[chave])
            for j, desc in enumerate(descs):
                v = "," if j < len(descs) - 1 else ""
                print(f"      '{desc}':{_lista(contas[chave][desc])}{v}")
            print(f"    }}{virgula}")
        print("  };")
    else:
        ordem = list(EMPRESAS)
        print("  var DRE_DESC = {")
        for i, emp in enumerate(ordem):
            virgula = "," if i < len(ordem) - 1 else ""
            contas = dados.get(emp, {})
            if not contas:
                print(f"    '{emp}': {{}}{virgula}")
                continue
            print(f"    '{emp}': {{")
            chaves_ordenadas = sorted(contas)
            for k, chave in enumerate(chaves_ordenadas):
                v1 = "," if k < len(chaves_ordenadas) - 1 else ""
                print(f"      {chave}: {{")
                descs = sorted(contas[chave])
                for j, desc in enumerate(descs):
                    v2 = "," if j < len(descs) - 1 else ""
                    print(f"        '{desc}':{_lista(contas[chave][desc])}{v2}")
                print(f"      }}{v1}")
            print(f"    }}{virgula}")
        print("  };")


if __name__ == "__main__":
    main()
