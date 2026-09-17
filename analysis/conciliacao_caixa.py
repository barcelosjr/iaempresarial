"""Conciliação de caixa: livro-caixa financeiro x saldo contábil, por empresa.

Responde a uma pergunta só: **o saldo de caixa do financeiro bate com o da
contabilidade?** Compara, mês a mês e por empresa, o acumulado de
``CAIXAS[VALOR]`` (dataset ``controlador``) com o acumulado de
``lancamentos[VALOR_AJUSTADO]`` nas contas de CAIXA GERAL (dataset padrão).

Regras de desenho — o porquê de cada uma está em ``powerbi/dax_conciliacao.py``
e em ``dictionary/regras_negocio.md``:

* **Por empresa, nunca por revenda.** Transferência de saldo entre caixas de
  revendas diferentes não gera lançamento contábil; por revenda os dois lados
  nunca fecham, por empresa elas se anulam.
* **Granularidade mensal.** A tabela contábil não tem coluna de data — só
  ``PERIODO`` (``MM/AAAA``). Não existe saldo contábil diário para comparar; o
  corte do lado financeiro é sempre no último dia do mês.
* **Nada é excluído do financeiro.** Caixas 9/99/4, 8/14 da Multicar Mits e as
  28 linhas de abertura entram todos — ao contrário da auditoria e dos painéis.

A diferença é decomposta em duas parcelas, que exigem providências diferentes:

``diferenca_abertura``
    Constante, nasce em 01/01/2025 e se arrasta por todos os meses: o
    ``"SALDO INICIAL DA PLANILHA"`` que a planilha trouxe é menor (ou maior) do
    que o saldo contábil fechado em 12/2024. Não é erro de lançamento do
    período — é ajuste de saldo inicial.

``diferenca_do_mes``
    A variação da diferença acumulada de um mês para o outro. É o número que
    interessa: se for zero, os dois livros registraram exatamente o mesmo
    movimento naquele mês, por maior que seja o resíduo de abertura arrastado.

Uso:
    python analysis/conciliacao_caixa.py [MM/AAAA] [--empresa NOME]
"""

from __future__ import annotations

import argparse
import calendar
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import RAIZ_PROJETO, ErroConfiguracao, carregar_configuracao  # noqa: E402
from powerbi import dax_conciliacao as dxc  # noqa: E402
from powerbi.client import ErroPowerBI, PowerBIClient  # noqa: E402

PASTA_REPORTS = RAIZ_PROJETO / "reports"
CONFIG_CONCILIACAO = RAIZ_PROJETO / "config" / "conciliacao_caixa.yaml"

#: Apelido do dataset financeiro. O contábil é o dataset padrão do ``.env``.
DATASET_FINANCEIRO = dxc.DATASET_FINANCEIRO


# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #
def carregar_config(caminho: Path | None = None) -> dict[str, Any]:
    """Lê ``config/conciliacao_caixa.yaml``.

    Args:
        caminho: Caminho alternativo do YAML. ``None`` usa o padrão.

    Returns:
        Dicionário com contas, mapa de empresas, primeiro mês e tolerância.

    Raises:
        ErroConfiguracao: Se o arquivo não existir ou vier sem contas/empresas.
    """
    caminho = caminho or CONFIG_CONCILIACAO
    if not caminho.exists():
        raise ErroConfiguracao(
            f"Arquivo de configuração da conciliação não encontrado: {caminho}"
        )
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    dados.setdefault("primeiro_mes", 202501)
    dados.setdefault("mes_abertura", 202412)
    dados.setdefault("tolerancia_reais", 0.01)
    dados.setdefault(
        "origens_transferencia_interna", list(dxc.PADROES_TRANSFERENCIA_INTERNA)
    )

    contas = [str(c).strip() for c in dados.get("contas_caixa") or []]
    if not contas:
        raise ErroConfiguracao(
            f"{caminho.name}: 'contas_caixa' está vazio — sem conta contábil de "
            "caixa não há o que conciliar."
        )
    dados["contas_caixa"] = contas

    empresas = dados.get("empresas") or {}
    if not empresas:
        raise ErroConfiguracao(
            f"{caminho.name}: 'empresas' está vazio — é o mapa que liga o nome "
            "da empresa no financeiro ao nome no contábil."
        )
    dados["empresas"] = {str(k).strip(): str(v).strip() for k, v in empresas.items()}
    return dados


