"""Testes do PowerBIClient com respostas da API mockadas (sem rede)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from powerbi.client import ErroPowerBI, PowerBIClient, _LimitadorTaxa


def _resposta(status: int, corpo: dict, headers: dict | None = None) -> MagicMock:
    """Cria uma resposta HTTP falsa com status e corpo JSON."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = corpo
    resp.headers = headers or {}
    return resp


def _cliente(config_fake, sessao) -> PowerBIClient:
    """Cria um cliente com autenticador e sessão mockados."""
    auth = MagicMock()
    auth.get_token.return_value = "token-falso"
    cliente = PowerBIClient(config=config_fake, autenticador=auth, sessao=sessao)
    # Evita ler datasets.yaml real durante os testes.
    cliente._datasets_apelidos = {}
    return cliente


def test_execute_dax_parseia_para_dataframe(config_fake) -> None:
    """A resposta de executeQueries é convertida em DataFrame."""
    corpo = {
        "results": [
            {
                "tables": [
                    {
                        "rows": [
                            {"Produto[Nome]": "Cloro", "[Total]": 10},
                            {"Produto[Nome]": "Soda", "[Total]": 5},
                        ]
                    }
                ]
            }
        ]
    }
    sessao = MagicMock()
    sessao.request.return_value = _resposta(200, corpo)
    cliente = _cliente(config_fake, sessao)

    df = cliente.execute_dax("EVALUATE Produtos")

    assert list(df.columns) == ["Produto[Nome]", "[Total]"]
    assert len(df) == 2
    assert df.iloc[0]["Produto[Nome]"] == "Cloro"


def test_execute_dax_resultado_vazio(config_fake) -> None:
    """Resposta sem linhas devolve DataFrame vazio, sem erro."""
    corpo = {"results": [{"tables": [{"rows": []}]}]}
    sessao = MagicMock()
    sessao.request.return_value = _resposta(200, corpo)
    cliente = _cliente(config_fake, sessao)

    df = cliente.execute_dax("EVALUATE Vazio")
    assert df.empty


def test_execute_dax_erro_na_consulta(config_fake) -> None:
    """Erro reportado dentro do resultado vira ErroPowerBI."""
    corpo = {"results": [{"error": {"message": "Sintaxe DAX inválida"}}]}
    sessao = MagicMock()
    sessao.request.return_value = _resposta(200, corpo)
    cliente = _cliente(config_fake, sessao)

    with pytest.raises(ErroPowerBI) as exc:
        cliente.execute_dax("EVALUATE errado")
    assert "Sintaxe DAX inválida" in str(exc.value)


def test_erro_403_mensagem_clara(config_fake) -> None:
    """403 é traduzido com causas prováveis (permissão/tenant setting)."""
    sessao = MagicMock()
    sessao.request.return_value = _resposta(403, {"error": {"message": "Forbidden"}})
    cliente = _cliente(config_fake, sessao)

    with pytest.raises(ErroPowerBI) as exc:
        cliente.execute_dax("EVALUATE ROW(\"ok\", 1)")
    texto = str(exc.value)
    assert "403" in texto
    assert "permiss" in texto.lower()


def test_erro_401_mensagem_clara(config_fake) -> None:
    """401 orienta refazer a autenticação."""
    sessao = MagicMock()
    sessao.request.return_value = _resposta(401, {})
    cliente = _cliente(config_fake, sessao)

    with pytest.raises(ErroPowerBI) as exc:
        cliente.execute_dax("EVALUATE ROW(\"ok\", 1)")
    assert "401" in str(exc.value)


def test_retry_em_429_depois_sucesso(config_fake, monkeypatch) -> None:
    """429 dispara retry; na tentativa seguinte, sucesso."""
    # Não dormir de verdade durante o teste.
    monkeypatch.setattr("powerbi.client.time.sleep", lambda *_: None)

    corpo_ok = {"results": [{"tables": [{"rows": [{"[x]": 1}]}]}]}
    sessao = MagicMock()
    sessao.request.side_effect = [
        _resposta(429, {}, {"Retry-After": "0"}),
        _resposta(200, corpo_ok),
    ]
    cliente = _cliente(config_fake, sessao)

    df = cliente.execute_dax("EVALUATE ROW(\"x\", 1)")
    assert len(df) == 1
    assert sessao.request.call_count == 2


def test_list_datasets(config_fake) -> None:
    """list_datasets converte o array 'value' em DataFrame."""
    corpo = {"value": [{"id": "1", "name": "Vendas"}, {"id": "2", "name": "Financeiro"}]}
    sessao = MagicMock()
    sessao.request.return_value = _resposta(200, corpo)
    cliente = _cliente(config_fake, sessao)

    df = cliente.list_datasets()
    assert len(df) == 2
    assert set(df["name"]) == {"Vendas", "Financeiro"}


def test_resolver_alvo_por_apelido(config_fake) -> None:
    """Apelido em datasets.yaml resolve para workspace/dataset corretos."""
    sessao = MagicMock()
    cliente = _cliente(config_fake, sessao)
    cliente._datasets_apelidos = {
        "vendas": {"workspace_id": "ws-vendas", "dataset_id": "ds-vendas", "padrao": True}
    }
    ws, ds = cliente._resolver_alvo("vendas")
    assert ws == "ws-vendas"
    assert ds == "ds-vendas"


def test_resolver_alvo_padrao_usa_env(config_fake) -> None:
    """Sem apelido padrão, usa workspace/dataset do .env."""
    sessao = MagicMock()
    cliente = _cliente(config_fake, sessao)
    ws, ds = cliente._resolver_alvo(None)
    assert ws == "ws-teste"
    assert ds == "ds-teste"


def test_limitador_taxa_permite_dentro_do_limite() -> None:
    """O limitador não bloqueia enquanto está dentro do limite."""
    lim = _LimitadorTaxa(max_por_minuto=5)
    # 5 chamadas rápidas não devem levantar nada nem travar.
    for _ in range(5):
        lim.aguardar_vaga()
    assert len(lim._marcas) == 5
