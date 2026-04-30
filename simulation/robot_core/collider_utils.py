import math
from panda3d.core import GeomVertexReader, LPoint3f
from panda3d.bullet import BulletConvexHullShape

def ConvexHullCollider(entity_model):
    """Genera BulletConvexHullShape a partir de los vértices reales del mesh.
    Se ajusta fielmente a la geometría — no es un AABB ni una caja."""
    shape = BulletConvexHullShape()
    geom_nodes = entity_model.findAllMatches('**/+GeomNode')
    for geom_np in geom_nodes:
        geom_node = geom_np.node()
        for i in range(geom_node.getNumGeoms()):
            shape.addGeom(geom_node.getGeom(i))
    return shape

def TorusCompoundCollider(entity_model, num_segments=8):
    """Genera N ConvexHulls segmentados para preservar el agujero del torus.
    Los objetos pueden pasar por el centro de la dona.
    Retorna lista de BulletConvexHullShape para addShape al RigidBodyNode."""
    shapes = []
    geom_nodes = entity_model.findAllMatches('**/+GeomNode')
    if geom_nodes.getNumPaths() == 0:
        return shapes

    # Collect ALL vertices from all geoms
    vertices = []
    for gn_np in geom_nodes:
        geom_node = gn_np.node()
        for gi in range(geom_node.getNumGeoms()):
            geom = geom_node.getGeom(gi)
            vdata = geom.getVertexData()
            reader = GeomVertexReader(vdata, 'vertex')
            while not reader.isAtEnd():
                v = reader.getData3f()
                vertices.append((v.x, v.y, v.z))

    if len(vertices) < 4:
        return shapes

    # Divide vertices into angular segments (by angle in the XZ plane)
    segment_verts = [[] for _ in range(num_segments)]
    for vx, vy, vz in vertices:
        angle = math.atan2(vz, vx)  # -pi to pi
        angle_norm = (angle + math.pi) / (2 * math.pi)  # 0 to 1
        seg_idx = int(angle_norm * num_segments) % num_segments
        # Add to this segment AND the next for overlap/continuity
        segment_verts[seg_idx].append(LPoint3f(vx, vy, vz))
        next_idx = (seg_idx + 1) % num_segments
        segment_verts[next_idx].append(LPoint3f(vx, vy, vz))

    for seg in segment_verts:
        if len(seg) < 4:
            continue
        hull = BulletConvexHullShape()
        for pt in seg:
            hull.addPoint(pt)
        shapes.append(hull)

    return shapes
