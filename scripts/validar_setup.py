"""Valida o setup do analista-bi: token, acesso ao dataset e consulta DAX.

Executa três etapas em sequência, imprimindo ✅/❌ e a correção sugerida:

1. Obtenção do token de acesso (Azure AD).
2. Leitura dos metadados do dataset configurado.
3. Uma consulta DAX trivial (``EVALUATE ROW("ok", 1)``).

Uso:
    python scripts/validar_setup.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garante que a raiz do projeto esteja no sys.path ao rodar como script.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth.azure_auth import AzureAuthenticator, ErroAutenticacao  # noqa: E402
from config.settings import (  # noqa: E402
    ErroConfiguracao,
    carregar_configuracao,
)
from powerbi.client import ErroPowerBI, PowerBIClient  # noqa: E402

OK = "✅"
FALHA = "❌"


def _cabecalho(texto: str) -> None:
    """Imprime um cabeçalho de seção."""
    print(f"\n{'=' * 70}\n{texto}\n{'=' * 70}")


def main() -> int:
    """Executa a validação. Devolve 0 em sucesso, 1 em falha."""
    _cabecalho("analista-bi — Validação de setup")

    # ------------------------------------------------------------------ #
    # Etapa 0: carregar configuração
    # ------------------------------------------------------------------ #
    try:
        config = carregar_configuracao()
    except ErroConfiguracao as exc:
        print(f"{FALHA} Configuração inválida.\n\n{exc}")
        return 1
    print(f"{OK} Configuração carregada (modo de autenticação: {config.auth_mode}).")

    autenticador = AzureAuthenticator(config)

    # ------------------------------------------------------------------ #
    # Etapa 1: token
    # ------------------------------------------------------------------ #
    _cabecalho("Etapa 1/3 — Autenticação (obtenção de token)")
    try:
        token = autenticador.get_token()
        print(f"{OK} Token obtido com sucesso (tamanho: {len(token)} caracteres).")
    except ErroAutenticacao as exc:
        print(f"{FALHA} Não foi possível obter o token.\n\n{exc}")
        print(
            "\nCorreção sugerida: confira AZURE_TENANT_ID e AZURE_CLIENT_ID no .env; "
            "no modo service_principal, confira também AZURE_CLIENT_SECRET."
        )
        return 1

    cliente = PowerBIClient(config=config, autenticador=autenticador)

    # ------------------------------------------------------------------ #
    # Etapa 2: acesso ao dataset
    # ------------------------------------------------------------------ #
    _cabecalho("Etapa 2/3 — Acesso ao dataset")
    try:
        info = cliente.get_dataset_info()
        nome = info.get("name", "(sem nome)")
        print(f"{OK} Dataset acessível: '{nome}' (id: {config.dataset_id}).")
    except ErroPowerBI as exc:
        print(f"{FALHA} Não foi possível ler o dataset.\n\n{exc}")
        print(
            "\nCorreção sugerida: verifique PBI_WORKSPACE_ID e PBI_DATASET_ID, e se "
            "o usuário/principal tem permissão Read+Build no workspace."
        )
        return 1

    # ------------------------------------------------------------------ #
    # Etapa 3: consulta DAX trivial
    # ------------------------------------------------------------------ #
    _cabecalho("Etapa 3/3 — Consulta DAX de teste")
    try:
        df = cliente.execute_dax('EVALUATE ROW("ok", 1)')
        print(f"{OK} Consulta executada. Resultado:\n{df.to_string(index=False)}")
    except ErroPowerBI as exc:
        print(f"{FALHA} A consulta DAX falhou.\n\n{exc}")
        print(
            "\nCorreção sugerida: a configuração de tenant 'Dataset Execute Queries "
            "REST API' precisa estar habilitada pelo admin do Power BI."
        )
        return 1

    _cabecalho("Resultado final")
    print(f"{OK} Setup validado com sucesso! O analista-bi está pronto para uso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
