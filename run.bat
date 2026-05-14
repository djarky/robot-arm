@echo off
set VENV_DIR=venv

:: Verificar y extraer el modelo 3D si no existe
set MODEL_FILE=robot_arm_sha.glb
set ZIP_FILE=robot_arm_sha.zip

if not exist %MODEL_FILE% (
    if exist %ZIP_FILE% (
        echo === El archivo %MODEL_FILE% no se encontró. Extrayendo desde %ZIP_FILE%... ===
        python -c "import zipfile; zipfile.ZipFile('%ZIP_FILE%', 'r').extractall('.')"
    ) else (
        echo === ADVERTENCIA: No se encontró ni %MODEL_FILE% ni %ZIP_FILE%. La simulación podría fallar. ===
    )
)


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
