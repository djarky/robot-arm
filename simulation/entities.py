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

class TransformationGizmo(Entity):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.target = None
        self.mode = None # 'translate', 'rotate', 'scale'
        self.lock_axis = None # 'x', 'y', 'z'
        
        # Geometría base (X=Rojo, Y=Verde/Z-Ursina, Z=Azul/Y-Ursina)
        # Adaptado al sistema Z-up de la simulación
        self.axis_length = 1.5
        self.thick = 0.05
        
        # Grupos de visualización
        self.visuals_translate = Entity(parent=self, enabled=True)
        self.visuals_rotate = Entity(parent=self, enabled=False)
        self.visuals_scale = Entity(parent=self, enabled=False)
        
        self.setup_visuals()
        
        self.active_axis = None
        self.original_transform = None
        self.drag_start_mouse = Vec2(0,0)
        
        self.target_original_color = None
        self.disable()

    def setup_visuals(self):
        # --- Traslación ---
        self.btn_tx = Button(parent=self.visuals_translate, model='cube', scale=(self.axis_length, self.thick, self.thick), 
                           position=(self.axis_length/2, 0, 0), color=color.red, collider='box')
        self.btn_ty = Button(parent=self.visuals_translate, model='cube', scale=(self.thick, self.thick, self.axis_length), 
                           position=(0, 0, self.axis_length/2), color=color.green, collider='box')
        self.btn_tz = Button(parent=self.visuals_translate, model='cube', scale=(self.thick, self.axis_length, self.thick), 
                           position=(0, self.axis_length/2, 0), color=color.blue, collider='box')
        
        # Flechas (Puntas)
        self.tip_tx = Entity(parent=self.visuals_translate, model='sphere', scale=0.15, position=(self.axis_length, 0, 0), color=color.red)
        self.tip_ty = Entity(parent=self.visuals_translate, model='sphere', scale=0.15, position=(0, 0, self.axis_length), color=color.green)
        self.tip_tz = Entity(parent=self.visuals_translate, model='sphere', scale=0.15, position=(0, self.axis_length, 0), color=color.blue)

        # --- Rotación (Anillos) ---
        self.setup_rotation_visuals()
        
        # --- Escala ---
        self.btn_sx = Button(parent=self.visuals_scale, model='cube', scale=(self.axis_length, self.thick, self.thick), 
                           position=(self.axis_length/2, 0, 0), color=color.red, collider='box')
        self.btn_sy = Button(parent=self.visuals_scale, model='cube', scale=(self.thick, self.thick, self.axis_length), 
                           position=(0, 0, self.axis_length/2), color=color.green, collider='box')
        self.btn_sz = Button(parent=self.visuals_scale, model='cube', scale=(self.thick, self.axis_length, self.thick), 
                           position=(0, self.axis_length/2, 0), color=color.blue, collider='box')
        
        self.tip_sx = Entity(parent=self.visuals_scale, model='cube', scale=0.15, position=(self.axis_length, 0, 0), color=color.red)
        self.tip_sy = Entity(parent=self.visuals_scale, model='cube', scale=0.15, position=(0, 0, self.axis_length), color=color.green)
        self.tip_sz = Entity(parent=self.visuals_scale, model='cube', scale=0.15, position=(0, self.axis_length, 0), color=color.blue)

        # Mapeo de ejes para visualización dinámica
        self.axis_entities = {
            'translate': {'x': [self.btn_tx, self.tip_tx], 'y': [self.btn_ty, self.tip_ty], 'z': [self.btn_tz, self.tip_tz]},
            'rotate': {'x': [self.rot_x], 'y': [self.rot_y], 'z': [self.rot_z]},
            'scale': {'x': [self.btn_sx, self.tip_sx], 'y': [self.btn_sy, self.tip_sy], 'z': [self.btn_sz, self.tip_sz]}
        }

        # Configuración común
        all_interactive = (self.btn_tx, self.btn_ty, self.btn_tz, self.btn_sx, self.btn_sy, self.btn_sz, 
                          self.rot_x, self.rot_y, self.rot_z)
        for btn in all_interactive:
            btn.highlight_color = color.yellow
            btn.pressed_color = color.white
            btn.on_click = self.start_drag

    def setup_rotation_visuals(self):
        res = 24
        path = [Vec3(math.cos(math.radians(i*(360/res))), 0, math.sin(math.radians(i*(360/res)))) for i in range(res+1)]
        cs = [Vec3(math.cos(math.radians(i*(360/8)))*0.02, math.sin(math.radians(i*(360/8)))*0.02, 0) for i in range(9)]
        
        self.rot_x = Button(parent=self.visuals_rotate, model=Pipe(path=path, base_shape=cs), color=color.red, rotation_z=90, collider='mesh')
        self.rot_y = Button(parent=self.visuals_rotate, model=Pipe(path=path, base_shape=cs), color=color.green, collider='mesh')
        self.rot_z = Button(parent=self.visuals_rotate, model=Pipe(path=path, base_shape=cs), color=color.blue, rotation_x=90, collider='mesh')

    def attach_to(self, entity):
        if self.target == entity: return
        
        if self.target:
            self.detach()
            
        self.target = entity
        # Guardar copia real del color para no perderlo
        self.target_original_color = color.Color(entity.color[0], entity.color[1], entity.color[2], entity.color[3])
        
        self.position = entity.position
        obj_size = max(entity.scale_x, entity.scale_y, entity.scale_z)
        self.world_scale = max(1.0, obj_size * 1.5)
        self.mode = None
        
        # Ocultar gizmo inicialmente
        self.visuals_translate.enabled = False
        self.visuals_rotate.enabled = False
        self.visuals_scale.enabled = False
        self.enable()

    def detach(self):
        if self.target and self.target_original_color:
            self.target.color = self.target_original_color
        self.target = None
        self.target_original_color = None
        self.disable()

    def input(self, key):
        if not self.target: return

        # Atajos de Blender
        if key == 'g': # Grab / Move
            self.mode = 'translate'
            self.visuals_translate.enabled = True
            self.visuals_rotate.enabled = False
            self.visuals_scale.enabled = False
            self.start_keyboard_op()
        elif key == 'r': # Rotate
            self.mode = 'rotate'
            self.visuals_translate.enabled = False
            self.visuals_rotate.enabled = True
            self.visuals_scale.enabled = False
            self.start_keyboard_op()
        elif key == 's': # Scale
            self.mode = 'scale'
            self.visuals_translate.enabled = False
            self.visuals_rotate.enabled = False
            self.visuals_scale.enabled = True
            self.start_keyboard_op()
        elif key == 'x' and not self.mode: # Delete
            self.delete_target()
        
        # Bloqueo de ejes (solo si hay modo activo)
        if self.mode:
            if key == 'x': self.lock_axis = 'x'
            elif key == 'y': self.lock_axis = 'y'
            elif key == 'z': self.lock_axis = 'z'
            
        # Confirmar / Cancelar
        if key == 'left mouse down' and self.mode:
            self.confirm_op()
            
        if key == 'escape':
            if self.mode:
                self.cancel_op()
            self.detach() # Soltar para reactivar físicas
            print("Deseleccionado y físicas activas")
        elif key == 'right mouse down' and self.mode:
            self.cancel_op()
            
        # Soltar ratón tras arrastre manual
        if key == 'left mouse up' and self.active_axis:
            self.active_axis = None

    def start_keyboard_op(self):
        self.lock_axis = None
        self.active_axis = 'keyboard'
        self.original_transform = {
            'pos': Vec3(*self.target.position),
            'rot': Vec3(*self.target.rotation),
            'scale': Vec3(*self.target.scale)
        }
        self.drag_start_mouse = Vec2(mouse.x, mouse.y)
        # Asegurar que el gizmo sea visible al iniciar operación de teclado
        if self.mode == 'translate': self.visuals_translate.enabled = True
        elif self.mode == 'rotate': self.visuals_rotate.enabled = True
        elif self.mode == 'scale': self.visuals_scale.enabled = True
        self.refresh_visual_colors()

    def start_drag(self):
        # Detectar qué botón se presionó
        self.active_axis = None
        h = mouse.hovered_entity
        if h in (self.btn_tx, self.btn_sx, self.rot_x): self.active_axis = 'x'
        elif h in (self.btn_ty, self.btn_sy, self.rot_y): self.active_axis = 'y'
        elif h in (self.btn_tz, self.btn_sz, self.rot_z): self.active_axis = 'z'
        
        if self.active_axis:
            self.original_transform = {
                'pos': Vec3(*self.target.position),
                'rot': Vec3(*self.target.rotation),
                'scale': Vec3(*self.target.scale)
            }
            self.drag_start_mouse = Vec2(mouse.x, mouse.y)
            # Determinar modo si no está ya activo por teclado
            if h in (self.btn_tx, self.btn_ty, self.btn_tz): self.mode = 'translate'
            elif h in (self.btn_sx, self.btn_sy, self.btn_sz): self.mode = 'scale'
            elif h in (self.rot_x, self.rot_y, self.rot_z): self.mode = 'rotate'

    def update(self):
        if not self.target: return
        
        # Efecto de parpadeo (blinking) cuando está seleccionado sin modo activo
        if not self.mode:
            import time
            # Pulsar entre color original y cian vibrante
            s = (math.sin(time.time() * 10) + 1) / 2 # 0 a 1
            t = 0.4 + s * 0.6
            c1 = self.target_original_color
            c2 = color.cyan
            self.target.color = color.Color(
                c1[0] + (c2[0] - c1[0]) * t,
                c1[1] + (c2[1] - c1[1]) * t,
                c1[2] + (c2[2] - c1[2]) * t,
                c1[3] + (c2[3] - c1[3]) * t
            )
        
        if not self.active_axis: return
        
        self.position = self.target.position
        
        # Bloqueo de ejes visuales dinámicos
        if self.mode and self.active_axis == 'keyboard':
            self.refresh_visual_colors()
            
        dx = (mouse.x - self.drag_start_mouse.x) * 20
        dy = (mouse.y - self.drag_start_mouse.y) * 20
            
        # Si es por teclado y no hay eje bloqueado, mover libremente en plano XY (Ursina)
        # Pero el usuario pidió bloquear ejes.
            
        eff_axis = self.lock_axis if self.active_axis == 'keyboard' else self.active_axis
            
        if self.mode == 'translate':
            new_pos = list(self.original_transform['pos'])
            val = dy if eff_axis in ('y', 'z') else dx
            idx = 0 if eff_axis == 'x' else (2 if eff_axis == 'y' else 1)
                
            if eff_axis:
                new_pos[idx] += val
            else: # Libre
                new_pos[0] += dx
                new_pos[2] += dy
            self.target.position = tuple(new_pos)
                
        elif self.mode == 'rotate':
            new_rot = list(self.original_transform['rot'])
            val = (dx + dy) * 50
            if eff_axis == 'x': new_rot[0] += val
            elif eff_axis == 'y': new_rot[2] += val
            elif eff_axis == 'z': new_rot[1] += val
            else: # Libre (YAW por defecto)
                new_rot[1] += val
            self.target.rotation = tuple(new_rot)
                
        elif self.mode == 'scale':
            new_scale = list(self.original_transform['scale'])
            fac = 1.0 + (dx + dy) * 0.5
            if eff_axis == 'x': new_scale[0] *= fac
            elif eff_axis == 'y': new_scale[2] *= fac
            elif eff_axis == 'z': new_scale[1] *= fac
            else: # Uniforme
                new_scale = [v * fac for v in new_scale]
            self.target.scale = tuple(new_scale)

    def confirm_op(self):
        self.active_axis = None
        self.mode = None
        self.lock_axis = None
        print("Transformación confirmada")

    def cancel_op(self):
        if self.original_transform:
            self.target.position = self.original_transform['pos']
            self.target.rotation = self.original_transform['rot']
            self.target.scale = self.original_transform['scale']
        self.active_axis = None
        self.mode = None
        self.lock_axis = None
        print("Transformación cancelada")

    def refresh_visual_colors(self):
        if not self.mode: return
        
        base_colors = {'x': color.red, 'y': color.green, 'z': color.blue}
        
        for axis_name, entities in self.axis_entities[self.mode].items():
            for e in entities:
                if self.lock_axis:
                    if axis_name == self.lock_axis:
                        e.color = color.white 
                        e.alpha = 1.0
                    else:
                        e.color = base_colors[axis_name]
                        e.alpha = 0.1 # Atenuar otros ejes
                else:
                    e.color = base_colors[axis_name]
                    e.alpha = 1.0

    def delete_target(self):
        if not self.target: return
        
        target_to_del = self.target
        self.detach() # Desasociar primero para limpiar colores/referencias
        
        import simulation
        # Buscar en la lista de la simulación para eliminarlo
        for scene_entity in scene.entities:
            if hasattr(scene_entity, 'spawned_objects') and isinstance(scene_entity, simulation.RobotArmSim):
                if target_to_del in scene_entity.spawned_objects:
                    scene_entity.spawn_objects_cleanup = True # Flag opcional para robot_sim
                    scene_entity.spawned_objects.remove(target_to_del)
                    break
        
        destroy(target_to_del)
        print("Objeto eliminado con éxito")
