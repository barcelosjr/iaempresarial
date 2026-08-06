"""Regenera o snapshot de dados embutido em ``build/painel_financeiro.html``.

O painel é um arquivo estático: os números vêm de blocos JS literais no topo do
``<script>``. Este script consulta o Power BI (somente leitura, via
``PowerBIClient``) e reescreve **apenas** esses blocos, preservando todo o
restante do HTML — layout, funções de render e textos.

Blocos regerados
----------------
``SNAPSHOT``        data de hoje (dd/mm/aaaa)
``DRE_EMP_2025``    DRE acumulada Jan–Jul do ano anterior, por empresa (8 componentes)
``DRE_DET``         DRE por empresa × conta × mês (Jan–Jul do ano corrente)
``DRE_DET_ANT``     idem, do ano anterior — base das comparações período a período
``BAL_DET``         Balanço acumulado, pares ``[jul/ano, jul/ano-1]``, por empresa × conta
``MOV``             movimento mensal das contas do Balanço (insumo do Fluxo de Caixa)
``MOV_ANT``         movimento mensal do Balanço no ano anterior, para reconstruir a
                    posição em fim de trimestre de 2025 e comparar com a de 2026
``NAT``             recortes por NATUREZA (depreciação, imobilizado, depreciação acumulada)
``FC_CONT``         Lucro Líquido e depreciação **só contábeis**, por empresa × mês
``SALDO_INI``       saldo de caixa em 31/12 do ano anterior, por empresa
``eficienciaCur``   indicadores de Eficiência do mês de referência (e do mesmo mês do ano anterior)

Convenções mantidas iguais às do painel original:

* Todos os valores são a **soma bruta de VALOR_AJUSTADO** — o sinal econômico já
  vem da coluna, e a inversão de exibição é feita no JS.
* **Visão gerencial**: nenhum filtro de ``TIPO_LANÇAMENTO``, isto é, contábeis +
  extras. É o que o rodapé do painel declara ("Lançamentos Contábeis e
  Gerenciais"). Para a visão contábil seria preciso filtrar
  ``TIPO_LANÇAMENTO = "CONTÁBIL"``, o que mudaria os números.
* Chaves de conta (``vendaVN``, ``caixaBancos``, …) seguem ``CAMPOS_DRE`` e
  ``CAMPOS_BAL`` do próprio HTML.

Uso (a partir da raiz do projeto)::

    .venv\\Scripts\\python.exe "Dashboard financeiro/atualizar_dados.py"

Precisa ser o Python do venv — o ``python`` do PATH costuma ser o stub da
Microsoft Store, sem ``yaml``/``msal``/``pandas`` instalados.
"""

from __future__ import annotations

import datetime as _dt
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:
    from powerbi import dax_financeiro as fin  # noqa: E402
    from powerbi import dax_kpis  # noqa: E402
    from powerbi.client import PowerBIClient  # noqa: E402
except ModuleNotFoundError as _exc:  # pragma: no cover - erro de ambiente
    raise SystemExit(
        f"Dependência ausente ({_exc.name}). Rode com o Python do venv:\n"
        '  .venv\\Scripts\\python.exe "Dashboard financeiro/atualizar_dados.py"'
    ) from _exc

HTML = Path(__file__).resolve().parent / "build" / "painel_financeiro.html"

#: Último mês fechado/parcial exibido no painel (o painel mostra Jan..este mês).
MES_FINAL = 6
ANO = 2026

MESES_ROTULO = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul"]

#: Ordem das empresas nos blocos (a mesma do seletor do painel).
EMPRESAS = [
    "KOBE",
    "MIT",
    "ROYAL",
    "RENAULT",
    "MEGA STORE",
    "MULT BOATS",
    "OMODA",
    "CORRETORA",
    "MULT SOLUÇÕES",
]

