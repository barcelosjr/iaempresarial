"""Gera um ano inteiro de dados de TODAS as empresas para o filtro de Ano do
painel consolidado (``painel_financeiro.html``).

Versão multi-marca de ``gerar_dados_empresa_ano.py``: em vez de filtrar uma
única EMPRESA, reaproveita o padrão de ``atualizar_dados.py`` — consulta uma
vez só (sem filtro de empresa) e agrupa client-side por EMPRESA — e adiciona
o drill-down por DESCRICAO_CONTA (aninhado por empresa, formato usado pelo
``DRE_DESC`` do painel consolidado, companheiro de ``gerar_drilldown_dre.py``).

Imprime o **literal JS de uma entrada do objeto ``DADOS_ANO``** (a chave do ano
fica de fora — acrescente na mão ao colar, ex.: ``'2025': { ... }``).

Uso (a partir da raiz do projeto)::

    .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dados_consolidado_ano.py" --ano 2025 --mes-final 12 > ano_2025.js
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
        '  .venv\\Scripts\\python.exe "Dashboard financeiro/gerar_dados_consolidado_ano.py"'
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
DRE_CHAVES = _atualizar.DRE_CHAVES
BAL_CHAVES = _atualizar.BAL_CHAVES
EMPRESAS = _atualizar.EMPRESAS


def _num(v: float) -> str:
    return "0" if abs(v) < 0.005 else f"{v:.2f}"


def _lista(vals: list[float]) -> str:
    return "[" + ",".join(_num(v) for v in vals) + "]"


def _pivot_meses(df, chaves: dict[str, str], mes_final: int):
    """{empresa: {chaveJS: [mes_final valores]}}, descartando contas sem lançamento."""
    out: dict[str, dict[str, list[float]]] = {}
    faltando = set()
    for _, r in df.iterrows():
        emp = str(r["[@E]"]).strip()
        if emp not in EMPRESAS:
            continue
        conta = str(r["[@C]"]).strip()
        chave = chaves.get(conta)
        if chave is None:
            faltando.add(conta)
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= mes_final:
            continue
        arr = out.setdefault(emp, {}).setdefault(chave, [0.0] * mes_final)
        arr[mes - 1] += float(r["[@Valor]"] or 0)
    if faltando:
        print(f"// AVISO: contas sem chave, ignoradas: {sorted(faltando)}", file=sys.stderr)
    for emp in list(out):
        out[emp] = {k: v for k, v in out[emp].items() if any(abs(x) >= 0.005 for x in v)}
    return out


def _pivot_acumulado(df, chaves: dict[str, str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for _, r in df.iterrows():
        emp = str(r["[@E]"]).strip()
        if emp not in EMPRESAS:
            continue
        chave = chaves.get(str(r["[@C]"]).strip())
        if chave is None:
            continue
        d = out.setdefault(emp, {})
        d[chave] = d.get(chave, 0.0) + float(r["[@Valor]"] or 0)
    return out


def gerar(ano: int, mes_final: int) -> dict:
    cliente = PowerBIClient()
    ate_ano = ano * 100 + mes_final
    ate_ant = (ano - 1) * 100 + mes_final

    print(f"// Consultando DRE {ano} (Jan-{mes_final:02d}), todas as empresas…", file=sys.stderr)
    dre_det = _pivot_meses(cliente.execute_dax(_atualizar._q_por_mes("DRE", ano * 100 + 1, ate_ano)), DRE_CHAVES, mes_final)

    print(f"// Consultando DRE {ano-1} (mesmos meses, comparação)…", file=sys.stderr)
    dre_det_ant = _pivot_meses(cliente.execute_dax(_atualizar._q_por_mes("DRE", (ano - 1) * 100 + 1, ate_ant)), DRE_CHAVES, mes_final)

    print("// Consultando Balanço acumulado (dois períodos)…", file=sys.stderr)
    bal_cur = _pivot_acumulado(cliente.execute_dax(_atualizar._q_acumulado("Balanço", ate_ano)), BAL_CHAVES)
    bal_ant = _pivot_acumulado(cliente.execute_dax(_atualizar._q_acumulado("Balanço", ate_ant)), BAL_CHAVES)
    bal_det: dict[str, dict[str, list[float]]] = {}
    for emp in EMPRESAS:
        contas = set(bal_cur.get(emp, {})) | set(bal_ant.get(emp, {}))
        d = {}
        for chave in BAL_CHAVES.values():
            if chave not in contas:
                continue
            par = [bal_cur.get(emp, {}).get(chave, 0.0), bal_ant.get(emp, {}).get(chave, 0.0)]
            if any(abs(x) >= 0.005 for x in par):
                d[chave] = par
        bal_det[emp] = d

    print(f"// Consultando movimento mensal do Balanço {ano}…", file=sys.stderr)
    mov = _pivot_meses(cliente.execute_dax(_atualizar._q_por_mes("Balanço", ano * 100 + 1, ate_ano)), BAL_CHAVES, mes_final)

    print(f"// Consultando movimento mensal do Balanço {ano-1}…", file=sys.stderr)
    mov_ant = _pivot_meses(cliente.execute_dax(_atualizar._q_por_mes("Balanço", (ano - 1) * 100 + 1, ate_ant)), BAL_CHAVES, mes_final)

    print("// Consultando recortes por NATUREZA…", file=sys.stderr)
    dfn = cliente.execute_dax(_atualizar._q_natureza(ano * 100 + 1, ate_ano))
    nat: dict[str, dict[str, list[float]]] = {
        emp: {k: [0.0] * mes_final for k in ("depD", "imobC", "imobD", "acumD")} for emp in EMPRESAS
    }
    for _, r in dfn.iterrows():
        emp = str(r["[@E]"]).strip()
        if emp not in EMPRESAS:
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= mes_final:
            continue
        dre_c = str(r["[@D]"]).strip()
        bal_c = str(r["[@C]"]).strip()
        natu = str(r["[@N]"]).strip()
        valor = float(r["[@Valor]"] or 0)
        if dre_c in fin.DRE_G5_DEPRECIACAO and natu == "D":
            nat[emp]["depD"][mes - 1] += valor
        if bal_c in fin.FC_IMOBILIZADO:
            nat[emp]["imobC" if natu == "C" else "imobD"][mes - 1] += valor
        if bal_c in fin.FC_DEPRECIACAO_ACUM and natu == "D":
            nat[emp]["acumD"][mes - 1] += valor

    print("// Consultando resultado contábil (insumo do Fluxo de Caixa)…", file=sys.stderr)
    dfc = cliente.execute_dax(_atualizar._q_resultado_contabil(ano * 100 + 1, ate_ano))
    fc_cont: dict[str, dict[str, list[float]]] = {
        emp: {"lucro": [0.0] * mes_final, "depD": [0.0] * mes_final} for emp in EMPRESAS
    }
    for _, r in dfc.iterrows():
        emp = str(r["[@E]"]).strip()
        if emp not in EMPRESAS:
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= mes_final:
            continue
        conta = str(r["[@C]"]).strip()
        valor = float(r["[@Valor]"] or 0)
        if conta in DRE_CHAVES:
            fc_cont[emp]["lucro"][mes - 1] += valor
        if conta in fin.DRE_G5_DEPRECIACAO and str(r["[@N]"]).strip() == "D":
            fc_cont[emp]["depD"][mes - 1] += valor

    print("// Consultando saldo de caixa inicial (31/12 do ano anterior)…", file=sys.stderr)
    df_ini = cliente.execute_dax(_atualizar._q_acumulado("Balanço", (ano - 1) * 100 + 12))
    saldo_ini = {emp: 0.0 for emp in EMPRESAS}
    for _, r in df_ini.iterrows():
        emp = str(r["[@E]"]).strip()
        if emp in EMPRESAS and str(r["[@C]"]).strip() in fin.BAL_DISPONIBILIDADES:
            saldo_ini[emp] += float(r["[@Valor]"] or 0)

    print("// Consultando drill-down DESCRICAO_CONTA (todas as empresas)…", file=sys.stderr)
    dfd = cliente.execute_dax(
        f"EVALUATE\n"
        f"VAR _P = ADDCOLUMNS('lancamentos', \"@E\", TRIM('lancamentos'[EMPRESA]), "
        f"\"@C\", TRIM('lancamentos'[DRE]), \"@D\", TRIM('lancamentos'[DESCRICAO_CONTA]), "
        f"\"@K\", {fin._expr_chave()})\n"
        f"VAR _F = FILTER(_P, [@K] >= {ano*100+1} && [@K] <= {ate_ano} && [@C] <> \"\" && [@E] <> \"REVENDA\")\n"
        'RETURN GROUPBY(_F, [@E], [@C], [@D], [@K], "@Valor", '
        "SUMX(CURRENTGROUP(), 'lancamentos'[VALOR_AJUSTADO]))"
    )
    dre_desc: dict[str, dict[str, dict[str, list[float]]]] = {}
    for _, r in dfd.iterrows():
        emp = str(r["[@E]"]).strip()
        if emp not in EMPRESAS:
            continue
        conta = str(r["[@C]"]).strip()
        chave = DRE_CHAVES.get(conta)
        if chave is None:
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= mes_final:
            continue
        desc = str(r["[@D]"]).strip()
        arr = dre_desc.setdefault(emp, {}).setdefault(chave, {}).setdefault(desc, [0.0] * mes_final)
        arr[mes - 1] += float(r["[@Valor]"] or 0)

    return {
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


def _emit_por_empresa_flat(nome: str, dados: dict[str, dict[str, list[float]]], ind: str) -> None:
    print(f"{ind}{nome}: {{")
    linhas = []
    for emp in EMPRESAS:
        contas = dados.get(emp, {})
        itens = ", ".join(f"{k}:{_lista(v)}" for k, v in contas.items())
        linhas.append(f"{ind}  '{emp}': {{{itens}}}")
    print(",\n".join(linhas))
    print(f"{ind}}},")


def emitir(dados: dict) -> None:
    ind = "    "
    _emit_por_empresa_flat("dreDet", dados["dreDet"], ind)
    _emit_por_empresa_flat("dreDetAnt", dados["dreDetAnt"], ind)
    _emit_por_empresa_flat("balDet", dados["balDet"], ind)
    _emit_por_empresa_flat("mov", dados["mov"], ind)
    _emit_por_empresa_flat("movAnt", dados["movAnt"], ind)
    _emit_por_empresa_flat("nat", dados["nat"], ind)
    _emit_por_empresa_flat("fcCont", dados["fcCont"], ind)

    itens_ini = ", ".join(f"'{e}':{_num(dados['saldoIni'][e])}" for e in EMPRESAS)
    print(f"{ind}saldoIni: {{ {itens_ini} }},")

    print(f"{ind}dreDesc: {{")
    linhas_emp = []
    for emp in EMPRESAS:
        contas = dados["dreDesc"].get(emp, {})
        if not contas:
            linhas_emp.append(f"{ind}  '{emp}': {{}}")
            continue
        chaves_ordenadas = sorted(contas)
        blocos_conta = []
        for chave in chaves_ordenadas:
            descs = sorted(contas[chave])
            itens_desc = ", ".join(f"'{d}':{_lista(contas[chave][d])}" for d in descs)
            blocos_conta.append(f"{ind}    {chave}: {{{itens_desc}}}")
        corpo = ",\n".join(blocos_conta)
        linhas_emp.append(f"{ind}  '{emp}': {{\n{corpo}\n{ind}  }}")
    print(",\n".join(linhas_emp))
    print(f"{ind}}}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", type=int, required=True)
    ap.add_argument("--mes-final", type=int, default=12)
    args = ap.parse_args()

    dados = gerar(args.ano, args.mes_final)
    print(f"// ===== Ano {args.ano} (todas as empresas) — mes_final={args.mes_final} =====", file=sys.stderr)
    emitir(dados)


if __name__ == "__main__":
    main()
