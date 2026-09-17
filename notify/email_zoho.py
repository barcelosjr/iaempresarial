"""Envio de e-mail pelo Zoho, para a cobrança da DMF assinada.

Usa só a biblioteca padrão (``smtplib`` + ``email.message.EmailMessage``) — o
projeto não tinha nenhuma infraestrutura de e-mail, e não vale acrescentar
dependência para um caso tão simples.

Quem recebe o quê
-----------------

A apuração é do **grupo inteiro** (soma todas as empresas e revendas, para
pegar fracionamento entre lojas), mas a cobrança tem **um dono só**: o
responsável pelo caixa da revenda onde foi feito o lançamento que levou o
acumulado do cliente a atingir o limiar. Um cliente que comprou em cinco lojas
gera uma cobrança, não cinco.

Esse responsável recebe uma DMF por empresa do grupo em que houve recebimento.
O setor de COAF recebe as mesmas DMFs **mais** o relatório consolidado do
grupo — que não vai para mais ninguém.

Duas salvaguardas deliberadas
-----------------------------

1. **Modo revisão é o padrão.** ``notificar_casos`` só envia de verdade com
   ``enviar=True`` (flag ``--enviar`` do job). Sem ela, tudo é gerado e
   registrado como ``suprimido_modo_revisao``, e nenhum gerente de loja recebe
   e-mail enquanto o compliance ainda está validando os primeiros PDFs.
2. **Falha de SMTP não derruba o job.** Assim como o snapshot em
   ``analysis/auditoria_diaria.py``, um erro de envio vira aviso no relatório —
   a detecção e o histórico já estão salvos, e perder o alerta inteiro porque o
   servidor de e-mail piscou seria bem pior.

Credenciais vêm exclusivamente do ``.env`` (``ZOHO_SMTP_*``), nunca aparecem em
log e nunca são impressas.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Sequence

from config.settings import Configuracao
from local_data import coaf_estado as estado

logger = logging.getLogger("coaf.email")

#: Porta de SSL implícito no Zoho. Qualquer outra porta usa STARTTLS.
PORTA_SSL = 465


class ErroEnvioEmail(Exception):
    """Falha ao enviar e-mail (conexão, autenticação ou destinatário)."""


def _fmt_moeda(valor: float) -> str:
    """``1234567.8`` -> ``"1.234.567,80"``."""
    return f"{valor:,.2f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def enviar(
    config: Configuracao,
    destinatarios: Sequence[str],
    copia: Sequence[str],
    assunto: str,
    corpo: str,
    anexos: Sequence[Path] = (),
) -> None:
    """Envia um e-mail com anexos pelo SMTP configurado.

    Args:
        config: Configuração do projeto, com as credenciais SMTP.
        destinatarios: E-mails no campo Para.
        copia: E-mails no campo Cc.
        assunto: Assunto da mensagem.
        corpo: Corpo em texto puro.
        anexos: Arquivos a anexar (PDFs da DMF).

    Raises:
        ErroEnvioEmail: Se o SMTP não estiver configurado ou o envio falhar.
    """
    if not config.smtp_configurado:
        raise ErroEnvioEmail(
            "SMTP não configurado. Preencha ZOHO_SMTP_HOST, ZOHO_SMTP_USER e "
            "ZOHO_SMTP_PASSWORD no .env (a senha deve ser uma senha de "
            "aplicativo gerada no painel do Zoho)."
        )
    if not destinatarios and not copia:
        raise ErroEnvioEmail("Nenhum destinatário informado.")

    msg = EmailMessage()
    remetente = config.smtp_user
    if config.smtp_remetente_nome:
        remetente = f"{config.smtp_remetente_nome} <{config.smtp_user}>"
    msg["From"] = remetente
    msg["To"] = ", ".join(destinatarios)
    if copia:
        msg["Cc"] = ", ".join(copia)
    msg["Subject"] = assunto
    msg.set_content(corpo)

    for caminho in anexos:
        dados = Path(caminho).read_bytes()
        msg.add_attachment(
            dados,
            maintype="application",
            subtype="pdf",
            filename=Path(caminho).name,
        )

    contexto = ssl.create_default_context()
    try:
        if config.smtp_port == PORTA_SSL:
            with smtplib.SMTP_SSL(
                config.smtp_host, config.smtp_port, context=contexto, timeout=30
            ) as servidor:
                servidor.login(config.smtp_user, config.smtp_password)
                servidor.send_message(msg)
        else:
            with smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=30) as servidor:
                servidor.starttls(context=contexto)
                servidor.login(config.smtp_user, config.smtp_password)
                servidor.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise ErroEnvioEmail(
            "Autenticação SMTP recusada. No Zoho, ZOHO_SMTP_PASSWORD precisa ser "
            "uma senha de aplicativo (Segurança > Senhas de aplicativo), não a "
            f"senha da conta. Detalhe: {exc.smtp_code}"
        ) from exc
    except (smtplib.SMTPException, OSError) as exc:
        raise ErroEnvioEmail(f"Falha ao enviar e-mail: {exc}") from exc


def _emails_da_string(bruto: str) -> list[str]:
    """``"a@x.com, b@x.com"`` -> ``["a@x.com", "b@x.com"]``.

    Um caixa pode ter mais de um responsável — o campo ``email:`` do YAML
    aceita vários endereços separados por vírgula. Sem espaço em branco e sem
    duplicata.
    """
    vistos: list[str] = []
    for parte in str(bruto or "").split(","):
        e = parte.strip()
        if e and e not in vistos:
            vistos.append(e)
    return vistos


def destinatario_do_caso(
    caso: dict[str, Any], destinatarios: dict[str, Any]
) -> tuple[str, str, list[str]]:
    """Resolve quem responde por este caso.

    Regra do gestor (19/08/2026): a cobrança vai para o responsável pelo
    **caixa da revenda onde foi feito o lançamento que levou o acumulado do
    cliente a atingir o limiar** — não para os responsáveis de todos os caixas
    em que o cliente movimentou. A apuração é do grupo inteiro; a cobrança tem
    um dono só. Isso não impede que ESSE caixa tenha mais de um responsável —
    ``email:`` no YAML aceita vários endereços separados por vírgula.

    Args:
        caso: Caso já enriquecido, com ``gatilho`` (e ``gatilho_incremento``,
            quando é um novo cruzamento).
        destinatarios: Mapa de ``config/responsaveis_caixa.yaml``.

    Returns:
        Tupla ``(rotulo_do_caixa, nome_do_responsavel, emails)``. ``emails``
        cai em ``email_padrao`` quando o caixa não está mapeado, e vem vazio
        se nem isso existir.
    """
    gatilho = caso.get("gatilho_incremento") or caso.get("gatilho") or {}
    revenda = str(gatilho.get("revenda") or "").strip()
    caixa = str(gatilho.get("caixa") or "").strip()
    rotulo = f"{revenda} / caixa {caixa}" if revenda else "(caixa não identificado)"

    dados = destinatarios.get("mapa", {}).get((revenda, caixa)) or {}
    emails = _emails_da_string(dados.get("email", "")) or _emails_da_string(
        destinatarios.get("email_padrao", "")
    )
    nome = dados.get("nome") or destinatarios.get("responsavel_padrao", "")
    return rotulo, nome, emails


def _bloco_identificacao(caso: dict[str, Any], limiar: float) -> str:
    """Trecho comum às duas mensagens: quem é o cliente e quanto acumulou."""
    linhas_empresa = "\n".join(
        f"  - {empresa}: R$ {_fmt_moeda(valor)}"
        for empresa, valor in sorted(
            caso["por_empresa"].items(), key=lambda kv: kv[1], reverse=True
        )
    )
    return f"""  Cliente ...........: {caso['nome_cliente']}
  Código no sistema .: {caso['codigo_cliente']}
  Período apurado ...: {caso['janela_inicio']:%d/%m/%Y} a {caso['janela_fim']:%d/%m/%Y}
  Recebimentos ......: {caso['qtd_lancamentos']}
  Total no grupo ....: R$ {_fmt_moeda(caso['total'])}  (limite: R$ {_fmt_moeda(limiar)})

