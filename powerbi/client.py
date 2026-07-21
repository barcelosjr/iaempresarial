"""Cliente da API REST do Power BI — SOMENTE LEITURA.

Expõe :class:`PowerBIClient`, que executa consultas DAX no servidor do Power BI
(endpoint ``executeQueries``) e devolve apenas os resultados (agregados/recortes)
como ``pandas.DataFrame``. Os dados brutos permanecem no Power BI.

Recursos de robustez:

* **Rate limit local** configurável (padrão conservador de 30 req/min).
* **Retry com backoff exponencial** em erros transitórios (429/5xx),
  respeitando o cabeçalho ``Retry-After`` quando presente.
* **Erros traduzidos** para português, indicando a causa provável.
"""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import yaml

from auth.azure_auth import AzureAuthenticator
from config.settings import RAIZ_PROJETO, Configuracao, carregar_configuracao

# URL base da API do Power BI.
_BASE_URL = "https://api.powerbi.com/v1.0/myorg"

# Tempo (segundos) máximo de espera entre tentativas, para não travar demais.
_BACKOFF_MAX_SEGUNDOS = 60.0


class ErroPowerBI(Exception):
    """Erro ao chamar a API do Power BI, com causa provável em português."""


class _LimitadorTaxa:
    """Limitador local de requisições por minuto (janela deslizante).

    Bloqueia (dorme) o tempo necessário para não ultrapassar ``max_por_minuto``
    requisições em qualquer janela de 60 segundos.
    """

    def __init__(self, max_por_minuto: int) -> None:
        self._max = max(1, int(max_por_minuto))
        self._marcas: deque[float] = deque()

    def aguardar_vaga(self) -> None:
        """Bloqueia até que haja "vaga" para uma nova requisição."""
        agora = time.monotonic()
        # Remove marcas com mais de 60s.
        while self._marcas and agora - self._marcas[0] >= 60.0:
            self._marcas.popleft()
        if len(self._marcas) >= self._max:
            espera = 60.0 - (agora - self._marcas[0])
            if espera > 0:
                time.sleep(espera)
            # Reavalia após dormir.
            return self.aguardar_vaga()
        self._marcas.append(time.monotonic())


