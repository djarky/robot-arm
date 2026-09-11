# Requisitos del Sistema - Experiment Lab

Este documento detalla los requisitos necesarios para ejecutar el Laboratorio de Experimentos del brazo robótico.

## 🐍 Entorno de Software
- **Python**: Versión 3.10 o superior.
- **Sistema Operativo**: Windows 10/11 o Linux.

## 📦 Dependencias de Python
El sistema utiliza un entorno virtual (`venv`). Las librerías necesarias son:
- `PySide6`: Para la interfaz gráfica avanzada.
- `ursina`: Para el motor de simulación 3D.
- `opencv-python`: Para el procesamiento de visión.
- `mediapipe`: Para el seguimiento de gestos.
- `pyserial`: Para la comunicación con el hardware Arduino.
- `pygame-ce`: **(Nuevo)** Necesario para la gestión de mandos y joysticks estándar.
- `requests`: **(Nuevo)** Necesario para la comunicación de red del laboratorio.
- `paho-mqtt`: **(Nuevo)** Para la comunicación por WiFi a través de un Broker MQTT.
- `evdev`: **(Opcional, Linux)** Para lectura directa de hardware de entrada.
- `pysdl2` y `pysdl2-dll`: **(Opcional)** Para el backend de SDL2 directo.

## 🛠️ Hardware
- **Cámara USB**: Necesaria para el seguimiento de gestos (si se habilita).
- **Arduino**: Opcional. Permite el control del brazo físico.
- **Mando / Joystick**: Opcional. El laboratorio permite control directo mediante dispositivos compatibles con Pygame.

## 🤖 Inteligencia Artificial y Drivers - OPCIONAL
El sistema tiene un Agente de IA y múltiples backends de entrada integrados.
- **IA (Ollama)**: El sistema detectará si Ollama está disponible y usará respuestas "Mock" si no lo está.
- **Drivers de Entrada**: El sistema detectará automáticamente qué librerías están instaladas (`evdev`, `pysdl2`). Si fallan al instalarse, el laboratorio seguirá funcionando perfectamente usando el backend estándar de `pygame`.

---

## 🌐 Configuración del Broker MQTT (WiFi)

Para la comunicación inalámbrica del brazo robótico, se requiere un Broker MQTT activo. Tienes dos opciones de configuración:

### Opción A: Broker Local (Mosquitto en tu PC) - RECOMENDADO
*Funciona completamente offline, con latencia mínima (<1ms) y es 100% privado.*

Para instalar **Eclipse Mosquitto** en tu sistema Linux:

1. **Instalar el software**:
   ```bash
   sudo apt update
   sudo apt install mosquitto mosquitto-clients
   ```

2. **Iniciar el servicio**:
   ```bash
   sudo systemctl enable mosquitto
   sudo systemctl start mosquitto
   ```

3. **Permitir conexiones de red local (Importante)**:
   Por defecto, Mosquitto solo acepta conexiones desde tu propia PC. Para permitir que la ESP32 o ESP8266 se conecte, edita el archivo de configuración:
   ```bash
   sudo nano /etc/mosquitto/mosquitto.conf
   ```
   Añade las siguientes dos líneas al final del archivo:
   ```text
   listener 1883
   allow_anonymous true
   ```
   Guarda (`Ctrl+O`, `Enter`) y cierra (`Ctrl+X`).

4. **Reiniciar el broker**:
   ```bash
   sudo systemctl restart mosquitto
   ```
   *Una vez hecho, introduce la **IP local de tu PC** (ejemplo: `192.168.1.50`) en la interfaz de Python del Laboratorio y en tu microcontrolador.*

---

### Opción B: Broker Público en la Nube (Pruebas Rápidas)
*No requiere descargas, pero necesita conexión a internet constante y los datos viajan por un canal público de desarrollo.*

Configura tanto el laboratorio Python como la ESP32 con:
* **Broker**: `broker.hivemq.com` (o `broker.emqx.io`)
* **Puerto**: `1883`

> [!WARNING]
> Dado que el broker público está compartido de forma abierta, utiliza un tópico personalizado y único para evitar que otros usuarios reciban tus comandos (ej. `mi_robot_secreto_9918/angles`).
