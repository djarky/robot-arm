#!/bin/bash

echo "========================================"
echo "Ursina Arm Simulator - Build Linux Binary"
echo "========================================"

# Verificar y extraer el modelo 3D si no existe (para incluirlo en el build)
MODEL_FILE="robot_arm_sha.glb"
ZIP_FILE="robot_arm_sha.zip"

if [ ! -f "$MODEL_FILE" ]; then
    if [ -f "$ZIP_FILE" ]; then
        echo "=== Preparando activos: Extrayendo $MODEL_FILE desde $ZIP_FILE... ==="
        python3 -c "import zipfile; zipfile.ZipFile('$ZIP_FILE', 'r').extractall('.')"
    else
        echo "=== ADVERTENCIA: No se encontró ni $MODEL_FILE ni $ZIP_FILE. El build podría estar incompleto. ==="
    fi
fi

echo ""

if [ -d ".venv" ]; then
    echo "Activating virtual environment (.venv)..."
    source .venv/bin/activate
elif [ -d "venv" ]; then
    echo "Activating virtual environment (venv)..."
    source venv/bin/activate
else
    echo "Warning: Virtual environment not found. Using system Python."
fi

echo ""
echo "Installing/Updating PyInstaller..."
pip install pyinstaller --quiet

echo ""
echo "Building executable with PyInstaller..."
pyinstaller ursina_arm_project.spec --clean --noconfirm

echo ""
echo "========================================"
if [ -d "dist/UrsinaArmSimulator" ]; then
    echo "SUCCESS! Executables created successfully."
    echo ""
    echo "Location: dist/UrsinaArmSimulator"
    echo "Making executables runnable..."
    chmod +x "dist/UrsinaArmSimulator/UrsinaArmSimulator"
    chmod +x "dist/UrsinaArmSimulator/sim_3d"
    echo ""
    echo "You can now distribute the dist/UrsinaArmSimulator directory to Linux users."
else
    echo "ERROR! Build failed. Check the output above for errors."
fi
echo "========================================"
echo ""
