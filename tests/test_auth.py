"""Testes de autenticação (com mocks — não exigem credenciais reais)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from auth.azure_auth import AzureAuthenticator, ErroAutenticacao


def test_service_principal_obtem_token(config_fake) -> None:
    """No modo service_principal, get_token usa acquire_token_for_client."""
    autenticador = AzureAuthenticator(config_fake)

    app_falso = MagicMock()
    app_falso.acquire_token_for_client.return_value = {"access_token": "abc123"}
    autenticador._app = app_falso  # injeta app já construído

    token = autenticador.get_token()

    assert token == "abc123"
    app_falso.acquire_token_for_client.assert_called_once()


def test_service_principal_erro_traduzido(config_fake) -> None:
    """Falha no client credentials vira ErroAutenticacao com mensagem clara."""
    autenticador = AzureAuthenticator(config_fake)

    app_falso = MagicMock()
    app_falso.acquire_token_for_client.return_value = {
        "error": "invalid_client",
        "error_description": "AADSTS7000215",
    }
    autenticador._app = app_falso

    with pytest.raises(ErroAutenticacao) as exc:
        autenticador.get_token()

    assert "invalid_client" in str(exc.value)
    assert "Client ID ou Client Secret" in str(exc.value)


def test_device_code_usa_cache_silencioso(config_fake) -> None:
    """Com conta em cache, device_code renova de forma silenciosa."""
    config_fake.auth_mode = "device_code"
    autenticador = AzureAuthenticator(config_fake)

    app_falso = MagicMock()
    app_falso.get_accounts.return_value = [{"username": "gestor@empresa.com"}]
    app_falso.acquire_token_silent.return_value = {"access_token": "cacheado"}
    autenticador._app = app_falso
    autenticador._token_cache = MagicMock()

    token = autenticador.get_token()

    assert token == "cacheado"
    app_falso.acquire_token_silent.assert_called_once()
    app_falso.initiate_device_flow.assert_not_called()


def test_device_code_dispara_fluxo_quando_sem_cache(config_fake) -> None:
    """Sem cache válido, device_code inicia o fluxo interativo."""
    config_fake.auth_mode = "device_code"
    autenticador = AzureAuthenticator(config_fake)

    app_falso = MagicMock()
    app_falso.get_accounts.return_value = []
    app_falso.initiate_device_flow.return_value = {
        "user_code": "XYZ",
        "message": "Acesse https://microsoft.com/devicelogin e digite XYZ",
    }
    app_falso.acquire_token_by_device_flow.return_value = {"access_token": "novo"}
    autenticador._app = app_falso
    autenticador._token_cache = MagicMock()

    token = autenticador.get_token()

    assert token == "novo"
    app_falso.initiate_device_flow.assert_called_once()
    app_falso.acquire_token_by_device_flow.assert_called_once()


def test_device_code_falha_ao_iniciar_fluxo(config_fake) -> None:
    """Se o device flow não iniciar, erro é traduzido."""
    config_fake.auth_mode = "device_code"
    autenticador = AzureAuthenticator(config_fake)

    app_falso = MagicMock()
    app_falso.get_accounts.return_value = []
    app_falso.initiate_device_flow.return_value = {
        "error_description": "client desconhecido"
    }
    autenticador._app = app_falso
    autenticador._token_cache = MagicMock()

    with pytest.raises(ErroAutenticacao) as exc:
        autenticador.get_token()

    assert "device code" in str(exc.value).lower()


def test_service_principal_sem_secret_falha() -> None:
    """Modo service_principal exige client_secret ao construir o app."""
    from config.settings import Configuracao

    config = Configuracao(
        auth_mode="service_principal",
        tenant_id="t",
        client_id="c",
        client_secret=None,
        workspace_id="ws",
        dataset_id="ds",
    )
    autenticador = AzureAuthenticator(config)
    with pytest.raises(ErroAutenticacao):
        autenticador.get_token()
