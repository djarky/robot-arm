import sys
import socket
import json
import os
import math
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

# Socket para enviar datos de vuelta a la GUI
feedback_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
GUI_ADDR = ("127.0.0.1", 5006)

class CircularSlider(Entity):
    def __init__(self, target_entity, axis='y', radius=0.8, slider_color=color.cyan, **kwargs):
        # Generar una "rosquilla" (toroide) ultra-estilizada y delgada
        segments = 100 # Resolución para suavidad
        path = [Vec3(math.cos(math.radians(i*(360/segments)))*radius, 0, math.sin(math.radians(i*(360/segments)))*radius) for i in range(segments + 1)]
            
        # Sección transversal cómoda y robusta
        thickness = 0.06 # Aumentado para máximo agarre y visibilidad
        cross_segments = 12
        # IMPORTANTE: Usar Vec3 para evitar el TypeError en el generador de Pipe interno
        cross_section = [Vec3(math.cos(math.radians(i*(360/cross_segments)))*thickness, math.sin(math.radians(i*(360/cross_segments)))*thickness, 0) for i in range(cross_segments + 1)]
        
        super().__init__(
            parent=target_entity,
            model=Pipe(path=path, base_shape=cross_section, cap_ends=False),
            color=color.rgba(slider_color.r, slider_color.g, slider_color.b, 0.4),
            double_sided=True,
            collider='mesh',
            **kwargs
        )
        # Forzar suavizado de malla y look de "luz"
        if self.model:
            self.model.generate_normals()
            self.model.smooth = True
            
        self.unlit = True 
        self.target = target_entity
        self.axis = axis
        self.radius = radius
        self.base_color = slider_color
        self.dragging = False
        self.pulse_time = 0

    def on_mouse_enter(self):
        self.color = color.rgba(1, 1, 1, 0.9)
        self.scale = 1.02 # Muy sutil
    
    def on_mouse_exit(self):
        if not self.dragging:
            self.color = color.rgba(self.base_color.r, self.base_color.g, self.base_color.b, 0.4)
            self.scale = 1.0

    def input(self, key):
        if key == 'left mouse down' and mouse.hovered_entity == self:
            self.dragging = True
            self.color = color.yellow
        elif key == 'left mouse up':
            self.dragging = False
            self.color = color.rgba(self.base_color.r, self.base_color.g, self.base_color.b, 0.4)
            self.scale = 1.0

    def update(self):
        # Efecto de pulso sutil (glow)
        self.pulse_time += time.dt * 2
        if not self.dragging:
            alpha = 0.3 + math.sin(self.pulse_time) * 0.1
            self.color = color.rgba(self.base_color.r, self.base_color.g, self.base_color.b, alpha)

        if self.dragging:
            delta = mouse.velocity[0] + mouse.velocity[1]
            if self.axis == 'y':
                self.target.rotation_y += delta * 500
            else:
                self.target.rotation_x -= delta * 500
            
            if hasattr(scene, 'sim_instance'):
                scene.sim_instance.sync_to_gui()

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
        # Paleta de colores Pastel - Saturados y Unlit para evitar el blanco
        # Nota: Ursina espera valores entre 0.0 y 1.0. Dividimos por 255.
        color_sage = color.rgb(160/255, 200/255, 140/255)
        color_rose = color.rgb(230/255, 150/255, 170/255)
        color_lavender = color.rgb(180/255, 150/255, 220/255)
        color_cream = color.rgb(240/255, 230/255, 140/255)
        color_orange = color.rgb(240/255, 180/255, 120/255)
        color_mint = color.rgb(150/255, 210/255, 170/255)
        color_peach = color.rgb(240/255, 160/255, 140/255)
        
        # Jerarquía base
        self.arm_origin = Entity(parent=scene, y=0.4) # Origen general del brazo
        
        # Base visual (Sage) - Unlit para color real
        self.base_vis = Entity(parent=scene, model='cube', color=color_sage, scale=(0.8, 0.4, 0.8), y=0.2, unlit=True)
        
        # Junta 0: Rotación Base (Y). Pivot
        self.joint0 = Entity(parent=self.arm_origin) 
        self.slider0 = CircularSlider(self.joint0, axis='y', radius=1.2, y=0.1, slider_color=color.cyan)
        
        # Link 1 visual: Pilar central (Rosa). Unlit.
        self.link1_vis = Entity(parent=self.joint0, model='cube', color=color_rose, scale=(0.3, 1.5, 0.3), y=0.75, collider='box', unlit=True)
        
        # Junta 1: Hombro (X). Pivot al final del link1
        self.joint1 = Entity(parent=self.joint0, y=1.5) 
        self.slider1 = CircularSlider(self.joint1, axis='x', radius=0.6, rotation_z=90, slider_color=color.cyan)

        # Tapa visual lavanda del hombro - Unlit.
        self.j1_vis = Entity(parent=self.joint1, model='cube', color=color_lavender, scale=(0.5, 0.3, 0.5), rotation_x=90, unlit=True)
        
        # Link 2 visual: Brazo principal (Amarillo). Unlit.
        self.link2_vis = Entity(parent=self.joint1, model='cube', color=color_cream, scale=(0.25, 1.5, 0.25), y=0.75, collider='box', unlit=True)
        
        # Junta 2: Codo (X). Pivot al final del link2
        self.joint2 = Entity(parent=self.joint1, y=1.5)
        self.slider2 = CircularSlider(self.joint2, axis='x', radius=0.5, rotation_z=90, slider_color=color.cyan)

        # Tapa visual naranja del codo - Unlit.
        self.j2_vis = Entity(parent=self.joint2, model='cube', color=color_orange, scale=(0.4, 0.2, 0.4), rotation_x=90, unlit=True)
        
        # Link 3 visual: Antebrazo (Menta). Unlit.
        self.link3_vis = Entity(parent=self.joint2, model='cylinder', color=color_mint, scale=(0.2, 0.8, 0.2), y=0.4, collider='box', unlit=True)
        
        # Pinza (Gripper) visual al final del antebrazo - Unlit.
        # Lo rotamos para que mire hacia adelante (eje Z local de la muñeca) en lugar de hacia arriba
        self.gripper_base = Entity(parent=self.joint2, y=0.8, rotation_x=90)
        Entity(parent=self.gripper_base, model='cube', color=color_peach, scale=(0.5, 0.1, 0.4), unlit=True)              # Palma
        Entity(parent=self.gripper_base, model='cube', color=color_peach, scale=(0.1, 0.4, 0.1), position=(-0.15, 0.2, 0), unlit=True) # Dedo Izq
        Entity(parent=self.gripper_base, model='cube', color=color_peach, scale=(0.1, 0.4, 0.1), position=(0.15, 0.2, 0), unlit=True)  # Dedo Der
        
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
        
        self.selected_joint = None
        self.rotation_mode = False
        scene.sim_instance = self

    def sync_to_gui(self):
        # Enviar ángulos actuales a la GUI para sincronizar sliders
        # Joint0 -> y, Joint1 -> -x, Joint2 -> -x
        angles = [
            round(self.joint0.rotation_y, 1),
            round(-self.joint1.rotation_x, 1),
            round(-self.joint2.rotation_x, 1)
        ]
        msg = json.dumps({"type": "sync_angles", "data": angles})
        try:
            feedback_sock.sendto(msg.encode(), GUI_ADDR)
        except:
            pass

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
                
        # Selección de piezas al hacer clic
        if mouse.left and not any(s.dragging for s in [self.slider0, self.slider1, self.slider2]):
            if mouse.hovered_entity:
                # Buscar a qué link pertenece
                if mouse.hovered_entity in [self.link1_vis, self.slider0]:
                    self.select_joint(0)
                elif mouse.hovered_entity in [self.link2_vis, self.slider1, self.j1_vis]:
                    self.select_joint(1)
                elif mouse.hovered_entity in [self.link3_vis, self.slider2, self.j2_vis]:
                    self.select_joint(2)

        # Modo Rotación (Tecla R)
        if held_keys['r'] and self.selected_joint is not None:
            self.rotation_mode = True
        
        if self.rotation_mode:
            delta = mouse.velocity[0] * 200
            if self.selected_joint == 0:
                self.joint0.rotation_y += delta
            elif self.selected_joint == 1:
                self.joint1.rotation_x -= delta
            elif self.selected_joint == 2:
                self.joint2.rotation_x -= delta
            
            self.sync_to_gui()
            
            if mouse.left: # Confirmar
                self.rotation_mode = False

        # Control manual de fallback con el ratón solo si se presiona la tecla shift, 
        # para no interferir con la EditorCamera por defecto.
        if held_keys['shift']:
            if mouse.left:
                self.joint0.rotation_y += mouse.velocity[0] * 100
                self.joint1.rotation_x -= mouse.velocity[1] * 100
            elif mouse.right:
                self.joint2.rotation_x -= mouse.velocity[1] * 100
            self.sync_to_gui()
        
        # Guardar posición de cámara cada 5 segundos si ha cambiado notablemente
        if time.time() - self.last_save_time > 5:
            self.save_camera_config()
            self.last_save_time = time.time()

    def select_joint(self, index):
        self.selected_joint = index
        # Visual feedback for selection
        for i, slider in enumerate([self.slider0, self.slider1, self.slider2]):
            slider.color = color.yellow if i == index else color.rgba(0, 1, 1, 0.4) # Restaurado a Cyan (0,1,1) base con glow

sim = RobotArmSim()

def update():
    sim.update()

# Bucle principal de Ursina
app.run()