# --------------------------------------------------------------------------- #
# Mapa conta (Power BI) -> chave JS
# --------------------------------------------------------------------------- #
DRE_CHAVES = {
    "Venda de Veículos Novos": "vendaVN",
    "Venda de Veículos Usados": "vendaVU",
    "Peças e Acessórios": "pecas",
    "Serviços Oficina": "oficina",
    "Comissões Diversas": "comissoes",
    "Comissão sobre Seguros": "comSeguros",
    "Comissão sobre Consórcios": "comConsorcios",
    "Comissão sobre Intermediação": "comIntermediacao",
    "(-) Devoluções": "devolucoes",
    "(-) Impostos sobre a Venda": "impostosVenda",
    "Custo de Veículos Novos": "custoVN",
    "Custo de Veículos Usados": "custoVU",
    "Custo de Peças e Acessórios": "custoPecas",
    "Custo de Serviços Oficina": "custoOficina",
    "Custo de Serviço de Terceiros": "custoTerceiros",
    "Folha de Pagamento": "folha",
    "Despesas Comerciais": "despComercial",
    "Despesas Gerais": "despGerais",
    "Manutenção de Bens": "manutencao",
    "Serviços Profissionais": "servProf",
    "Taxas e Impostos Diversos": "taxasImpostos",
    "Despesas de Funcionamento": "despFuncionamento",
    "Alugueis e Condomínios": "alugueis",
    "Despesas Gerais de Funcionamento": "despGeraisFunc",
    "Outras Despesas Operacionais": "outrasDesp",
    "Gastos Diversos com Funcionários": "gastosFunc",
    "Rateio do Grupo": "rateioGrupo",
    "(+) Receitas Diversas": "receitasDiversas",
    "(+) Receitas Não Operacionais": "receitasNaoOper",
    "(-) Despesas Não Dedutíveis": "despNaoDedutiveis",
    "(-) Despesas Não Operacionais": "despNaoOper",
    "Depreciação e Amortização de Ativos": "da",
    "(+) Receitas Financeiras": "recFin",
    "(-) Despesas Financeiras": "despFin",
    "(-) IR e CSLL": "irCsll",
}

BAL_CHAVES = {
    "Caixa e Bancos": "caixaBancos",
    "Aplicações Financeiras": "aplicacoesFinanceiras",
    "Contas a Receber": "contasReceber",
    "Cartões de Crédito a Receber": "cartoesReceber",
    "Financiamentos a Receber": "financiamentosReceber",
    "Adiantamentos a Fornecedores": "adiantForn",
    "Outros Adiantamentos": "outrosAdiant",
    "Outros Créditos a Receber": "outrosCreditos",
    "Impostos a Recuperar": "impostosRecuperar",
    "Estoque de Veículos Novos": "estVN",
    "Estoque de Veículos Usados": "estVU",
    "Estoque de Peças": "estPecas",
    "Investimentos a Longo Prazo - FVN": "realizavelLP",
    "Investimentos a Longo Prazo": "invLP",
    "Investimentos Permanentes": "invPermanentes",
    "Terrenos": "terrenos",
    "Edifícios": "edificios",
    "Instalações": "instalacoes",
    "Veículos": "veiculos",
    "Máquinas e Equipamentos": "maquinas",
    "Computadores e Periféricos": "computadores",
    "Móveis e Utensílios": "moveis",
    "Construções em Andamento": "construcoes",
    "Benfeitorias em Bens de Terceiros": "benfeitorias",
    "Consórcios": "consorcios",
    "Aeronaves": "aeronaves",
    "(-) Depreciação Acumulada": "deprecAcum",
    "Direitos de Concessão": "direitosConcessao",
    "(-) Amortização Acumulada": "amortAcum",
    "Floor Plan Veículos Novos": "floorVN",
    "Floor Plan Veículos Usados": "floorVU",
    "Floor Plan Peças e Acessórios": "floorPecas",
    "Fornecedores Diversos": "fornecDiv",
    "Empréstimos Bancários": "emprestBancarios",
    "Empréstimos de Terceiros": "emprestTerceiros",
    "Conta Garantida": "contaGarantida",
    "Financiamentos": "financiamentos",
    "Notas Comerciais": "notasComerciais",
    "Obrigações Sociais e Trabalhistas": "obrigSociais",
    "Obrigações Tributárias e Diversas": "obrigTrib",
    "Adiantamento de Clientes": "adiantCliente",
    "Provisões": "provisoes",
    "Outras Contas a Pagar": "outrasContas",
    "Lucros a Pagar": "lucrosPagar",
    "Empréstimos e Financiamentos LP": "emprestFinancLP",
    "Outros Credores": "outrosCredores",
    "Parcelamentos LP": "parcelamentosLP",
    "Adiantamento Futura Integralização": "adiantFuturaIntegr",
    "Capital Social Integralizado": "capitalSocial",
    "Reservas de Capital": "reservasCapital",
    "Reservas de Lucros": "reservasLucros",
    "Reservas de Incentivos Fiscais": "reservasIncentivos",
    "Prejuízos Acumulados": "prejuizosAcum",
    "Ajustes de Exercícios Anteriores": "ajustesExercAnt",
}

