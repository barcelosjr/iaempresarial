"""Autenticação no Azure AD (MSAL) para acesso à API REST do Power BI.

Suporta dois modos, definidos por :attr:`Configuracao.auth_mode`:

* ``device_code``: fluxo interativo em que o usuário loga com a própria conta
  corporativa. O token é cacheado em disco para evitar novos logins.
* ``service_principal``: fluxo *client credentials* (app registrado no Azure AD),
  adequado para automações sem interação humana.

Nenhum segredo é impresso. O token nunca é logado.
"""

from __future__ import annotations

import atexit
import sys
from pathlib import Path

import msal

from config.settings import POWERBI_SCOPE, Configuracao, carregar_configuracao


class ErroAutenticacao(Exception):
    """Falha ao obter ou renovar o token de acesso do Azure AD."""


# O escopo do executeQueries é solicitado como ".default"; internamente o MSAL
# trata a lista abaixo. Mantemos como lista de um único item.
_SCOPES: list[str] = [POWERBI_SCOPE]


class AzureAuthenticator:
    """Obtém e renova tokens de acesso do Azure AD para o Power BI.

    A instância escolhe automaticamente o fluxo MSAL adequado conforme o
    ``auth_mode`` da configuração. O método :meth:`get_token` sempre devolve um
    token válido, renovando de forma silenciosa quando possível.
    """

    def __init__(self, config: Configuracao | None = None) -> None:
        """Inicializa o autenticador.

        Args:
            config: Configuração já carregada. Se omitida, carrega do ``.env``.
        """
        self._config = config or carregar_configuracao()
        self._app: msal.ClientApplication | None = None
        self._token_cache: msal.SerializableTokenCache | None = None

    # ------------------------------------------------------------------ #
    # Construção da aplicação MSAL
    # ------------------------------------------------------------------ #
    def _carregar_cache(self) -> msal.SerializableTokenCache:
        """Carrega (ou cria) o cache de token persistido em disco."""
        cache = msal.SerializableTokenCache()
        caminho: Path = self._config.token_cache_path
        if caminho.exists():
            try:
                cache.deserialize(caminho.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Cache corrompido: ignora e recomeça do zero.
                pass

        def _persistir() -> None:
            if cache.has_state_changed:
                try:
                    caminho.write_text(cache.serialize(), encoding="utf-8")
                    # Permissões restritas: apenas o dono lê/escreve.
                    caminho.chmod(0o600)
                except OSError:
                    pass

        atexit.register(_persistir)
        self._persistir_cache = _persistir  # type: ignore[attr-defined]
        return cache

    def _obter_app(self) -> msal.ClientApplication:
        """Constrói (uma vez) a aplicação MSAL adequada ao modo de auth."""
        if self._app is not None:
            return self._app

        if self._config.auth_mode == "service_principal":
            if not self._config.client_secret:
                raise ErroAutenticacao(
                    "Modo service_principal exige AZURE_CLIENT_SECRET no .env."
                )
            self._app = msal.ConfidentialClientApplication(
                client_id=self._config.client_id,
                authority=self._config.authority,
                client_credential=self._config.client_secret,
            )
        else:  # device_code
            self._token_cache = self._carregar_cache()
            self._app = msal.PublicClientApplication(
                client_id=self._config.client_id,
                authority=self._config.authority,
                token_cache=self._token_cache,
            )
        return self._app

    # ------------------------------------------------------------------ #
    # Obtenção de token
    # ------------------------------------------------------------------ #
    def get_token(self) -> str:
        """Devolve um token de acesso válido, renovando quando necessário.

        Returns:
            O *access token* (string) para usar no cabeçalho Authorization.

        Raises:
            ErroAutenticacao: Se não for possível obter o token (credenciais
                inválidas, login não concluído, etc.).
        """
        app = self._obter_app()

        if self._config.auth_mode == "service_principal":
            resultado = app.acquire_token_for_client(scopes=_SCOPES)
            return self._extrair_token(resultado)

        # device_code: tenta silenciosamente a partir de contas em cache.
        contas = app.get_accounts()
        if contas:
            resultado = app.acquire_token_silent(_SCOPES, account=contas[0])
            if resultado and "access_token" in resultado:
                self._salvar_cache()
                return resultado["access_token"]

        # Sem token em cache válido: dispara o fluxo device code.
        return self._fluxo_device_code(app)

    def _fluxo_device_code(self, app: msal.ClientApplication) -> str:
        """Executa o fluxo interativo device code e devolve o token."""
        fluxo = app.initiate_device_flow(scopes=_SCOPES)
        if "user_code" not in fluxo:
            raise ErroAutenticacao(
                "Não foi possível iniciar o fluxo device code. "
                "Verifique AZURE_CLIENT_ID e AZURE_TENANT_ID. "
                f"Detalhe: {fluxo.get('error_description', 'desconhecido')}"
            )

        # A mensagem já contém a URL e o código a digitar. Vai para stderr para
        # não poluir saídas estruturadas (ex.: JSON) em stdout.
        print(fluxo["message"], file=sys.stderr, flush=True)

        resultado = app.acquire_token_by_device_flow(fluxo)
        token = self._extrair_token(resultado)
        self._salvar_cache()
        return token

    def _salvar_cache(self) -> None:
        """Persiste o cache de token imediatamente, se houver mudanças."""
        persistir = getattr(self, "_persistir_cache", None)
        if callable(persistir):
            persistir()

    @staticmethod
    def _extrair_token(resultado: dict | None) -> str:
        """Valida a resposta do MSAL e devolve o access token.

        Args:
            resultado: Dicionário retornado pelos métodos ``acquire_token_*``.

        Returns:
            O access token.

        Raises:
            ErroAutenticacao: Se a resposta não contiver um token, com mensagem
                traduzindo o erro do Azure AD.
        """
        if resultado and "access_token" in resultado:
            return resultado["access_token"]

        if not resultado:
            raise ErroAutenticacao(
                "Nenhuma credencial em cache e nenhum login realizado. "
                "Rode `python scripts/validar_setup.py` para autenticar."
            )

        erro = resultado.get("error", "desconhecido")
        descricao = resultado.get("error_description", "")
        dica = {
            "invalid_client": "Client ID ou Client Secret inválidos.",
            "unauthorized_client": "O aplicativo não está autorizado neste tenant.",
            "invalid_scope": "Escopo inválido — confira as permissões do app no Azure AD.",
            "invalid_grant": "Login expirado ou revogado — refaça a autenticação.",
            "access_denied": "Consentimento negado pelo usuário/administrador.",
        }.get(erro, "Verifique tenant, client e permissões do Power BI.")

        raise ErroAutenticacao(
            f"Falha na autenticação Azure AD ({erro}): {dica}\n"
            f"Detalhe técnico: {descricao}"
        )
