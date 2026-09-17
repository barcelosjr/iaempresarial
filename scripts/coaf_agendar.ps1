<#
.SYNOPSIS
    Registra as tarefas agendadas do monitoramento COAF no Windows.

.DESCRIPTION
    Cria duas tarefas que rodam scripts\coaf_job.bat de 30 em 30 minutos,
    acompanhando o refresh da base de lançamentos:

      COAF-Especie-Semana   segunda a sexta, 07:00 -> 19:00
      COAF-Especie-Sabado   sábado,          07:00 -> 12:00

    As tarefas rodam na SESSÃO DO USUÁRIO LOGADO, de propósito: a autenticação
    do Power BI está em AUTH_MODE=device_code, cujo cache de token (.token_cache.json)
    pertence ao usuário. Rodar como SYSTEM não enxergaria esse cache.

    A ação registrada não chama coaf_job.bat diretamente — chama
    coaf_job_notificar.ps1 (via ``powershell.exe -WindowStyle Hidden``), que
    roda o job por baixo dos panos e só mostra alguma coisa na tela (um
    balão de notificação, não uma janela) quando há erro, aviso ou e-mail de
    verdade enviado. Na execução comum (nada novo para notificar), não
    aparece nenhuma janela preta piscando na tela a cada 30 minutos —
    pedido do gestor (31/08/2026). O log completo de toda execução continua
    em logs\coaf_AAAA-MM.log, notável ou não.

    Quando o refresh token expirar, o job falha com mensagem clara no log e é
    preciso refazer o login uma vez:
        .venv\Scripts\python.exe scripts\validar_setup.py

.PARAMETER Enviar
    Registra as tarefas com a flag --enviar, ou seja, com disparo real de
    e-mail. Sem este parâmetro, as tarefas rodam em MODO REVISÃO: geram
    alertas, histórico e PDFs, mas não enviam nada.

.PARAMETER Remover
    Remove as duas tarefas em vez de criá-las.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\coaf_agendar.ps1
    Registra as tarefas em modo revisão (recomendado no início).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\coaf_agendar.ps1 -Enviar
    Registra as tarefas com envio real de e-mail.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\coaf_agendar.ps1 -Remover
#>

[CmdletBinding()]
param(
    [switch]$Enviar,
    [switch]$Remover
)

$ErrorActionPreference = 'Stop'

$TarefaSemana = 'COAF-Especie-Semana'
$TarefaSabado = 'COAF-Especie-Sabado'

$Raiz = Split-Path -Parent $PSScriptRoot
$Bat  = Join-Path $PSScriptRoot 'coaf_job.bat'
$WrapperNotificar = Join-Path $PSScriptRoot 'coaf_job_notificar.ps1'

function Remove-TarefaSeExistir {
    param([string]$Nome)
    $existente = Get-ScheduledTask -TaskName $Nome -ErrorAction SilentlyContinue
    if ($null -ne $existente) {
        Unregister-ScheduledTask -TaskName $Nome -Confirm:$false
        Write-Host "Tarefa removida: $Nome"
        return $true
    }
    return $false
}

if ($Remover) {
    $n = 0
    foreach ($nome in @($TarefaSemana, $TarefaSabado)) {
        if (Remove-TarefaSeExistir -Nome $nome) { $n++ }
    }
    if ($n -eq 0) { Write-Host 'Nenhuma tarefa do COAF estava registrada.' }
    exit 0
}

if (-not (Test-Path $Bat)) {
    throw "Wrapper não encontrado: $Bat"
}
if (-not (Test-Path $WrapperNotificar)) {
    throw "Wrapper de notificação não encontrado: $WrapperNotificar"
}

$argumentoPs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$WrapperNotificar`""
if ($Enviar) { $argumentoPs += ' -Enviar' }

# Ação: powershell.exe -WindowStyle Hidden roda coaf_job_notificar.ps1, que
# por sua vez chama o .bat (que cuida de cd para a raiz e do Python do venv).
# Nada aparece na tela, exceto um balão de notificação quando há erro, aviso
# ou e-mail enviado de verdade — ver coaf_job_notificar.ps1.
$acao = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argumentoPs -WorkingDirectory $Raiz

# Gatilhos. A repetição de 30 min fica ATIVA pela duração da janela: começa às
# 07:00 e a última execução cai no fim do intervalo.
$gatilhoSemana = New-ScheduledTaskTrigger -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At '07:00'
$gatilhoSemana.Repetition = (New-ScheduledTaskTrigger -Once -At '07:00' `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Hours 12)).Repetition

$gatilhoSabado = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At '07:00'
$gatilhoSabado.Repetition = (New-ScheduledTaskTrigger -Once -At '07:00' `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration (New-TimeSpan -Hours 5)).Repetition

# Roda como o usuário atual, só quando ele está logado — exigência do cache de
# token do device_code.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive -RunLevel Limited

$config = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -MultipleInstances IgnoreNew

$modo = if ($Enviar) { 'ENVIO REAL de e-mail' } else { 'MODO REVISÃO (não envia e-mail)' }

foreach ($item in @(
    @{ Nome = $TarefaSemana; Gatilho = $gatilhoSemana; Desc = 'seg-sex 07:00-19:00' },
    @{ Nome = $TarefaSabado; Gatilho = $gatilhoSabado; Desc = 'sábado 07:00-12:00' }
)) {
    Remove-TarefaSeExistir -Nome $item.Nome | Out-Null
    Register-ScheduledTask `
        -TaskName $item.Nome `
        -Action $acao `
        -Trigger $item.Gatilho `
        -Principal $principal `
        -Settings $config `
        -Description "Monitoramento COAF de recebimentos em espécie ($($item.Desc), a cada 30 min). $modo." | Out-Null
    Write-Host "Tarefa registrada: $($item.Nome) - $($item.Desc)"
}

Write-Host ''
Write-Host "Modo: $modo"
Write-Host 'Para testar agora:'
Write-Host "    Start-ScheduledTask -TaskName $TarefaSemana"
Write-Host 'Para acompanhar:'
Write-Host "    Get-Content logs\coaf_$(Get-Date -Format 'yyyy-MM').log -Tail 20 -Wait"
