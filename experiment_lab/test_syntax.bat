@echo off
setlocal enabledelayedexpansion
set "PYTHON_VERSION=3.14.3"
echo Intentando instalar...
set ERRORLEVEL=1
if "!ERRORLEVEL!" NEQ "0" (
    echo Fallo con version !PYTHON_VERSION!
)
pause