#: Componentes de ``DRE_EMP_2025``, na ordem em que o painel os lê.
COMPONENTES_2025 = [
    fin.DRE_G1_RECEITA,
    fin.DRE_G2_CUSTOS,
    fin.DRE_G3_DESPESAS,
    fin.DRE_G4_OUTRAS,
    fin.DRE_G5_DEPRECIACAO,
    ["(+) Receitas Financeiras"],
    ["(-) Despesas Financeiras"],
    fin.DRE_G7_IMPOSTOS,
]

INDICADORES_EFIC = {
    "Giro de Estoque VN": "giroVN",
    "Giro de Estoque VU": "giroVU",
    "Giro de Estoque de Peças": "giroPecas",
    "PMR — Prazo Médio de Recebimento": "pmr",
    "PMP — Prazo Médio de Pagamento": "pmp",
    "Ciclo Financeiro": "cicloFinanceiro",
    "Custo de Pessoal / Receita Líquida": "custoPessoalRL",
    "Total Despesas Operac. / Receita Líquida": "despOperRL",
}


# --------------------------------------------------------------------------- #
# Consultas
# --------------------------------------------------------------------------- #
def _chave() -> str:
    return fin._expr_chave()


def _q_por_mes(coluna: str, de: int, ate: int) -> str:
    """Agrupa VALOR_AJUSTADO por empresa × conta × mês no intervalo."""
    k = _chave()
    return (
        "EVALUATE\n"
        f"VAR _B = FILTER('lancamentos', {k} >= {de} && {k} <= {ate})\n"
        f"VAR _P = ADDCOLUMNS(_B, \"@E\", TRIM('lancamentos'[EMPRESA]), "
        f"\"@C\", TRIM('lancamentos'[{coluna}]), \"@K\", {k}, "
        "\"@V\", 'lancamentos'[VALOR_AJUSTADO])\n"
        'RETURN GROUPBY(_P, [@E], [@C], [@K], "@Valor", SUMX(CURRENTGROUP(), [@V]))'
    )


def _q_acumulado(coluna: str, ate: int) -> str:
    """Agrupa VALOR_AJUSTADO por empresa × conta, acumulado até a chave."""
    k = _chave()
    return (
        "EVALUATE\n"
        f"VAR _B = FILTER('lancamentos', {k} <= {ate})\n"
        f"VAR _P = ADDCOLUMNS(_B, \"@E\", TRIM('lancamentos'[EMPRESA]), "
        f"\"@C\", TRIM('lancamentos'[{coluna}]), "
        "\"@V\", 'lancamentos'[VALOR_AJUSTADO])\n"
        'RETURN GROUPBY(_P, [@E], [@C], "@Valor", SUMX(CURRENTGROUP(), [@V]))'
    )


def _q_resultado_contabil(de: int, ate: int) -> str:
    """DRE × natureza por empresa e mês, **só lançamentos contábeis**.

    Insumo exclusivo do Fluxo de Caixa: de lá saem o Lucro Líquido e o add-back
    de depreciação, que precisam bater com as variações do Balanço. Ver a nota
    em :func:`powerbi.dax_financeiro.fluxo_caixa`.
    """
    k = _chave()
    cont = fin._filtro_visao("contabil")
    return (
        "EVALUATE\n"
        f"VAR _B = FILTER('lancamentos', {k} >= {de} && {k} <= {ate}{cont})\n"
        f"VAR _P = ADDCOLUMNS(_B, \"@E\", TRIM('lancamentos'[EMPRESA]), "
        f"\"@C\", TRIM('lancamentos'[DRE]), \"@N\", 'lancamentos'[NATUREZA], "
        f"\"@K\", {k}, \"@V\", 'lancamentos'[VALOR_AJUSTADO])\n"
        'RETURN GROUPBY(_P, [@E], [@C], [@N], [@K], "@Valor", '
        "SUMX(CURRENTGROUP(), [@V]))"
    )