class PowerBIClient:
    """Cliente somente leitura para a API REST do Power BI."""

    def __init__(
        self,
        config: Configuracao | None = None,
        autenticador: AzureAuthenticator | None = None,
        sessao: requests.Session | None = None,
    ) -> None:
        """Inicializa o cliente.

        Args:
            config: Configuração carregada. Se omitida, lê do ``.env``.
            autenticador: Autenticador Azure. Se omitido, cria um novo.
            sessao: Sessão ``requests`` (útil para testes). Se omitida, cria uma.
        """
        self._config = config or carregar_configuracao()
        self._auth = autenticador or AzureAuthenticator(self._config)
        self._sessao = sessao or requests.Session()
        self._limitador = _LimitadorTaxa(self._config.rate_limit_por_minuto)
        self._datasets_apelidos: dict[str, dict[str, str]] | None = None

    # ------------------------------------------------------------------ #
    # Resolução de workspace/dataset (por apelido ou GUID)
    # ------------------------------------------------------------------ #
    def _carregar_apelidos(self) -> dict[str, dict[str, str]]:
        """Carrega o mapa de apelidos de ``config/datasets.yaml`` (cacheado)."""
        if self._datasets_apelidos is not None:
            return self._datasets_apelidos
        caminho: Path = RAIZ_PROJETO / "config" / "datasets.yaml"
        mapa: dict[str, dict[str, str]] = {}
        if caminho.exists():
            try:
                dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
                for apelido, info in (dados.get("datasets") or {}).items():
                    if info and info.get("dataset_id"):
                        mapa[apelido] = info
            except yaml.YAMLError:
                mapa = {}
        self._datasets_apelidos = mapa
        return mapa

    def _resolver_alvo(self, dataset: str | None) -> tuple[str, str]:
        """Resolve (workspace_id, dataset_id) a partir de apelido/GUID/padrão.

        Args:
            dataset: Apelido (ex.: ``"vendas"``), GUID do dataset, ou ``None``
                para usar o padrão do ``.env``/``datasets.yaml``.

        Returns:
            Tupla ``(workspace_id, dataset_id)``.
        """
        apelidos = self._carregar_apelidos()

        if dataset is None:
            # Procura um apelido marcado como padrão; senão usa o .env.
            for info in apelidos.values():
                if info.get("padrao"):
                    return str(info["workspace_id"]), str(info["dataset_id"])
            return self._config.workspace_id, self._config.dataset_id

        if dataset in apelidos:
            info = apelidos[dataset]
            return str(info["workspace_id"]), str(info["dataset_id"])

        # Tratado como GUID de dataset no workspace padrão.
        return self._config.workspace_id, dataset

    # ------------------------------------------------------------------ #
    # Chamada HTTP com retry/backoff/rate limit
    # ------------------------------------------------------------------ #
    def _requisitar(
        self, metodo: str, url: str, *, json_body: dict | None = None
    ) -> requests.Response:
        """Faz uma requisição HTTP com autenticação, rate limit e retry.

        Args:
            metodo: Método HTTP (``GET`` ou ``POST``).
            url: URL completa da API.
            json_body: Corpo JSON (para POST).

        Returns:
            A resposta HTTP bem-sucedida.

        Raises:
            ErroPowerBI: Em erros não recuperáveis, com causa provável.
        """
        ultima_excecao: Exception | None = None
        for tentativa in range(1, self._config.max_retries + 1):
            self._limitador.aguardar_vaga()
            token = self._auth.get_token()
            cabecalhos = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }
            try:
                resposta = self._sessao.request(
                    metodo, url, headers=cabecalhos, json=json_body, timeout=120
                )
            except requests.RequestException as exc:
                ultima_excecao = exc
                self._dormir_backoff(tentativa, None)
                continue

            if resposta.status_code < 400:
                return resposta

            # Erros transitórios: tenta de novo.
            if resposta.status_code == 429 or resposta.status_code >= 500:
                ultima_excecao = ErroPowerBI(self._traduzir_erro(resposta))
                if tentativa < self._config.max_retries:
                    retry_after = resposta.headers.get("Retry-After")
                    self._dormir_backoff(tentativa, retry_after)
                    continue

            # Erros definitivos (401, 403, 404, 400, etc.).
            raise ErroPowerBI(self._traduzir_erro(resposta))

        raise ErroPowerBI(
            "Falha ao contatar a API do Power BI após "
            f"{self._config.max_retries} tentativas. "
            f"Último erro: {ultima_excecao}"
        )

    def _dormir_backoff(self, tentativa: int, retry_after: str | None) -> None:
        """Dorme com backoff exponencial (ou conforme ``Retry-After``)."""
        if retry_after:
            try:
                time.sleep(min(float(retry_after), _BACKOFF_MAX_SEGUNDOS))
                return
            except (TypeError, ValueError):
                pass
        espera = min(2.0 ** tentativa, _BACKOFF_MAX_SEGUNDOS)
        time.sleep(espera)

    @staticmethod
    def _traduzir_erro(resposta: requests.Response) -> str:
        """Traduz um erro HTTP da API em mensagem clara em português."""
        status = resposta.status_code
        try:
            corpo = resposta.json()
        except ValueError:
            corpo = {}
        detalhe = ""
        if isinstance(corpo, dict):
            erro = corpo.get("error", {})
            if isinstance(erro, dict):
                detalhe = erro.get("message") or erro.get("code") or ""
            elif isinstance(erro, str):
                detalhe = erro

        causas = {
            401: (
                "Token inválido ou expirado (401). Refaça a autenticação: "
                "`python scripts/validar_setup.py`."
            ),
            403: (
                "Permissão negada (403). Causas prováveis: falta de permissão "
                "Read+Build no dataset; a configuração de tenant 'Dataset Execute "
                "Queries REST API' está desabilitada; ou (service principal) a opção "
                "'Allow service principals to use Power BI APIs' está desligada."
            ),
            404: (
                "Recurso não encontrado (404). Confira PBI_WORKSPACE_ID e "
                "PBI_DATASET_ID — o dataset pode não existir ou você não tem acesso."
            ),
            400: (
                "Requisição inválida (400). Provável erro na sintaxe da consulta "
                "DAX ou no corpo da requisição."
            ),
            429: (
                "Limite de requisições atingido no servidor (429). "
                "O cliente aguardará e tentará novamente automaticamente."
            ),
        }
        base = causas.get(status)
        if base is None:
            if status >= 500:
                base = (
                    f"Erro no servidor do Power BI ({status}). Problema temporário — "
                    "o cliente tentará novamente."
                )
            else:
                base = f"Erro inesperado da API do Power BI ({status})."
        if detalhe:
            return f"{base}\nDetalhe da API: {detalhe}"
        return base

    # ------------------------------------------------------------------ #
    # Operações públicas (somente leitura)
    # ------------------------------------------------------------------ #
    def execute_dax(self, query: str, dataset_id: str | None = None) -> pd.DataFrame:
        """Executa uma consulta DAX no servidor e devolve o resultado.

        A consulta roda no Power BI; apenas o resultado (já agregado/filtrado)
        retorna. Nenhum dado é gravado.

        Args:
            query: Consulta DAX (deve começar com ``EVALUATE`` / ``DEFINE``).
            dataset_id: Apelido, GUID do dataset ou ``None`` para o padrão.

        Returns:
            ``pandas.DataFrame`` com o resultado. Vazio se a consulta não
            retornar linhas.

        Raises:
            ErroPowerBI: Em falhas da API ou erro reportado na própria consulta.
        """
        workspace_id, dataset = self._resolver_alvo(dataset_id)
        url = (
            f"{_BASE_URL}/groups/{workspace_id}/datasets/{dataset}/executeQueries"
        )
        corpo = {
            "queries": [{"query": query}],
            "serializerSettings": {"includeNulls": True},
        }
        resposta = self._requisitar("POST", url, json_body=corpo)
        return self._resposta_para_dataframe(resposta.json())

    @staticmethod
    def _resposta_para_dataframe(payload: dict[str, Any]) -> pd.DataFrame:
        """Converte o JSON do ``executeQueries`` em ``DataFrame``.

        Args:
            payload: Corpo JSON da resposta da API.

        Returns:
            ``DataFrame`` com as linhas retornadas (colunas no formato do DAX,
            ex.: ``Tabela[Coluna]`` ou ``[Medida]``).

        Raises:
            ErroPowerBI: Se a resposta contiver um erro por consulta.
        """
        resultados = payload.get("results", [])
        if not resultados:
            return pd.DataFrame()

        primeiro = resultados[0]
        if "error" in primeiro and primeiro["error"]:
            erro = primeiro["error"]
            msg = erro.get("message") if isinstance(erro, dict) else str(erro)
            raise ErroPowerBI(f"A consulta DAX retornou erro: {msg}")

        tabelas = primeiro.get("tables", [])
        if not tabelas:
            return pd.DataFrame()

        linhas = tabelas[0].get("rows", [])
        return pd.DataFrame(linhas)

    def list_datasets(self) -> pd.DataFrame:
        """Lista os datasets do workspace padrão.

        Returns:
            ``DataFrame`` com colunas como ``id``, ``name`` e
            ``configuredBy`` (conforme retornado pela API).

        Raises:
            ErroPowerBI: Em caso de falha na API.
        """
        url = f"{_BASE_URL}/groups/{self._config.workspace_id}/datasets"
        resposta = self._requisitar("GET", url)
        valores = resposta.json().get("value", [])
        return pd.DataFrame(valores)

    def get_dataset_info(self, dataset_id: str | None = None) -> dict[str, Any]:
        """Obtém metadados de um dataset específico.

        Args:
            dataset_id: Apelido, GUID do dataset ou ``None`` para o padrão.

        Returns:
            Dicionário com os metadados do dataset retornados pela API.

        Raises:
            ErroPowerBI: Em caso de falha na API.
        """
        workspace_id, dataset = self._resolver_alvo(dataset_id)
        url = f"{_BASE_URL}/groups/{workspace_id}/datasets/{dataset}"
        resposta = self._requisitar("GET", url)
        return resposta.json()
