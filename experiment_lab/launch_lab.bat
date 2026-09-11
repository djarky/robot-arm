@echo off
setlocal enabledelayedexpansion

REM Launcher para el Laboratorio de Experimentos (Windows)
title Robot Arm - Experiment Lab Launcher

cd /d "%~dp0"

set VENV_DIR=..\venv
set PYTHONPATH=%PYTHONPATH%;%cd%\..
set PYTHONIOENCODING=utf-8

echo === Cargando Entorno del Laboratorio ===

:: Obtener version de Python
for /f "tokens=2" %%v in ('python --version') do set PYTHON_VERSION=%%v

:: Verificar si el venv existe en el directorio padre
if not exist "%VENV_DIR%" (
    echo [ERROR] No se encontro el entorno virtual en %VENV_DIR%
    echo Por favor, ejecuta primero 'run.bat' en la carpeta principal.
    pause
    exit /b
)

:: Activar el entorno virtual
call "%VENV_DIR%\Scripts\activate"

:: Verificar/Instalar dependencias especificas del lab
echo Verificando dependencias...

:: Instalar requests por separado (suele fallar menos)
python -m pip install requests --quiet --trusted-host pypi.org --trusted-host files.pythonhosted.org

:: Intentar instalar pygame-ce (mas moderno y con mejor soporte para versiones nuevas de Python)
echo Intentando instalar pygame-ce...
python -m pip install pygame-ce --quiet --trusted-host pypi.org --trusted-host files.pythonhosted.org

if "!ERRORLEVEL!" NEQ "0" (
    echo [ADVERTENCIA] No se pudo instalar pygame-ce automaticamente.
    echo Version de Python detectada: !PYTHON_VERSION!
    echo Intentando con pygame estandar...
    python -m pip install pygame --quiet --trusted-host pypi.org --trusted-host files.pythonhosted.org
)

:: Lanzar el laboratorio
echo Iniciando lab_main.py...
python lab_main.py

if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] La aplicacion se cerro con errores.
    pause
)

deactivate
