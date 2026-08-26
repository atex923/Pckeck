@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PY=py -3"
) else (
    set "PY=python"
)

%PY% -c "import PySide6, fitz" >nul 2>nul
if not %errorlevel%==0 (
    echo 正在安裝必要套件...
    %PY% -m pip install -r requirements.txt
    if not %errorlevel%==0 goto :FAIL
)

start "" %PY% "Pckeck_V0.2.2.pyw"
exit /b 0

:FAIL
echo 套件安裝失敗，請保留畫面訊息供後續排查。
pause
exit /b 1