Acumulado por empresa do grupo:
{linhas_empresa}"""


def _avisos(caso: dict[str, Any]) -> str:
    """Alertas de qualidade do dado que o destinatário precisa ver."""
    texto = ""
    if not caso["nome_identificado"]:
        texto += (
            "\nATENÇÃO: o histórico do lançamento não trouxe o nome do cliente "
            f"(código {caso['codigo_cliente']}). O campo 1 da DMF está em branco "
            "e precisa ser preenchido à mão.\n"
        )
    if caso["tem_caixa_sinalizado"]:
        texto += (
            "\nObservação: há lançamentos em caixa que não representa saldo real "
            "(9, 99, 4 — ou 8/14 na Multicar Mits). Eles estão marcados com * no "
            "demonstrativo e entram na apuração por decisão da gestão.\n"
        )
    return texto


def _bloco_gatilho(caso: dict[str, Any], para_o_coaf: bool = False) -> str:
    """Detalha o lançamento que disparou a cobrança.

    O mesmo bloco serve às duas mensagens; só a frase de abertura muda, porque
    o responsável precisa entender *por que recebeu* e o COAF precisa saber
    *o que aconteceu*.
    """
    gatilho = caso.get("gatilho_incremento") or caso.get("gatilho")
    if not gatilho:
        return ""
    abertura = (
        "Lançamento que disparou a cobrança:"
        if para_o_coaf
        else (
            "Você está recebendo porque o lançamento que levou o acumulado deste\n"
            "cliente a atingir o limite foi feito no seu caixa:"
        )
    )
    return f"""
{abertura}

  Data ..............: {gatilho['data']:%d/%m/%Y}
  Revenda / caixa ...: {gatilho['revenda']} / {gatilho['caixa']}
  Usuário do sistema : {gatilho['usuario']}
  Origem ............: {gatilho['origem']}
  Título ............: {gatilho['titulo']}
  Valor .............: R$ {_fmt_moeda(gatilho['valor'])}
  Acumulado no ponto : R$ {_fmt_moeda(gatilho['acumulado_no_gatilho'])}
