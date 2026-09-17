@echo off
REM ===========================================================================
REM  Monitoramento COAF - recebimentos em especie
REM ===========================================================================
REM  Wrapper chamado pelo Agendador de Tarefas do Windows (ver
REM  scripts\coaf_agendar.ps1). Roda de 30 em 30 minutos no horario comercial.
REM
REM  Usa SEMPRE o Python do venv: o "python" do PATH e o stub da Microsoft
REM  Store e falha com modulo ausente.
REM
REM  Para ligar o envio real de e-mail, acrescente --enviar na linha do
REM  comando abaixo (ou passe como argumento: coaf_job.bat --enviar).
REM ===========================================================================

setlocal

REM Raiz do projeto = pasta pai de scripts\
set "RAIZ=%~dp0.."
cd /d "%RAIZ%"

set "PYTHON=%RAIZ%\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo [ERRO] Python do venv nao encontrado em "%PYTHON%".
    echo        Crie o ambiente com: python -m venv .venv
    exit /b 1
)

if not exist "logs" mkdir "logs"

echo [%date% %time%] Iniciando monitoramento COAF...
"%PYTHON%" analysis\coaf_especie.py %*
set "CODIGO=%ERRORLEVEL%"

if not "%CODIGO%"=="0" (
    echo [%date% %time%] FALHA - codigo de saida %CODIGO%. Ver logs\coaf_*.log
) else (
    echo [%date% %time%] Concluido com sucesso.
)

endlocal & exit /b %CODIGO%