# --------------------------------------------------------------------------- #
# Datas e chaves AAAAMM
# --------------------------------------------------------------------------- #
def periodo_para_chave(periodo: str) -> int:
    """Converte ``"MM/AAAA"`` na chave inteira ``AAAAMM``.

    Raises:
        ValueError: Se o texto não estiver no formato ``MM/AAAA``.
    """
    texto = str(periodo).strip()
    partes = texto.split("/")
    if len(partes) != 2 or not partes[0].isdigit() or not partes[1].isdigit():
        raise ValueError(f"Período inválido: {periodo!r}. Use o formato MM/AAAA.")
    mes, ano = int(partes[0]), int(partes[1])
    if not 1 <= mes <= 12:
        raise ValueError(f"Mês inválido em {periodo!r}.")
    return ano * 100 + mes


def chave_para_periodo(chave: int) -> str:
    """Converte a chave ``AAAAMM`` em ``"MM/AAAA"``."""
    chave = int(chave)
    return f"{chave % 100:02d}/{chave // 100:04d}"


def ultimo_dia(chave: int) -> date:
    """Último dia do mês da chave ``AAAAMM`` — o corte do lado financeiro."""
    chave = int(chave)
    ano, mes = chave // 100, chave % 100
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def primeiro_dia(chave: int) -> date:
    """Primeiro dia do mês da chave ``AAAAMM``."""
    chave = int(chave)
    return date(chave // 100, chave % 100, 1)


def _meses(desde: int, ate: int) -> list[int]:
    """Sequência contínua de chaves ``AAAAMM`` de ``desde`` a ``ate``."""
    chaves: list[int] = []
    ano, mes = desde // 100, desde % 100
    while ano * 100 + mes <= ate:
        chaves.append(ano * 100 + mes)
        mes += 1
        if mes > 12:
            ano, mes = ano + 1, 1
    return chaves


# --------------------------------------------------------------------------- #
# Preparação dos dois lados
# --------------------------------------------------------------------------- #
def _coluna(df: pd.DataFrame, sufixo: str) -> str:
    """Localiza a coluna cujo nome DAX termina em ``[sufixo]``.

    A API devolve nomes qualificados (``lancamentos[EMPRESA]``) ou aliases
    (``[SALDO]``) conforme a consulta. Este projeto já tropeçou nisso em
    ``mcp_server.server._normalizar_coluna``; aqui a busca é por sufixo para
    funcionar nos dois formatos sem depender de qual consulta gerou o
    ``DataFrame``.

    Raises:
        KeyError: Se nenhuma coluna casar.
    """
    alvo = f"[{sufixo}]"
    for col in df.columns:
        if str(col).endswith(alvo):
            return str(col)
    raise KeyError(f"Coluna {sufixo!r} não veio no resultado: {list(df.columns)}")


def preparar_lado(df: pd.DataFrame, meses: list[int]) -> pd.DataFrame:
    """Normaliza um lado (contábil ou financeiro) numa grade completa de meses.

    Duas coisas acontecem aqui, e as duas importam:

    1. **Renomeia** as colunas DAX para ``empresa``/``chave``/``saldo``.
    2. **Preenche os meses sem movimento.** Uma empresa que não movimentou o
       caixa em março não tem linha de março na consulta — mas tem saldo em
       março (o de fevereiro). Sem o ``ffill``, o mês entraria como ausente e o
       ``merge`` produziria uma divergência inexistente. Antes do primeiro
       movimento o saldo é 0.

    Args:
        df: Resultado bruto de :func:`dax_conciliacao.saldos_contabeis_mensais`
            ou :func:`dax_conciliacao.saldos_financeiros_mensais`.
        meses: Grade contínua de chaves ``AAAAMM`` a devolver.

    Returns:
        ``DataFrame`` com ``empresa``, ``chave`` e ``saldo``, uma linha por
        empresa por mês da grade.
    """
    if df.empty:
        return pd.DataFrame(columns=["empresa", "chave", "saldo"])

    dados = pd.DataFrame(
        {
            "empresa": df[_coluna(df, "EMPRESA")].astype(str).str.strip(),
            "chave": df[_coluna(df, "CHAVE")].astype(float).astype(int),
            "saldo": df[_coluna(df, "SALDO")].astype(float),
        }
    )
    # Uma empresa pode ter linhas fora da grade (meses anteriores ao recorte);
    # elas já estão dentro do acumulado e não precisam ser devolvidas.
    dados = dados[dados["chave"].isin(meses)]

    grade = pd.MultiIndex.from_product(
        [sorted(dados["empresa"].unique()), meses], names=["empresa", "chave"]
    )
    completo = (
        dados.set_index(["empresa", "chave"])
        .reindex(grade)
        .groupby(level="empresa")["saldo"]
        .ffill()
        .fillna(0.0)
        .reset_index()
    )
    return completo


# --------------------------------------------------------------------------- #
# Conciliação
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ResultadoConciliacao:
    """Saída completa de uma rodada de conciliação.

    Attributes:
        linhas: Uma linha por empresa por mês, com os dois saldos, a diferença
            acumulada, a diferença nascida no mês e o status.
        abertura: Comparação do saldo contábil de fechamento de 2024 com o
            ``"SALDO INICIAL DA PLANILHA"`` do livro-caixa.
        transferencias: Líquido mensal das transferências internas por empresa
            (deve ser zero quando as duas pernas ficam na mesma empresa).
        sem_contrapartida: Empresas presentes em um lado e ausentes no mapa do
            outro — nunca somem em silêncio.
        contas_fora_do_config: Contas contábeis com "CAIXA" na descrição que
            não estão em ``contas_caixa``.
        ate_chave: Mês de corte da rodada.
        config: Configuração efetivamente usada.
        queries: As consultas executadas, para auditoria.
    """

    linhas: pd.DataFrame
    abertura: pd.DataFrame
    transferencias: pd.DataFrame
    sem_contrapartida: dict[str, list[str]]
    contas_fora_do_config: pd.DataFrame
    ate_chave: int
    config: dict[str, Any]
    queries: dict[str, str]


def conciliar(
    contabil: pd.DataFrame,
    financeiro: pd.DataFrame,
    config: dict[str, Any],
    ate_chave: int,
    residuo_abertura: dict[str, float] | None = None,
) -> tuple[pd.DataFrame, dict[str, list[str]]]:
    """Cruza os dois lados e classifica cada mês de cada empresa.

    O ``merge`` é feito no nome contábil da empresa: o lado financeiro é
    traduzido pelo mapa ``empresas`` do YAML antes do cruzamento.

    ``residuo_abertura`` é o que separa "saldo inicial errado" de "movimento
    do mês errado". Sem ele, a empresa cujo ``SALDO INICIAL DA PLANILHA`` veio
    incompleto apareceria como divergente em 01/2025 — quando, na verdade,
    todos os movimentos do período batem e o que falta é um ajuste de abertura.
    Com ele, o resíduo é descontado do primeiro mês e ``status`` passa a
    responder só por movimento.

    Args:
        contabil: Saída de :func:`preparar_lado` do lado contábil.
        financeiro: Saída de :func:`preparar_lado` do lado financeiro.
        config: Configuração carregada.
        ate_chave: Mês de corte (``AAAAMM``).
        residuo_abertura: ``{empresa_contábil: diferença_de_abertura}``, no
            mesmo sinal de ``diferenca`` (financeiro − contábil). ``None`` trata
            todas as empresas como abertura zerada.

    Returns:
        Tupla ``(linhas, sem_contrapartida)``. ``linhas`` tem uma linha por
        empresa/mês com ``saldo_contabil``, ``saldo_financeiro``,
        ``diferenca``, ``residuo_abertura``, ``diferenca_do_mes`` e ``status``.
    """
    mapa = config["empresas"]
    tolerancia = float(config["tolerancia_reais"])

    fin = financeiro.copy()
    fin["empresa_financeiro"] = fin["empresa"]
    fin["empresa"] = fin["empresa"].map(mapa)

    nao_mapeadas = sorted(
        fin.loc[fin["empresa"].isna(), "empresa_financeiro"].unique().tolist()
    )
    fin = fin.dropna(subset=["empresa"])

    ctb_empresas = set(contabil["empresa"].unique())
    fin_empresas = set(fin["empresa"].unique())
    sem_contrapartida = {
        "financeiro_sem_mapa": nao_mapeadas,
        "so_no_contabil": sorted(ctb_empresas - fin_empresas),
        "so_no_financeiro": sorted(fin_empresas - ctb_empresas),
    }

    linhas = pd.merge(
        contabil.rename(columns={"saldo": "saldo_contabil"}),
        fin[["empresa", "chave", "saldo"]].rename(columns={"saldo": "saldo_financeiro"}),
        on=["empresa", "chave"],
        how="outer",
    ).fillna({"saldo_contabil": 0.0, "saldo_financeiro": 0.0})

    linhas = linhas[linhas["chave"] <= ate_chave].sort_values(["empresa", "chave"])
    linhas["diferenca"] = linhas["saldo_financeiro"] - linhas["saldo_contabil"]
    residuo = residuo_abertura or {}
    linhas["residuo_abertura"] = linhas["empresa"].map(residuo).fillna(0.0)
    # Diferença nascida NESTE mês = variação da diferença acumulada. No primeiro
    # mês da série não há mês anterior: a base de comparação é o resíduo de
    # abertura, para que o saldo inicial faltante não conte como movimento.
    linhas["diferenca_do_mes"] = (
        linhas.groupby("empresa")["diferenca"]
        .diff()
        .fillna(linhas["diferenca"] - linhas["residuo_abertura"])
    )
    linhas["status"] = [
        "OK" if abs(d) <= tolerancia else "DIVERGENTE"
        for d in linhas["diferenca_do_mes"]
    ]
    return linhas.reset_index(drop=True), sem_contrapartida


def _preparar_abertura(
    abertura_fin: pd.DataFrame,
    contabil_bruto: pd.DataFrame,
    config: dict[str, Any],
) -> pd.DataFrame:
    """Monta o quadro de abertura: contábil 12/2024 x planilha 01/01/2025.

    O saldo contábil de fechamento é lido do próprio resultado mensal do lado
    contábil (última chave ``<= mes_abertura``), evitando uma consulta extra.
    Empresa sem linha de abertura no financeiro entra com 0 — é justamente o
    caso que precisa aparecer (CORRETORA nunca teve saldo inicial lançado).
    """
    mapa = config["empresas"]
    mes_abertura = int(config["mes_abertura"])
    tolerancia = float(config["tolerancia_reais"])

    if contabil_bruto.empty:
        fechamento = pd.Series(dtype=float)
    else:
        ctb = pd.DataFrame(
            {
                "empresa": contabil_bruto[_coluna(contabil_bruto, "EMPRESA")]
                .astype(str)
                .str.strip(),
                "chave": contabil_bruto[_coluna(contabil_bruto, "CHAVE")]
                .astype(float)
                .astype(int),
                "saldo": contabil_bruto[_coluna(contabil_bruto, "SALDO")].astype(float),
            }
        )
        ctb = ctb[ctb["chave"] <= mes_abertura].sort_values("chave")
        fechamento = ctb.groupby("empresa")["saldo"].last()

    if abertura_fin.empty:
        planilha = pd.Series(dtype=float)
    else:
        fin = pd.DataFrame(
            {
                "empresa_financeiro": abertura_fin[_coluna(abertura_fin, "EMPRESA")]
                .astype(str)
                .str.strip(),
                "abertura": abertura_fin[_coluna(abertura_fin, "ABERTURA")].astype(float),
            }
        )
        fin["empresa"] = fin["empresa_financeiro"].map(mapa)
        planilha = fin.dropna(subset=["empresa"]).groupby("empresa")["abertura"].sum()

    empresas = sorted(set(fechamento.index) | set(planilha.index))
    quadro = pd.DataFrame(
        {
            "empresa": empresas,
            "contabil_fechamento": [float(fechamento.get(e, 0.0)) for e in empresas],
            "planilha_abertura": [float(planilha.get(e, 0.0)) for e in empresas],
        }
    )
    quadro["diferenca"] = quadro["planilha_abertura"] - quadro["contabil_fechamento"]
    quadro["status"] = [
        "OK" if abs(d) <= tolerancia else "DIVERGENTE" for d in quadro["diferenca"]
    ]
    return quadro


def _preparar_transferencias(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Normaliza o líquido de transferências caixa a caixa, por empresa e mês.

    Devolve só os pares empresa/mês com líquido diferente de zero. Eles não são
    exceção por si — um líquido sobrando pode ter contrapartida classificada em
    outra origem e estar perfeitamente contabilizado. Servem como **pista** e o
    relatório só os mostra cruzados com um mês já apontado como divergente.
    """
    if df.empty:
        return pd.DataFrame(columns=["empresa", "chave", "liquido"])
    dados = pd.DataFrame(
        {
            "empresa_financeiro": df[_coluna(df, "EMPRESA")].astype(str).str.strip(),
            "chave": df[_coluna(df, "CHAVE")].astype(float).astype(int),
            "liquido": df[_coluna(df, "LIQUIDO_TRANSF")].astype(float),
        }
    )
    dados["empresa"] = dados["empresa_financeiro"].map(config["empresas"])
    dados["empresa"] = dados["empresa"].fillna(dados["empresa_financeiro"])
    tolerancia = float(config["tolerancia_reais"])
    return dados[dados["liquido"].abs() > tolerancia][
        ["empresa", "chave", "liquido"]
    ].reset_index(drop=True)


def _contas_fora_do_config(df: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    """Contas com "CAIXA" na descrição que não estão em ``contas_caixa``.

    Bancos entram na descrição de algumas contas ("BANCO CAIXA..."), então a
    lista é informativa: cabe ao controller decidir se a conta nova é caixa de
    verdade. O que não pode é uma conta de espécie surgir sem ninguém ver.
    """
    if df.empty:
        return pd.DataFrame(columns=["conta", "descricao", "empresa", "saldo"])
    dados = pd.DataFrame(
        {
            "conta": df[_coluna(df, "CONTA")].astype(str).str.strip(),
            "descricao": df[_coluna(df, "DESCRICAO_CONTA")].astype(str).str.strip(),
            "empresa": df[_coluna(df, "EMPRESA")].astype(str).str.strip(),
            "saldo": df[_coluna(df, "SALDO")].astype(float),
        }
    )
    conhecidas = set(config["contas_caixa"])
    return dados[~dados["conta"].isin(conhecidas)].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Execução
# --------------------------------------------------------------------------- #
def executar(
    ate: str | int,
    empresa: str | None = None,
    cliente: PowerBIClient | None = None,
    config: dict[str, Any] | None = None,
    dataset_financeiro: str | None = DATASET_FINANCEIRO,
    dataset_contabil: str | None = None,
) -> ResultadoConciliacao:
    """Roda a conciliação até o mês pedido e devolve o resultado estruturado.

    Args:
        ate: Mês de corte, ``"MM/AAAA"`` ou chave ``AAAAMM``.
        empresa: Filtra uma empresa. Aceita o nome do financeiro
            (``"ROYAL ENFIELD"``) ou do contábil (``"ROYAL"``).
        cliente: Cliente Power BI já construído. ``None`` cria um.
        config: Configuração já carregada. ``None`` lê o YAML.
        dataset_financeiro: Apelido/GUID do dataset do livro-caixa.
        dataset_contabil: Apelido/GUID do dataset contábil. ``None`` = padrão
            do ``.env``.

    Returns:
        O :class:`ResultadoConciliacao` completo.

    Raises:
        ErroConfiguracao: Configuração ausente ou inválida.
        ErroPowerBI: Falha em qualquer das consultas.
        ValueError: Período mal formatado ou empresa desconhecida.
    """
    config = config or carregar_config()
    cliente = cliente or PowerBIClient(config=carregar_configuracao())

    ate_chave = int(ate) if isinstance(ate, int) else periodo_para_chave(str(ate))
    desde_chave = int(config["primeiro_mes"])
    if ate_chave < desde_chave:
        raise ValueError(
            f"Mês de corte {chave_para_periodo(ate_chave)} é anterior ao primeiro "
            f"mês conciliável ({chave_para_periodo(desde_chave)})."
        )

    mapa = config["empresas"]
    emp_fin: str | None = None
    emp_ctb: str | None = None
    if empresa:
        alvo = str(empresa).strip().upper()
        for chave_fin, chave_ctb in mapa.items():
            if alvo in (chave_fin.upper(), chave_ctb.upper()):
                emp_fin, emp_ctb = chave_fin, chave_ctb
                break
        if emp_fin is None:
            raise ValueError(
                f"Empresa {empresa!r} não está no mapa de config/conciliacao_caixa.yaml. "
                f"Conhecidas: {', '.join(sorted(mapa))}."
            )

    corte = ultimo_dia(ate_chave)
    contas = config["contas_caixa"]
    # O acumulado contábil precisa começar na abertura de 2024 para que o quadro
    # de abertura saia da mesma consulta — o SALDO já é cumulativo desde o
    # início da base, o recorte só define quais meses voltam.
    desde_contabil = min(desde_chave, int(config["mes_abertura"]))

    queries = {
        "contabil": dxc.saldos_contabeis_mensais(
            contas, ate_chave, desde_contabil, emp_ctb
        ),
        "financeiro": dxc.saldos_financeiros_mensais(corte, desde_chave, emp_fin),
        "abertura": dxc.abertura_financeira(emp_fin),
        "transferencias": dxc.transferencias_por_empresa(
            corte, desde_chave, config["origens_transferencia_interna"]
        ),
        "contas_candidatas": dxc.contas_de_caixa_candidatas(),
    }

    contabil_bruto = cliente.execute_dax(queries["contabil"], dataset_id=dataset_contabil)
    financeiro_bruto = cliente.execute_dax(
        queries["financeiro"], dataset_id=dataset_financeiro
    )
    abertura_bruta = cliente.execute_dax(queries["abertura"], dataset_id=dataset_financeiro)
    transf_bruta = cliente.execute_dax(
        queries["transferencias"], dataset_id=dataset_financeiro
    )
    contas_brutas = cliente.execute_dax(
        queries["contas_candidatas"], dataset_id=dataset_contabil
    )

    meses = _meses(desde_chave, ate_chave)
    # A abertura sai primeiro: o resíduo dela é insumo da conciliação mensal,
    # senão o saldo inicial faltante vira "divergência de movimento" em 01/2025.
    abertura = _preparar_abertura(abertura_bruta, contabil_bruto, config)
    residuo = dict(zip(abertura["empresa"], abertura["diferenca"].astype(float)))
    linhas, sem_contrapartida = conciliar(
        preparar_lado(contabil_bruto, meses),
        preparar_lado(financeiro_bruto, meses),
        config,
        ate_chave,
        residuo,
    )

    return ResultadoConciliacao(
        linhas=linhas,
        abertura=abertura,
        transferencias=_preparar_transferencias(transf_bruta, config),
        sem_contrapartida=sem_contrapartida,
        contas_fora_do_config=_contas_fora_do_config(contas_brutas, config),
        ate_chave=ate_chave,
        config=config,
        queries=queries,
    )


# --------------------------------------------------------------------------- #
# Relatório
# --------------------------------------------------------------------------- #
def _moeda(valor: float) -> str:
    """Formata no padrão brasileiro, com negativo entre parênteses.

    Resíduo de ponto flutuante é achatado em zero antes de formatar: sem isso,
    uma empresa que concilia perfeitamente sai como ``(0,00)`` — parênteses de
    negativo em cima de ``-1e-12``, que lê como diferença onde não há nenhuma.
    """
    if abs(valor) < 0.005:
        valor = 0.0
    texto = f"{abs(valor):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
    return f"({texto})" if valor < 0 else texto


def montar_relatorio(resultado: ResultadoConciliacao) -> str:
    """Monta o relatório de conciliação em Markdown.

    A ordem das seções segue a ordem em que o controller precisa decidir:
    primeiro o veredito por empresa, depois a abertura (que explica o resíduo
    constante), depois os meses divergentes (o que precisa ser investigado) e
    só então os diagnósticos e as queries.
    """
    cfg = resultado.config
    tolerancia = float(cfg["tolerancia_reais"])
    linhas = resultado.linhas
    corte = chave_para_periodo(resultado.ate_chave)
    inicio = chave_para_periodo(int(cfg["primeiro_mes"]))

    out: list[str] = [
        "# Conciliação de Caixa — financeiro x contábil",
        "",
        f"- **Período:** {inicio} a {corte} (saldo de fechamento de cada mês)",
        "- **Chave de conciliação:** EMPRESA (não revenda — ver observação no rodapé)",
        f"- **Contas contábeis:** {', '.join(cfg['contas_caixa'])} (CAIXA GERAL)",
        "- **Fonte financeira:** `CAIXAS[VALOR]`, dataset `controlador`, "
        "sem excluir caixa nenhum",
        f"- **Tolerância:** R$ {tolerancia:.2f}",
        "",
        "> ⚠️ Nenhum número deste relatório é medida oficial: os dois modelos "
        "estão sem medidas cadastradas. Tudo é soma direta de `CAIXAS[VALOR]` e "
        "`lancamentos[VALOR_AJUSTADO]`.",
        "",
    ]

    if linhas.empty:
        out.append("(nenhuma linha retornada — verifique contas e período)")
        return "\n".join(out)

    # ---------------------------------------------------------------- veredito
    out.append("## Veredito por empresa")
    out.append("")
    out.append(
        "Legenda: ✅ concilia · ⚠️ movimentos batem, falta ajuste de saldo "
        "inicial · ❌ movimento descasado em algum mês."
    )
    out.append("")
    out.append(
        "| Empresa | Saldo contábil | Saldo financeiro | Diferença "
        "| da abertura | Meses divergentes |"
    )
    out.append("|---|---:|---:|---:|---:|---:|")

    ultimo = linhas[linhas["chave"] == resultado.ate_chave].set_index("empresa")
    divergentes_por_empresa = (
        linhas[linhas["status"] == "DIVERGENTE"].groupby("empresa").size()
    )
    total_ctb = total_fin = total_abertura = 0.0
    for empresa in sorted(ultimo.index):
        r = ultimo.loc[empresa]
        n_div = int(divergentes_por_empresa.get(empresa, 0))
        abertura_emp = float(r["residuo_abertura"])
        if n_div:
            marca = "❌"
        elif abs(abertura_emp) > tolerancia:
            marca = "⚠️"
        else:
            marca = "✅"
        total_ctb += float(r["saldo_contabil"])
        total_fin += float(r["saldo_financeiro"])
        total_abertura += abertura_emp
        out.append(
            f"| {marca} {empresa} | {_moeda(float(r['saldo_contabil']))} "
            f"| {_moeda(float(r['saldo_financeiro']))} "
            f"| {_moeda(float(r['diferenca']))} "
            f"| {_moeda(abertura_emp)} | {n_div} |"
        )
    out.append(
        f"| **TOTAL** | **{_moeda(total_ctb)}** | **{_moeda(total_fin)}** "
        f"| **{_moeda(total_fin - total_ctb)}** "
        f"| **{_moeda(total_abertura)}** "
        f"| **{int(divergentes_por_empresa.sum())}** |"
    )
    out.append("")

    # ---------------------------------------------------------------- abertura
    abertura = resultado.abertura
    if not abertura.empty:
        fora = abertura[abertura["status"] == "DIVERGENTE"]
        out.append(
            f"## Abertura do livro-caixa ({chave_para_periodo(int(cfg['mes_abertura']))} "
            "contábil x SALDO INICIAL DA PLANILHA)"
        )
        out.append("")
        if fora.empty:
            out.append(
                "✅ Todas as empresas iniciaram o livro-caixa com o saldo contábil "
                "de fechamento correto."
            )
        else:
            out.append(
                "A diferença abaixo **não é erro de lançamento do período**: é "
                "saldo inicial que a planilha não trouxe (ou trouxe a mais). Ela "
                "se arrasta constante por todos os meses seguintes e só sai com "
                "um ajuste de abertura."
            )
            out.append("")
            out.append("| Empresa | Contábil (fechamento) | Planilha (abertura) | Diferença |")
            out.append("|---|---:|---:|---:|")
            for _, r in fora.iterrows():
                out.append(
                    f"| {r['empresa']} | {_moeda(float(r['contabil_fechamento']))} "
                    f"| {_moeda(float(r['planilha_abertura']))} "
                    f"| {_moeda(float(r['diferenca']))} |"
                )
        out.append("")

    # ------------------------------------------------------- meses divergentes
    divergentes = linhas[linhas["status"] == "DIVERGENTE"]
    out.append("## Meses com divergência de movimento")
    out.append("")
    if divergentes.empty:
        out.append(
            "✅ Nenhum. Em todos os meses do período os dois livros registraram "
            "exatamente o mesmo movimento de caixa por empresa. O que sobrar de "
            "diferença acumulada vem inteiramente da abertura."
        )
    else:
        out.append(
            "`Diferença do mês` é a variação da diferença acumulada — o que "
            "nasceu **neste** mês. O resíduo de abertura já está descontado, "
            "então toda linha aqui é movimento realmente descasado."
        )
        out.append("")
        out.append(
            "| Empresa | Mês | Saldo contábil | Saldo financeiro "
            "| Diferença acumulada | Diferença do mês |"
        )
        out.append("|---|---|---:|---:|---:|---:|")
        for _, r in divergentes.iterrows():
            out.append(
                f"| {r['empresa']} | {chave_para_periodo(int(r['chave']))} "
                f"| {_moeda(float(r['saldo_contabil']))} "
                f"| {_moeda(float(r['saldo_financeiro']))} "
                f"| {_moeda(float(r['diferenca']))} "
                f"| {_moeda(float(r['diferenca_do_mes']))} |"
            )
    out.append("")

    # ------------------------------------------------------------ diagnósticos
    avisos: list[str] = []

    # Só interessa a transferência caixa a caixa que caiu num mês JÁ divergente
    # — sozinha ela não é exceção (pode ter contrapartida em outra origem).
    transf = resultado.transferencias
    if not transf.empty and not divergentes.empty:
        chaves_divergentes = set(
            zip(divergentes["empresa"], divergentes["chave"].astype(int))
        )
        pistas = [
            r
            for _, r in transf.iterrows()
            if (r["empresa"], int(r["chave"])) in chaves_divergentes
        ]
        if pistas:
            avisos.append(
                "- **Transferência caixa a caixa sem par no mesmo mês/empresa** — "
                "candidata a explicar a divergência apontada acima:"
            )
            avisos.extend(
                f"  - {r['empresa']} · {chave_para_periodo(int(r['chave']))} · "
                f"{_moeda(float(r['liquido']))}"
                for r in pistas
            )

    sc = resultado.sem_contrapartida
    if sc["financeiro_sem_mapa"]:
        avisos.append(
            "- **Empresas do financeiro fora do mapa** (não conciliadas — "
            "acrescente em `config/conciliacao_caixa.yaml`): "
            + ", ".join(sc["financeiro_sem_mapa"])
        )
    if sc["so_no_contabil"]:
        avisos.append(
            "- **Empresas só no contábil** (têm saldo em CAIXA GERAL e nenhum "
            "lançamento no livro-caixa): " + ", ".join(sc["so_no_contabil"])
        )
    if sc["so_no_financeiro"]:
        avisos.append(
            "- **Empresas só no financeiro** (movimentam caixa e não têm conta "
            "contábil de caixa mapeada): " + ", ".join(sc["so_no_financeiro"])
        )

    contas_novas = resultado.contas_fora_do_config
    if not contas_novas.empty:
        rotulos = sorted(
            {f"{r['conta']} ({r['descricao']})" for _, r in contas_novas.iterrows()}
        )
        avisos.append(
            "- **Contas com \"CAIXA\" na descrição fora de `contas_caixa`** — "
            "confira se alguma é caixa em espécie e deveria entrar: "
            + "; ".join(rotulos)
        )

    if avisos:
        out.append("## Diagnósticos")
        out.append("")
        # Cada aviso já vem com o próprio marcador — sub-itens são indentados
        # e não podem levar um "- " extra na frente (quebra a lista aninhada).
        out.extend(avisos)
        out.append("")

    # ------------------------------------------------------------- observações
    out.append("## Por que por empresa, e não por revenda")
    out.append("")
    out.append(
        "Transferência de saldo de caixa para caixa (`ORIGEM` com `SALDO "
        "CAIXA`) gera duas linhas no livro-caixa e **nenhum lançamento "
        "contábil** — o dinheiro não saiu da conta CAIXA GERAL. Quando as duas "
        "pernas estão em revendas diferentes da mesma empresa, a quebra por "
        "revenda nunca fecha e a por empresa fecha, porque as pernas se anulam. "
        "Por isso a conciliação é por EMPRESA, e a quebra por revenda só serve "
        "para estreitar a busca dentro de um mês já apontado como divergente. "
        "As origens `TRANSF. CAIXA P/ <banco>` são outra coisa: têm "
        "contrapartida em conta bancária e são contabilizadas normalmente."
    )
    out.append("")
    out.append(
        "**Granularidade:** mensal. A tabela contábil `lancamentos` não tem "
        "coluna de data — só `PERIODO` (`MM/AAAA`). Não existe saldo contábil "
        "diário para comparar; o financeiro é cortado no último dia do mês."
    )
    out.append("")
    out.append("---")
    out.append("")
    out.append("<details><summary>Consultas executadas (auditoria)</summary>")
    out.append("")
    for nome, query in resultado.queries.items():
        out.append(f"**{nome}**")
        out.append("")
        out.append("```dax")
        out.append(query.strip())
        out.append("```")
        out.append("")
    out.append("</details>")
    return "\n".join(out)


def gerar_relatorio(
    ate: str | int,
    empresa: str | None = None,
    salvar: bool = True,
) -> tuple[str, Path | None]:
    """Roda a conciliação e devolve ``(relatório, caminho_salvo)``.

    Args:
        ate: Mês de corte, ``"MM/AAAA"`` ou chave ``AAAAMM``.
        empresa: Filtra uma empresa. ``None`` = todas.
        salvar: Se ``True``, grava em ``reports/``.
    """
    resultado = executar(ate=ate, empresa=empresa)
    texto = montar_relatorio(resultado)
    if not salvar:
        return texto, None

    PASTA_REPORTS.mkdir(parents=True, exist_ok=True)
    sufixo = f"_{str(empresa).strip().lower().replace(' ', '_')}" if empresa else ""
    destino = (
        PASTA_REPORTS / f"conciliacao_caixa_{resultado.ate_chave}{sufixo}.md"
    )
    destino.write_text(texto, encoding="utf-8")
    return texto, destino


def main() -> int:
    """CLI da conciliação. Devolve 0 em sucesso, 1 em falha."""
    parser = argparse.ArgumentParser(
        description="Concilia o livro-caixa financeiro com o saldo contábil, por empresa."
    )
    parser.add_argument(
        "ate",
        nargs="?",
        default=None,
        help="Mês de corte no formato MM/AAAA (padrão: mês anterior ao atual).",
    )
    parser.add_argument(
        "--empresa",
        default=None,
        help="Concilia só uma empresa (nome do financeiro ou do contábil).",
    )
    parser.add_argument(
        "--sem-salvar",
        action="store_true",
        help="Só imprime o relatório, sem gravar em reports/.",
    )
    args = parser.parse_args()

    # O console do Windows abre em cp1252 e engasga com os ✅/❌/⚠️ do relatório.
    # O arquivo em reports/ já é gravado em UTF-8; aqui é só a saída de tela.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.ate:
        ate: str | int = args.ate
    else:
        hoje = date.today()
        ate = (hoje.year * 100 + hoje.month) - 1 if hoje.month > 1 else (hoje.year - 1) * 100 + 12

    try:
        texto, destino = gerar_relatorio(ate, args.empresa, salvar=not args.sem_salvar)
    except (ErroConfiguracao, ValueError) as exc:
        print(f"❌ {exc}")
        return 1
    except ErroPowerBI as exc:
        print(f"❌ Erro ao consultar o Power BI:\n{exc}")
        return 1

    print(texto)
    if destino:
        print(f"\n✅ Conciliação salva em: {destino}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
