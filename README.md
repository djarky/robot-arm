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

## 📊 Flujo de Control y Arquitectura Interna

A continuación se detalla cómo interactúan y se actualizan las variables entre los distintos módulos del sistema:

### 1. Comunicación con Arduino (`arduino_control.ino` y `communication.py`)
- **Protocolo:** El Arduino (hardware esclavo) recibe datos por el puerto serial a 115200 baudios. El formato esperado es `"ANG1,ANG2,ANG3,GRIPPER\n"`.
- Los ángulos (Base, Hombro, Codo) se envían en el rango de 0 a 180 grados. El Gripper acepta 1 (cerrado) o 0 (abierto).
- **Desde la GUI:** Los sliders manipulan un rango semántico de -90 a 90 grados, pero al ser enviados por Serial se les aplica un mapeo (offset de +90).

### 2. Control Manual por Sliders (`gui_main.py`)
- Al modificar los sliders de la interfaz, el evento `valueChanged` desencadena la función `send_angles()`.
- **Efecto Dual:** Transmite los ángulos iterados tanto a la Simulación 3D vía UDP local (puerto 5005) como de manera Serial al Arduino.

### 3. Simulación 3D Bidireccional (`sim_3d.py`)
- **GUI -> Simulación:** Recibe rotaciones globales por UDP y las aplica forzosamente en las entidades 3D (`rotation_x`/`y`).
- **Simulación -> GUI:** Clicar y arrastrar los eslabones en 3D emite devoluciones constantes (`sync_angles`) por UDP al puerto 5006 de la GUI.
- **Bucle de retroalimentación:** La GUI lee las notificaciones usando un `QTimer` cada 50ms y actualiza la posición de los sliders. Durante esta actualización **se bloquean las señales** (`blockSignals(True)`); lo cual implica que mover la simulación no mueve por reflejo el brazo físico del Arduino.

### 4. Seguimiento y Mapeo por Cámara
- Se calcula la rotación local procesando las coordenadas (`landmarks`) de MediaPipe y usando matemática de vectores.
- Se implementa un filtro de Media Móvil Exponencial (EMA) para suavizar las altas fluctuaciones entre fotogramas.
- La salida del sensor de cámara genera movimientos **exclusivos** hacia el emulador gráfico a través del método de UDP `send_camera_angles()`, sin intervenir activamente en los sliders y por tanto eludiendo la conexión física con el Arduino.

### 5. Motor de Animación (`animation_manager.py`)
- Actúa como un motor de sub-pasos o interpolador a 30 FPS (`QTimer`).
- Al ejecutarse una secuencia desde el timeline, calcula interpolaciones (`deltas`) entre puntos A y B convirtiéndolas a flotantes.
- En cada "frame" se cambian los sliders sin activar eventos de interfaz, y se llama explícitamente a `send_angles()` para mover la arquitectura virtual y la física en asíncrono, dotando a la simulación y al Arduino de animaciones fluidas paso a paso.

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