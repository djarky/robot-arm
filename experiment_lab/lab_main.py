import sys
import os
import json
import subprocess
import time
import threading
import queue
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QPushButton, QLabel, QComboBox, QTextEdit, QFrame, QGroupBox,
    QSplitter, QSlider, QCheckBox, QLineEdit, QDoubleSpinBox, QFileDialog,
    QScrollArea
)
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QFont, QColor, QPalette

from communication import LabCommunication
from input_manager import InputManager
from input_mapper_dialog import InputMapperDialog
from fsm_engine import FSMEngine
from ai_agent import AIAgent
from cnc_widgets import CNCControlWidget
# El import de FSMDesignerWindow se hará dinámicamente o al principio

class ExperimentLabUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("INEXP-ursina | Laboratorio de Experimentos")
        self.resize(1000, 700)
        
        # Estilo Dark Premium
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; color: #e0e0e0; }
            QGroupBox { border: 2px solid #333; border-radius: 8px; margin-top: 15px; font-weight: bold; color: #4CAF50; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; }
            QPushButton { background-color: #1e1e1e; border: 1px solid #444; color: white; padding: 8px; border-radius: 4px; }
            QPushButton:hover { background-color: #333; border: 1px solid #4CAF50; }
            QPushButton#btn_connect { background-color: #2e7d32; }
            QLabel { color: #bbb; }
            QTextEdit { background-color: #000; color: #00ff00; border: 1px solid #222; font-family: 'Courier New'; }
            QComboBox, QDoubleSpinBox { background-color: #1e1e1e; border: 1px solid #444; color: white; padding: 3px; border-radius: 4px; }
            QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { background: #333; border: none; width: 16px; }
        """)

        self.comm = LabCommunication()
        self.input_mgr = InputManager()
        self.current_angles = [0.0] * 5
        self.last_sent_angles = [0.0] * 5
        self.last_interaction_time = 0
        self.sim_process = None
        self.log_queue = queue.Queue()
        
        self.init_ui()
        
        # FSM Engine
        self.fsm = FSMEngine()
        self.fsm_file = os.path.join(os.path.dirname(__file__), "fsm_sequences.json")
        self.all_fsm_data = {}
        self.load_fsm_library()
        
        # AI Agent
        self.ai_agent = AIAgent(self.ai_console)
        self.temp_screenshot_path = os.path.join(os.path.dirname(__file__), "assets", "temp_sim_state.png")

        # Lanzar simulación automáticamente
        QTimer.singleShot(500, self.launch_simulation)
        
        # Timers
        self.loop_timer = QTimer()
        self.loop_timer.timeout.connect(self.main_loop)
        self.loop_timer.start(30) # ~33 FPS

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        self.global_layout = QVBoxLayout(central)
        self.global_layout.setContentsMargins(5, 5, 5, 5)
        self.global_layout.setSpacing(5)
        
        # WIDGET SUPERIOR (Splitter Horizontal: Controles | Simulación) ---
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        self.top_splitter = QSplitter(Qt.Horizontal)
        
        # PANEL IZQUIERDO (Controles con Scroll)
        self.left_scroll = QScrollArea()
        self.left_scroll.setWidgetResizable(True)
        self.left_scroll.setFrameShape(QFrame.NoFrame)
        self.left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.left_scroll.setStyleSheet("background-color: transparent;")

        left_panel_widget = QWidget()
        left_panel_widget.setStyleSheet("background-color: transparent;")
        left_panel = QVBoxLayout(left_panel_widget)
        left_panel.setContentsMargins(5, 5, 5, 5)
        
        # Conexión Hardware (Serial / MQTT)
        conn_group = QGroupBox("Conexión de Hardware")
        conn_layout = QVBoxLayout()
        
        # Selector de Tipo de Conexión
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("Tipo de Conexión:"))
        self.conn_type_selector = QComboBox()
        self.conn_type_selector.addItems(["Puerto Serial (USB)", "WiFi (MQTT)"])
        self.conn_type_selector.currentIndexChanged.connect(self.on_connection_type_changed)
        type_layout.addWidget(self.conn_type_selector)
        conn_layout.addLayout(type_layout)
        
        # --- CONTENEDOR 1: SERIAL ---
        self.serial_container = QWidget()
        serial_box_layout = QVBoxLayout(self.serial_container)
        serial_box_layout.setContentsMargins(0, 5, 0, 0)
        
        port_header = QHBoxLayout()
        port_header.addWidget(QLabel("Puerto Serial:"))
        self.chk_exp_mode = QCheckBox("Modo Exp.")
        self.chk_exp_mode.setToolTip("Muestra todos los puertos, no solo Arduinos")
        self.chk_exp_mode.stateChanged.connect(self.refresh_ports)
        port_header.addWidget(self.chk_exp_mode)
        serial_box_layout.addLayout(port_header)
        
        self.port_selector = QComboBox()
        self.btn_connect = QPushButton("CONECTAR ARDUINO")
        self.btn_connect.setObjectName("btn_connect")
        self.btn_connect.clicked.connect(self.toggle_arduino)
        
        serial_box_layout.addWidget(self.port_selector)
        serial_box_layout.addWidget(self.btn_connect)
        conn_layout.addWidget(self.serial_container)
        
        # --- CONTENEDOR 2: MQTT ---
        self.mqtt_container = QWidget()
        self.mqtt_container.hide() # Oculto por defecto
        mqtt_box_layout = QVBoxLayout(self.mqtt_container)
        mqtt_box_layout.setContentsMargins(0, 5, 0, 0)
        
        # Formulario MQTT
        from PySide6.QtWidgets import QFormLayout
        mqtt_form = QFormLayout()
        mqtt_form.setLabelAlignment(Qt.AlignLeft)
        mqtt_form.setFormAlignment(Qt.AlignLeft)
        
        self.mqtt_broker_input = QLineEdit("192.168.1.100")
        self.mqtt_broker_input.setPlaceholderText("Ej: 192.168.1.100 o broker.hivemq.com")
        self.mqtt_port_input = QLineEdit("1883")
        self.mqtt_topic_input = QLineEdit("robot/arm/angles")
        
        mqtt_form.addRow("Broker:", self.mqtt_broker_input)
        mqtt_form.addRow("Puerto:", self.mqtt_port_input)
        mqtt_form.addRow("Tópico:", self.mqtt_topic_input)
        mqtt_box_layout.addLayout(mqtt_form)
        
        self.btn_connect_mqtt = QPushButton("CONECTAR MQTT")
        self.btn_connect_mqtt.setStyleSheet("background-color: #2e7d32; font-weight: bold;")
        self.btn_connect_mqtt.clicked.connect(self.toggle_mqtt)
        mqtt_box_layout.addWidget(self.btn_connect_mqtt)
        
        conn_layout.addWidget(self.mqtt_container)
        conn_group.setLayout(conn_layout)
        left_panel.addWidget(conn_group)
        
        # Gestión de Mandos
        input_group = QGroupBox("Entrada / Dispositivo")
        input_layout = QVBoxLayout()
        
        self.btn_configure_binds = QPushButton("⚙ CONFIGURAR BINDS")
        self.btn_configure_binds.setMinimumHeight(45)
        self.btn_configure_binds.clicked.connect(self.open_mapper_dialog)
        
        self.input_status = QLabel("Mando: Esperando...")
        input_layout.addWidget(self.btn_configure_binds)
        input_layout.addWidget(self.input_status)
        input_group.setLayout(input_layout)
        left_panel.addWidget(input_group)

        # Estado de Ángulos y Sliders Manuales
        angles_group = QGroupBox("Estado del Brazo / Control Manual")
        angles_layout = QVBoxLayout()
        self.angle_labels = []
        self.sliders = []
        for i in range(5):
            # Label
            lbl = QLabel(f"J{i}: 0.0°")
            angles_layout.addWidget(lbl)
            self.angle_labels.append(lbl)
            
            # Slider
            s = QSlider(Qt.Horizontal)
            s.setRange(-90, 90)
            s.setValue(0)
            s.setTickPosition(QSlider.TicksBelow)
            s.setTickInterval(15)
            # Conectamos el cambio del slider al envío de ángulos
            s.valueChanged.connect(lambda val, idx=i: self.on_slider_change(idx, val))
            angles_layout.addWidget(s)
            self.sliders.append(s)

        angles_group.setLayout(angles_layout)
        left_panel.addWidget(angles_group)

        # --- FSM DESIGNER LAUNCHER ---
        fsm_design_group = QGroupBox("Automatización / FSM")
        fsm_design_layout = QVBoxLayout()
        
        self.btn_open_fsm_designer = QPushButton("🚀 ABRIR DISEÑADOR FSM")
        self.btn_open_fsm_designer.setMinimumHeight(50)
        self.btn_open_fsm_designer.setStyleSheet("""
            QPushButton { 
                background-color: #1a237e; 
                border: 2px solid #3f51b5; 
                font-weight: bold; 
                font-size: 14px; 
            }
            QPushButton:hover { background-color: #283593; border: 2px solid #5c6bc0; }
        """)
        self.btn_open_fsm_designer.clicked.connect(self.open_fsm_designer)
        
        fsm_design_layout.addWidget(self.btn_open_fsm_designer)
        fsm_design_group.setLayout(fsm_design_layout)
        left_panel.addWidget(fsm_design_group)

        # --- CNC CONTROL WIDGET ---
        self.cnc_ctrl = CNCControlWidget()
        self.cnc_ctrl.file_selected.connect(self.comm.load_svg)
        self.cnc_ctrl.start_requested.connect(self.comm.start_svg_trajectory)
        self.cnc_ctrl.stop_requested.connect(self.comm.stop_svg_trajectory)
        self.cnc_ctrl.reset_requested.connect(self.comm.reset_cnc_trace)
        self.cnc_ctrl.params_changed.connect(self.comm.set_cnc_params)
        left_panel.addWidget(self.cnc_ctrl)

        left_panel.addStretch()
        
        self.left_scroll.setWidget(left_panel_widget)
        self.top_splitter.addWidget(self.left_scroll)
        
        # PANEL CENTRAL (Simulación Ursina)
        self.sim_container = QGroupBox("Visualización 3D (Ursina)")
        sim_layout = QVBoxLayout()
        # Spawn Bar (Similar a gui_main)
        spawn_row = QHBoxLayout()
        spawn_row.addWidget(QLabel("Spawn:"))
        self.obj_type = QComboBox()
        self.obj_type.addItems(["cube", "cylinder", "sphere", "torus", "svg", "custom..."])
        self.obj_type.setMinimumWidth(100)
        self.obj_type.currentIndexChanged.connect(self.on_spawn_type_changed)
        self.custom_model_path = None
        
        self.obj_size = QDoubleSpinBox()
        self.obj_size.setValue(0.5)
        self.obj_size.setRange(0.1, 10.0)
        self.obj_size.setSingleStep(0.1)
        
        self.obj_mass = QDoubleSpinBox()
        self.obj_mass.setValue(1.0)
        self.obj_mass.setRange(0.1, 100.0)
        
        self.btn_spawn = QPushButton("SPAWN")
        self.btn_spawn.setStyleSheet("background-color: #1a237e; font-weight: bold;")
        self.btn_spawn.clicked.connect(self.spawn_request)
        
        spawn_row.addWidget(self.obj_type)
        spawn_row.addWidget(QLabel("S:"))
        spawn_row.addWidget(self.obj_size)
        spawn_row.addWidget(QLabel("M:"))
        spawn_row.addWidget(self.obj_mass)
        spawn_row.addWidget(self.btn_spawn)
        spawn_row.addStretch()
        
        sim_layout.addLayout(spawn_row)
        
        self.sim_view = QWidget()
        self.sim_view.setStyleSheet("background-color: #000;")
        self.sim_view.setMinimumSize(500, 400)
        sim_layout.addWidget(self.sim_view)
        self.sim_container.setLayout(sim_layout)
        
        self.top_splitter.addWidget(self.sim_container)
        top_layout.addWidget(self.top_splitter)
        
        # Añadimos el widget superior al layout global con factor de expansión 1
        self.global_layout.addWidget(top_widget, 1)
        
        # --- BOTTOM PANEL (Consola y Chat) ---
        self.console_container = QGroupBox("Panel de Inteligencia y Estado")
        console_main_layout = QVBoxLayout()
        
        self.btn_toggle_console = QPushButton("▲ EXPANDIR PANEL")
        self.btn_toggle_console.clicked.connect(self.toggle_console)
        console_main_layout.addWidget(self.btn_toggle_console)

        # Splitter para separar Log de Chat
        self.bottom_splitter = QSplitter(Qt.Horizontal)
        
        # Lado Izquierdo: Consola de Logs (la existente)
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 5, 0, 0)
        self.ai_console = QTextEdit()
        self.ai_console.setReadOnly(True)
        self.ai_console.append(">> Sistema Lab inicializado. Ursina cargando...")
        log_layout.addWidget(QLabel("LOGS DEL SISTEMA:"))
        log_layout.addWidget(self.ai_console)
        self.bottom_splitter.addWidget(log_widget)

        # Lado Derecho: Chat con IA
        chat_widget = QWidget()
        chat_layout = QVBoxLayout(chat_widget)
        chat_layout.setContentsMargins(0, 5, 0, 0)
        
        self.chat_history = QTextEdit()
        self.chat_history.setReadOnly(True)
        self.chat_history.setStyleSheet("background-color: #0d1117; color: #c9d1d9; border: 1px solid #30363d;")
        self.chat_history.append("<span style='color:#58a6ff;'><b>Agente:</b> Hola, soy tu asistente de IA. ¿En qué puedo ayudarte con el brazo robótico?</span>")
        
        self.chat_input = QLineEdit()
        self.chat_input.setPlaceholderText("Escribe un mensaje al agente (ej: 'Qué ves en la escena?')...")
        self.chat_input.returnPressed.connect(self.send_to_ai)
        
        btn_send_chat = QPushButton("ENVIAR A IA")
        btn_send_chat.clicked.connect(self.send_to_ai)
        btn_send_chat.setStyleSheet("background-color: #238636; color: white; font-weight: bold;")
        
        chat_layout.addWidget(QLabel("CHAT CON AGENTE (Visual):"))
        chat_layout.addWidget(self.chat_history)
        chat_input_row = QHBoxLayout()
        chat_input_row.addWidget(self.chat_input)
        chat_input_row.addWidget(btn_send_chat)
        chat_layout.addLayout(chat_input_row)
        
        self.bottom_splitter.addWidget(chat_widget)
        
        console_main_layout.addWidget(self.bottom_splitter)
        self.console_container.setLayout(console_main_layout)
        
        self.bottom_splitter.hide() # Empezamos con el contenido oculto
        
        # Añadimos la consola al layout global
        self.global_layout.addWidget(self.console_container, 0)

        
        # Ahora que todo está inicializado, refrescamos los puertos
        self.refresh_ports()

    def refresh_ports(self):
        """Refresca la lista de puertos aplicando el filtro si Modo Exp está apagado."""
        self.port_selector.clear()
        filter_arduino = not self.chk_exp_mode.isChecked()
        ports = self.comm.list_ports(filter_arduino=filter_arduino)
        self.port_selector.addItems(ports)
        if not ports:
            self.ai_console.append(">> [Hardware] No se detectaron puertos compatibles.")

    def toggle_console(self):
        """Muestra/Oculta la caja de texto de la consola de forma limpia."""
        if self.bottom_splitter.isVisible():
            self.bottom_splitter.hide()
            self.btn_toggle_console.setText("▲ EXPANDIR PANEL")
        else:
            self.bottom_splitter.show()
            self.btn_toggle_console.setText("▼ MINIMIZAR PANEL")
        
        # Forzamos al layout a re-calcular el espacio
        self.global_layout.invalidate()
        self.global_layout.activate()

    def send_to_ai(self):
        """Envía el comando del chat a la IA junto con screenshot y estado."""
        prompt = self.chat_input.text().strip()
        if not prompt:
            return
            
        self.chat_history.append(f"<br><span style='color:#7986CB;'><b>Usuario:</b> {prompt}</span>")
        self.chat_input.clear()
        self.chat_input.setDisabled(True)
        
        # 1. Solicitar captura de pantalla
        self.ai_console.append(">> [AI] Capturando escena simulación...")
        self.comm.request_screenshot(self.temp_screenshot_path)
        
        # 2. Esperar delay para escritura y llamar en hilo para no bloquear
        # Usamos QTimer para dar tiempo al disco/sim y luego procesamos
        QTimer.singleShot(300, lambda: self._process_ai_query(prompt))

    def _process_ai_query(self, prompt):
        """Recopila datos y consulta al agente en segundo plano."""
        state = {
            "angles": self.current_angles,
            "collision": getattr(self, "last_feedback", {}).get("colliding", False),
            "timestamp": time.time()
        }
        
        # Para no bloquear el hilo principal de Qt, idealmente usaríamos un QThread,
        # pero para esta versión, llamaremos al agente que ya tiene su manejo de tiempo.
        # Nota: requests.post en query_with_image es bloqueante, en una app de producción
        # esto debería ir en un WorkerThread.
        try:
            response = self.ai_agent.query_with_image(prompt, self.temp_screenshot_path, state)
            self.chat_history.append(f"<span style='color:#4CAF50;'><b>Agente:</b> {response}</span>")
        except Exception as e:
            self.chat_history.append(f"<span style='color:#f44336;'><b>Agente (Error):</b> No pude procesar la consulta. {e}</span>")
        
        self.chat_input.setDisabled(False)
        self.chat_input.setFocus()
        # Scroll al final
        self.chat_history.verticalScrollBar().setValue(self.chat_history.verticalScrollBar().maximum())

    def launch_simulation(self):
        """Lanza la simulación Ursina incrustada."""
        win_id = str(int(self.sim_view.winId()))
        w = str(self.sim_view.width())
        h = str(self.sim_view.height())
        
        # Usar el mismo ejecutable de Python que esta corriendo el lab
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        python_exe = sys.executable
        sim_script = os.path.join(base_dir, "sim_3d.py")
        
        # Forzar X11 para la simulación también si es Linux
        env = os.environ.copy()
        if sys.platform == "linux" or sys.platform == "linux2":
            env["QT_X11_NO_MITSHM"] = "1"
            env["QT_QPA_PLATFORM"] = "xcb"

        try:
            self.sim_process = subprocess.Popen(
                [python_exe, sim_script, win_id, w, h],
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            self.ai_console.append(f">> Simulación lanzada en Window ID: {win_id}")
            
            # Hilo para leer logs de la simulación de forma no bloqueante (Compatible con Windows)
            self.log_thread = threading.Thread(target=self._log_reader_worker, args=(self.sim_process.stdout,), daemon=True)
            self.log_thread.start()

            # Timer para procesar la cola de logs en el hilo principal de la GUI
            self.log_timer = QTimer()
            self.log_timer.timeout.connect(self.read_sim_logs)
            self.log_timer.start(100)
        except Exception as e:
            self.ai_console.append(f">> ERROR al lanzar simulación: {e}")

    def _log_reader_worker(self, stdout):
        """Hilo secundario que lee el stdout del subproceso y lo mete en la cola."""
        try:
            for line in iter(stdout.readline, ''):
                if line:
                    self.log_queue.put(line)
                else:
                    break
        except Exception:
            pass
        finally:
            stdout.close()

    def read_sim_logs(self):
        """Procesa los logs acumulados en la cola y los muestra en la consola."""
        while not self.log_queue.empty():
            try:
                line = self.log_queue.get_nowait()
                # Sistema de colores dinámico según el tag
                line_str = line.strip()
                color = "white"
                
                if "[ERROR]" in line_str or "Error" in line_str:
                    color = "#ff4444" # Rojo
                elif "[WARN]" in line_str:
                    color = "#ffbb33" # Naranja
                elif "[INFO]" in line_str:
                    color = "#33b5e5" # Azul claro
                elif "[DEBUG]" in line_str:
                    color = "#aa66cc" # Púrpura
                elif "[CNC]" in line_str:
                    color = "#00cccc" # Cyan
                elif "[Sim]" in line_str:
                    color = "#999999" # Gris
                
                # Mostrar en consola si tiene algún tag o es importante
                tags = ["[INFO]", "[WARN]", "[DEBUG]", "[CNC]", "[ERROR]", "Error", "fail"]
                if any(tag in line_str for tag in tags) or line_str.startswith(">>"):
                    self.ai_console.append(f"<span style='color:{color};'>{line_str}</span>")
            except queue.Empty:
                break

    def toggle_arduino(self):
        if not self.comm.ser or not self.comm.ser.is_open:
            port = self.port_selector.currentText()
            if self.comm.connect_arduino(port):
                self.btn_connect.setText("DESCONECTAR")
                self.btn_connect.setStyleSheet("background-color: #c62828;")
        else:
            self.comm.ser.close()
            self.btn_connect.setText("CONECTAR ARDUINO")
            self.btn_connect.setStyleSheet("background-color: #2e7d32;")

    def on_connection_type_changed(self, index):
        """Alterna entre la visualización de los paneles de Serial y MQTT."""
        if index == 0:  # Serial
            self.serial_container.show()
            self.mqtt_container.hide()
        else:  # MQTT
            self.serial_container.hide()
            self.mqtt_container.show()

    def toggle_mqtt(self):
        """Conecta o desconecta la comunicación WiFi vía MQTT."""
        if not self.comm.mqtt_connected:
            broker = self.mqtt_broker_input.text().strip()
            port_str = self.mqtt_port_input.text().strip()
            topic = self.mqtt_topic_input.text().strip()
            
            if not broker or not port_str or not topic:
                self.ai_console.append("!! ERROR MQTT: Faltan campos por completar.")
                return
                
            try:
                port = int(port_str)
            except ValueError:
                self.ai_console.append("!! ERROR MQTT: Puerto inválido.")
                return
                
            self.ai_console.append(f">> [MQTT] Conectando a {broker}:{port}...")
            if self.comm.connect_mqtt(broker, port, topic):
                self.btn_connect_mqtt.setText("DESCONECTAR MQTT")
                self.btn_connect_mqtt.setStyleSheet("background-color: #c62828;")
                self.ai_console.append(">> [MQTT] Conectado exitosamente al broker.")
            else:
                self.ai_console.append("!! ERROR MQTT: No se pudo conectar al broker.")
        else:
            self.comm.disconnect_mqtt()
            self.btn_connect_mqtt.setText("CONECTAR MQTT")
            self.btn_connect_mqtt.setStyleSheet("background-color: #2e7d32; font-weight: bold;")
            self.ai_console.append(">> [MQTT] Desconectado del broker.")

    def open_mapper_dialog(self):
        """Abre la ventana premium de configuración de mandos."""
        # Desactivamos el bucle principal temporalmente para que no "robe" eventos
        # del dispositivo ni vacíe la cola mientras intentamos mapear.
        self.loop_timer.stop()
        
        dialog = InputMapperDialog(self.input_mgr, self)
        if dialog.exec():
            self.ai_console.append(">> [Input] Configuración de dispositivo actualizada.")
            
        self.loop_timer.start(16)

    def on_slider_change(self, index, value):
        """Maneja el movimiento manual de un slider."""
        self.current_angles[index] = float(value)
        self.angle_labels[index].setText(f"J{index}: {self.current_angles[index]:.1f}°")
        self.last_interaction_time = time.time() # Registrar interacción manual

    def load_fsm_library(self):
        """Carga el JSON de secuencias FSM del laboratorio."""
        if os.path.exists(self.fsm_file):
            try:
                with open(self.fsm_file, "r") as f:
                    self.all_fsm_data = json.load(f)
            except Exception as e:
                # Si ai_console no está listo aún, imprimir a consola
                print(f"[FSM] Error al cargar biblioteca: {e}")
        else:
            self.save_fsm_library()

    def save_fsm_library(self):
        """Guarda la biblioteca actual en el JSON."""
        try:
            with open(self.fsm_file, "w") as f:
                json.dump(self.all_fsm_data, f, indent=4)
        except Exception as e:
            print(f"[FSM] Error al guardar biblioteca: {e}")

    def import_from_main_gui(self):
        """Importa poses y animaciones del sistema principal al Lab."""
        try:
            root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            poses_path = os.path.join(root_dir, "poses.json")
            anims_path = os.path.join(root_dir, "animations.json")
            
            imported_count = 0
            
            if os.path.exists(poses_path):
                with open(poses_path, "r") as f:
                    main_poses = json.load(f)
                for name, angles in main_poses.items():
                    fsm_name = f"Pose_{name}"
                    if fsm_name not in self.all_fsm_data:
                        self.all_fsm_data[fsm_name] = {
                            "entry_state": "main",
                            "states": {
                                "main": { "pose": name, "angles": angles, "transition_time": 1.0, "transitions": [] }
                            }
                        }
                        imported_count += 1

            if os.path.exists(anims_path):
                with open(anims_path, "r") as f:
                    main_anims = json.load(f)
                with open(poses_path, "r") as f:
                    main_poses = json.load(f)

                for anim_name, steps in main_anims.items():
                    fsm_name = f"Seq_{anim_name}"
                    if fsm_name not in self.all_fsm_data:
                        states = {}
                        for i, step in enumerate(steps):
                            state_name = f"step_{i}"
                            pose_key = step["pose"]
                            angles = main_poses.get(pose_key, [0.0]*5)
                            next_state = f"step_{i+1}" if i < len(steps)-1 else None
                            states[state_name] = {
                                "pose": str(pose_key),
                                "angles": angles,
                                "transition_time": step.get("duration", 1.0),
                                "transitions": [
                                    {"type": "time", "params": step.get("duration", 1.0) + 1.0, "next": next_state}
                                ] if next_state else []
                            }
                        self.all_fsm_data[fsm_name] = { "entry_state": "step_0", "states": states }
                        imported_count += 1
            
            if imported_count > 0:
                self.save_fsm_library()
        except Exception as e:
            print(f"[FSM] Error en importación: {e}")

    def open_fsm_designer(self):
        """Lanza la ventana del Diseñador FSM."""
        try:
            from fsm_designer import FSMDesignerWindow
            if not hasattr(self, "fsm_designer_win") or not self.fsm_designer_win.isVisible():
                self.fsm_designer_win = FSMDesignerWindow(self) # Pasar 'self' para acceso a comm/sim
                self.fsm_designer_win.show()
            else:
                self.fsm_designer_win.raise_()
                self.fsm_designer_win.activateWindow()
        except ImportError as e:
            self.ai_console.append(f">> [Error] No se pudo cargar el Diseñador FSM: {e}")
        except Exception as e:
            self.ai_console.append(f">> [Error] Error al abrir Diseñador: {e}")

    def save_current_pose(self):
        """Guarda la posición actual en el archivo de poses."""
        try:
            poses_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "poses.json")
            poses = {}
            if os.path.exists(poses_path):
                with open(poses_path, "r") as f:
                    poses = json.load(f)
            
            pose_name = f"JoypadSnapshot_{int(time.time())}"
            poses[pose_name] = self.current_angles
            
            with open(poses_path, "w") as f:
                json.dump(poses, f, indent=4)
            print(f"[Lab] Pose guardada: {pose_name}")
        except Exception as e:
            print(f"[Lab] Error al guardar pose: {e}")

    def spawn_request(self):
        """Recoge los datos de la UI y solicita el spawn al sistema de comunicación."""
        obj_type = self.obj_type.currentText()
        size = self.obj_size.value()
        mass = self.obj_mass.value()
        
        model_path = None
        if obj_type == "custom...":
            if not self.custom_model_path:
                self.ai_console.append("!! ERROR: No se ha seleccionado un archivo para el spawn custom.")
                return
            obj_type = "custom"
            model_path = self.custom_model_path
        
        if obj_type == "svg":
            if hasattr(self, 'custom_svg_path') and self.custom_svg_path:
                self.ai_console.append(f">> [CNC] Cargando blueprint SVG: {os.path.basename(self.custom_svg_path)}")
                self.comm.load_svg(self.custom_svg_path)
            else:
                self.ai_console.append("!! ERROR: Primero selecciona un archivo SVG en el selector de arriba.")
            return

        self.ai_console.append(f">> [Spawn] Solicitando {obj_type} (S:{size}, M:{mass})")
        self.comm.spawn_object(obj_type, size, mass, model_path=model_path)


    def on_spawn_type_changed(self, index):
        """Maneja el cambio en el selector de tipo de objeto."""
        if self.obj_type.currentText() == "custom...":
            path, _ = QFileDialog.getOpenFileName(
                self, 
                "Seleccionar Modelo 3D", 
                os.path.dirname(os.path.dirname(__file__)), 
                "Modelos 3D (*.glb *.gltf *.obj)"
            )
            if path:
                self.custom_model_path = path
                filename = os.path.basename(path)
                self.ai_console.append(f">> [Spawn] Archivo cargado: {filename}")
            else:
                self.obj_type.setCurrentIndex(0)
                self.custom_model_path = None
        elif self.obj_type.currentText() == "svg":
            path, _ = QFileDialog.getOpenFileName(
                self, "Cargar Vector SVG", "", "Archivos SVG (*.svg)"
            )
            if path:
                self.custom_svg_path = path
                self.cnc_ctrl.set_svg_file(path)
                self.comm.load_svg(path)
                self.ai_console.append(f">> [CNC] SVG cargado: {os.path.basename(path)}")
            else:
                self.obj_type.setCurrentIndex(0)

    def keyPressEvent(self, event):
        """Captura teclas presionadas y las inyecta al sistema de entrada."""
        if not event.isAutoRepeat():
            self.input_mgr.inject_key_event(event.key(), True)
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        """Captura teclas soltadas y actualiza el sistema de entrada."""
        if not event.isAutoRepeat():
            self.input_mgr.inject_key_event(event.key(), False)
        super().keyReleaseEvent(event)

    def main_loop(self):
        # 1. Leer entradas de la simulación (Feedback) - Vaciado completo del buffer
        fb = self.comm.get_feedback()
        if fb:
            self.last_feedback = fb
            if fb.get("type") == "sync_angles":
                # damos un margen de 0.5 segundos tras la última interacción local
                if time.time() - self.last_interaction_time > 0.5:
                    angles = fb["data"]
                    self.sync_ui_from_sim(angles)
            elif fb.get("type") == "collision_status" and fb.get("colliding"):
                self.ai_console.append("!! ALERTA: Colisión detectada en simulación.")
            elif fb.get("type") == "cnc_status":
                status = fb.get("status", "")
                progress = fb.get("progress", 0)
                error_msg = fb.get("error")
                
                if status == "loaded":
                    self.cnc_ctrl.set_mode_positioning()
                    self.ai_console.append(">> [CNC] Blueprint cargado. Posiciona con Gizmo y presiona INICIAR.")
                elif status == "running":
                    self.cnc_ctrl.set_running(True)
                    self.cnc_ctrl.update_progress(progress)
                elif status == "completed":
                    self.cnc_ctrl.set_running(False)
                    self.cnc_ctrl.update_progress(100)
                    self.ai_console.append(">> [CNC] Trayectoria completada.")
                elif status == "stopped":
                    self.cnc_ctrl.set_running(False)
                    self.ai_console.append(">> [CNC] Trayectoria detenida.")
                elif status == "error":
                    self.cnc_ctrl.set_running(False)
                    self.ai_console.append(f"!! [CNC] Error: {error_msg}")

        # 2. Leer entradas de mandos (Necesario antes de la FSM para los triggers)
        joy_inputs, actions, camera_inputs = self.input_mgr.get_arm_inputs()

        # 3. Actualizar FSM si está activa
        if self.fsm.active and not self.fsm.is_paused:
            ext_inputs = {
                "keys": set(),
                "sensors": {
                    "collision": getattr(self, "last_feedback", {}).get("colliding", False)
                }
            }
            # Alimentar FSM con las acciones del mando
            if actions:
                for action_name, pressed in actions.items():
                    if pressed:
                        ext_inputs["keys"].add(action_name)
            
            fsm_angles = self.fsm.update(ext_inputs)
            self.current_angles = list(fsm_angles)
            # Notificar a la ventana del diseñador si está abierta
            if hasattr(self, "fsm_designer_win") and self.fsm_designer_win:
                self.fsm_designer_win.update_status_from_main()
            
            # Sincronizar Sliders visualmente sin disparar eventos redundantes
            for i in range(5):
                self.sliders[i].blockSignals(True)
                self.sliders[i].setValue(int(self.current_angles[i]))
                self.sliders[i].blockSignals(False)

        # UI status mando...
        if self.input_mgr.active_device_id == "KM":
            self.input_status.setText("Teclado: Activo")
            self.input_status.setStyleSheet("color: #4CAF50;")
        elif self.input_mgr.initialized and self.input_mgr.joystick:
            self.input_status.setText(f"Mando: {self.input_mgr.joystick.get_name()}")
            self.input_status.setStyleSheet("color: #4CAF50;")
        elif self.input_mgr.wiimote_active:
            self.input_status.setText("Wiimote: Activo")
            self.input_status.setStyleSheet("color: #4CAF50;")
        elif getattr(self.input_mgr, 'custom_evdev', None):
            self.input_status.setText(f"RAW: {self.input_mgr.custom_evdev.name}")
            self.input_status.setStyleSheet("color: #3f51b5;")
        elif self.input_mgr.active_category == "MIDI" and self.input_mgr._active_handler and self.input_mgr._active_handler.initialized:
            dev_name = getattr(self.input_mgr._active_handler, 'device_name', 'MIDI')
            self.input_status.setText(f"MIDI: {dev_name}")
            self.input_status.setStyleSheet("color: #e040fb;")
        elif self.input_mgr.active_category == "Serial" and self.input_mgr._active_handler and getattr(self.input_mgr._active_handler, 'initialized', False):
            self.input_status.setText(f"Serial: {self.input_mgr.active_device_id}")
            self.input_status.setStyleSheet("color: #ffab40;")
        else:
            self.input_status.setText("Mando: No detectado")
            self.input_status.setStyleSheet("color: #f44336;")

        # Aplicar deltas de mandos o posición absoluta para MIDI CC
        mando_movido = False
        if self.input_mgr.active_device_id:
            is_midi = (self.input_mgr.active_category == "MIDI")
            binds = self.input_mgr.get_current_binds().get("inputs", {})
            joint_names = ["base", "shoulder", "elbow", "j3", "j4"]

            # Obtener sensibilidad para los controles incrementales (por defecto 2.0)
            sens = self.input_mgr.get_current_binds().get("sensitivity", 2.0)

            # Control de los 5 ejes
            for i in range(min(len(joy_inputs), 5)):
                name_base = joint_names[i]
                pos_bind = binds.get(f"{name_base}_pos")
                neg_bind = binds.get(f"{name_base}_neg")

                # Los ejes de MIDI (CC) se tratan como absoluto.
                # Notas MIDI (botones) o gamepads/teclado se tratan como incremental.
                is_absolute = False
                if is_midi:
                    if (pos_bind and pos_bind.get("type") == "axis") or (neg_bind and neg_bind.get("type") == "axis"):
                        is_absolute = True

                if is_absolute:
                    # Evitar saltos/snap si el slider/knob físico no ha sido tocado aún
                    if self.input_mgr.is_joint_axis_touched(name_base):
                        target_angle = joy_inputs[i] * 90.0
                        target_angle = max(-90.0, min(90.0, target_angle))
                        if abs(self.current_angles[i] - target_angle) > 0.01:
                            self.current_angles[i] = target_angle
                            self.sliders[i].blockSignals(True)
                            self.sliders[i].setValue(int(self.current_angles[i]))
                            self.sliders[i].blockSignals(False)
                            mando_movido = True
                else:
                    if joy_inputs[i] != 0: 
                        self.current_angles[i] += joy_inputs[i] * sens
                        self.current_angles[i] = max(-90, min(90, self.current_angles[i]))
                        self.sliders[i].blockSignals(True)
                        self.sliders[i].setValue(int(self.current_angles[i]))
                        self.sliders[i].blockSignals(False)
                        mando_movido = True
            
            # Manejar Acciones Especiales (Snapshot, Console, Reset)
            if actions.get("snapshot") and not hasattr(self, "_last_joy_snapshot"):
                self.save_current_pose()
                self.ai_console.append(">> [Joypad] Pose guardada vía Snapshot.")
                self._last_joy_snapshot = True
            elif not actions.get("snapshot"):
                if hasattr(self, "_last_joy_snapshot"): del self._last_joy_snapshot
                
            if actions.get("toggle_console") and not hasattr(self, "_last_joy_console"):
                self.toggle_console()
                self._last_joy_console = True
            elif not actions.get("toggle_console"):
                if hasattr(self, "_last_joy_console"): del self._last_joy_console

            if actions.get("reset"):
                self.current_angles = [0.0] * 5
                for s in self.sliders: s.setValue(0)
                mando_movido = True

            # Manejar Binds Personalizados (Animaciones/Poses)
            if not hasattr(self, "_last_custom_fsm_states"):
                self._last_custom_fsm_states = {}
            
            for act_name, pressed in actions.items():
                if act_name.startswith("custom_fsm_"):
                    fsm_name = act_name[len("custom_fsm_"):]
                    was_pressed = self._last_custom_fsm_states.get(fsm_name, False)
                    if pressed and not was_pressed:
                        # Activar animación/pose
                        if fsm_name in self.all_fsm_data:
                            self.fsm.load_from_dict(self.all_fsm_data[fsm_name])
                            self.fsm.start()
                            self.ai_console.append(f">> [Input] Iniciando secuencia/pose: {fsm_name}")
                        else:
                            self.ai_console.append(f">> [Input] Secuencia/pose no encontrada: {fsm_name}")
                    self._last_custom_fsm_states[fsm_name] = pressed

            # Manejar Controles Estándar de Animaciones (Play/Pausa, Skips)
            if actions.get("fsm_play_pause") and not hasattr(self, "_last_fsm_play_pause"):
                if self.fsm.active:
                    self.fsm.toggle_pause()
                    self.ai_console.append(f">> [Input] Animación {'PAUSADA' if self.fsm.is_paused else 'REANUDADA'}")
                    if hasattr(self, "fsm_designer_win") and self.fsm_designer_win:
                        if self.fsm.is_paused:
                            self.fsm_designer_win.btn_play.setText("▶")
                            self.fsm_designer_win.btn_play.setStyleSheet("background-color: #2e7d32; border-radius: 30px;")
                        else:
                            self.fsm_designer_win.btn_play.setText("⏸")
                            self.fsm_designer_win.btn_play.setStyleSheet("background-color: #f57c00; border-radius: 30px;")
                self._last_fsm_play_pause = True
            elif not actions.get("fsm_play_pause"):
                if hasattr(self, "_last_fsm_play_pause"): del self._last_fsm_play_pause

            if actions.get("fsm_skip_forward") and not hasattr(self, "_last_fsm_skip_forward"):
                if self.fsm.active:
                    self.fsm.force_next()
                    self.ai_console.append(">> [Input] Animación Skip Adelante (Siguiente Frame)")
                self._last_fsm_skip_forward = True
            elif not actions.get("fsm_skip_forward"):
                if hasattr(self, "_last_fsm_skip_forward"): del self._last_fsm_skip_forward

            if actions.get("fsm_skip_backward") and not hasattr(self, "_last_fsm_skip_backward"):
                if self.fsm.active:
                    success = self.fsm.force_prev()
                    if success:
                        self.ai_console.append(">> [Input] Animación Skip Atrás (Frame Anterior)")
                    else:
                        self.ai_console.append(">> [Input] Animación Skip Atrás (No hay frames anteriores)")
                self._last_fsm_skip_backward = True
            elif not actions.get("fsm_skip_backward"):
                if hasattr(self, "_last_fsm_skip_backward"): del self._last_fsm_skip_backward

            # Control de cámara
            cam_moving = False
            cam_deltas = [0.0] * 7
            for i in range(len(camera_inputs)):
                if abs(camera_inputs[i]) > 0.05:
                    cam_deltas[i] = camera_inputs[i] * 0.15 # multiplier scale
                    cam_moving = True
            
            if cam_moving:
                self.comm.send_camera_offsets(cam_deltas)
        
        if mando_movido:
            self.last_interaction_time = time.time()

        # 3. ¿Debemos enviar ángulos a la simulación?
        # Eliminamos el timeout de 2.0s para que el mando RAW siempre tenga control
        if True: 
            diff = sum(abs(a - b) for a, b in zip(self.current_angles, self.last_sent_angles))
            if diff > 0.1:
                self.comm.send_angles(self.current_angles)
                self.last_sent_angles = list(self.current_angles)
                # Feedback visual en consola cada vez que el "Link" se activa
                # Limitamos a 2 veces por segundo para no saturar el render de Qt
                if mando_movido:
                    if not hasattr(self, "_last_link_log") or time.time() - self._last_link_log > 0.5:
                        self.ai_console.append(f"<span style='color:#7986CB;'>[Link] Mando -> Sim: {self.current_angles[0]:.1f}°...</span>")
                        self._last_link_log = time.time()
        
        # 4. Actualizar Labels (siempre para feedback visual)
        for i, val in enumerate(self.current_angles):
            self.angle_labels[i].setText(f"J{i}: {val:.1f}°")

    def sync_ui_from_sim(self, angles):
        """Actualiza mandos y UI basándose en la posición real de Ursina."""
        for i in range(min(len(angles), 5)):
            self.current_angles[i] = angles[i]
            self.sliders[i].blockSignals(True)
            self.sliders[i].setValue(int(angles[i]))
            self.sliders[i].blockSignals(False)
            self.angle_labels[i].setText(f"J{i}: {angles[i]:.1f}°")

    def closeEvent(self, event):
        """Garantiza la desconexión limpia de puertos y sockets al salir."""
        # Detener el bucle de refresco de Qt
        self.loop_timer.stop()
        if hasattr(self, 'log_timer'):
            self.log_timer.stop()
            
        # Cerrar Arduino Serial
        if self.comm.ser and self.comm.ser.is_open:
            try:
                self.comm.ser.close()
            except Exception:
                pass
                
        # Cerrar MQTT WiFi
        if getattr(self.comm, 'mqtt_connected', False):
            try:
                self.comm.disconnect_mqtt()
            except Exception:
                pass
                
        # Detener simulación Ursina
        if self.sim_process:
            try:
                self.sim_process.terminate()
            except Exception:
                pass
                
        super().closeEvent(event)

if __name__ == "__main__":
    if sys.platform == "linux" or sys.platform == "linux2":
        os.environ["QT_QPA_PLATFORM"] = "xcb"
    
    app = QApplication(sys.argv)
    window = ExperimentLabUI()
    window.show()
    sys.exit(app.exec())