"""


def montar_mensagem(
    caso: dict[str, Any], limiar: float, qtd_empresas: int = 1
) -> tuple[str, str]:
    """Mensagem para o responsável pelo lançamento-gatilho.

    Args:
        caso: Caso já enriquecido.
        limiar: Valor que caracteriza a comunicação ao COAF.
        qtd_empresas: Quantas DMFs (uma por empresa) vão anexadas.

    Returns:
        Tupla ``(assunto, corpo)``.
    """
    complemento = bool(caso.get("ja_notificado")) and caso.get("incremento", 0.0) > 0
    if complemento:
        assunto = (
            f"[COAF] DMF complementar — {caso['nome_cliente']} — "
            f"+R$ {_fmt_moeda(caso['incremento'])} desde a última declaração"
        )
        abertura = (
            "O cliente abaixo VOLTOU a atingir o limite de recebimento em espécie\n"
            "e precisa de nova Declaração de Movimentação Financeira (DMF) assinada.\n\n"
            f"  Recebido DESDE a última DMF: R$ {_fmt_moeda(caso['incremento'])}\n"
            "  (este valor sozinho já atinge o limite; o que foi declarado antes\n"
            "   NÃO entra nesta conta)\n"
        )
    else:
        assunto = (
            f"[COAF] DMF pendente — {caso['nome_cliente']} — "
            f"R$ {_fmt_moeda(caso['total'])}"
        )
        abertura = (
            "O cliente abaixo atingiu o limite de recebimento em espécie que exige\n"
            "a Declaração de Movimentação Financeira (DMF) assinada.\n"
        )

    plural = "DMFs" if qtd_empresas > 1 else "DMF"
    anexo_txt = (
        f"Seguem em anexo {qtd_empresas} {plural} — uma por empresa do grupo em que\n"
        "houve recebimento, já preenchidas com o nome do cliente, o valor daquela\n"
        "empresa e o demonstrativo dos lançamentos correspondentes.\n"
    )
    if complemento:
        anexo_txt += (
            "As linhas ainda não declaradas aparecem marcadas como NOVO no\n"
            "demonstrativo, e há um anexo complementar só com elas.\n"
        )

    corpo = f"""Prezado(a),

{abertura}
{_bloco_identificacao(caso, limiar)}
{_bloco_gatilho(caso)}{_avisos(caso)}
{anexo_txt}
O que fazer, em cada DMF:
  1. Completar os campos 2 a 5 e 7 a 9 (CNPJ/CPF, profissão, servidor público,
     pessoa politicamente exposta, natureza da compra, modelo do bem e data).
  2. Colher a assinatura do cliente.
  3. Devolver os documentos digitalizados ao setor de compliance.

