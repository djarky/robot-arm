import sys
import os

# --- FIX PYINSTALLER: Registrar Loader GLTF manualmente ---
# En entornos congelados, Panda3D no siempre encuentra los entry points de los plugins
from panda3d.core import load_prc_file_data
load_prc_file_data("", "load-file-type gltf gltf")
load_prc_file_data("", "load-file-type glb gltf")
import gltf
import simplepbr
# --------------------------------------------------------

# Intentar habilitar PBR para que el modelo GLTF se vea bien
try:
    simplepbr.init()
except:
    pass

from ursina import *
from panda3d.core import ConfigVariableString

# Importar la lógica de simulación modularizada
from simulation import RobotArmSim

# Configurar Ursina para incrustación o sin bordes dependiendo del SO
# Esto debe hacerse antes de instanciar Ursina()
if len(sys.argv) > 1:
    parent_window_id = sys.argv[1]
    # Intentar pasar el control de la ventana usando panda3d properties
    if sys.platform == "win32":
        print(f"Windows: Intentando anclaje a {parent_window_id}")
    ConfigVariableString("parent-window-handle", parent_window_id).setValue(parent_window_id)
    print(f"Ursina intentando anclarse a la ventana: {parent_window_id}")

# Tomar ancho y alto pasados como argumento, por defecto 600x400
w = int(sys.argv[2]) if len(sys.argv) > 2 else 600
h = int(sys.argv[3]) if len(sys.argv) > 3 else 400

# Iniciamos Ursina con el tamaño del contenedor de PySide6 y forzando el origen
app = Ursina(size=(w, h), borderless=True)
window.position = (0, 0) # Forzar posición para evitar desfases al incrustar
window.color = color.light_gray

# Instanciar la simulación principal
sim = RobotArmSim()

def update():
    sim.update()

def input(key):
    # El TransformationGizmo ya maneja G, R, S, X y ESC internamente.
    # Mantenemos 'delete' como alternativa global.
    if key == 'delete':
        if sim.gizmo.enabled and sim.gizmo.target:
            sim.gizmo.delete_target()

# Bucle principal de Ursina
if __name__ == '__main__':
    app.run()

