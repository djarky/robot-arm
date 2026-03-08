from ursina import *
import numpy as np

class UrsinaArmController:
    def __init__(self):
        # La escena de Ursina se inicializa fuera si es necesario, 
        # pero para mantenerlo portable lo manejamos aquí.
        self.entities = []
        self.joints = []
        
        # Crear la base (Cilindro blanco como en el URDF)
        self.base = Entity(model='cylinder', color=color.white, scale=(0.6, 0.75, 0.6), y=0.375)
        
        # Link 1 (Ejemplo de brazo rrr)
        self.link1 = Entity(model='cube', color=color.gray, scale=(0.2, 1.0, 0.2), y=0.5, parent=self.base)
        self.link1.y = 1.0 # Posición relativa a la base
        
        # Link 2
        self.link2 = Entity(model='cube', color=color.light_gray, scale=(0.18, 0.75, 0.18), y=0.8, parent=self.link1)
        self.link2.y = 0.8
        
        # Guardamos las articulaciones para controlarlas
        # En Ursina, rotar el padre rota a los hijos.
        self.joints = [self.base, self.link1, self.link2]
        
        # Añadir suelo
        Entity(model='plane', scale=10, color=color.dark_gray, texture='white_cube')
        
        # Configurar cámara
        EditorCamera()

    def set_joint_angles(self, angles):
        """
        angles: lista de ángulos en grados [base, link1, link2]
        """
        if len(angles) >= 1:
            self.base.rotation_y = angles[0]
        if len(angles) >= 2:
            self.link1.rotation_x = angles[1] - 90
        if len(angles) >= 3:
            self.link2.rotation_x = angles[2] - 90

    def spawn_basic_object(self, shape, size, mass, position=(2, 0.5, 2)):
        # Ursina básico para visualización (la física real requeriría ursina.physics)
        obj = Entity(model=shape, scale=size, position=position, color=color.random_color())
        if shape == 'cube':
            obj.collider = 'box'
        elif shape == 'cylinder':
            obj.collider = 'mesh'
        return obj

    # Lógica de actualización de Ursina se llamaría en el loop principal de ursina
