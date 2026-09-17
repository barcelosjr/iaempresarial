"""Testes da biblioteca de auditoria de lançamentos de caixa (R1–R14).

Validam a montagem das strings DAX — sem chamar a API. Não confundir com a
validação contra dados reais: essa já foi feita manualmente (ver achados de
referência em ``dictionary/regras_negocio.md``) e não é reproduzível aqui sem
credenciais. O que estes testes garantem é que o código não regride: os dois
filtros universais continuam presentes em toda regra, os parâmetros são
interpolados corretamente e a validação de período continua rejeitando
entrada inválida.
"""

from __future__ import annotations

import pandas as pd
import pytest

from mcp_server import server
from mcp_server.server import _normalizar_coluna
from powerbi import dax_auditoria as aud


def _chamar_regra(regra_id: str, **overrides):
    """Chama o construtor de uma regra do registro, no mesmo padrão do servidor MCP."""
    regra = aud.REGRAS[regra_id]
    kwargs: dict[str, object] = {"empresa": overrides.pop("empresa", None)}
    if regra.aceita_periodo:
        kwargs["periodo"] = overrides.pop("periodo", None)
        kwargs["modo"] = overrides.pop("modo", "mensal")
    kwargs.update(overrides)
    return regra.construtor(**kwargs)


# --------------------------------------------------------------------------- #
# Registro de regras — completude
# --------------------------------------------------------------------------- #
def test_registro_tem_as_14_regras():
    assert set(aud.REGRAS) == {f"R{i}" for i in range(1, 15)}


def test_r6_e_informativa_nao_e_excecao():
    """R6 foi rebaixada a informativo — a hipótese de lacuna não se sustentou
    contra os dados reais (ver docstring de regra_r6_cobertura_titulo)."""
    assert aud.REGRAS["R6"].severidade == "informativo"


def test_demais_regras_tem_severidade_de_excecao():
    severidades_validas = {"alta", "media", "baixa"}
    for regra_id, regra in aud.REGRAS.items():
        if regra_id == "R6":
            continue
        assert regra.severidade in severidades_validas, regra_id


def test_r9_e_r10_nao_aceitam_periodo():
    """R9 (data implausível) e R10 (janela própria de 90 dias) varrem a base
    toda por definição — aceitar período mascararia o que elas auditam."""
    assert aud.REGRAS["R9"].aceita_periodo is False
    assert aud.REGRAS["R10"].aceita_periodo is False


# --------------------------------------------------------------------------- #
# Regras estruturais comuns a todas as regras
# --------------------------------------------------------------------------- #
@pytest.fixture(params=list(aud.REGRAS))
def consulta(request):
    """A consulta DAX de cada uma das 14 regras, com parâmetros padrão."""
    return request.param, _chamar_regra(request.param)


def test_consulta_e_somente_leitura(consulta):
    _, query = consulta
    assert query.lstrip().startswith("EVALUATE")


def test_exclui_caixas_de_concentracao(consulta):
    """Toda regra deve excluir os caixas 9/99/4 — fonte única: _filtro_caixas_operacionais()."""
    _, query = consulta
    for caixa in ('"9"', '"99"', '"4"'):
        assert caixa in query, f"caixa {caixa} não excluído em: {query[:200]}"


def test_exclui_caixas_mits_8_e_14(consulta):
    _, query = consulta
    assert "MULTICAR MITS MATRIZ" in query
    assert "MULTICAR MITS VV" in query
    assert '"8"' in query
    assert '"14"' in query


def test_exclui_linhas_de_abertura(consulta):
    """As 28 linhas de "SALDO INICIAL DA PLANILHA" não têm NOME_USUARIO —
    _excluir_abertura() precisa aparecer em toda regra."""
    _, query = consulta
    assert "ISBLANK('CAIXAS'[NOME_USUARIO])" in query


def test_referencia_tabela_caixas(consulta):
    _, query = consulta
    assert "'CAIXAS'" in query


# --------------------------------------------------------------------------- #
# TOPN + ORDER BY — regressão do bug de ordenação invertida
# --------------------------------------------------------------------------- #
def test_topn_com_order_by_explicito(consulta):
    """TOPN sozinho não garante a ordem de exibição (bug real encontrado ao
    validar contra dados reais) — toda regra que usa TOPN precisa fechar com
    ORDER BY explícito no nível do EVALUATE."""
    regra_id, query = consulta
    if "TOPN(" in query:
        assert "ORDER BY" in query, f"{regra_id} usa TOPN sem ORDER BY"


def test_ordenar_por_alias_nunca_coluna_qualificada_pos_selectcolumns():
    """Regressão do bug: depois de SELECTCOLUMNS, TOPN deve ordenar pelo
    alias (ex.: [VALOR]), nunca pela coluna qualificada original — ela deixa
    de existir naquele contexto e a API devolve 400 sem detalhe."""
    query = aud.regra_r2_estorno_positivo()
    # A cláusula ORDER BY (após o SELECTCOLUMNS) não pode referenciar 'CAIXAS'[...]
    trecho_final = query.split(")\n")[-1]
    assert "'CAIXAS'[" not in trecho_final


# --------------------------------------------------------------------------- #
# Parâmetros — thresholds e filtros interpolados corretamente
# --------------------------------------------------------------------------- #
def test_r1_limiar_customizado_aparece_na_query():
    query = aud.regra_r1_estorno_mesmo_dia(limiar=12345.0)
    assert "12345.0" in query