Mensagem gerada automaticamente pelo monitoramento COAF.
Os valores são apurados a partir dos lançamentos de caixa do período e não
substituem a escrituração contábil.
"""
    return assunto, corpo


def montar_mensagem_coaf(
    caso: dict[str, Any],
    limiar: float,
    caixa_destino: str,
    responsavel: str,
    email_responsavel: str,
) -> tuple[str, str]:
    """Mensagem para o setor de COAF, com o consolidado do grupo.

    Diferente da mensagem do responsável, esta traz a visão de grupo e diz a
    quem a cobrança foi endereçada — é o setor que acompanha se a DMF volta
    assinada.

    Returns:
        Tupla ``(assunto, corpo)``.
    """
    complemento = bool(caso.get("ja_notificado")) and caso.get("incremento", 0.0) > 0
    marcador = "novo cruzamento" if complemento else "1ª ocorrência"
    assunto = (
        f"[COAF · consolidado] {caso['nome_cliente']} — "
        f"R$ {_fmt_moeda(caso['total'])} ({marcador})"
    )

    extra = ""
    if complemento:
        extra = (
            f"\nEste cliente já havia sido declarado. Desde a última DMF enviada\n"
            f"acumulou mais R$ {_fmt_moeda(caso['incremento'])}, valor que sozinho\n"
            "atinge o limite.\n"
        )

    corpo = f"""Registro de acionamento do monitoramento COAF.

{_bloco_identificacao(caso, limiar)}
{extra}
Cobrança endereçada a:
  Caixa do gatilho ..: {caixa_destino}
  Responsável .......: {responsavel or '(sem responsável cadastrado)'}
  E-mail ............: {email_responsavel or '(sem e-mail mapeado)'}
{_bloco_gatilho(caso, para_o_coaf=True)}{_avisos(caso)}
Anexos:
  - Relatório consolidado do grupo (exclusivo deste setor), com a quebra por
    empresa, a identificação do lançamento-gatilho e todos os recebimentos.
  - Uma DMF por empresa, iguais às enviadas ao responsável.

Mensagem gerada automaticamente pelo monitoramento COAF.
Os valores são apurados a partir dos lançamentos de caixa do período e não
substituem a escrituração contábil.
"""
    return assunto, corpo


def montar_mensagem_sem_identificacao(caso: dict[str, Any], limiar: float) -> tuple[str, str]:
    """Mensagem da rede de segurança: cliente não identificado no histórico.

    Regra do gestor (21/08/2026): quando o nome do cliente não pôde ser
    identificado, o caso **não** segue o fluxo normal de dois destinatários —
    nada vai para o responsável de um caixa real. Uma DMF com o campo 1 em
    branco não identifica a quem se refere; mandar isso para fora do
    compliance arrisca expor um documento incompleto sem ninguém saber a
    quem cobrar a assinatura. Tudo (todas as DMFs + o consolidado) vai só
    para o setor de COAF, com o assunto deixando isso explícito.

    Returns:
        Tupla ``(assunto, corpo)``.
    """
    assunto = (
        f"[COAF · SEM IDENTIFICAÇÃO] código {caso['codigo_cliente']} — "
        f"R$ {_fmt_moeda(caso['total'])} — requer identificação manual"
    )
    corpo = f"""ATENÇÃO: o nome deste cliente não pôde ser identificado no histórico dos
lançamentos. Por isso este caso NÃO seguiu o fluxo normal — nada foi
enviado ao responsável de nenhum caixa. Só o setor de COAF está recebendo
esta mensagem, com todos os anexos, para identificar o cliente manualmente
antes de qualquer DMF ser encaminhada para assinatura.

{_bloco_identificacao(caso, limiar)}
{_bloco_gatilho(caso, para_o_coaf=True)}
Anexos (gerados com o campo 1 em branco — não enviar a ninguém sem
completar a identificação):
  - Relatório consolidado do grupo.
  - Uma DMF por empresa em que houve recebimento.

