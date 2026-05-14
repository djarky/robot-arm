import os
import math
import gltf
from ursina import destroy, Entity, color, Cylinder, Pipe, Vec3
from ursina.physics import PhysicsEntity
from panda3d.core import NodePath
from .collider_utils import ConvexHullCollider, TorusCompoundCollider

class SpawnMixin:
    """Mixin for spawning logic and previews."""
    BLUEPRINT_COLOR = color.rgba(0, 0.7, 1, 0.25)  # Cian semi-transparente

    def _create_spawn_preview(self, shape, size, model_path=None):
        """Crea un preview 'blueprint' del objeto a spawnear.
        Muestra la forma real con apariencia holográfica."""
        # Limpiar preview anterior (solo la entidad, NO el pending_spawn_data)
        if self.spawn_preview:
            destroy(self.spawn_preview)
            self.spawn_preview = None

        preview_model = None

        if shape == "cube":
            preview_model = 'cube'
        elif shape == "sphere":
            preview_model = 'sphere'
        elif shape == "cylinder":
            preview_model = Cylinder(resolution=16)
        elif shape == "torus":
            torus_path = [Vec3(math.cos(math.radians(i * (360 / 30))), 0,
                         math.sin(math.radians(i * (360 / 30)))) for i in range(31)]
            cross_section = [Vec3(math.cos(math.radians(i * (360 / 8))) * 0.2,
                            math.sin(math.radians(i * (360 / 8))) * 0.2, 0) for i in range(9)]
            try:
                preview_model = Pipe(path=torus_path, base_shape=cross_section, cap_ends=False)
            except Exception:
                preview_model = 'sphere'
        elif shape == "custom" and model_path:
            # Intentar cargar el modelo GLB para el preview
            ext = os.path.splitext(model_path)[1].lower()
            if ext in ('.glb', '.gltf'):
                try:
                    panda_node = gltf.load_model(model_path)
                    loaded_np = NodePath(panda_node)

                    # Crear entity contenedor
                    self.spawn_preview = Entity(
                        scale=size,
                        color=self.BLUEPRINT_COLOR,
                        enabled=False,
                        always_on_top=True,
                        unlit=True
                    )
                    # Normalizar el modelo (misma lógica que spawn_object)
                    bounds = loaded_np.getTightBounds()
                    if bounds:
                        min_p, max_p = bounds
                        extent = max(
                            max_p.getX() - min_p.getX(),
                            max_p.getY() - min_p.getY(),
                            max_p.getZ() - min_p.getZ()
                        )
                        if extent > 0:
                            norm_scale = 1.0 / extent
                            loaded_np.setScale(norm_scale)
                            cx = (min_p.getX() + max_p.getX()) / 2.0
                            cy = (min_p.getY() + max_p.getY()) / 2.0
                            cz = (min_p.getZ() + max_p.getZ()) / 2.0
                            loaded_np.setPos(-cx * norm_scale, -cy * norm_scale, -cz * norm_scale)

                    loaded_np.reparentTo(self.spawn_preview)
                    # Aplicar color blueprint a todos los geom nodes
                    loaded_np.setColorScale(0, 0.7, 1, 0.25)
                    loaded_np.setTransparency(True)

                    self.spawn_preview.collider = None
                    print(f"[Preview] GLB preview creado para: {model_path}")
                    return
                except Exception as e:
                    print(f"[Preview] Error cargando GLB preview, usando cubo: {e}")
                    preview_model = 'cube'
            else:
                preview_model = 'cube'
        else:
            preview_model = 'cube'

        # Crear preview con forma estándar
        self.spawn_preview = Entity(
            model=preview_model,
            scale=size,
            color=self.BLUEPRINT_COLOR,
            enabled=False,
            always_on_top=True,
            unlit=True
        )
        self.spawn_preview.collider = None
        print(f"[Preview] Blueprint preview creado: {shape} (size={size})")

    def _destroy_spawn_preview(self):
        """Destruye el preview de spawn y limpia el estado."""
        if self.spawn_preview:
            destroy(self.spawn_preview)
            self.spawn_preview = None
        self.pending_spawn_data = None

    def spawn_object(self, shape, size, mass, position=None, model_path=None):
        """Spawnea objetos con físicas Bullet reales.
        Cada objeto usa el collider que corresponde EXACTAMENTE a su geometría."""
        spawn_pos = position if position else (2.5, 3, 0)
        obj = None

        if shape == "cube":
            # BulletBoxShape IS the exact shape of a cube
            obj = PhysicsEntity(
                model='cube', scale=size, color=color.random_color(),
                position=spawn_pos, collider='box',
                mass=mass, friction=0.7
            )

        elif shape == "sphere":
            # BulletSphereShape IS the exact shape of a sphere — rolls naturally
            obj = PhysicsEntity(
                model='sphere', scale=size, color=color.random_color(),
                position=spawn_pos, collider='sphere',
                mass=mass, friction=0.5
            )
        elif shape == "cylinder":
            # ConvexHullShape from the real cylinder vertices — rolls naturally
            cyl_model = Cylinder(resolution=16)
            obj = PhysicsEntity(
                model=cyl_model, scale=size, color=color.random_color(),
                position=spawn_pos, mass=mass, friction=0.5
            )
            try:
                hull = ConvexHullCollider(obj.entity.model)
                obj.node.addShape(hull)
            except Exception as e:
                print(f"[Spawn] Cylinder hull fallback: {e}")
                obj.collider = 'box'
        elif shape == "torus":
            # CompoundShape of N segmented ConvexHulls — hole is traversable
            torus_path = [Vec3(math.cos(math.radians(i * (360 / 30))), 0,
                         math.sin(math.radians(i * (360 / 30)))) for i in range(31)]
            cross_section = [Vec3(math.cos(math.radians(i * (360 / 8))) * 0.2,
                            math.sin(math.radians(i * (360 / 8))) * 0.2, 0) for i in range(9)]
            try:
                torus_model = Pipe(path=torus_path, base_shape=cross_section, cap_ends=False)
                torus_model.generate_normals()
                torus_model.smooth = True
                obj = PhysicsEntity(
                    model=torus_model, scale=size, color=color.random_color(),
                    position=spawn_pos, mass=mass, friction=0.5
                )
                hulls = TorusCompoundCollider(obj.entity.model, num_segments=8)
                for hull_shape in hulls:
                    obj.node.addShape(hull_shape)
                if not hulls:
                    print("[Spawn] Torus: no hull segments, using convex hull")
                    hull = ConvexHullCollider(obj.entity.model)
                    obj.node.addShape(hull)
            except Exception as e:
                print(f"[Spawn] Torus error: {e}")
                obj = PhysicsEntity(
                    model='sphere', scale=(size, size * 0.5, size),
                    color=color.random_color(), position=spawn_pos,
                    collider='sphere', mass=mass, friction=0.5
                )
        elif shape == "custom" and model_path:
            try:
                ext = os.path.splitext(model_path)[1].lower()
                loaded_np = None

                if ext in ('.glb', '.gltf'):
                    # Usar gltf.load_model — misma técnica probada del brazo robótico
                    panda_node = gltf.load_model(model_path)
                    loaded_np = NodePath(panda_node)
                    print(f"[Spawn] Modelo GLB cargado: {model_path}")

                if loaded_np:
                    # ── Normalizar geometría para que quepa en un cubo unitario ──
                    bounds = loaded_np.getTightBounds()
                    if bounds:
                        min_p, max_p = bounds
                        extent = max(
                            max_p.getX() - min_p.getX(),
                            max_p.getY() - min_p.getY(),
                            max_p.getZ() - min_p.getZ()
                        )
                        if extent > 0:
                            norm_scale = 1.0 / extent
                            loaded_np.setScale(norm_scale)
                            # Centrar el modelo en el origen del entity
                            center_x = (min_p.getX() + max_p.getX()) / 2.0
                            center_y = (min_p.getY() + max_p.getY()) / 2.0
                            center_z = (min_p.getZ() + max_p.getZ()) / 2.0
                            loaded_np.setPos(
                                -center_x * norm_scale,
                                -center_y * norm_scale,
                                -center_z * norm_scale
                            )
                            print(f"[Spawn] Modelo normalizado: extent={extent:.1f} → scale={norm_scale:.4f}")
                        else:
                            loaded_np.setScale(1)
                    else:
                        loaded_np.setScale(1)
                        print("[Spawn] WARN: No se pudieron calcular bounds, usando scale=1")

                    # Crear PhysicsEntity con box collider
                    obj = PhysicsEntity(
                        model='cube', scale=size, color=color.white,
                        position=spawn_pos, collider='box',
                        mass=mass, friction=0.5
                    )
                    # Ocultar la geometría del cubo dummy usando stash
                    cube_geoms = obj.entity.findAllMatches('**/+GeomNode')
                    for g in cube_geoms:
                        g.stash()

                    # Reparentar el modelo normalizado al entity visual
                    loaded_np.reparentTo(obj.entity)
                    # Bloquear la herencia de color del padre
                    loaded_np.setColorScaleOff()
                    print(f"[Spawn] Modelo custom spawneado con box collider")
                else:
                    # Para OBJ y otros formatos
                    obj = PhysicsEntity(
                        model=model_path, scale=size, color=color.random_color(),
                        position=spawn_pos, mass=mass, friction=0.5
                    )
                    hull = ConvexHullCollider(obj.entity.model)
                    obj.node.addShape(hull)
            except Exception as e:
                print(f"[Spawn] Error cargando modelo custom ({model_path}): {e}")
                import traceback
                traceback.print_exc()
                # Fallback a cubo si falla
                obj = PhysicsEntity(
                    model='cube', scale=size, color=color.random_color(),
                    position=spawn_pos, collider='box',
                    mass=mass, friction=0.7
                )

        if obj:
            obj.is_spawned_toy = True
            if hasattr(obj, 'entity'):
                # Proxy invisible estricto que Ursina siempre detectará en sus raycasts normales
                picker = Entity(parent=obj.entity, model='cube', scale=1, collider='box', color=color.clear)
                picker.is_spawned_toy = True
                picker.parent_physics = obj
            self.spawned_objects.append(obj)
