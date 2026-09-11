import xml.etree.ElementTree as ET
import re
import math

class SVGInterpreter:
    """
    Parses SVG files and converts <path> elements into a list of 3D waypoints.
    """
    def __init__(self, scale=0.01):
        self.scale = scale # Mapeo de px a unidades del mundo (ej: 0.01 = 1cm por 100px)
        
    def parse_file(self, file_path):
        """
        Lee un SVG y extrae todos los puntos de las rutas.
        Retorna: Lista de listas de puntos [[(x,z), (x,z)...], [ruta2...]]
        """
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            
            # Namespace handling
            ns = {'svg': 'http://www.w3.org/2000/svg'}
            
            paths = []
            # Find all path elements
            for path_elem in root.findall('.//{http://www.w3.org/2000/svg}path') + root.findall('.//path'):
                d = path_elem.get('d')
                if d:
                    points = self._parse_d_attribute(d)
                    if points:
                        paths.append(points)
            return paths
        except Exception as e:
            print(f"[SVG] Error parsing file: {e}")
            return []

    def _parse_d_attribute(self, d):
        """
        Parsea el atributo 'd' de un path de SVG.
        """
        # Tokenize commands and numbers
        tokens = re.findall(r'([A-Za-z])|(-?\d*\.?\d+)', d)
        commands = []
        for cmd, val in tokens:
            if cmd:
                commands.append({'type': cmd, 'args': []})
            else:
                commands[-1]['args'].append(float(val))
        
        waypoints = []
        curr_pos = [0, 0]
        
        for cmd in commands:
            ctype = cmd['type']
            args = cmd['args']
            
            if ctype.upper() == 'M': # MoveTo
                for i in range(0, len(args), 2):
                    x, z = args[i], args[i+1]
                    if ctype == 'm': # Relative
                        curr_pos[0] += x
                        curr_pos[1] += z
                    else:
                        curr_pos[0] = x
                        curr_pos[1] = z
                    # M indicates a "pen up" movement usually, but here we just store the point
                    waypoints.append({'pos': tuple(curr_pos), 'pen': False})
                    
            elif ctype.upper() == 'L': # LineTo
                for i in range(0, len(args), 2):
                    x, z = args[i], args[i+1]
                    if ctype == 'l': # Relative
                        curr_pos[0] += x
                        curr_pos[1] += z
                    else:
                        curr_pos[0] = x
                        curr_pos[1] = z
                    waypoints.append({'pos': tuple(curr_pos), 'pen': True})

            elif ctype.upper() == 'C': # Cubic Bezier
                for i in range(0, len(args), 6):
                    p0 = tuple(curr_pos)
                    if ctype == 'c':
                        p1 = (curr_pos[0] + args[i], curr_pos[1] + args[i+1])
                        p2 = (curr_pos[0] + args[i+2], curr_pos[1] + args[i+3])
                        p3 = (curr_pos[0] + args[i+4], curr_pos[1] + args[i+5])
                    else:
                        p1 = (args[i], args[i+1])
                        p2 = (args[i+2], args[i+3])
                        p3 = (args[i+4], args[i+5])
                    
                    # Discretize
                    curve_points = self._discretize_bezier(p0, p1, p2, p3)
                    for pt in curve_points:
                        waypoints.append({'pos': pt, 'pen': True})
                    curr_pos = list(p3)
                    
            # Basic implementation: could add Q, S, T, A here
        
        return waypoints

    def _discretize_bezier(self, p0, p1, p2, p3, segments=20):
        """Genera puntos a lo largo de una curva Bezier cúbica."""
        points = []
        for i in range(1, segments + 1):
            t = i / segments
            # Fórmula de Bezier Cúbica
            x = (1-t)**3 * p0[0] + 3*(1-t)**2 * t * p1[0] + 3*(1-t) * t**2 * p2[0] + t**3 * p3[0]
            z = (1-t)**3 * p0[1] + 3*(1-t)**2 * t * p1[1] + 3*(1-t) * t**2 * p2[1] + t**3 * p3[1]
            points.append((x, z))
        return points

    def get_world_waypoints(self, svg_paths, origin=(0,0,0), rotation=0, scale=1.0, offset=(0,0)):
        """
        Convierte los puntos 2D del SVG a 3D (X, Y, Z) en el mundo de Ursina.
        offset: Desplazamiento local (cx, cz) aplicado al mesh para centrarlo.
        """
        world_paths = []
        cx, cz = offset
        for path in svg_paths:
            world_points = []
            for wp in path:
                # SVG (x, z) -> Ursina (X, Y, Z)
                # Restamos el offset para que el punto (0,0) sea el centro del blueprint
                lx = (wp['pos'][0] * self.scale - cx) * scale
                lz = (wp['pos'][1] * self.scale - cz) * scale
                
                # Rotación simple en el plano XZ
                rad = math.radians(-rotation) # Invertir para Ursina
                rx = lx * math.cos(rad) - lz * math.sin(rad)
                rz = lx * math.sin(rad) + lz * math.cos(rad)
                
                # Posición final
                fx = rx + origin[0]
                fz = rz + origin[2]
                fy = origin[1]
                
                world_points.append({
                    'pos': (fx, fy, fz),
                    'pen': wp['pen']
                })
            world_paths.append(world_points)
        return world_paths
