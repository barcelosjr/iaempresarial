"""Monitoramento COAF: recebimentos em espécie acima do limiar em 6 meses.

Detecta clientes cujo acumulado recebido em espécie atinge R$ 30 mil em uma
janela móvel de 6 meses, gera a DMF (Declaração de Movimentação Financeira) em
PDF e — com ``--enviar`` — despacha por e-mail ao responsável pelo caixa.

Projetado para rodar de 30 em 30 minutos pelo Agendador de Tarefas do Windows
(``scripts/coaf_agendar.ps1``), acompanhando o refresh da base.

Três decisões de projeto que não são óbvias
-------------------------------------------

1. **A agregação é em Python, não em DAX**, e a chave de identidade é
   ``CAIXAS[CLIENTE]`` (o código) — decisão do gestor, 26/08/2026, depois de
   um reenvio indevido em produção causado por usar o nome como chave (ver
   :func:`chave_do_cliente`). O nome (``CAIXAS[NOME_CLIENTE]``, com o parser
   de ``HISTORICO`` como fallback — :func:`extrair_nome_cliente`) é só
   informação de exibição, não afeta mais a chave.
2. **A janela de 6 meses é móvel.** Testar só "os últimos 6 meses a partir de
   hoje" deixaria passar fracionamento que cruza a borda do semestre. Toda
   janela que termina em uma data de recebimento é avaliada — ver
   :func:`detectar`.
3. **Histórico e notificação são coisas separadas.** A deduplicação decide
   apenas se dispara e-mail; nada é removido do histórico permanente. Ver
   ``local_data/coaf_estado.py``.

Uso:
    python analysis/coaf_especie.py                  # modo revisão (não envia)
    python analysis/coaf_especie.py --enviar         # envia de verdade
    python analysis/coaf_especie.py --historico      # só reimprime o histórico
    python analysis/coaf_especie.py --historico --csv
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import (  # noqa: E402
    RAIZ_PROJETO,
    Configuracao,
    ErroConfiguracao,
    carregar_configuracao,
)
from local_data import coaf_estado as estado  # noqa: E402
from powerbi import dax_coaf  # noqa: E402
from powerbi.client import ErroPowerBI, PowerBIClient  # noqa: E402

#: Dataset de lançamentos de caixa — o padrão do .env é o contábil, então o
#: apelido precisa ser explícito em toda chamada.
DATASET_PADRAO = "controlador"

PASTA_REPORTS = RAIZ_PROJETO / "reports"
PASTA_DMF = PASTA_REPORTS / "dmf"
PASTA_LOGS = RAIZ_PROJETO / "logs"
CONFIG_COAF = RAIZ_PROJETO / "config" / "coaf.yaml"
CONFIG_DESTINATARIOS = RAIZ_PROJETO / "config" / "responsaveis_caixa.yaml"

logger = logging.getLogger("coaf")


# --------------------------------------------------------------------------- #
# Configuração
# --------------------------------------------------------------------------- #
def carregar_config_coaf(caminho: Path | None = None) -> dict[str, Any]:
    """Lê ``config/coaf.yaml`` com os parâmetros da regra de negócio.

    Args:
        caminho: Caminho alternativo do YAML. ``None`` usa o padrão.

    Returns:
        Dicionário com limiar, janela, exclusões e caixas sinalizados.

    Raises:
        ErroConfiguracao: Se o arquivo não existir ou estiver malformado.
    """
    caminho = caminho or CONFIG_COAF
    if not caminho.exists():
        raise ErroConfiguracao(
            f"Arquivo de configuração do COAF não encontrado: {caminho}"
        )
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    dados.setdefault("limiar_reais", 30000)
    dados.setdefault("janela_meses", 6)
    dados.setdefault("janela_dias_folga", 5)
    dados.setdefault("meses_consulta", 12)
    dados.setdefault("escopo_alerta", "grupo")
    dados.setdefault("reenvio_dias", 30)
    dados.setdefault("exclusoes_origem", {})
    dados["exclusoes_origem"].setdefault(
        "padroes", list(dax_coaf.PADROES_EXCLUSAO_PADRAO)
    )
    dados["exclusoes_origem"].setdefault("exatas", [])
    dados.setdefault("caixas_sinalizados", {})
    dados["caixas_sinalizados"].setdefault("global", [])
    dados["caixas_sinalizados"].setdefault("por_revenda", {})
    dados.setdefault("caixas_excluidos", {})
    dados["caixas_excluidos"].setdefault("global", [])
    dados.setdefault("clientes_excluidos", {})
    dados["clientes_excluidos"].setdefault("nomes", [])
    dados["clientes_excluidos"].setdefault("codigos", [])
    return dados


def carregar_destinatarios(caminho: Path | None = None) -> dict[str, Any]:
    """Lê ``config/responsaveis_caixa.yaml``.

    O roteamento é por **caixa**: a chave é ``REVENDA + CAIXA`` do lançamento
    que disparou a cobrança. Não é por usuário nem por todos os caixas em que o
    cliente movimentou — a apuração é do grupo, mas a cobrança tem um dono só.

    Arquivo ausente não é erro fatal: o job segue gerando alertas e PDFs, e
    registra a lacuna no relatório. Bloquear a detecção porque falta um e-mail
    seria o pior dos mundos para o compliance.

    Returns:
        Dicionário com ``email_coaf``, ``email_padrao``, ``responsavel_padrao``
        e o mapa ``(revenda, caixa) -> {"nome", "email"}``.
    """
    caminho = caminho or CONFIG_DESTINATARIOS
    if not caminho.exists():
        logger.warning("Mapa de responsáveis não encontrado: %s", caminho)
        return {
            "email_coaf": "",
            "email_padrao": "",
            "responsavel_padrao": "Controladoria",
            "mapa": {},
        }
    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    mapa: dict[tuple[str, str], dict[str, str]] = {}
    for item in dados.get("responsaveis") or []:
        chave = (
            str(item.get("revenda", "")).strip(),
            str(item.get("caixa", "")).strip(),
        )
        mapa[chave] = {
            "nome": (item.get("nome") or "").strip(),
            "email": (item.get("email") or "").strip(),
        }
    return {
        "email_coaf": (dados.get("email_coaf") or "").strip(),
        "email_padrao": (dados.get("email_padrao") or "").strip(),
        "responsavel_padrao": dados.get("responsavel_padrao") or "Controladoria",
        "mapa": mapa,
    }


# --------------------------------------------------------------------------- #
# Identidade do cliente
# --------------------------------------------------------------------------- #
#: Captura o nome do cliente no texto livre de HISTORICO. Cobre as variações
#: reais observadas na base: "Cliente:FULANO" (sem espaço, em adiantamentos) e
#: "Cliente: FULANO" (com espaço, em notas fiscais). O nome vai até o fim da
#: linha — não há campo depois dele nos formatos conhecidos.
_RE_CLIENTE = re.compile(r"Cliente:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)


def extrair_nome_cliente(historico: Any) -> str | None:
    """Extrai o nome do cliente do texto livre de ``HISTORICO``.

    Fallback do nome de exibição (a fonte primária é ``CAIXAS[NOME_CLIENTE]``
    — ver :func:`preparar_lancamentos`), usado quando essa coluna vem em
    branco em algum lançamento. Três variações reais observadas no texto:

    - ``"Ref. Adiantamento: 4 Cliente:VANDERLEY FRANCISCO BARBOSA RAMOS"``
    - ``"Ref. Nota(s) Fiscal(is): 68391 30608 Cliente: ALICE PEREIRA COSTA"``
    - ``"Ref. Estorno Titulo: 73 Cliente: LAGE E SCARABELI COMERCIO LTDA"``

    Args:
        historico: Conteúdo de ``CAIXAS[HISTORICO]``.

    Returns:
        O nome encontrado, ou ``None`` quando o histórico não traz cliente
        (lançamentos de baixa de adiantamento em lote, por exemplo).
    """
    if not isinstance(historico, str) or not historico:
        return None
    achado = _RE_CLIENTE.search(historico)
    if not achado:
        return None
    nome = achado.group(1).strip()
    # Históricos multilinha (baixa de adiantamento em lote) trazem lixo após o
    # nome; corta em quebra de linha literal ou escapada.
    nome = re.split(r"\\r|\\n|[\r\n]", nome)[0].strip()
    return nome or None


#: Valores de ``CAIXAS[Fisjur]``. Além de F e J existe "O" (97 lançamentos em
#: 19/08/2026) — tipo desconhecido, tratado como não identificado.
PESSOA_FISICA = "F"
PESSOA_JURIDICA = "J"

#: Mínimo de dígitos para tentar reconstruir um documento. O CPF perde no
#: máximo os zeros à esquerda (11 -> 8 no pior caso realista); abaixo disso o
#: valor é lixo e a DMF sai com o campo em branco.
DIGITOS_MINIMOS = 8


def formatar_documento(bruto: Any, fisjur: Any) -> tuple[str, str]:
    """Normaliza e formata o CPF/CNPJ do cliente.

    **O zero à esquerda se perde na base**: o CPF de VALDETE TEIXEIRA DA SILVA
    chega como ``6418722671`` (10 dígitos), não ``06418722671``. Como o campo é
    numérico na origem, todo documento que começa com zero vem truncado — por
    isso o preenchimento à esquerda antes de aplicar a máscara. Sem isso a DMF
    sairia com um CPF inválido, que é pior do que sair em branco.

    Args:
        bruto: Valor de ``CAIXAS[cpf_cnpj]``.
        fisjur: Valor de ``CAIXAS[Fisjur]`` (``"F"``, ``"J"`` ou outro).

    Returns:
        Tupla ``(tipo, documento_formatado)``. ``tipo`` é ``"F"``, ``"J"`` ou
        ``""`` quando não identificado; o documento vem vazio quando não há
        dígito suficiente para um CPF ou CNPJ válido em comprimento.
    """
    tipo = str(fisjur or "").strip().upper()
    digitos = re.sub(r"[^0-9]", "", str(bruto or ""))
    tipo_saida = tipo if tipo in (PESSOA_FISICA, PESSOA_JURIDICA) else ""
    # Menos de 8 dígitos não é CPF com zeros perdidos, é lixo. Preencher com
    # zeros produziria um documento inválido na DMF — pior que deixar em branco.
    if len(digitos) < DIGITOS_MINIMOS or int(digitos or 0) == 0:
        return tipo_saida, ""

    if tipo == PESSOA_JURIDICA:
        digitos = digitos.zfill(14)
    elif tipo == PESSOA_FISICA:
        digitos = digitos.zfill(11)
    else:
        # Tipo desconhecido: deduz pelo comprimento, sem inventar máscara.
        if len(digitos) > 11:
            tipo, digitos = PESSOA_JURIDICA, digitos.zfill(14)
        elif len(digitos) <= 11:
            tipo, digitos = PESSOA_FISICA, digitos.zfill(11)

    if tipo == PESSOA_JURIDICA and len(digitos) == 14:
        return tipo, (
            f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/"
            f"{digitos[8:12]}-{digitos[12:]}"
        )
    if tipo == PESSOA_FISICA and len(digitos) == 11:
        return tipo, f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"
    return tipo, ""


def rotulos_do_declarante(tipo: str) -> tuple[str, str]:
    """Rótulos dos campos 1 e 2 da DMF, conforme o tipo de pessoa.

    Pedido do gestor (19/08/2026): pessoa jurídica declara *Razão Social* e
    *CNPJ*; pessoa física declara *Nome* e *CPF*. Quando o tipo não é
    identificado, mantém-se o rótulo genérico do formulário original.

    Args:
        tipo: ``"F"``, ``"J"`` ou vazio.

    Returns:
        Tupla ``(rotulo_campo_1, rotulo_campo_2)``.
    """
    if tipo == PESSOA_JURIDICA:
        return "RAZÃO SOCIAL", "CNPJ"
    if tipo == PESSOA_FISICA:
        return "NOME", "CPF"
    return "RAZÃO SOCIAL / NOME", "CNPJ / CPF"


def normalizar_texto(valor: str) -> str:
    """Normaliza um nome para uso como chave: sem acento, maiúsculo, sem espaço duplo."""
    sem_acento = "".join(
        c
        for c in unicodedata.normalize("NFKD", str(valor))
        if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sem_acento).strip().upper()


def chave_do_cliente(codigo: Any) -> str:
    """Resolve a chave de agregação e de identidade do cliente.

    Decisão do gestor (26/08/2026): a chave é ``CAIXAS[CLIENTE]`` (o código),
    não o nome. Motivo — o nome, seja de ``NOME_CLIENTE`` (cadastro) ou do
    parser de ``HISTORICO``, pode variar de formatação entre lançamentos ou
    ser corrigido com o tempo; usá-lo como chave faz o mesmo cliente virar
    "pessoas" diferentes aos olhos do histórico e do controle de notificação
    — foi o que aconteceu em produção em 26/08/2026 (código 225456, ver
    ``dictionary/regras_negocio.md``). O código é estável: confirmado em
    25/08/2026 que nenhum ``CAIXAS[CLIENTE]`` aparece com mais de um
    ``NOME_CLIENTE`` distinto nos recebimentos do período.

    Args:
        codigo: Valor de ``CAIXAS[CLIENTE]``.

    Returns:
        A chave, como string (``codigo`` já vem como string da consulta;
        ``str()`` aqui é só para tolerar chamada direta com outro tipo).
    """
    return str(codigo).strip()


def resolver_nome_do_grupo(nomes: "pd.Series") -> tuple[str, bool]:
    """Nome de exibição de um caso, a partir dos nomes de cada lançamento.

    Como a chave agora é o código (não o nome), um grupo pode ter lançamentos
    com nome resolvido e outros sem (ex.: um SAQUE sem "Cliente:" no
    HISTORICO, ao lado de uma nota fiscal que tem). Usa o primeiro nome não
    vazio encontrado; se nenhum lançamento do grupo tiver nome, o caso fica
    sem identificação — mesmo comportamento de antes, só que decidido por
    grupo em vez de por lançamento isolado.

    Args:
        nomes: Coluna ``NOME_CLIENTE`` (por lançamento) do grupo.

    Returns:
        Tupla ``(nome_exibicao, nome_identificado)``.
    """
    for nome in nomes:
        if nome:
            return str(nome).strip(), True
    return "", False


# --------------------------------------------------------------------------- #
# Janela móvel
# --------------------------------------------------------------------------- #
def subtrair_meses(d: date, meses: int) -> date:
    """Recua ``meses`` a partir de ``d``, tratando estouro de dia.

    31/08 menos 6 meses vira 28/02 (ou 29/02 em ano bissexto), não uma data
    inválida.
    """
    ano = d.year
    mes = d.month - meses
    while mes <= 0:
        mes += 12
        ano -= 1
    dia = d.day
    while True:
        try:
            return date(ano, mes, dia)
        except ValueError:
            dia -= 1


# --------------------------------------------------------------------------- #
# Preparo dos lançamentos
# --------------------------------------------------------------------------- #
def _normalizar_coluna(nome: str) -> str:
    """``"CAIXAS[REVENDA]"`` ou ``"[REVENDA]"`` -> ``"REVENDA"``."""
    texto = str(nome)
    if "[" in texto and texto.endswith("]"):
        return texto[texto.index("[") + 1 : -1]
    return texto.strip("[]")


def _caixa_sinalizado(revenda: str, caixa: str, cfg: dict[str, Any]) -> bool:
    """Se o caixa é um dos que não representam saldo real.

    Eles **entram** na análise do COAF (decisão do gestor: concentram 46% do
    volume movimentado e vários recebimentos acima do limiar), mas saem
    marcados para o compliance avaliar caso a caso.
    """
    sinal = cfg.get("caixas_sinalizados", {})
    if str(caixa) in [str(c) for c in sinal.get("global", [])]:
        return True
    por_revenda = sinal.get("por_revenda", {}) or {}
    return str(caixa) in [str(c) for c in por_revenda.get(revenda, [])]


def preparar_lancamentos(
    df: pd.DataFrame, cfg: dict[str, Any], hoje: date | None = None
) -> pd.DataFrame:
    """Normaliza o resultado do Power BI e enriquece com o que a detecção precisa.

    Faz a higiene de dados documentada em ``regras_negocio.md``: descarta datas
    futuras (a base tem lançamentos com ``DATA`` até 2041) e valores não
    positivos, que não são recebimento efetivo.

    Args:
        df: Resultado bruto de ``PowerBIClient.execute_dax``.
        cfg: Configuração do COAF.
        hoje: Data de referência para o corte de data futura.

    Returns:
        DataFrame com colunas normalizadas mais ``NOME_CLIENTE``,
        ``CHAVE_CLIENTE``, ``NOME_IDENTIFICADO``, ``CAIXA_SINALIZADO`` e
        ``HASH_LANCAMENTO``. Vazio se nada sobreviver à higiene.
    """
    hoje = hoje or date.today()
    if df.empty:
        return df
    df = df.rename(columns=_normalizar_coluna).copy()
    df["DATA"] = pd.to_datetime(df["DATA"], errors="coerce").dt.date
    df["VALOR"] = pd.to_numeric(df["VALOR"], errors="coerce")

    antes = len(df)
    df = df[df["DATA"].notna() & df["VALOR"].notna()]
    df = df[df["DATA"] <= hoje]
    df = df[df["VALOR"] > 0]
    descartados = antes - len(df)
    if descartados:
        logger.info(
            "Higiene: %d lançamento(s) descartado(s) (data futura, data/valor "
            "inválido ou valor não positivo).",
            descartados,
        )
    if df.empty:
        return df

    textuais = (
        "EMPRESA", "RAZAO_SOCIAL", "REVENDA", "CAIXA", "ORIGEM", "TITULO",
        "HISTORICO", "NOME_USUARIO", "CLIENTE", "FISJUR", "CPF_CNPJ", "NOME_CLIENTE",
    )
    for coluna in textuais:
        if coluna in df.columns:
            df[coluna] = df[coluna].fillna("").astype(str)
        else:
            # Tolera modelo antigo, sem as colunas de 19/08/2026: a DMF sai com
            # os campos em branco em vez de o job quebrar.
            df[coluna] = ""

    # Nome resolvido POR LANÇAMENTO — só informação de exibição (DMF,
    # e-mail), NÃO é mais a chave de identidade (ver chave_do_cliente, que
    # usa CAIXAS[CLIENTE] desde 26/08/2026). Fonte primária: NOME_CLIENTE
    # (cadastro do Power BI); fallback: parser de HISTORICO
    # (extrair_nome_cliente), usado só quando NOME_CLIENTE vem em branco.
    # Como o nome não afeta mais a chave, uma correção de cadastro no meio do
    # caminho (o que motivou a troca — ver dictionary/regras_negocio.md) só
    # muda o texto exibido, não gera mais reenvio indevido.
    #
    # Pode ficar vazio em algum lançamento pontual (ex.: SAQUE sem
    # "Cliente:" no HISTORICO e, hipoteticamente, sem NOME_CLIENTE); nesse
    # caso o nome de exibição do caso vem de outro lançamento do MESMO
    # código dentro do grupo — ver a agregação em :func:`detectar`
    # (:func:`resolver_nome_do_grupo`). Não precisa de backfill aqui: agrupar
    # por código já une naturalmente os lançamentos com e sem nome.
    nomes_coluna = df["NOME_CLIENTE"].str.strip()
    nomes_historico = df["HISTORICO"].map(extrair_nome_cliente)
    df["NOME_CLIENTE"] = [nc or nh or "" for nc, nh in zip(nomes_coluna, nomes_historico)]
    df["NOME_IDENTIFICADO"] = df["NOME_CLIENTE"] != ""
    df["CHAVE_CLIENTE"] = [chave_do_cliente(c) for c in df["CLIENTE"]]

    df["CAIXA_SINALIZADO"] = [
        _caixa_sinalizado(r, c, cfg) for r, c in zip(df["REVENDA"], df["CAIXA"])
    ]
    df["HASH_LANCAMENTO"] = [
        estado.hash_lancamento(r, c, d, t, v, o)
        for r, c, d, t, v, o in zip(
            df["REVENDA"], df["CAIXA"], df["DATA"], df["TITULO"], df["VALOR"], df["ORIGEM"]
        )
    ]
    return df.sort_values("DATA").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# Detecção
# --------------------------------------------------------------------------- #
def intervalo_da_janela(cfg: dict[str, Any], hoje: date | None = None) -> tuple[date, date]:
    """Intervalo de acumulação: sempre terminando hoje, olhando para trás.

    Decisão do gestor (19/08/2026): a avaliação é feita **a partir da data de
    hoje**, não em janelas que terminam no passado. Acrescenta-se
    ``janela_dias_folga`` ao início como margem de segurança, para não perder
    nada em virada de mês, atraso de digitação ou refresh da base.

    Isso funciona porque o job roda de 30 em 30 minutos: todo cruzamento é
    detectado no dia em que acontece e vai para o histórico permanente, que
    nada apaga. Quando a janela anda e o cliente sai da lista, o registro da
    detecção continua lá.

    Args:
        cfg: Configuração do COAF.
        hoje: Data de referência. ``None`` usa a data atual.

    Returns:
        Tupla ``(inicio, fim)``, ambas inclusive.
    """
    hoje = hoje or date.today()
    inicio = subtrair_meses(hoje, int(cfg["janela_meses"]))
    inicio -= timedelta(days=int(cfg.get("janela_dias_folga", 0)))
    return inicio, hoje


def _documento_do_cliente(lancamentos: "pd.DataFrame") -> tuple[str, str]:
    """Tipo de pessoa e documento do cliente, a partir dos lançamentos.

    Usa o valor predominante: em tese ``Fisjur``/``cpf_cnpj`` são constantes
    por cliente, mas a base é de refresh contínuo e um cadastro corrigido no
    meio do período deixaria linhas divergentes. Predominância evita que uma
    linha velha mande na DMF.
    """
    validos = [
        formatar_documento(doc, tipo)
        for doc, tipo in zip(lancamentos["CPF_CNPJ"], lancamentos["FISJUR"])
    ]
    preenchidos = [par for par in validos if par[1]]
    if preenchidos:
        return max(set(preenchidos), key=preenchidos.count)
    tipos = [t for t, _ in validos if t]
    return (max(set(tipos), key=tipos.count) if tipos else ""), ""


def _razao_social_predominante(lancamentos: "pd.DataFrame") -> str:
    """Razão social da empresa do grupo, escolhida pelo maior valor.

    ``RAZAO_SOCIAL`` não é constante por ``EMPRESA``: KOBE tem nove variações,
    com prefixo numérico de filial (``"1 - LAGE E SCARABELI..."``,
    ``"6 - ..."``). Como a DMF é um documento por empresa, escolhe-se a filial
    que concentra o maior valor no caso.
    """
    if "RAZAO_SOCIAL" not in lancamentos.columns:
        return ""
    validos = lancamentos[lancamentos["RAZAO_SOCIAL"].astype(str).str.strip() != ""]
    if validos.empty:
        return ""
    return str(validos.groupby("RAZAO_SOCIAL")["VALOR"].sum().idxmax())


def lancamento_gatilho(
    lancamentos: "pd.DataFrame", limiar: float
) -> dict[str, Any] | None:
    """O lançamento que levou o acumulado a atingir o limiar.

    Ordena por data e acumula: o gatilho é o primeiro lançamento em que a soma
    corrente alcança ou ultrapassa o limiar. É ele que define **para quem vai a
    cobrança** — o responsável pelo caixa em que foi feito (decisão do gestor,
    19/08/2026).

    **Não é o lançamento mais recente do período.** As duas leituras só divergem
    quando o cliente continua comprando depois de já ter estourado o limite, e é
    aí que a escolha importa: quem recebeu o dinheiro que estourou é quem
    responde. Travado por
    ``tests/test_coaf_especie.py::test_gatilho_e_quem_cruzou_nao_quem_lancou_por_ultimo``.

    Empates de data são desempatados pela ordem em que o Power BI devolveu, que
    o job preserva desde a consulta (``ORDER BY [DATA] ASC``).

    Args:
        lancamentos: Recebimentos de um cliente numa janela.
        limiar: Valor que caracteriza a comunicação ao COAF.

    Returns:
        Dicionário com os dados do lançamento decisivo, ou ``None`` se o
        acumulado nunca chega ao limiar.
    """
    if lancamentos.empty:
        return None
    ordenado = lancamentos.sort_values("DATA", kind="stable")
    acumulado = ordenado["VALOR"].cumsum()
    atingiu = acumulado >= limiar
    if not atingiu.any():
        return None
    linha = ordenado[atingiu].iloc[0]
    posicao = int(atingiu.values.argmax())
    return {
        "usuario": str(linha["NOME_USUARIO"]),
        "data": linha["DATA"],
        "revenda": str(linha["REVENDA"]),
        "caixa": str(linha["CAIXA"]),
        "empresa": str(linha["EMPRESA"]),
        "valor": float(linha["VALOR"]),
        "origem": str(linha["ORIGEM"]),
        "titulo": str(linha["TITULO"]),
        "acumulado_no_gatilho": float(acumulado.iloc[posicao]),
    }


def dividir_por_empresa(caso: dict[str, Any]) -> list[dict[str, Any]]:
    """Quebra um caso do grupo em um sub-caso por empresa.

    A apuração é sempre consolidada no grupo — é assim que fracionamento entre
    lojas é pego. Mas a DMF é um documento por pessoa jurídica: cada empresa
    declara o que recebeu. Esta função produz os sub-casos que viram um PDF
    cada, preservando os campos que o gerador do PDF usa.

    Args:
        caso: Caso devolvido por :func:`detectar`.

    Returns:
        Sub-casos ordenados do maior total para o menor.
    """
    sub_casos: list[dict[str, Any]] = []
    for empresa, grupo in caso["lancamentos"].groupby("EMPRESA", sort=False):
        sub = dict(caso)
        sub["empresa"] = str(empresa)
        sub["lancamentos"] = grupo.sort_values("DATA").reset_index(drop=True)
        sub["total"] = float(grupo["VALOR"].sum())
        sub["qtd_lancamentos"] = int(len(grupo))
        sub["revendas"] = sorted(grupo["REVENDA"].unique())
        sub["caixas"] = sorted(grupo["CAIXA"].unique())
        sub["revenda_principal"] = str(grupo.groupby("REVENDA")["VALOR"].sum().idxmax())
        sub["tem_caixa_sinalizado"] = bool(grupo["CAIXA_SINALIZADO"].any())
        sub["razao_social"] = _razao_social_predominante(grupo)
        sub["por_empresa"] = {str(empresa): sub["total"]}
        novos = caso.get("lancamentos_novos")
        if novos is not None:
            sub["lancamentos_novos"] = novos[novos["EMPRESA"] == empresa].reset_index(
                drop=True
            )
            sub["incremento"] = float(sub["lancamentos_novos"]["VALOR"].sum())
        sub_casos.append(sub)
    return sorted(sub_casos, key=lambda c: c["total"], reverse=True)


def detectar(
    df: pd.DataFrame, cfg: dict[str, Any], hoje: date | None = None
) -> list[dict[str, Any]]:
    """Encontra os clientes que cruzaram o limiar na janela que termina hoje.

    Args:
        df: Lançamentos já preparados por :func:`preparar_lancamentos`.
        cfg: Configuração do COAF.
        hoje: Data de referência da janela. ``None`` usa a data atual.

    Returns:
        Lista de casos, do maior total para o menor. Cada caso traz o resumo do
        cliente, a janela apurada, a quebra por empresa, os lançamentos e o
        lançamento-gatilho.
    """
    if df.empty:
        return []
    limiar = float(cfg["limiar_reais"])
    escopo = str(cfg.get("escopo_alerta", "grupo")).lower()
    inicio, fim = intervalo_da_janela(cfg, hoje)

    na_janela_total = df[(df["DATA"] >= inicio) & (df["DATA"] <= fim)]
    if na_janela_total.empty:
        return []

    colunas_grupo = ["CHAVE_CLIENTE"]
    if escopo == "empresa":
        colunas_grupo = ["EMPRESA", "CHAVE_CLIENTE"]

    casos: list[dict[str, Any]] = []
    for _, na_janela in na_janela_total.groupby(colunas_grupo, sort=False):
        total = float(na_janela["VALOR"].sum())
        if total < limiar:
            continue
        hashes = list(na_janela["HASH_LANCAMENTO"])
        hash_conj = estado.hash_conjunto(hashes)
        chave = str(na_janela["CHAVE_CLIENTE"].iloc[0])
        codigo_cliente = str(na_janela["CLIENTE"].iloc[0])
        nome_cliente, nome_identificado = resolver_nome_do_grupo(na_janela["NOME_CLIENTE"])
        if not nome_identificado:
            nome_cliente = f"(sem nome no histórico — código {codigo_cliente})"
        por_empresa = (
            na_janela.groupby("EMPRESA")["VALOR"].sum().sort_values(ascending=False)
        )
        revendas = sorted(na_janela["REVENDA"].unique())
        casos.append(
            {
                "chave_cliente": chave,
                "nome_cliente": nome_cliente,
                "codigo_cliente": codigo_cliente,
                "nome_identificado": nome_identificado,
                **dict(
                    zip(
                        ("tipo_pessoa", "documento"),
                        _documento_do_cliente(na_janela),
                    )
                ),
                "razao_social": _razao_social_predominante(na_janela),
                "escopo": escopo,
                "empresa": " / ".join(sorted(na_janela["EMPRESA"].unique())),
                "revendas": revendas,
                "revenda_principal": str(
                    na_janela.groupby("REVENDA")["VALOR"].sum().idxmax()
                ),
                "caixas": sorted(na_janela["CAIXA"].unique()),
                "total": total,
                "qtd_lancamentos": int(len(na_janela)),
                "janela_inicio": inicio,
                "janela_fim": fim,
                "tem_caixa_sinalizado": bool(na_janela["CAIXA_SINALIZADO"].any()),
                "hash_lancamentos": hash_conj,
                "por_empresa": por_empresa.to_dict(),
                "lancamentos": na_janela.sort_values("DATA").reset_index(drop=True),
                "gatilho": lancamento_gatilho(na_janela, limiar),
            }
        )
    return sorted(casos, key=lambda c: c["total"], reverse=True)


def enriquecer_com_incremento(
    con, casos: list[dict[str, Any]], escopo: str, limiar: float
) -> None:
    """Marca, em cada caso, o que ainda NÃO foi declarado em DMF enviada.

    Regra do gestor (19/08/2026): depois que um cliente é notificado, o que
    conta para uma nova DMF é **só o dinheiro novo** — os valores já declarados
    não voltam para a conta. Um cliente notificado com R$ 31 mil que recebe
    mais R$ 35 mil tem incremento de R$ 35 mil, não R$ 66 mil.

    Acrescenta a cada caso, no lugar:

    - ``hashes_declarados``: lançamentos já cobertos por uma DMF enviada;
    - ``lancamentos_novos``: os recebimentos ainda não declarados;
    - ``incremento``: a soma deles;
    - ``ja_notificado``: se o cliente já recebeu alguma DMF.

    Args:
        con: Conexão DuckDB.
        casos: Casos devolvidos por :func:`detectar`.
        escopo: ``"grupo"`` ou ``"empresa"``.
        limiar: Valor que caracteriza a comunicação ao COAF.
    """
    declarados = estado.hashes_notificados(con, escopo)
    notificados = estado.clientes_notificados(con, escopo)
    for caso in casos:
        ja = declarados.get(caso["chave_cliente"], set())
        lancamentos = caso["lancamentos"]
        novos = lancamentos[~lancamentos["HASH_LANCAMENTO"].isin(ja)]
        caso["hashes_declarados"] = ja
        caso["lancamentos_novos"] = novos.reset_index(drop=True)
        caso["incremento"] = float(novos["VALOR"].sum())
        caso["ja_notificado"] = caso["chave_cliente"] in notificados
        # Num novo cruzamento, quem responde é quem lançou o valor que fez o
        # INCREMENTO chegar ao limiar — não o gatilho da primeira vez.
        if caso["ja_notificado"]:
            caso["gatilho_incremento"] = lancamento_gatilho(
                caso["lancamentos_novos"], limiar
            )


def gatilho_efetivo(caso: dict[str, Any]) -> dict[str, Any] | None:
    """O lançamento que motiva ESTA cobrança.

    Na estreia é o que cruzou o limiar pela primeira vez; num novo cruzamento é
    o que fez o incremento sozinho chegar ao limiar. É daqui que sai o
    destinatário do e-mail.
    """
    if caso.get("ja_notificado") and caso.get("gatilho_incremento"):
        return caso["gatilho_incremento"]
    return caso.get("gatilho")


def deve_notificar(caso: dict[str, Any], limiar: float) -> bool:
    """Se o caso justifica um e-mail agora.

    Duas situações, e só elas:

    1. **Estreia** — o cliente nunca recebeu DMF e está acima do limiar.
    2. **Novo cruzamento** — o cliente já foi notificado e, *desde então*,
       acumulou sozinho outro tanto igual ao limiar.

    Não existe carência por tempo. A versão anterior tinha uma de 30 dias e ela
    barrava o caso legítimo junto com o ruído: um cliente notificado que
    recebesse mais R$ 35 mil dez dias depois ficava sem aviso. O que segura o
    ruído agora é o próprio limiar do incremento — pingado de R$ 200 não
    dispara nada até somar R$ 30 mil por conta própria.

    Args:
        caso: Caso já passado por :func:`enriquecer_com_incremento`.
        limiar: Valor que caracteriza a comunicação ao COAF.

    Returns:
        ``True`` se deve disparar e-mail.
    """
    if not caso.get("ja_notificado"):
        return True
    return caso.get("incremento", 0.0) >= limiar


def filtrar_clientes_excluidos(
    casos: list[dict[str, Any]], cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    """Retira da lista clientes marcados como excluídos em ``config/coaf.yaml``.

    Decisão do gestor (25/08/2026): alguns clientes (ex.: empresas do próprio
    grupo, contas internas) nunca devem gerar alerta do COAF — nem entram no
    histórico, nem geram PDF, nem são notificados. É diferente de
    ``filtro_cliente`` (a flag ``--cliente`` da CLI): aquele é uma restrição
    manual pontual para teste; este é regra permanente de negócio.

    Casamento por nome usa :func:`normalizar_texto` (maiúsculo, sem acento) —
    não depende de o usuário digitar o nome exatamente como aparece no
    cadastro ou no histórico. Casamento por código usa ``CAIXAS[CLIENTE]``
    como string (o mesmo valor usado por :func:`chave_do_cliente`). Um caso
    cai fora se casar em qualquer um dos dois critérios.

    Args:
        casos: Casos devolvidos por :func:`detectar`.
        cfg: Configuração do COAF, com ``clientes_excluidos.nomes`` e
            ``clientes_excluidos.codigos``.

    Returns:
        Os casos que não casaram com nenhuma exclusão.
    """
    regra = cfg.get("clientes_excluidos") or {}
    nomes_excluidos = {normalizar_texto(n) for n in (regra.get("nomes") or [])}
    codigos_excluidos = {str(c).strip() for c in (regra.get("codigos") or [])}
    if not nomes_excluidos and not codigos_excluidos:
        return casos

    mantidos = []
    excluidos = []
    for caso in casos:
        nome_norm = normalizar_texto(caso["nome_cliente"])
        codigo = str(caso.get("codigo_cliente", "")).strip()
        if nome_norm in nomes_excluidos or codigo in codigos_excluidos:
            excluidos.append(caso["nome_cliente"])
        else:
            mantidos.append(caso)

    if excluidos:
        logger.info(
            "Clientes excluídos da apuração (config/coaf.yaml): %d — %s.",
            len(excluidos),
            ", ".join(excluidos),
        )
    return mantidos


# --------------------------------------------------------------------------- #
# Formatação
# --------------------------------------------------------------------------- #
def fmt_moeda(valor: float) -> str:
    """Formata em reais com centavos: ``1234567.8`` -> ``"1.234.567,80"``.

    A DMF é uma declaração de valores específicos recebidos — diferente dos
    relatórios gerenciais (``design_system_relatorios.md`` §2, que arredonda),
    aqui o centavo importa e é mantido.
    """
    return f"{valor:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_data(d: Any) -> str:
    """Formata uma data como ``DD/MM/AAAA``."""
    if isinstance(d, (date, datetime)):
        return d.strftime("%d/%m/%Y")
    return str(d)


# --------------------------------------------------------------------------- #
# Relatórios
# --------------------------------------------------------------------------- #
def montar_relatorio_execucao(
    casos: list[dict[str, Any]],
    novos: list[dict[str, Any]],
    cfg: dict[str, Any],
    data_inicio: date,
    data_fim: date,
    total_lancamentos: int,
    avisos: list[str],
    janela: tuple[date, date] | None = None,
) -> str:
    """Monta o Markdown da execução atual.

    Cita período, filtro e a natureza do cálculo, como exige o ``CLAUDE.md``.
    """
    limiar = float(cfg["limiar_reais"])
    exc = cfg["exclusoes_origem"]
    chaves_novas = {c["chave_cliente"] for c in novos}
    janela_inicio, janela_fim = janela or intervalo_da_janela(cfg, data_fim)

    linhas = [
        "# Monitoramento COAF — recebimentos em espécie",
        "",
        f"**Gerado em:** {datetime.now():%d/%m/%Y %H:%M}  ",
        f"**Janela de apuração:** {fmt_data(janela_inicio)} a {fmt_data(janela_fim)}"
        f" ({cfg['janela_meses']} meses + {cfg.get('janela_dias_folga', 0)} dias de folga)  ",
        f"**Período consultado no Power BI:** {fmt_data(data_inicio)} a {fmt_data(data_fim)}"
        " (histórico maior que a janela, para consulta)  ",
        f"**Limiar:** R$ {fmt_moeda(limiar)}  ",
        f"**Escopo do alerta:** {cfg.get('escopo_alerta', 'grupo')}  ",
        f"**Filtro aplicado:** `PAGAR_RECEBER = \"R\"`, excluindo origens que "
        f"contêm {', '.join(f'`{p}`' for p in exc['padroes'])}"
        + (
            f", caixa(s) `{', '.join(cfg['caixas_excluidos']['global'])}` "
            "(qualquer revenda)"
            if cfg.get("caixas_excluidos", {}).get("global")
            else ""
        )
        + "  ",
        f"**Lançamentos analisados:** {total_lancamentos}",
        "",
        "> Os valores abaixo **não são medida oficial** do modelo semântico — o "
        "dataset `lancamentos_financeiros` não possui medidas. São calculados "
        "por `analysis/coaf_especie.py` a partir de `CAIXAS[VALOR]`.",
        "",
        "## Resumo",
        "",
        f"- Clientes acima do limiar: **{len(casos)}**",
        f"- Casos novos ou com movimentação nova nesta execução: **{len(novos)}**",
        "",
    ]

    if not casos:
        linhas += ["Nenhum cliente atingiu o limiar no período.", ""]
    else:
        linhas += [
            "## Clientes acima do limiar",
            "",
            "| # | Cliente | Empresa | Revenda(s) | Janela | Lanç. | Total (R$) | Situação |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for i, caso in enumerate(casos, 1):
            marcas = []
            if caso["chave_cliente"] in chaves_novas:
                marcas.append("**NOVO**")
            if not caso["nome_identificado"]:
                marcas.append("⚠ sem nome")
            if caso["tem_caixa_sinalizado"]:
                marcas.append("⚑ caixa sinalizado")
            linhas.append(
                f"| {i} | {caso['nome_cliente']} | {caso['empresa']} | "
                f"{', '.join(caso['revendas'])} | "
                f"{fmt_data(caso['janela_inicio'])}–{fmt_data(caso['janela_fim'])} | "
                f"{caso['qtd_lancamentos']} | {fmt_moeda(caso['total'])} | "
                f"{' · '.join(marcas) if marcas else 'em acompanhamento'} |"
            )
        linhas.append("")

        linhas += ["## Quebra por empresa", "", "| Cliente | Empresa | Valor (R$) |", "|---|---|---|"]
        for caso in casos:
            for empresa, valor in caso["por_empresa"].items():
                linhas.append(f"| {caso['nome_cliente']} | {empresa} | {fmt_moeda(valor)} |")
        linhas.append("")

    if avisos:
        linhas += ["## Avisos", ""] + [f"- {a}" for a in avisos] + [""]

    linhas += [
        "---",
        "",
        "Fonte: dataset `lancamentos_financeiros` (tabela `CAIXAS`) · "
        "Cálculo próprio, não é medida oficial · Uso interno de compliance.",
    ]
    return "\n".join(linhas)


def montar_relatorio_historico(hist: pd.DataFrame) -> str:
    """Monta o Markdown do histórico acumulado.

    Este relatório é a garantia de que nenhum cliente já detectado se perde:
    ele é regerado inteiro a cada execução a partir de ``coaf_deteccao``, que é
    append-only. Cliente já notificado continua aqui, com a data do envio.
    """
    linhas = [
        "# Histórico COAF — todos os clientes já detectados",
        "",
        f"**Atualizado em:** {datetime.now():%d/%m/%Y %H:%M}  ",
        f"**Clientes no histórico:** {len(hist)}",
        "",
        "> Registro **permanente e cumulativo**. Nenhuma linha é removida quando "
        "o cliente é notificado — a coluna *Notificado em* mostra o envio.",
        "",
    ]
    if hist.empty:
        linhas += ["Ainda não há detecções registradas.", ""]
        return "\n".join(linhas)

    linhas += [
        "| Cliente | Código | Empresa | Revenda(s) | 1ª detecção | Última | Vezes | Maior total (R$) | Notificado em |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for _, r in hist.iterrows():
        notificado = (
            f"{r['notificado_em']:%d/%m/%Y %H:%M}"
            if pd.notna(r["notificado_em"])
            else "—"
        )
        marca = "" if r["nome_identificado"] else " ⚠"
        sinal = " ⚑" if r["tem_caixa_sinalizado"] else ""
        linhas.append(
            f"| {r['nome_cliente']}{marca}{sinal} | {r['codigo_cliente']} | "
            f"{r['empresa']} | {r['revendas']} | "
            f"{r['primeira_deteccao_em']:%d/%m/%Y %H:%M} | "
            f"{r['ultima_deteccao_em']:%d/%m/%Y %H:%M} | {r['vezes_detectado']} | "
            f"{fmt_moeda(float(r['maior_total']))} | {notificado} |"
        )
    linhas += [
        "",
        "Legenda: ⚠ nome não identificado no histórico do lançamento · "
        "⚑ envolve caixa que não representa saldo real (9/99/4, ou 8/14 na Multicar Mits).",
    ]
    return "\n".join(linhas)


# --------------------------------------------------------------------------- #
# Persistência da execução
# --------------------------------------------------------------------------- #
def persistir(con, casos: list[dict[str, Any]], escopo: str) -> list[dict[str, Any]]:
    """Grava as detecções no histórico e devolve as que são novidade.

    Uma detecção é gravada quando é a estreia do cliente, quando o conjunto de
    lançamentos mudou, ou quando ainda não houve registro idêntico hoje. Este
    último caso evita 24 linhas idênticas por dia sem sacrificar o histórico.

    Args:
        con: Conexão DuckDB em escrita.
        casos: Casos devolvidos por :func:`detectar`.
        escopo: ``"grupo"`` ou ``"empresa"``.

    Returns:
        Os casos que representam novidade (estreia ou movimentação nova) — são
        os candidatos a notificação.
    """
    ja_detectados = estado.clientes_ja_detectados(con, escopo)
    hashes_anteriores = estado.hashes_por_cliente(con, escopo)
    gravados_hoje = estado.detectado_hoje(con, escopo)
    agora = datetime.now()

    novos: list[dict[str, Any]] = []
    for caso in casos:
        chave = caso["chave_cliente"]
        primeira = chave not in ja_detectados
        mudou = hashes_anteriores.get(chave) != caso["hash_lancamentos"]
        ja_hoje = (chave, caso["hash_lancamentos"]) in gravados_hoje

        # O id é determinístico, então pode ser resolvido antes de decidir se
        # grava: quem usa --forcar-envio precisa dele mesmo nos casos pulados.
        id_det = estado.id_deteccao(chave, escopo, caso["hash_lancamentos"])
        caso["id_deteccao"] = id_det
        caso["primeira_deteccao"] = primeira

        if not primeira and not mudou and ja_hoje:
            continue  # nada mudou e o dia já está registrado
        estado.gravar_deteccao(
            con,
            {
                "id_deteccao": id_det,
                "detectado_em": agora,
                "chave_cliente": chave,
                "nome_cliente": caso["nome_cliente"],
                "codigo_cliente": caso["codigo_cliente"],
                "nome_identificado": caso["nome_identificado"],
                "escopo": escopo,
                "empresa": caso["empresa"],
                "revendas": "; ".join(caso["revendas"]),
                "caixas": "; ".join(caso["caixas"]),
                "total": caso["total"],
                "qtd_lancamentos": caso["qtd_lancamentos"],
                "janela_inicio": caso["janela_inicio"],
                "janela_fim": caso["janela_fim"],
                "tem_caixa_sinalizado": caso["tem_caixa_sinalizado"],
                "hash_lancamentos": caso["hash_lancamentos"],
                "primeira_deteccao": primeira,
            },
            [
                {
                    "hash_lancamento": r["HASH_LANCAMENTO"],
                    "data": r["DATA"],
                    "empresa": r["EMPRESA"],
                    "revenda": r["REVENDA"],
                    "caixa": r["CAIXA"],
                    "origem": r["ORIGEM"],
                    "titulo": r["TITULO"],
                    "valor": float(r["VALOR"]),
                    "historico": r["HISTORICO"],
                    "nome_usuario": r["NOME_USUARIO"],
                    "caixa_sinalizado": bool(r["CAIXA_SINALIZADO"]),
                }
                for _, r in caso["lancamentos"].iterrows()
            ],
        )
        if primeira or mudou:
            novos.append(caso)
    return novos


# --------------------------------------------------------------------------- #
# Orquestração
# --------------------------------------------------------------------------- #
def _configurar_log() -> None:
    """Liga o log em arquivo mensal e no stdout.

    O projeto até aqui só usava ``print()``; um job agendado precisa deixar
    rastro para quando ninguém estiver olhando.
    """
    # O console do Windows roda em cp1252 e quebra em emoji/acento — sem isto,
    # o job morre no print final com UnicodeEncodeError.
    for fluxo in (sys.stdout, sys.stderr):
        if hasattr(fluxo, "reconfigure"):
            fluxo.reconfigure(encoding="utf-8", errors="replace")

    PASTA_LOGS.mkdir(parents=True, exist_ok=True)
    arquivo = PASTA_LOGS / f"coaf_{date.today():%Y-%m}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(arquivo, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def executar(
    enviar: bool = False,
    cliente: PowerBIClient | None = None,
    config: Configuracao | None = None,
    dataset: str | None = DATASET_PADRAO,
    forcar_envio: bool = False,
    filtro_cliente: str | None = None,
) -> dict[str, Any]:
    """Roda o ciclo completo: consulta, detecta, persiste, gera PDF e notifica.

    Args:
        enviar: Se ``False`` (padrão), gera tudo mas não dispara e-mail —
            é o modo revisão pedido pelo gestor.
        cliente: Cliente Power BI já autenticado.
        config: Configuração do projeto.
        dataset: Apelido ou GUID do dataset de caixa.
        forcar_envio: Notifica **todos** os casos acima do limiar, e não só os
            que a regra de incremento selecionaria. Serve para reenviar tudo
            depois de corrigir o mapa de responsáveis, ou para validar o fluxo
            de envio ponta a ponta. Não altera o histórico.
        filtro_cliente: Restringe a execução aos clientes cujo nome contenha
            este trecho (sem diferenciar maiúsculas ou acento). Serve para
            testar um caso isolado sem disparar a lista inteira.

    Returns:
        Dicionário com contagens e caminhos dos artefatos gerados.
    """
    cfg = carregar_config_coaf()
    destinatarios = carregar_destinatarios()
    config = config or carregar_configuracao()
    cliente = cliente or PowerBIClient(config=config)

    hoje = date.today()
    data_inicio = subtrair_meses(hoje, int(cfg["meses_consulta"]))
    exc = cfg["exclusoes_origem"]
    caixas_excluidos = cfg["caixas_excluidos"]["global"]

    logger.info(
        "Consultando recebimentos de %s a %s (dataset %s).",
        data_inicio,
        hoje,
        dataset,
    )
    query = dax_coaf.recebimentos_especie(
        data_inicio, hoje, exc["padroes"], exc["exatas"], caixas_excluidos
    )
    bruto = cliente.execute_dax(query, dataset_id=dataset)
    df = preparar_lancamentos(bruto, cfg, hoje)
    logger.info("Lançamentos válidos após higiene: %d.", len(df))

    janela = intervalo_da_janela(cfg, hoje)
    casos = detectar(df, cfg, hoje)
    escopo = str(cfg.get("escopo_alerta", "grupo")).lower()
    logger.info("Janela de apuração: %s a %s.", janela[0], janela[1])

    casos = filtrar_clientes_excluidos(casos, cfg)

    if filtro_cliente:
        alvo_norm = normalizar_texto(filtro_cliente)
        antes = len(casos)
        casos = [c for c in casos if alvo_norm in normalizar_texto(c["nome_cliente"])]
        logger.info(
            "Filtro de cliente %r: %d de %d caso(s) selecionado(s).",
            filtro_cliente,
            len(casos),
            antes,
        )
    logger.info("Clientes acima do limiar: %d.", len(casos))

    avisos: list[str] = []
    sem_nome = [c for c in casos if not c["nome_identificado"]]
    if sem_nome:
        avisos.append(
            f"{len(sem_nome)} caso(s) sem nome de cliente no histórico — a DMF "
            "sai com o campo 1 em branco e precisa ser completada à mão."
        )

    con = estado.abrir()
    try:
        novos = persistir(con, casos, escopo)
        logger.info("Detecções novas ou alteradas: %d.", len(novos))

        # Quanto cada cliente recebeu DESDE a última DMF enviada. É isso que
        # decide o reenvio — o valor já declarado não volta para a conta.
        limiar = float(cfg["limiar_reais"])
        enriquecer_com_incremento(con, casos, escopo, limiar)

        # Import tardio: só faz falta quando há caso. dmf_html segue o design
        # system em design_system/coaf-alerta-30-mil/ (regra definida pelo
        # usuário em 21/08/2026) — substitui dmf_pdf.py (reportlab), mantido
        # no repositório mas não mais chamado daqui.
        from analysis.dmf_html import (
            gerar_dmf,
            gerar_dmf_complementar,
            gerar_relatorio_consolidado,
        )

        PASTA_DMF.mkdir(parents=True, exist_ok=True)

        # Decide QUEM notificar antes de gerar qualquer PDF. A ordem importa:
        # cada DMF custa uma execução do Chrome headless (~2-5s, às vezes
        # muito mais sob antivírus), e o job roda de 30 em 30 minutos com,
        # tipicamente, ZERO casos a notificar. Gerar PDF de todo caso acima do
        # limiar a cada rodada significava 30+ execuções do Chrome por rodada
        # cujo resultado era descartado — foi o que estourou o timeout de
        # impressão em produção (31/08/2026) e derrubou o job.
        if forcar_envio:
            alvos = casos
            logger.info(
                "--forcar-envio: notificando os %d casos acima do limiar, "
                "ignorando a regra de incremento.",
                len(casos),
            )
        else:
            alvos = [c for c in casos if deve_notificar(c, limiar)]
            estreias = sum(1 for c in alvos if not c["ja_notificado"])
            logger.info(
                "A notificar: %d (%d estreia(s), %d novo(s) cruzamento(s) de "
                "R$ %s desde a última DMF).",
                len(alvos),
                estreias,
                len(alvos) - estreias,
                fmt_moeda(limiar),
            )

        # A apuração é do grupo, mas a DMF é um documento por pessoa jurídica:
        # cada empresa declara o que recebeu. O consolidado (só para o COAF)
        # recompõe a visão de grupo por cima disso.
        anexos_por_caso: dict[str, dict[str, Any]] = {}
        for caso in alvos:
            dmfs = [
                gerar_dmf(sub, destinatarios, PASTA_DMF)
                for sub in dividir_por_empresa(caso)
            ]
            consolidado = gerar_relatorio_consolidado(caso, PASTA_DMF)
            complementar = None
            if caso["ja_notificado"] and not caso["lancamentos_novos"].empty:
                complementar = gerar_dmf_complementar(caso, destinatarios, PASTA_DMF)
            anexos_por_caso[caso["chave_cliente"]] = {
                "empresas": dmfs,
                "consolidado": consolidado,
                "complementar": complementar,
            }
            logger.info(
                "Documentos gerados para %s: %d DMF(s) por empresa + consolidado%s.",
                caso["nome_cliente"],
                len(dmfs),
                " + complementar" if complementar else "",
            )

        from notify.email_zoho import notificar_casos  # import tardio

        resultado_envio = notificar_casos(
            con=con,
            casos=alvos,
            anexos_por_caso=anexos_por_caso,
            destinatarios=destinatarios,
            cfg=cfg,
            config=config,
            escopo=escopo,
            enviar=enviar,
        )
        avisos.extend(resultado_envio["avisos"])

        hist = estado.carregar_historico(con, escopo)
    finally:
        con.close()

    PASTA_REPORTS.mkdir(parents=True, exist_ok=True)
    caminho_exec = PASTA_REPORTS / f"coaf_especie_{hoje:%Y-%m-%d}.md"
    caminho_exec.write_text(
        montar_relatorio_execucao(
            casos, novos, cfg, data_inicio, hoje, len(df), avisos, janela
        ),
        encoding="utf-8",
    )
    caminho_hist = PASTA_REPORTS / "coaf_historico.md"
    caminho_hist.write_text(montar_relatorio_historico(hist), encoding="utf-8")

    return {
        "casos": len(casos),
        "novos": len(novos),
        "enviados": resultado_envio["enviados"],
        "suprimidos": resultado_envio["suprimidos"],
        "relatorio": caminho_exec,
        "historico": caminho_hist,
        "pdfs": [
            caminho
            for anexos in anexos_por_caso.values()
            for caminho in anexos["empresas"]
        ],
        "avisos": avisos,
    }


def exportar_historico(csv: bool = False) -> Path:
    """Regera o relatório de histórico a partir do DuckDB, sem consultar o Power BI.

    Args:
        csv: Se ``True``, também exporta ``reports/coaf_historico.csv``.

    Returns:
        Caminho do arquivo Markdown gerado.
    """
    cfg = carregar_config_coaf()
    escopo = str(cfg.get("escopo_alerta", "grupo")).lower()
    con = estado.abrir()
    try:
        hist = estado.carregar_historico(con, escopo)
    finally:
        con.close()

    PASTA_REPORTS.mkdir(parents=True, exist_ok=True)
    caminho = PASTA_REPORTS / "coaf_historico.md"
    caminho.write_text(montar_relatorio_historico(hist), encoding="utf-8")
    if csv:
        destino_csv = PASTA_REPORTS / "coaf_historico.csv"
        hist.to_csv(destino_csv, index=False, encoding="utf-8-sig", sep=";")
        logger.info("Histórico exportado para %s", destino_csv)
    return caminho


def main() -> int:
    """CLI do monitoramento COAF. Devolve 0 em sucesso, 1 em falha."""
    parser = argparse.ArgumentParser(
        description="Monitoramento COAF de recebimentos em espécie."
    )
    parser.add_argument(
        "--enviar",
        action="store_true",
        help="Dispara os e-mails de verdade. Sem esta flag, roda em modo "
        "revisão: gera alertas e PDFs, mas não envia nada.",
    )
    parser.add_argument(
        "--cliente",
        metavar="TRECHO",
        help="Restringe a execução aos clientes cujo nome contenha este trecho. "
        "Útil para testar um caso isolado sem disparar a lista inteira.",
    )
    parser.add_argument(
        "--forcar-envio",
        action="store_true",
        help="Notifica TODOS os casos acima do limiar, não só os novos, "
        "ignorando a carência de reenvio. Combine com --enviar para disparar "
        "de verdade. Não altera o histórico.",
    )
    parser.add_argument(
        "--historico",
        action="store_true",
        help="Só regera o relatório de histórico a partir do banco local, "
        "sem consultar o Power BI.",
    )
    parser.add_argument(
        "--csv",
        action="store_true",
        help="Junto com --historico, também exporta reports/coaf_historico.csv.",
    )
    parser.add_argument(
        "--dataset",
        default=DATASET_PADRAO,
        help=f"Apelido ou GUID do dataset (padrão: {DATASET_PADRAO}).",
    )
    args = parser.parse_args()

    _configurar_log()

    if args.historico:
        caminho = exportar_historico(csv=args.csv)
        print(f"✅ Histórico atualizado: {caminho}")
        return 0

    try:
        resultado = executar(
            enviar=args.enviar,
            dataset=args.dataset,
            forcar_envio=args.forcar_envio,
            filtro_cliente=args.cliente,
        )
    except ErroConfiguracao as exc:
        logger.error("Configuração incompleta: %s", exc)
        print(f"❌ Configuração incompleta:\n{exc}")
        print("RESUMO_MAQUINA: erro=1 enviados=0 avisos=0")
        return 1
    except ErroPowerBI as exc:
        logger.error("Erro ao consultar o Power BI: %s", exc)
        print(
            f"❌ Erro ao consultar o Power BI:\n{exc}\n\n"
            "Se for token expirado, rode: "
            ".venv/Scripts/python.exe scripts/validar_setup.py"
        )
        print("RESUMO_MAQUINA: erro=1 enviados=0 avisos=0")
        return 1

    modo = "ENVIO" if args.enviar else "REVISÃO (nada enviado)"
    print(
        f"✅ COAF [{modo}] — {resultado['casos']} cliente(s) acima do limiar, "
        f"{resultado['novos']} novo(s), {resultado['enviados']} e-mail(s) enviado(s).\n"
        f"   Relatório: {resultado['relatorio']}\n"
        f"   Histórico: {resultado['historico']}"
    )
    for aviso in resultado["avisos"]:
        print(f"   ⚠ {aviso}")
    # Linha só em ASCII, para o wrapper do agendador (coaf_job_notificar.ps1)
    # decidir se mostra notificação sem depender de casar emoji/acento em
    # texto capturado de um processo filho — a codificação da captura via
    # pipe do PowerShell nem sempre preserva UTF-8 corretamente.
    print(
        f"RESUMO_MAQUINA: erro=0 enviados={resultado['enviados']} "
        f"avisos={len(resultado['avisos'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
