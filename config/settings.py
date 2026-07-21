"""Carregamento e validação das configurações do analista-bi.

Todas as configurações sensíveis (credenciais Azure) vêm exclusivamente do
arquivo ``.env`` (via python-dotenv). Este módulo nunca imprime segredos e
falha com mensagens claras em português quando algo essencial está ausente.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Raiz do projeto (dois níveis acima deste arquivo: config/settings.py -> raiz).
RAIZ_PROJETO: Path = Path(__file__).resolve().parent.parent

# Escopo OAuth exigido pela API REST do Power BI.
POWERBI_SCOPE: str = "https://analysis.windows.net/powerbi/api/.default"

# Modos de autenticação suportados.
MODOS_AUTENTICACAO: tuple[str, ...] = ("device_code", "service_principal")


class ErroConfiguracao(Exception):
    """Erro de configuração: alguma variável essencial está ausente ou inválida."""


@dataclass
class Configuracao:
    """Configuração validada do projeto.

    Attributes:
        auth_mode: Modo de autenticação (``device_code`` ou ``service_principal``).
        tenant_id: Tenant ID (Diretório) do Azure AD.
        client_id: Client ID (ID do aplicativo) do Azure AD.
        client_secret: Client Secret — usado apenas no modo service_principal.
        workspace_id: ID do workspace (grupo) padrão do Power BI.
        dataset_id: ID do dataset (modelo semântico) padrão.
        rate_limit_por_minuto: Limite local de requisições por minuto à API.
        max_retries: Número máximo de tentativas em erros transitórios.
        limite_linhas_padrao: Limite padrão de linhas retornadas por consulta.
        token_cache_path: Caminho absoluto do cache de token (device_code).
    """

    auth_mode: str
    tenant_id: str
    client_id: str
    client_secret: str | None
    workspace_id: str
    dataset_id: str
    rate_limit_por_minuto: int = 30
    max_retries: int = 4
    limite_linhas_padrao: int = 20
    token_cache_path: Path = field(default_factory=lambda: RAIZ_PROJETO / ".token_cache.json")

    @property
    def authority(self) -> str:
        """URL de autoridade do Azure AD para este tenant."""
        return f"https://login.microsoftonline.com/{self.tenant_id}"


def _ler_int(nome: str, padrao: int) -> int:
    """Lê uma variável de ambiente inteira, com fallback e validação.

    Args:
        nome: Nome da variável de ambiente.
        padrao: Valor padrão caso a variável esteja ausente ou vazia.

    Returns:
        O valor inteiro configurado ou o padrão.

    Raises:
        ErroConfiguracao: Se o valor presente não for um inteiro válido.
    """
    bruto = os.getenv(nome, "").strip()
    if not bruto:
        return padrao
    try:
        return int(bruto)
    except ValueError as exc:
        raise ErroConfiguracao(
            f"A variável {nome} deve ser um número inteiro (valor atual: '{bruto}')."
        ) from exc


def carregar_configuracao(caminho_env: Path | str | None = None) -> Configuracao:
    """Carrega o ``.env`` e devolve uma :class:`Configuracao` validada.

    Args:
        caminho_env: Caminho opcional para um arquivo ``.env`` específico. Se
            omitido, procura ``.env`` na raiz do projeto.

    Returns:
        A configuração validada.

    Raises:
        ErroConfiguracao: Quando uma variável essencial está ausente ou o
            ``AUTH_MODE`` é inválido.
    """
    if caminho_env is None:
        caminho_env = RAIZ_PROJETO / ".env"
    load_dotenv(dotenv_path=caminho_env, override=False)

    auth_mode = os.getenv("AUTH_MODE", "device_code").strip().lower()
    if auth_mode not in MODOS_AUTENTICACAO:
        raise ErroConfiguracao(
            f"AUTH_MODE inválido: '{auth_mode}'. "
            f"Use um destes valores: {', '.join(MODOS_AUTENTICACAO)}."
        )

    faltando: list[str] = []

    def _obrigatoria(nome: str) -> str:
        valor = os.getenv(nome, "").strip()
        if not valor:
            faltando.append(nome)
        return valor

    tenant_id = _obrigatoria("AZURE_TENANT_ID")
    client_id = _obrigatoria("AZURE_CLIENT_ID")
    workspace_id = _obrigatoria("PBI_WORKSPACE_ID")
    dataset_id = _obrigatoria("PBI_DATASET_ID")

    client_secret = os.getenv("AZURE_CLIENT_SECRET", "").strip() or None
    if auth_mode == "service_principal" and not client_secret:
        faltando.append("AZURE_CLIENT_SECRET (obrigatório no modo service_principal)")

    if faltando:
        itens = "\n  - ".join(faltando)
        raise ErroConfiguracao(
            "Configuração incompleta. As seguintes variáveis são obrigatórias "
            "e estão ausentes no seu .env:\n  - "
            f"{itens}\n\n"
            "Dica: copie o arquivo .env.example para .env e preencha os valores "
            "(cp .env.example .env)."
        )

    token_cache_bruto = os.getenv("TOKEN_CACHE_PATH", ".token_cache.json").strip()
    token_cache_path = Path(token_cache_bruto)
    if not token_cache_path.is_absolute():
        token_cache_path = RAIZ_PROJETO / token_cache_path

    return Configuracao(
        auth_mode=auth_mode,
        tenant_id=tenant_id,
        client_id=client_id,
        client_secret=client_secret,
        workspace_id=workspace_id,
        dataset_id=dataset_id,
        rate_limit_por_minuto=_ler_int("PBI_RATE_LIMIT_PER_MIN", 30),
        max_retries=_ler_int("PBI_MAX_RETRIES", 4),
        limite_linhas_padrao=_ler_int("PBI_DEFAULT_ROW_LIMIT", 20),
        token_cache_path=token_cache_path,
    )
