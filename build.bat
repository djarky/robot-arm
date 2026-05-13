@echo off
echo ========================================
echo Ursina Arm Simulator - Build Executable
echo ========================================

:: Verificar y extraer el modelo 3D si no existe (para incluirlo en el build)
set MODEL_FILE=robot_arm_sha.glb
set ZIP_FILE=robot_arm_sha.zip

if not exist %MODEL_FILE% (
    if exist %ZIP_FILE% (
        echo === Preparando activos: Extrayendo %MODEL_FILE% desde %ZIP_FILE%... ===
        python -c "import zipfile; zipfile.ZipFile('%ZIP_FILE%', 'r').extractall('.')"
    ) else (
        echo === ADVERTENCIA: No se encontró ni %MODEL_FILE% ni %ZIP_FILE%. El build podría estar incompleto. ===
    )
)

echo.

if exist "venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate.bat" (
    echo Activating virtual environment...
    call .venv\Scripts\activate.bat
) else (
    echo Warning: Virtual environment not found. Using system Python.
)

echo.
echo Installing/Updating PyInstaller...
pip install pyinstaller --quiet

echo.
echo Building executable with PyInstaller...
pyinstaller ursina_arm_project.spec --clean --noconfirm

echo.
echo ========================================
if exist "dist\UrsinaArmSimulator\UrsinaArmSimulator.exe" (
    echo SUCCESS! Executable created successfully.
    echo.
    echo Location: dist\UrsinaArmSimulator
    echo.
    echo You can now distribute the dist\UrsinaArmSimulator folder to Windows users.
) else (
    echo ERROR! Build failed. Check the output above for errors.
)
echo ========================================
echo.
pause
