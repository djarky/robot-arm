# Robot Arm Control System

Un sistema avanzado y modular para el control de brazos robóticos, integrando visión artificial, simulación 3D e interfaces de hardware en tiempo real.

## 🚀 Características Principales

- **Seguimiento Híbrido por Cámara**: Utiliza MediaPipe Pose para el control de hombro y codo, y MediaPipe Hands para la rotación de la base mediante la orientación de la palma.
- **Simulación 3D Interactiva**: Motor de simulación basado en Ursina que permite previsualizar movimientos, interactuar con objetos y controlar el brazo mediante sliders circulares en 3D.
- **Control de Hardware Real**: Integración directa con Arduino vía Serial para ejecutar movimientos en un brazo robótico físico.
- **Galería de Poses**: Captura "snapshots" de configuraciones del brazo con miniaturas visuales generadas desde la simulación.
- **Timeline de Animaciones**: Crea secuencias de movimiento complejas arrastrando poses al timeline, ajustando duraciones e interpolando recorridos suavizados a 30 FPS.
- **Persistencia Inteligente**: Guarda automáticamente ángulos de juntas, configuración de cámara y preferencias de conexión.

## 🏗️ Arquitectura del Software

El proyecto sigue una estructura modular para facilitar el mantenimiento y la escalabilidad:

- **`gui_main.py`**: Punto de entrada principal y definición de la interfaz PySide6.
- **`gui/` Package**:
    - `widgets.py`: Componentes visuales personalizados (galería y timeline).
    - `camera_thread.py`: Hilo de procesamiento de MediaPipe.
    - `pose_manager.py`: Lógica de gestión y persistencia de poses.
    - `animation_manager.py`: Motor de secuencias e interpolación.
    - `communication.py`: Gestión de sockets UDP y comunicación Serial.
- **`sim_3d.py`**: Script de simulación Ursina (ejecutado como subproceso e incrustado en la GUI).
- **`arduino_control.ino`**: Firmware para el controlador Arduino.

## 🛠️ Requisitos e Instalación

### Dependencias
- Python 3.10+
- OpenCV
- MediaPipe
- PySide6
- Ursina (Panda3D)
- PySerial

### Ejecución Rápida
En sistemas Linux, puedes usar el script de lanzamiento que configura el entorno virtual automáticamente:

```bash
chmod +x run.sh
./run.sh
```

## 🎮 Controles de Simulación

- **R + Arrastrar**: Rotar junta seleccionada.
- **Shift + Click Izquierdo/Derecho**: Mover base/hombro y codo manualmente.
- **Editor Camera**: Permite orbitar y hacer zoom en la escena 3D de forma independiente.