Mensagem gerada automaticamente pelo monitoramento COAF.
Os valores são apurados a partir dos lançamentos de caixa do período e não
substituem a escrituração contábil.
"""
    return assunto, corpo


def notificar_casos(
    con,
    casos: list[dict[str, Any]],
    anexos_por_caso: dict[str, dict[str, Any]],
    destinatarios: dict[str, Any],
    cfg: dict[str, Any],
    config: Configuracao,
    escopo: str,
    enviar_de_verdade: bool = False,
    **compat: Any,
) -> dict[str, Any]:
    """Dispara as notificações de cada caso e registra toda tentativa.

    Manda **duas** mensagens por caso, com públicos e conteúdos diferentes:

    1. **Responsável pelo lançamento-gatilho** — recebe uma DMF por empresa do
       grupo em que houve recebimento. É quem tem que preencher e colher a
       assinatura.
    2. **Setor de COAF** — recebe as mesmas DMFs **mais** o relatório
       consolidado do grupo, que mostra a soma entre empresas e a quem a
       cobrança foi endereçada. Esse relatório não vai para mais ninguém.

    Quem entra nesta lista já foi filtrado por
    ``analysis.coaf_especie.deve_notificar``; aqui não há decisão de reenvio.
    Registrar o envio é o que "consome" os lançamentos: eles passam a contar
    como declarados e saem da base do próximo incremento.

    Args:
        con: Conexão DuckDB em escrita.
        casos: Casos a notificar (consolidados do grupo).
        anexos_por_caso: Mapa ``chave_cliente -> {"empresas": [Path, ...],
            "consolidado": Path | None, "complementar": Path | None}``.
        destinatarios: Mapa de ``config/destinatarios_coaf.yaml``.
        cfg: Configuração do COAF.
        config: Configuração do projeto (credenciais SMTP).
        escopo: ``"grupo"`` ou ``"empresa"``.
        enviar_de_verdade: Se ``False``, registra supressão e não envia.
        **compat: Aceita ``enviar=`` como alias, para o chamador ficar legível.

    Returns:
        Dicionário com ``enviados``, ``suprimidos`` e ``avisos``.
    """
    if "enviar" in compat:
        enviar_de_verdade = bool(compat["enviar"])

    limiar = float(cfg["limiar_reais"])
    email_coaf = (destinatarios.get("email_coaf") or "").strip()
    agora = datetime.now()

    enviados = 0
    suprimidos = 0
    avisos: list[str] = []

    if not email_coaf:
        avisos.append(
            "email_coaf não preenchido em config/destinatarios_coaf.yaml — "
            "o relatório consolidado do grupo não será enviado a ninguém."
        )

    for caso in casos:
        chave = caso["chave_cliente"]
        anexos = anexos_por_caso.get(chave, {})
        dmfs = list(anexos.get("empresas") or [])
        consolidado = anexos.get("consolidado")
        complementar = anexos.get("complementar")

        # ---- rede de segurança: cliente não identificado ------------------ #
        # Regra do gestor (21/08/2026): sem nome, a DMF sai com o campo 1 em
        # branco — não pode ir para o responsável de um caixa real, que não
        # teria como saber a quem ela se refere. Tudo vai só para o COAF, e o
        # fluxo normal de dois destinatários é pulado por completo.
        if not caso["nome_identificado"]:
            todos_anexos = (
                ([consolidado] if consolidado else [])
                + dmfs
                + ([complementar] if complementar else [])
            )
            if not enviar_de_verdade:
                suprimidos += 1
                estado.registrar_notificacao(
                    con, chave, escopo, email_coaf, caso.get("id_deteccao", ""),
                    "; ".join(str(a) for a in todos_anexos),
                    estado.STATUS_SUPRIMIDO, agora,
                )
                logger.info(
                    "Modo revisão: cliente não identificado (código %s) — "
                    "envio suprimido, só para o COAF.",
                    caso["codigo_cliente"],
                )
                continue
            if not email_coaf:
                avisos.append(
                    f"Cliente não identificado (código {caso['codigo_cliente']}): "
                    "email_coaf não preenchido — nem a rede de segurança teve "
                    "para onde mandar. A DMF foi gerada, mas nada foi enviado."
                )
                estado.registrar_notificacao(
                    con, chave, escopo, "", caso.get("id_deteccao", ""), "",
                    estado.STATUS_SEM_DESTINATARIO, agora,
                )
                continue
            assunto, corpo = montar_mensagem_sem_identificacao(caso, limiar)
            try:
                enviar(config, [email_coaf], [], assunto, corpo, todos_anexos)
            except ErroEnvioEmail as exc:
                avisos.append(
                    f"Cliente não identificado (código {caso['codigo_cliente']}): "
                    f"falha no envio ao COAF — {exc}"
                )
                logger.error(
                    "Falha ao notificar o COAF sobre cliente não identificado "
                    "(código %s): %s", caso["codigo_cliente"], exc,
                )
                estado.registrar_notificacao(
                    con, chave, escopo, email_coaf, caso.get("id_deteccao", ""),
                    "; ".join(str(a) for a in todos_anexos), estado.STATUS_FALHA, agora,
                )
            else:
                enviados += 1
                estado.registrar_notificacao(
                    con, chave, escopo, email_coaf, caso.get("id_deteccao", ""),
                    "; ".join(str(a) for a in todos_anexos), estado.STATUS_ENVIADO, agora,
                )
                logger.info(
                    "Cliente não identificado (código %s) enviado só ao COAF "
                    "— rede de segurança.", caso["codigo_cliente"],
                )
            continue

        caixa_destino, responsavel, emails_resp = destinatario_do_caso(
            caso, destinatarios
        )
        if not emails_resp:
            avisos.append(
                f"{caso['nome_cliente']}: {caixa_destino} sem e-mail em "
                "config/responsaveis_caixa.yaml — a DMF foi gerada, mas só o "
                "setor de COAF será avisado."
            )
        emails_resp_txt = ", ".join(emails_resp) if emails_resp else ""

        anexos_resp = dmfs + ([complementar] if complementar else [])
        anexos_coaf = ([consolidado] if consolidado else []) + anexos_resp

        # ---- modo revisão: registra e não envia --------------------------- #
        if not enviar_de_verdade:
            suprimidos += 1
            for destino in [*emails_resp, email_coaf]:
                if not destino:
                    continue
                estado.registrar_notificacao(
                    con, chave, escopo, destino, caso.get("id_deteccao", ""),
                    "; ".join(str(a) for a in anexos_resp),
                    estado.STATUS_SUPRIMIDO, agora,
                )
            logger.info(
                "Modo revisão: envio suprimido para %s (%s) + COAF.",
                caso["nome_cliente"],
                emails_resp_txt or "sem destinatário",
            )
            continue

        if not emails_resp and not email_coaf:
            estado.registrar_notificacao(
                con, chave, escopo, "", caso.get("id_deteccao", ""), "",
                estado.STATUS_SEM_DESTINATARIO, agora,
            )
            continue

        houve_envio = False

        # ---- 1) responsável(is) pelo lançamento-gatilho -------------------- #
        # Um caixa pode ter mais de um responsável (config/responsaveis_caixa.yaml,
        # email: "a@x.com, b@x.com") — todos recebem a mesma mensagem, no
        # mesmo "Para", para que um veja que o outro também foi avisado.
        if emails_resp:
            assunto, corpo = montar_mensagem(caso, limiar, qtd_empresas=len(dmfs))
            try:
                enviar(config, emails_resp, [], assunto, corpo, anexos_resp)
            except ErroEnvioEmail as exc:
                avisos.append(f"{caso['nome_cliente']}: falha no envio ao responsável — {exc}")
                logger.error("Falha ao notificar %s: %s", caso["nome_cliente"], exc)
                for destino in emails_resp:
                    estado.registrar_notificacao(
                        con, chave, escopo, destino, caso.get("id_deteccao", ""),
                        "; ".join(str(a) for a in anexos_resp), estado.STATUS_FALHA, agora,
                    )
            else:
                houve_envio = True
                for destino in emails_resp:
                    estado.registrar_notificacao(
                        con, chave, escopo, destino, caso.get("id_deteccao", ""),
                        "; ".join(str(a) for a in anexos_resp), estado.STATUS_ENVIADO, agora,
                    )
                logger.info(
                    "DMF (%d empresa(s)) enviada para %s <%s> — cliente %s.",
                    len(dmfs), caixa_destino, emails_resp_txt, caso["nome_cliente"],
                )

        # ---- 2) setor de COAF, com o consolidado -------------------------- #
        if email_coaf:
            assunto, corpo = montar_mensagem_coaf(
                caso, limiar, caixa_destino, responsavel, emails_resp_txt
            )
            try:
                enviar(config, [email_coaf], [], assunto, corpo, anexos_coaf)
            except ErroEnvioEmail as exc:
                avisos.append(f"{caso['nome_cliente']}: falha no envio ao COAF — {exc}")
                logger.error("Falha ao notificar o COAF sobre %s: %s", caso["nome_cliente"], exc)
                estado.registrar_notificacao(
                    con, chave, escopo, email_coaf, caso.get("id_deteccao", ""),
                    str(consolidado or ""), estado.STATUS_FALHA, agora,
                )
            else:
                houve_envio = True
                estado.registrar_notificacao(
                    con, chave, escopo, email_coaf, caso.get("id_deteccao", ""),
                    str(consolidado or ""), estado.STATUS_ENVIADO, agora,
                )
                logger.info("Consolidado enviado ao COAF — cliente %s.", caso["nome_cliente"])

        if houve_envio:
            enviados += 1

    return {"enviados": enviados, "suprimidos": suprimidos, "avisos": avisos}
