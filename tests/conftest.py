"""Configuração compartilhada dos testes.

Garante que a raiz do projeto esteja no ``sys.path`` para importações do tipo
``from powerbi.client import ...`` funcionarem sob o pytest, e fornece uma
:class:`Configuracao` de teste sem depender de credenciais reais.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from config.settings import Configuracao  # noqa: E402


@pytest.fixture
def config_fake(tmp_path) -> Configuracao:
    """Configuração de teste com valores fictícios (sem credenciais reais)."""
    return Configuracao(
        auth_mode="service_principal",
        tenant_id="tenant-teste",
        client_id="client-teste",
        client_secret="segredo-teste",
        workspace_id="ws-teste",
        dataset_id="ds-teste",
        rate_limit_por_minuto=1000,
        max_retries=3,
        limite_linhas_padrao=20,
        token_cache_path=tmp_path / ".token_cache.json",
    )
