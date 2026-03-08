import pybullet as p
import pybullet_data
import os
import time

class ArmController:
    def __init__(self):
        self.physics_client = p.connect(p.DIRECT) # Usar DIRECT para integración en GUI
        p.setAdditionalSearchPath(pybullet_data.getDataPath())
        p.setGravity(0, 0, -9.81)
        
        self.plane_id = p.loadURDF("plane.urdf")
        
        # Ruta al modelo URDF descargado
        urdf_path = os.path.join(os.getcwd(), "rrr-arm-model/rrr-arm-main/urdf/rrr_arm.urdf")
        
        if not os.path.exists(urdf_path):
            print(f"Error: No se encontró el URDF en {urdf_path}")
            self.robot_id = None
        else:
            self.robot_id = p.loadURDF(urdf_path, [0, 0, 0], useFixedBase=True)
            self.num_joints = p.getNumJoints(self.robot_id)
            print(f"Modelo cargado. Articulaciones detectadas: {self.num_joints}")

    def spawn_object(self, shape_type, size, mass, position):
        """Genera un objeto en la escena."""
        if shape_type == "box":
            visual_id = p.createVisualShape(p.GEOM_BOX, halfExtents=[size/2]*3)
            collision_id = p.createCollisionShape(p.GEOM_BOX, halfExtents=[size/2]*3)
        elif shape_type == "cylinder":
            visual_id = p.createVisualShape(p.GEOM_CYLINDER, radius=size/2, length=size)
            collision_id = p.createCollisionShape(p.GEOM_CYLINDER, radius=size/2, length=size)
        else:
            return None
            
        return p.createMultiBody(baseMass=mass,
                                baseCollisionShapeIndex=collision_id,
                                baseVisualShapeIndex=visual_id,
                                basePosition=position)

    def set_joint_angles(self, angles):
        """Actualiza los ángulos de las articulaciones del robot."""
        if self.robot_id is None: return
        
        # Mapear ángulos de 0-180 a radianes según los límites del URDF
        # Este modelo RRR suele tener 3 articulaciones rotativas principales
        for i in range(min(len(angles), self.num_joints)):
            rad = (angles[i] - 90) * (3.14159 / 180.0)
            p.setJointMotorControl2(bodyIndex=self.robot_id,
                                    jointIndex=i,
                                    controlMode=p.POSITION_CONTROL,
                                    targetPosition=rad)

    def step(self):
        p.stepSimulation()

    def get_camera_image(self, width=640, height=480):
        """Renderiza una imagen de la escena para mostrar en la GUI."""
        view_matrix = p.computeViewMatrixFromVisualizerConfig()
        proj_matrix = p.computeProjectionMatrixFOV(60, width/height, 0.01, 100)
        
        (_, _, px, _, _) = p.getCameraImage(width, height, view_matrix, proj_matrix, renderer=p.ER_TINY_RENDERER)
        return px

    def disconnect(self):
        p.disconnect()
