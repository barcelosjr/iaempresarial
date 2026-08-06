"""Gera um ano inteiro de dados de UMA empresa para o filtro de Ano do painel.

Versão genérica de ``gerar_dados_corretora_ano.py``/``gerar_dados_royal_ano.py``,
parametrizada por ``--empresa`` em vez de um arquivo por marca. Companheiro de
``atualizar_dados.py`` e ``gerar_drilldown_dre.py``: o painel exclusivo de uma
marca (``painel_financeiro_<marca>.html``) tem um seletor de Ano (2025/2026,
por ora), e cada ano precisa do mesmo conjunto de blocos que o painel
principal — só que **de uma empresa só**, para não pesar o arquivo.

Reaproveita os construtores de consulta DAX de ``atualizar_dados.py`` (que já
recebem ``de``/``ate`` como parâmetro, não presos às constantes ``ANO``/
``MES_FINAL`` do módulo) e a lógica de ``gerar_drilldown_dre.py`` para o
drill-down por DESCRICAO_CONTA. Nada é reconsultado por adivinhação — mesmas
consultas, só que com o intervalo de datas do ano pedido e filtradas por
``--empresa``.

Imprime o **literal JS de uma entrada do objeto ``DADOS_ANO``** (a chave do ano
fica de fora — acrescente na mão ao colar, ex.: ``'2025': { ... }``).

Uso (a partir da raiz do projeto)::

    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dados_empresa_ano.py" --empresa KOBE --ano 2025 > ano_2025.js
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
        '  .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dados_empresa_ano.py"'
    ) from _exc


def _carregar(nome_arquivo: str, nome_modulo: str):
    spec = importlib.util.spec_from_file_location(
        nome_modulo, Path(__file__).resolve().parent / nome_arquivo
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


_atualizar = _carregar("atualizar_dados.py", "atualizar_dados")
fin = _atualizar.fin
dax_kpis = _atualizar.dax_kpis
DRE_CHAVES = _atualizar.DRE_CHAVES
BAL_CHAVES = _atualizar.BAL_CHAVES
INDICADORES_EFIC = _atualizar.INDICADORES_EFIC

EMPRESA = ""  # definido em main() a partir de --empresa


def _num(v: float) -> str:
    return "0" if abs(v) < 0.005 else f"{v:.2f}"


def _lista(vals: list[float]) -> str:
    return "[" + ",".join(_num(v) for v in vals) + "]"


def _por_mes_uma_empresa(cliente, coluna: str, de: int, ate: int, mes_final: int):
    """{chave_js: [mes_final valores]} de uma coluna (DRE/Balanço), só EMPRESA."""
    df = cliente.execute_dax(_atualizar._q_por_mes(coluna, de, ate))
    chaves = DRE_CHAVES if coluna == "DRE" else BAL_CHAVES
    faltando = set()
    out: dict[str, list[float]] = {}
    for _, r in df.iterrows():
        if str(r["[@E]"]).strip() != EMPRESA:
            continue
        conta = str(r["[@C]"]).strip()
        chave = chaves.get(conta)
        if chave is None:
            faltando.add(conta)
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= mes_final:
            continue
        arr = out.setdefault(chave, [0.0] * mes_final)
        arr[mes - 1] += float(r["[@Valor]"] or 0)
    if faltando:
        print(f"// AVISO ({coluna}): contas sem chave, ignoradas: {sorted(faltando)}", file=sys.stderr)
    # Descarta contas sem nenhum lançamento no intervalo (o painel omite essas linhas).
    return {k: v for k, v in out.items() if any(abs(x) >= 0.005 for x in v)}


def _acumulado_uma_empresa(cliente, coluna: str, ate: int) -> dict[str, float]:
    df = cliente.execute_dax(_atualizar._q_acumulado(coluna, ate))
    chaves = DRE_CHAVES if coluna == "DRE" else BAL_CHAVES
    out: dict[str, float] = {}
    for _, r in df.iterrows():
        if str(r["[@E]"]).strip() != EMPRESA:
            continue
        chave = chaves.get(str(r["[@C]"]).strip())
        if chave is None:
            continue
        out[chave] = out.get(chave, 0.0) + float(r["[@Valor]"] or 0)
    return out


def gerar(ano: int, mes_final: int) -> dict:
    cliente = PowerBIClient()
    ate_ano = ano * 100 + mes_final
    ate_ant = (ano - 1) * 100 + mes_final

    print(f"// Consultando DRE {ano} (Jan-{mes_final:02d})…", file=sys.stderr)
    dre_det = _por_mes_uma_empresa(cliente, "DRE", ano * 100 + 1, ate_ano, mes_final)

    print(f"// Consultando DRE {ano-1} (mesmos meses, comparação)…", file=sys.stderr)
    dre_det_ant = _por_mes_uma_empresa(
        cliente, "DRE", (ano - 1) * 100 + 1, ate_ant, mes_final
    )

    print("// Consultando Balanço acumulado (dois períodos)…", file=sys.stderr)
    bal_cur = _acumulado_uma_empresa(cliente, "Balanço", ate_ano)
    bal_ant = _acumulado_uma_empresa(cliente, "Balanço", ate_ant)
    contas_bal = set(bal_cur) | set(bal_ant)
    bal_det = {}
    for chave in BAL_CHAVES.values():
        if chave not in contas_bal:
            continue
        par = [bal_cur.get(chave, 0.0), bal_ant.get(chave, 0.0)]
        if any(abs(x) >= 0.005 for x in par):
            bal_det[chave] = par

    print(f"// Consultando movimento mensal do Balanço {ano}…", file=sys.stderr)
    mov = _por_mes_uma_empresa(cliente, "Balanço", ano * 100 + 1, ate_ano, mes_final)

    print(f"// Consultando movimento mensal do Balanço {ano-1}…", file=sys.stderr)
    mov_ant = _por_mes_uma_empresa(
        cliente, "Balanço", (ano - 1) * 100 + 1, ate_ant, mes_final
    )

    print("// Consultando recortes por NATUREZA…", file=sys.stderr)
    dfn = cliente.execute_dax(_atualizar._q_natureza(ano * 100 + 1, ate_ano))
    nat = {k: [0.0] * mes_final for k in ("depD", "imobC", "imobD", "acumD")}
    for _, r in dfn.iterrows():
        if str(r["[@E]"]).strip() != EMPRESA:
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= mes_final:
            continue
        dre_c = str(r["[@D]"]).strip()
        bal_c = str(r["[@C]"]).strip()
        natu = str(r["[@N]"]).strip()
        valor = float(r["[@Valor]"] or 0)
        if dre_c in fin.DRE_G5_DEPRECIACAO and natu == "D":
            nat["depD"][mes - 1] += valor
        if bal_c in fin.FC_IMOBILIZADO:
            nat["imobC" if natu == "C" else "imobD"][mes - 1] += valor
        if bal_c in fin.FC_DEPRECIACAO_ACUM and natu == "D":
            nat["acumD"][mes - 1] += valor

    print("// Consultando resultado contábil (insumo do Fluxo de Caixa)…", file=sys.stderr)
    dfc = cliente.execute_dax(_atualizar._q_resultado_contabil(ano * 100 + 1, ate_ano))
    fc_cont = {"lucro": [0.0] * mes_final, "depD": [0.0] * mes_final}
    for _, r in dfc.iterrows():
        if str(r["[@E]"]).strip() != EMPRESA:
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= mes_final:
            continue
        conta = str(r["[@C]"]).strip()
        valor = float(r["[@Valor]"] or 0)
        if conta in DRE_CHAVES:
            fc_cont["lucro"][mes - 1] += valor
        if conta in fin.DRE_G5_DEPRECIACAO and str(r["[@N]"]).strip() == "D":
            fc_cont["depD"][mes - 1] += valor

    print("// Consultando saldo de caixa inicial (31/12 do ano anterior)…", file=sys.stderr)
    df_ini = cliente.execute_dax(_atualizar._q_acumulado("Balanço", (ano - 1) * 100 + 12))
    saldo_ini = 0.0
    for _, r in df_ini.iterrows():
        if str(r["[@E]"]).strip() == EMPRESA and str(r["[@C]"]).strip() in fin.BAL_DISPONIBILIDADES:
            saldo_ini += float(r["[@Valor]"] or 0)

    print("// Consultando drill-down DESCRICAO_CONTA…", file=sys.stderr)
    dfd = cliente.execute_dax(
        f"EVALUATE\n"
        f"VAR _P = ADDCOLUMNS('lancamentos', \"@E\", TRIM('lancamentos'[EMPRESA]), "
        f"\"@C\", TRIM('lancamentos'[DRE]), \"@D\", TRIM('lancamentos'[DESCRICAO_CONTA]), "
        f"\"@K\", {fin._expr_chave()})\n"
        f"VAR _F = FILTER(_P, [@E] = \"{EMPRESA}\" && [@K] >= {ano*100+1} && "
        f"[@K] <= {ate_ano} && [@C] <> \"\")\n"
        'RETURN GROUPBY(_F, [@C], [@D], [@K], "@Valor", '
        "SUMX(CURRENTGROUP(), 'lancamentos'[VALOR_AJUSTADO]))"
    )
    dre_desc: dict[str, dict[str, list[float]]] = {}
    for _, r in dfd.iterrows():
        conta = str(r["[@C]"]).strip()
        chave = DRE_CHAVES.get(conta)
        if chave is None:
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= mes_final:
            continue
        desc = str(r["[@D]"]).strip()
        arr = dre_desc.setdefault(chave, {}).setdefault(desc, [0.0] * mes_final)
        arr[mes - 1] += float(r["[@Valor]"] or 0)

    return {
        "meses": mes_final,
        "dreDet": dre_det,
        "dreDetAnt": dre_det_ant,
        "balDet": bal_det,
        "mov": mov,
        "movAnt": mov_ant,
        "nat": nat,
        "fcCont": fc_cont,
        "saldoIni": saldo_ini,
        "dreDesc": dre_desc,
    }


def emitir(dados: dict) -> None:
    ind = "    "
    print(f"{ind}dreDet: {{'{EMPRESA}': {{")
    itens = [f"{k}:{_lista(v)}" for k, v in dados["dreDet"].items()]
    print(",\n".join(f"{ind}  {it}" for it in itens))
    print(f"{ind}}}}},")

    print(f"{ind}dreDetAnt: {{'{EMPRESA}': {{")
    itens = [f"{k}:{_lista(v)}" for k, v in dados["dreDetAnt"].items()]
    print(",\n".join(f"{ind}  {it}" for it in itens))
    print(f"{ind}}}}},")

    print(f"{ind}balDet: {{'{EMPRESA}': {{")
    itens = [f"{k}:{_lista(v)}" for k, v in dados["balDet"].items()]
    print(",\n".join(f"{ind}  {it}" for it in itens))
    print(f"{ind}}}}},")

    print(f"{ind}mov: {{'{EMPRESA}': {{")
    itens = [f"{k}:{_lista(v)}" for k, v in dados["mov"].items()]
    print(",\n".join(f"{ind}  {it}" for it in itens))
    print(f"{ind}}}}},")

    print(f"{ind}movAnt: {{'{EMPRESA}': {{")
    itens = [f"{k}:{_lista(v)}" for k, v in dados["movAnt"].items()]
    print(",\n".join(f"{ind}  {it}" for it in itens))
    print(f"{ind}}}}},")

    print(f"{ind}nat: {{'{EMPRESA}': {{")
    itens = [f"{k}:{_lista(v)}" for k, v in dados["nat"].items()]
    print(",\n".join(f"{ind}  {it}" for it in itens))
    print(f"{ind}}}}},")

    print(f"{ind}fcCont: {{'{EMPRESA}': {{")
    itens = [f"{k}:{_lista(v)}" for k, v in dados["fcCont"].items()]
    print(",\n".join(f"{ind}  {it}" for it in itens))
    print(f"{ind}}}}},")

    print(f"{ind}saldoIni: {{'{EMPRESA}':{_num(dados['saldoIni'])}}},")

    print(f"{ind}dreDesc: {{")
    chaves = sorted(dados["dreDesc"])
    for i, chave in enumerate(chaves):
        print(f"{ind}  {chave}: {{")
        descs = sorted(dados["dreDesc"][chave])
        linhas_desc = [f"'{d}':{_lista(dados['dreDesc'][chave][d])}" for d in descs]
        print(",\n".join(f"{ind}    {it}" for it in linhas_desc))
        print(f"{ind}  }}{',' if i < len(chaves)-1 else ''}")
    print(f"{ind}}}")


def main() -> None:
    global EMPRESA
    ap = argparse.ArgumentParser()
    ap.add_argument("--empresa", required=True, help='Ex.: KOBE, MIT, ROYAL, CORRETORA')
    ap.add_argument("--ano", type=int, required=True)
    ap.add_argument("--mes-final", type=int, default=12)
    args = ap.parse_args()
    EMPRESA = args.empresa

    dados = gerar(args.ano, args.mes_final)
    print(f"// ===== Ano {args.ano} ({EMPRESA}) — mes_final={args.mes_final} =====", file=sys.stderr)
    emitir(dados)


if __name__ == "__main__":
    main()
