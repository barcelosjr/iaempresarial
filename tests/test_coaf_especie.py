"""Testes da detecção COAF e do histórico permanente.

Usam dados sintéticos e um DuckDB temporário — não exigem credenciais, no
mesmo padrão do resto da suíte.

Os casos aqui não são genéricos: cada um reproduz uma armadilha real da base.
O nome do cliente pode variar de formatação entre lançamentos ou ser
corrigido com o tempo (por isso a chave é o código, não o nome); a base tem
lançamentos com ``DATA`` até 2041; e o fracionamento pode cruzar a borda do
semestre, escapando de uma janela fixa de "últimos 6 meses".
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb
import pandas as pd
import pytest

from analysis import coaf_especie as coaf
from local_data import coaf_estado as estado


@pytest.fixture
def cfg():
    """Configuração real do projeto — os testes validam a regra em vigor."""
    return coaf.carregar_config_coaf()


@pytest.fixture
def con(tmp_path):
    """Banco DuckDB temporário com as tabelas do COAF criadas."""
    conexao = duckdb.connect(str(tmp_path / "teste.duckdb"))
    estado.garantir_tabelas(conexao)
    yield conexao
    conexao.close()


def _lancamento(**kwargs):
    """Lançamento sintético com os campos que o Power BI devolve."""
    base = dict(
        EMPRESA="KOBE",
        REVENDA="KOBE NISSAN GV",
        CAIXA="2",
        DATA=date(2026, 5, 10),
        CLIENTE="123456",
        TITULO="T1",
        VALOR=10000.0,
        ORIGEM="371 - A VISTA",
        HISTORICO="Ref. NF: 1 Cliente: FULANO DE TAL",
        NOME_USUARIO="OPERADOR",
    )
    base.update(kwargs)
    return base


# --------------------------------------------------------------------------- #
# Extração do nome do cliente
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "historico, esperado",
    [
        # Adiantamento: sem espaço depois dos dois-pontos.
        (
            "Ref. Adiantamento: 4 Cliente:VANDERLEY FRANCISCO BARBOSA RAMOS",
            "VANDERLEY FRANCISCO BARBOSA RAMOS",
        ),
        # Nota fiscal: com espaço.
        (
            "Ref. Nota(s) Fiscal(is): 68391 30608 Cliente: ALICE PEREIRA COSTA",
            "ALICE PEREIRA COSTA",
        ),
        # Pessoa jurídica.
        (
            "Ref. Estorno Titulo: 73 Cliente: LAGE E SCARABELI COMERCIO DE VEICULOS LTDA",
            "LAGE E SCARABELI COMERCIO DE VEICULOS LTDA",
        ),
        # Baixa de adiantamento em lote: não traz cliente.
        (
            "LANCAMENTO REFERENTE A BAIXA DE ADIANTAMENTO NESTA DATA:\\rNr.:3-01 - SINDICATO",
            None,
        ),
        ("", None),
        (None, None),
    ],
)
def test_extrair_nome_cliente(historico, esperado):
    assert coaf.extrair_nome_cliente(historico) == esperado


def test_chave_e_o_codigo_do_cliente():
    assert coaf.chave_do_cliente("30184") == "30184"
    assert coaf.chave_do_cliente(30184) == "30184"


def test_resolver_nome_do_grupo_usa_primeiro_nome_nao_vazio():
    nomes = pd.Series(["", "FULANO DE TAL", "CICLANO"])
    nome, identificado = coaf.resolver_nome_do_grupo(nomes)
    assert nome == "FULANO DE TAL"
    assert identificado is True


def test_resolver_nome_do_grupo_sem_nenhum_nome():
    nomes = pd.Series(["", ""])
    nome, identificado = coaf.resolver_nome_do_grupo(nomes)
    assert nome == ""
    assert identificado is False


# --------------------------------------------------------------------------- #
# Janela móvel
# --------------------------------------------------------------------------- #
def test_subtrair_meses_trata_estouro_de_dia():
    assert coaf.subtrair_meses(date(2026, 8, 31), 6) == date(2026, 2, 28)
    assert coaf.subtrair_meses(date(2024, 8, 31), 6) == date(2024, 2, 29)  # bissexto
    assert coaf.subtrair_meses(date(2026, 3, 15), 6) == date(2025, 9, 15)
    assert coaf.subtrair_meses(date(2026, 1, 10), 6) == date(2025, 7, 10)


def test_janela_termina_sempre_hoje_com_folga(cfg):
    """A janela é [hoje - 6 meses - 5 dias, hoje] (decisão do gestor)."""
    inicio, fim = coaf.intervalo_da_janela(cfg, hoje=date(2026, 8, 19))
    assert fim == date(2026, 8, 19)
    assert inicio == date(2026, 2, 14), "6 meses antes é 19/02; a folga puxa para 14/02"


def test_folga_de_5_dias_alarga_a_janela(cfg):
    """A folga existe para não perder lançamento em virada de mês ou atraso.

    Um recebimento de 16/02 fica FORA da janela de 6 meses cravados (que
    começaria em 19/02) e DENTRO da janela com folga.
    """
    df = pd.DataFrame(
        [
            _lancamento(DATA=date(2026, 2, 16), VALOR=20000.0, TITULO="T1"),
            _lancamento(DATA=date(2026, 7, 1), VALOR=11000.0, TITULO="T2"),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))

    casos = coaf.detectar(prep, cfg, hoje=date(2026, 8, 19))
    assert len(casos) == 1
    assert casos[0]["total"] == 31000.0

    sem_folga = dict(cfg, janela_dias_folga=0)
    assert coaf.detectar(prep, sem_folga, hoje=date(2026, 8, 19)) == []


def test_cruzamento_e_pego_no_dia_em_que_acontece(cfg):
    """Fracionamento entre janeiro e junho: R$ 8 mil x 4 = R$ 32 mil.

    Consequência aceita da janela fixa: rodando em 19/08 o caso NÃO aparece
    mais, porque a janela começa em 14/02 e só enxerga R$ 24 mil. Mas o job
    roda de 30 em 30 minutos — em 20/06, dia do quarto recebimento, a janela
    daquele dia enxerga os R$ 32 mil e dispara. O histórico é permanente, então
    a detecção fica registrada mesmo depois de a janela andar.

    É por isso que a janela fixa é segura em regime: ela não precisa
    redescobrir o passado, porque o passado já foi coberto quando era presente.
    """
    datas = [date(2026, 1, 10), date(2026, 3, 5), date(2026, 5, 2), date(2026, 6, 20)]
    df = pd.DataFrame(
        [_lancamento(DATA=d, TITULO=f"T{i}", VALOR=8000.0) for i, d in enumerate(datas)]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))

    # Rodando dois meses depois: fora da janela, não aparece.
    assert coaf.detectar(prep, cfg, hoje=date(2026, 8, 19)) == []

    # Rodando no dia do cruzamento: aparece, com o total cheio.
    casos = coaf.detectar(prep, cfg, hoje=date(2026, 6, 20))
    assert len(casos) == 1
    assert casos[0]["total"] == 32000.0
    assert casos[0]["janela_fim"] == date(2026, 6, 20)
    assert casos[0]["gatilho"]["titulo"] == "T3"


def test_abaixo_do_limiar_nao_gera_caso(cfg):
    df = pd.DataFrame([_lancamento(VALOR=29999.99)])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    assert coaf.detectar(prep, cfg) == []


def test_exatamente_no_limiar_gera_caso(cfg):
    """A regra é "igual ou superior a 30 mil" — o limiar exato conta."""
    df = pd.DataFrame([_lancamento(VALOR=30000.0)])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    assert len(coaf.detectar(prep, cfg)) == 1


# --------------------------------------------------------------------------- #
# Higiene de dados
# --------------------------------------------------------------------------- #
def test_data_futura_e_descartada(cfg):
    """A base tem lançamentos com DATA até 2041 — sujeira, não recebimento."""
    df = pd.DataFrame(
        [
            _lancamento(VALOR=31000.0),
            _lancamento(DATA=date(2041, 7, 5), VALOR=99000.0, TITULO="TF"),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    assert len(prep) == 1
    assert coaf.detectar(prep, cfg)[0]["total"] == 31000.0


def test_valor_nao_positivo_e_descartado(cfg):
    df = pd.DataFrame([_lancamento(VALOR=31000.0), _lancamento(VALOR=-500.0, TITULO="T2")])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    assert len(prep) == 1


def test_caixa_de_concentracao_e_sinalizado_nao_excluido(cfg):
    """Decisão do gestor (19/08): caixa 99 entra na apuração, mas sai marcado.

    Caixa 9 tinha essa mesma regra até 25/08/2026, quando o gestor decidiu
    excluí-lo por completo (config/coaf.yaml: caixas_excluidos) — ver
    test_caixa_9_nao_e_mais_sinalizado_e_sim_excluido.
    """
    df = pd.DataFrame([_lancamento(CAIXA="99", VALOR=31000.0)])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg)
    assert len(casos) == 1
    assert casos[0]["tem_caixa_sinalizado"] is True


def test_caixa_9_nao_e_mais_sinalizado_e_sim_excluido(cfg):
    """Decisão do gestor (25/08/2026): caixa 9 saiu de "sinalizado" e virou
    "excluído" — a exclusão de verdade acontece na consulta DAX
    (powerbi.dax_coaf._filtro_caixas_excluidos); aqui só confirmamos que o
    Python não marca mais caixa 9 como sinalizado, já que ele nem deveria
    chegar como lançamento em produção."""
    assert "9" not in cfg["caixas_sinalizados"]["global"]
    assert cfg["caixas_excluidos"]["global"] == ["9"]

    df = pd.DataFrame([_lancamento(CAIXA="9", VALOR=31000.0)])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg)
    assert len(casos) == 1
    assert casos[0]["tem_caixa_sinalizado"] is False


def test_dax_exclui_caixa_9_de_qualquer_revenda():
    from powerbi.dax_coaf import recebimentos_especie

    q = recebimentos_especie(
        date(2026, 2, 20), date(2026, 8, 25), caixas_excluidos=["9"]
    )
    assert 'NOT(\'CAIXAS\'[CAIXA] IN {"9"})' in q


def test_dax_sem_caixas_excluidos_nao_altera_a_query():
    from powerbi.dax_coaf import recebimentos_especie

    q = recebimentos_especie(date(2026, 2, 20), date(2026, 8, 25))
    assert "CAIXA] IN" not in q


def test_caixa_8_so_e_sinalizado_na_multicar_mits(cfg):
    comum = pd.DataFrame([_lancamento(CAIXA="8", VALOR=31000.0)])
    mits = pd.DataFrame(
        [
            _lancamento(
                CAIXA="8", VALOR=31000.0, REVENDA="MULTICAR MITS VV", EMPRESA="MIT"
            )
        ]
    )
    prep_comum = coaf.preparar_lancamentos(comum, cfg, hoje=date(2026, 8, 19))
    prep_mits = coaf.preparar_lancamentos(mits, cfg, hoje=date(2026, 8, 19))
    assert coaf.detectar(prep_comum, cfg)[0]["tem_caixa_sinalizado"] is False
    assert coaf.detectar(prep_mits, cfg)[0]["tem_caixa_sinalizado"] is True


# --------------------------------------------------------------------------- #
# Identidade do cliente — a chave é o código, não o nome (decisão do gestor,
# 26/08/2026, depois do reenvio indevido do código 225456 — ver
# dictionary/regras_negocio.md)
# --------------------------------------------------------------------------- #
def test_mesmo_codigo_gera_um_so_caso_mesmo_com_nomes_diferentes_no_historico(cfg):
    """A chave é CAIXAS[CLIENTE] (o código), não o nome.

    Dois lançamentos do MESMO código, com nomes DIFERENTES no histórico
    (o cenário que antes se temia do código 30184), agora somam num único
    caso — o nome do caso é o primeiro encontrado na ordem cronológica. É a
    troca deliberada: o nome pode variar de formatação entre lançamentos ou
    ser corrigido com o tempo (cadastro), o código não.
    """
    df = pd.DataFrame(
        [
            _lancamento(
                CLIENTE="30184", VALOR=31000.0, TITULO="TA", DATA=date(2026, 3, 1),
                HISTORICO="Ref. Adiantamento: 1 Cliente:EMPRESA ALFA LTDA",
            ),
            _lancamento(
                CLIENTE="30184", VALOR=33000.0, TITULO="TB", DATA=date(2026, 3, 10),
                HISTORICO="Ref. Adiantamento: 2 Cliente:EMPRESA BETA LTDA",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg, hoje=date(2026, 8, 19))
    assert len(casos) == 1
    assert casos[0]["chave_cliente"] == "30184"
    assert casos[0]["nome_cliente"] == "EMPRESA ALFA LTDA"
    assert casos[0]["total"] == 64000.0


def test_backfill_de_nome_por_codigo_quando_um_so_nome_existe(cfg):
    """Bug real de produção (código 34642, 21/08/2026).

    Um SAQUE (R$ 30 mil) não tem "Cliente:" no histórico e sozinho já cruza o
    limiar; um adiantamento do MESMO código, dois meses depois, tem o nome.
    Sem backfill, o SAQUE virava um caso "sem nome" separado, e a DMF saía
    sem identificar o declarante mesmo o nome estando disponível na base.
    """
    df = pd.DataFrame(
        [
            _lancamento(
                CLIENTE="34642", VALOR=30000.0, TITULO="SAQUE",
                DATA=date(2026, 2, 20), HISTORICO="SAQUE CHEQUE Nº 161",
            ),
            _lancamento(
                CLIENTE="34642", VALOR=300.0, TITULO="ADT",
                DATA=date(2026, 6, 5),
                HISTORICO="Ref. Adiantamento: 23 Cliente:MULTI COMERCIO DE VEICULOS LTDA",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 21))
    casos = coaf.detectar(prep, cfg, hoje=date(2026, 8, 21))
    assert len(casos) == 1
    assert casos[0]["nome_cliente"] == "MULTI COMERCIO DE VEICULOS LTDA"
    assert casos[0]["nome_identificado"] is True
    assert casos[0]["total"] == 30300.0


def test_lancamento_sem_nome_soma_no_caso_do_mesmo_codigo(cfg):
    """Um lançamento sem nome no histórico (ex.: SAQUE) some no mesmo caso dos
    outros lançamentos do MESMO código — a chave é o código, então nunca fica
    "órfão" isolado por falta de nome. O nome de exibição do caso vem do
    primeiro lançamento do grupo que tiver algum (ordem cronológica)."""
    df = pd.DataFrame(
        [
            _lancamento(
                CLIENTE="99999", VALOR=31000.0, TITULO="T1",
                DATA=date(2026, 3, 1), HISTORICO="SAQUE SEM REFERENCIA",
            ),
            _lancamento(
                CLIENTE="99999", VALOR=10000.0, TITULO="T2",
                DATA=date(2026, 3, 5),
                HISTORICO="Ref. Adiantamento: 1 Cliente:PRIMEIRO CLIENTE LTDA",
            ),
            _lancamento(
                CLIENTE="99999", VALOR=6000.0, TITULO="T3",
                DATA=date(2026, 3, 10),
                HISTORICO="Ref. Adiantamento: 2 Cliente:SEGUNDO CLIENTE LTDA",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 21))
    casos = coaf.detectar(prep, cfg, hoje=date(2026, 8, 21))
    assert len(casos) == 1
    assert casos[0]["chave_cliente"] == "99999"
    assert casos[0]["nome_cliente"] == "PRIMEIRO CLIENTE LTDA"
    assert casos[0]["nome_identificado"] is True
    assert casos[0]["total"] == 47000.0


def test_nome_cliente_da_coluna_e_usado_quando_historico_nao_tem_padrao(cfg):
    """CAIXAS[NOME_CLIENTE] é fallback: preenche o nome quando HISTORICO não
    traz "Cliente:" (ex.: transferência interna entre caixas)."""
    df = pd.DataFrame(
        [
            _lancamento(
                CLIENTE="30184", VALOR=31000.0, TITULO="T1",
                HISTORICO="Entrada por transferência de saldo do caixa 07.",
                NOME_CLIENTE="LAGE E SCARABELI COMERCIO DE VEICULOS LTDA",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg, hoje=date(2026, 8, 19))
    assert len(casos) == 1
    assert casos[0]["nome_cliente"] == "LAGE E SCARABELI COMERCIO DE VEICULOS LTDA"
    assert casos[0]["nome_identificado"] is True


def test_nome_cliente_fallback_para_historico_quando_coluna_ausente(cfg):
    """Modelo sem a coluna NOME_CLIENTE (tolerância a schema antigo) continua
    resolvendo o nome pelo parser de HISTORICO, como antes."""
    df = pd.DataFrame(
        [_lancamento(VALOR=31000.0, HISTORICO="Ref. NF: 1 Cliente: FULANO DE TAL")]
    )
    assert "NOME_CLIENTE" not in df.columns
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg, hoje=date(2026, 8, 19))
    assert casos[0]["nome_cliente"] == "FULANO DE TAL"


def test_nome_cliente_em_branco_cai_no_fallback_de_historico(cfg):
    """Coluna NOME_CLIENTE presente mas vazia numa linha específica: usa o
    HISTORICO daquela linha, sem virar "sem nome" à toa."""
    df = pd.DataFrame(
        [
            _lancamento(
                VALOR=31000.0, NOME_CLIENTE="",
                HISTORICO="Ref. NF: 1 Cliente: CICLANO DA SILVA",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg, hoje=date(2026, 8, 19))
    assert casos[0]["nome_cliente"] == "CICLANO DA SILVA"


def test_nome_cliente_prevalece_sobre_historico_quando_os_dois_existem(cfg):
    """NOME_CLIENTE é a fonte primária — decisão do gestor (26/08/2026).

    Risco registrado e aceito: por ser cadastro (master data), pode ser
    reformatado com o tempo — diferente do texto de HISTORICO, imutável.
    Isso já trocou a chave de um cliente já notificado em produção (código
    225456: "AGNALDO CEZAR BATISTA DE SOUZA" no histórico, resolvido depois
    como "AGNALDO CEZAR SOUZA" via NOME_CLIENTE), disparando um reenvio
    indevido — mitigado com a migração pontual de 26/08/2026 (ver
    dictionary/regras_negocio.md), não com uma mudança de prioridade.
    """
    df = pd.DataFrame(
        [
            _lancamento(
                CLIENTE="225456", VALOR=51010.0, TITULO="T1",
                HISTORICO="Ref. NF: 1 Cliente: AGNALDO CEZAR BATISTA DE SOUZA",
                NOME_CLIENTE="AGNALDO CEZAR SOUZA",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg, hoje=date(2026, 8, 19))
    assert casos[0]["nome_cliente"] == "AGNALDO CEZAR SOUZA"


def test_filtrar_clientes_excluidos_por_nome(cfg):
    df = pd.DataFrame(
        [
            _lancamento(VALOR=31000.0),  # FULANO DE TAL, do _lancamento padrão
            _lancamento(
                VALOR=40000.0, TITULO="T2", CLIENTE="999",
                HISTORICO="Ref. NF: 1 Cliente: OUTRO CLIENTE",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg)
    assert len(casos) == 2

    cfg_com_exclusao = dict(cfg, clientes_excluidos={"nomes": ["fulano de tal"], "codigos": []})
    restantes = coaf.filtrar_clientes_excluidos(casos, cfg_com_exclusao)
    assert {c["nome_cliente"] for c in restantes} == {"OUTRO CLIENTE"}


def test_filtrar_clientes_excluidos_por_codigo(cfg):
    df = pd.DataFrame([_lancamento(VALOR=31000.0, CLIENTE="34642", HISTORICO="SAQUE")])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg)
    assert len(casos) == 1

    cfg_com_exclusao = dict(cfg, clientes_excluidos={"nomes": [], "codigos": ["34642"]})
    assert coaf.filtrar_clientes_excluidos(casos, cfg_com_exclusao) == []


def test_filtrar_clientes_excluidos_sem_regra_nao_muda_nada(cfg):
    df = pd.DataFrame([_lancamento(VALOR=31000.0)])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg)
    assert coaf.filtrar_clientes_excluidos(casos, cfg) == casos


def test_mesmo_cliente_em_revendas_diferentes_soma_no_escopo_grupo(cfg):
    """Escopo 'grupo': fracionamento entre lojas não pode escapar."""
    df = pd.DataFrame(
        [
            _lancamento(VALOR=16000.0, TITULO="T1"),
            _lancamento(
                VALOR=16000.0, TITULO="T2", REVENDA="KOBE NISSAN VV", DATA=date(2026, 5, 12)
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    casos = coaf.detectar(prep, cfg)
    assert len(casos) == 1
    assert casos[0]["total"] == 32000.0
    assert len(casos[0]["revendas"]) == 2


# --------------------------------------------------------------------------- #
# Histórico permanente vs. deduplicação — o requisito central
# --------------------------------------------------------------------------- #
def _caso_pronto(cfg, valor=31000.0):
    df = pd.DataFrame([_lancamento(VALOR=valor)])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    return coaf.detectar(prep, cfg)


def test_primeira_deteccao_e_marcada_e_gravada(con, cfg):
    novos = coaf.persistir(con, _caso_pronto(cfg), "grupo")
    assert len(novos) == 1
    assert novos[0]["primeira_deteccao"] is True
    assert con.execute("SELECT COUNT(*) FROM coaf_deteccao").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM coaf_deteccao_lancamento").fetchone()[0] == 1


def test_segunda_execucao_identica_nao_gera_novidade(con, cfg):
    coaf.persistir(con, _caso_pronto(cfg), "grupo")
    antes = con.execute("SELECT COUNT(*) FROM coaf_deteccao").fetchone()[0]

    novos = coaf.persistir(con, _caso_pronto(cfg), "grupo")

    assert novos == []
    depois = con.execute("SELECT COUNT(*) FROM coaf_deteccao").fetchone()[0]
    assert depois == antes, "o histórico não pode encolher nem inchar"


def test_lancamento_novo_reabre_a_novidade(con, cfg):
    coaf.persistir(con, _caso_pronto(cfg), "grupo")
    df = pd.DataFrame(
        [_lancamento(VALOR=31000.0), _lancamento(VALOR=5000.0, TITULO="T2")]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))

    novos = coaf.persistir(con, coaf.detectar(prep, cfg), "grupo")

    assert len(novos) == 1
    assert novos[0]["primeira_deteccao"] is False
    assert novos[0]["total"] == 36000.0
    assert con.execute("SELECT COUNT(*) FROM coaf_deteccao").fetchone()[0] == 2


def test_cliente_notificado_permanece_no_historico(con, cfg):
    """O requisito central: notificar tira da fila de e-mail, não do histórico."""
    casos = _caso_pronto(cfg)
    coaf.persistir(con, casos, "grupo")
    chave = casos[0]["chave_cliente"]

    estado.registrar_notificacao(
        con, chave, "grupo", "gerente@empresa.com", casos[0]["id_deteccao"],
        "reports/dmf/x.pdf", estado.STATUS_ENVIADO,
    )

    # Sai da fila de envio...
    ultimos = estado.ultima_notificacao(con, "grupo")
    assert (chave, "gerente@empresa.com") in ultimos

    # ...mas continua no histórico, com a data do envio.
    hist = estado.carregar_historico(con, "grupo")
    assert len(hist) == 1
    assert hist.iloc[0]["chave_cliente"] == chave
    assert pd.notna(hist.iloc[0]["notificado_em"])

    # E aparece no relatório de histórico.
    markdown = coaf.montar_relatorio_historico(hist)
    assert "FULANO DE TAL" in markdown


def test_historico_acumula_varios_clientes(con, cfg):
    coaf.persistir(con, _caso_pronto(cfg), "grupo")
    df = pd.DataFrame(
        [_lancamento(VALOR=40000.0, CLIENTE="999", HISTORICO="Ref. NF: 2 Cliente: OUTRO CLIENTE")]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    coaf.persistir(con, coaf.detectar(prep, cfg), "grupo")

    hist = estado.carregar_historico(con, "grupo")
    assert len(hist) == 2
    assert set(hist["nome_cliente"]) == {"FULANO DE TAL", "OUTRO CLIENTE"}


def test_historico_consolida_codigo_com_chaves_antigas_diferentes(con, cfg):
    """O histórico agrega por CÓDIGO, não por chave_cliente (26/08/2026).

    A chave de identidade já mudou de esquema duas vezes em produção (nome do
    HISTORICO -> NOME_CLIENTE -> código — ver dictionary/regras_negocio.md).
    ``coaf_deteccao`` é append-only e guarda cada detecção com a chave do
    esquema vigente na hora — por isso o mesmo cliente real (código 225456)
    tem linhas com chaves diferentes. O relatório precisa consolidar isso
    numa linha só, sem alterar as tabelas de origem.
    """
    base = {
        "codigo_cliente": "225456",
        "escopo": "grupo",
        "empresa": "ROYAL ENFIELD",
        "revendas": "MULTICAR ROYAL - VI",
        "caixas": "1",
        "total": 51010.0,
        "qtd_lancamentos": 3,
        "janela_inicio": date(2026, 2, 19),
        "janela_fim": date(2026, 8, 19),
        "tem_caixa_sinalizado": False,
    }
    estado.gravar_deteccao(
        con,
        {
            **base,
            "id_deteccao": "det-esquema-nome-historico",
            "detectado_em": datetime(2026, 8, 19, 10, 0),
            "chave_cliente": "AGNALDO CEZAR BATISTA DE SOUZA",
            "nome_cliente": "AGNALDO CEZAR BATISTA DE SOUZA",
            "nome_identificado": True,
            "hash_lancamentos": "hash-1",
            "primeira_deteccao": True,
        },
        [],
    )
    estado.gravar_deteccao(
        con,
        {
            **base,
            "id_deteccao": "det-esquema-codigo",
            "detectado_em": datetime(2026, 8, 26, 12, 0),
            "chave_cliente": "225456",
            "nome_cliente": "AGNALDO CEZAR SOUZA",
            "nome_identificado": True,
            "hash_lancamentos": "hash-2",
            "primeira_deteccao": True,
        },
        [],
    )

    hist = estado.carregar_historico(con, "grupo")
    assert len(hist) == 1
    linha = hist.iloc[0]
    assert linha["codigo_cliente"] == "225456"
    assert linha["vezes_detectado"] == 2
    assert linha["nome_cliente"] == "AGNALDO CEZAR SOUZA"
    assert linha["chave_cliente"] == "225456"
    assert linha["primeira_deteccao_em"] == datetime(2026, 8, 19, 10, 0)
    assert linha["ultima_deteccao_em"] == datetime(2026, 8, 26, 12, 0)


def test_lancamentos_da_deteccao_permitem_reconstruir_a_dmf(con, cfg):
    """A base é de refresh contínuo; sem a cópia local a DMF enviada some."""
    casos = _caso_pronto(cfg)
    coaf.persistir(con, casos, "grupo")
    lancs = estado.lancamentos_da_deteccao(con, casos[0]["id_deteccao"])
    assert len(lancs) == 1
    assert float(lancs.iloc[0]["valor"]) == 31000.0
    assert lancs.iloc[0]["revenda"] == "KOBE NISSAN GV"


# --------------------------------------------------------------------------- #
# Hashes
# --------------------------------------------------------------------------- #
def test_hash_lancamento_independe_do_tipo_da_data():
    a = estado.hash_lancamento("R", "2", date(2026, 3, 27), "1", 100.0, "O")
    b = estado.hash_lancamento("R", "2", "2026-03-27T00:00:00", "1", 100.0, "O")
    assert a == b


def test_hash_conjunto_independe_da_ordem():
    assert estado.hash_conjunto(["a", "b"]) == estado.hash_conjunto(["b", "a"])


def test_hash_lancamento_muda_com_o_valor():
    a = estado.hash_lancamento("R", "2", date(2026, 3, 27), "1", 100.0, "O")
    b = estado.hash_lancamento("R", "2", date(2026, 3, 27), "1", 100.01, "O")
    assert a != b


# --------------------------------------------------------------------------- #
# Formatação
# --------------------------------------------------------------------------- #
def test_moeda_em_padrao_brasileiro():
    assert coaf.fmt_moeda(1234567.8) == "1.234.567,80"
    assert coaf.fmt_moeda(30000) == "30.000,00"
    assert coaf.fmt_moeda(0.5) == "0,50"


# --------------------------------------------------------------------------- #
# PDF — rótulo do emissor
# --------------------------------------------------------------------------- #
def test_rotulo_do_emissor_com_uma_empresa():
    from analysis.dmf_pdf import _rotulo_emissor

    assert _rotulo_emissor({"empresa": "KOBE"}) == "KOBE"


def test_rotulo_do_emissor_com_varias_empresas_vira_consolidado():
    """Um cliente chega a aparecer em 8 marcas; a lista inteira estoura a faixa
    do cabeçalho e colide com o nome do documento (design system §1)."""
    from analysis.dmf_pdf import _rotulo_emissor

    muitas = "CORRETORA / KOBE / MEGA STORE / MIT / MULT BOATS / OMODA / RENAULT"
    assert _rotulo_emissor({"empresa": muitas}) == "Consolidado"


def test_nome_do_arquivo_e_ascii_puro():
    """Acento em nome de arquivo vira mojibake em console e anexo de e-mail."""
    from analysis.dmf_pdf import nome_arquivo_dmf

    nome = nome_arquivo_dmf(
        {
            "revenda_principal": "MULTICAR ROYAL - VI",
            "nome_cliente": "JOSÉ DA CONCEIÇÃO ANDRÉ",
        }
    )
    assert nome.isascii(), nome
    assert nome.startswith("DMF_MULTICAR-ROYAL---VI_JOSE-DA-CONCEICAO-ANDRE_")
    assert nome.endswith(".pdf")


# --------------------------------------------------------------------------- #
# Roteamento: quem recebe a cobrança
# --------------------------------------------------------------------------- #
def _config_fake():
    from config.settings import Configuracao

    return Configuracao(
        auth_mode="device_code",
        tenant_id="t",
        client_id="c",
        client_secret=None,
        workspace_id="w",
        dataset_id="d",
    )


def _destinatarios(mapa=None):
    return {
        "email_coaf": "coaf@empresa.com",
        "email_padrao": "fallback@empresa.com",
        "responsavel_padrao": "Controladoria",
        "mapa": mapa
        if mapa is not None
        else {
            ("KOBE NISSAN GV", "2"): {"nome": "Ana", "email": "ana@empresa.com"},
            ("KOBE NISSAN VV", "1"): {"nome": "Bruno", "email": "bruno@empresa.com"},
        },
    }


def test_gatilho_e_o_lancamento_que_cruza_o_limiar(cfg):
    """Três de R$ 12 mil: o acumulado passa de 30 mil no TERCEIRO."""
    df = pd.DataFrame(
        [
            _lancamento(DATA=date(2026, 5, 1), VALOR=12000.0, TITULO="T1", CAIXA="2"),
            _lancamento(
                DATA=date(2026, 5, 5), VALOR=12000.0, TITULO="T2",
                REVENDA="KOBE NISSAN VV", CAIXA="1",
            ),
            _lancamento(
                DATA=date(2026, 5, 9), VALOR=12000.0, TITULO="T3",
                REVENDA="KOBE NISSAN MH", CAIXA="7",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    caso = coaf.detectar(prep, cfg)[0]

    assert caso["total"] == 36000.0
    gatilho = caso["gatilho"]
    assert gatilho["titulo"] == "T3"
    assert gatilho["revenda"] == "KOBE NISSAN MH"
    assert gatilho["caixa"] == "7"
    assert gatilho["acumulado_no_gatilho"] == 36000.0


def test_gatilho_e_quem_cruzou_nao_quem_lancou_por_ultimo(cfg):
    """Decisão do gestor (19/08/2026): o gatilho é o lançamento que CRUZOU o
    limiar, não o mais recente do período.

    As duas leituras só divergem quando o cliente continua comprando depois de
    já ter estourado os R$ 30 mil — e é justamente aí que a escolha importa,
    porque manda a cobrança para caixas diferentes. Quem recebeu o dinheiro que
    estourou o limite é quem responde; quem recebeu os R$ 5 mil seguintes não
    teve nada a ver com isso.

    Este teste existe para impedir que a regra seja trocada sem querer.
    """
    df = pd.DataFrame(
        [
            _lancamento(DATA=date(2026, 5, 10), VALOR=12000.0, TITULO="T1", CAIXA="2"),
            _lancamento(
                DATA=date(2026, 5, 20), VALOR=12000.0, TITULO="T2",
                REVENDA="KOBE NISSAN VV", CAIXA="1",
            ),
            # Cruza o limiar aqui: 24.000 -> 36.000.
            _lancamento(
                DATA=date(2026, 6, 1), VALOR=12000.0, TITULO="T3",
                REVENDA="KOBE NISSAN MH", CAIXA="7",
            ),
            # Mais recente, mas irrelevante para a obrigação.
            _lancamento(
                DATA=date(2026, 6, 15), VALOR=5000.0, TITULO="T4",
                REVENDA="KOBE NISSAN IP", CAIXA="1",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    caso = coaf.detectar(prep, cfg)[0]

    assert caso["total"] == 41000.0
    gatilho = caso["gatilho"]
    assert gatilho["titulo"] == "T3", "o gatilho é o que cruzou, não o mais recente"
    assert gatilho["revenda"] == "KOBE NISSAN MH"
    assert gatilho["caixa"] == "7"
    assert gatilho["acumulado_no_gatilho"] == 36000.0

    ultimo = caso["lancamentos"].iloc[-1]
    assert ultimo["TITULO"] == "T4"
    assert gatilho["caixa"] != ultimo["CAIXA"], (
        "cenário inútil se os dois lançamentos caírem no mesmo caixa"
    )


def test_destinatario_e_o_caixa_do_gatilho(cfg):
    """A apuração é do grupo, mas a cobrança vai para UM caixa: o do gatilho."""
    from notify.email_zoho import destinatario_do_caso

    df = pd.DataFrame(
        [
            _lancamento(DATA=date(2026, 5, 1), VALOR=16000.0, TITULO="T1", CAIXA="2"),
            _lancamento(
                DATA=date(2026, 5, 5), VALOR=16000.0, TITULO="T2",
                REVENDA="KOBE NISSAN VV", CAIXA="1",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    caso = coaf.detectar(prep, cfg)[0]

    rotulo, nome, email = destinatario_do_caso(caso, _destinatarios())

    assert email == ["bruno@empresa.com"], "deveria ir ao caixa do 2º lançamento"
    assert nome == "Bruno"
    assert "KOBE NISSAN VV" in rotulo
    assert "ana@empresa.com" not in email


def test_caixa_sem_responsavel_cai_no_email_padrao(cfg):
    from notify.email_zoho import destinatario_do_caso

    caso = _caso_pronto(cfg)[0]
    _rotulo, _nome, email = destinatario_do_caso(caso, _destinatarios(mapa={}))
    assert email == ["fallback@empresa.com"]


# --------------------------------------------------------------------------- #
# Anexos: uma DMF por empresa, consolidado só para o COAF
# --------------------------------------------------------------------------- #
def test_uma_dmf_por_empresa_do_grupo(cfg):
    """Cliente com recebimento em três marcas gera três sub-casos."""
    df = pd.DataFrame(
        [
            _lancamento(DATA=date(2026, 5, 1), VALOR=12000.0, TITULO="T1"),
            _lancamento(
                DATA=date(2026, 5, 5), VALOR=12000.0, TITULO="T2",
                EMPRESA="MIT", REVENDA="MULTICAR MITS VV", CAIXA="2",
            ),
            _lancamento(
                DATA=date(2026, 5, 9), VALOR=12000.0, TITULO="T3",
                EMPRESA="ROYAL ENFIELD", REVENDA="MULTICAR ROYAL - VI", CAIXA="1",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    caso = coaf.detectar(prep, cfg)[0]

    subs = coaf.dividir_por_empresa(caso)

    assert len(subs) == 3
    assert {s["empresa"] for s in subs} == {"KOBE", "MIT", "ROYAL ENFIELD"}
    assert sum(s["total"] for s in subs) == caso["total"]
    for sub in subs:
        assert sub["total"] == 12000.0
        assert sub["qtd_lancamentos"] == 1
        assert sub["nome_cliente"] == caso["nome_cliente"]


def test_consolidado_e_dmfs_por_empresa_sao_gerados(cfg, tmp_path):
    from analysis.dmf_pdf import gerar_dmf, gerar_relatorio_consolidado

    df = pd.DataFrame(
        [
            _lancamento(DATA=date(2026, 5, 1), VALOR=20000.0, TITULO="T1"),
            _lancamento(
                DATA=date(2026, 5, 5), VALOR=15000.0, TITULO="T2",
                EMPRESA="MIT", REVENDA="MULTICAR MITS VV", CAIXA="2",
            ),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    caso = coaf.detectar(prep, cfg)[0]

    dmfs = [
        gerar_dmf(sub, _destinatarios(), tmp_path)
        for sub in coaf.dividir_por_empresa(caso)
    ]
    consolidado = gerar_relatorio_consolidado(caso, tmp_path)

    assert len(dmfs) == 2
    assert all(p.exists() and p.stat().st_size > 0 for p in dmfs)
    assert consolidado.exists()
    assert consolidado.name.startswith("COAF-CONSOLIDADO_")
    assert len({p.name for p in dmfs}) == 2, "nomes de arquivo não podem colidir"


def test_coaf_recebe_consolidado_e_responsavel_nao(con, cfg, monkeypatch):
    """O relatório do grupo é exclusivo do compliance."""
    from notify import email_zoho

    recebidos: list[tuple[str, list]] = []
    monkeypatch.setattr(
        email_zoho,
        "enviar",
        lambda cfg_, dest, cc, assunto, corpo, anexos=(): recebidos.append(
            (dest[0], [str(a) for a in anexos])
        ),
    )

    casos = _caso_pronto(cfg)
    coaf.persistir(con, casos, "grupo")
    coaf.enriquecer_com_incremento(con, casos, "grupo", 30000.0)
    anexos = {
        casos[0]["chave_cliente"]: {
            "empresas": ["dmf_kobe.pdf"],
            "consolidado": "consolidado.pdf",
            "complementar": None,
        }
    }

    email_zoho.notificar_casos(
        con=con, casos=casos, anexos_por_caso=anexos,
        destinatarios=_destinatarios(), cfg=cfg, config=_config_fake(),
        escopo="grupo", enviar=True,
    )

    por_destino = dict(recebidos)
    assert por_destino["ana@empresa.com"] == ["dmf_kobe.pdf"]
    assert "consolidado.pdf" not in por_destino["ana@empresa.com"]
    assert por_destino["coaf@empresa.com"] == ["consolidado.pdf", "dmf_kobe.pdf"]


def _caso_sem_nome(cfg, valor=30000.0):
    df = pd.DataFrame(
        [_lancamento(VALOR=valor, HISTORICO="SAQUE CHEQUE Nº 161", CLIENTE="34642")]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    return coaf.detectar(prep, cfg)


def test_cliente_nao_identificado_vai_so_para_o_coaf(con, cfg, monkeypatch):
    """Rede de segurança (21/08/2026): sem nome, nada vai ao responsável do
    caixa — só o COAF recebe, com todos os anexos, para investigar."""
    from notify import email_zoho

    recebidos: list[tuple[str, list]] = []
    monkeypatch.setattr(
        email_zoho,
        "enviar",
        lambda cfg_, dest, cc, assunto, corpo, anexos=(): recebidos.append(
            (dest[0], [str(a) for a in anexos])
        ),
    )

    casos = _caso_sem_nome(cfg)
    assert casos[0]["nome_identificado"] is False
    coaf.persistir(con, casos, "grupo")
    coaf.enriquecer_com_incremento(con, casos, "grupo", 30000.0)
    anexos = {
        casos[0]["chave_cliente"]: {
            "empresas": ["dmf_kobe.pdf"],
            "consolidado": "consolidado.pdf",
            "complementar": None,
        }
    }

    resultado = email_zoho.notificar_casos(
        con=con, casos=casos, anexos_por_caso=anexos,
        destinatarios=_destinatarios(), cfg=cfg, config=_config_fake(),
        escopo="grupo", enviar=True,
    )

    assert resultado["enviados"] == 1
    assert len(recebidos) == 1, "deve haver exatamente 1 mensagem, não 2"
    destino, anexos_enviados = recebidos[0]
    assert destino == "coaf@empresa.com"
    assert set(anexos_enviados) == {"dmf_kobe.pdf", "consolidado.pdf"}

    status = con.execute(
        "SELECT status, destinatario FROM coaf_notificacao"
    ).fetchall()
    assert status == [(estado.STATUS_ENVIADO, "coaf@empresa.com")]


def test_cliente_nao_identificado_assunto_sinaliza_isso(cfg):
    from notify.email_zoho import montar_mensagem_sem_identificacao

    caso = _caso_sem_nome(cfg)[0]
    assunto, corpo = montar_mensagem_sem_identificacao(caso, 30000.0)
    assert "SEM IDENTIFICAÇÃO" in assunto
    assert caso["codigo_cliente"] in assunto
    assert "identificação manual" in corpo.lower() or "identificar" in corpo.lower()


def test_modo_revisao_nao_envia_nada(con, cfg, monkeypatch):
    from notify import email_zoho

    def _explodir(*args, **kwargs):
        raise AssertionError("modo revisão não pode enviar e-mail")

    monkeypatch.setattr(email_zoho, "enviar", _explodir)

    casos = _caso_pronto(cfg)
    coaf.persistir(con, casos, "grupo")
    coaf.enriquecer_com_incremento(con, casos, "grupo", 30000.0)

    resultado = email_zoho.notificar_casos(
        con=con, casos=casos, anexos_por_caso={}, destinatarios=_destinatarios(),
        cfg=cfg, config=_config_fake(), escopo="grupo", enviar=False,
    )

    assert resultado["enviados"] == 0
    assert resultado["suprimidos"] == 1
    status = {s for (s,) in con.execute("SELECT DISTINCT status FROM coaf_notificacao").fetchall()}
    assert status == {estado.STATUS_SUPRIMIDO}


# --------------------------------------------------------------------------- #
# Reenvio: o incremento isolado, sem carência por tempo
# --------------------------------------------------------------------------- #
def _notificar(con, cfg, casos, monkeypatch, mod):
    """Dispara a notificação e devolve só quem NÃO é o COAF.

    O setor de compliance é avisado em todo caso; o que os testes de reenvio
    querem saber é se o **responsável pelo caixa** foi acionado.
    """
    enviados: list[str] = []
    monkeypatch.setattr(
        mod, "enviar", lambda c, d, cc, a, b, anexos=(): enviados.append(d[0])
    )
    mod.notificar_casos(
        con=con, casos=casos, anexos_por_caso={}, destinatarios=_destinatarios(),
        cfg=cfg, config=_config_fake(), escopo="grupo", enviar=True,
    )
    return [e for e in enviados if e != "coaf@empresa.com"]


def test_novo_cruzamento_de_30k_notifica_de_novo(con, cfg, monkeypatch):
    """A pergunta do gestor: cliente já avisado que recebe mais 30 mil.

    A versão anterior tinha carência de 30 dias e engolia este caso. Agora o que
    conta é o incremento isolado: R$ 35 mil novos atingem o limiar sozinhos,
    então sai nova cobrança — 15 dias depois da primeira, não 30.
    """
    from notify import email_zoho

    df1 = pd.DataFrame([_lancamento(DATA=date(2026, 3, 10), VALOR=31000.0, TITULO="T1")])
    prep1 = coaf.preparar_lancamentos(df1, cfg, hoje=date(2026, 3, 15))
    casos1 = coaf.detectar(prep1, cfg, hoje=date(2026, 3, 15))
    coaf.persistir(con, casos1, "grupo")
    coaf.enriquecer_com_incremento(con, casos1, "grupo", 30000.0)
    assert coaf.deve_notificar(casos1[0], 30000.0) is True
    assert _notificar(con, cfg, casos1, monkeypatch, email_zoho) == ["ana@empresa.com"]

    df2 = pd.DataFrame(
        [
            _lancamento(DATA=date(2026, 3, 10), VALOR=31000.0, TITULO="T1"),
            _lancamento(DATA=date(2026, 3, 25), VALOR=35000.0, TITULO="T2"),
        ]
    )
    prep2 = coaf.preparar_lancamentos(df2, cfg, hoje=date(2026, 3, 26))
    casos2 = coaf.detectar(prep2, cfg, hoje=date(2026, 3, 26))
    coaf.persistir(con, casos2, "grupo")
    coaf.enriquecer_com_incremento(con, casos2, "grupo", 30000.0)

    assert casos2[0]["ja_notificado"] is True
    assert casos2[0]["incremento"] == 35000.0, "o já declarado não entra na conta"
    assert casos2[0]["total"] == 66000.0, "a DMF continua cumulativa"
    assert coaf.deve_notificar(casos2[0], 30000.0) is True
    assert _notificar(con, cfg, casos2, monkeypatch, email_zoho) == ["ana@empresa.com"]


def test_incremento_abaixo_do_limiar_nao_notifica(con, cfg, monkeypatch):
    """R$ 5 mil novos não somam com os R$ 31 mil já declarados."""
    from notify import email_zoho

    df1 = pd.DataFrame([_lancamento(DATA=date(2026, 3, 10), VALOR=31000.0, TITULO="T1")])
    prep1 = coaf.preparar_lancamentos(df1, cfg, hoje=date(2026, 3, 15))
    casos1 = coaf.detectar(prep1, cfg, hoje=date(2026, 3, 15))
    coaf.persistir(con, casos1, "grupo")
    coaf.enriquecer_com_incremento(con, casos1, "grupo", 30000.0)
    _notificar(con, cfg, casos1, monkeypatch, email_zoho)

    df2 = pd.DataFrame(
        [
            _lancamento(DATA=date(2026, 3, 10), VALOR=31000.0, TITULO="T1"),
            _lancamento(DATA=date(2026, 3, 25), VALOR=5000.0, TITULO="T2"),
        ]
    )
    prep2 = coaf.preparar_lancamentos(df2, cfg, hoje=date(2026, 3, 26))
    casos2 = coaf.detectar(prep2, cfg, hoje=date(2026, 3, 26))
    coaf.persistir(con, casos2, "grupo")
    coaf.enriquecer_com_incremento(con, casos2, "grupo", 30000.0)

    assert casos2[0]["incremento"] == 5000.0
    assert coaf.deve_notificar(casos2[0], 30000.0) is False


def test_copia_da_dmf_vai_so_ao_responsavel_nao_ao_coaf(con, cfg, monkeypatch):
    """``email_copia_dmf`` entra em Cc da DMF do caixa; o consolidado do COAF
    continua indo só para ``email_coaf`` (decisão do gestor, 17/09/2026)."""
    from notify import email_zoho

    df = pd.DataFrame([_lancamento(DATA=date(2026, 3, 10), VALOR=31000.0)])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 3, 15))
    casos = coaf.detectar(prep, cfg, hoje=date(2026, 3, 15))
    coaf.persistir(con, casos, "grupo")
    coaf.enriquecer_com_incremento(con, casos, "grupo", 30000.0)

    chamadas: list[tuple[list[str], list[str]]] = []
    monkeypatch.setattr(
        email_zoho, "enviar",
        lambda c, para, cc, a, b, anexos=(): chamadas.append((list(para), list(cc))),
    )
    destinatarios = _destinatarios()
    destinatarios["email_copia_dmf"] = "compliance@empresa.com, ana@empresa.com"
    email_zoho.notificar_casos(
        con=con, casos=casos, anexos_por_caso={}, destinatarios=destinatarios,
        cfg=cfg, config=_config_fake(), escopo="grupo", enviar=True,
    )

    # 1) DMF ao responsável: Ana no Para; compliance em Cc; Ana não repete no Cc.
    # 2) Consolidado ao COAF: sem cópia nenhuma.
    assert chamadas == [
        (["ana@empresa.com"], ["compliance@empresa.com"]),
        (["coaf@empresa.com"], []),
    ]
    # A cópia fica registrada no histórico como notificada.
    notificados = {
        d for (d,) in con.execute(
            "SELECT DISTINCT destinatario FROM coaf_notificacao WHERE status = ?",
            [estado.STATUS_ENVIADO],
        ).fetchall()
    }
    assert notificados == {"ana@empresa.com", "compliance@empresa.com", "coaf@empresa.com"}


def test_gatilho_do_incremento_endereca_o_novo_cruzamento(con, cfg):
    """No reenvio, quem responde é o caixa do lançamento que fechou o incremento."""
    from notify.email_zoho import destinatario_do_caso

    df1 = pd.DataFrame([_lancamento(DATA=date(2026, 3, 10), VALOR=31000.0, TITULO="T1")])
    prep1 = coaf.preparar_lancamentos(df1, cfg, hoje=date(2026, 3, 15))
    casos1 = coaf.detectar(prep1, cfg, hoje=date(2026, 3, 15))
    coaf.persistir(con, casos1, "grupo")
    estado.registrar_notificacao(
        con, casos1[0]["chave_cliente"], "grupo", "ana@empresa.com",
        casos1[0]["id_deteccao"], "x.pdf", estado.STATUS_ENVIADO,
    )

    df2 = pd.DataFrame(
        [
            _lancamento(DATA=date(2026, 3, 10), VALOR=31000.0, TITULO="T1"),
            _lancamento(
                DATA=date(2026, 3, 25), VALOR=35000.0, TITULO="T2",
                REVENDA="KOBE NISSAN VV", CAIXA="1",
            ),
        ]
    )
    prep2 = coaf.preparar_lancamentos(df2, cfg, hoje=date(2026, 3, 26))
    casos2 = coaf.detectar(prep2, cfg, hoje=date(2026, 3, 26))
    coaf.enriquecer_com_incremento(con, casos2, "grupo", 30000.0)

    assert casos2[0]["gatilho_incremento"]["titulo"] == "T2"
    _rotulo, nome, email = destinatario_do_caso(casos2[0], _destinatarios())
    assert email == ["bruno@empresa.com"]
    assert nome == "Bruno"


# --------------------------------------------------------------------------- #
# Documento do cliente (colunas Fisjur e cpf_cnpj, 19/08/2026)
# --------------------------------------------------------------------------- #
def test_cnpj_e_formatado_com_mascara():
    assert coaf.formatar_documento("14488355000186", "J") == (
        "J", "14.488.355/0001-86",
    )


def test_cpf_recupera_o_zero_a_esquerda():
    """A base guarda o documento como número: o zero inicial se perde.

    VALDETE TEIXEIRA DA SILVA chega como 6418722671 (10 dígitos). Sem o
    preenchimento à esquerda, a DMF sairia com um CPF inválido.
    """
    assert coaf.formatar_documento("6418722671", "F") == ("F", "064.187.226-71")


def test_documento_lixo_nao_vira_cpf_falso():
    """Preencher 123 com zeros produziria 000.000.001-23 — pior que em branco."""
    assert coaf.formatar_documento("123", "O") == ("", "")
    assert coaf.formatar_documento("0", "F") == ("F", "")
    assert coaf.formatar_documento(None, "J") == ("J", "")


def test_tipo_desconhecido_deduz_pelo_comprimento():
    """Fisjur tem um terceiro valor, "O", em 97 lançamentos."""
    tipo, doc = coaf.formatar_documento("14488355000186", "O")
    assert (tipo, doc) == ("J", "14.488.355/0001-86")


@pytest.mark.parametrize(
    "tipo, esperado",
    [
        ("J", ("RAZÃO SOCIAL", "CNPJ")),
        ("F", ("NOME", "CPF")),
        ("", ("RAZÃO SOCIAL / NOME", "CNPJ / CPF")),
    ],
)
def test_rotulos_dos_campos_1_e_2(tipo, esperado):
    assert coaf.rotulos_do_declarante(tipo) == esperado


def test_caso_carrega_documento_e_razao_social(cfg):
    df = pd.DataFrame(
        [
            _lancamento(
                VALOR=31000.0, FISJUR="J", CPF_CNPJ="14488355000186",
                RAZAO_SOCIAL="6 - MULTI COMERCIO DE VEICULOS LTDA",
            )
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 19))[0]

    assert caso["tipo_pessoa"] == "J"
    assert caso["documento"] == "14.488.355/0001-86"
    assert caso["razao_social"] == "6 - MULTI COMERCIO DE VEICULOS LTDA"


def test_modelo_sem_as_colunas_novas_nao_quebra(cfg):
    """Tolerância a modelo antigo: a DMF sai com os campos em branco."""
    df = pd.DataFrame([_lancamento(VALOR=31000.0)])
    df = df.drop(columns=[c for c in ("FISJUR", "CPF_CNPJ", "RAZAO_SOCIAL") if c in df])
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 19))[0]

    assert caso["tipo_pessoa"] == ""
    assert caso["documento"] == ""
    assert caso["razao_social"] == ""


def test_razao_social_predominante_por_valor(cfg):
    """RAZAO_SOCIAL varia por filial dentro da mesma empresa (KOBE tem 9)."""
    df = pd.DataFrame(
        [
            _lancamento(VALOR=5000.0, TITULO="T1", RAZAO_SOCIAL="1 - LAGE E SCARABELI LTDA"),
            _lancamento(VALOR=26000.0, TITULO="T2", RAZAO_SOCIAL="6 - LAGE E SCARABELI LTDA"),
        ]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 19))[0]
    assert caso["razao_social"] == "6 - LAGE E SCARABELI LTDA"


# --------------------------------------------------------------------------- #
# Segurança: o documento circula fora da empresa
# --------------------------------------------------------------------------- #
def test_pdf_nao_expoe_origem_tecnica_do_dado(cfg, tmp_path):
    """A DMF vai ao cliente para assinatura. Nomear a ferramenta ou o dataset
    entrega a um terceiro o caminho para pedir acesso."""
    import pdfplumber

    from analysis.dmf_pdf import gerar_dmf, gerar_relatorio_consolidado

    df = pd.DataFrame(
        [_lancamento(VALOR=31000.0, FISJUR="J", CPF_CNPJ="14488355000186")]
    )
    prep = coaf.preparar_lancamentos(df, cfg, hoje=date(2026, 8, 19))
    caso = coaf.detectar(prep, cfg, hoje=date(2026, 8, 19))[0]

    for caminho in (
        gerar_dmf(caso, {"mapa": {}}, tmp_path),
        gerar_relatorio_consolidado(caso, tmp_path),
    ):
        with pdfplumber.open(caminho) as pdf:
            texto = "\n".join(p.extract_text() or "" for p in pdf.pages)
        baixo = texto.lower()
        for proibido in ("lancamentos_financeiros", "power bi", "powerbi", "dataset"):
            assert proibido not in baixo, f"{caminho.name} expõe {proibido!r}"
        assert "Gerado em" in texto
        assert "Uso interno" in texto
        assert "Página" in texto


def test_email_nao_expoe_origem_tecnica(cfg):
    from notify.email_zoho import montar_mensagem, montar_mensagem_coaf

    caso = _caso_pronto(cfg)[0]
    _a, corpo = montar_mensagem(caso, 30000.0)
    _a2, corpo_coaf = montar_mensagem_coaf(caso, 30000.0, "REV / caixa 1", "F", "f@x.com")
    for texto in (corpo, corpo_coaf):
        baixo = texto.lower()
        for proibido in ("lancamentos_financeiros", "power bi", "dataset", "semântico"):
            assert proibido not in baixo, proibido
