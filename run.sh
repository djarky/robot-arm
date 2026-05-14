#!/bin/bash

# Nombre del entorno virtual
VENV_DIR="venv"

# Verificar y extraer el modelo 3D si no existe
MODEL_FILE="robot_arm_sha.glb"
ZIP_FILE="robot_arm_sha.zip"

if [ ! -f "$MODEL_FILE" ]; then
    if [ -f "$ZIP_FILE" ]; then
        echo "=== El archivo $MODEL_FILE no se encontró. Extrayendo desde $ZIP_FILE... ==="
        python3 -c "import zipfile; zipfile.ZipFile('$ZIP_FILE', 'r').extractall('.')"
    else
        echo "=== ADVERTENCIA: No se encontró ni $MODEL_FILE ni $ZIP_FILE. La simulación podría fallar. ==="
    fi
fi


echo "=== Configurando el entorno para el Seguimiento de Gestos ==="

# Forzar X11 para mayor estabilidad en Linux con PySide + Ursina
export QT_QPA_PLATFORM=xcb

# Crear el entorno virtual si no existe
if [ ! -d "$VENV_DIR" ]; then
    echo "Creando entorno virtual en $VENV_DIR..."
    python3 -m venv "$VENV_DIR"
fi

# Activar el entorno virtual
source "$VENV_DIR/bin/activate"

# Instalar o actualizar dependencias
echo "Instalando dependencias (opencv, mediapipe, pyside6, ursina, pyserial)..."
pip install --upgrade pip
pip install opencv-python mediapipe PySide6 ursina pyserial

# Ejecutar la aplicación principal (GUI)
echo "Iniciando la aplicación GUI..."
python gui_main.py

# Desactivar al terminar
deactivate
