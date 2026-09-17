"""Migração pontual (26/08/2026): reavalia o histórico do COAF com
``CAIXAS[NOME_CLIENTE]`` como fonte primária do nome, e marca como já
notificado tudo que a nova chave encontrar na janela de 19/02 a 24/08/2026.

Contexto
--------

``analysis/coaf_especie.py`` passou a usar ``NOME_CLIENTE`` como fonte
primária do nome do cliente (decisão do gestor, 26/08/2026), no lugar do
parser de ``HISTORICO``. Como a chave de agregação é o nome, essa troca muda
a chave de qualquer cliente cujo ``NOME_CLIENTE`` seja formatado diferente do
nome que o ``HISTORICO`` produzia — e um cliente já notificado sob a chave
antiga vira, aos olhos do sistema, um cliente "novo" sob a chave nova. Sem
esta migração, isso dispararia um novo e-mail de "estreia" (com DMF real) para
todo caso cuja formatação de nome mudou — foi exatamente o que aconteceu, sem
aviso, com o código 225456 em 26/08/2026 (ver
``dictionary/regras_negocio.md``, seção "Identidade do cliente").

O que este script faz
----------------------

1. Consulta o Power BI (mesma consulta de ``executar()``, ``meses_consulta``
   meses de histórico) e recalcula a detecção com ``hoje = 24/08/2026`` — a
   data da última notificação real conhecida antes da virada de chave — usando
   a lógica ATUAL (``NOME_CLIENTE`` primário). Isso reproduz a janela de
   19/02 a 24/08/2026 pedida pelo gestor.
2. Grava cada caso encontrado em ``coaf_deteccao``/``coaf_deteccao_lancamento``
   (mesma função ``persistir`` usada pela execução normal — respeita
   ``clientes_excluidos``).
3. Para cada caso, registra em ``coaf_notificacao`` um envio com
   ``status = 'enviado'`` para o responsável do caixa-gatilho e para o COAF —
   **sem mandar nenhum e-mail de verdade**. Isso "declara" os lançamentos da
   janela como já cobertos: o próximo cálculo de incremento
   (``enriquecer_com_incremento``) só vai contar lançamentos POSTERIORES a
   24/08/2026 como novidade.

Nada é apagado. As linhas antigas (chave pelo nome de ``HISTORICO``, inclusive
a notificação indevida do código 225456) continuam no histórico, como sempre —
esta migração só acrescenta o estado sob a chave nova.

Uso:
    .venv/Scripts/python.exe scripts/coaf_migrar_nome_cliente.py
    .venv/Scripts/python.exe scripts/coaf_migrar_nome_cliente.py --confirmar
        (sem --confirmar, só mostra o que seria gravado — nada é escrito)
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from analysis.coaf_especie import (  # noqa: E402
    DATASET_PADRAO,
    carregar_config_coaf,
    carregar_destinatarios,
    detectar,
    filtrar_clientes_excluidos,
    persistir,
    preparar_lancamentos,
    subtrair_meses,
)
from config.settings import carregar_configuracao  # noqa: E402
from local_data import coaf_estado as estado  # noqa: E402
from notify.email_zoho import destinatario_do_caso  # noqa: E402
from powerbi import dax_coaf  # noqa: E402
from powerbi.client import PowerBIClient  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("coaf.migracao")

#: Data de corte da migração: última notificação real conhecida sob a chave
#: antiga (código 225456, 24/08/2026), véspera da mudança de cadastro que
#: expôs o problema.
HOJE_MIGRACAO = date(2026, 8, 24)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--confirmar",
        action="store_true",
        help="Grava de verdade. Sem esta flag, só mostra o que seria feito.",
    )
    args = parser.parse_args()

    cfg = carregar_config_coaf()
    destinatarios = carregar_destinatarios()
    config = carregar_configuracao()
    cliente = PowerBIClient(config=config)

    data_inicio = subtrair_meses(HOJE_MIGRACAO, int(cfg["meses_consulta"]))
    exc = cfg["exclusoes_origem"]
    caixas_excluidos = cfg["caixas_excluidos"]["global"]

    logger.info(
        "Consultando recebimentos de %s a %s (dataset %s) para reavaliação "
        "com hoje=%s.",
        data_inicio, HOJE_MIGRACAO, DATASET_PADRAO, HOJE_MIGRACAO,
    )
    query = dax_coaf.recebimentos_especie(
        data_inicio, HOJE_MIGRACAO, exc["padroes"], exc["exatas"], caixas_excluidos
    )
    bruto = cliente.execute_dax(query, dataset_id=DATASET_PADRAO)
    df = preparar_lancamentos(bruto, cfg, HOJE_MIGRACAO)
    logger.info("Lançamentos válidos após higiene: %d.", len(df))

    escopo = str(cfg.get("escopo_alerta", "grupo")).lower()
    casos = detectar(df, cfg, HOJE_MIGRACAO)
    casos = filtrar_clientes_excluidos(casos, cfg)
    logger.info(
        "Clientes acima do limiar na janela até %s (NOME_CLIENTE como fonte "
        "primária): %d.",
        HOJE_MIGRACAO, len(casos),
    )

    if not casos:
        logger.info("Nada a migrar.")
        return 0

    for caso in sorted(casos, key=lambda c: c["nome_cliente"]):
        rotulo, _, emails = destinatario_do_caso(caso, destinatarios)
        logger.info(
            "  - %s (código %s): R$ %.2f | %d lançamento(s) | gatilho: %s | "
            "destinatário: %s",
            caso["nome_cliente"], caso["codigo_cliente"], caso["total"],
            caso["qtd_lancamentos"], rotulo, ", ".join(emails) or "(nenhum)",
        )

    if not args.confirmar:
        logger.info(
            "Simulação (sem --confirmar): nada foi gravado no DuckDB. Rode de "
            "novo com --confirmar para aplicar."
        )
        return 0

    email_coaf = (destinatarios.get("email_coaf") or "").strip()
    agora = datetime.now()
    nota = f"(migração {agora:%d/%m/%Y} — reavaliação retroativa com NOME_CLIENTE, sem PDF/e-mail real)"

    con = estado.abrir()
    try:
        novos = persistir(con, casos, escopo)
        logger.info(
            "Gravado em coaf_deteccao: %d caso(s) novo(s) ou alterado(s) sob a "
            "chave atual (de %d avaliados).",
            len(novos), len(casos),
        )

        registros = 0
        for caso in casos:
            chave = caso["chave_cliente"]
            id_det = caso["id_deteccao"]
            _, _, emails_resp = destinatario_do_caso(caso, destinatarios)
            for destino in [*emails_resp, email_coaf]:
                if not destino:
                    continue
                estado.registrar_notificacao(
                    con, chave, escopo, destino, id_det, nota,
                    estado.STATUS_ENVIADO, agora,
                )
                registros += 1
        logger.info(
            "Gravado em coaf_notificacao: %d registro(s) 'enviado' (sem envio "
            "real de e-mail) para %d caso(s).",
            registros, len(casos),
        )
    finally:
        con.close()

    logger.info("Migração concluída.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
