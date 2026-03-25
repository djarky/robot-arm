import math
from ursina import *

class CircularJointSlider(Entity):
    def __init__(self, sim, joint_index, axis='YAW', radius=2.4, slider_color=color.cyan, **kwargs):
        # Resolución reducida para evitar "lag" masivo en colisionador de malla
        segments = 32 # Antes 100, mucho más ligero
        path = [Vec3(math.cos(math.radians(i*(360/segments)))*radius, 0, math.sin(math.radians(i*(360/segments)))*radius) for i in range(segments + 1)]
            
        thickness = 0.1 
        cross_segments = 8 # Antes 12
        cross_section = [Vec3(math.cos(math.radians(i*(360/cross_segments)))*thickness, math.sin(math.radians(i*(360/cross_segments)))*thickness, 0) for i in range(cross_segments + 1)]
        
        super().__init__(
            model=Pipe(path=path, base_shape=cross_section, cap_ends=False),
            color=color.rgba(slider_color.r, slider_color.g, slider_color.b, 0.4),
            double_sided=True,
            collider='mesh',
            **kwargs
        )
        
        if self.model:
            self.model.generate_normals()
            self.model.smooth = True
            
        self.unlit = True 
        self.sim = sim
        self.joint_index = joint_index
        self.axis_type = axis # YAW, PITCH, or ROLL
        self.base_color = slider_color
        self.dragging = False
        self.pulse_time = 0

        # Orientación según el eje lógico de Panda3D
        if self.axis_type == 'YAW': # Heading (Z)
            # J0 y J3 son YAW y funcionan bien en Horizontal (rot_x=0)
            self.rotation_x = 0
        elif self.axis_type == 'PITCH': # Pitch (X)
            # J4 y J5 son PITCH y funcionan bien en Horizontal (0,0,0)
            if joint_index in [4, 5]:
                self.rotation_x = 0
            else:
                self.rotation_z = 90
        elif self.axis_type == 'ROLL': # Roll (Y)
            # J1-J2 son ROLL y funcionan bien enfrentando Z
            self.rotation_x = 90

    def on_mouse_enter(self):
        self.color = color.rgba(1, 1, 1, 0.9)
    
    def on_mouse_exit(self):
        if not self.dragging:
            self.color = color.rgba(self.base_color.r, self.base_color.g, self.base_color.b, 0.4)

    def input(self, key):
        if key == 'left mouse down' and mouse.hovered_entity == self:
            self.dragging = True
            self.color = color.yellow
        elif key == 'left mouse up':
            self.dragging = False
            self.color = color.rgba(self.base_color.r, self.base_color.g, self.base_color.b, 0.4)

    def update(self):
        self.pulse_time += time.dt * 2
        if not self.dragging:
            alpha = 0.3 + math.sin(self.pulse_time) * 0.1
            self.color = color.rgba(self.base_color.r, self.base_color.g, self.base_color.b, alpha)

        if self.dragging:
            # Usar velocidad del ratón para incrementar el ángulo
            delta = mouse.velocity[0] + mouse.velocity[1]
            current_angle = self.sim._get_angle(self.joint_index)
            self.sim._apply_angle(self.joint_index, current_angle + delta * 500)
            self.sim.sync_to_gui()

class TranslationGizmo(Entity):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target = None
        
        # Color axes: Red=X, Green=Y, Blue=Z.
        axis_length = 1.5
        arrow_size = 0.2
        thick = 0.05
        
        # --- Eje X (Rojo) ---
        self.btn_x = Button(parent=self, model='cube', scale=(axis_length, thick, thick), position=(axis_length/2, 0, 0), color=color.red, collider='box')
        self.arrow_x = Entity(parent=self, model='cube', scale=(arrow_size, arrow_size, arrow_size*2), position=(axis_length, 0, 0), color=color.red, rotation=(0, 90, 0))
        
        # --- Eje Y (Verde) -> Ahora Horizontal (Z en Ursina) ---
        self.btn_y = Button(parent=self, model='cube', scale=(thick, thick, axis_length), position=(0, 0, axis_length/2), color=color.green, collider='box')
        self.arrow_y = Entity(parent=self, model='cube', scale=(arrow_size, arrow_size, arrow_size*2), position=(0, 0, axis_length), color=color.green, rotation=(0, 0, 0))
        
        # --- Eje Z (Azul) -> Ahora Vertical (Y en Ursina) ---
        self.btn_z = Button(parent=self, model='cube', scale=(thick, axis_length, thick), position=(0, axis_length/2, 0), color=color.blue, collider='box')
        self.arrow_z = Entity(parent=self, model='cube', scale=(arrow_size, arrow_size, arrow_size*2), position=(0, axis_length, 0), color=color.blue, rotation=(-90, 0, 0))

        # Configuraciones de botones
        for btn in (self.btn_x, self.btn_y, self.btn_z):
            btn.highlight_color = color.yellow
            btn.pressed_color = color.white
            btn.on_click = self.start_drag
        
        self.active_axis = None
        self.original_target_pos = None
        self.drag_start_mouse_y = 0
        self.drag_start_mouse_x = 0
        
        # Iniciar apagado
        self.disable()

    def update(self):
        if self.target and self.active_axis:
            # Calcular delta respecto al movimiento del ratón
            # Ursina normaliza la posición del mouse entre -0.5 y 0.5
            dx = mouse.x - self.drag_start_mouse_x
            dy = mouse.y - self.drag_start_mouse_y
            
            # Ajustar velocidad
            speed = 20
            
            new_pos = list(self.original_target_pos)
            if self.active_axis == 'x':
                new_pos[0] += dx * speed
            elif self.active_axis == 'y':
                # En el nuevo sistema Y es Horizontal Forward (Z en Ursina)
                new_pos[2] += dy * speed
            elif self.active_axis == 'z':
                # En el nuevo sistema Z es Vertical (Y en Ursina)
                new_pos[1] += dy * speed
                
            self.target.position = tuple(new_pos)
            self.position = self.target.position
            
        elif self.target:
            self.position = self.target.position

    def input(self, key):
        if key == 'left mouse up' and self.active_axis:
            self.stop_drag()
            
    def start_drag(self):
        self.active_axis = None
        if mouse.hovered_entity == self.btn_x: self.active_axis = 'x'
        elif mouse.hovered_entity == self.btn_y: self.active_axis = 'y'
        elif mouse.hovered_entity == self.btn_z: self.active_axis = 'z'
        
        if self.active_axis:
            self.original_target_pos = self.target.position
            self.drag_start_mouse_x = mouse.x
            self.drag_start_mouse_y = mouse.y
            
    def stop_drag(self):
        self.active_axis = None

    def attach_to(self, entity):
        self.target = entity
        self.position = entity.position
        self.enable()
        
    def detach(self):
        self.target = None
        self.disable()

    def delete_target(self):
        if self.target:
            obj = self.target
            self.detach() # Soltar el objeto
            
            # Quitar de la lista de la simulación
            if hasattr(scene, 'sim_instance') and obj in scene.sim_instance.spawned_objects:
                scene.sim_instance.spawned_objects.remove(obj)
                
            destroy(obj)
