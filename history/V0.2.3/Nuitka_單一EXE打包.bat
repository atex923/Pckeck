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

set "MAIN=Pckeck_V0.2.3.pyw"
set "OUT=build_nuitka"

%PY% -m pip install -U nuitka ordered-set zstandard
if not %errorlevel%==0 goto :FAIL
%PY% -m pip install -r requirements.txt
if not %errorlevel%==0 goto :FAIL

if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%"

%PY% -m nuitka ^
  --mode=onefile ^
  --windows-console-mode=disable ^
  --enable-plugin=pyside6 ^
  --include-data-dir=runtime=runtime ^
  --include-package=pymupdf ^
  --assume-yes-for-downloads ^
  --output-dir="%OUT%" ^
  --output-filename="Pckeck_V0.2.3.exe" ^
  "%MAIN%"

if not %errorlevel%==0 goto :FAIL
echo 打包完成：%OUT%\Pckeck_V0.2.3.exe
pause
exit /b 0

:FAIL
echo Nuitka 打包失敗，請保留畫面訊息供後續排查。
pause
exit /b 1
