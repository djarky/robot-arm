@echo off
set VENV_DIR=venv

echo === Configurando el entorno para el Seguimiento de Gestos (Windows) ===

:: Crear el entorno virtual si no existe
if not exist %VENV_DIR% (
    echo Creando entorno virtual en %VENV_DIR%...
    python -m venv %VENV_DIR%
)

:: Activar el entorno virtual
call %VENV_DIR%\Scripts\activate

:: Instalar o actualizar dependencias
echo Instalando dependencias (opencv, mediapipe, pyside6, ursina, pyserial)...
python -m pip install --upgrade pip
pip install opencv-python mediapipe PySide6 ursina pyserial

:: Ejecutar la aplicación principal (GUI)
echo Iniciando la aplicación GUI...
python gui_main.py

:: Desactivar al terminar
deactivate
pause
