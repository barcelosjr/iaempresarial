<#
.SYNOPSIS
    Roda o monitoramento COAF sem abrir janela nenhuma, e so notifica quando
    importa: erro, aviso (ex.: falha de envio a um destinatario) ou e-mail
    realmente enviado.

.DESCRIPTION
    E o que o Agendador de Tarefas chama de 30 em 30 minutos (ver
    coaf_agendar.ps1) em vez de coaf_job.bat diretamente. Continua chamando
    coaf_job.bat por baixo - so que a partir de um processo powershell.exe
    ja iniciado com -WindowStyle Hidden, entao nenhuma janela aparece na
    tela na maioria das execucoes (o caso comum: nada novo para notificar).

    Quando o resultado e notavel - falha (codigo de saida != 0, ou marcador
    de erro na saida), aviso (ex.: caixa sem e-mail cadastrado) ou pelo
    menos um e-mail de verdade enviado - mostra um balao de notificacao do
    Windows (a mesma bandeja de "novo e-mail" ou "USB conectado"), que some
    sozinho em alguns segundos. Nao e um pop-up bloqueante: nao precisa
    clicar em nada.

    O log completo de toda execucao (notavel ou nao) continua sendo gravado
    em logs\coaf_AAAA-MM.log, como sempre - isto aqui so decide se aparece
    alguma coisa NA TELA.

.PARAMETER Enviar
    Repassado para coaf_job.bat como --enviar (envio real de e-mail). Sem
    isso, roda em modo revisao.

.EXAMPLE
    powershell -WindowStyle Hidden -ExecutionPolicy Bypass -File scripts\coaf_job_notificar.ps1 -Enviar
#>

[CmdletBinding()]
param(
    [switch]$Enviar
)

$Raiz = Split-Path -Parent $PSScriptRoot
$Bat = Join-Path $PSScriptRoot 'coaf_job.bat'

$argumentos = @()
if ($Enviar) { $argumentos += '--enviar' }

# Forca UTF-8 na saida do Python mesmo sem console anexado (redirecionado
# por pipe) - sem isso o texto acentuado do balao de notificacao pode sair
# ilegivel. A LOGICA de decidir se notifica nao depende disto (usa so
# ASCII - ver RESUMO_MAQUINA abaixo); isto e so para o texto ficar legivel.
$env:PYTHONUTF8 = '1'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}
$OutputEncoding = [System.Text.Encoding]::UTF8

Push-Location $Raiz
try {
    $saida = & $Bat @argumentos 2>&1 | Out-String
    $codigo = $LASTEXITCODE
} finally {
    Pop-Location
}

$enviados = 0
$avisos = 0
if ($saida -match 'RESUMO_MAQUINA:\s*erro=(\d+)\s+enviados=(\d+)\s+avisos=(\d+)') {
    # Linha so em ASCII, gravada pelo proprio job (analysis/coaf_especie.py)
    # exatamente para isto: decidir sem depender de casar emoji/acento em
    # texto capturado via pipe, cuja codificacao a partir de um processo
    # filho nem sempre preserva UTF-8 corretamente.
    $enviados = [int]$Matches[2]
    $avisos = [int]$Matches[3]
}

# Se o job travou antes de chegar la (erro nao tratado, config quebrada
# antes do parser de args, etc.), a linha acima pode nao existir - o codigo
# de saida sozinho ja cobre esse caso.
$houveErro = ($codigo -ne 0) -or ($saida -match 'FALHA|Traceback')
$houveAviso = $avisos -gt 0

# Diagnostico: a saida completa (inclusive traceback, se houver) as vezes
# nao aparece em logs\coaf_AAAA-MM.log (o logger so grava o que passa por
# logging.*; uma excecao nao tratada vai so para stderr). Sem isto, uma
# falha ficaria sem rastro nenhum fora do balao de 15s.
#
# Em caso de SUCESSO o arquivo e apagado - assim a simples existencia dele
# significa sempre "a ultima rodada falhou", sem risco de confundir com um
# erro velho ja resolvido.
try {
    $pastaLogs = Join-Path $Raiz 'logs'
    $arquivoErro = Join-Path $pastaLogs 'coaf_ultimo_erro.txt'
    if ($houveErro) {
        if (-not (Test-Path $pastaLogs)) { New-Item -ItemType Directory -Path $pastaLogs | Out-Null }
        $saida | Out-File -FilePath $arquivoErro -Encoding utf8
    } elseif (Test-Path $arquivoErro) {
        Remove-Item $arquivoErro -Force
    }
} catch {}

if (-not ($houveErro -or $houveAviso -or $enviados -gt 0)) {
    # Caso comum: nada novo. Sai em silencio, sem tocar na tela.
    exit $codigo
}

try {
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing

    if ($houveErro) {
        $titulo = 'COAF - falha no monitoramento'
        $icone = [System.Windows.Forms.ToolTipIcon]::Error
    } elseif ($enviados -gt 0) {
        $titulo = "COAF - $enviados e-mail(s) de DMF enviado(s)"
        $icone = [System.Windows.Forms.ToolTipIcon]::Info
    } else {
        $titulo = 'COAF - aviso no monitoramento'
        $icone = [System.Windows.Forms.ToolTipIcon]::Warning
    }

    # Ultimas linhas com conteudo - cabe no balao (o log completo, sempre, e
    # logs\coaf_AAAA-MM.log).
    $linhas = $saida -split "`r?`n" | Where-Object { $_.Trim() -ne '' }
    $texto = ($linhas | Select-Object -Last 6) -join "`n"
    if ($texto.Length -gt 250) { $texto = $texto.Substring(0, 247) + '...' }

    $notificacao = New-Object System.Windows.Forms.NotifyIcon
    $notificacao.Icon = [System.Drawing.SystemIcons]::Information
    $notificacao.Visible = $true
    $notificacao.BalloonTipTitle = $titulo
    $notificacao.BalloonTipText = $texto
    $notificacao.BalloonTipIcon = $icone
    $notificacao.ShowBalloonTip(15000)

    # Mantem o processo vivo tempo suficiente para o balao aparecer antes de
    # o NotifyIcon ser descartado (e a notificacao, retirada da bandeja).
    Start-Sleep -Seconds 16
    $notificacao.Dispose()
} catch {
    # Nunca deixa a notificacao (cosmetica) derrubar o codigo de saida do job.
}

exit $codigo
