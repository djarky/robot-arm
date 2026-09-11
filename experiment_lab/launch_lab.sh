#!/bin/bash
# Launcher para el Laboratorio de Experimentos en Linux
cd "$(dirname "$0")"
export PYTHONPATH=$PYTHONPATH:$(pwd)/..

# Asegurar dependencias del lab
../venv/bin/pip install pygame-ce requests --quiet

echo "Iniciando lab_main.py..."
../venv/bin/python3 lab_main.py
