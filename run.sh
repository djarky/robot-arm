#!/bin/bash

# Nombre del entorno virtual
VENV_DIR="venv"

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