def test_r4_minimo_ocorrencias_customizado():
    query = aud.regra_r4_fracionamento(minimo_ocorrencias=7)
    assert "[N] >= 7" in query


def test_r11_limiar_customizado():
    query = aud.regra_r11_valor_redondo(limiar=25000.0)
    assert "25000.0" in query


def test_filtro_empresa_aplicado_quando_informado():
    query = aud.regra_r2_estorno_positivo(empresa="KOBE")
    assert '"KOBE"' in query
    assert "'CAIXAS'[EMPRESA]" in query


def test_filtro_empresa_ausente_por_padrao():
    query = aud.regra_r2_estorno_positivo()
    assert "'CAIXAS'[EMPRESA]" not in query


def test_filtro_periodo_aplicado_quando_informado():
    query = aud.regra_r2_estorno_positivo(periodo="06/2026", modo="mensal")
    assert "DATE(2026,6,1)" in query
    assert "DATE(2026,6,30)" in query


def test_r9_ignora_periodo_por_construcao():
    """regra_r9_data_implausivel nem aceita periodo/modo como parâmetro."""
    import inspect

    assinatura = inspect.signature(aud.regra_r9_data_implausivel)
    assert "periodo" not in assinatura.parameters
    assert "modo" not in assinatura.parameters


# --------------------------------------------------------------------------- #
# Helpers de período (intervalo_do_modo)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("periodo", "modo", "esperado"),
    [
        ("06/2026", "mensal", ("2026-06-01", "2026-06-30")),
        ("02/2024", "mensal", ("2024-02-01", "2024-02-29")),  # ano bissexto
        ("06/2026", "trimestral", ("2026-04-01", "2026-06-30")),
        ("12/2025", "anual", ("2025-01-01", "2025-12-31")),
    ],
)
def test_intervalo_do_modo(periodo, modo, esperado):
    data_de, data_ate = aud.intervalo_do_modo(periodo, modo)
    assert (data_de.isoformat(), data_ate.isoformat()) == esperado


@pytest.mark.parametrize("periodo_invalido", ["2026-06", "13/2026", "abc", "06-2026"])
def test_intervalo_do_modo_rejeita_periodo_invalido(periodo_invalido):
    with pytest.raises(ValueError):
        aud.intervalo_do_modo(periodo_invalido, "mensal")


def test_intervalo_do_modo_trimestral_exige_fim_de_trimestre():
    with pytest.raises(ValueError):
        aud.intervalo_do_modo("05/2026", "trimestral")


def test_intervalo_do_modo_anual_exige_dezembro():
    with pytest.raises(ValueError):
        aud.intervalo_do_modo("06/2026", "anual")


def test_intervalo_do_modo_rejeita_modo_invalido():
    with pytest.raises(ValueError):
        aud.intervalo_do_modo("06/2026", "semanal")


# --------------------------------------------------------------------------- #
# R6 — não pode mais alegar "lacuna"/"faltando" (correção documentada)
# --------------------------------------------------------------------------- #
def test_r6_nao_alega_mais_lacuna():
    """A versão anterior comparava (max-min+1) contra a contagem distinta e
    chamava a diferença de "Faltando" — sob a premissa (falsa) de TITULO ser
    um contador privado por revenda. Corrigido para reportar densidade sem
    alegar lançamento ausente."""
    query = aud.regra_r6_cobertura_titulo()
    assert "Faltando" not in query
    assert "Densidade" in query


# --------------------------------------------------------------------------- #
# Segregação de funções — marcação de revisão independente (mcp_server)
# --------------------------------------------------------------------------- #
def test_marcacao_revisao_independente_dispara_para_o_usuario_informado():
    """Regressão funcional do requisito de desenho (regras_negocio.md,
    'Segregação de funções'): uma exceção cujo usuário é o próprio revisor
    tem que aparecer destacada, sem precisar de rede/credenciais."""
    df_r2 = pd.DataFrame(
        [
            {"[REVENDA]": "KOBE NISSAN GV", "[VALOR]": 500.0, "[USUARIO]": "ANA PAULA SILVA"},
            {"[REVENDA]": "KOBE NISSAN GV", "[VALOR]": 200.0, "[USUARIO]": "JOAO PEDRO"},
        ]
    )

    resultados = {"R2": (df_r2, "EVALUATE ...")}
    texto = server._formatar_auditoria(
        resultados, erros={}, titulo="# teste", usuario_revisor="ANA PAULA SILVA"
    )
    assert "Requer revisão independente" in texto
    assert "R2" in texto.split("Requer revisão independente")[1].split("##")[0]


def test_r12_sempre_entra_em_revisao_independente_mesmo_sem_revisor_informado():
    df_r12 = pd.DataFrame(
        [{"CAIXAS[REVENDA]": "KOBE NISSAN GV", "[SomaR]": 6000.0, "[SomaP]": -6000.0}]
    )
    resultados = {"R12": (df_r12, "EVALUATE ...")}
    texto = server._formatar_auditoria(resultados, erros={}, titulo="# teste", usuario_revisor=None)
    assert "Requer revisão independente" in texto
    assert "R12" in texto.split("Requer revisão independente")[1].split("##")[0]


def test_normalizar_coluna_lida_com_qualificada_e_alias():
    assert _normalizar_coluna("CAIXAS[REVENDA]") == "REVENDA"
    assert _normalizar_coluna("[VALOR]") == "VALOR"
    assert _normalizar_coluna("SomaR") == "SomaR"