def _q_natureza(de: int, ate: int) -> str:
    """Agrupa por empresa × conta(DRE e Balanço) × natureza × mês."""
    k = _chave()
    return (
        "EVALUATE\n"
        f"VAR _B = FILTER('lancamentos', {k} >= {de} && {k} <= {ate})\n"
        f"VAR _P = ADDCOLUMNS(_B, \"@E\", TRIM('lancamentos'[EMPRESA]), "
        f"\"@D\", TRIM('lancamentos'[DRE]), \"@C\", TRIM('lancamentos'[Balanço]), "
        f"\"@N\", 'lancamentos'[NATUREZA], \"@K\", {k}, "
        "\"@V\", 'lancamentos'[VALOR_AJUSTADO])\n"
        "RETURN GROUPBY(_P, [@E], [@D], [@C], [@N], [@K], \"@Valor\", "
        "SUMX(CURRENTGROUP(), [@V]))"
    )


# --------------------------------------------------------------------------- #
# Formatação JS
# --------------------------------------------------------------------------- #
def _num(v: float) -> str:
    return "0" if abs(v) < 0.005 else f"{v:.2f}"


def _lista(vals: list[float]) -> str:
    return "[" + ",".join(_num(v) for v in vals) + "]"


def _bloco_por_empresa(
    nome: str, dados: dict[str, dict[str, list[float]]], por_linha: int
) -> str:
    """Monta ``var NOME = { 'EMPRESA': { chave:[...], ... }, ... };``."""
    linhas = [f"  var {nome} = {{"]
    for i, emp in enumerate(EMPRESAS):
        contas = dados.get(emp, {})
        virgula = "," if i < len(EMPRESAS) - 1 else ""
        if not contas:
            linhas.append(f"    '{emp}': {{}}{virgula}")
            continue
        itens = [f"{k}:{_lista(v)}" for k, v in contas.items()]
        corpo: list[str] = []
        for j in range(0, len(itens), por_linha):
            corpo.append("      " + ", ".join(itens[j : j + por_linha]) + ",")
        corpo[-1] = corpo[-1].rstrip(",")
        linhas.append(f"    '{emp}': {{")
        linhas.extend(corpo)
        linhas.append(f"    }}{virgula}")
    linhas.append("  };")
    return "\n".join(linhas)


def _trocar_bloco(html: str, nome: str, novo: str) -> str:
    """Troca ``var NOME = { … };`` inteiro pelo bloco novo.

    Localiza o início pela declaração e o fim pelo primeiro ``\\n  };`` — o
    fechamento no mesmo nível de indentação. Se logo depois vier a linha de
    apelido ASCII que o painel original usava
    (``NOME['MULT SOLU\\u00c7\\u00d5ES'] = NOME['MULT SOLUCOES'];``), ela também
    é consumida: os blocos gerados aqui já usam a chave acentuada direto.

    Ser idempotente importa — este script roda de novo a cada atualização, sobre
    um arquivo que ele mesmo gerou.
    """
    inicio = f"  var {nome} = {{"
    i = html.index(inicio)
    j = html.index("\n  };", i) + len("\n  };")
    resto = html[j:]
    apelido = re.match(
        r"\n  " + re.escape(nome) + r"\['MULT SOLU\\u00c7\\u00d5ES'\] = "
        + re.escape(nome) + r"\['MULT SOLUCOES'\];",
        resto,
    )
    if apelido:
        j += apelido.end()
    return html[:i] + novo + html[j:]


