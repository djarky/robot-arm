import math
import time
from ursina import destroy, Entity, Mesh, color, Vec3, scene

class CNCMixin:
    """Mixin for CNC and SVG logic."""
    
    def _load_svg_blueprint(self, path):
        """Carga el SVG y crea una representación visual (holograma)."""
        if self.svg_blueprint:
            if self.svg_blueprint in self.spawned_objects:
                self.spawned_objects.remove(self.svg_blueprint)
            destroy(self.svg_blueprint)
            self.svg_blueprint = None
        
        raw_paths = self.svg_interpreter.parse_file(path)
        if not raw_paths:
            print(f"[CNC] Error: No se encontraron rutas en {path}")
            return
        
        # ── Paso 1: Generar vértices crudos y calcular bounding box ──
        raw_verts = []
        min_x, max_x = float('inf'), float('-inf')
        min_z, max_z = float('inf'), float('-inf')
        
        for svg_path in raw_paths:
            for i in range(len(svg_path)-1):
                x1 = svg_path[i]['pos'][0] * self.svg_interpreter.scale
                z1 = svg_path[i]['pos'][1] * self.svg_interpreter.scale
                x2 = svg_path[i+1]['pos'][0] * self.svg_interpreter.scale
                z2 = svg_path[i+1]['pos'][1] * self.svg_interpreter.scale
                raw_verts.append((x1, z1))
                raw_verts.append((x2, z2))
                min_x = min(min_x, x1, x2)
                max_x = max(max_x, x1, x2)
                min_z = min(min_z, z1, z2)
                max_z = max(max_z, z1, z2)
        
        if not raw_verts:
            print("[CNC] Error: SVG no generó vértices.")
            return
        
        # ── Paso 2: Centrar vértices en el origen local ──
        cx = (min_x + max_x) / 2
        cz = (min_z + max_z) / 2
        centered_verts = [(x - cx, 0, z - cz) for x, z in raw_verts]
        
        w = max(max_x - min_x, 0.2)
        d = max(max_z - min_z, 0.2)
        extent = max(w, d)
        
        # ── Paso 3: Crear entidad con mesh centrado y vertex colors ──
        # La posición del Entity ES el centro del dibujo.
        initial_colors = [color.rgba32(0, 200, 255, 180)] * len(centered_verts)  # Cyan por defecto
        self.svg_blueprint = Entity(
            parent=scene,
            model=Mesh(vertices=centered_verts, colors=initial_colors, mode='line', thickness=3),
            color=color.white,
            always_on_top=True,
            unlit=True
        )
        self.svg_blueprint.world_position = Vec3(1.85, 0.05, 0)

        self.svg_blueprint.raw_paths = raw_paths
        self.svg_blueprint.is_svg_blueprint = True
        self.svg_blueprint.mesh_extent = extent
        self.svg_blueprint.mesh_offset_raw = (cx, cz)
        self.svg_blueprint.vert_count = len(centered_verts)
        
        # ── Mapeo de segmentos a waypoints ──
        seg_wp_end = []  # Para cada segmento s, el índice plano del waypoint final
        flat_idx = 0
        for svg_path in raw_paths:
            for i in range(len(svg_path) - 1):
                seg_wp_end.append(flat_idx + i + 1)
            flat_idx += len(svg_path)
        self.svg_blueprint.seg_wp_end = seg_wp_end
        
        # ── Paso 4: Picker centrado en (0,0,0) local ──
        picker = Entity(
            parent=self.svg_blueprint,
            model='cube',
            color=color.rgba(0, 0.7, 1, 0.08),
            position=(0, 0, 0),
            scale=(w, 0.15, d),
            collider='box'
        )
        picker.is_spawned_toy = True
        picker.parent_physics = self.svg_blueprint
        
        self.svg_blueprint.is_spawned_toy = True 
        self.spawned_objects.append(self.svg_blueprint)
        
        self._send_cnc_status("loaded")
        print(f"[CNC] Blueprint cargado: {path} ({len(centered_verts)//2} segmentos, {len(seg_wp_end)} trazos, extent={extent:.1f})")


    def _start_cnc_execution(self):
        """Prepara los waypoints de mundo directamente desde las coordenadas del mesh,
        garantizando que coincidan con la posición visual del blueprint."""
        if not self.svg_blueprint:
            print("[CNC] Error: No hay SVG cargado.")
            self._send_cnc_status("error", "No hay SVG cargado")
            return
        
        bp = self.svg_blueprint
        raw_paths = bp.raw_paths
        
        # Offset usado para centrar el mesh
        cx, cz = getattr(bp, 'mesh_offset_raw', (0, 0))
        scale_factor = self.svg_interpreter.scale  # 0.02 (px → mundo)
        
        # Transformación REAL de la entidad
        entity_pos = bp.world_position
        entity_scale = bp.world_scale
        entity_rot_y = bp.rotation_y
        
        rad = math.radians(-entity_rot_y)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        
        print(f"[CNC] Blueprint transform: pos={entity_pos}, scale={entity_scale}, rot_y={entity_rot_y}")
        print(f"[CNC] Mesh offset: cx={cx:.4f}, cz={cz:.4f}, svg_scale={scale_factor}")
        
        self.cnc_trajectory = []
        
        for path in raw_paths:
            for wp in path:
                # 1. Coordenada local del mesh
                local_x = wp['pos'][0] * scale_factor - cx
                local_z = wp['pos'][1] * scale_factor - cz
                
                # 2. Aplicar escala de la entidad
                scaled_x = local_x * entity_scale.x
                scaled_z = local_z * entity_scale.z
                
                # 3. Aplicar rotación Y (en plano XZ)
                rot_x = scaled_x * cos_r - scaled_z * sin_r
                rot_z = scaled_x * sin_r + scaled_z * cos_r
                
                # 4. Trasladar a posición del mundo
                world_x = rot_x + entity_pos.x
                world_z = rot_z + entity_pos.z
                world_y = entity_pos.y  # Altura de dibujo = posición Y del blueprint
                
                self.cnc_trajectory.append({
                    'pos': (world_x, world_y, world_z),
                    'pen': wp['pen']
                })
        
        if not self.cnc_trajectory:
            print("[CNC] Error: Trayectoria vacía.")
            self._send_cnc_status("error", "Trayectoria vacía")
            return
        
        # Log primeros waypoints para verificación
        for i, wp in enumerate(self.cnc_trajectory[:3]):
            print(f"  WP[{i}]: pos={wp['pos']}, pen={'DOWN' if wp['pen'] else 'UP'}")
        
        self.cnc_index = 0
        self.cnc_active = True
        
        # Inicializar posición lógica del interpolador
        first_wp = self.cnc_trajectory[0]
        start_pos = Vec3(first_wp['pos'])
        if not first_wp['pen']:
            start_pos.y += self.cnc_safety_height
        self.cnc_logical_pos = start_pos
        
        self._send_cnc_status("running")
        print(f"[CNC] Iniciando trayectoria con {len(self.cnc_trajectory)} puntos.")


    def _update_cnc_execution(self):
        """Mueve el brazo suavemente hacia el waypoint actual usando interpolación por tiempo."""
        if self.cnc_index >= len(self.cnc_trajectory):
            self.cnc_active = False
            self._send_cnc_status("completed")
            print("[CNC] Trayectoria completada.")
            if hasattr(self, 'cnc_logical_pos'): del self.cnc_logical_pos
            return
            
        target = self.cnc_trajectory[self.cnc_index]
        target_pos = Vec3(target['pos'])
        pen_down = target['pen']
        
        if not pen_down:
            target_pos.y += self.cnc_safety_height

        # ── Interpolación de posición (Feedrate constante) ──
        if not hasattr(self, 'cnc_logical_pos'):
            self.cnc_logical_pos = Vec3(target_pos)

        direction = target_pos - self.cnc_logical_pos
        distance_to_wp = direction.length()
        
        # Velocidad de movimiento
        current_speed = self.cnc_feedrate * (3.0 if not pen_down else 1.0)
        move_step = current_speed * time.dt
        
        if move_step >= distance_to_wp or distance_to_wp < 0.001:
            # Hemos llegado al waypoint
            self.cnc_logical_pos = Vec3(target_pos)
            self.cnc_index += 1
        else:
            # Avanzar proporcionalmente
            self.cnc_logical_pos += direction.normalized() * move_step
        
        # ── Resolver IK y aplicar ──
        # Ursina (Y-up) -> IK Solver (Z-up)
        local_target = self.cnc_logical_pos - self.robot_root.world_position
        ik_coords = (local_target.x, local_target.z, local_target.y)
        angles = self.ik_solver.solve(ik_coords)
        
        if angles:
            self._apply_angles_batched(angles)
            
            # ── Actualizar rastro visual (solo si el pen está abajo) ──
            if pen_down:
                if not hasattr(self, '_last_trace_pos') or (self.cnc_logical_pos - self._last_trace_pos).length() > 0.02:
                    if hasattr(self, '_last_trace_pos') and getattr(self, '_pen_was_down', False):
                        # Continuación de trazo: añadir segmento
                        self.drawing_trace.model.vertices.append(Vec3(self._last_trace_pos))
                        self.drawing_trace.model.vertices.append(Vec3(self.cnc_logical_pos))
                    
                    self.drawing_trace.model.generate()
                    self._last_trace_pos = Vec3(self.cnc_logical_pos)
            
            self._pen_was_down = pen_down
            self.sync_to_gui()
        else:
            # Punto inalcanzable
            print(f"[CNC] Punto inalcanzable en index {self.cnc_index}, saltando...")
            self.cnc_index += 1
            if self.cnc_index < len(self.cnc_trajectory):
                next_wp = self.cnc_trajectory[self.cnc_index]
                self.cnc_logical_pos = Vec3(next_wp['pos'])
                if not next_wp['pen']:
                    self.cnc_logical_pos.y += self.cnc_safety_height
            self._pen_was_down = False
            if hasattr(self, '_last_trace_pos'): del self._last_trace_pos

        # Enviar progreso periódicamente (~5Hz)
        if self.cnc_index % max(1, len(self.cnc_trajectory) // 50) == 0:
            progress = int((self.cnc_index / len(self.cnc_trajectory)) * 100)
            self._send_cnc_status("running", progress=progress)
        
        # ── Actualizar colores de los trazos del blueprint (progreso visual) ──
        bp = self.svg_blueprint
        if bp and bp.model and hasattr(bp, 'seg_wp_end'):
            seg_map = bp.seg_wp_end
            num_segs = len(seg_map)
            # Solo actualizar cada ~30 pasos para rendimiento
            if num_segs > 0 and self.cnc_index % max(1, num_segs // 30) == 0:
                col_done = color.rgba32(50, 255, 50, 255)      # Verde brillante - completado
                col_curr = color.rgba32(255, 255, 0, 255)      # Amarillo - segmento actual
                col_pending = color.rgba32(0, 200, 255, 100)   # Cyan tenue - pendiente
                
                new_colors = []
                for s in range(num_segs):
                    end_idx = seg_map[s]
                    if self.cnc_index > end_idx:
                        c = col_done
                    elif self.cnc_index >= end_idx - 1:
                        c = col_curr
                    else:
                        c = col_pending
                    new_colors.append(c)  # Vértice inicio del segmento
                    new_colors.append(c)  # Vértice fin del segmento
                
                bp.model.colors = new_colors
                bp.model.generate()

    def _reset_cnc_trace(self):
        """Limpia el rastro visual y reinicia el índice si no está en marcha."""
        if self.drawing_trace:
            self.drawing_trace.model.vertices = []
            self.drawing_trace.model.generate()
        self._trace_segments = []
        
        # Resetear colores de los trazos del blueprint a cyan por defecto
        if self.svg_blueprint and self.svg_blueprint.model:
            vert_count = getattr(self.svg_blueprint, 'vert_count', 0)
            if vert_count > 0:
                self.svg_blueprint.model.colors = [color.rgba32(0, 200, 255, 180)] * vert_count
                self.svg_blueprint.model.generate()
        
        if not self.cnc_active:
            self.cnc_index = 0
            self._send_cnc_status("loaded", progress=0)
        
        if hasattr(self, '_last_trace_pos'): del self._last_trace_pos
        if hasattr(self, '_pen_was_down'): del self._pen_was_down
        print("[CNC] Rastro visual reiniciado.")

    def _update_blueprint_reachability(self):
        """Colorea cada segmento de línea del SVG según alcanzabilidad del IK.
        Verde = alcanzable, Rojo = fuera de rango."""
        bp = self.svg_blueprint
        if not bp or not bp.model or not bp.model.vertices:
            return
        
        entity_pos = bp.world_position
        entity_scale = bp.world_scale
        entity_rot_y = bp.rotation_y
        
        rad = math.radians(-entity_rot_y)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        
        verts = bp.model.vertices
        new_colors = []
        
        col_ok = color.rgba32(0, 255, 100, 220)    # Verde brillante
        col_bad = color.rgba32(255, 40, 40, 240)    # Rojo brillante
        
        for v in verts:
            # v es (local_x, 0, local_z) en espacio local del mesh
            scaled_x = v[0] * entity_scale.x
            scaled_z = v[2] * entity_scale.z
            
            rot_x = scaled_x * cos_r - scaled_z * sin_r
            rot_z = scaled_x * sin_r + scaled_z * cos_r
            
            world_x = rot_x + entity_pos.x
            world_z = rot_z + entity_pos.z
            world_y = entity_pos.y
            
            # El IK asume base en Y=0. Ajustamos al offset de robot_root
            # Ursina (Y-up) -> IK Solver (Z-up)
            local_target = Vec3(world_x, world_y, world_z) - self.robot_root.world_position
            ik_coords = (local_target.x, local_target.z, local_target.y)
            result = self.ik_solver.solve(ik_coords)
            new_colors.append(col_ok if result else col_bad)
        
        bp.model.colors = new_colors
        bp.model.generate()
