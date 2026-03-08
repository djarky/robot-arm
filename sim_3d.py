import sys
import socket
import json
import os
from ursina import *
from panda3d.core import ConfigVariableString

# Configurar Ursina para incrustación o sin bordes dependiendo del SO
# Esto debe hacerse antes de instanciar Ursina()
if len(sys.argv) > 1:
    parent_window_id = sys.argv[1]
    # Intentar pasar el control de la ventana usando panda3d properties
    ConfigVariableString("parent-window-handle", parent_window_id).setValue(parent_window_id)
    print(f"Ursina intentando anclarse a la ventana: {parent_window_id}")

# Tomar ancho y alto pasados como argumento, por defecto 600x400
w = int(sys.argv[2]) if len(sys.argv) > 2 else 600
h = int(sys.argv[3]) if len(sys.argv) > 3 else 400

# Iniciamos Ursina con el tamaño del contenedor de PySide6 y forzando el origen
app = Ursina(size=(w, h), borderless=True)
window.position = (0, 0) # Forzar posición para evitar desfases al incrustar
window.color = color.light_gray

DEFAULT_CAM_POS = (2.3, 3.54, -7.09)
DEFAULT_CAM_ROT = (-346.42, -18.57, 0)

class RobotArmSim:
    def __init__(self):
        # Escenario básico
        self.sky = Sky(color=color.rgb(135, 206, 235))
        self.floor = Entity(model='plane', scale=500, texture='white_cube', 
                          texture_scale=(50,50), color=color.gray, collider='box')

        # Ejes XYZ para orientación (Rojo=X, Verde=Y, Azul=Z)
        Entity(model='cube', color=color.red, scale=(5, 0.05, 0.05), position=(2.5, 0.05, 0))
        Entity(model='cube', color=color.green, scale=(0.05, 5, 0.05), position=(0, 2.5, 0))
        Entity(model='cube', color=color.blue, scale=(0.05, 0.05, 5), position=(0, 0.05, 2.5))

        # Colores personalizados basados en la imagen (Gris oscuro y Azul metálico)
        joint_color = color.rgb(100, 130, 170)
        link_color = color.rgb(60, 60, 60)
        
        # Jerarquía base
        self.arm_origin = Entity(parent=scene, y=0.4) # Origen general del brazo
        
        # Base visual (Azul)
        self.base_vis = Entity(parent=scene, model='cube', color=joint_color, scale=(0.8, 0.4, 0.8), y=0.2)
        
        # Junta 0: Rotación Base (Y). Pivot
        self.joint0 = Entity(parent=self.arm_origin) 
        
        # Link 1 visual: Pilar central (Gris oscuro). Anclado a Joint0.
        self.link1_vis = Entity(parent=self.joint0, model='cube', color=link_color, scale=(0.3, 1.5, 0.3), y=0.75)
        
        # Junta 1: Hombro (X). Pivot al final del link1
        self.joint1 = Entity(parent=self.joint0, y=1.5) 
        # Tapa visual azul del hombro 
        self.j1_vis = Entity(parent=self.joint1, model='cube', color=joint_color, scale=(0.5, 0.3, 0.5), rotation_x=90)
        
        # Link 2 visual: Brazo principal (Gris oscuro). Anclado a Joint1.
        self.link2_vis = Entity(parent=self.joint1, model='cube', color=link_color, scale=(0.25, 1.5, 0.25), y=0.75)
        
        # Junta 2: Codo (X). Pivot al final del link2
        self.joint2 = Entity(parent=self.joint1, y=1.5)
        # Tapa visual azul del codo
        self.j2_vis = Entity(parent=self.joint2, model='cube', color=joint_color, scale=(0.4, 0.2, 0.4), rotation_x=90)
        
        # Link 3 visual: Antebrazo (Gris oscuro). Anclado a Joint2
        self.link3_vis = Entity(parent=self.joint2, model='cylinder', color=link_color, scale=(0.2, 0.8, 0.2), y=0.4)
        
        # Pinza (Gripper) visual al final del antebrazo
        # Lo rotamos para que mire hacia adelante (eje Z local de la muñeca) en lugar de hacia arriba
        self.gripper_base = Entity(parent=self.joint2, y=0.8, rotation_x=90)
        Entity(parent=self.gripper_base, model='cube', color=link_color, scale=(0.5, 0.1, 0.4))              # Palma
        Entity(parent=self.gripper_base, model='cube', color=link_color, scale=(0.1, 0.4, 0.1), position=(-0.15, 0.2, 0)) # Dedo Izq
        Entity(parent=self.gripper_base, model='cube', color=link_color, scale=(0.1, 0.4, 0.1), position=(0.15, 0.2, 0))  # Dedo Der
        
        self.angles = [0, 0, 0]        
        
        # Configuración de Cámara (EditorCamera) por defecto para que no se pierda el usuario
        self.cam = EditorCamera()
        self.cam.position = (0, 3, -8)  # Posición inicial cómoda
        self.cam.look_at(self.base_vis)
        
        # Networking (UDP receptor para no bloquear a la GUI principal)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Permite reutilizar el puerto inmediatamente si se reinicia la app
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 5005))
        self.sock.setblocking(False)

        self.last_save_time = time.time()
        self.load_camera_config()

    def load_camera_config(self, reset=False):
        try:
            cam_cfg = None
            if not reset and os.path.exists("config.json"):
                with open("config.json", "r") as f:
                    config = json.load(f)
                    cam_cfg = config.get("camera")
            
            if cam_cfg:
                pos = cam_cfg.get("position")
                rot = cam_cfg.get("rotation")
                if pos: self.cam.position = tuple(pos)
                if rot: self.cam.rotation = tuple(rot)
            else:
                self.cam.position = DEFAULT_CAM_POS
                self.cam.rotation = DEFAULT_CAM_ROT
                
            if reset:
                print("Cámara reseteada a valores por defecto")
            else:
                print("Cámara restaurada desde config.json")
        except Exception as e:
            print(f"Error cargando config de cámara: {e}")
            self.cam.position = DEFAULT_CAM_POS
            self.cam.rotation = DEFAULT_CAM_ROT

    def save_camera_config(self):
        try:
            config = {}
            if os.path.exists("config.json"):
                with open("config.json", "r") as f:
                    config = json.load(f)
            
            config["camera"] = {
                "position": [self.cam.x, self.cam.y, self.cam.z],
                "rotation": [self.cam.rotation_x, self.cam.rotation_y, self.cam.rotation_z]
            }
            
            with open("config.json", "w") as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"Error guardando config de cámara: {e}")

    def spawn_object(self, shape, size, mass):
        # Spawnea objetos a un lado del robot para interactuar
        if shape == "box":
            Entity(model='cube', scale=size, color=color.random_color(), position=(2, 3, 0), collider='box')
        elif shape == "cylinder":
            Entity(model='cylinder', scale=size, color=color.random_color(), position=(2, 3, 0), collider='mesh')

    def update(self):
        # Recibir mensajes de control de la GUI principal.
        # Leemos TODOS los paquetes en la cola hasta vaciarla para evitar lag.
        data_received = False
        last_data = None
        while True:
            try:
                data, _ = self.sock.recvfrom(1024)
                last_data = data
                data_received = True
            except BlockingIOError:
                break # No hay más mensajes en la cola

        if data_received and last_data:
            try:
                msg = json.loads(last_data.decode())
                if msg.get("type") == "angles":
                    self.angles = msg["data"]
                    # Aplicar ángulos recibidos a las rotaciones locales (sobrescribe la entrada del ratón)
                    # Joint 0 es la base (rotación alrededor del eje Y global/paralelo)
                    self.joint0.rotation_y = self.angles[0]
                    # Joint 1 es el hombro (baja y sube, rotación en X). Invertido visualmente si es necesario
                    self.joint1.rotation_x = -self.angles[1]
                    # Joint 2 es el codo
                    self.joint2.rotation_x = -self.angles[2]
                elif msg.get("type") == "spawn":
                    self.spawn_object(msg["shape"], msg["size"], msg["mass"])
                elif msg.get("type") == "reset_camera":
                    self.load_camera_config(reset=True)
            except Exception as e:
                print("Error decodificando UDP:", e)
                
        # Control manual de fallback con el ratón solo si se presiona la tecla shift, 
        # para no interferir con la EditorCamera por defecto.
        if held_keys['shift']:
            if mouse.left:
                self.joint0.rotation_y += mouse.velocity[0] * 100
                self.joint1.rotation_x -= mouse.velocity[1] * 100
            elif mouse.right:
                self.joint2.rotation_x -= mouse.velocity[1] * 100
        
        # Guardar posición de cámara cada 5 segundos si ha cambiado notablemente
        if time.time() - self.last_save_time > 5:
            self.save_camera_config()
            self.last_save_time = time.time()

sim = RobotArmSim()

def update():
    sim.update()

# Bucle principal de Ursina
app.run()