# --------------------------------------------------------------------------- #
# Extração
# --------------------------------------------------------------------------- #
def _conferir_cobertura(df, chaves: dict[str, str], rotulo: str) -> None:
    """Aborta se o modelo tiver conta que o mapa de chaves não conhece.

    Sem isso, uma conta nova (ou renomeada) no Power BI simplesmente **some** do
    painel: ``chaves.get(...)`` devolve ``None`` e a linha é ignorada em
    silêncio, subestimando despesas e inflando o EBITDA. Já aconteceu quando
    "Despesas Gerais e Rateio do Grupo" foi dividida em "Rateio do Grupo" e
    "Despesas Gerais de Funcionamento" — melhor quebrar do que publicar errado.
    """
    vistas = {str(c).strip() for c in df["[@C]"].unique() if str(c).strip()}
    faltando = sorted(vistas - set(chaves))
    if faltando:
        raise SystemExit(
            f"Contas de {rotulo} presentes no modelo mas sem chave no painel:\n  "
            + "\n  ".join(faltando)
            + "\n\nAdicione-as ao mapa em atualizar_dados.py (e à estrutura em "
            "powerbi/dax_financeiro.py) antes de regerar."
        )


def _pivot_meses(df, chaves: dict[str, str], col_cat: str = "[@C]") -> dict:
    """Organiza o resultado em ``{empresa: {chaveJS: [7 meses]}}``."""
    out: dict[str, dict[str, list[float]]] = {}
    for _, r in df.iterrows():
        emp = str(r["[@E]"]).strip()
        chave = chaves.get(str(r[col_cat]).strip())
        if chave is None or emp not in EMPRESAS:
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= MES_FINAL:
            continue
        alvo = out.setdefault(emp, {}).setdefault(chave, [0.0] * MES_FINAL)
        alvo[mes - 1] += float(r["[@Valor]"] or 0)
    # Descarta contas sem nenhum lançamento (o painel omite essas linhas).
    for emp in list(out):
        out[emp] = {
            k: v for k, v in out[emp].items() if any(abs(x) >= 0.005 for x in v)
        }
    return out


