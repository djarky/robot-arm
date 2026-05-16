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
        
        w = max_x - min_x
        d = max_z - min_z
        extent = max(w, d)
        
        # ── Paso 3: Crear entidad con mesh centrado y vertex colors ──
        initial_colors = [color.rgba32(0, 200, 255, 180)] * len(centered_verts)
        self.svg_blueprint = Entity(
            parent=scene,
            model=Mesh(vertices=centered_verts, colors=initial_colors, mode='line', thickness=3),
            color=color.white,
            always_on_top=True,
            unlit=True
        )
        self.svg_blueprint.world_position = Vec3(1.4, 0.05, 0)

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
            
        if hasattr(self, 'recalibrate_tool'):
            self.recalibrate_tool()
        
        bp = self.svg_blueprint
        raw_paths = bp.raw_paths
        
        # Offset usado para centrar el mesh
        cx, cz = getattr(bp, 'mesh_offset_raw', (0, 0))
        scale_factor = self.svg_interpreter.scale
        entity_scale = bp.world_scale
        entity_rot_y = bp.rotation_y
        
        rad = math.radians(-entity_rot_y)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        
        print(f"[CNC] Blueprint transform: pos={bp.world_position}, scale={entity_scale}, rot_y={entity_rot_y}")
        print(f"[CNC] Mesh offset: cx={cx:.4f}, cz={cz:.4f}, svg_scale={scale_factor}")
        
        self.cnc_trajectory = []
        
        for path in raw_paths:
            for wp in path:
                # Coordenada local del mesh (relativa al centro)
                local_x = wp['pos'][0] * scale_factor - cx
                local_z = wp['pos'][1] * scale_factor - cz
                
                self.cnc_trajectory.append({
                    'local_pos': (local_x, 0, local_z), # Y=0 en el plano del papel
                    'pen': wp['pen']
                })
        
        if not self.cnc_trajectory:
            print("[CNC] Error: Trayectoria vacía.")
            self._send_cnc_status("error", "Trayectoria vacía")
            return
        
        # Log primeros waypoints para verificación
        for i, wp in enumerate(self.cnc_trajectory[:3]):
            print(f"  WP[{i}]: local_pos={wp['local_pos']}, pen={'DOWN' if wp['pen'] else 'UP'}")
        
        print(f"[CNC] Pre-calculando {len(self.cnc_trajectory)} puntos usando IK Heurística (CCD)...")
        self._precalculate_trajectory()
        print(f"[CNC] Pre-cálculo completado. Iniciando trayectoria con seguimiento dinámico.")
        
        # Inicializar posición lógica del interpolador
        self.cnc_index = 0
        self.cnc_active = True
        self._update_cnc_logical_pos() # Calcular primera posición mundial
        print(f"[CNC] Trayectoria iniciada con seguimiento dinámico.")
        
        self._send_cnc_status("running")
        print(f"[CNC] Iniciando trayectoria con {len(self.cnc_trajectory)} puntos.")


    def _update_cnc_logical_pos(self):
        """Calcula la posición mundial del waypoint actual basada en el estado actual del blueprint."""
        if self.cnc_index >= len(self.cnc_trajectory): return None
        
        bp = self.svg_blueprint
        target = self.cnc_trajectory[self.cnc_index]
        local_target = Vec3(target['local_pos'])
        
        # 1. Escala
        world_target = Vec3(
            local_target.x * bp.world_scale.x,
            local_target.y * bp.world_scale.y,
            local_target.z * bp.world_scale.z
        )
        
        # 2. Rotación
        rad = math.radians(-bp.rotation_y)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        rx = world_target.x * cos_r - world_target.z * sin_r
        rz = world_target.x * sin_r + world_target.z * cos_r
        world_target.x = rx
        world_target.z = rz
        
        # 3. Posición
        world_target += bp.world_position
        
        # 4. Altura de seguridad
        if not target['pen']:
            world_target.y += self.cnc_safety_height
            
        return world_target

    def _solve_with_skeleton(self, target_pos, start_angles, iterations_per_step=15):
        """Doble Tanteo: usa el esqueleto REAL de Panda3D para encontrar los ángulos
        que minimizan la distancia del nodo CNC al objetivo.
        
        Para cada junta, prueba +step y -step, se queda con la dirección que
        acorta la distancia. Repite con pasos cada vez más finos.
        Garantizado de funcionar porque usa el mismo esqueleto que el renderer.
        """
        current_angles = list(start_angles)
        joints = [0, 1, 2, 4]  # J0 (base), J1 (hombro), J2 (codo), J4 (muñeca)
        step_sizes = [10.0, 5.0, 2.0, 1.0, 0.5, 0.2]
        
        for step in step_sizes:
            for _ in range(iterations_per_step):
                improved = False
                
                # Evaluar distancia actual
                for ji, a in enumerate(current_angles):
                    if ji < self.NUM_JOINTS:
                        self._apply_angle_raw(ji, a)
                self.actor.getPartBundle('modelRoot').forceUpdate()
                tip = Vec3(self.cnc_node.getPos(base.render))
                best_dist_sq = (tip.x - target_pos.x)**2 + (tip.y - target_pos.y)**2 + (tip.z - target_pos.z)**2
                
                if best_dist_sq < 0.0001:  # Distancia < 0.01 unidades = perfecto
                    return current_angles
                
                for j in joints:
                    original = current_angles[j]
                    lo, hi = self.JOINT_LIMITS[j] if j < len(self.JOINT_LIMITS) else (-90, 90)
                    
                    # ── Tanteo +step ──
                    test_plus = min(hi, original + step)
                    dist_plus = float('inf')
                    if test_plus != original:
                        current_angles[j] = test_plus
                        for ji, a in enumerate(current_angles):
                            if ji < self.NUM_JOINTS:
                                self._apply_angle_raw(ji, a)
                        self.actor.getPartBundle('modelRoot').forceUpdate()
                        tip = Vec3(self.cnc_node.getPos(base.render))
                        dist_plus = (tip.x - target_pos.x)**2 + (tip.y - target_pos.y)**2 + (tip.z - target_pos.z)**2
                    
                    # ── Tanteo -step ──
                    test_minus = max(lo, original - step)
                    dist_minus = float('inf')
                    if test_minus != original:
                        current_angles[j] = test_minus
                        for ji, a in enumerate(current_angles):
                            if ji < self.NUM_JOINTS:
                                self._apply_angle_raw(ji, a)
                        self.actor.getPartBundle('modelRoot').forceUpdate()
                        tip = Vec3(self.cnc_node.getPos(base.render))
                        dist_minus = (tip.x - target_pos.x)**2 + (tip.y - target_pos.y)**2 + (tip.z - target_pos.z)**2
                    
                    # ── Quedarse con el mejor ──
                    if dist_plus < best_dist_sq and dist_plus <= dist_minus:
                        current_angles[j] = test_plus
                        best_dist_sq = dist_plus
                        improved = True
                    elif dist_minus < best_dist_sq:
                        current_angles[j] = test_minus
                        best_dist_sq = dist_minus
                        improved = True
                    else:
                        current_angles[j] = original  # Revertir
                
                if not improved:
                    break  # Mínimo local con este paso, pasar a paso más fino
        
        return current_angles

    def _precalculate_trajectory(self):
        """Pre-calcula todos los ángulos usando el esqueleto real (doble tanteo).
        
        Cada punto parte de los ángulos del punto anterior, garantizando
        movimientos suaves y continuos (sin saltos)."""
        # Guardar ángulos originales para restaurar después
        saved_angles = list(self.angles)
        
        # Partimos de la posición actual del robot (reposo)
        current_guess = list(self.angles)
        total = len(self.cnc_trajectory)
        
        t_start = time.time()
        
        for i in range(total):
            # Calcular posición mundo del waypoint
            self.cnc_index = i
            world_target = self._update_cnc_logical_pos()
            
            # Resolver usando el esqueleto real
            angles = self._solve_with_skeleton(world_target, current_guess)
            
            # Guardar y encadenar
            self.cnc_trajectory[i]['angles'] = angles
            self.cnc_trajectory[i]['world_pos'] = world_target
            current_guess = list(angles)
            
            # Progreso cada 50 puntos
            if (i + 1) % 50 == 0:
                elapsed = time.time() - t_start
                print(f"  [CNC Pre-Calc] {i+1}/{total} puntos ({elapsed:.1f}s)")
        
        elapsed = time.time() - t_start
        print(f"  [CNC Pre-Calc] Completado: {total} puntos en {elapsed:.1f}s")
        
        # Restaurar ángulos originales y resetear index
        for ji, a in enumerate(saved_angles):
            if ji < self.NUM_JOINTS:
                self._apply_angle_raw(ji, a)
        self.actor.getPartBundle('modelRoot').forceUpdate()
        self.cnc_index = 0

    def _update_cnc_execution(self):
        """Mueve el brazo suavemente hacia el waypoint actual usando interpolación por tiempo."""
        if self.cnc_index >= len(self.cnc_trajectory):
            self.cnc_active = False
            self._send_cnc_status("completed")
            print("[CNC] Trayectoria completada.")
            if hasattr(self, 'cnc_logical_pos'): del self.cnc_logical_pos
            return
            
        # Calcular posición mundial ACTUAL (por si el blueprint se movió)
        target_pos = self._update_cnc_logical_pos()
        if target_pos is None: return
        
        pen_down = self.cnc_trajectory[self.cnc_index]['pen']
        
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
        # ── Aplicar Ángulos Pre-Calculados ──
        # Usamos directamente los ángulos del waypoint actual (ya optimizados por el doble tanteo)
        wp_idx = min(self.cnc_index, len(self.cnc_trajectory) - 1)
        angles = self.cnc_trajectory[wp_idx]['angles']
            
        if angles:
            self._apply_angles_batched(angles, force=True)
            
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
            # Punto inalcanzable (incluso proyectado) o error de límites
            # NO saltamos el punto automáticamente, dejamos que el brazo lo intente alcanzar.
            # Esto permite que el láser de depuración guíe al usuario.
            if not getattr(self, '_ik_fail_logged', False):
                print(f"[CNC] Punto {self.cnc_index} fuera de alcance. Esperando...")
                self._ik_fail_logged = True
            
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
        """Trazado virtual: el brazo INTENTA alcanzar cada punto del SVG
        usando el doble tanteo con el esqueleto real.
        
        Verde = CNC tip tocó el punto
        Amarillo = cerca pero no exacto
        Rojo = no pudo alcanzar
        """
        bp = self.svg_blueprint
        if not bp or not bp.model or not bp.model.vertices:
            return
        
        if not hasattr(self, 'cnc_node') or self.cnc_node.isEmpty():
            return
        
        saved_angles = list(self.angles)
        
        entity_pos = bp.world_position
        entity_scale = bp.world_scale
        entity_rot_y = bp.rotation_y
        
        rad = math.radians(-entity_rot_y)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        
        verts = bp.model.vertices
        
        col_ok = color.rgba32(0, 255, 100, 220)
        col_marginal = color.rgba32(255, 200, 0, 220)
        col_bad = color.rgba32(255, 40, 40, 240)
        
        reach_ok = 0.1
        reach_warn = 0.5
        
        # Muestrear cada N vértices para rendimiento (el skeleton solver es pesado)
        sample_step = 6
        cached_results = []
        current_guess = list(self.angles)
        
        for vi in range(0, len(verts), sample_step):
            v = verts[vi]
            
            scaled_x = v[0] * entity_scale.x
            scaled_z = v[2] * entity_scale.z
            
            rx = scaled_x * cos_r - scaled_z * sin_r
            rz = scaled_x * sin_r + scaled_z * cos_r
            
            target = Vec3(
                rx + entity_pos.x,
                entity_pos.y,
                rz + entity_pos.z
            )
            
            # Resolver usando el esqueleto real (3 pasos rápidos para preview)
            angles = self._solve_with_skeleton(target, current_guess, iterations_per_step=3)
            current_guess = list(angles)
            
            # Medir distancia real resultante
            tip_pos = Vec3(self.cnc_node.getPos(base.render))
            dist = (tip_pos - target).length()
            
            if dist < reach_ok:
                c = col_ok
            elif dist < reach_warn:
                c = col_marginal
            else:
                c = col_bad
            
            for j in range(sample_step):
                if vi + j < len(verts):
                    cached_results.append(c)
        
        while len(cached_results) < len(verts):
            cached_results.append(col_bad)
        
        # Restaurar ángulos originales
        for i, a in enumerate(saved_angles):
            if i < self.NUM_JOINTS:
                self._apply_angle_raw(i, a)
        self.actor.getPartBundle('modelRoot').forceUpdate()
        
        bp.model.colors = cached_results[:len(verts)]
        bp.model.generate()