def _pivot_acumulado(df, chaves: dict[str, str]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for _, r in df.iterrows():
        emp = str(r["[@E]"]).strip()
        chave = chaves.get(str(r["[@C]"]).strip())
        if chave is None or emp not in EMPRESAS:
            continue
        d = out.setdefault(emp, {})
        d[chave] = d.get(chave, 0.0) + float(r["[@Valor]"] or 0)
    return out


def main() -> None:
    cliente = PowerBIClient()
    ate_ano = ANO * 100 + MES_FINAL
    ate_ant = (ANO - 1) * 100 + MES_FINAL

    print("Consultando DRE detalhada do ano corrente…")
    df_dre = cliente.execute_dax(_q_por_mes("DRE", ANO * 100 + 1, ate_ano))
    _conferir_cobertura(df_dre, DRE_CHAVES, "DRE")
    dre_det = _pivot_meses(df_dre, DRE_CHAVES)

    print("Consultando DRE do ano anterior (acumulado Jan–Jul)…")
    # Intervalo fechado (não acumulado desde 2024): o painel compara Jan–Jul
    # de um ano com Jan–Jul do outro.
    df25 = cliente.execute_dax(_q_por_mes("DRE", (ANO - 1) * 100 + 1, ate_ant))
    bruto25: dict[str, dict[str, float]] = {}
    for _, r in df25.iterrows():
        emp = str(r["[@E]"]).strip()
        if emp not in EMPRESAS:
            continue
        bruto25.setdefault(emp, {})
        conta = str(r["[@C]"]).strip()
        bruto25[emp][conta] = bruto25[emp].get(conta, 0.0) + float(r["[@Valor]"] or 0)
    dre_2025 = {
        emp: [
            sum(bruto25.get(emp, {}).get(c, 0.0) for c in grupo)
            for grupo in COMPONENTES_2025
        ]
        for emp in EMPRESAS
    }

    print("Consultando Balanço acumulado (dois períodos)…")
    bal_cur = _pivot_acumulado(
        cliente.execute_dax(_q_acumulado("Balanço", ate_ano)), BAL_CHAVES
    )
    bal_ant = _pivot_acumulado(
        cliente.execute_dax(_q_acumulado("Balanço", ate_ant)), BAL_CHAVES
    )
    bal_det: dict[str, dict[str, list[float]]] = {}
    for emp in EMPRESAS:
        contas = set(bal_cur.get(emp, {})) | set(bal_ant.get(emp, {}))
        d = {}
        for chave in BAL_CHAVES.values():
            if chave not in contas:
                continue
            par = [
                bal_cur.get(emp, {}).get(chave, 0.0),
                bal_ant.get(emp, {}).get(chave, 0.0),
            ]
            if any(abs(x) >= 0.005 for x in par):
                d[chave] = par
        bal_det[emp] = d

    print("Consultando DRE detalhada do ano anterior (por conta × mês)…")
    # Base das comparações período a período: sem isso só daria para comparar o
    # acumulado Jan–Jul, e o painel precisa de T1 vs T1, T2 vs T2 etc.
    df_dre_ant = cliente.execute_dax(
        _q_por_mes("DRE", (ANO - 1) * 100 + 1, ate_ant)
    )
    _conferir_cobertura(df_dre_ant, DRE_CHAVES, "DRE (ano anterior)")
    dre_det_ant = _pivot_meses(df_dre_ant, DRE_CHAVES)

    print("Consultando movimento mensal do Balanço…")
    df_mov = cliente.execute_dax(_q_por_mes("Balanço", ANO * 100 + 1, ate_ano))
    _conferir_cobertura(df_mov, BAL_CHAVES, "Balanço")
    mov = _pivot_meses(df_mov, BAL_CHAVES)

    print("Consultando movimento mensal do Balanço no ano anterior…")
    df_mov_ant = cliente.execute_dax(
        _q_por_mes("Balanço", (ANO - 1) * 100 + 1, ate_ant)
    )
    _conferir_cobertura(df_mov_ant, BAL_CHAVES, "Balanço (ano anterior)")
    mov_ant = _pivot_meses(df_mov_ant, BAL_CHAVES)

    print("Consultando recortes por NATUREZA…")
    dfn = cliente.execute_dax(_q_natureza(ANO * 100 + 1, ate_ano))
    nat: dict[str, dict[str, list[float]]] = {
        emp: {k: [0.0] * MES_FINAL for k in ("depD", "imobC", "imobD", "acumD")}
        for emp in EMPRESAS
    }
    for _, r in dfn.iterrows():
        emp = str(r["[@E]"]).strip()
        if emp not in EMPRESAS:
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= MES_FINAL:
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

    print("Consultando resultado contábil (insumo do Fluxo de Caixa)…")
    dfc = cliente.execute_dax(_q_resultado_contabil(ANO * 100 + 1, ate_ano))
    _conferir_cobertura(dfc, DRE_CHAVES, "DRE (base contábil)")
    fc_cont: dict[str, dict[str, list[float]]] = {
        emp: {"lucro": [0.0] * MES_FINAL, "depD": [0.0] * MES_FINAL}
        for emp in EMPRESAS
    }
    for _, r in dfc.iterrows():
        emp = str(r["[@E]"]).strip()
        if emp not in EMPRESAS:
            continue
        mes = int(r["[@K]"]) % 100
        if not 1 <= mes <= MES_FINAL:
            continue
        conta = str(r["[@C]"]).strip()
        valor = float(r["[@Valor]"] or 0)
        # Lucro Líquido = soma de todas as contas da DRE (o sinal já vem certo).
        if conta in DRE_CHAVES:
            fc_cont[emp]["lucro"][mes - 1] += valor
        if conta in fin.DRE_G5_DEPRECIACAO and str(r["[@N]"]).strip() == "D":
            fc_cont[emp]["depD"][mes - 1] += valor

    print("Consultando saldo de caixa inicial (31/12 do ano anterior)…")
    df_ini = cliente.execute_dax(_q_acumulado("Balanço", (ANO - 1) * 100 + 12))
    saldo_ini = {emp: 0.0 for emp in EMPRESAS}
    for _, r in df_ini.iterrows():
        emp = str(r["[@E]"]).strip()
        if emp in EMPRESAS and str(r["[@C]"]).strip() in fin.BAL_DISPONIBILIDADES:
            saldo_ini[emp] += float(r["[@Valor]"] or 0)

    print("Consultando indicadores de Eficiência…")
    ref = f"{MES_FINAL:02d}/{ANO}"
    ref_ant = f"{MES_FINAL:02d}/{ANO - 1}"

    def _efic(periodo: str) -> dict[str, float]:
        df = cliente.execute_dax(dax_kpis.indicadores(periodo))
        out: dict[str, float] = {}
        for _, r in df.iterrows():
            chave = INDICADORES_EFIC.get(str(r["[Indicador]"]).strip())
            if chave:
                valor = float(r["[Valor]"] or 0)
                out[chave] = (
                    round(valor) if str(r["[Unidade]"]).strip() == "dias"
                    else round(valor, 4)
                )
        return out

    efic_cur, efic_ant = _efic(ref), _efic(ref_ant)

    # ----------------------------------------------------------------------- #
    # Reescrita do HTML
    # ----------------------------------------------------------------------- #
    html = HTML.read_text(encoding="utf-8")
    hoje = _dt.date.today().strftime("%d/%m/%Y")

    html = re.sub(
        r"var SNAPSHOT = '\d{2}/\d{2}/\d{4}';", f"var SNAPSHOT = '{hoje}';", html
    )

    bloco_2025 = ["  var DRE_EMP_2025 = {"]
    for i, emp in enumerate(EMPRESAS):
        virgula = "," if i < len(EMPRESAS) - 1 else ""
        bloco_2025.append(f"    '{emp}': {_lista(dre_2025[emp])}{virgula}")
    bloco_2025.append("  };")
    html = _trocar_bloco(html, "DRE_EMP_2025", "\n".join(bloco_2025))

    html = _trocar_bloco(html, "DRE_DET", _bloco_por_empresa("DRE_DET", dre_det, 1))
    html = _trocar_bloco(
        html, "DRE_DET_ANT", _bloco_por_empresa("DRE_DET_ANT", dre_det_ant, 1)
    )
    html = _trocar_bloco(html, "BAL_DET", _bloco_por_empresa("BAL_DET", bal_det, 2))
    html = _trocar_bloco(html, "MOV", _bloco_por_empresa("MOV", mov, 1))
    html = _trocar_bloco(html, "MOV_ANT", _bloco_por_empresa("MOV_ANT", mov_ant, 1))
    html = _trocar_bloco(html, "NAT", _bloco_por_empresa("NAT", nat, 1))
    html = _trocar_bloco(html, "FC_CONT", _bloco_por_empresa("FC_CONT", fc_cont, 1))

    itens_ini = ", ".join(f"'{e}':{_num(saldo_ini[e])}" for e in EMPRESAS)
    html = re.sub(
        r"  var SALDO_INI = \{.*?\};",
        f"  var SALDO_INI = {{ {itens_ini} }};",
        html,
        flags=re.S,
    )

    def _js_efic(nome: str, d: dict[str, float]) -> str:
        campos = ", ".join(
            f"{k}:{d.get(k, 0)}" for k in
            ("giroVN", "giroVU", "giroPecas", "pmr", "pmp", "cicloFinanceiro",
             "custoPessoalRL", "despOperRL")
        )
        return f"  var {nome} = {{ {campos} }};"

    html = re.sub(
        r"  var eficienciaCur = \{[^}]*\};", _js_efic("eficienciaCur", efic_cur), html
    )
    html = re.sub(
        r"  var eficienciaPrior = \{[^}]*\};",
        _js_efic("eficienciaPrior", efic_ant),
        html,
    )

    HTML.write_text(html, encoding="utf-8")
    print(f"\n✅ {HTML.name} atualizado — SNAPSHOT = {hoje}")

    # Conferência rápida: totais do consolidado.
    rl = sum(
        sum(dre_det.get(e, {}).get(k, [0] * MES_FINAL))
        for e in EMPRESAS
        for k in ("vendaVN", "vendaVU", "pecas", "oficina", "comissoes",
                  "comSeguros", "comConsorcios", "comIntermediacao",
                  "devolucoes", "impostosVenda")
    )
    print(f"   Receita Líquida acumulada Jan–{MESES_ROTULO[MES_FINAL - 1]}/{ANO}: "
          f"{rl:,.2f}")


if __name__ == "__main__":
    main()
